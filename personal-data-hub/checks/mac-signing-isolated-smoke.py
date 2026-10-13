#!/usr/bin/env python3
"""Exercise real macOS Keychain access across two different signed binaries.

Uses a temporary keychain and synthetic secret; does not access login credentials.
Can run while the screen/login keychain is locked.
"""
import os
import pathlib
import plistlib
import secrets
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = r'''
import Foundation
import Security
func check(_ code: OSStatus) { guard code == errSecSuccess else { print("security_failed", code); exit(1) } }
check(SecKeychainSetUserInteractionAllowed(false))
let path = CommandLine.arguments[1]
let create = CommandLine.arguments[2] == "create"
let password = FileHandle.standardInput.readDataToEndOfFile()
var keychain: SecKeychain?
if create {
    var list: CFArray?
    check(SecKeychainCopySearchList(&list))
    password.withUnsafeBytes { check(SecKeychainCreate(path, UInt32($0.count), $0.baseAddress, false, nil, &keychain)) }
    if let list { check(SecKeychainSetSearchList(list)) }
} else { check(SecKeychainOpen(path, &keychain)) }
guard let keychain else { exit(1) }
password.withUnsafeBytes { check(SecKeychainUnlock(keychain, UInt32($0.count), $0.baseAddress, true)) }
defer { SecKeychainLock(keychain) }
let secret = Data("synthetic-test-value".utf8)
if create {
    let item: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "com.yuwk.personal-data-hub.signing-test",
        kSecAttrAccount as String: "fixture", kSecValueData as String: secret,
        kSecUseKeychain as String: keychain]
    check(SecItemAdd(item as CFDictionary, nil))
}
let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "com.yuwk.personal-data-hub.signing-test",
    kSecAttrAccount as String: "fixture", kSecReturnData as String: true,
    kSecMatchSearchList as String: [keychain]]
var result: CFTypeRef?
check(SecItemCopyMatching(query as CFDictionary, &result))
guard result as? Data == secret else { exit(1) }
print("signed_binary_VARIANT_read_ok dialogs=disabled")
'''

os.umask(0o077)
with tempfile.TemporaryDirectory(prefix="pdh-isolated-signing-") as temporary:
    folder = pathlib.Path(temporary)
    password = secrets.token_hex(32).encode()
    keychain = folder / "fixture.keychain-db"
    hashes, requirements = [], []
    for number in (1, 2):
        app = folder / f"Version{number}/Personal Data Hub.app"
        binary = app / "Contents/MacOS/PersonalDataHub"
        binary.parent.mkdir(parents=True)
        source = folder / f"version{number}.swift"
        source.write_text(SOURCE.replace("VARIANT", str(number)))
        subprocess.run(["swiftc", "-suppress-warnings", str(source), "-o", str(binary)], check=True)
        with (app / "Contents/Info.plist").open("wb") as file:
            plistlib.dump({"CFBundleIdentifier": "com.yuwk.personal-data-hub", "CFBundleExecutable": "PersonalDataHub",
                          "CFBundlePackageType": "APPL", "CFBundleVersion": str(number)}, file)
        subprocess.run(["swift", "-suppress-warnings", str(ROOT / "apps/mac-client/signing.swift"), str(app)], check=True)
        result = subprocess.run(["codesign", "-d", "--verbose=4", "-r-", str(app)], capture_output=True, text=True, check=True)
        lines = (result.stdout + result.stderr).splitlines()
        hashes.append(next(line for line in lines if line.startswith("CDHash=")))
        requirements.append(next(line for line in lines if line.startswith("designated =>")))
        subprocess.run([str(binary), str(keychain), "create" if number == 1 else "read"], input=password, check=True, timeout=15)
    assert hashes[0] != hashes[1], "Binary did not change"
    assert requirements[0] == requirements[1], "Signing requirement changed"
print("isolated_signing_smoke_ok changed_binary=true stable_requirement=true keychain=readable dialogs=disabled")
