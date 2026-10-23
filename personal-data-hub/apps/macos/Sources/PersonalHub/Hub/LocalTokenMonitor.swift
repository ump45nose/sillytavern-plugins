import AppKit
import Darwin
import Foundation
import HubKit

/// Transport to the current user's Token Monitor. It never reads provider credentials.
final class LocalTokenMonitor: NSObject, URLSessionTaskDelegate {
    struct Provider: Decodable, Identifiable {
        var id: String, name: String, methods: [String]
        var multiple: Bool
    }
    struct Account: Decodable, Identifiable {
        var binding: SubscriptionBinding
        var label: String
        var plan: String?
        var id: String { binding.provider + ":" + binding.account }
    }
    struct Connection: Decodable {
        struct Workspace: Decodable, Identifiable { var id: String, label: String }
        var id: String, provider: String, status: String
        var phase: String?
        var loginUrl: String?, userCode: String?
        var workspaces: [Workspace]?
        var account: Account?
        var syncStatus: String?, error: String?
        var terminal: Bool { ["succeeded", "failed", "cancelled", "expired"].contains(status) }
    }
    struct Problem: LocalizedError {
        var code: String
        var errorDescription: String? {
            switch code {
            case "unavailable": "Token Monitor 尚未运行，或当前版本没有本机账号接口。启动后重试；原版 0.75.0 需要更新。"
            case "replacement_required": "这个平台只支持一个账号，请确认替换现有连接。订阅台账会保留。"
            case "too_late": "账号正在保存，请等待连接完成。"
            case "login_in_progress": "Token Monitor 正在连接这个平台，请先完成或取消现有操作。"
            case "local_mode_required": "Claude 必须使用 Token Monitor 的本地桌面模式。这里不会切换到在线采集。"
            case "runtime_unavailable": "Token Monitor 采集进程尚未就绪，请稍后重试。"
            case "account_unavailable": "尚未发现该账号，请先完成本机登录，或选择一个已有账号。"
            case "invalid_credential": "凭据未通过验证，请检查后重试。"
            case "login_expired", "connection_expired": "连接已过期，请重新开始。"
            default: "连接未完成，请检查 Token Monitor 后重试。"
            }
        }
    }
    private struct Discovery: Decodable { var version: Int, port: Int, token: String, pid: Int }
    private struct Failure: Decodable { var error: String }
    private let endpoint: Discovery
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.timeoutIntervalForRequest = 15
        config.connectionProxyDictionary = [:]
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    init(directory: URL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Token Monitor")) throws {
        let file = directory.appendingPathComponent("local-account-control.json")
        let descriptor = open(file.path, O_RDONLY | O_NOFOLLOW)
        guard descriptor >= 0 else { throw Problem(code: "unavailable") }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0, metadata.st_uid == getuid(), metadata.st_mode & 0o077 == 0,
              metadata.st_mode & S_IFMT == S_IFREG, metadata.st_size > 0, metadata.st_size <= 4096,
              let discovery = try? JSONDecoder().decode(Discovery.self, from: handle.readDataToEndOfFile()),
              discovery.version == 1, (1024...65535).contains(discovery.port),
              discovery.token.count == 64, discovery.token.allSatisfy(\.isHexDigit), discovery.pid > 0,
              kill(Int32(discovery.pid), 0) == 0 else { throw Problem(code: "unavailable") }
        endpoint = discovery
        super.init()
    }

    func capabilities() async throws -> [Provider] {
        struct Reply: Decodable { var version: Int, providers: [Provider] }
        let reply: Reply = try await send("GET", "/v1/capabilities")
        guard reply.version == 1 else { throw Problem(code: "unavailable") }
        return reply.providers
    }
    func accounts() async throws -> [Account] {
        struct Reply: Decodable { var accounts: [Account] }
        let reply: Reply = try await send("GET", "/v1/accounts")
        return reply.accounts
    }
    func connect(_ body: [String: Any]) async throws -> Connection { try await send("POST", "/v1/connections", body: body) }
    func status(_ id: String) async throws -> Connection { try await send("GET", try connectionPath(id)) }
    func cancel(_ id: String) async throws -> Connection { try await send("DELETE", try connectionPath(id)) }
    func select(_ id: String, workspace: String) async throws -> Connection {
        try await send("POST", try connectionPath(id) + "/selection", body: ["workspaceId": workspace])
    }
    private func connectionPath(_ id: String) throws -> String {
        guard UUID(uuidString: id) != nil else { throw Problem(code: "connection_expired") }
        return "/v1/connections/" + id
    }
    private func send<T: Decodable>(_ method: String, _ path: String, body: [String: Any]? = nil) async throws -> T {
        let url = URL(string: "http://127.0.0.1:\(endpoint.port)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer " + endpoint.token, forHTTPHeaderField: "Authorization")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, data.count <= 262144 else { throw Problem(code: "invalid_response") }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard (200..<300).contains(http.statusCode) else {
            throw Problem(code: (try? decoder.decode(Failure.self, from: data).error) ?? "connection_failed")
        }
        return try decoder.decode(T.self, from: data)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }

    @MainActor static func launch() {
        let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.javis.tokenmonitor")
            ?? URL(fileURLWithPath: "/Applications/Token Monitor.app")
        let configuration = NSWorkspace.OpenConfiguration(); configuration.activates = false
        NSWorkspace.shared.openApplication(at: url, configuration: configuration) { _, _ in }
    }
}
