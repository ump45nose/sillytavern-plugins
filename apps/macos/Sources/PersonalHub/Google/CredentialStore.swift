import CryptoKit
import Foundation
import HubKit
import Security

/// Reads and writes the Google refresh token through the fixed credential helper, so the
/// login keychain never sees a new CDHash when the app itself is rebuilt.
enum CredentialStore {
    struct Failure: LocalizedError {
        let status: OSStatus
        var errorDescription: String? {
            switch status {
            case errSecCSReqFailed, errSecAuthFailed: "凭据助手校验失败（\(status)）。请用 scripts/build.sh --install 安装正式版本。"
            case errSecInteractionNotAllowed: "钥匙串已锁定，解锁后重试。"
            default: "系统钥匙串访问失败（\(status)）。"
            }
        }
    }

    private struct Reply: Decodable { let status: OSStatus; let data: String? }

    static let helper = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PersonalHub/Personal Hub Credentials.app")

    static func load() throws -> StoredCredential? {
        do {
            guard let data = try call("read") else { return nil }
            return try JSONDecoder().decode(StoredCredential.self, from: data)
        } catch let failure as Failure where failure.status == errSecItemNotFound {
            return nil
        }
    }

    static func save(_ credential: StoredCredential) throws {
        _ = try call("write", input: try JSONEncoder().encode(credential))
    }

    static func delete() throws { _ = try call("delete") }

    private static func call(_ operation: String, input: Data? = nil) throws -> Data? {
        // Pin the helper to this running app's certificate rather than to a writable manifest.
        var own: SecCode?, ownStatic: SecStaticCode?, info: CFDictionary?
        guard SecCodeCopySelf([], &own) == errSecSuccess,
              SecCodeCopyStaticCode(own!, [], &ownStatic) == errSecSuccess,
              SecCodeCopySigningInformation(ownStatic!, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
              let certificates = (info as? [String: Any])?[kSecCodeInfoCertificates as String] as? [SecCertificate],
              let certificate = certificates.first else { throw Failure(status: errSecAuthFailed) }
        let digest = Insecure.SHA1.hash(data: SecCertificateCopyData(certificate) as Data).map { String(format: "%02x", $0) }.joined()
        var requirement: SecRequirement?, code: SecStaticCode?
        guard SecRequirementCreateWithString("identifier \"com.yuwk.personal-hub.credentials\" and anchor = H\"\(digest)\"" as CFString, [], &requirement) == errSecSuccess,
              SecStaticCodeCreateWithPath(helper as CFURL, [], &code) == errSecSuccess,
              SecStaticCodeCheckValidity(code!, [], requirement) == errSecSuccess else { throw Failure(status: errSecCSReqFailed) }

        var interaction = DarwinBoolean(false)
        guard SecKeychainGetUserInteractionAllowed(&interaction) == errSecSuccess else { throw Failure(status: errSecInteractionNotAllowed) }
        let process = Process(), stdin = Pipe(), stdout = Pipe()
        process.executableURL = helper.appendingPathComponent("Contents/MacOS/PersonalHubCredentials")
        process.arguments = [operation, interaction.boolValue ? "allow" : "deny"]
        process.standardInput = stdin
        process.standardOutput = stdout
        process.standardError = FileHandle.nullDevice
        try process.run()
        if let input { stdin.fileHandleForWriting.write(input) }
        try stdin.fileHandleForWriting.close()
        let result = stdout.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        guard result.count <= 100_000, let reply = try? JSONDecoder().decode(Reply.self, from: result) else { throw Failure(status: errSecInternalError) }
        guard reply.status == errSecSuccess, process.terminationStatus == 0 else { throw Failure(status: reply.status) }
        return reply.data.flatMap { Data(base64Encoded: $0) }
    }
}
