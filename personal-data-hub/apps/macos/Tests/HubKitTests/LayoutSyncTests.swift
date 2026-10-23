import Foundation
import Testing
@testable import HubKit

private func api(_ hub: ScriptedHub) -> HubAPI {
    HubAPI(transport: hub, credential: HubCredential(baseURL: URL(string: "http://hub.test")!, token: "t"))
}

private func json(_ doc: LayoutDocument) -> String {
    String(decoding: try! JSONEncoder().encode(doc), as: UTF8.self)
}

private func row(_ version: Int, _ doc: LayoutDocument?) -> String {
    #"{"version": \#(version), "updated_at": "2026-10-21T15:00:00+08:00", "document": \#(doc.map(json) ?? #"{"version": 1, "pages": [{"id": "home", "title": "主页", "subtitle": "", "kind": "grid", "items": [{"module": "weather", "size": "compact"}]}]}"#)}"#
}

private var custom: LayoutDocument {
    var doc = LayoutDocument.default
    doc.addPage(title: "阅读", id: "page-reading")
    return doc
}

@Test func firstDeviceUploadsItsLayout() async throws {
    let hub = ScriptedHub { r in r.httpMethod == "GET" ? (404, #"{"detail": "Not Found"}"#) : (200, row(1, custom)) }
    let out = try await LayoutSync.run(api: api(hub), local: custom, state: LayoutSyncState())
    #expect(out == .init(adopt: nil, state: LayoutSyncState(version: 1, dirty: false)))
    let put = try #require(hub.requests.last)
    #expect(put.method == "PUT" && put.ifMatch == "0")
    let pages = (put.body?["document"] as? [String: Any])?["pages"] as? [[String: Any]]
    #expect(pages?.last?["id"] as? String == "page-reading" && pages?.last?["kind"] as? String == "grid")
}

@Test func aNewerHubLayoutIsAdopted() async throws {
    let hub = ScriptedHub { _ in (200, row(4, custom)) }
    let out = try await LayoutSync.run(api: api(hub), local: .default, state: LayoutSyncState(version: 3))
    #expect(out.adopt == custom && out.state == LayoutSyncState(version: 4))
    #expect(hub.requests.count == 1, "reading only")

    let same = try await LayoutSync.run(api: api(hub), local: custom, state: LayoutSyncState(version: 4))
    #expect(same.adopt == nil && hub.requests.count == 2)
}

@Test func aCustomizedMacKeepsItsLayoutOnFirstContact() async throws {
    let hub = ScriptedHub { r in r.httpMethod == "GET" ? (200, row(2, .default)) : (200, row(3, custom)) }
    let out = try await LayoutSync.run(api: api(hub), local: custom, state: LayoutSyncState())
    #expect(out.adopt == nil && out.state == LayoutSyncState(version: 3))
    #expect(hub.requests.last?.ifMatch == "2")
}

@Test func unsentEditsWinAConflict() async throws {
    let hub = ScriptedHub { r in
        r.value(forHTTPHeaderField: "If-Match") == "5"
            ? (409, #"{"error": {"code": "conflict", "message": "conflict"}, "current": \#(row(6, .default))}"#)
            : (200, row(7, custom))
    }
    let out = try await LayoutSync.run(api: api(hub), local: custom, state: LayoutSyncState(version: 5, dirty: true))
    #expect(out.state == LayoutSyncState(version: 7))
    #expect(hub.requests.map(\.ifMatch) == ["5", "6"])
}

@Test func anUnreadableHubLayoutIsNeverOverwritten() async throws {
    let reading = ScriptedHub { _ in (200, row(9, nil)) }
    let quiet = try await LayoutSync.run(api: api(reading), local: custom, state: LayoutSyncState(version: 8))
    #expect(quiet.adopt == nil && quiet.state == LayoutSyncState(version: 8))
    #expect(reading.requests.count == 1)

    let writing = ScriptedHub { _ in (409, #"{"error": {"code": "conflict", "message": "conflict"}, "current": \#(row(9, nil))}"#) }
    let held = try await LayoutSync.run(api: api(writing), local: custom, state: LayoutSyncState(version: 8, dirty: true))
    #expect(held.state == LayoutSyncState(version: 8, dirty: true))
    #expect(writing.requests.count == 1)
}
