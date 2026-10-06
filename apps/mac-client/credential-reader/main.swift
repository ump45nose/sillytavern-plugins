// Version 1. This executable is installed once and preserved across UI updates.
// Credentials remain in the login keychain. Only a client signed by our certificate
// and bearing the exact GUI bundle identifier may use the private pipe protocol.
import Foundation
import Security
import CryptoKit
import Darwin

struct Reply: Codable { let status: OSStatus; let data: String? }
func reply(_ status: OSStatus, _ data: Data? = nil) -> Never {
    let payload = try! JSONEncoder().encode(Reply(status: status, data: data?.base64EncodedString()))
    FileHandle.standardOutput.write(payload)
    exit(status == errSecSuccess ? 0 : 1)
}
func check(_ status: OSStatus) { if status != errSecSuccess { reply(status) } }
let parent = getppid()
var own: SecCode?; var ownStatic: SecStaticCode?; var info: CFDictionary?
check(SecCodeCopySelf([], &own))
check(SecCodeCopyStaticCode(own!, [], &ownStatic))
check(SecCodeCopySigningInformation(ownStatic!, SecCSFlags(rawValue: kSecCSSigningInformation), &info))
guard let certificates = (info as? [String: Any])?[kSecCodeInfoCertificates as String] as? [SecCertificate],
      let certificate = certificates.first else { reply(errSecAuthFailed) }
let digest = Insecure.SHA1.hash(data: SecCertificateCopyData(certificate) as Data).map { String(format: "%02x", $0) }.joined()
var requirement: SecRequirement?
check(SecRequirementCreateWithString("identifier \"com.yuwk.personal-data-hub\" and anchor = H\"\(digest)\"" as CFString, [], &requirement))
var caller: SecCode?
check(SecCodeCopyGuestWithAttributes(nil, [kSecGuestAttributePid as String: parent] as CFDictionary, [], &caller))
check(SecCodeCheckValidity(caller!, [], requirement))
guard getppid() == parent, CommandLine.arguments.count == 4,
      ["read", "write"].contains(CommandLine.arguments[1]),
      ["allow", "deny"].contains(CommandLine.arguments[3]) else { reply(errSecParam) }
let services = ["viewer": ("com.yuwk.personal-data-hub.viewer", "archive"),
                "google": ("com.yuwk.personal-data-hub.google", "oauth")]
guard let (service, account) = services[CommandLine.arguments[2]] else { reply(errSecParam) }
check(SecKeychainSetUserInteractionAllowed(CommandLine.arguments[3] == "allow"))
let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                          kSecAttrService as String: service, kSecAttrAccount as String: account]
if CommandLine.arguments[1] == "read" {
    var request = query; request[kSecReturnData as String] = true
    var value: CFTypeRef?
    check(SecItemCopyMatching(request as CFDictionary, &value))
    guard let data = value as? Data, getppid() == parent else { reply(errSecAuthFailed) }
    reply(errSecSuccess, data)
} else {
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty, data.count <= 65_536 else { reply(errSecParam) }
    let attrs: [String: Any] = [kSecValueData as String: data,
                               kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
    let status = SecItemUpdate(query as CFDictionary, attrs as CFDictionary)
    if status == errSecItemNotFound {
        check(SecItemAdd(query.merging(attrs) { _, new in new } as CFDictionary, nil))
    } else { check(status) }
    reply(errSecSuccess)
}
