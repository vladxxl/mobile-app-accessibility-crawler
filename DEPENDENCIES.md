# Dependencies

This project has no third-party Python package dependencies. The scripts use only the Python standard library.

## Python

- Python 3.10 or newer.
- `pip install -r requirements.txt` is safe to run, but it installs nothing because there are no PyPI dependencies.

Optional virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Android Tools

Install Android Studio or the Android SDK command-line tools with:

- Android SDK Platform-Tools, for `adb`.
- Android Emulator, for `emulator`.
- Android API 36 Google Play system image.

The default AVD used by the scripts is:

```text
Medium Phone API 36.0
```

Recommended emulator image:

- Android API 36 Google Play image.
- arm64 image on Apple Silicon Macs.
- x86_64 image on Intel Macs.

Check local AVD names:

```bash
emulator -list-avds
```

If your AVD has a different name, either rename it in Android Studio Device Manager or set:

```bash
export TARGET_AVD="Your AVD Name"
```

## Environment Variables

Recommended shell setup:

```bash
export ANDROID_HOME="$HOME/Library/Android/sdk"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
export ANDROID_SERIAL="emulator-5554"
export TARGET_AVD="Medium Phone API 36.0"
```

Optional Play Store account prompt:

```bash
export GOOGLE_PLAY_ACCOUNT="team-test-account@example.com"
```

Do not put a password in an environment variable or config file. Complete passwords and 2FA manually in the emulator.

## Android Commands Used by the Pipeline

The scripts call Android tools through `adb`, including:

- `adb devices`
- `adb wait-for-device`
- `adb shell getprop sys.boot_completed`
- `adb shell am start`
- `adb shell monkey`
- `adb shell pm path`
- `adb shell dumpsys window`
- `adb shell uiautomator dump`
- `adb exec-out screencap -p`
- `adb shell input tap`
- `adb shell input swipe`
- `adb shell input keyevent`
- `adb shell wm dismiss-keyguard`

## GitHub Publishing

GitHub CLI is not required to run the crawler. It was only used to create and push this repository.
