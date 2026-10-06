#!/usr/bin/env python3
"""On Mac: prove changed builds retain Keychain access without authorization UI.

Reads existing credentials through the signed app, never prints or exports them.
The installed app is untouched; the update candidate lives in a private temp dir.
"""
import pathlib
import plistlib
import re
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = pathlib.Path.home() / "Applications/Personal Data Hub.app"


def signature(app):
    result = subprocess.run(["codesign", "-d", "--verbose=4", "-r-", str(app)],
                            capture_output=True, text=True, check=True)
    output = result.stdout + result.stderr
    requirement = re.search(r"^designated => (.+)$", output, re.M)
    cdhash = re.search(r"^CDHash=([0-9a-f]+)$", output, re.M)
    assert requirement and cdhash and "certificate root" in requirement[1], "Persistent certificate missing"
    subprocess.run(["codesign", "--verify", "--strict", "-R", "=" + requirement[1], str(app)], check=True)
    return requirement[1], cdhash[1]


def read_without_dialog(app):
    subprocess.run([str(app / "Contents/MacOS/PersonalDataHub"), "--keychain-smoke"], check=True, timeout=15)


first = signature(APP)
read_without_dialog(APP)
with tempfile.TemporaryDirectory(prefix="pdh-signing-smoke-") as directory:
    candidate = pathlib.Path(directory) / APP.name
    shutil.copytree(APP, candidate)
    info = candidate / "Contents/Info.plist"
    with info.open("rb") as file:
        values = plistlib.load(file)
    values["CFBundleVersion"] += ".signing-smoke"
    with info.open("wb") as file:
        plistlib.dump(values, file)
    subprocess.run(["swift", "-suppress-warnings", str(ROOT / "apps/mac-client/signing.swift"), str(candidate)], check=True)
    second = signature(candidate)
    assert first[0] == second[0], "Signing identity changed"
    assert first[1] != second[1], "Update did not change the CodeDirectory hash"
    read_without_dialog(candidate)
print("signing_smoke_ok changed_cdhash=true stable_requirement=true viewer=readable google=readable dialogs=disabled")
