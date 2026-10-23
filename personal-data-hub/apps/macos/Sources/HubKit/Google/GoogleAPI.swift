import Foundation

public protocol HTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse)
}

public struct URLSessionTransport: HTTPTransport {
    private let session: URLSession

    public init(session: URLSession = URLSession(configuration: .ephemeral)) { self.session = session }

    public func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw GoogleAPIError.http(0) }
        return (data, http)
    }
}

public enum GoogleAPIError: Error, Equatable, Sendable {
    /// No usable credentials; the user must reconnect.
    case unauthorized
    case notFound
    /// Calendar sync token expired; a full sync is required.
    case gone
    case http(Int)
    /// Network unreachable or timed out; safe to retry later.
    case offline
    case invalidResponse

    /// Whether a queued change should stay queued and be retried.
    public var isTransient: Bool {
        switch self {
        case .offline, .unauthorized: true
        case .http(let code): code == 429 || code >= 500
        default: false
        }
    }
}

/// Typed access to the Google Tasks and Calendar REST APIs.
public struct GoogleAPI: Sendable {
    public typealias TokenSource = @Sendable (_ forceRefresh: Bool) async throws -> String

    private let transport: HTTPTransport
    private let token: TokenSource
    private let calendar: Calendar

    public init(transport: HTTPTransport, calendar: Calendar = .hub, token: @escaping TokenSource) {
        self.transport = transport
        self.token = token
        self.calendar = calendar
    }

    static let tasksBase = "https://tasks.googleapis.com/tasks/v1"
    static let calendarBase = "https://www.googleapis.com/calendar/v3"

    // MARK: Task lists

    public func taskLists() async throws -> [TaskListRecord] {
        try await pages(Self.tasksBase + "/users/@me/lists", query: ["maxResults": "100"]).map {
            TaskListRecord(id: $0["id"] as? String ?? "", title: $0["title"] as? String ?? "", updated: $0["updated"] as? String)
        }
    }

    public func insertList(title: String) async throws -> TaskListRecord {
        let d = try await json(Self.tasksBase + "/users/@me/lists", method: "POST", body: ["title": title])
        return TaskListRecord(id: d["id"] as? String ?? "", title: d["title"] as? String ?? title, updated: d["updated"] as? String)
    }

    public func renameList(id: String, title: String) async throws {
        _ = try await json(Self.tasksBase + "/users/@me/lists/" + path(id), method: "PATCH", body: ["title": title])
    }

    public func deleteList(id: String) async throws {
        _ = try await json(Self.tasksBase + "/users/@me/lists/" + path(id), method: "DELETE")
    }

    // MARK: Tasks

    /// With `updatedMin`, returns only changes since then, including deleted and hidden tasks.
    public func tasks(listID: String, updatedMin: String? = nil) async throws -> [TaskRecord] {
        var q = ["maxResults": "100", "showCompleted": "true", "showHidden": "true"]
        if let updatedMin {
            q["updatedMin"] = updatedMin
            q["showDeleted"] = "true"
        }
        return try await pages(Self.tasksBase + "/lists/\(path(listID))/tasks", query: q).map { TaskRecord(api: $0, listID: listID) }
    }

    public func insertTask(listID: String, title: String, notes: String?, due: String?, parent: String?) async throws -> TaskRecord {
        var body: [String: Any] = ["title": title]
        if let notes { body["notes"] = notes }
        if let due { body["due"] = Self.apiDue(due) }
        let q = parent.map { ["parent": $0] } ?? [:]
        let d = try await json(Self.tasksBase + "/lists/\(path(listID))/tasks", method: "POST", query: q, body: body)
        return TaskRecord(api: d, listID: listID)
    }

    public func patchTask(listID: String, id: String, patch: TaskPatch) async throws -> TaskRecord {
        let d = try await json(Self.tasksBase + "/lists/\(path(listID))/tasks/\(path(id))", method: "PATCH", body: patch.body)
        return TaskRecord(api: d, listID: listID)
    }

    public func deleteTask(listID: String, id: String) async throws {
        _ = try await json(Self.tasksBase + "/lists/\(path(listID))/tasks/\(path(id))", method: "DELETE")
    }

    /// Moves within a list (new parent) or to another list via `destinationList`.
    public func moveTask(listID: String, id: String, parent: String?, destinationList: String?) async throws -> TaskRecord {
        var q: [String: String] = [:]
        if let parent { q["parent"] = parent }
        if let destinationList { q["destinationTasklist"] = destinationList }
        let d = try await json(Self.tasksBase + "/lists/\(path(listID))/tasks/\(path(id))/move", method: "POST", query: q)
        return TaskRecord(api: d, listID: destinationList ?? listID)
    }

    static func apiDue(_ day: String) -> String { day + "T00:00:00.000Z" }

    // MARK: Calendar

    public func calendars() async throws -> [CalendarRecord] {
        try await pages(Self.calendarBase + "/users/me/calendarList", query: ["maxResults": "250"]).map(CalendarRecord.init(api:))
    }

    public struct EventPage: Sendable {
        public var events: [EventRecord]
        public var nextSyncToken: String?
    }

    /// Full sync from `timeMin` when `syncToken` is nil, otherwise incremental. Throws `.gone` when the token expired.
    public func events(calendarID: String, syncToken: String?, timeMin: Date) async throws -> EventPage {
        var q = ["singleEvents": "true", "maxResults": "2500"]
        if let syncToken { q["syncToken"] = syncToken } else { q["timeMin"] = GoogleDate.string(timeMin) }
        var items: [[String: Any]] = []
        var next: String?
        var seen = Set<String>()
        repeat {
            var page = q
            if let next { page["pageToken"] = next }
            let d = try await json(Self.calendarBase + "/calendars/\(path(calendarID))/events", query: page)
            items += d["items"] as? [[String: Any]] ?? []
            next = d["nextPageToken"] as? String
            if let token = d["nextSyncToken"] as? String {
                return EventPage(events: items.compactMap { EventRecord(api: $0, calendarID: calendarID, calendar: calendar) }, nextSyncToken: token)
            }
            if let next, !seen.insert(next).inserted { throw GoogleAPIError.invalidResponse }
        } while next != nil
        return EventPage(events: items.compactMap { EventRecord(api: $0, calendarID: calendarID, calendar: calendar) }, nextSyncToken: nil)
    }

    public func insertEvent(calendarID: String, draft: EventDraft) async throws -> EventRecord {
        try event(calendarID, try await json(Self.calendarBase + "/calendars/\(path(calendarID))/events", method: "POST", body: draft.body(calendar: calendar)))
    }

    public func patchEvent(calendarID: String, id: String, draft: EventDraft) async throws -> EventRecord {
        try event(calendarID, try await json(Self.calendarBase + "/calendars/\(path(calendarID))/events/\(path(id))", method: "PATCH",
                                             body: draft.body(calendar: calendar)))
    }

    public func deleteEvent(calendarID: String, id: String) async throws {
        _ = try await json(Self.calendarBase + "/calendars/\(path(calendarID))/events/\(path(id))", method: "DELETE")
    }

    public func moveEvent(calendarID: String, id: String, destination: String) async throws -> EventRecord {
        try event(destination, try await json(Self.calendarBase + "/calendars/\(path(calendarID))/events/\(path(id))/move",
                                              method: "POST", query: ["destination": destination]))
    }

    private func event(_ calendarID: String, _ d: [String: Any]) throws -> EventRecord {
        guard let e = EventRecord(api: d, calendarID: calendarID, calendar: calendar) else { throw GoogleAPIError.invalidResponse }
        return e
    }

    // MARK: Transport

    private func path(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/?#@"))) ?? s
    }

    private func pages(_ url: String, query: [String: String]) async throws -> [[String: Any]] {
        var q = query
        var items: [[String: Any]] = []
        var seen = Set<String>()
        while true {
            let d = try await json(url, query: q)
            items += d["items"] as? [[String: Any]] ?? []
            guard let next = d["nextPageToken"] as? String else { return items }
            guard seen.insert(next).inserted else { throw GoogleAPIError.invalidResponse }
            q["pageToken"] = next
        }
    }

    private func json(_ url: String, method: String = "GET", query: [String: String] = [:], body: [String: Any]? = nil) async throws -> [String: Any] {
        var c = URLComponents(string: url)!
        if !query.isEmpty { c.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        var request = URLRequest(url: c.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 25)
        request.httpMethod = method
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        var retried = false
        while true {
            request.setValue("Bearer " + (try await token(retried)), forHTTPHeaderField: "Authorization")
            let data: Data, response: HTTPURLResponse
            do {
                (data, response) = try await transport.send(request)
            } catch let error as GoogleAPIError {
                throw error
            } catch {
                throw GoogleAPIError.offline
            }
            switch response.statusCode {
            case 200..<300:
                guard !data.isEmpty else { return [:] }
                guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw GoogleAPIError.invalidResponse }
                return object
            case 401 where !retried:
                retried = true
            case 401: throw GoogleAPIError.unauthorized
            case 404: throw GoogleAPIError.notFound
            case 410: throw GoogleAPIError.gone
            default: throw GoogleAPIError.http(response.statusCode)
            }
        }
    }
}

/// Fields to change on a task; `due: .some(nil)` clears the date.
public struct TaskPatch: Codable, Equatable, Sendable {
    public var title: String?
    public var notes: String??
    public var due: String??
    public var completed: Bool?

    public init(title: String? = nil, notes: String?? = nil, due: String?? = nil, completed: Bool? = nil) {
        self.title = title
        self.notes = notes
        self.due = due
        self.completed = completed
    }

    private enum Keys: String, CodingKey { case title, notes, due, completed }

    /// Keeps "absent" (no change) distinct from `null` (clear) in the persisted queue.
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        completed = try c.decodeIfPresent(Bool.self, forKey: .completed)
        notes = c.contains(.notes) ? .some(try c.decodeNil(forKey: .notes) ? nil : try c.decode(String.self, forKey: .notes)) : nil
        due = c.contains(.due) ? .some(try c.decodeNil(forKey: .due) ? nil : try c.decode(String.self, forKey: .due)) : nil
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: Keys.self)
        try c.encodeIfPresent(title, forKey: .title)
        try c.encodeIfPresent(completed, forKey: .completed)
        if let notes { if let notes { try c.encode(notes, forKey: .notes) } else { try c.encodeNil(forKey: .notes) } }
        if let due { if let due { try c.encode(due, forKey: .due) } else { try c.encodeNil(forKey: .due) } }
    }

    var body: [String: Any] {
        var b: [String: Any] = [:]
        if let title { b["title"] = title }
        if let notes { b["notes"] = notes ?? NSNull() }
        if let due { b["due"] = due.map(GoogleAPI.apiDue) ?? NSNull() }
        if let completed {
            b["status"] = completed ? "completed" : "needsAction"
            if !completed { b["completed"] = NSNull() }
        }
        return b
    }
}
