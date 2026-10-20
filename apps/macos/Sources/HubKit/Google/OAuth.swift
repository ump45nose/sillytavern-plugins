import CryptoKit
import Foundation
import Network

/// Desktop OAuth client settings bundled with the app; never contains user tokens.
public struct OAuthClient: Codable, Sendable, Equatable {
    public var clientID: String
    public var clientSecret: String?
    /// Primary calendar ID (the account email) the user is expected to sign in with.
    public var expectedAccount: String?

    enum CodingKeys: String, CodingKey {
        case clientID = "client_id", clientSecret = "client_secret", expectedAccount = "expected_calendar"
    }

    public init(clientID: String, clientSecret: String? = nil, expectedAccount: String? = nil) {
        self.clientID = clientID
        self.clientSecret = clientSecret
        self.expectedAccount = expectedAccount
    }
}

/// What the credential store keeps for the signed-in account.
public struct StoredCredential: Codable, Sendable, Equatable {
    public var refreshToken: String
    public var account: String?
    public var scope: String?

    public init(refreshToken: String, account: String? = nil, scope: String? = nil) {
        self.refreshToken = refreshToken
        self.account = account
        self.scope = scope
    }
}

public enum OAuth {
    public static let scopes = [
        "https://www.googleapis.com/auth/tasks",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    ]

    static let authEndpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    static let tokenEndpoint = "https://oauth2.googleapis.com/token"

    public struct PKCE: Sendable {
        public var verifier: String
        public var challenge: String

        public static func make() -> PKCE {
            var bytes = [UInt8](repeating: 0, count: 32)
            _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
            let verifier = base64URL(Data(bytes))
            return PKCE(verifier: verifier, challenge: base64URL(Data(SHA256.hash(data: Data(verifier.utf8)))))
        }
    }

    static func base64URL(_ d: Data) -> String {
        d.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    public static func authorizationURL(client: OAuthClient, redirect: String, pkce: PKCE, state: String) -> URL {
        var c = URLComponents(string: authEndpoint)!
        var items = [
            "client_id": client.clientID, "redirect_uri": redirect, "response_type": "code",
            "scope": scopes.joined(separator: " "), "access_type": "offline", "prompt": "consent",
            "code_challenge": pkce.challenge, "code_challenge_method": "S256", "state": state,
        ]
        if let hint = client.expectedAccount { items["login_hint"] = hint }
        c.queryItems = items.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) }
        return c.url!
    }

    public struct TokenResponse: Decodable, Sendable {
        public var accessToken: String
        public var expiresIn: Double?
        public var refreshToken: String?
        public var scope: String?

        enum CodingKeys: String, CodingKey {
            case accessToken = "access_token", expiresIn = "expires_in", refreshToken = "refresh_token", scope
        }
    }

    public static func exchangeRequest(client: OAuthClient, code: String, redirect: String, verifier: String) -> URLRequest {
        form(["client_id": client.clientID, "client_secret": client.clientSecret ?? "", "code": code,
              "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier])
    }

    public static func refreshRequest(client: OAuthClient, refreshToken: String) -> URLRequest {
        form(["client_id": client.clientID, "client_secret": client.clientSecret ?? "",
              "refresh_token": refreshToken, "grant_type": "refresh_token"])
    }

    private static func form(_ values: [String: String]) -> URLRequest {
        var r = URLRequest(url: URL(string: tokenEndpoint)!, timeoutInterval: 25)
        r.httpMethod = "POST"
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "-._~"))
        r.httpBody = values.sorted { $0.key < $1.key }
            .map { "\($0.key)=\($0.value.addingPercentEncoding(withAllowedCharacters: allowed) ?? "")" }
            .joined(separator: "&").data(using: .utf8)
        r.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        return r
    }

    public static func token(_ request: URLRequest, transport: HTTPTransport) async throws -> TokenResponse {
        let data: Data, response: HTTPURLResponse
        do { (data, response) = try await transport.send(request) } catch { throw GoogleAPIError.offline }
        switch response.statusCode {
        case 200: break
        case 400, 401: throw GoogleAPIError.unauthorized
        default: throw GoogleAPIError.http(response.statusCode)
        }
        guard let t = try? JSONDecoder().decode(TokenResponse.self, from: data) else { throw GoogleAPIError.invalidResponse }
        return t
    }
}

/// Caches the short-lived access token and refreshes it from the stored refresh token.
public actor AccessTokenCache {
    private let client: OAuthClient
    private let transport: HTTPTransport
    private let refreshToken: @Sendable () throws -> String?
    private var token: String?
    private var expiry = Date.distantPast
    private var inflight: Task<(String, Date), Error>?

    public init(client: OAuthClient, transport: HTTPTransport, refreshToken: @escaping @Sendable () throws -> String?) {
        self.client = client
        self.transport = transport
        self.refreshToken = refreshToken
    }

    public func get(forceRefresh: Bool = false) async throws -> String {
        if !forceRefresh, let token, expiry > Date() { return token }
        if let inflight { return try await inflight.value.0 }
        let task = Task { [client, transport, refreshToken] () throws -> (String, Date) in
            guard let refresh = try refreshToken() else { throw GoogleAPIError.unauthorized }
            let r = try await OAuth.token(OAuth.refreshRequest(client: client, refreshToken: refresh), transport: transport)
            return (r.accessToken, Date().addingTimeInterval((r.expiresIn ?? 3600) - 60))
        }
        inflight = task
        defer { inflight = nil }
        let (value, until) = try await task.value
        token = value
        expiry = until
        return value
    }

    public func reset() {
        token = nil
        expiry = .distantPast
    }
}

/// One-shot HTTP listener on 127.0.0.1 that receives the OAuth redirect.
public final class LoopbackReceiver: @unchecked Sendable {
    private let listener: NWListener
    private let state: String
    private let queue = DispatchQueue(label: "hub.oauth.loopback")
    private var continuation: CheckedContinuation<String, Error>?

    public enum Failure: Error, Sendable { case denied, timeout, listener }

    public init(state: String) throws {
        self.state = state
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        listener = try NWListener(using: parameters)
    }

    /// Calls `ready` with the redirect URI once listening, then waits for the authorization code.
    public func code(timeout: TimeInterval = 300, ready: @escaping @Sendable (String) -> Void) async throws -> String {
        try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<String, Error>) in
                queue.async { [self] in
                    continuation = c
                    listener.stateUpdateHandler = { [weak self] status in
                        guard let self else { return }
                        switch status {
                        case .ready: if let port = listener.port?.rawValue { ready("http://127.0.0.1:\(port)") }
                        case .failed: finish(.failure(Failure.listener))
                        default: break
                        }
                    }
                    listener.newConnectionHandler = { [weak self] connection in self?.handle(connection) }
                    listener.start(queue: queue)
                    queue.asyncAfter(deadline: .now() + timeout) { [weak self] in self?.finish(.failure(Failure.timeout)) }
                }
            }
        } onCancel: { [weak self] in
            self?.queue.async { self?.finish(.failure(CancellationError())) }
        }
    }

    private func handle(_ connection: NWConnection) {
        connection.start(queue: queue)
        connection.receive(minimumIncompleteLength: 1, maximumLength: 16384) { [weak self] data, _, _, _ in
            guard let self else { return }
            let request = String(decoding: data ?? Data(), as: UTF8.self)
            let target = request.split(separator: " ").dropFirst().first.map(String.init) ?? ""
            let items = URLComponents(string: "http://127.0.0.1" + target)?.queryItems ?? []
            let values = Dictionary(items.map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
            let matches = values["state"] == state
            let code = matches ? values["code"] : nil
            let page = code != nil
                ? "<h3>Personal Hub 已连接 Google</h3><p>可以关闭此页面，回到应用。</p>"
                : "<h3>授权没有完成</h3><p>请回到 Personal Hub 重试。</p>"
            let body = Data("<!doctype html><meta charset=utf-8><body style=\"font:15px -apple-system;padding:40px\">\(page)".utf8)
            let header = "HTTP/1.1 \(code != nil ? "200 OK" : "400 Bad Request")\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
            connection.send(content: Data(header.utf8) + body, completion: .contentProcessed { _ in connection.cancel() })
            // Stray localhost requests (favicon, probes) must not end the flow.
            guard matches else { return }
            finish(code.map { .success($0) } ?? .failure(Failure.denied))
        }
    }

    private func finish(_ result: Result<String, Error>) {
        guard let c = continuation else { return }
        continuation = nil
        listener.cancel()
        c.resume(with: result)
    }
}
