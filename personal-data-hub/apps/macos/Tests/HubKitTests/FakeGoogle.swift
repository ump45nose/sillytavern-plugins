import Foundation
@testable import HubKit

/// In-memory Google Tasks + Calendar server speaking just enough of the REST API.
final class FakeGoogle: HTTPTransport, @unchecked Sendable {
    private let lock = NSLock()
    var offline = false
    var lists: [[String: Any]] = []
    var tasks: [String: [[String: Any]]] = [:]
    var events: [String: [[String: Any]]] = [:]
    var calendars: [[String: Any]] = [["id": "me@example.com", "summary": "我", "primary": true, "selected": true, "accessRole": "owner"]]
    var revision = 0
    /// Events changed after this revision are returned for a sync token of that revision.
    var eventRevisions: [String: Int] = [:]
    var expiredTokens = false
    /// Simulates a grant with only calendar.events.owned: other calendars answer 404, as Google does.
    var ownedOnlyScope = false
    var failNext: [String: Int] = [:]
    private(set) var log: [String] = []
    private var counter = 0

    func locked<T>(_ body: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try body()
    }

    func addList(_ id: String, _ title: String) { locked { lists.append(["id": id, "title": title]); tasks[id] = [] } }

    func addTask(_ list: String, _ id: String, _ title: String, due: String? = nil, parent: String? = nil, updated: String = "2026-10-01T00:00:00Z") {
        locked {
            var t: [String: Any] = ["id": id, "title": title, "status": "needsAction", "updated": updated]
            if let due { t["due"] = due + "T00:00:00.000Z" }
            if let parent { t["parent"] = parent }
            tasks[list, default: []].append(t)
        }
    }

    func addEvent(_ id: String, _ title: String, start: String, end: String, cal: String = "me@example.com",
                  organizer: String? = nil, recurring: Bool = false) {
        locked {
            revision += 1
            var e: [String: Any] = ["id": id, "summary": title, "status": "confirmed", "start": ["dateTime": start], "end": ["dateTime": end]]
            if let organizer { e["organizer"] = ["email": organizer] }
            if recurring { e["recurringEventId"] = "series-" + id }
            events[cal, default: []].append(e)
            eventRevisions[id] = revision
        }
    }

    func cancelEvent(_ id: String, cal: String = "me@example.com") {
        locked {
            revision += 1
            if let i = events[cal]?.firstIndex(where: { $0["id"] as? String == id }) { events[cal]![i]["status"] = "cancelled" }
            eventRevisions[id] = revision
        }
    }

    func event(_ id: String, cal: String = "me@example.com") -> [String: Any]? {
        locked { events[cal]?.first { $0["id"] as? String == id } }
    }

    func task(_ list: String, titled title: String) -> [String: Any]? {
        locked { tasks[list]?.first { $0["title"] as? String == title } }
    }

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        try locked { () throws -> (Data, HTTPURLResponse) in
            let method = request.httpMethod ?? "GET"
            let url = request.url!
            let path = url.path
            log.append("\(method) \(path)" + (url.query.map { "?" + $0 } ?? ""))
            if offline { throw URLError(.notConnectedToInternet) }
            if let code = failNext.removeValue(forKey: "\(method) \(path)") { return respond(code, [:]) }
            let q = Dictionary((URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []).map { ($0.name, $0.value ?? "") }) { a, _ in a }
            let body = request.httpBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] } ?? [:]
            let parts = path.split(separator: "/").map { $0.removingPercentEncoding ?? String($0) }
            return route(method, Array(parts), q, body)
        }
    }

    private func nextID(_ prefix: String) -> String {
        counter += 1
        return "\(prefix)\(counter)"
    }

    private func route(_ m: String, _ p: [String], _ q: [String: String], _ body: [String: Any]) -> (Data, HTTPURLResponse) {
        // /tasks/v1/users/@me/lists[/id]
        if p.starts(with: ["tasks", "v1", "users", "@me", "lists"]) {
            if p.count == 5 {
                if m == "GET" { return respond(200, ["items": lists]) }
                let list: [String: Any] = ["id": nextID("L"), "title": body["title"] ?? ""]
                lists.append(list)
                tasks[list["id"] as! String] = []
                return respond(200, list)
            }
            let id = p[5]
            guard let i = lists.firstIndex(where: { $0["id"] as? String == id }) else { return respond(404, [:]) }
            if m == "DELETE" { lists.remove(at: i); tasks[id] = nil; return respond(204, nil) }
            lists[i]["title"] = body["title"]
            return respond(200, lists[i])
        }
        // /tasks/v1/lists/{list}/tasks[/{id}[/move]]
        if p.starts(with: ["tasks", "v1", "lists"]), p.count >= 5 {
            let list = p[3]
            guard tasks[list] != nil else { return respond(404, [:]) }
            if p.count == 5 {
                if m == "GET" {
                    var items = tasks[list]!
                    if let min = q["updatedMin"] { items = items.filter { ($0["updated"] as? String ?? "") >= min } }
                    if q["showDeleted"] != "true" { items = items.filter { $0["deleted"] as? Bool != true } }
                    return respond(200, ["items": items])
                }
                var t = body
                t["id"] = nextID("T")
                t["status"] = "needsAction"
                t["updated"] = stamp()
                if let parent = q["parent"] { t["parent"] = parent }
                tasks[list]!.append(t)
                return respond(200, t)
            }
            let id = p[5]
            guard let i = tasks[list]!.firstIndex(where: { $0["id"] as? String == id && $0["deleted"] as? Bool != true }) else { return respond(404, [:]) }
            if p.count == 7, p[6] == "move" {
                var t = tasks[list]![i]
                t["updated"] = stamp()
                if let parent = q["parent"] { t["parent"] = parent } else { t["parent"] = nil }
                if let dest = q["destinationTasklist"] {
                    tasks[list]![i]["deleted"] = true
                    tasks[list]![i]["updated"] = stamp()
                    tasks[dest, default: []].append(t)
                } else {
                    tasks[list]![i] = t
                }
                return respond(200, t)
            }
            if m == "DELETE" {
                tasks[list]![i]["deleted"] = true
                tasks[list]![i]["updated"] = stamp()
                return respond(204, nil)
            }
            for (k, v) in body { tasks[list]![i][k] = v is NSNull ? nil : v }
            tasks[list]![i]["updated"] = stamp()
            return respond(200, tasks[list]![i])
        }
        if p == ["calendar", "v3", "users", "me", "calendarList"] { return respond(200, ["items": calendars]) }
        // /calendar/v3/calendars/{id}/events[/{event}[/move]]
        if p.starts(with: ["calendar", "v3", "calendars"]), p.count >= 5, p[4] == "events" {
            let cal = p[3]
            let role = calendars.first(where: { $0["id"] as? String == cal })?["accessRole"] as? String
            if role == nil || (ownedOnlyScope && role != "owner") { return respond(404, [:]) }
            let writable = role == "owner" || role == "writer"
            if m != "GET", !writable { return respond(403, [:]) }
            func touch(_ id: String) { revision += 1; eventRevisions[id] = revision }
            if p.count == 5, m == "POST" {
                var e = body.filter { !($0.value is NSNull) }
                e["id"] = nextID("E")
                e["status"] = "confirmed"
                touch(e["id"] as! String)
                events[cal, default: []].append(e)
                return respond(200, e)
            }
            if p.count >= 6 {
                let id = p[5]
                guard let i = events[cal]?.firstIndex(where: { $0["id"] as? String == id }) else { return respond(404, [:]) }
                if events[cal]![i]["status"] as? String == "cancelled" { return respond(m == "DELETE" ? 410 : 404, [:]) }
                if p.count == 7, p[6] == "move", let dest = q["destination"] {
                    var e = events[cal]![i]
                    events[cal]![i]["status"] = "cancelled"
                    e["organizer"] = ["email": dest]
                    events[dest, default: []].append(e)
                    touch(id)
                    return respond(200, e)
                }
                if m == "DELETE" {
                    events[cal]![i]["status"] = "cancelled"
                    touch(id)
                    return respond(204, nil)
                }
                for (k, v) in body {
                    if var nested = v as? [String: Any] {
                        var merged = events[cal]![i][k] as? [String: Any] ?? [:]
                        for (nk, nv) in nested { merged[nk] = nv is NSNull ? nil : nv }
                        nested = merged
                        events[cal]![i][k] = nested
                    } else {
                        events[cal]![i][k] = v is NSNull ? nil : v
                    }
                }
                touch(id)
                return respond(200, events[cal]![i])
            }
            if let token = q["syncToken"] {
                if expiredTokens { return respond(410, [:]) }
                let since = Int(token.dropFirst(3)) ?? 0
                let changed = (events[cal] ?? []).filter { (eventRevisions[$0["id"] as! String] ?? 0) > since }
                return respond(200, ["items": changed, "nextSyncToken": "rev\(revision)"])
            }
            let live = (events[cal] ?? []).filter { $0["status"] as? String != "cancelled" }
            return respond(200, ["items": live, "nextSyncToken": "rev\(revision)"])
        }
        return respond(404, [:])
    }

    private func stamp() -> String {
        revision += 1
        return String(format: "2026-10-20T10:%02d:%02dZ", (revision / 60) % 60, revision % 60)
    }

    private func respond(_ code: Int, _ object: [String: Any]?) -> (Data, HTTPURLResponse) {
        let data = object.flatMap { try? JSONSerialization.data(withJSONObject: $0) } ?? Data()
        return (data, HTTPURLResponse(url: URL(string: "https://fake")!, statusCode: code, httpVersion: nil, headerFields: nil)!)
    }
}
