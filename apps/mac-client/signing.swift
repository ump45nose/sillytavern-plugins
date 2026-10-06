// Persistent signing identity for this Mac. Never replaces an existing identity.
// Keys and configuration live outside the checkout; no login-keychain changes.
import Foundation
import Security
import CryptoKit
import Darwin

struct SigningFailure: Error, CustomStringConvertible {
    let description: String
}
func check(_ status: OSStatus, _ operation: String) throws {
    guard status == errSecSuccess else { throw SigningFailure(description: "\(operation) failed (Security \(status))") }
}
func run(_ executable: String, _ arguments: [String]) throws {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    // No credentials in arguments or command output.
    process.standardOutput = FileHandle.nullDevice
    process.standardError = executable == "/usr/bin/codesign" ? FileHandle.standardError : FileHandle.nullDevice
    try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        throw SigningFailure(description: "\(URL(fileURLWithPath: executable).lastPathComponent) failed (\(process.terminationStatus))")
    }
}
let fm = FileManager.default
let folder = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/PersonalDataHub/Signing")
let keychainPath = folder.appendingPathComponent("identity.keychain-db")
let passwordPath = folder.appendingPathComponent("keychain-password")
let certificatePath = folder.appendingPathComponent("certificate.pem")
let manifestPath = folder.appendingPathComponent("identity.json")
let identifier = "com.yuwk.personal-data-hub"

struct Identity: Codable {
    let certificateSHA1: String
    var requirement: String { "identifier \"\(identifier)\" and anchor = H\"\(certificateSHA1)\"" }
}
func privateWrite(_ data: Data, to url: URL) throws {
    try data.write(to: url, options: .atomic)
    try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
}
func openKeychain(_ password: Data) throws -> SecKeychain {
    var keychain: SecKeychain?
    try check(SecKeychainOpen(keychainPath.path, &keychain), "Open signing keychain")
    guard let keychain else { throw SigningFailure(description: "Signing keychain missing") }
    try password.withUnsafeBytes { bytes in
        try check(SecKeychainUnlock(keychain, UInt32(bytes.count), bytes.baseAddress, true), "Unlock signing keychain")
    }
    return keychain
}
func createIdentity() throws -> Identity {
    // An incomplete setup must be repaired explicitly, never silently rotate the key.
    guard !fm.fileExists(atPath: folder.path) else {
        throw SigningFailure(description: "Signing identity incomplete; preserve Signing directory and repair it before building")
    }
    let installed = fm.homeDirectoryForCurrentUser.appendingPathComponent("Applications/Personal Data Hub.app")
    if fm.fileExists(atPath: installed.path) {
        let inspection = Process(); let output = Pipe()
        inspection.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        inspection.arguments = ["-d", "-r-", installed.path]
        inspection.standardOutput = output; inspection.standardError = output
        try inspection.run()
        let text = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        inspection.waitUntilExit()
        guard !text.contains("certificate ") else {
            throw SigningFailure(description: "Installed app already has a certificate; restore its Signing directory instead of creating a new identity")
        }
    }
    try fm.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    var random = Data(count: 32)
    try random.withUnsafeMutableBytes { try check(SecRandomCopyBytes(kSecRandomDefault, $0.count, $0.baseAddress!), "Generate signing password") }
    let password = Data(random.map { String(format: "%02x", $0) }.joined().utf8)
    try privateWrite(password, to: passwordPath)
    let temporary = folder.appendingPathComponent("bootstrap-" + UUID().uuidString)
    try fm.createDirectory(at: temporary, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    defer { try? fm.removeItem(at: temporary) }
    let config = temporary.appendingPathComponent("openssl.cnf")
    let key = temporary.appendingPathComponent("key.pem")
    let p12 = temporary.appendingPathComponent("identity.p12")
    try privateWrite(Data("""
    [req]
    distinguished_name=subject
    x509_extensions=signing
    prompt=no
    [subject]
    CN=Personal Data Hub Local Signing
    [signing]
    basicConstraints=critical,CA:FALSE
    keyUsage=critical,digitalSignature
    extendedKeyUsage=critical,codeSigning
    subjectKeyIdentifier=hash
    """.utf8), to: config)
    try run("/usr/bin/openssl", ["req", "-new", "-x509", "-newkey", "rsa:3072", "-sha256", "-nodes", "-days", "3650",
                                 "-config", config.path, "-keyout", key.path, "-out", certificatePath.path])
    try run("/usr/bin/openssl", ["pkcs12", "-export", "-in", certificatePath.path, "-inkey", key.path, "-out", p12.path,
                                 "-passout", "file:" + passwordPath.path])
    var searchList: CFArray?
    try check(SecKeychainCopySearchList(&searchList), "Read keychain search list")
    var keychain: SecKeychain?
    try password.withUnsafeBytes { bytes in
        try check(SecKeychainCreate(keychainPath.path, UInt32(bytes.count), bytes.baseAddress, false, nil, &keychain), "Create signing keychain")
    }
    defer { if let searchList { _ = SecKeychainSetSearchList(searchList) } }
    guard let keychain else { throw SigningFailure(description: "Signing keychain creation failed") }
    var tool: SecTrustedApplication?
    try check(SecTrustedApplicationCreateFromPath("/usr/bin/codesign", &tool), "Authorize codesign")
    var access: SecAccess?
    try check(SecAccessCreate("Personal Data Hub signing key" as CFString, [tool!] as CFArray, &access), "Create signing ACL")
    let options: [String: Any] = [kSecImportExportPassphrase as String: String(decoding: password, as: UTF8.self),
                                  kSecImportExportKeychain as String: keychain, kSecImportExportAccess as String: access!]
    var items: CFArray?
    try check(SecPKCS12Import(try Data(contentsOf: p12) as CFData, options as CFDictionary, &items), "Import signing identity")
    guard let first = (items as? [[String: Any]])?.first,
          let value = first[kSecImportItemIdentity as String] else { throw SigningFailure(description: "Imported identity missing") }
    let identity = value as! SecIdentity
    var certificate: SecCertificate?
    try check(SecIdentityCopyCertificate(identity, &certificate), "Read signing certificate")
    let digest = Insecure.SHA1.hash(data: SecCertificateCopyData(certificate!) as Data)
    let result = Identity(certificateSHA1: digest.map { String(format: "%02x", $0) }.joined())
    try privateWrite(try JSONEncoder().encode(result), to: manifestPath)
    print("Created persistent Mac signing identity; private key stays in dedicated keychain")
    return result
}

do {
    umask(0o077)
    guard CommandLine.arguments.count == 2, CommandLine.arguments[1].hasSuffix(".app") else {
        throw SigningFailure(description: "Usage: swift signing.swift /absolute/App.app")
    }
    // Setup/signing uses only the dedicated keychain; never asks for a login password.
    try check(SecKeychainSetUserInteractionAllowed(false), "Disable signing prompts")
    let identity: Identity
    if fm.fileExists(atPath: manifestPath.path) {
        identity = try JSONDecoder().decode(Identity.self, from: Data(contentsOf: manifestPath))
    } else { identity = try createIdentity() }
    guard identity.certificateSHA1.count == 40, identity.certificateSHA1.allSatisfy({ $0.isHexDigit }) else {
        throw SigningFailure(description: "Invalid signing identity manifest")
    }
    let keychain = try openKeychain(Data(contentsOf: passwordPath))
    defer { _ = SecKeychainLock(keychain) }
    let app = CommandLine.arguments[1]
    try run("/usr/bin/codesign", ["--force", "--sign", identity.certificateSHA1, "--keychain", keychainPath.path,
                                  "--identifier", identifier, "--timestamp=none", "--requirements", "=designated => " + identity.requirement, app])
    try run("/usr/bin/codesign", ["--verify", "--strict", "--test-requirement", "=" + identity.requirement, app])
    print("Signed with persistent certificate \(identity.certificateSHA1)")
} catch {
    fputs("Persistent signing failed: \(error). No ad hoc fallback.\n", stderr)
    exit(1)
}
