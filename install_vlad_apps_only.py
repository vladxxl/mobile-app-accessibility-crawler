#!/usr/bin/env python3
"""Install Vlad's assigned Play Store apps without collecting screenshots."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


ADB = os.environ.get("ADB", str(Path.home() / "Library/Android/sdk/platform-tools/adb"))
SERIAL = os.environ.get("ANDROID_SERIAL", "emulator-5554")
LOG_PATH = Path("screenshots_vlad_apps/install_setup_log.csv")
FINAL_AUDIT_PATH = Path("screenshots_vlad_apps/install_final_audit.csv")


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


@dataclass
class Node:
    text: str
    desc: str
    bounds: tuple[int, int, int, int]

    @property
    def label(self) -> str:
        return (self.text or self.desc or "").strip()

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)


def run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def adb(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return run([ADB, "-s", SERIAL, *args], timeout=timeout)


def shell(command: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return adb(["shell", command], timeout=timeout)


def package_installed(package: str) -> bool:
    proc = shell(f"pm path {package}", timeout=20)
    return proc.returncode == 0 and "package:" in proc.stdout


def parse_bounds(value: str) -> tuple[int, int, int, int] | None:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def dump_nodes() -> list[Node]:
    shell("uiautomator dump /sdcard/window.xml >/dev/null", timeout=40)
    proc = adb(["exec-out", "cat", "/sdcard/window.xml"], timeout=40)
    root = ET.fromstring(proc.stdout)
    nodes: list[Node] = []
    for elem in root.iter("node"):
        bounds = parse_bounds(elem.attrib.get("bounds", ""))
        if not bounds:
            continue
        nodes.append(
            Node(
                text=elem.attrib.get("text", ""),
                desc=elem.attrib.get("content-desc", ""),
                bounds=bounds,
            )
        )
    return nodes


def text_blob(nodes: list[Node]) -> str:
    return "\n".join(node.label for node in nodes if node.label).lower()


def tap_node(node: Node) -> None:
    x, y = node.center
    shell(f"input tap {x} {y}", timeout=15)
    time.sleep(1.5)


def find_label(nodes: list[Node], labels: list[str]) -> Node | None:
    wanted = [label.lower() for label in labels]
    for node in nodes:
        label = node.label.lower()
        if label in wanted:
            return node
    for node in nodes:
        label = node.label.lower()
        if any(w in label for w in wanted):
            return node
    return None


def open_listing(package: str) -> None:
    shell(
        "am start -a android.intent.action.VIEW -d "
        + repr(f"market://details?id={package}"),
        timeout=30,
    )
    time.sleep(7)


def install_app(app_name: str, package: str) -> dict[str, str]:
    row = {
        "app_name": app_name,
        "package_name": package,
        "status": "unknown",
        "notes": "",
    }

    if package_installed(package):
        row["status"] = "already_installed"
        return row

    open_listing(package)

    for attempt in range(90):
        if package_installed(package):
            row["status"] = "installed"
            return row

        nodes = dump_nodes()
        blob = text_blob(nodes)

        if "open" in blob and package_installed(package):
            row["status"] = "installed"
            return row

        if "not compatible" in blob or "won't work for your device" in blob:
            row["status"] = "incompatible"
            row["notes"] = "Play Store says incompatible."
            return row
        if "not available" in blob or "item not found" in blob:
            row["status"] = "unavailable"
            row["notes"] = "Play Store says unavailable."
            return row
        if "verify" in blob and "install" not in blob:
            row["status"] = "blocked"
            row["notes"] = "Play Store requires extra verification."
            return row

        button = find_label(nodes, ["Install", "Update"])
        if button:
            tap_node(button)
            time.sleep(5)
            continue

        if find_label(nodes, ["Open"]):
            row["status"] = "installed_unverified"
            row["notes"] = "Play Store shows Open, but pm path did not confirm package."
            return row

        if attempt % 10 == 0:
            print(f"  waiting on listing/install UI for {app_name}...")
        time.sleep(4)

    row["status"] = "timeout"
    row["notes"] = "Timed out waiting for install."
    return row


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    print("Checking emulator...")
    boot = shell("getprop sys.boot_completed", timeout=20).stdout.strip()
    if boot != "1":
        raise SystemExit("Emulator is not booted.")

    for app_name, package in APPS:
        print(f"\n{app_name} ({package})")
        try:
            row = install_app(app_name, package)
        except Exception as exc:
            row = {
                "app_name": app_name,
                "package_name": package,
                "status": "error",
                "notes": f"{type(exc).__name__}: {exc}",
            }
        print(f"  {row['status']} {row['notes']}")
        rows.append(row)

    with LOG_PATH.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["app_name", "package_name", "status", "notes"])
        writer.writeheader()
        writer.writerows(rows)

    with FINAL_AUDIT_PATH.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["app_name", "package_name", "installed"])
        writer.writeheader()
        for app_name, package in APPS:
            writer.writerow(
                {
                    "app_name": app_name,
                    "package_name": package,
                    "installed": str(package_installed(package)).lower(),
                }
            )

    print(f"Wrote {LOG_PATH}")
    print(f"Wrote {FINAL_AUDIT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
