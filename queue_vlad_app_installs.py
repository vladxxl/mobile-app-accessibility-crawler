#!/usr/bin/env python3
"""Queue Play Store installs quickly, then audit installed packages."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ADB = os.environ.get("ADB", str(Path.home() / "Library/Android/sdk/platform-tools/adb"))
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5554")
LOG = Path("screenshots_vlad_apps/install_queue_log.csv")
FINAL_AUDIT = Path("screenshots_vlad_apps/install_final_audit.csv")

APPS = [
    ("Temu: Shop Like a Billionaire", "com.einnovation.temu"),
    ("CapCut - Video Editor", "com.lemon.lvoverseas"),
    ("Claude by Anthropic", "com.anthropic.claude"),
    ("ReelShort - Stream Drama & TV", "com.newleaf.app.android.victor"),
    ("T-Life", "com.tmobile.tuesdays"),
    ("Google Gemini", "com.google.android.apps.bard"),
    ("Shop: All your favorite brands", "com.shopify.arrive"),
    ("Cleanup: Phone Storage Cleaner", "com.storage.androidcleaner"),
    ("Paramount+", "com.cbs.app"),
    ("The Masters Golf Tournament", "com.ibm.events.android.masters"),
    ("Duolingo: Language & Chess", "com.duolingo"),
    ("PolyBuzz: Chat with AI Friends", "ai.socialapps.speakmaster"),
    ("Cleaner Toolbox", "com.cleanertool.box"),
    ("Costco Wholesale", "com.costco.app.android"),
    ("Reddit", "com.reddit.frontpage"),
    ("MyChart", "epic.mychart.android"),
    ("Pandora - Music & Podcasts", "com.pandora.android"),
]


def adb(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run([ADB, "-s", SERIAL, *args], capture_output=True, text=True, timeout=timeout)


def shell(command: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return adb(["shell", command], timeout=timeout)


def installed(package: str) -> bool:
    try:
        out = shell(f"pm path {package}", timeout=10).stdout
    except subprocess.TimeoutExpired:
        return False
    return "package:" in out


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value)
    if not match:
        return None
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def dump_labels() -> list[tuple[str, tuple[int, int, int, int]]]:
    try:
        shell("uiautomator dump /sdcard/window.xml >/dev/null", timeout=12)
        xml = adb(["exec-out", "cat", "/sdcard/window.xml"], timeout=12).stdout
        root = ET.fromstring(xml)
    except Exception:
        return []
    labels = []
    for node in root.iter("node"):
        label = " ".join(
            part for part in [node.attrib.get("text", ""), node.attrib.get("content-desc", "")] if part
        ).strip()
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if label and bounds:
            labels.append((label, bounds))
    return labels


def tap_bounds(bounds: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = bounds
    shell(f"input tap {(x1 + x2)//2} {(y1 + y2)//2}", timeout=10)


def queue_install(app: str, package: str) -> str:
    if installed(package):
        return "already_installed"

    shell("am force-stop com.android.vending", timeout=10)
    shell(f"am start -a android.intent.action.VIEW -d 'market://details?id={package}'", timeout=12)
    time.sleep(6)

    labels = dump_labels()
    blob = "\n".join(label for label, _ in labels).lower()
    if installed(package):
        return "already_installed"
    if "not compatible" in blob or "won't work" in blob:
        return "incompatible"
    if "not available" in blob or "item not found" in blob:
        return "unavailable"

    for label, bounds in labels:
        if label.lower() in {"install", "update"}:
            tap_bounds(bounds)
            time.sleep(2)
            return "install_tapped"
    if any(label.lower() == "open" for label, _ in labels):
        return "open_seen"
    return "install_not_found"


def audit() -> list[dict[str, str]]:
    rows = []
    for app, package in APPS:
        rows.append(
            {
                "app_name": app,
                "package_name": package,
                "installed": str(installed(package)).lower(),
            }
        )
    return rows


def main() -> int:
    LOG.parent.mkdir(exist_ok=True)
    queued = []
    for app, package in APPS:
        print(f"{app}: ", end="", flush=True)
        try:
            status = queue_install(app, package)
        except Exception as exc:
            status = f"error:{type(exc).__name__}"
        print(status, flush=True)
        queued.append({"app_name": app, "package_name": package, "queue_status": status})

    print("\nShort settle before audit...", flush=True)
    time.sleep(20)
    installed_rows = {row["package_name"]: row for row in audit()}

    with LOG.open("w", newline="") as fh:
        fieldnames = ["app_name", "package_name", "queue_status", "installed"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in queued:
            row["installed"] = installed_rows[row["package_name"]]["installed"]
            writer.writerow(row)

    with FINAL_AUDIT.open("w", newline="") as fh:
        fieldnames = ["app_name", "package_name", "installed"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for app, package in APPS:
            writer.writerow(
                {
                    "app_name": app,
                    "package_name": package,
                    "installed": installed_rows[package]["installed"],
                }
            )

    print("\nAudit:")
    for row in queued:
        print(f"{row['app_name']}: installed={installed_rows[row['package_name']]['installed']}")
    print(f"\nWrote {LOG}")
    print(f"Wrote {FINAL_AUDIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
