import AppKit
import Foundation
import HubKit

enum GoogleAccount {
    enum Failure: LocalizedError {
        case missingConfig, noRefreshToken, missingScopes, wrongAccount(String?)

        var errorDescription: String? {
            switch self {
            case .missingConfig: "应用里没有 Google OAuth 客户端配置。请重新构建安装。"
            case .noRefreshToken: "Google 没有返回长期授权，请重试。"
            case .missingScopes: "授权时没有勾选全部权限（任务、日历），请重试并全部允许。"
            case .wrongAccount(let got): "登录的账号\(got.map { "（\($0)）" } ?? "")不是配置里指定的账号。"
            }
        }
    }

    /// Client info only: the bundled file never contains user tokens (build.sh rejects them).
    static func client() -> OAuthClient? {
        var candidates = [Bundle.main.url(forResource: "google-oauth", withExtension: "json")]
        #if DEBUG
        candidates.append(FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/PersonalDataHub/google-desktop-config.json"))
        #endif
        for url in candidates.compactMap({ $0 }) {
            if let data = try? Data(contentsOf: url), let client = try? JSONDecoder().decode(OAuthClient.self, from: data) { return client }
        }
        return nil
    }

    /// Browser sign-in with PKCE over a 127.0.0.1 redirect. Returns the credential to persist.
    static func authorize(client: OAuthClient, transport: HTTPTransport) async throws -> StoredCredential {
        let state = UUID().uuidString, pkce = OAuth.PKCE.make()
        let receiver = try LoopbackReceiver(state: state)
        let redirect = Box()
        let code = try await receiver.code { uri in
            redirect.value = uri
            let url = OAuth.authorizationURL(client: client, redirect: uri, pkce: pkce, state: state)
            DispatchQueue.main.async { NSWorkspace.shared.open(url) }
        }
        let token = try await OAuth.token(OAuth.exchangeRequest(client: client, code: code, redirect: redirect.value, verifier: pkce.verifier),
                                          transport: transport)
        guard let refresh = token.refreshToken else { throw Failure.noRefreshToken }
        let granted = Set((token.scope ?? "").split(separator: " ").map(String.init))
        guard granted.isSuperset(of: OAuth.scopes) else {
            await revoke(refresh, transport: transport)
            throw Failure.missingScopes
        }
        let api = GoogleAPI(transport: transport) { _ in token.accessToken }
        let primary = try await api.calendars().first(where: \.primary)?.id
        if let expected = client.expectedAccount, primary?.lowercased() != expected.lowercased() {
            await revoke(refresh, transport: transport)
            throw Failure.wrongAccount(primary)
        }
        return StoredCredential(refreshToken: refresh, account: primary, scope: token.scope)
    }

    static func revoke(_ token: String, transport: HTTPTransport) async {
        _ = try? await transport.send(OAuth.revokeRequest(token: token))
    }

    private final class Box: @unchecked Sendable {
        var value = ""
    }
}
