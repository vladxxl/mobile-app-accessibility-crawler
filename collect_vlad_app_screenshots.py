#!/usr/bin/env python3
"""
Collect Android emulator app screenshots through Play Store using adb/uiautomator.

The script intentionally does not accept, store, log, or type passwords.
When Google Play requires credentials, it pauses so the user can enter them
manually in the emulator.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


TARGET_AVD = os.environ.get("TARGET_AVD", "Medium Phone API 36.0")
GOOGLE_ACCOUNT = os.environ.get("GOOGLE_PLAY_ACCOUNT", "")
OUTPUT_DIR = Path("screenshots_vlad_apps")
APP_LIST = Path("apps_vlad.txt")
RUN_LOG = OUTPUT_DIR / "run_log.csv"

CSV_COLUMNS = [
    "app_name",
    "status",
    "package_name_if_found",
    "installed",
    "launched",
    "screenshots_taken",
    "blocker",
    "notes",
]

# Package hints speed up opening exact Play Store listings. The script still
# records blockers from Play Store UI if a hint is wrong, unavailable, or blocked.
PACKAGE_HINTS = {
    "Temu: Shop Like a Billionaire": "com.einnovation.temu",
    "CapCut - Video Editor": "com.lemon.lvoverseas",
    "Claude by Anthropic": "com.anthropic.claude",
    "Google Gemini": "com.google.android.apps.bard",
    "Shop: All your favorite brands": "com.shopify.arrive",
    "Paramount+": "com.cbs.app",
    "The Masters Golf Tournament": "com.ibm.events.android.masters",
    "Duolingo: Language & Chess": "com.duolingo",
    "Costco Wholesale": "com.costco.app.android",
    "Reddit": "com.reddit.frontpage",
    "MyChart": "epic.mychart.android",
    "Pandora - Music & Podcasts": "com.pandora.android",
}

BLOCKER_PATTERNS = {
    "unavailable": [
        "not available",
        "not found",
        "item not found",
        "try again",
        "something went wrong",
    ],
    "incompatible": [
        "not compatible",
        "not optimized for your device",
        "not work on your device",
    ],
    "paid": [
        "buy",
        "purchase",
        "payment method",
        "add a payment",
    ],
    "extra_verification": [
        "verify",
        "verification",
        "authentication is required",
        "requires authentication",
        "parental",
    ],
}

SAFE_NEGATIVE_LABELS = [
    "not now",
    "skip",
    "maybe later",
    "no thanks",
    "cancel",
    "dismiss",
    "close",
    "don't allow",
    "deny",
]

SAFE_PROGRESS_LABELS = [
    "continue",
    "get started",
    "start",
    "next",
    "accept",
    "agree",
    "i agree",
    "ok",
    "got it",
    "done",
    "later",
    "browse",
    "explore",
]

UNSAFE_LABELS = [
    "subscribe",
    "free trial",
    "start trial",
    "buy",
    "purchase",
    "upgrade",
    "post",
    "send",
    "message",
    "upload",
    "share",
    "pay",
    "payment",
    "add card",
    "create account",
    "sign up",
    "register",
]

LOGIN_LABELS = [
    "sign in",
    "log in",
    "login",
    "continue with google",
    "continue with apple",
    "email",
    "password",
]


@dataclass
class UiNode:
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def label(self) -> str:
        return " ".join(
            part for part in [self.text, self.content_desc, self.resource_id] if part
        ).strip()

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)


@dataclass
class AppResult:
    app_name: str
    status: str = "skipped"
    package_name_if_found: str = ""
    installed: bool = False
    launched: bool = False
    screenshots_taken: int = 0
    blocker: str = ""
    notes: str = ""


def safe_name(name: str) -> str:
    cleaned = name.lower()
    cleaned = cleaned.replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:90] or "app"


def normalize_avd_name(name: str) -> str:
    return re.sub(r"[\s_]+", "", name).lower()


def find_binary(name: str, relative: str) -> str | None:
    path = shutil_which(name)
    if path:
        return path

    candidates = []
    for env_name in ["ANDROID_HOME", "ANDROID_SDK_ROOT"]:
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / relative)
    candidates.append(Path.home() / "Library/Android/sdk" / relative)
    candidates.append(Path.home() / "Android/Sdk" / relative)

    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def shutil_which(name: str) -> str | None:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    for directory in paths:
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def run(
    cmd: list[str],
    *,
    timeout: int = 60,
    check: bool = False,
    text: bool = True,
) -> subprocess.CompletedProcess:
    printable = " ".join(shlex.quote(part) for part in cmd)
    print(f"$ {printable}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=text,
        timeout=timeout,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip(), file=sys.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed with exit {proc.returncode}: {printable}")
    return proc


class Android:
    def __init__(self, adb: str, emulator: str | None = None, serial: str | None = None):
        self.adb_path = adb
        self.emulator_path = emulator
        self.serial = serial

    def adb(self, args: list[str], *, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
        cmd = [self.adb_path]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return run(cmd, timeout=timeout, check=check)

    def adb_bytes(self, args: list[str], *, timeout: int = 60) -> bytes:
        cmd = [self.adb_path]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace")
            raise RuntimeError(f"adb failed: {' '.join(cmd)}\n{stderr}")
        return proc.stdout

    def shell(self, command: str, *, timeout: int = 60, check: bool = False) -> subprocess.CompletedProcess:
        return self.adb(["shell", command], timeout=timeout, check=check)

    def shell_text(self, command: str, *, timeout: int = 60) -> str:
        proc = self.shell(command, timeout=timeout)
        return proc.stdout or ""

    def tap(self, x: int, y: int) -> None:
        self.shell(f"input tap {x} {y}", timeout=15)
        time.sleep(0.8)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 400) -> None:
        self.shell(f"input swipe {x1} {y1} {x2} {y2} {duration_ms}", timeout=15)
        time.sleep(1.0)

    def keyevent(self, key: str) -> None:
        self.shell(f"input keyevent {shlex.quote(key)}", timeout=15)
        time.sleep(0.8)

    def wake(self) -> None:
        self.shell("input keyevent KEYCODE_WAKEUP", timeout=15)
        self.shell("wm dismiss-keyguard", timeout=15)

    def boot_completed(self) -> bool:
        out = self.shell_text("getprop sys.boot_completed", timeout=20).strip()
        return out == "1"

    def wait_for_boot(self, timeout_s: int = 240) -> None:
        deadline = time.time() + timeout_s
        self.adb(["wait-for-device"], timeout=timeout_s)
        while time.time() < deadline:
            if self.boot_completed():
                self.wake()
                return
            time.sleep(3)
        raise TimeoutError("Android did not report sys.boot_completed=1 in time.")

    def current_package(self) -> str:
        out = self.shell_text("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=20)
        match = re.search(r" ([a-zA-Z0-9_.]+)/", out)
        return match.group(1) if match else ""

    def is_package_installed(self, package: str) -> bool:
        if not package:
            return False
        proc = self.shell(f"pm path {shlex.quote(package)}", timeout=20)
        return proc.returncode == 0 and "package:" in (proc.stdout or "")

    def launch_package(self, package: str) -> bool:
        if not package:
            return False
        proc = self.shell(
            f"monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1",
            timeout=30,
        )
        time.sleep(4)
        return proc.returncode == 0

    def start_intent(self, uri: str) -> None:
        self.shell(
            "am start -a android.intent.action.VIEW -d " + shlex.quote(uri),
            timeout=30,
        )
        time.sleep(5)

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.adb_bytes(["exec-out", "screencap", "-p"], timeout=40)
        path.write_bytes(data)

    def dump_ui(self) -> list[UiNode]:
        self.shell("uiautomator dump /sdcard/window.xml >/dev/null", timeout=30)
        xml_data = self.adb_bytes(["exec-out", "cat", "/sdcard/window.xml"], timeout=30)
        root = ET.fromstring(xml_data.decode("utf-8", errors="replace"))
        nodes: list[UiNode] = []
        for elem in root.iter("node"):
            bounds = parse_bounds(elem.attrib.get("bounds", ""))
            if not bounds:
                continue
            nodes.append(
                UiNode(
                    text=elem.attrib.get("text", ""),
                    content_desc=elem.attrib.get("content-desc", ""),
                    resource_id=elem.attrib.get("resource-id", ""),
                    class_name=elem.attrib.get("class", ""),
                    clickable=elem.attrib.get("clickable", "false") == "true",
                    bounds=bounds,
                )
            )
        return nodes


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value)
    if not match:
        return None
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def visible_text(nodes: Iterable[UiNode]) -> str:
    return "\n".join(node.label for node in nodes if node.label).lower()


def find_clickable(nodes: list[UiNode], labels: list[str], *, exact: bool = False) -> UiNode | None:
    wanted = [label.lower() for label in labels]
    candidates = [node for node in nodes if node.clickable or node.class_name.endswith("Button")]
    for node in candidates:
        label = node.label.lower()
        if not label:
            continue
        if exact and label in wanted:
            return node
        if not exact and any(w in label for w in wanted):
            return node
    return None


def screen_has(nodes: list[UiNode], labels: list[str]) -> bool:
    text = visible_text(nodes)
    return any(label.lower() in text for label in labels)


def ensure_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not RUN_LOG.exists():
        with RUN_LOG.open("w", newline="") as fh:
            csv.DictWriter(fh, fieldnames=CSV_COLUMNS).writeheader()


def read_apps() -> list[str]:
    if not APP_LIST.exists():
        raise FileNotFoundError(f"Missing {APP_LIST}")
    apps = [line.strip() for line in APP_LIST.read_text().splitlines() if line.strip()]
    if not apps:
        raise ValueError(f"{APP_LIST} is empty")
    return apps


def append_log(result: AppResult) -> None:
    ensure_output()
    with RUN_LOG.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writerow(
            {
                "app_name": result.app_name,
                "status": result.status,
                "package_name_if_found": result.package_name_if_found,
                "installed": str(result.installed).lower(),
                "launched": str(result.launched).lower(),
                "screenshots_taken": result.screenshots_taken,
                "blocker": result.blocker,
                "notes": result.notes,
            }
        )


def detect_tools() -> tuple[str, str | None]:
    adb = find_binary("adb", "platform-tools/adb")
    emulator = find_binary("emulator", "emulator/emulator")
    if not adb:
        raise RuntimeError(
            "adb was not found. Install Android SDK platform-tools or set ANDROID_HOME."
        )
    return adb, emulator


def list_avds(emulator: str | None) -> list[str]:
    if not emulator:
        return []
    proc = run([emulator, "-list-avds"], timeout=30)
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def start_emulator_if_needed(android: Android, avd_name: str) -> None:
    devices = android.adb(["devices"], timeout=30).stdout or ""
    if re.search(r"^emulator-\d+\s+device$", devices, re.MULTILINE):
        print("An emulator is already connected.")
        return
    if not android.emulator_path:
        raise RuntimeError("emulator binary was not found.")
    print(f"Starting emulator AVD: {avd_name}")
    subprocess.Popen(
        [android.emulator_path, "-avd", avd_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def detect_only() -> int:
    adb, emulator = detect_tools()
    print(f"adb: {adb}")
    print(f"emulator: {emulator or 'not found'}")
    android = Android(adb, emulator)

    android.adb(["devices"], timeout=30)
    avds = list_avds(emulator)
    if avds:
        print("AVDs:")
        for avd in avds:
            marker = " (target)" if normalize_avd_name(avd) == normalize_avd_name(TARGET_AVD) else ""
            print(f"  {avd}{marker}")
    else:
        print("No AVDs returned by emulator -list-avds.")

    if not any(normalize_avd_name(avd) == normalize_avd_name(TARGET_AVD) for avd in avds):
        print(f"WARNING: target AVD not found by normalized name: {TARGET_AVD}")

    android.shell("getprop sys.boot_completed", timeout=20)
    return 0


def prepare_play_store(start: bool) -> int:
    adb, emulator = detect_tools()
    android = Android(adb, emulator)
    avds = list_avds(emulator)
    actual_avd = choose_avd(avds)
    if start:
        start_emulator_if_needed(android, actual_avd)
    android.wait_for_boot()
    android.wake()
    open_play_store(android)
    ensure_play_store_signed_in(android)
    return 0


def choose_avd(avds: list[str]) -> str:
    for avd in avds:
        if normalize_avd_name(avd) == normalize_avd_name(TARGET_AVD):
            return avd
    if TARGET_AVD in avds:
        return TARGET_AVD
    raise RuntimeError(f"Could not find target AVD {TARGET_AVD!r}. Found: {avds}")


def open_play_store(android: Android) -> None:
    android.shell(
        "monkey -p com.android.vending -c android.intent.category.LAUNCHER 1",
        timeout=30,
    )
    time.sleep(5)


def ensure_play_store_signed_in(android: Android) -> None:
    for _ in range(3):
        nodes = android.dump_ui()
        text = visible_text(nodes)
        if "sign in" not in text and "add account" not in text and "google account" not in text:
            print("Play Store appears reachable without a sign-in wall.")
            return
        print()
        print("Play Store appears to require sign-in.")
        if GOOGLE_ACCOUNT:
            print(f"Use Google account: {GOOGLE_ACCOUNT}")
        else:
            print("Use the Google Play test account assigned to your team.")
            print("Optional: set GOOGLE_PLAY_ACCOUNT to show the account name in this prompt.")
        print("Type the password and complete any 2FA manually in the emulator.")
        input("Press Enter here only after Play Store is signed in and ready...")
        time.sleep(3)
    nodes = android.dump_ui()
    if screen_has(nodes, ["sign in", "add account"]):
        raise RuntimeError("Play Store still appears to require sign-in.")


def open_listing(android: Android, app_name: str, package_hint: str) -> None:
    if package_hint:
        android.start_intent(f"market://details?id={package_hint}")
    else:
        android.start_intent(f"market://search?q={quote(app_name)}")
        nodes = android.dump_ui()
        listing = find_clickable(nodes, [app_name.split(":")[0], app_name.split("-")[0]])
        if listing:
            android.tap(*listing.center)
            time.sleep(3)


def classify_blocker(nodes: list[UiNode]) -> tuple[str, str]:
    text = visible_text(nodes)
    for status, patterns in BLOCKER_PATTERNS.items():
        for pattern in patterns:
            if pattern in text:
                return status, pattern
    return "", ""


def install_from_listing(android: Android, app_name: str, package_hint: str, result: AppResult) -> bool:
    if package_hint and android.is_package_installed(package_hint):
        result.installed = True
        return True

    for _ in range(4):
        nodes = android.dump_ui()
        blocker, pattern = classify_blocker(nodes)
        if blocker:
            result.status = "incompatible" if blocker == "incompatible" else "unavailable"
            if blocker == "paid":
                result.status = "skipped"
            result.blocker = blocker
            result.notes = f"Play Store text matched: {pattern}"
            return False

        open_button = find_clickable(nodes, ["open"], exact=True)
        if open_button:
            result.installed = True
            return True

        install_button = find_clickable(nodes, ["install"], exact=False)
        if install_button:
            android.tap(*install_button.center)
            return wait_for_install(android, package_hint, result)

        update_button = find_clickable(nodes, ["update"], exact=False)
        if update_button:
            android.tap(*update_button.center)
            return wait_for_install(android, package_hint, result)

        android.swipe(540, 1600, 540, 900, 300)

    result.status = "install_failed"
    result.blocker = "install_button_not_found"
    result.notes = "Could not find Install/Open on Play Store listing."
    return False


def wait_for_install(android: Android, package_hint: str, result: AppResult, timeout_s: int = 600) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        nodes = android.dump_ui()
        blocker, pattern = classify_blocker(nodes)
        if blocker == "extra_verification":
            result.status = "install_failed"
            result.blocker = "extra_verification"
            result.notes = f"Play Store text matched: {pattern}"
            return False
        if find_clickable(nodes, ["open"], exact=True):
            result.installed = True
            return True
        if package_hint and android.is_package_installed(package_hint):
            result.installed = True
            return True
        print("Waiting for install to finish...")
        time.sleep(8)

    result.status = "install_failed"
    result.blocker = "install_timeout"
    return False


def take_named_screenshot(android: Android, app_dir: Path, index: int, stem: str) -> int:
    android.screenshot(app_dir / f"{index:03d}_{stem}.png")
    return index + 1


def handle_permission_or_onboarding(android: Android, app_dir: Path, index: int) -> tuple[int, bool]:
    nodes = android.dump_ui()
    text = visible_text(nodes)
    changed = False

    if "permission controller" in android.current_package() or "allow" in text or "permission" in text:
        index = take_named_screenshot(android, app_dir, index, "permission_dialog")
        deny = find_clickable(nodes, ["don't allow", "deny", "not now"])
        if deny:
            android.tap(*deny.center)
            changed = True
            return index, changed
        allow_basic = find_clickable(nodes, ["while using the app", "allow notifications", "allow"])
        if allow_basic:
            android.tap(*allow_basic.center)
            changed = True
            return index, changed

    negative = find_clickable(nodes, SAFE_NEGATIVE_LABELS)
    if negative:
        android.tap(*negative.center)
        changed = True
        return index, changed

    progress = find_clickable(nodes, SAFE_PROGRESS_LABELS)
    if progress and not has_unsafe_label(progress):
        android.tap(*progress.center)
        changed = True

    return index, changed


def has_unsafe_label(node: UiNode) -> bool:
    label = node.label.lower()
    return any(term in label for term in UNSAFE_LABELS)


def is_login_wall(nodes: list[UiNode]) -> bool:
    text = visible_text(nodes)
    return any(label in text for label in LOGIN_LABELS) and not any(
        label in text for label in ["home", "search", "explore", "browse"]
    )


def collect_app_screens(android: Android, app_name: str, app_dir: Path, max_extra: int) -> tuple[int, str, str]:
    index = 2
    index = take_named_screenshot(android, app_dir, index, "first_launch")

    for _ in range(5):
        index, changed = handle_permission_or_onboarding(android, app_dir, index)
        if not changed:
            break
        time.sleep(2)

    nodes = android.dump_ui()
    if is_login_wall(nodes):
        index = take_named_screenshot(android, app_dir, index, "login_required")
        return index - 1, "login_required", "App requires sign-in before main screen."

    index = take_named_screenshot(android, app_dir, index, "home_screen")

    seen_labels: set[str] = set()
    extra_count = 0
    for _ in range(max_extra * 3):
        if extra_count >= max_extra:
            break
        nodes = android.dump_ui()
        candidates = safe_navigation_candidates(nodes, seen_labels)
        if not candidates:
            android.swipe(540, 1700, 540, 800, 400)
            time.sleep(1)
            candidates = safe_navigation_candidates(android.dump_ui(), seen_labels)
            if not candidates:
                break
        node = candidates[0]
        seen_labels.add(node.label.lower())
        android.tap(*node.center)
        time.sleep(2)
        index = take_named_screenshot(android, app_dir, index, f"screen_{extra_count + 1}")
        extra_count += 1

    status = "completed" if extra_count >= 3 else "partially_completed"
    note = f"Captured {extra_count} additional screens."
    return index - 1, status, note


def safe_navigation_candidates(nodes: list[UiNode], seen_labels: set[str]) -> list[UiNode]:
    candidates: list[UiNode] = []
    preferred = [
        "home",
        "search",
        "explore",
        "browse",
        "for you",
        "categories",
        "profile",
        "library",
        "shows",
        "shop",
        "cart",
        "settings",
        "notifications",
    ]
    for node in nodes:
        label = node.label.lower()
        if not label or label in seen_labels:
            continue
        if not (node.clickable or "button" in node.class_name.lower()):
            continue
        if has_unsafe_label(node):
            continue
        x1, y1, x2, y2 = node.bounds
        if (x2 - x1) < 24 or (y2 - y1) < 24:
            continue
        if any(term in label for term in preferred):
            candidates.append(node)
    return candidates


def process_app(android: Android, app_name: str, max_extra: int) -> AppResult:
    result = AppResult(app_name=app_name)
    package_hint = PACKAGE_HINTS.get(app_name, "")
    result.package_name_if_found = package_hint
    app_dir = OUTPUT_DIR / safe_name(app_name)
    app_dir.mkdir(parents=True, exist_ok=True)
    index = 1

    print(f"\n=== {app_name} ===")
    open_listing(android, app_name, package_hint)
    index = take_named_screenshot(android, app_dir, index, "play_store_listing")

    if not install_from_listing(android, app_name, package_hint, result):
        result.screenshots_taken = index - 1
        return result

    launched = False
    if package_hint:
        launched = android.launch_package(package_hint)
    if not launched:
        nodes = android.dump_ui()
        open_button = find_clickable(nodes, ["open"], exact=True)
        if open_button:
            android.tap(*open_button.center)
            launched = True
            time.sleep(4)

    result.launched = launched
    if not launched:
        result.status = "launch_failed"
        result.blocker = "could_not_launch"
        result.screenshots_taken = index - 1
        return result

    screenshots, status, note = collect_app_screens(android, app_name, app_dir, max_extra)
    result.screenshots_taken = screenshots
    result.status = status
    if status == "login_required":
        result.blocker = "login_required"
    result.notes = note
    return result


def run_collection(args: argparse.Namespace) -> int:
    ensure_output()
    adb, emulator = detect_tools()
    android = Android(adb, emulator)
    avds = list_avds(emulator)
    actual_avd = choose_avd(avds)
    if args.start_emulator:
        start_emulator_if_needed(android, actual_avd)
    android.wait_for_boot()
    android.wake()
    open_play_store(android)
    ensure_play_store_signed_in(android)

    apps = read_apps()
    if args.only:
        wanted = {name.strip().lower() for name in args.only}
        apps = [app for app in apps if app.lower() in wanted]
    if args.start_at:
        try:
            start_index = [app.lower() for app in apps].index(args.start_at.lower())
            apps = apps[start_index:]
        except ValueError:
            raise ValueError(f"--start-at app not found in list: {args.start_at}")

    for app_name in apps:
        try:
            result = process_app(android, app_name, args.max_extra_screens)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            result = AppResult(
                app_name=app_name,
                status="partially_completed",
                blocker=type(exc).__name__,
                notes=str(exc),
            )
        append_log(result)
        android.keyevent("KEYCODE_HOME")
        time.sleep(2)

    summarize_log()
    return 0


def summarize_log() -> None:
    if not RUN_LOG.exists():
        return
    rows = list(csv.DictReader(RUN_LOG.open()))
    latest = rows[-len(read_apps()) :] if rows else []
    counts: dict[str, int] = {}
    for row in latest:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("\nSummary for most recent logged rows:")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")
    for row in latest:
        print(f"  {row['app_name']}: {row['screenshots_taken']} screenshots, {row['status']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--detect-only", action="store_true", help="Run safe ADB/AVD/boot checks only.")
    mode.add_argument("--prepare-play-store", action="store_true", help="Boot emulator and verify Play Store login.")
    mode.add_argument("--run", action="store_true", help="Install apps and collect screenshots.")
    parser.add_argument("--no-start-emulator", dest="start_emulator", action="store_false")
    parser.set_defaults(start_emulator=True)
    parser.add_argument("--start-at", help="Start processing at an app name from apps_vlad.txt.")
    parser.add_argument("--only", action="append", help="Process only this app name. Can be repeated.")
    parser.add_argument("--max-extra-screens", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.detect_only:
        return detect_only()
    if args.prepare_play_store:
        return prepare_play_store(start=args.start_emulator)
    if args.run:
        return run_collection(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
