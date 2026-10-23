// Signs the bundle with this Mac's persistent self-signed identity (shared with the v0 app).
// Read-only: never creates, rotates or edits the identity, never touches the login keychain,
// and never falls back to ad hoc signing, so TCC grants and keychain ACLs survive rebuilds.
import Darwin
import Foundation
import Security

struct SigningFailure: Error, CustomStringConvertible { let description: String }

func check(_ status: OSStatus, _ operation: String) throws {
    guard status == errSecSuccess else { throw SigningFailure(description: "\(operation) failed (Security \(status))") }
}

func codesign(_ arguments: [String]) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
    process.arguments = arguments
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.standardError
    try process.run()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else { throw SigningFailure(description: "codesign failed (\(process.terminationStatus))") }
}

struct Identity: Codable { let certificateSHA1: String }

let allowedIdentifiers = ["com.yuwk.personal-hub", "com.yuwk.personal-hub.credentials"]
let folder = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Application Support/PersonalDataHub/Signing")
let keychainPath = folder.appendingPathComponent("identity.keychain-db").path

do {
    guard CommandLine.arguments.count == 2, CommandLine.arguments[1].hasSuffix(".app") else {
        throw SigningFailure(description: "Usage: swift sign.swift /path/App.app")
    }
    let app = CommandLine.arguments[1]
    let info = try PropertyListSerialization.propertyList(
        from: Data(contentsOf: URL(fileURLWithPath: app).appendingPathComponent("Contents/Info.plist")), format: nil) as? [String: Any]
    guard let identifier = info?["CFBundleIdentifier"] as? String, allowedIdentifiers.contains(identifier) else {
        throw SigningFailure(description: "Unexpected bundle identifier")
    }
    guard let manifest = try? Data(contentsOf: folder.appendingPathComponent("identity.json")),
          let identity = try? JSONDecoder().decode(Identity.self, from: manifest),
          identity.certificateSHA1.count == 40, identity.certificateSHA1.allSatisfy(\.isHexDigit),
          FileManager.default.fileExists(atPath: keychainPath) else {
        throw SigningFailure(description: "Persistent signing identity missing or incomplete; restore the Signing directory")
    }
    let password = try Data(contentsOf: folder.appendingPathComponent("keychain-password"))

    try check(SecKeychainSetUserInteractionAllowed(false), "Disable signing prompts")
    var keychain: SecKeychain?
    try check(SecKeychainOpen(keychainPath, &keychain), "Open signing keychain")
    guard let keychain else { throw SigningFailure(description: "Signing keychain missing") }
    try password.withUnsafeBytes { bytes in
        try check(SecKeychainUnlock(keychain, UInt32(bytes.count), bytes.baseAddress, true), "Unlock signing keychain")
    }
    defer { _ = SecKeychainLock(keychain) }

    let requirement = "identifier \"\(identifier)\" and anchor = H\"\(identity.certificateSHA1)\""
    try codesign(["--force", "--sign", identity.certificateSHA1, "--keychain", keychainPath, "--identifier", identifier,
                  "--options", "runtime", "--timestamp=none", "--requirements", "=designated => " + requirement, app])
    try codesign(["--verify", "--strict", "--test-requirement", "=" + requirement, app])
    print("Signed \(identifier) with persistent certificate \(identity.certificateSHA1.prefix(8))…")
} catch {
    fputs("Signing failed: \(error). No ad hoc fallback.\n", stderr)
    exit(1)
}
