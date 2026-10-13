"""Give the existing signed Token Monitor launcher its installed Grok CLI path."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time


def app_running():
    rows = subprocess.check_output(["ps", "-axo", "command="], text=True).splitlines()
    return any(row.strip().startswith("/Applications/Token Monitor.app/Contents/MacOS/Token Monitor") for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restart", action="store_true", help="Reload the original launcher and app")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("Run on the affected Mac")
    home = Path.home()
    cli = home / ".grok/bin/grok"
    if not os.access(cli, os.X_OK):
        raise RuntimeError("Existing Grok CLI is missing or not executable")
    label = "xyz.172906573.token-monitor.desktop"
    path = home / "Library/LaunchAgents" / (label + ".plist")
    original = path.read_bytes()
    data = plistlib.loads(original)
    command = list(data.get("ProgramArguments", []))
    if data.get("Label") != label or not command or command[0] != "/usr/bin/open" or "/Applications/Token Monitor.app" not in command:
        raise RuntimeError("Unexpected launcher; inspect it before changing")
    updated = []
    index = 0
    while index < len(command):
        if command[index] == "--env" and index + 1 < len(command) and command[index + 1].startswith("GROK_CLI_PATH="):
            index += 2
            continue
        updated.append(command[index])
        index += 1
    updated.extend(["--env", "GROK_CLI_PATH=" + str(cli)])
    data["ProgramArguments"] = updated
    changed = updated != command
    if changed:
        backup = home / "Library/Application Support/Token Monitor/backups" / ("grok-launcher-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(path, backup / path.name)
        (backup / path.name).chmod(0o600)
        path.write_bytes(plistlib.dumps(data))
        path.chmod(0o600)
    if args.restart:
        target = "gui/" + str(os.getuid())
        try:
            subprocess.run(["osascript", "-e", 'if application id "com.javis.tokenmonitor" is running then tell application id "com.javis.tokenmonitor" to quit'], check=True, capture_output=True)
            deadline = time.monotonic() + 10
            while app_running() and time.monotonic() < deadline:
                time.sleep(0.2)
            if app_running():
                raise subprocess.CalledProcessError(1, "app_quit_timeout")
            subprocess.run(["launchctl", "bootout", target + "/" + label], capture_output=True)
            subprocess.run(["launchctl", "bootstrap", target, str(path)], check=True, capture_output=True)
            deadline = time.monotonic() + 10
            while not app_running() and time.monotonic() < deadline:
                time.sleep(0.2)
            if not app_running():
                raise subprocess.CalledProcessError(1, "app_launch_timeout")
        except subprocess.CalledProcessError:
            path.write_bytes(original)
            subprocess.run(["launchctl", "bootout", target + "/" + label], capture_output=True)
            subprocess.run(["launchctl", "bootstrap", target, str(path)], capture_output=True)
            raise RuntimeError("Launcher reload failed; original plist restored") from None
    print(json.dumps({"launcher": str(path), "grok_cli": str(cli), "changed": changed, "restarted": args.restart}))


if __name__ == "__main__":
    main()
