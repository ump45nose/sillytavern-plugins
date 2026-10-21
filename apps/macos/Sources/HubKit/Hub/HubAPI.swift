import Foundation

public enum HubError: Error, Equatable, Sendable {
    /// The device token was rejected or revoked; the user must sign in again.
    case unauthorized
    /// hub-api is unreachable; keep showing the cache.
    case offline
    case http(Int)
    case invalidResponse
    /// A source rule refused the content (422); `message` is the source's own wording.
    case rejected(String, field: String?)
    /// The review session's window has closed (409 `expired`).
    case expired

    public var message: String {
        switch self {
        case .unauthorized: "hub 登录已失效"
        case .offline: "连不上 hub"
        case .rejected(let message, _): message
        case .expired: "这次复盘已经过期，不能再确认"
        case .http(502): "来源写入失败，可以稍后重试"
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

    /// nil while hub-api has no list endpoint yet (404, or 405 beside the existing POST).
    public func memos(pageSize: Int = 20, pageToken: String? = nil, tag: String? = nil, query: String? = nil) async throws -> MemoPage? {
        var q = ["page_size": String(pageSize)]
        if let pageToken { q["page_token"] = pageToken }
        if let tag, !tag.isEmpty { q["tag"] = tag }
        if let query, !query.isEmpty { q["q"] = query }
        let (data, response) = try await exchange(request("/api/v1/memos", query: q))
        if response.statusCode == 404 || response.statusCode == 405 { return nil }
        return try decode(MemoPage.self, try check(data, response))
    }

    /// Only the fields given are sent.
    public func updateMemo(id: String, content: String? = nil, visibility: String? = nil, pinned: Bool? = nil) async throws -> MemosData.Memo {
        var body: [String: Any] = [:]
        if let content { body["content"] = content }
        if let visibility { body["visibility"] = visibility }
        if let pinned { body["pinned"] = pinned }
        return try decode(MemosData.Memo.self, try await send(request("/api/v1/memos/\(path(id))", method: "PATCH", body: body)))
    }

    /// hub archives rather than deletes; the memo can be restored in Memos.
    public func archiveMemo(id: String) async throws {
        _ = try await send(request("/api/v1/memos/\(path(id))", method: "DELETE"))
    }

    /// Image references from module data are opaque and signed by hub-api.
    public func image(ref: String) async throws -> Data {
        try await get("/api/v1/media/image", query: ["ref": ref])
    }

    /// For streaming players that send their own Range requests.
    public func audioRequest(recording id: String) throws -> URLRequest {
        try request("/api/v1/recordings/\(path(id))/audio")
    }

    /// nil while hub-api has no list endpoint yet (404 or 405 on the bare collection).
    public func plaudRecordings(before: String? = nil, limit: Int = 14) async throws -> PlaudList? {
        var query = ["source": "plaud", "limit": String(limit)]
        if let before { query["before"] = before }
        let (data, response) = try await exchange(request("/api/v1/recordings", query: query))
        if response.statusCode == 404 || response.statusCode == 405 { return nil }
        return try decode(PlaudList.self, try check(data, response))
    }

    public func transcript(recording id: String) async throws -> String {
        String(decoding: try await get("/api/v1/recordings/\(path(id))/transcript"), as: UTF8.self)
    }

    // MARK: Review & stage (phase 5)

    public func reviewSessions(kind: ReviewKind, limit: Int = 14) async throws -> [ReviewSummary] {
        try decode(ReviewPage.self, try await get("/api/v1/review/sessions", query: ["kind": kind.rawValue, "limit": String(limit)])).items
    }

    public func reviewSession(id: String) async throws -> ReviewSession {
        try decode(ReviewSession.self, try await get("/api/v1/review/sessions/\(path(id))"))
    }

    /// The final text personal-review would store (health and finance filled in), or `.rejected`.
    public func previewReview(id: String, content: String) async throws -> String {
        let data = try await send(request("/api/v1/review/sessions/\(path(id))/preview", method: "POST", body: ["content": content]))
        return try decode(ReviewPreview.self, data).content
    }

    public func finalizeReview(id: String, content: String) async throws -> ReviewFinalized {
        let data = try await send(request("/api/v1/review/sessions/\(path(id))/finalize", method: "POST", body: ["content": content]))
        return try decode(ReviewFinalized.self, data)
    }

    public func commentGoal(id: String, text: String, dryRun: Bool) async throws -> StageResult {
        try await stage("/api/v1/stage/goals/\(path(id))/comments", ["text": text, "dry_run": dryRun])
    }

    public func closeCycle(id: String, text: String, outcomes: [String: String], dryRun: Bool) async throws -> StageResult {
        try await stage("/api/v1/stage/cycles/\(path(id))/close", ["text": text, "outcomes": outcomes, "dry_run": dryRun])
    }

    public func createCycle(dryRun: Bool) async throws -> StageResult {
        try await stage("/api/v1/stage/cycles", ["dry_run": dryRun])
    }

    public func addGoal(cycle id: String, _ draft: GoalDraft, dryRun: Bool) async throws -> StageResult {
        try await stage("/api/v1/stage/cycles/\(path(id))/goals", [
            "domain": draft.domain, "goal": draft.goal, "progress": draft.progress, "deadline": draft.deadline,
            "success_criteria": draft.successCriteria, "stop_signal": draft.stopSignal, "dry_run": dryRun,
        ])
    }

    private func stage(_ path: String, _ body: [String: Any]) async throws -> StageResult {
        try decode(StageResult.self, try await send(request(path, method: "POST", body: body)))
    }

    // MARK: Layout (§5.5)

    /// nil when no device has stored a layout yet.
    public func layout() async throws -> RemoteLayout? {
        let (data, response) = try await exchange(request("/api/v1/layout"))
        if response.statusCode == 404 { return nil }
        return try decode(RemoteLayout.self, try check(data, response))
    }

    /// Optimistic write: `version` is the one last read (0 for the first write).
    public func putLayout(_ document: LayoutDocument, version: Int) async throws -> LayoutWrite {
        let encoded = try JSONEncoder().encode(document)
        guard let object = try JSONSerialization.jsonObject(with: encoded) as? [String: Any] else { throw HubError.invalidResponse }
        var r = try request("/api/v1/layout", method: "PUT", body: ["document": object])
        r.setValue(String(version), forHTTPHeaderField: "If-Match")
        let (data, response) = try await exchange(r)
        if response.statusCode == 409 {
            struct Conflict: Decodable { var current: RemoteLayout? }
            return .conflict(try decode(Conflict.self, data).current)
        }
        return .saved(try decode(RemoteLayout.self, try check(data, response)).version)
    }

    // MARK: Network plans

    /// nil while hub-api has no plan endpoint yet (404).
    public func netPlans() async throws -> [NetPlan]? {
        let (data, response) = try await exchange(request("/api/v1/net/plans"))
        if response.statusCode == 404 { return nil }
        return try decode(NetPlans.self, try check(data, response)).items
    }

    public func putNetPlans(_ items: [NetPlan]) async throws -> [NetPlan] {
        let body: [String: Any] = ["items": items.map { p -> [String: Any] in
            var item: [String: Any] = ["id": p.id, "name": p.name, "total_bytes": p.totalBytes, "reset_day": p.resetDay]
            item["expires_on"] = p.expiresOn ?? NSNull()
            return item
        }]
        return try decode(NetPlans.self, try await send(request("/api/v1/net/plans", method: "PUT", body: body))).items
    }

    private struct NetPlans: Decodable { var items: [NetPlan] }

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
        let (data, response) = try await exchange(request)
        return try check(data, response)
    }

    private func exchange(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        do { return try await transport.send(request) } catch let e as HubError { throw e } catch { throw HubError.offline }
    }

    private func check(_ data: Data, _ response: HTTPURLResponse) throws -> Data {
        switch response.statusCode {
        case 200..<300: return data
        case 401, 403: throw HubError.unauthorized
        case 409 where Self.problem(data)?.code == "expired": throw HubError.expired
        case 422: throw HubError.rejected(Self.problem(data)?.message ?? "内容没有通过校验", field: Self.problem(data)?.field)
        case 400, 404, 409:
            guard let problem = Self.problem(data), let message = problem.message else { throw HubError.http(response.statusCode) }
            throw HubError.rejected(message, field: problem.field)
        default: throw HubError.http(response.statusCode)
        }
    }

    private struct Problem: Decodable {
        struct Body: Decodable { var code: String?; var message: String?; var field: String? }
        var error: Body
    }

    private static func problem(_ data: Data) -> Problem.Body? {
        try? HubJSON.decoder.decode(Problem.self, from: data).error
    }

    private func decode<T: Decodable>(_ type: T.Type, _ data: Data) throws -> T {
        do { return try HubJSON.decoder.decode(type, from: data) } catch { throw HubError.invalidResponse }
    }
}
