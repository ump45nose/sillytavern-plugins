"""Install once; never recompile or replace a previously approved reader."""
from pathlib import Path
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile

os.umask(0o077)
root = Path(__file__).resolve().parents[1]
private = Path.home() / "Library/Application Support/PersonalDataHub"
app = private / "Personal Data Hub Credentials.app"
manifest = private / "Signing/credential-reader.json"
identity = json.loads((private / "Signing/identity.json").read_text())["certificateSHA1"]
bundle_id = "com.yuwk.personal-data-hub.credential-reader"
requirement = f'identifier "{bundle_id}" and anchor = H"{identity}"'
source_hash = hashlib.sha256((root / "credential-reader/main.swift").read_bytes()).hexdigest()


def verify(candidate):
    subprocess.run(["codesign", "--verify", "--strict", "-R", "=" + requirement, str(candidate)], check=True)


if app.exists() or manifest.exists():
    if not app.exists() or not manifest.exists():
        raise SystemExit("Restore the existing credential reader and its manifest; automatic replacement is disabled")
    saved = json.loads(manifest.read_text())
    actual = hashlib.sha256((app / "Contents/MacOS/PersonalDataHubCredentialReader").read_bytes()).hexdigest()
    if saved != {"sourceSHA256": source_hash, "binarySHA256": actual, "certificateSHA1": identity}:
        raise SystemExit("Credential reader changed; preserve the approved binary and perform an explicit migration")
    verify(app)
    print("Existing credential reader preserved byte for byte")
else:
    with tempfile.TemporaryDirectory(prefix="credential-reader-", dir=private) as directory:
        candidate = Path(directory) / app.name
        binary = candidate / "Contents/MacOS/PersonalDataHubCredentialReader"
        binary.parent.mkdir(parents=True)
        architecture = subprocess.check_output(["uname", "-m"], text=True).strip()
        subprocess.run(["swiftc", "-O", "-suppress-warnings", "-target", f"{architecture}-apple-macosx13.0",
                        str(root / "credential-reader/main.swift"), "-o", str(binary)], check=True)
        with (candidate / "Contents/Info.plist").open("wb") as file:
            plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleExecutable": binary.name,
                          "CFBundleName": "Personal Data Hub Credentials", "CFBundleVersion": "1",
                          "CFBundlePackageType": "APPL", "LSUIElement": True, "LSMinimumSystemVersion": "13.0"}, file)
        subprocess.run(["swift", "-suppress-warnings", str(root / "signing.swift"), str(candidate)], check=True)
        verify(candidate)
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        shutil.copytree(candidate, app)
        manifest.write_text(json.dumps({"sourceSHA256": source_hash, "binarySHA256": digest, "certificateSHA1": identity}))
        manifest.chmod(0o600)
    print("Fixed credential reader installed; login Keychain items unchanged")
