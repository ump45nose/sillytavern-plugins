import Foundation
import Testing
@testable import HubKit

/// Serves canned hub-api responses shaped like the live service.
final class FakeHub: HTTPTransport, @unchecked Sendable {
    private let lock = NSLock()
    var offline = false
    var statusCode = 200
    var breakModule: String?
    /// Whether this hub has shipped `/api/v1/net/plans`.
    var plans = false
    /// Whether this hub has shipped the Memos list, PATCH and DELETE.
    var memosCRUD = false
    private(set) var paths: [String] = []
    private(set) var authorizations: [String?] = []
    private(set) var bodies: [[String: Any]] = []

    func locked<T>(_ body: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body()
    }

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (offline, code, broken, plans, crud) = locked { (self.offline, statusCode, breakModule, self.plans, self.memosCRUD) }
        if offline { throw URLError(.notConnectedToInternet) }
        let url = request.url!
        let path = url.path + (url.query.map { "?" + $0 } ?? "")
        locked {
            paths.append(path)
            authorizations.append(request.value(forHTTPHeaderField: "Authorization"))
            if let b = request.httpBody, let o = try? JSONSerialization.jsonObject(with: b) as? [String: Any] { bodies.append(o) }
        }
        let response = HTTPURLResponse(url: url, statusCode: code, httpVersion: nil, headerFields: nil)!
        guard code == 200 else { return (Data(), response) }
        let body: String
        switch url.path {
        case "/api/v1/modules":
            body = Self.batch.replacingOccurrences(of: broken.map { "\"\($0)\": {\"module\"" } ?? "\u{0}", with: "\"\(broken ?? "")\": {\"modulex\"")
        case "/api/v1/modules/token":
            let range = url.query?.replacingOccurrences(of: "range=", with: "") ?? "day"
            body = Self.token(range)
        case "/api/v1/status": body = Self.status
        case "/api/v1/memos" where request.httpMethod == "GET":
            guard crud else { return (Data(), HTTPURLResponse(url: url, statusCode: 405, httpVersion: nil, headerFields: nil)!) }
            body = #"{"items": [{"id": "m1", "created_at": "\#(Self.stamp)", "updated_at": "\#(Self.stamp)", "content": "第一条 #想法", "tags": ["想法"], "visibility": "PRIVATE", "pinned": true, "url": null, "attachments": [{"name": "attachments/1", "filename": "a.png", "type": "image/png"}]}], "next_page_token": "p2"}"#
        case "/api/v1/memos": body = #"{"id": "abc", "created_at": "2026-10-20T18:00:00.123456+08:00"}"#
        case let p where p.hasPrefix("/api/v1/memos/") && crud:
            if request.httpMethod == "DELETE" { return (Data(), HTTPURLResponse(url: url, statusCode: 204, httpVersion: nil, headerFields: nil)!) }
            body = #"{"id": "m1", "created_at": "\#(Self.stamp)", "content": "改过了", "tags": [], "visibility": "PUBLIC", "pinned": false, "url": null}"#
        case "/api/v1/net/plans" where plans:
            body = request.httpMethod == "PUT" ? String(decoding: request.httpBody ?? Data(), as: UTF8.self)
                : #"{"items": [{"id": "main", "name": "主套餐", "total_bytes": 214748364800, "reset_day": 1, "expires_on": null}]}"#
        default: return (Data(), HTTPURLResponse(url: url, statusCode: 404, httpVersion: nil, headerFields: nil)!)
        }
        return (Data(body.utf8), response)
    }

    static let stamp = "2026-10-20T17:57:41.512345+08:00"

    static func token(_ range: String) -> String {
        #"{"module": "token", "status": "ok", "updated_at": "\#(stamp)", "sources": [], "data": {"range": "\#(range)", "period": {"start": "2026-10-14", "end": "2026-10-20"}, "total": 182300000, "previous": null, "cost": 4.2, "tools": null, "devices": null, "buckets": {"unit": "hour", "rows": "date", "series": [{"key": "2026-10-14", "values": [null, 12000, null]}]}, "limits": [{"tool": "Codex", "plan": "Pro", "windows": [{"label": "5 小时", "percent": 42, "resets_at": "2026-10-20T20:00:00+08:00"}]}], "today": {"total": 25000000, "cost": 56.7}}}"#
    }

    static let status = #"{"sources": [{"id": "records_health", "name": "健康", "status": "ok", "last_success": "\#(stamp)", "last_error": null, "latency_ms": 41}, {"id": "github", "name": "GitHub", "status": "unconfigured", "last_success": null, "last_error": null, "latency_ms": null}, {"id": "usage", "name": "usage-monitor", "status": "error", "last_success": null, "last_error": {"type": "timeout", "status_code": null}, "latency_ms": 5003}]}"#

    static let batch = #"""
    {"modules": {
      "health": {"module": "health", "status": "ok", "updated_at": "\#(stamp)", "sources": [{"id": "records_health", "status": "ok", "updated_at": "\#(stamp)"}],
        "data": {"date": "2026-10-20", "steps": null, "active_kcal": null, "exercise_minutes": null, "sleep_minutes": 452.5, "sleep_stages": null, "resting_hr": null, "spo2": null,
                 "step_goal": 8600, "kcal_goal": 520, "exercise_goal": 45, "days": [{"date": "2026-10-19", "steps": 9100, "resting_hr": 60.5, "sleep_minutes": null}, {"date": "2026-10-20", "steps": null, "resting_hr": null, "sleep_minutes": null}]}},
      "bills": {"module": "bills", "status": "ok", "updated_at": "\#(stamp)", "sources": [],
        "data": {"date": "2026-10-20", "today_total": 0.0, "month_total": 3260.4, "month_budget": null, "days_left_in_month": 11, "today_items": [], "days": [{"date": "2026-10-20", "total": 0.0}],
                 "month_categories": [{"name": "餐饮", "amount": 980.2}], "net_worth": null, "net_worth_months": null, "accounts": null}},
      "crm": {"module": "crm", "status": "ok", "updated_at": "\#(stamp)", "sources": [],
        "data": {"today": [{"id": "x", "person_id": "p", "name": "张三", "relation": null, "channel": "微信", "time": "2026-10-20T15:30:00+08:00", "summary": "…", "recording": {"id": "plaud:2026-10-20:0123456789abcdef0123456789abcdef", "title": null, "duration_seconds": 1520}}],
                 "cycle": {"start": "2026-09-09", "days": 42, "people": 23, "interactions": 61, "recordings": 9}, "stale": [{"person_id": "q", "name": "李四", "days": 47}]}},
      "media": {"module": "media", "status": "partial", "updated_at": "\#(stamp)", "sources": [],
        "data": {"continue_watching": [{"id": "1", "title": "繁花", "subtitle": null, "image": "ref1", "link": "https://emby", "progress": 0.42}], "latest": null, "recent_albums": [],
                 "downloads": [{"id": "d", "title": "x", "progress": 1, "state": "downloading", "speed_bps": 2400000, "eta_seconds": null}], "services": [{"id": "emby", "status": "ok", "link": "https://emby"}, {"id": "navidrome", "status": "error", "link": null}]}},
      "token": \#(token("day")),
      "net": {"module": "net", "status": "partial", "updated_at": "\#(stamp)", "sources": [], "data": {"pools": null, "today": {"up_bytes": 10, "down_bytes": 20}, "month_bytes": 300, "hourly": [{"hour": "2026-10-20T00:00:00+08:00", "bytes": 5}, {"hour": "2026-10-20T01:00:00+08:00", "bytes": null}]}},
      "memos": {"module": "memos", "status": "ok", "updated_at": "\#(stamp)", "sources": [], "data": {"recent": [{"id": "m", "created_at": "\#(stamp)", "content": "hi #想法", "tags": ["想法"], "visibility": "PRIVATE", "url": "https://memos"}], "tags": [{"name": "想法", "count": 3}]}},
      "git": {"module": "git", "status": "unconfigured", "updated_at": null, "sources": [], "data": null},
      "subs": {"module": "subs", "status": "unconfigured", "updated_at": null, "sources": [], "data": null},
      "attention": {"module": "attention", "status": "unconfigured", "updated_at": null, "sources": [], "data": null}
    }}
    """#
}

private let credential = HubCredential(baseURL: URL(string: "http://hub.test:18190")!, token: "sentinel-token")

private func makeSync(_ hub: FakeHub, file: URL? = nil) async -> HubSync {
    let sync = HubSync(file: file)
    await sync.connect(api: HubAPI(transport: hub, credential: credential))
    return sync
}

@Test func batchDecodesLiveShapesWithNulls() async throws {
    let hub = FakeHub()
    let data = try await HubAPI(transport: hub, credential: credential).modules()
    #expect(data.health?.status == .ok)
    #expect(data.health?.updatedAt == HubJSON.parseDate("2026-10-20T17:57:41.512+08:00"))
    #expect(data.health?.data?.steps == nil)
    #expect(data.health?.data?.sleepMinutes == 452.5)
    #expect(data.health?.data?.days?.first?.restingHr == 60.5)
    #expect(data.bills?.data?.todayTotal == 0)
    #expect(data.crm?.data?.today?.first?.recording?.durationSeconds == 1520)
    #expect(data.media?.data?.latest == nil)
    #expect(data.media?.data?.downloads?.first?.progress == 1)
    #expect(data.net?.data?.pools == nil)
    #expect(data.net?.data?.hourly?.last?.bytes == nil)
    #expect(data.token[.day]?.data?.limits?.first?.windows.first?.percent == 42)
    #expect(data.git?.status == .unconfigured && data.git?.data == nil)
    #expect(hub.locked { hub.authorizations.allSatisfy { $0 == "Bearer sentinel-token" } })
}

@Test func oneMalformedModuleLeavesTheOthers() async throws {
    let hub = FakeHub()
    hub.locked { hub.breakModule = "bills" }
    let data = try await HubAPI(transport: hub, credential: credential).modules()
    #expect(data.bills == nil)
    #expect(data.health?.status == .ok)
    #expect(data.memos?.data?.recent?.count == 1)
}

@Test func refreshFetchesEveryTokenRangeAndSourceStatus() async {
    let hub = FakeHub()
    let sync = await makeSync(hub)
    await sync.refresh()
    #expect(await sync.status == .idle)
    let s = await sync.snapshot
    #expect(Set(s.token.keys) == Set(TokenRange.allCases))
    #expect(s.token[.year]?.data?.range == .year)
    #expect(s.sources.count == 3)
    #expect(s.sources.last?.lastError?.type == "timeout")
    #expect(s.fetchedAt != nil)
    #expect(hub.locked { hub.paths.contains("/api/v1/modules/token?range=month") })
}

@Test func offlineKeepsTheCacheAndRejectedTokenAsksToSignIn() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("hub-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: dir) }
    let file = dir.appendingPathComponent("hub.json")
    let hub = FakeHub()
    let sync = await makeSync(hub, file: file)
    await sync.refresh()
    let perms = try FileManager.default.attributesOfItem(atPath: file.path)[.posixPermissions] as? Int
    #expect(perms == 0o600)
    #expect(!(try String(contentsOf: file, encoding: .utf8)).contains("sentinel-token"))

    hub.locked { hub.offline = true }
    await sync.refresh()
    #expect(await sync.status == .offline)
    #expect(await sync.snapshot.health?.status == .ok)

    // A relaunch while offline shows the cached copy straight away.
    let reopened = HubSync(file: file)
    #expect(await reopened.snapshot.memos?.data?.recent?.first?.content == "hi #想法")

    hub.locked { hub.offline = false; hub.statusCode = 401 }
    await sync.refresh()
    #expect(await sync.status == .needsSignIn)
    #expect(await sync.snapshot.crm != nil)
}

@Test func postingAMemoSendsContentAndVisibility() async throws {
    let hub = FakeHub()
    let created = try await HubAPI(transport: hub, credential: credential).createMemo(content: "记一条 #想法")
    #expect(created.id == "abc")
    let body = hub.locked { hub.bodies.last }
    #expect(body?["content"] as? String == "记一条 #想法")
    #expect(body?["visibility"] as? String == "PRIVATE")
}

@Test func netPlansAreOptionalUntilHubShipsThem() async throws {
    let hub = FakeHub()
    let api = HubAPI(transport: hub, credential: credential)
    #expect(try await api.netPlans() == nil)

    hub.locked { hub.plans = true }
    let plans = try #require(try await api.netPlans())
    #expect(plans == [NetPlan(id: "main", name: "主套餐", totalBytes: 200 * 1_073_741_824)])

    let saved = try await api.putNetPlans([NetPlan(id: "a", name: "机场", totalBytes: 500, resetDay: 15, expiresOn: "2026-12-31")])
    #expect(saved.first?.resetDay == 15 && saved.first?.expiresOn == "2026-12-31")
    let item = (hub.locked { hub.bodies.last }?["items"] as? [[String: Any]])?.first
    #expect(item?["total_bytes"] as? Double == 500)
    #expect(item?["reset_day"] as? Int == 15)
}

@Test func pythonTimestampsParse() {
    #expect(HubJSON.parseDate("2026-10-20T17:57:41.512345+08:00") != nil)
    #expect(HubJSON.parseDate("2026-10-20T17:57:41+08:00") != nil)
    #expect(HubJSON.parseDate("2026-10-20T09:57:41.5Z") != nil)
    #expect(HubJSON.parseDate("2026-10-20") == nil)
}

@Test func signInURLEncodesTheLoopbackRedirect() throws {
    let pkce = OAuth.PKCE.make()
    let url = try #require(HubSignIn.startURL(base: URL(string: "https://hub.example:28443")!, deviceName: "玮康的 MacPro",
                                              redirect: "http://127.0.0.1:5555/callback", pkce: pkce, state: "s+1/2"))
    let query = try #require(url.query(percentEncoded: true))
    #expect(url.path() == "/auth/start")
    #expect(!query.contains("http://"), "NPM block-exploits rejects a raw URL in the query")
    #expect(query.contains("redirect_uri=http%3A%2F%2F127.0.0.1%3A5555%2Fcallback"))
    let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
    #expect(items.first { $0.name == "device_name" }?.value == "玮康的 MacPro")
    #expect(items.first { $0.name == "state" }?.value == "s+1/2")
    #expect(items.first { $0.name == "code_challenge" }?.value == pkce.challenge)
}

@Test func sampleDataRoundTripsThroughTheCacheFormat() throws {
    let data = HubSample.data(now: HubJSON.parseDate("2026-10-20T17:58:00+08:00")!)
    let decoded = try HubJSON.decoder.decode(HubData.self, from: HubJSON.encoder.encode(data))
    #expect(decoded.token.count == 4)
    #expect(decoded.health?.data == data.health?.data)
    #expect(decoded.git?.data?.activity == data.git?.data?.activity)
}

@Test func memosCRUDWaitsForHubAndSendsOnlyChangedFields() async throws {
    let hub = FakeHub()
    let api = HubAPI(transport: hub, credential: credential)
    #expect(try await api.memos() == nil, "405 beside the existing POST means no list yet")
    await #expect(throws: HubError.self) { _ = try await api.updateMemo(id: "m1", pinned: true) }

    hub.locked { hub.memosCRUD = true }
    let page = try #require(try await api.memos(pageToken: "p1", tag: "想法", query: "第一"))
    #expect(page.nextPageToken == "p2" && page.items.first?.pinned == true && page.items.first?.attachments?.count == 1)
    let listed = try #require(hub.locked { hub.paths.last })
    #expect(listed.contains("page_token=p1") && listed.contains("page_size=20") && listed.contains("q=") && listed.contains("tag="))

    let saved = try await api.updateMemo(id: "m1", visibility: "PUBLIC")
    #expect(saved.visibility == "PUBLIC")
    #expect(hub.locked { hub.bodies.last }?.keys.sorted() == ["visibility"])
    try await api.archiveMemo(id: "m1")
    #expect(hub.locked { hub.paths.last } == "/api/v1/memos/m1")
}
