#!/usr/bin/env python3
"""Shared data and helpers for Vlad NAI app collection."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_LIST_PATH = ROOT / "apps_vlad.txt"
INSTALL_AUDIT_PATH = ROOT / "screenshots_vlad_apps" / "install_final_audit.csv"
OUTPUT_ROOT = ROOT / "nai_candidate_frames"


NAI_ISSUES = {
    "Missing or Unclear Input Purpose": {
        "color": "#FFA39E",
        "short_definition": (
            "An input field does not clearly communicate what information is expected "
            "through a visible label, descriptive placeholder, or clear accompanying text."
        ),
        "signals": ["input", "field", "search", "email", "password", "placeholder", "edittext"],
    },
    "Unclear Icon/Button Purpose": {
        "color": "#D4380D",
        "short_definition": (
            "An icon or button does not provide enough visible information to understand "
            "its action, or uses a familiar icon for an unexpected action."
        ),
        "signals": ["icon-only", "button", "unlabeled", "clickable", "imagebutton"],
    },
    "Icon/Button Inconsistency": {
        "color": "#FFC069",
        "short_definition": (
            "Visually similar icons/buttons perform different actions, or different "
            "icons/buttons perform the same action without consistent identification."
        ),
        "signals": ["repeated-control", "menu", "toolbar", "same-icon", "different-action"],
    },
    "View Inconsistency": {
        "color": "#AD8B00",
        "short_definition": (
            "Similar views differ in available actions, layout structure, navigation, "
            "or component presence."
        ),
        "signals": ["detail", "list", "similar-view", "layout", "actions"],
    },
    "No View Identifier": {
        "color": "#D3F261",
        "short_definition": (
            "The current view lacks a clear visible title, active navigation state, "
            "or other perceivable indicator of where the user is."
        ),
        "signals": ["no-title", "no-active-nav", "navigation", "header", "location"],
    },
    "Disappearing View Identifier": {
        "color": "#389E0D",
        "short_definition": (
            "A visible view identifier, title, or active navigation indicator disappears "
            "or becomes indistinguishable after scrolling or interaction."
        ),
        "signals": ["scroll", "before-after", "hidden-title", "collapsed-header"],
    },
}


APP_METADATA = {
    "Temu: Shop Like a Billionaire": {
        "package": "com.einnovation.temu",
        "category": "shopping",
        "login_expectation": "guest_browse_possible",
        "targets": ["onboarding", "home_feed", "categories", "search", "product_detail", "cart_gate"],
    },
    "CapCut - Video Editor": {
        "package": "com.lemon.lvoverseas",
        "category": "creative_media",
        "login_expectation": "guest_browse_possible",
        "targets": ["onboarding", "templates", "tool_grid", "new_project_gate", "settings"],
    },
    "Claude by Anthropic": {
        "package": "com.anthropic.claude",
        "category": "ai_chat",
        "login_expectation": "login_likely",
        "targets": ["welcome", "login_wall", "prompt_input_if_available", "settings_if_available"],
    },
    "ReelShort - Stream Drama & TV": {
        "package": "com.newleaf.app.android.victor",
        "category": "streaming",
        "login_expectation": "paywall_or_login_possible",
        "targets": ["home_feed", "discover", "show_detail", "episode_list", "player_preview", "paywall"],
    },
    "T-Life": {
        "package": "com.tmobile.tuesdays",
        "category": "account_offers",
        "login_expectation": "login_likely",
        "targets": ["welcome", "offers", "permissions", "account_login", "navigation"],
    },
    "Google Gemini": {
        "package": "com.google.android.apps.bard",
        "category": "ai_chat",
        "login_expectation": "device_google_account",
        "targets": ["intro", "main_prompt", "example_prompts", "settings", "model_switcher"],
    },
    "Shop: All your favorite brands": {
        "package": "com.shopify.arrive",
        "category": "shopping_tracking",
        "login_expectation": "tracking_login_possible",
        "targets": ["onboarding", "discover", "search", "store_detail", "tracking_gate", "permissions"],
    },
    "Cleanup: Phone Storage Cleaner": {
        "package": "com.storage.androidcleaner",
        "category": "utility_cleaner",
        "login_expectation": "no_login_expected",
        "targets": ["onboarding", "permission_prompt", "dashboard", "scan_categories", "settings", "paywall"],
    },
    "Paramount+": {
        "package": "com.cbs.app",
        "category": "streaming",
        "login_expectation": "login_or_subscription_likely",
        "targets": ["landing", "browse", "show_detail", "login_wall", "subscription_gate"],
    },
    "The Masters Golf Tournament": {
        "package": "com.ibm.events.android.masters",
        "category": "sports_info",
        "login_expectation": "guest_browse_possible",
        "targets": ["home", "leaderboard", "schedule", "news", "player_profile", "course_map"],
    },
    "Duolingo: Language & Chess": {
        "package": "com.duolingo",
        "category": "education",
        "login_expectation": "onboarding_signup_possible",
        "targets": ["language_picker", "onboarding", "lesson_map", "profile_gate", "login_wall"],
    },
    "PolyBuzz: Chat with AI Friends": {
        "package": "ai.socialapps.speakmaster",
        "category": "ai_character_chat",
        "login_expectation": "login_or_chat_gate_possible",
        "targets": ["character_discovery", "filters", "character_profile", "chat_entry_no_send", "login_wall"],
    },
    "Cleaner Toolbox": {
        "package": "com.cleanertool.box",
        "category": "utility_cleaner",
        "login_expectation": "no_login_expected",
        "targets": ["onboarding", "permission_prompt", "dashboard", "tool_list", "scan_results_pre_action", "settings"],
    },
    "Costco Wholesale": {
        "package": "com.costco.app.android",
        "category": "shopping_membership",
        "login_expectation": "membership_login_possible",
        "targets": ["home", "categories", "search", "product_detail", "warehouse_locator_gate", "cart_gate"],
    },
    "Reddit": {
        "package": "com.reddit.frontpage",
        "category": "social_feed",
        "login_expectation": "guest_browse_possible",
        "targets": ["popular_feed", "subreddit", "post_detail", "comments", "search", "login_prompt"],
    },
    "MyChart": {
        "package": "epic.mychart.android",
        "category": "health",
        "login_expectation": "login_required",
        "targets": ["welcome", "provider_search", "login_wall", "signup_info", "recovery_info"],
    },
    "Pandora - Music & Podcasts": {
        "package": "com.pandora.android",
        "category": "music",
        "login_expectation": "login_likely",
        "targets": ["welcome", "genre_browse", "search", "player_preview", "login_wall", "paywall"],
    },
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
    "cart",
    "add to cart",
    "add_to_cart",
    "checkout",
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
    "delete",
    "clean",
    "clean now",
    "clear",
    "boost",
    "refresh",
    "security verification",
    "verification",
    "captcha",
    "fill each box",
    "required number",
]

BLOCKER_LABELS = [
    "sign in",
    "log in",
    "login",
    "subscribe",
    "start free trial",
    "create account",
    "register",
    "membership",
    "verify",
]


@dataclass(frozen=True)
class AppSpec:
    app_name: str
    package_name: str
    safe_name: str
    category: str
    login_expectation: str
    targets: list[str]


def safe_name(name: str) -> str:
    cleaned = name.lower().replace("&", " and ")
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    return re.sub(r"_+", "_", cleaned).strip("_")[:90] or "app"


def read_app_names(path: Path = APP_LIST_PATH) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def read_install_audit(path: Path = INSTALL_AUDIT_PATH) -> dict[str, dict[str, str]]:
    with path.open(newline="") as fh:
        return {row["app_name"]: row for row in csv.DictReader(fh)}


def build_manifest() -> list[AppSpec]:
    specs: list[AppSpec] = []
    for app_name in read_app_names():
        if app_name not in APP_METADATA:
            raise ValueError(f"Missing APP_METADATA entry for apps_vlad.txt app: {app_name}")
        meta = APP_METADATA[app_name]
        specs.append(
            AppSpec(
                app_name=app_name,
                package_name=meta["package"],
                safe_name=safe_name(app_name),
                category=meta["category"],
                login_expectation=meta["login_expectation"],
                targets=list(meta["targets"]),
            )
        )
    return specs


def validate_installed_manifest() -> list[AppSpec]:
    specs = build_manifest()
    audit = read_install_audit()
    errors: list[str] = []
    for spec in specs:
        row = audit.get(spec.app_name)
        if not row:
            errors.append(f"{spec.app_name}: missing from install audit")
            continue
        if row.get("package_name") != spec.package_name:
            errors.append(
                f"{spec.app_name}: package mismatch manifest={spec.package_name} audit={row.get('package_name')}"
            )
        if row.get("installed", "").lower() != "true":
            errors.append(f"{spec.app_name}: audit says installed={row.get('installed')}")
    if len(specs) != 17:
        errors.append(f"apps_vlad.txt produced {len(specs)} apps, expected 17")
    if errors:
        raise RuntimeError("Install manifest validation failed:\n" + "\n".join(errors))
    return specs
