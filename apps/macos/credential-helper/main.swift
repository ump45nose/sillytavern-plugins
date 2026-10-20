// Version 1. Built and signed once by scripts/install-credentials.sh, then never rebuilt:
// the login keychain trusts this exact binary, so changing it would prompt for every item.
// Only a parent signed as com.yuwk.personal-hub with this helper's certificate may talk to it.
// Protocol: argv = [read|write|delete, allow|deny]; write takes the secret on stdin;
// stdout is one JSON object {"status": OSStatus, "data": base64?}.
import CryptoKit
import Darwin
import Foundation
import Security

struct Reply: Codable { let status: OSStatus; let data: String? }

func reply(_ status: OSStatus, _ data: Data? = nil) -> Never {
    let payload = try! JSONEncoder().encode(Reply(status: status, data: data?.base64EncodedString()))
    FileHandle.standardOutput.write(payload)
    exit(status == errSecSuccess ? 0 : 1)
}

func check(_ status: OSStatus) { if status != errSecSuccess { reply(status) } }

let parent = getppid()
var own: SecCode?, ownStatic: SecStaticCode?, info: CFDictionary?
check(SecCodeCopySelf([], &own))
check(SecCodeCopyStaticCode(own!, [], &ownStatic))
check(SecCodeCopySigningInformation(ownStatic!, SecCSFlags(rawValue: kSecCSSigningInformation), &info))
guard let certificates = (info as? [String: Any])?[kSecCodeInfoCertificates as String] as? [SecCertificate],
      let certificate = certificates.first else { reply(errSecAuthFailed) }
let digest = Insecure.SHA1.hash(data: SecCertificateCopyData(certificate) as Data).map { String(format: "%02x", $0) }.joined()
var requirement: SecRequirement?
check(SecRequirementCreateWithString("identifier \"com.yuwk.personal-hub\" and anchor = H\"\(digest)\"" as CFString, [], &requirement))
var caller: SecCode?
check(SecCodeCopyGuestWithAttributes(nil, [kSecGuestAttributePid as String: parent] as CFDictionary, [], &caller))
check(SecCodeCheckValidity(caller!, [], requirement))

let arguments = CommandLine.arguments
guard getppid() == parent, arguments.count == 3,
      ["read", "write", "delete"].contains(arguments[1]),
      ["allow", "deny"].contains(arguments[2]) else { reply(errSecParam) }
check(SecKeychainSetUserInteractionAllowed(arguments[2] == "allow"))

let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                            kSecAttrService as String: "com.yuwk.personal-hub.google",
                            kSecAttrAccount as String: "oauth"]
switch arguments[1] {
case "read":
    var request = query
    request[kSecReturnData as String] = true
    var value: CFTypeRef?
    check(SecItemCopyMatching(request as CFDictionary, &value))
    guard let data = value as? Data, getppid() == parent else { reply(errSecAuthFailed) }
    reply(errSecSuccess, data)
case "write":
    let data = FileHandle.standardInput.readDataToEndOfFile()
    guard !data.isEmpty, data.count <= 65_536 else { reply(errSecParam) }
    let attrs: [String: Any] = [kSecValueData as String: data,
                                kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
    let status = SecItemUpdate(query as CFDictionary, attrs as CFDictionary)
    if status == errSecItemNotFound {
        check(SecItemAdd(query.merging(attrs) { _, new in new } as CFDictionary, nil))
    } else {
        check(status)
    }
    reply(errSecSuccess)
default:
    let status = SecItemDelete(query as CFDictionary)
    reply(status == errSecItemNotFound ? errSecSuccess : status)
}
