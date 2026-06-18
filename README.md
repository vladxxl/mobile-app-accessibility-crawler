# Android App Screenshot and NAI Candidate Pipeline

This repository contains Python/ADB automation for installing assigned Android apps, collecting app screenshots, crawling candidate screens for non-apparent information (NAI) review, and serving a local review UI.

The scripts are designed for an Android emulator with Google Play. They avoid passwords, purchases, subscriptions, posting, messaging, uploading, account creation, destructive cleaner actions, and other unsafe app actions.

## Repository Contents

- `apps_vlad.txt` - app list used by the pipeline.
- `collect_vlad_app_screenshots.py` - broad Play Store install and screenshot collection workflow.
- `queue_vlad_app_installs.py` - quick Play Store install queue plus installed-app audit.
- `install_vlad_apps_only.py` - slower installer that waits on each app listing.
- `collect_nai_candidates.py` - crawler that captures NAI candidate frames with PNG, UI XML, and JSON metadata.
- `supplement_first4_menu_frames.py` - optional coordinate-based supplement for the first four apps.
- `generate_nai_manifest.py` - writes the app manifest and NAI taxonomy files into the generated output folder.
- `review_nai_candidates.py` - local browser review tool for keep/discard decisions.
- `nai_shared.py` - shared app metadata, issue taxonomy, safety labels, and validation helpers.

Generated screenshots, XML dumps, JSON metadata, logs, bugreports, and local review state are intentionally ignored by git.

## How to Run

If the emulator is already booted, Play Store is logged in, and the apps are installed:

```bash
python3 collect_nai_candidates.py --preflight-only
python3 generate_nai_manifest.py
python3 collect_nai_candidates.py --min-frames 10 --max-frames 22
python3 review_nai_candidates.py
```

Open the review UI at:

```text
http://127.0.0.1:8765
```

To run only one app:

```bash
python3 collect_nai_candidates.py --only reddit --min-frames 10 --max-frames 22
```

To resume after an interruption:

```bash
python3 collect_nai_candidates.py --resume --min-frames 10 --max-frames 22
```

If the apps are not installed yet, run this first:

```bash
python3 collect_vlad_app_screenshots.py --prepare-play-store
python3 queue_vlad_app_installs.py
```

Then confirm `screenshots_vlad_apps/install_final_audit.csv` shows `installed=true` for each app before starting the NAI crawl.

## Quick Start Checklist

Before running the crawler, make sure:

- Android Studio or Android SDK tools are installed.
- `adb` works from the terminal.
- A Google Play-capable emulator is booted, or the target AVD exists so the script can start it.
- The emulator has network access.
- Play Store is open and logged in with the team test account.
- Do not type passwords into the terminal. Enter Google credentials and 2FA only inside the emulator.
- The apps in `apps_vlad.txt` are the intended crawl set.
- Apps are installed before running `collect_nai_candidates.py`.
- `screenshots_vlad_apps/install_final_audit.csv` exists and marks each app as installed before the NAI candidate crawl.

The usual command sequence is:

```bash
python3 collect_vlad_app_screenshots.py --detect-only
python3 collect_vlad_app_screenshots.py --prepare-play-store
python3 queue_vlad_app_installs.py
python3 collect_nai_candidates.py --preflight-only
python3 generate_nai_manifest.py
python3 collect_nai_candidates.py --min-frames 10 --max-frames 22
python3 review_nai_candidates.py
```

If the emulator is already running and signed in, add `--no-start-emulator` to the Play Store preparation command.

## Apps to Crawl

The crawler reads this list from `apps_vlad.txt`:

1. Temu: Shop Like a Billionaire
2. CapCut - Video Editor
3. Claude by Anthropic
4. ReelShort - Stream Drama & TV
5. T-Life
6. Google Gemini
7. Shop: All your favorite brands
8. Cleanup: Phone Storage Cleaner
9. Paramount+
10. The Masters Golf Tournament
11. Duolingo: Language & Chess
12. PolyBuzz: Chat with AI Friends
13. Cleaner Toolbox
14. Costco Wholesale
15. Reddit
16. MyChart
17. Pandora - Music & Podcasts

To crawl a different batch, edit `apps_vlad.txt` and update the matching app metadata in `nai_shared.py`.

## Requirements

- Python 3.10 or newer. The scripts use only the Python standard library.
- Android Studio or Android SDK command-line tools.
- `adb` and, for emulator startup, `emulator`.
- A Google Play-capable Android Studio emulator.
- Required/default AVD name: `Medium Phone API 36.0`.
- Recommended emulator image: Android API 36 Google Play image, arm64 on Apple Silicon or x86_64 on Intel.

The default AVD name is used by `collect_vlad_app_screenshots.py` when it starts the emulator. If your local AVD has a different name, either rename it in Android Studio Device Manager or set `TARGET_AVD` before running the scripts.

Check available AVD names with:

```bash
emulator -list-avds
```

Recommended shell setup:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
export ANDROID_SERIAL="emulator-5554"
export TARGET_AVD="Medium Phone API 36.0"
```

If a Play Store sign-in is required, complete the password and any 2FA manually in the emulator. The scripts do not accept or store the password. To show the account name in prompts without committing it:

```bash
export GOOGLE_PLAY_ACCOUNT="team-test-account@example.com"
```

## 1. Check the Environment

This is a safe preflight. It does not install or launch third-party apps.

```bash
python3 collect_vlad_app_screenshots.py --detect-only
```

Manual checks that are useful when debugging:

```bash
adb devices
emulator -list-avds
adb shell getprop sys.boot_completed
```

## 2. Prepare Play Store

Boot or connect the emulator, open Play Store, and complete sign-in manually if needed:

```bash
python3 collect_vlad_app_screenshots.py --prepare-play-store
```

Use `--no-start-emulator` if the emulator is already running and you do not want the script to start an AVD:

```bash
python3 collect_vlad_app_screenshots.py --prepare-play-store --no-start-emulator
```

## 3. Install Apps and Write the Audit

The NAI crawler requires `screenshots_vlad_apps/install_final_audit.csv`, which records whether every package in `apps_vlad.txt` is installed.

Fast queue-and-audit path:

```bash
python3 queue_vlad_app_installs.py
```

Slower listing-by-listing path:

```bash
python3 install_vlad_apps_only.py
```

Both scripts write `screenshots_vlad_apps/install_final_audit.csv`.

Confirm the audit before crawling:

```bash
cat screenshots_vlad_apps/install_final_audit.csv
```

Every row should have `installed` set to `true`. If an app is unavailable, incompatible, or blocked by verification, note that in the research log and exclude it from the NAI crawl with `--only` runs for the installed apps.

## 4. Broad Screenshot Collection

Collect Play Store listing screenshots, first-launch screens, permission/login blockers, and a small set of safe in-app navigation screenshots:

```bash
python3 collect_vlad_app_screenshots.py --run
```

Useful scoped runs:

```bash
python3 collect_vlad_app_screenshots.py --run --only "Reddit"
python3 collect_vlad_app_screenshots.py --run --start-at "Reddit"
python3 collect_vlad_app_screenshots.py --run --max-extra-screens 5
```

Output goes to `screenshots_vlad_apps/`.

## 5. NAI Candidate Crawl

After apps are installed and the audit CSV exists:

```bash
python3 collect_nai_candidates.py --preflight-only
python3 generate_nai_manifest.py
python3 collect_nai_candidates.py --min-frames 10 --max-frames 22
```

Useful scoped or resumable runs:

```bash
python3 collect_nai_candidates.py --only reddit --min-frames 10 --max-frames 22
python3 collect_nai_candidates.py --resume --min-frames 10 --max-frames 22
python3 collect_nai_candidates.py --limit 4 --min-frames 10 --max-frames 22
```

Output goes to `nai_candidate_frames/`.

Optional supplement for the first four apps:

```bash
python3 supplement_first4_menu_frames.py --target-count 22
```

## 6. Review Candidate Frames

Start the local review tool:

```bash
python3 review_nai_candidates.py
```

Then open:

```text
http://127.0.0.1:8765
```

Review state and exported decisions are written under `nai_candidate_frames/`.

## Output Policy

Do not commit generated output by default:

- `screenshots_vlad_apps/`
- `nai_candidate_frames/`
- Android bugreport `.zip` files
- `.log`, `.pid`, `.pyc`, `.DS_Store`, and cache files

If colleagues need a small example dataset, add a deliberately curated sample in a separate directory and verify it contains no personal account data, health data, credentials, or proprietary app content beyond what the team is allowed to share.
