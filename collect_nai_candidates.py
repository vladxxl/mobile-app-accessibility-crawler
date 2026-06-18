#!/usr/bin/env python3
"""Collect NAI candidate frames from Vlad's installed Android apps."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from nai_shared import (
    BLOCKER_LABELS,
    NAI_ISSUES,
    OUTPUT_ROOT,
    SAFE_NEGATIVE_LABELS,
    SAFE_PROGRESS_LABELS,
    UNSAFE_LABELS,
    AppSpec,
    build_manifest,
    validate_installed_manifest,
)


ADB = os.environ.get("ADB", str(Path.home() / "Library/Android/sdk/platform-tools/adb"))
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5554")
RUN_LOG = OUTPUT_ROOT / "collection_run_log.csv"
ACCEPTED_FOCUS_PACKAGES = {
    "com.google.android.apps.bard": {"com.google.android.apps.bard", "com.google.android.googlequicksearchbox"},
}


@dataclass
class UiNode:
    text: str
    content_desc: str
    resource_id: str
    class_name: str
    clickable: bool
    enabled: bool
    focused: bool
    scrollable: bool
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

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bounds
        return max(0, x2 - x1) * max(0, y2 - y1)


@dataclass
class Capture:
    app_name: str
    package_name: str
    category: str
    file_stem: str
    png_path: str
    xml_path: str
    metadata_path: str
    current_package: str
    current_activity: str
    action_path: str
    suspected_issue: str
    issue_definition: str
    confidence: str
    notes: str
    image_sha256: str
    ui_sha256: str
    timestamp: float
    keep_delete: str = ""


def run(args: list[str], timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}\n{proc.stderr}")
    return proc


def adb(args: list[str], timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess:
    return run([ADB, "-s", SERIAL, *args], timeout=timeout, check=check)


def adb_bytes(args: list[str], timeout: int = 30) -> bytes:
    proc = subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    return proc.stdout


def shell(command: str, timeout: int = 30, check: bool = False) -> subprocess.CompletedProcess:
    return adb(["shell", command], timeout=timeout, check=check)


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value)
    if not match:
        return None
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def boot_ready() -> bool:
    try:
        return shell("getprop sys.boot_completed", timeout=10).stdout.strip() == "1"
    except Exception:
        return False


def installed(package: str) -> bool:
    try:
        return "package:" in shell(f"pm path {package}", timeout=12).stdout
    except Exception:
        return False


def current_focus() -> tuple[str, str]:
    out = shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=15).stdout
    match = re.search(r" ([a-zA-Z0-9_.]+)/([a-zA-Z0-9_.$]+)", out)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def focus_matches(expected_package: str, current_package: str) -> bool:
    accepted = ACCEPTED_FOCUS_PACKAGES.get(expected_package, {expected_package})
    return current_package in accepted


def resolve_launcher_activity(package: str) -> str | None:
    proc = shell(f"cmd package resolve-activity --brief {package}", timeout=15)
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        if "/" in line and line.startswith(package):
            return line
    return None


def launch_package(package: str) -> None:
    shell("input keyevent KEYCODE_WAKEUP", timeout=10)
    shell("wm dismiss-keyguard", timeout=10)
    launcher = resolve_launcher_activity(package)
    for attempt in range(4):
        if launcher:
            shell(f"am start -n {launcher}", timeout=25)
        else:
            shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", timeout=25)
        time.sleep(4)
        current_package, current_activity = current_focus()
        if focus_matches(package, current_package):
            return
        if current_package == "com.google.android.permissioncontroller":
            shell("input keyevent KEYCODE_BACK", timeout=10)
            time.sleep(1)
            continue
        if attempt == 1:
            shell("input keyevent KEYCODE_HOME", timeout=10)
            time.sleep(1)
    current_package, current_activity = current_focus()
    if not focus_matches(package, current_package):
        raise RuntimeError(f"Launch failed: focused {current_package}/{current_activity}, expected {package}")


def parse_ui_xml(xml_text: str) -> list[UiNode]:
    nodes: list[UiNode] = []
    root = ET.fromstring(xml_text)
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
                enabled=elem.attrib.get("enabled", "false") == "true",
                focused=elem.attrib.get("focused", "false") == "true",
                scrollable=elem.attrib.get("scrollable", "false") == "true",
                bounds=bounds,
            )
        )
    return nodes


def dump_ui() -> tuple[str, list[UiNode]]:
    shell("uiautomator dump /sdcard/window.xml >/dev/null", timeout=30)
    xml_text = adb_bytes(["exec-out", "cat", "/sdcard/window.xml"], timeout=30).decode(
        "utf-8", errors="replace"
    )
    return xml_text, parse_ui_xml(xml_text)


def text_blob(nodes: Iterable[UiNode]) -> str:
    return "\n".join(node.label for node in nodes if node.label).lower()


def has_any(text: str, labels: Iterable[str]) -> bool:
    low = text.lower()
    return any(label.lower() in low for label in labels)


def node_is_unsafe(node: UiNode) -> bool:
    label = compact_label(node).lower().replace("_", " ")
    return any(term in label for term in UNSAFE_LABELS)


def tap(node: UiNode) -> None:
    x, y = node.center
    shell(f"input tap {x} {y}", timeout=10)
    time.sleep(2)


def swipe_up() -> None:
    shell("input swipe 540 1780 540 650 450", timeout=12)
    time.sleep(1.5)


def key_back() -> None:
    shell("input keyevent KEYCODE_BACK", timeout=10)
    time.sleep(1.2)


def image_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ui_hash(xml_text: str) -> str:
    normalized = re.sub(r"\s+", " ", xml_text)
    return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()


def issue_for_screen(nodes: list[UiNode], action_path: str, previous_ui_hash: str | None = None) -> tuple[str, str, str]:
    blob = text_blob(nodes)
    edit_nodes = [node for node in nodes if "edittext" in node.class_name.lower()]
    unlabeled_clickables = [
        node
        for node in nodes
        if node.clickable and not node.text and not node.content_desc and node.area >= 500
    ]
    title_candidates = [
        node
        for node in nodes
        if node.text and not node.clickable and node.bounds[1] < 420 and len(node.text.strip()) >= 3
    ]
    nav_labels = ["home", "search", "profile", "settings", "apps", "books", "games", "for you"]
    if edit_nodes and not any(word in blob for word in ["search", "email", "password", "name", "phone"]):
        return issue_tuple("Missing or Unclear Input Purpose", "medium", "Input field present with weak visible purpose signals.")
    if unlabeled_clickables:
        return issue_tuple("Unclear Icon/Button Purpose", "medium", "Clickable unlabeled/icon-only controls detected.")
    if "scroll_after" in action_path:
        return issue_tuple("Disappearing View Identifier", "medium", "Scroll-after frame collected to compare title/navigation persistence.")
    if "detail" in action_path or "result" in action_path:
        return issue_tuple("View Inconsistency", "low", "Detail/list frame collected for manual comparison against similar views.")
    if not title_candidates and not any(label in blob for label in nav_labels):
        return issue_tuple("No View Identifier", "medium", "No obvious top title or common active navigation text detected.")
    if previous_ui_hash and previous_ui_hash != ui_hash_from_nodes(nodes):
        return issue_tuple("Icon/Button Inconsistency", "low", "Post-interaction frame collected for control/function comparison.")
    return issue_tuple("Unclear Icon/Button Purpose", "low", "General candidate frame with controls requiring manual review.")


def issue_tuple(issue: str, confidence: str, notes: str) -> tuple[str, str, str]:
    return issue, confidence, notes


def ui_hash_from_nodes(nodes: list[UiNode]) -> str:
    compact = "|".join(f"{node.class_name}:{node.label}:{node.bounds}" for node in nodes)
    return hashlib.sha256(compact.encode("utf-8", errors="replace")).hexdigest()


def capture_frame(
    spec: AppSpec,
    app_dir: Path,
    index: int,
    action_path: str,
    notes: str = "",
    previous_ui_hash: str | None = None,
) -> Capture:
    xml_text, nodes = dump_ui()
    # `adb exec-out screencap -p` already returns a valid binary PNG stream.
    # Rewriting CRLF bytes corrupts PNG chunk data and makes Preview unable to open it.
    png_bytes = adb_bytes(["exec-out", "screencap", "-p"], timeout=30)
    current_package, current_activity = current_focus()
    issue, confidence, issue_notes = issue_for_screen(nodes, action_path, previous_ui_hash)
    stem = f"{index:03d}_{slug(action_path)}"
    png_path = app_dir / f"{stem}.png"
    xml_path = app_dir / f"{stem}.xml"
    metadata_path = app_dir / f"{stem}.json"
    png_path.write_bytes(png_bytes)
    xml_path.write_text(xml_text)
    capture = Capture(
        app_name=spec.app_name,
        package_name=spec.package_name,
        category=spec.category,
        file_stem=stem,
        png_path=str(png_path.relative_to(OUTPUT_ROOT)),
        xml_path=str(xml_path.relative_to(OUTPUT_ROOT)),
        metadata_path=str(metadata_path.relative_to(OUTPUT_ROOT)),
        current_package=current_package,
        current_activity=current_activity,
        action_path=action_path,
        suspected_issue=issue,
        issue_definition=NAI_ISSUES[issue]["short_definition"],
        confidence=confidence,
        notes="; ".join(part for part in [notes, issue_notes] if part),
        image_sha256=image_hash(png_bytes),
        ui_sha256=ui_hash(xml_text),
        timestamp=time.time(),
    )
    metadata_path.write_text(json.dumps(asdict(capture), indent=2) + "\n")
    return capture


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower())
    return re.sub(r"_+", "_", cleaned).strip("_")[:70] or "screen"


def find_nodes(nodes: list[UiNode], terms: Iterable[str]) -> list[UiNode]:
    wanted = [term.lower() for term in terms]
    found = []
    for node in nodes:
        label = node.label.lower()
        if not label or not node.enabled:
            continue
        if any(term in label for term in wanted):
            found.append(node)
    return found


def expand_terms(terms: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for term in terms:
        for part in re.split(r"[^a-zA-Z0-9]+", term):
            part = part.strip().lower()
            if len(part) >= 3:
                expanded.append(part)
        expanded.append(term.lower())
    return list(dict.fromkeys(expanded))


def compact_label(node: UiNode) -> str:
    label = node.label.strip()
    if label:
        return label
    if node.resource_id:
        return node.resource_id.rsplit("/", 1)[-1].replace("_", " ")
    return f"{node.class_name.rsplit('.', 1)[-1]}_{node.bounds}"


def node_is_clickable_control(node: UiNode) -> bool:
    class_low = node.class_name.lower()
    return node.enabled and (
        node.clickable
        or "button" in class_low
        or "tab" in class_low
        or "imagebutton" in class_low
        or "textview" in class_low
    )


def node_region_score(node: UiNode) -> int:
    x1, y1, x2, y2 = node.bounds
    width = max(1, x2 - x1)
    score = 0
    if y1 >= 1450:
        score += 80
    if y2 <= 360:
        score += 55
    if width >= 180 and y1 < 1300:
        score += 20
    if width >= 220 and 360 <= y1 <= 1750:
        score += 25
    return score


def safe_click_candidates(nodes: list[UiNode], spec: AppSpec, seen: set[str]) -> list[tuple[str, UiNode]]:
    category_terms = {
        "shopping": ["search", "category", "shop", "deals", "product", "home"],
        "shopping_tracking": ["search", "shop", "stores", "track", "orders", "home"],
        "shopping_membership": ["search", "shop", "warehouse", "categories", "home"],
        "streaming": ["home", "search", "shows", "movies", "episodes", "watch", "browse"],
        "music": ["search", "browse", "stations", "podcasts", "genres", "library"],
        "ai_chat": ["settings", "search", "help", "prompt", "examples", "account"],
        "ai_character_chat": ["search", "discover", "characters", "filters", "profile"],
        "utility_cleaner": ["tools", "settings", "scan", "storage", "dashboard", "permission"],
        "sports_info": ["leaderboard", "schedule", "news", "players", "course", "watch"],
        "education": ["courses", "language", "lesson", "profile", "practice", "settings"],
        "social_feed": ["search", "popular", "communities", "home", "profile", "comments"],
        "health": ["provider", "search", "login", "help", "sign in", "forgot"],
        "creative_media": ["templates", "edit", "tools", "effects", "settings", "new project"],
        "account_offers": ["offers", "home", "account", "benefits", "settings", "search"],
    }
    preferred = category_terms.get(spec.category, []) + [
        "home",
        "search",
        "settings",
        "profile",
        "explore",
        "browse",
        "categories",
        "help",
    ]
    preferred = expand_terms(preferred + spec.targets)
    candidates: list[tuple[int, str, UiNode]] = []
    for node in nodes:
        label = compact_label(node)
        label_low = label.lower()
        if not label or label_low in seen:
            continue
        if not node_is_clickable_control(node):
            continue
        if node_is_unsafe(node):
            continue
        if node.area < 600:
            continue
        if node.bounds[3] - node.bounds[1] > 900:
            continue
        score = node_region_score(node)
        matched_preferred = any(term in label_low for term in preferred)
        if spec.category in {"shopping", "shopping_tracking", "shopping_membership"} and not matched_preferred:
            continue
        if matched_preferred:
            score += 100
        if node.clickable:
            score += 10
        if score >= 25:
            candidates.append((score, label, node))
    candidates.sort(key=lambda item: (-item[0], item[2].bounds[1], item[2].bounds[0]))
    return [(label, node) for _, label, node in candidates[:10]]


def capture_current_blocker(
    spec: AppSpec,
    app_dir: Path,
    index: int,
    blockers: list[str],
    captures: list[Capture],
) -> int:
    _, nodes = dump_ui()
    blocker = likely_blocked(nodes)
    if blocker and blocker not in blockers:
        blockers.append(blocker)
        captures.append(capture_frame(spec, app_dir, index, f"blocker_{blocker}"))
        return index + 1
    return index


def return_to_app_home(package_name: str) -> None:
    for _ in range(2):
        current_package, _ = current_focus()
        if not focus_matches(package_name, current_package):
            launch_package(package_name)
            return
        key_back()
    current_package, _ = current_focus()
    if not focus_matches(package_name, current_package):
        launch_package(package_name)


def handle_initial_dialogs(spec: AppSpec, app_dir: Path, start_index: int, captures: list[Capture]) -> int:
    index = start_index
    for attempt in range(5):
        xml_text, nodes = dump_ui()
        blob = text_blob(nodes)
        if has_any(blob, ["permission", "allow", "notifications", "location"]):
            captures.append(capture_frame(spec, app_dir, index, f"permission_or_system_dialog_{attempt+1}"))
            index += 1
        negative = find_nodes(nodes, SAFE_NEGATIVE_LABELS)
        if negative:
            tap(negative[0])
            continue
        progress = [node for node in find_nodes(nodes, SAFE_PROGRESS_LABELS) if not node_is_unsafe(node)]
        if progress:
            tap(progress[0])
            continue
        break
    return index


def likely_blocked(nodes: list[UiNode]) -> str:
    blob = text_blob(nodes)
    if has_any(blob, BLOCKER_LABELS):
        if has_any(blob, ["subscribe", "trial", "payment"]):
            return "subscription_or_payment_gate"
        if has_any(blob, ["sign in", "log in", "login", "create account", "register"]):
            return "login_or_account_gate"
        return "verification_or_gate"
    return ""


def collect_app(spec: AppSpec, min_frames: int, max_frames: int) -> dict[str, object]:
    app_dir = OUTPUT_ROOT / "apps" / spec.safe_name
    app_dir.mkdir(parents=True, exist_ok=True)
    for stale in app_dir.glob("*"):
        if stale.suffix.lower() in {".png", ".xml", ".json"}:
            stale.unlink()
    captures: list[Capture] = []
    seen_labels: set[str] = set()
    blockers: list[str] = []

    launch_package(spec.package_name)
    index = 1
    captures.append(capture_frame(spec, app_dir, index, "first_launch", "Initial app launch."))
    index += 1
    index = handle_initial_dialogs(spec, app_dir, index, captures)
    index = len(captures) + 1

    captures.append(capture_frame(spec, app_dir, index, "home_or_current_view"))
    index += 1
    index = capture_current_blocker(spec, app_dir, index, blockers, captures)

    target_terms = expand_terms(spec.targets + ["search", "settings", "profile", "home", "browse"])
    for term in target_terms:
        if len(captures) >= max_frames:
            break
        xml_text, nodes = dump_ui()
        index = capture_current_blocker(spec, app_dir, index, blockers, captures)
        candidates = [
            node
            for node in find_nodes(nodes, [term])
            if node_is_clickable_control(node) and not node_is_unsafe(node)
        ]
        if not candidates:
            continue
        seen_labels.add(compact_label(candidates[0]).lower())
        tap(candidates[0])
        cap = capture_frame(spec, app_dir, index, f"target_{term}")
        captures.append(cap)
        index += 1
        _, inner_nodes = dump_ui()
        inner = safe_click_candidates(inner_nodes, spec, seen_labels)
        if inner and len(captures) < max_frames:
            inner_label, inner_node = inner[0]
            seen_labels.add(inner_label.lower())
            tap(inner_node)
            captures.append(capture_frame(spec, app_dir, index, f"target_{term}_inner_{slug(inner_label)}"))
            index += 1
        return_to_app_home(spec.package_name)

    no_progress_rounds = 0
    scroll_reveals = 0
    while len(captures) < max_frames and no_progress_rounds < 14:
        xml_text, nodes = dump_ui()
        index = capture_current_blocker(spec, app_dir, index, blockers, captures)
        candidates = safe_click_candidates(nodes, spec, seen_labels)
        if not candidates:
            if scroll_reveals >= 6:
                break
            previous = captures[-1].ui_sha256 if captures else None
            swipe_up()
            no_progress_rounds += 1
            scroll_reveals += 1
            cap = capture_frame(
                spec,
                app_dir,
                index,
                f"reveal_more_controls_scroll_{scroll_reveals}",
                previous_ui_hash=previous,
            )
            captures.append(cap)
            index += 1
            continue
        label, node = candidates[0]
        seen_labels.add(label.lower())
        tap(node)
        captures.append(capture_frame(spec, app_dir, index, f"menu_or_view_{slug(label)}"))
        index += 1
        no_progress_rounds = 0
        _, branch_nodes = dump_ui()
        branch_candidates = safe_click_candidates(branch_nodes, spec, seen_labels)
        if branch_candidates and len(captures) < max_frames:
            branch_label, branch_node = branch_candidates[0]
            seen_labels.add(branch_label.lower())
            tap(branch_node)
            captures.append(
                capture_frame(spec, app_dir, index, f"menu_or_view_{slug(label)}_inner_{slug(branch_label)}")
            )
            index += 1
        return_to_app_home(spec.package_name)
    shell("input keyevent KEYCODE_HOME", timeout=10)
    return {
        "app_name": spec.app_name,
        "package_name": spec.package_name,
        "frames": len(captures),
        "blockers": ";".join(blockers),
        "status": "completed" if len(captures) >= min_frames else "partial",
        "app_dir": str(app_dir.relative_to(OUTPUT_ROOT)),
    }


def write_index() -> None:
    metadata_files = sorted((OUTPUT_ROOT / "apps").glob("*/*.json"))
    items = []
    for path in metadata_files:
        try:
            item = json.loads(path.read_text())
        except Exception:
            continue
        if "png_path" in item:
            items.append(item)
    (OUTPUT_ROOT / "candidates_index.json").write_text(json.dumps(items, indent=2) + "\n")


def write_log(rows: list[dict[str, object]]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["app_name", "package_name", "status", "frames", "blockers", "app_dir"]
        )
        writer.writeheader()
        writer.writerows(rows)


def existing_frame_count(spec: AppSpec) -> int:
    app_dir = OUTPUT_ROOT / "apps" / spec.safe_name
    return len(list(app_dir.glob("*.png")))


def select_specs(only: list[str] | None, limit: int | None) -> list[AppSpec]:
    specs = validate_installed_manifest()
    if only:
        wanted = {name.lower() for name in only}
        specs = [spec for spec in specs if spec.app_name.lower() in wanted or spec.safe_name.lower() in wanted]
    if limit:
        specs = specs[:limit]
    return specs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", action="append", help="Exact app name or safe name to crawl. Can repeat.")
    parser.add_argument("--limit", type=int, help="Limit to the first N apps from apps_vlad.txt.")
    parser.add_argument("--min-frames", type=int, default=10)
    parser.add_argument("--max-frames", type=int, default=22)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Skip apps that already have min-frames PNGs.")
    args = parser.parse_args()

    if not boot_ready():
        raise SystemExit("Emulator is not booted or ADB is not responsive.")
    specs = select_specs(args.only, args.limit)
    missing = [spec.package_name for spec in specs if not installed(spec.package_name)]
    if missing:
        raise SystemExit("Missing installed packages: " + ", ".join(missing))
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUTPUT_ROOT / "apps").mkdir(exist_ok=True)
    if args.preflight_only:
        print(f"Preflight OK: {len(specs)} app(s), emulator booted, packages installed.")
        return 0
    rows = []
    for spec in specs:
        if not boot_ready():
            write_log(rows)
            write_index()
            raise SystemExit("ADB/emulator disconnected; stop now and rerun with --resume after restarting it.")
        if args.resume and existing_frame_count(spec) >= args.min_frames:
            row = {
                "app_name": spec.app_name,
                "package_name": spec.package_name,
                "frames": existing_frame_count(spec),
                "blockers": "",
                "status": "skipped_existing",
                "app_dir": str((OUTPUT_ROOT / "apps" / spec.safe_name).relative_to(OUTPUT_ROOT)),
            }
            rows.append(row)
            print(f"\n=== {spec.app_name} ({spec.package_name}) ===", flush=True)
            print(f"skipped_existing: {row['frames']} frames", flush=True)
            continue
        print(f"\n=== {spec.app_name} ({spec.package_name}) ===", flush=True)
        try:
            row = collect_app(spec, args.min_frames, args.max_frames)
        except Exception as exc:
            row = {
                "app_name": spec.app_name,
                "package_name": spec.package_name,
                "frames": 0,
                "blockers": type(exc).__name__,
                "status": "error",
                "app_dir": str((OUTPUT_ROOT / "apps" / spec.safe_name).relative_to(OUTPUT_ROOT)),
            }
            print(f"ERROR: {type(exc).__name__}: {exc}", flush=True)
        rows.append(row)
        print(f"{row['status']}: {row['frames']} frames blockers={row['blockers']}", flush=True)
    write_log(rows)
    write_index()
    print(f"\nWrote {RUN_LOG}")
    print(f"Wrote {OUTPUT_ROOT / 'candidates_index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
