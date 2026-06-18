#!/usr/bin/env python3
"""Supplement first-four app captures with coordinate-based menu/view probes."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from collect_nai_candidates import (
    OUTPUT_ROOT,
    adb_bytes,
    capture_frame,
    current_focus,
    dump_ui,
    image_hash,
    launch_package,
    shell,
    slug,
)
from nai_shared import NAI_ISSUES
from nai_shared import validate_installed_manifest


FIRST_FOUR = [
    "Temu: Shop Like a Billionaire",
    "CapCut - Video Editor",
    "Claude by Anthropic",
    "ReelShort - Stream Drama & TV",
]


def next_index(app_dir: Path) -> int:
    highest = 0
    for path in app_dir.glob("*.png"):
        match = re.match(r"(\d+)_", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def existing_count(app_dir: Path) -> int:
    return len(list(app_dir.glob("*.png")))


def tap_xy(x: int, y: int, wait: float = 2.0) -> None:
    shell(f"input tap {x} {y}", timeout=10)
    time.sleep(wait)


def swipe_up(wait: float = 1.5) -> None:
    shell("input swipe 540 1780 540 650 450", timeout=12)
    time.sleep(wait)


def key_back(wait: float = 1.0) -> None:
    shell("input keyevent KEYCODE_BACK", timeout=10)
    time.sleep(wait)


def visible_text() -> str:
    try:
        _, nodes = dump_ui()
    except Exception:
        return ""
    return " ".join(node.label.lower() for node in nodes if node.label)


def unsafe_state() -> bool:
    text = visible_text()
    unsafe_terms = [
        "checkout",
        "payment",
        "start free trial",
        "subscribe",
        "security verification",
        "captcha",
        "fill each box",
        "required number",
    ]
    return any(term in text for term in unsafe_terms)


def capture(spec, app_dir: Path, index: int, action: str) -> int:
    action_path = f"supplement_{action}"
    try:
        capture_frame(spec, app_dir, index, action_path)
        return index + 1
    except Exception as exc:
        png_bytes = adb_bytes(["exec-out", "screencap", "-p"], timeout=30)
        current_package, current_activity = current_focus()
        stem = f"{index:03d}_{slug(action_path)}"
        png_path = app_dir / f"{stem}.png"
        xml_path = app_dir / f"{stem}.xml"
        metadata_path = app_dir / f"{stem}.json"
        xml_text = f"<uiautomator-unavailable error={type(exc).__name__!r}/>\n"
        png_path.write_bytes(png_bytes)
        xml_path.write_text(xml_text)
        issue = "Unclear Icon/Button Purpose"
        metadata = {
            "app_name": spec.app_name,
            "package_name": spec.package_name,
            "category": spec.category,
            "file_stem": stem,
            "png_path": str(png_path.relative_to(OUTPUT_ROOT)),
            "xml_path": str(xml_path.relative_to(OUTPUT_ROOT)),
            "metadata_path": str(metadata_path.relative_to(OUTPUT_ROOT)),
            "current_package": current_package,
            "current_activity": current_activity,
            "action_path": action_path,
            "suspected_issue": issue,
            "issue_definition": NAI_ISSUES[issue]["short_definition"],
            "confidence": "low",
            "notes": f"Supplemental raw screenshot; uiautomator failed with {type(exc).__name__}.",
            "image_sha256": image_hash(png_bytes),
            "ui_sha256": "",
            "timestamp": time.time(),
            "keep_delete": "",
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return index + 1


def home_reset(spec) -> None:
    for _ in range(2):
        pkg, _ = current_focus()
        if pkg not in {spec.package_name, "com.google.android.googlequicksearchbox"}:
            launch_package(spec.package_name)
            return
        key_back(0.8)
    launch_package(spec.package_name)


def supplement_app(spec, target_count: int) -> None:
    app_dir = OUTPUT_ROOT / "apps" / spec.safe_name
    app_dir.mkdir(parents=True, exist_ok=True)
    index = next_index(app_dir)
    launch_package(spec.package_name)
    index = capture(spec, app_dir, index, "relaunch_baseline")

    probes = [
        ("top_left_or_menu", 95, 160),
        ("top_center_or_search", 540, 170),
        ("top_right_or_profile", 980, 160),
        ("bottom_tab_1", 110, 2210),
        ("bottom_tab_2", 325, 2210),
        ("bottom_tab_3", 540, 2210),
        ("bottom_tab_4", 755, 2210),
        ("bottom_tab_5", 970, 2210),
        ("upper_card_left", 260, 650),
        ("upper_card_right", 820, 650),
        ("middle_card_left", 260, 1060),
        ("middle_card_right", 820, 1060),
        ("lower_menu_row", 540, 1540),
    ]

    for name, x, y in probes:
        if existing_count(app_dir) >= target_count:
            break
        home_reset(spec)
        tap_xy(x, y)
        if unsafe_state():
            index = capture(spec, app_dir, index, f"{name}_blocked_or_gate")
            key_back()
            continue
        index = capture(spec, app_dir, index, name)
        if existing_count(app_dir) >= target_count:
            break
        swipe_up()
        if unsafe_state():
            index = capture(spec, app_dir, index, f"{name}_after_swipe_blocked_or_gate")
            key_back()
            continue
        index = capture(spec, app_dir, index, f"{name}_after_swipe")

    scroll_round = 1
    while existing_count(app_dir) < target_count and scroll_round <= 6:
        home_reset(spec)
        for _ in range(scroll_round):
            swipe_up(0.7)
        if unsafe_state():
            index = capture(spec, app_dir, index, f"scroll_round_{scroll_round}_blocked_or_gate")
            break
        index = capture(spec, app_dir, index, f"scroll_round_{scroll_round}")
        scroll_round += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-count", type=int, default=22)
    args = parser.parse_args()
    specs = {spec.app_name: spec for spec in validate_installed_manifest()}
    for name in FIRST_FOUR:
        spec = specs[name]
        before = existing_count(OUTPUT_ROOT / "apps" / spec.safe_name)
        print(f"\n=== supplement {name}: before={before} target={args.target_count}", flush=True)
        if before >= args.target_count:
            print(f"skipped_existing after={before}", flush=True)
            continue
        supplement_app(spec, args.target_count)
        after = existing_count(OUTPUT_ROOT / "apps" / spec.safe_name)
        print(f"after={after}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
