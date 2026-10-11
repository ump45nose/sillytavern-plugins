import Foundation
import Security

struct Connection: Codable {
    var endpoint: String
    static let service = "com.yuwk.personal-data-hub.viewer"
    static let directory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PersonalDataHub", isDirectory: true)
    static let path = directory.appendingPathComponent("connection.json")

    static func load() -> Connection {
        (try? JSONDecoder().decode(Connection.self, from: Data(contentsOf: path)))
            ?? Connection(endpoint: "https://crm-home.172906573.xyz")
    }

    func baseURL() throws -> URL {
        guard let url = URL(string: endpoint.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "https", url.host != nil, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { throw HubError.invalidEndpoint }
        return url
    }

    static func keyQuery() -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: "archive"]
    }

    static func token() throws -> String {
        let data = try CredentialStore.read("viewer")
        guard let value = String(data: data, encoding: .utf8), !value.isEmpty else {
            throw HubError.credentials
        }
        return value
    }

    func save(token: String?) throws {
        _ = try baseURL()
        // 先保存凭据，失败时不覆盖连接配置。空输入保留原 Keychain 项。
        if let token = token, !token.isEmpty {
            try CredentialStore.write("viewer", Data(token.utf8))
        }
        try FileManager.default.createDirectory(at: Self.directory, withIntermediateDirectories: true,
                                               attributes: [.posixPermissions: 0o700])
        try JSONEncoder().encode(self).write(to: Self.path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: Self.path.path)
    }
}

enum HubError: LocalizedError {
    case invalidEndpoint, credentials, keychain, http(Int), response, integrity, redirect, readTimeout, network
    case contentChanged, contentRemoved
    var errorDescription: String? {
        switch self {
        case .invalidEndpoint: return "请输入有效的 HTTPS 服务地址。"
        case .credentials: return "请在连接设置中保存只读访问凭据。"
        case .keychain: return "无法保存到系统钥匙串。"
        case .http(401): return "访问凭据无效，请检查连接设置。"
        case .http(404): return "这条信息或附件已被删除。"
        case .contentChanged: return "正文已更新，请重新读取当前版本。"
        case .contentRemoved: return "这份内容已被删除。"
        case .http(let code): return "服务暂时无法完成请求（\(code)）。"
        case .response: return "服务返回了无法读取的数据。"
        case .integrity: return "附件校验失败，未保存文件。"
        case .redirect: return "服务地址发生跳转，请检查连接设置。"
        case .readTimeout: return "读取超时，请点击刷新重试。"
        case .network: return "暂时无法连接归档服务，请检查网络后重试。"
        }
    }
}

final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) { completionHandler(nil) }
}

struct HubAPI {
    let connection: Connection
    static let sharedSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 600
        return URLSession(configuration: config, delegate: NoRedirect(), delegateQueue: nil)
    }()
    let session: URLSession
    private let tokenProvider: () throws -> String
    init(_ connection: Connection, session: URLSession = Self.sharedSession,
         tokenProvider: @escaping () throws -> String = Connection.token) {
        self.connection = connection; self.session = session; self.tokenProvider = tokenProvider
    }

    func request(_ path: String, query: [URLQueryItem] = []) throws -> URLRequest {
        let base = try connection.baseURL()
        let url = base.appendingPathComponent(path)
        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { throw HubError.invalidEndpoint }
        if !query.isEmpty { components.queryItems = query }
        guard let endpoint = components.url else { throw HubError.invalidEndpoint }
        var request = URLRequest(url: endpoint)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("Bearer " + (try tokenProvider()), forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    func check(_ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { throw HubError.response }
        if (300..<400).contains(http.statusCode) { throw HubError.redirect }
        guard (200..<300).contains(http.statusCode) else { throw HubError.http(http.statusCode) }
    }

    func get<T: Decodable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        let (data, response): (Data, URLResponse)
        do { (data, response) = try await session.data(for: request(path, query: query)) }
        catch { throw Self.readError(error) }
        if let http = response as? HTTPURLResponse,
           let detail = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] {
            if http.statusCode == 409, detail["detail"] as? String == "content_changed" { throw HubError.contentChanged }
            if http.statusCode == 404, detail["detail"] as? String == "content_removed" { throw HubError.contentRemoved }
        }
        try check(response)
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw HubError.response }
    }

    func record(_ id: String) async throws -> RecordDetail {
        let (data, response): (Data, URLResponse)
        do { (data, response) = try await session.data(for: request("api/v1/records/" + id)) }
        catch { throw Self.readError(error) }
        try check(response)
        return try RecordDetail(data: data)
    }

    func download(_ asset: ArchiveAsset) async throws -> URL {
        let (url, response): (URL, URLResponse)
        do { (url, response) = try await session.download(for: request("api/v1/assets/" + asset.id)) }
        catch { throw Self.readError(error) }
        do { try check(response) } catch { try? FileManager.default.removeItem(at: url); throw error }
        return url
    }
    private static func readError(_ error: Error) -> Error {
        guard let failure = error as? URLError else { return error }
        if failure.code == .cancelled { return CancellationError() }
        return failure.code == .timedOut ? HubError.readTimeout : HubError.network
    }
}
