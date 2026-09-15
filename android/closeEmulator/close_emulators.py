"""Close all Android SDK emulators listed by adb, leaving physical devices alone.

Usage:
    python close_emulators.py
    python close_emulators.py --dry-run
"""

import argparse
import re
import shutil
import subprocess
import sys
import time


def emulator_serials(output: str) -> list[str]:
    return list(dict.fromkeys(
        fields[0] for line in output.splitlines()
        if len(fields := line.split()) >= 2 and re.fullmatch(r"emulator-\d+", fields[0])
    ))


def close_emulator(serial: str, adb_path: str, runner, timeout: float = 15) -> None:
    """Close one SDK emulator and confirm it disappeared from adb's list."""
    if not re.fullmatch(r"emulator-\d+", serial):
        raise ValueError(f"Not an Android SDK emulator: {serial}")
    runner([adb_path, "-s", serial, "emu", "kill"], timeout=15)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, output = runner([adb_path, "devices"], stream_output=False, timeout=10)
        if serial not in emulator_serials(output):
            return
        time.sleep(0.5)
    raise TimeoutError(f"Shutdown requested, but {serial} is still listed by adb")


def run_adb(adb: str, *args: str) -> str:
    result = subprocess.run(
        [adb, *args], capture_output=True, text=True, errors="replace", timeout=15
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                           or f"adb exited with code {result.returncode}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="List emulators without closing them")
    args = parser.parse_args()

    adb = shutil.which("adb")
    if not adb:
        print("Error: adb was not found. Add Android SDK platform-tools to PATH.", file=sys.stderr)
        return 1

    try:
        output = run_adb(adb, "devices")
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Failed to list devices: {exc}", file=sys.stderr)
        return 1

    emulators = emulator_serials(output)

    if not emulators:
        print("No Android SDK emulators found.")
        return 0

    failures = 0
    for serial in emulators:
        if args.dry_run:
            print(f"Would close: {serial}")
            continue
        try:
            run_adb(adb, "-s", serial, "emu", "kill")
            print(f"Shutdown command sent: {serial}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            failures += 1
            print(f"Failed to close {serial}: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
