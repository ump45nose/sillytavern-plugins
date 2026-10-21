import Foundation

public enum HubError: Error, Equatable, Sendable {
    /// The device token was rejected or revoked; the user must sign in again.
    case unauthorized
    /// hub-api is unreachable; keep showing the cache.
    case offline
    case http(Int)
    case invalidResponse

    public var message: String {
        switch self {
        case .unauthorized: "hub 登录已失效"
        case .offline: "连不上 hub"
        case .http(409): "有冲突，未保存"
        case .http(503): "hub 未配置这个来源"
        case .http(let code): "hub 返回 \(code)"
        case .invalidResponse: "hub 返回了无法识别的数据"
        }
    }
}

public struct HubCredential: Codable, Equatable, Sendable {
    public var baseURL: URL
    public var token: String
    public var deviceID: String?

    public init(baseURL: URL, token: String, deviceID: String? = nil) {
        self.baseURL = baseURL
        self.token = token
        self.deviceID = deviceID
    }
}

/// Device sign-in (§4.3): the browser goes through Authelia, hub-api redirects a one-time code to
/// the loopback listener, and the code plus PKCE verifier is exchanged for a device token.
public enum HubSignIn {
    public static func startURL(base: URL, deviceName: String, redirect: String, pkce: OAuth.PKCE, state: String) -> URL? {
        guard var c = URLComponents(url: base.appendingPathComponent("/auth/start"), resolvingAgainstBaseURL: false) else { return nil }
        // Fully percent-encoded: NPM's block-exploits rule answers 403 to a raw `=http://` in the query.
        let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        let items = [("device_name", deviceName), ("redirect_uri", redirect), ("code_challenge", pkce.challenge),
                     ("code_challenge_method", "S256"), ("state", state)]
        c.percentEncodedQuery = items.map { "\($0.0)=\($0.1.addingPercentEncoding(withAllowedCharacters: unreserved) ?? "")" }.joined(separator: "&")
        return c.url
    }

    private struct Issued: Decodable { var deviceId: String?; var token: String }

    public static func exchange(base: URL, code: String, verifier: String, transport: HTTPTransport) async throws -> HubCredential {
        var r = URLRequest(url: base.appendingPathComponent("/auth/token"), timeoutInterval: 20)
        r.httpMethod = "POST"
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try JSONSerialization.data(withJSONObject: ["code": code, "code_verifier": verifier])
        let data: Data, response: HTTPURLResponse
        do { (data, response) = try await transport.send(r) } catch { throw HubError.offline }
        switch response.statusCode {
        case 200..<300: break
        case 400, 401, 403: throw HubError.unauthorized
        default: throw HubError.http(response.statusCode)
        }
        guard let issued = try? HubJSON.decoder.decode(Issued.self, from: data), !issued.token.isEmpty else { throw HubError.invalidResponse }
        return HubCredential(baseURL: base, token: issued.token, deviceID: issued.deviceId)
    }
}

/// Typed access to hub-api. Never logs URLs, headers or bodies.
public struct HubAPI: Sendable {
    private let transport: HTTPTransport
    public let credential: HubCredential

    public init(transport: HTTPTransport, credential: HubCredential) {
        self.transport = transport
        self.credential = credential
    }

    public func modules() async throws -> HubData {
        try decode(HubBatch.self, try await get("/api/v1/modules")).data
    }

    public func token(range: TokenRange) async throws -> HubEnvelope<TokenData> {
        try decode(HubEnvelope<TokenData>.self, try await get("/api/v1/modules/token", query: ["range": range.rawValue]))
    }

    public func status() async throws -> [HubSourceStatus] {
        try decode(HubStatusPage.self, try await get("/api/v1/status")).sources
    }

    public struct CreatedMemo: Decodable, Sendable { public var id: String }

    public func createMemo(content: String, visibility: String = "PRIVATE") async throws -> CreatedMemo {
        let data = try await send(request("/api/v1/memos", method: "POST", body: ["content": content, "visibility": visibility]))
        return try decode(CreatedMemo.self, data)
    }

    /// Image references from module data are opaque and signed by hub-api.
    public func image(ref: String) async throws -> Data {
        try await get("/api/v1/media/image", query: ["ref": ref])
    }

    /// For streaming players that send their own Range requests.
    public func audioRequest(recording id: String) throws -> URLRequest {
        try request("/api/v1/recordings/\(path(id))/audio")
    }

    public func transcript(recording id: String) async throws -> String {
        String(decoding: try await get("/api/v1/recordings/\(path(id))/transcript"), as: UTF8.self)
    }

    // MARK: Plumbing

    private func path(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? s
    }

    private func get(_ path: String, query: [String: String] = [:]) async throws -> Data {
        try await send(request(path, query: query))
    }

    func request(_ path: String, method: String = "GET", query: [String: String] = [:], body: [String: Any]? = nil) throws -> URLRequest {
        guard var c = URLComponents(url: credential.baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: false) else {
            throw HubError.invalidResponse
        }
        if !query.isEmpty { c.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        guard let url = c.url else { throw HubError.invalidResponse }
        var r = URLRequest(url: url, timeoutInterval: 20)
        r.httpMethod = method
        r.setValue("Bearer " + credential.token, forHTTPHeaderField: "Authorization")
        r.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            r.httpBody = try JSONSerialization.data(withJSONObject: body)
            r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return r
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let data: Data, response: HTTPURLResponse
        do { (data, response) = try await transport.send(request) } catch let e as HubError { throw e } catch { throw HubError.offline }
        switch response.statusCode {
        case 200..<300: return data
        case 401, 403: throw HubError.unauthorized
        default: throw HubError.http(response.statusCode)
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try HubJSON.decoder.decode(type, from: data) } catch { throw HubError.invalidResponse }
    }
}
