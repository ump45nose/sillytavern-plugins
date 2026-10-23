import Foundation
import Security
import CryptoKit

enum CredentialStore {
    struct Failure: LocalizedError {
        let status: OSStatus
        var errorDescription: String? { "系统钥匙串访问失败（\(status)）。请解锁钥匙串并允许凭据助手访问。" }
    }
    struct Reply: Decodable { let status: OSStatus; let data: String? }
    static let reader = Connection.directory.appendingPathComponent("Personal Data Hub Credentials.app")
    static func call(_ operation: String, _ service: String, data: Data? = nil) throws -> Data? {
        // Pin the helper to this running client's certificate, not to a writable manifest.
        var own: SecCode?; var ownStatic: SecStaticCode?; var info: CFDictionary?
        guard SecCodeCopySelf([], &own) == errSecSuccess,
              SecCodeCopyStaticCode(own!, [], &ownStatic) == errSecSuccess,
              SecCodeCopySigningInformation(ownStatic!, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
              let certificates = (info as? [String: Any])?[kSecCodeInfoCertificates as String] as? [SecCertificate],
              let certificate = certificates.first else { throw Failure(status: errSecAuthFailed) }
        let digest = Insecure.SHA1.hash(data: SecCertificateCopyData(certificate) as Data).map { String(format: "%02x", $0) }.joined()
        var requirement: SecRequirement?; var code: SecStaticCode?
        guard SecRequirementCreateWithString("identifier \"com.yuwk.personal-data-hub.credential-reader\" and anchor = H\"\(digest)\"" as CFString, [], &requirement) == errSecSuccess,
              SecStaticCodeCreateWithPath(reader as CFURL, [], &code) == errSecSuccess,
              SecStaticCodeCheckValidity(code!, [], requirement) == errSecSuccess else { throw Failure(status: errSecAuthFailed) }
        var interaction = DarwinBoolean(false)
        guard SecKeychainGetUserInteractionAllowed(&interaction) == errSecSuccess else { throw Failure(status: errSecInteractionNotAllowed) }
        let process = Process(); let input = Pipe(); let output = Pipe()
        process.executableURL = reader.appendingPathComponent("Contents/MacOS/PersonalDataHubCredentialReader")
        process.arguments = [operation, service, interaction.boolValue ? "allow" : "deny"]
        process.standardInput = input; process.standardOutput = output; process.standardError = FileHandle.nullDevice
        try process.run()
        if let data { input.fileHandleForWriting.write(data) }
        try input.fileHandleForWriting.close()
        let result = output.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit()
        guard result.count <= 100_000, let reply = try? JSONDecoder().decode(Reply.self, from: result) else { throw Failure(status: errSecInternalError) }
        guard reply.status == errSecSuccess, process.terminationStatus == 0 else { throw Failure(status: reply.status) }
        return reply.data.flatMap { Data(base64Encoded: $0) }
    }
    static func read(_ service: String) throws -> Data {
        guard let data = try call("read", service) else { throw Failure(status: errSecDecode) }
        return data
    }
    static func write(_ service: String, _ data: Data) throws { _ = try call("write", service, data: data) }
}
