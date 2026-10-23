import AppKit
import HubKit

if let i = CommandLine.arguments.firstIndex(of: "--render-iconset"), i + 1 < CommandLine.arguments.count {
    do {
        try LogoImage.writeIconset(to: URL(fileURLWithPath: CommandLine.arguments[i + 1]))
        exit(0)
    } catch {
        fputs("Icon render failed: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

// `PersonalHub --mcp`: stdio MCP server for local agents. Stdout carries only JSON-RPC.
if CommandLine.arguments.contains("--mcp") {
    Task.detached { exit(await HubMCP.run()) }
    dispatchMain()
}

// Thin overlay scrollbars even when System Settings says "always show" or a mouse is attached;
// the argument domain outranks the global one and is never written to disk.
var arguments = UserDefaults.standard.volatileDomain(forName: UserDefaults.argumentDomain)
arguments["AppleShowScrollBars"] = "WhenScrolling"
UserDefaults.standard.setVolatileDomain(arguments, forName: UserDefaults.argumentDomain)

let app = NSApplication.shared

// `PersonalHub --agenda-smoke`: real-account acceptance check on a throwaway list (signed build only,
// since the credential helper only answers this app). Prints pass/fail lines, never content or tokens.
if CommandLine.arguments.contains("--agenda-smoke") {
    app.setActivationPolicy(.prohibited)
    Task.detached {
        guard let client = GoogleAccount.client(), let credential = try? CredentialStore.load().google else {
            print("FAIL credentials: Google not connected or credential helper unavailable")
            exit(2)
        }
        let transport = URLSessionTransport()
        let cache = AccessTokenCache(client: client, transport: transport) { credential.refreshToken }
        let checks = await AgendaSmoke.run(transport: transport, token: { try await cache.get(forceRefresh: $0) },
                                           workDir: FileManager.default.temporaryDirectory)
        for c in checks { print("\(c.ok ? "PASS" : "FAIL") \(c.name)\(c.detail.isEmpty ? "" : " — \(c.detail)")") }
        exit(checks.allSatisfy(\.ok) ? 0 : 1)
    }
    app.run()
}

// `PersonalHub --hub-token-stdin [URL]` stores a hub device token piped on stdin;
// `PersonalHub --hub-smoke` checks every hub endpoint the app reads. Both print only counts and statuses.
if let i = CommandLine.arguments.firstIndex(of: "--hub-token-stdin") {
    app.setActivationPolicy(.prohibited)
    let next = CommandLine.arguments.indices.contains(i + 1) ? URL(string: CommandLine.arguments[i + 1]) : nil
    let base = next.flatMap { $0.scheme?.hasPrefix("http") == true ? $0 : nil } ?? HubModel.defaultBase
    Task.detached { exit(await HubCLI.storeToken(base: base)) }
    app.run()
}
if CommandLine.arguments.contains("--hub-smoke") {
    app.setActivationPolicy(.prohibited)
    Task.detached { exit(await HubCLI.smoke()) }
    app.run()
}
if CommandLine.arguments.contains("--hub-subs-quota") {
    app.setActivationPolicy(.prohibited)
    Task.detached { exit(await HubCLI.subsQuota()) }
    app.run()
}
// `PersonalHub --hub-probe PATH [k=v ...]` prints the response's key paths and counts, never values.
if let i = CommandLine.arguments.firstIndex(of: "--hub-probe"), CommandLine.arguments.indices.contains(i + 1) {
    app.setActivationPolicy(.prohibited)
    let rest = CommandLine.arguments[(i + 2)...].prefix { !$0.hasPrefix("--") }
    let query = Dictionary(rest.compactMap { kv -> (String, String)? in
        let p = kv.split(separator: "=", maxSplits: 1).map(String.init)
        return p.count == 2 ? (p[0], p[1]) : nil
    }, uniquingKeysWith: { $1 })
    let path = CommandLine.arguments[i + 1]
    Task.detached { exit(await HubCLI.probe(path, query: query)) }
    app.run()
}

// `PersonalHub --hub-openapi FILTER` prints hub's API description for matching paths.
if let i = CommandLine.arguments.firstIndex(of: "--hub-openapi"), CommandLine.arguments.indices.contains(i + 1) {
    app.setActivationPolicy(.prohibited)
    let filter = CommandLine.arguments[i + 1]
    Task.detached { exit(await HubCLI.openAPI(filter)) }
    app.run()
}

if let i = CommandLine.arguments.firstIndex(of: "--hub-preview"), CommandLine.arguments.indices.contains(i + 1) {
    app.setActivationPolicy(.prohibited)
    let path = CommandLine.arguments[i + 1]
    let body = Dictionary(CommandLine.arguments[(i + 2)...].prefix { !$0.hasPrefix("--") }.compactMap { kv -> (String, String)? in
        let p = kv.split(separator: "=", maxSplits: 1).map(String.init)
        return p.count == 2 ? (p[0], p[1]) : nil
    }, uniquingKeysWith: { $1 })
    Task.detached { exit(await HubCLI.preview(path, body: body)) }
    app.run()
}

#if DEBUG
if let dir = CommandLine.value(after: "--qa-render") {
    app.setActivationPolicy(.prohibited)
    let now = CommandLine.value(after: "--qa-now").flatMap { text -> Date? in
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd'T'HH:mm"
        return f.date(from: text)
    }
    MainActor.assumeIsolated {
        Task {
            await QARender.run(to: URL(fileURLWithPath: dir), now: now)
            exit(0)
        }
    }
    app.run()
}
if CommandLine.arguments.contains("--qa-bench") {
    app.setActivationPolicy(.prohibited)
    MainActor.assumeIsolated {
        Task {
            await QABench.run()
            exit(0)
        }
    }
    app.run()
}
#endif

let delegate = MainActor.assumeIsolated { AppDelegate() }
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
