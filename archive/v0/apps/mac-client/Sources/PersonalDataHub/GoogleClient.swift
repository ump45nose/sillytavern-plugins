import AppKit
import CryptoKit
import Foundation
import Network
import Security

enum GoogleError: LocalizedError {
    case unconfigured, clientConfigurationMissing, browserUnavailable, authorizationTimeout, unauthorized, request(Int), conflict, invalid, callback, timeout, wrongAccount, keychain(OSStatus)
    var errorDescription: String? {
        switch self {
        case .keychain(let status): return "系统钥匙串暂不能读取 Google 凭据（\(status)）。请解锁钥匙串并允许凭据助手访问。无需重新进行浏览器授权。"
        case .wrongAccount: return "请选择与 NAS 采集相同的 Google 账号。"
        case .unconfigured: return "Google 尚未连接。请在设置中连接 Google。"
        case .clientConfigurationMissing: return "这台 Mac 缺少 Google 连接配置，暂时无法打开授权页。请先完成设备的 Google 连接设置。"
        case .browserUnavailable: return "无法打开 Google 授权页，请检查默认浏览器后重试。"
        case .authorizationTimeout: return "等待 Google 授权超时，请再次连接并在浏览器中完成授权。"
        case .unauthorized: return "Google 授权已失效，请重新连接。"
        case .request(let code): return "Google 请求失败（\(code)）。草稿已保留。"
        case .conflict: return "内容已在其他设备修改，请刷新后重新编辑。"
        case .invalid: return "请检查标题、日期和清单。"
        case .callback: return "Google 授权未完成，请重试。"
        case .timeout: return "请求结果暂未确认，请刷新查看后再提交。"
        }
    }
}
enum GoogleKeychain {
    static let service = "com.yuwk.personal-data-hub.google"
    static func read(_ account: String) throws -> Data {
        guard account == "oauth" else { throw GoogleError.invalid }
        do { return try CredentialStore.read("google") }
        catch let error as CredentialStore.Failure {
            if error.status == errSecItemNotFound { throw GoogleError.unconfigured }
            throw GoogleError.keychain(error.status)
        }
    }
    static func write(_ account: String, _ data: Data) throws {
        guard account == "oauth" else { throw GoogleError.invalid }
        try CredentialStore.write("google", data)
    }
}
struct GoogleList: Codable, Identifiable {
    let id: String; let title: String; let etag: String
}
struct GoogleCalendar: Codable, Identifiable {
    let id: String; let title: String; let owned: Bool; let primary: Bool
}
struct GoogleTask: Codable, Identifiable {
    let taskID: String; let listID: String; let title: String; let notes: String
    let status: String; let due: String; let parent: String; let position: String; let etag: String; let link: String
    var id: String { listID + ":" + taskID }
    var completed: Bool { status == "completed" }
    init(_ d: [String: Any], list: String) {
        taskID = d["id"] as? String ?? ""; listID = list; title = d["title"] as? String ?? ""
        notes = d["notes"] as? String ?? ""; status = d["status"] as? String ?? "needsAction"
        due = String((d["due"] as? String ?? "").prefix(10)); parent = d["parent"] as? String ?? ""
        position = d["position"] as? String ?? ""; etag = d["etag"] as? String ?? ""
        link = d["webViewLink"] as? String ?? "https://tasks.google.com/"
    }
}
struct GoogleEvent: Codable, Identifiable {
    let eventID: String; let calendarID: String; let title: String; let notes: String; let location: String
    let start: String; let end: String; let zone: String; let allDay: Bool; let recurrence: [String]
    let recurringID: String; let etag: String; let link: String; let hasGuests: Bool; let ordinary: Bool
    var id: String { calendarID + ":" + eventID }
    var startDate: Date? { archiveDate(start) ?? dateOnly(start) }
    var endDate: Date? { archiveDate(end) ?? dateOnly(end) }
    init(_ d: [String: Any], calendar: String) {
        eventID = d["id"] as? String ?? ""; calendarID = calendar
        title = d["summary"] as? String ?? "未命名日程"; notes = d["description"] as? String ?? ""; location = d["location"] as? String ?? ""
        let a = d["start"] as? [String: String] ?? [:], b = d["end"] as? [String: String] ?? [:]
        start = a["dateTime"] ?? a["date"] ?? ""; end = b["dateTime"] ?? b["date"] ?? ""
        zone = a["timeZone"] ?? TimeZone.current.identifier; allDay = a["date"] != nil
        recurrence = d["recurrence"] as? [String] ?? []; recurringID = d["recurringEventId"] as? String ?? ""
        etag = d["etag"] as? String ?? ""; link = d["htmlLink"] as? String ?? "https://calendar.google.com/"
        hasGuests = !(d["attendees"] as? [Any] ?? []).isEmpty
        ordinary = (d["eventType"] as? String ?? "default") == "default"
    }
}
func dateOnly(_ text: String) -> Date? {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = .current
    return f.date(from: String(text.prefix(10)))
}
struct GoogleSnapshot: Codable {
    var lists: [GoogleList]; var calendars: [GoogleCalendar]; var tasks: [GoogleTask]; var events: [GoogleEvent]; var fetchedAt: Date
    var queryDate: String?; var rangeDays: Int?
    static let cache = Connection.directory.appendingPathComponent("google-cache.json")
    static let quickCache = Connection.directory.appendingPathComponent("google-quick-cache.json")
    static func load(quick: Bool = false) -> GoogleSnapshot? { (try? Data(contentsOf: quick ? quickCache : cache)).flatMap { try? JSONDecoder().decode(Self.self, from: $0) } }
    func save(quick: Bool = false) {
        let path = quick ? Self.quickCache : Self.cache
        try? JSONEncoder().encode(self).write(to: path, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }
}
final class OAuthCallback: @unchecked Sendable {
    let listener: NWListener
    let state: String
    private let queue = DispatchQueue(label: "hub.oauth.callback")
    private var continuation: CheckedContinuation<String, Error>?
    init(state: String) throws {
        self.state = state
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        listener = try NWListener(using: parameters)
    }
    func code(_ open: @escaping (UInt16) -> Void) async throws -> String {
        try await withCheckedThrowingContinuation { cont in
            continuation = cont
            listener.stateUpdateHandler = { [weak self] status in
                guard let self = self else { return }
                if case .ready = status, let port = self.listener.port?.rawValue { open(port) }
                if case .failed = status { self.finish(.failure(GoogleError.callback)) }
            }
            listener.newConnectionHandler = { [weak self] connection in
                guard let self = self else { return }
                connection.start(queue: self.queue)
                connection.receive(minimumIncompleteLength: 1, maximumLength: 16384) { data, _, _, _ in
                    let request = String(data: data ?? Data(), encoding: .utf8) ?? ""
                    let target = request.components(separatedBy: " ").dropFirst().first ?? ""
                    let parts = URLComponents(string: "http://127.0.0.1" + target)
                    let values = Dictionary((parts?.queryItems ?? []).map { ($0.name, $0.value ?? "") }, uniquingKeysWith: { a, _ in a })
                    let valid = values["state"] == self.state && values["code"] != nil
                    let message = valid ? "Google connected. You can close this page." : "Authorization failed. Please return to the app."
                    let body = Data(message.utf8)
                    let header = "HTTP/1.1 \(valid ? "200 OK" : "400 Bad Request")\r\nContent-Type: text/plain\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
                    connection.send(content: Data(header.utf8) + body, completion: .contentProcessed { _ in connection.cancel() })
                    // Ignore unrelated localhost requests; only finish the expected callback.
                    if values["state"] == self.state {
                        self.finish(valid ? .success(values["code"]!) : .failure(GoogleError.callback))
                    }
                }
            }
            listener.start(queue: queue)
            queue.asyncAfter(deadline: .now() + 180) { [weak self] in self?.finish(.failure(GoogleError.authorizationTimeout)) }
        }
    }
    func browserFailed() {
        queue.async { [weak self] in self?.finish(.failure(GoogleError.browserUnavailable)) }
    }
    private func finish(_ result: Result<String, Error>) {
        guard let c = continuation else { return }
        continuation = nil; listener.cancel(); c.resume(with: result)
    }
}
actor GoogleClient {
    private var accessToken = ""
    private var expires = Date.distantPast
    private let session: URLSession
    private let diagnostics: Bool
    init(session: URLSession? = nil, accessToken: String = "", diagnostics: Bool = false) {
        self.diagnostics = diagnostics
        self.session = session ?? URLSession(configuration: .ephemeral, delegate: NoRedirect(), delegateQueue: nil)
        self.accessToken = accessToken
        if !accessToken.isEmpty { expires = Date().addingTimeInterval(3600) }
    }
    private func config() throws -> [String: String] {
        let data: Data
        do {
            // Existing device credentials remain authoritative across app updates.
            data = try GoogleKeychain.read("oauth")
        } catch GoogleError.unconfigured {
            guard let resources = Bundle.main.resourceURL,
                  let packaged = try? Data(contentsOf: resources.appendingPathComponent("google-oauth.json")) else { throw GoogleError.clientConfigurationMissing }
            data = packaged
        }
        guard let d = try JSONSerialization.jsonObject(with: data) as? [String: String],
              let clientID = d["client_id"], !clientID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw GoogleError.clientConfigurationMissing }
        return d
    }
    func configurationStatus() throws -> [String: Bool] {
        let cfg = try config()
        return ["configured": true, "authorized": !(cfg["refresh_token"] ?? "").isEmpty]
    }
    func authorize() async throws {
        var cfg = try config()
        let verifier = UUID().uuidString + UUID().uuidString
        let challenge = Data(SHA256.hash(data: Data(verifier.utf8))).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        let state = UUID().uuidString
        let callback = try OAuthCallback(state: state)
        var redirect = ""
        let code = try await callback.code { [weak callback] port in
            redirect = "http://127.0.0.1:\(port)"
            var c = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
            c.queryItems = ["client_id": cfg["client_id"]!, "redirect_uri": redirect, "response_type": "code",
                           "scope": "https://www.googleapis.com/auth/tasks https://www.googleapis.com/auth/calendar.events.owned https://www.googleapis.com/auth/calendar.calendarlist.readonly",
                           "access_type": "offline", "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256", "state": state].map { URLQueryItem(name: $0.key, value: $0.value) }
            if let url = c.url {
                DispatchQueue.main.async { if !NSWorkspace.shared.open(url) { callback?.browserFailed() } }
            } else { callback?.browserFailed() }
        }
        let token = try await tokenRequest(["client_id": cfg["client_id"]!, "client_secret": cfg["client_secret"] ?? "", "code": code,
                                           "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier])
        guard let refresh = token["refresh_token"] as? String else { throw GoogleError.callback }
        if let expected = cfg["expected_calendar"], let access = token["access_token"] as? String {
            accessToken = access; expires = Date().addingTimeInterval(300)
            do {
                let calendars = try await pages("https://www.googleapis.com/calendar/v3/users/me/calendarList")
                guard calendars.contains(where: { $0["primary"] as? Bool == true && $0["id"] as? String == expected }) else { throw GoogleError.wrongAccount }
            } catch { accessToken = ""; expires = .distantPast; throw error }
        }
        cfg["refresh_token"] = refresh
        try GoogleKeychain.write("oauth", JSONSerialization.data(withJSONObject: cfg))
        accessToken = ""; expires = .distantPast
    }
    private func tokenRequest(_ values: [String: String]) async throws -> [String: Any] {
        var r = URLRequest(url: URL(string: "https://oauth2.googleapis.com/token")!)
        r.httpMethod = "POST"
        var c = URLComponents(); c.queryItems = values.map { URLQueryItem(name: $0.key, value: $0.value) }
        r.httpBody = c.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B").data(using: .utf8)
        r.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: r)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw GoogleError.unauthorized }
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }
    private func token() async throws -> String {
        if expires > Date() { return accessToken }
        let cfg = try config()
        guard let refresh = cfg["refresh_token"] else { throw GoogleError.unconfigured }
        let d = try await tokenRequest(["client_id": cfg["client_id"]!, "client_secret": cfg["client_secret"] ?? "", "refresh_token": refresh, "grant_type": "refresh_token"])
        guard let t = d["access_token"] as? String else { throw GoogleError.unauthorized }
        accessToken = t; expires = Date().addingTimeInterval((d["expires_in"] as? Double ?? 3600) - 60)
        return t
    }
    private func part(_ v: String) -> String { v.addingPercentEncoding(withAllowedCharacters: CharacterSet.urlPathAllowed.subtracting(CharacterSet(charactersIn: "/?#"))) ?? "" }
    private func request(_ url: String, _ method: String = "GET", query: [String: String] = [:], body: [String: Any]? = nil, etag: String? = nil) async throws -> [String: Any] {
        var c = URLComponents(string: url)!
        c.queryItems = query.isEmpty ? nil : query.map { URLQueryItem(name: $0.key, value: $0.value) }
        var r = URLRequest(url: c.url!, cachePolicy: .reloadIgnoringLocalCacheData); r.httpMethod = method; r.timeoutInterval = 25
        r.setValue("Bearer " + (try await token()), forHTTPHeaderField: "Authorization")
        if let body = body { r.httpBody = try JSONSerialization.data(withJSONObject: body); r.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let etag = etag, !etag.isEmpty { r.setValue(etag, forHTTPHeaderField: "If-Match") }
        let data: Data; let response: URLResponse
        do { (data, response) = try await session.data(for: r) } catch { throw GoogleError.timeout }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 401 { accessToken = ""; expires = .distantPast; throw GoogleError.unauthorized }
        if status == 412 { throw GoogleError.conflict }
        guard (200..<300).contains(status) else {
            if diagnostics, let d = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let e = d["error"] as? [String: Any], let msg = e["message"] as? String {
                let safe = msg.replacingOccurrences(of: "[A-Za-z0-9_+/=.-]{20,}|[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+", with: "[identifier]", options: .regularExpression)
                print("google_acceptance_error \(status) \(String(safe.prefix(150)))")
            }
            throw GoogleError.request(status)
        }
        return data.isEmpty ? [:] : ((try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:])
    }
    private func pages(_ url: String, query: [String: String] = [:]) async throws -> [[String: Any]] {
        var q = query; var result: [[String: Any]] = []; var seen = Set<String>()
        for _ in 0..<1000 {
            let d = try await request(url, query: q)
            result += d["items"] as? [[String: Any]] ?? []
            guard let next = d["nextPageToken"] as? String else { return result }
            guard seen.insert(next).inserted else { throw GoogleError.invalid }
            q["pageToken"] = next
        }
        throw GoogleError.invalid
    }
    func snapshot(date: Date, days: Int) async throws -> GoogleSnapshot {
        let listsData = try await pages("https://tasks.googleapis.com/tasks/v1/users/@me/lists", query: ["maxResults": "100"])
        let lists = listsData.map { GoogleList(id: $0["id"] as? String ?? "", title: $0["title"] as? String ?? "", etag: $0["etag"] as? String ?? "") }
        var tasks: [GoogleTask] = []
        for list in lists {
            let rows = try await pages("https://tasks.googleapis.com/tasks/v1/lists/\(part(list.id))/tasks", query: ["maxResults": "100", "showCompleted": "true", "showHidden": "true"])
            tasks += rows.map { GoogleTask($0, list: list.id) }
        }
        let calendarsData = try await pages("https://www.googleapis.com/calendar/v3/users/me/calendarList", query: ["maxResults": "250"])
        let calendars = calendarsData.filter { ($0["accessRole"] as? String) == "owner" }.map { GoogleCalendar(id: $0["id"] as? String ?? "", title: $0["summary"] as? String ?? "", owned: true, primary: $0["primary"] as? Bool ?? false) }
        let start = Calendar.current.startOfDay(for: date), end = Calendar.current.date(byAdding: .day, value: days, to: start)!
        var events: [GoogleEvent] = []
        for cal in calendars {
            let rows = try await pages("https://www.googleapis.com/calendar/v3/calendars/\(part(cal.id))/events", query: ["timeMin": ISO8601DateFormatter().string(from: start), "timeMax": ISO8601DateFormatter().string(from: end), "singleEvents": "true", "orderBy": "startTime", "maxResults": "2500"])
            events += rows.map { GoogleEvent($0, calendar: cal.id) }
        }
        let value = GoogleSnapshot(lists: lists, calendars: calendars, tasks: tasks.sorted { $0.position < $1.position }, events: events.sorted { $0.start < $1.start }, fetchedAt: Date(), queryDate: dayKey(date), rangeDays: days)
        value.save(); return value
    }
    func nextEvent(calendars: [GoogleCalendar]) async throws -> GoogleEvent? {
        var upcoming: [GoogleEvent] = []
        for cal in calendars where cal.owned {
            let response = try await request("https://www.googleapis.com/calendar/v3/calendars/\(part(cal.id))/events", query: ["timeMin": ISO8601DateFormatter().string(from: Date()), "singleEvents": "true", "orderBy": "startTime", "maxResults": "1"])
            if let row = (response["items"] as? [[String: Any]])?.first { upcoming.append(GoogleEvent(row, calendar: cal.id)) }
        }
        return upcoming.min { ($0.startDate ?? .distantFuture) < ($1.startDate ?? .distantFuture) }
    }
    func quickSnapshot() async throws -> GoogleSnapshot {
        var value = try await snapshot(date: Date(), days: 1)
        value.events = try await nextEvent(calendars: value.calendars).map { [$0] } ?? []
        value.save(quick: true); return value
    }
    func saveTask(_ task: GoogleTask?, list: String, title: String, notes: String, due: String, parent: String = "") async throws {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, title.count <= 1024, notes.count <= 8192, !list.isEmpty else { throw GoogleError.invalid }
        let url = "https://tasks.googleapis.com/tasks/v1/lists/\(part(list))/tasks"
        var body: [String: Any] = ["title": title, "notes": notes]
        if !due.isEmpty { body["due"] = due + "T00:00:00.000Z" }
        else if task != nil { body["due"] = NSNull() }
        if let task = task {
            guard task.listID == list else { throw GoogleError.invalid }
            body["status"] = task.status
            _ = try await request(url + "/" + part(task.taskID), "PATCH", body: body, etag: task.etag)
        } else {
            _ = try await request(url, "POST", query: parent.isEmpty ? [:] : ["parent": parent], body: body)
        }
    }
    func complete(_ task: GoogleTask) async throws {
        var body: [String: Any] = ["status": task.completed ? "needsAction" : "completed"]
        if task.completed { body["completed"] = NSNull() }
        _ = try await request("https://tasks.googleapis.com/tasks/v1/lists/\(part(task.listID))/tasks/\(part(task.taskID))", "PATCH", body: body, etag: task.etag)
    }
    func deleteTask(_ task: GoogleTask) async throws {
        _ = try await request("https://tasks.googleapis.com/tasks/v1/lists/\(part(task.listID))/tasks/\(part(task.taskID))", "DELETE", etag: task.etag)
    }
    func move(_ task: GoogleTask, previous: String = "", parent: String = "", destination: String? = nil) async throws {
        var params = ["previous": previous, "parent": parent].filter { !$0.value.isEmpty }
        if let destination = destination { params["destinationTasklist"] = destination }
        _ = try await request("https://tasks.googleapis.com/tasks/v1/lists/\(part(task.listID))/tasks/\(part(task.taskID))/move", "POST", query: params)
    }
    func saveList(_ list: GoogleList?, title: String) async throws {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw GoogleError.invalid }
        let url = "https://tasks.googleapis.com/tasks/v1/users/@me/lists"
        _ = try await request(url + (list.map { "/" + part($0.id) } ?? ""), list == nil ? "POST" : "PATCH", body: ["title": title], etag: list?.etag)
    }
    func deleteList(_ list: GoogleList) async throws {
        _ = try await request("https://tasks.googleapis.com/tasks/v1/users/@me/lists/" + part(list.id), "DELETE", etag: list.etag)
    }
    func saveEvent(_ event: GoogleEvent?, calendar: String, title: String, notes: String, location: String, start: Date, end: Date, allDay: Bool, zone: String, recurrence: String, series: Bool, creationID: String) async throws {
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, end > start, TimeZone(identifier: zone) != nil, event?.hasGuests != true, event?.ordinary != false else { throw GoogleError.invalid }
        let url = "https://www.googleapis.com/calendar/v3/calendars/\(part(calendar))/events"
        let dateFormatter = DateFormatter(); dateFormatter.dateFormat = "yyyy-MM-dd"; dateFormatter.timeZone = TimeZone(identifier: zone)
        var body: [String: Any] = ["summary": title, "description": notes, "location": location]
        body["start"] = allDay ? ["date": dateFormatter.string(from: start)] : ["dateTime": ISO8601DateFormatter().string(from: start), "timeZone": zone]
        body["end"] = allDay ? ["date": dateFormatter.string(from: end)] : ["dateTime": ISO8601DateFormatter().string(from: end), "timeZone": zone]
        if let event = event {
            let eid = series && !event.recurringID.isEmpty ? event.recurringID : event.eventID
            let latest = try await request(url + "/" + part(eid))
            // Editing a series uses the master, not an expanded occurrence.
            if series && !event.recurringID.isEmpty {
                guard latest["attendees"] == nil || (latest["attendees"] as? [Any] ?? []).isEmpty else { throw GoogleError.invalid }
            } else if latest["etag"] as? String != event.etag { throw GoogleError.conflict }
            if event.recurringID.isEmpty || series { body["recurrence"] = recurrence.isEmpty ? [] : ["RRULE:" + recurrence] }
            _ = try await request(url + "/" + part(eid), "PATCH", body: body, etag: latest["etag"] as? String)
        } else {
            body["id"] = creationID
            if !recurrence.isEmpty { body["recurrence"] = ["RRULE:" + recurrence] }
            _ = try await request(url, "POST", body: body)
        }
    }
    func master(_ event: GoogleEvent) async throws -> GoogleEvent {
        let id = event.recurringID.isEmpty ? event.eventID : event.recurringID
        let d = try await request("https://www.googleapis.com/calendar/v3/calendars/\(part(event.calendarID))/events/\(part(id))")
        return GoogleEvent(d, calendar: event.calendarID)
    }
    func deleteEvent(_ event: GoogleEvent, series: Bool) async throws {
        guard !event.hasGuests, event.ordinary else { throw GoogleError.invalid }
        let actual = series ? try await master(event) : event
        _ = try await request("https://www.googleapis.com/calendar/v3/calendars/\(part(actual.calendarID))/events/\(part(actual.eventID))", "DELETE", etag: actual.etag)
    }
    func cleanupAcceptance() async throws {
        let rows = try await pages("https://tasks.googleapis.com/tasks/v1/users/@me/lists")
        var removed = 0
        for row in rows {
            guard let title = row["title"] as? String,
                  title.range(of: #"^\[Personal Hub 验收\] [A-Fa-f0-9-]{36}$"#, options: .regularExpression) != nil,
                  let id = row["id"] as? String else { continue }
            let list = GoogleList(id: id, title: title, etag: row["etag"] as? String ?? "")
            try await deleteList(list); removed += 1
        }
        print("google_acceptance_lists_removed \(removed)")
    }
    func smoke() async throws {
        let initial = try await snapshot(date: Date(), days: 1)
        guard let calendar = initial.calendars.first(where: \.primary) else { throw GoogleError.invalid }
        let title = "[Personal Hub 验收] " + UUID().uuidString
        let listData = try await request("https://tasks.googleapis.com/tasks/v1/users/@me/lists", "POST", body: ["title": title])
        guard let lid = listData["id"] as? String else { throw GoogleError.invalid }
        let list = GoogleList(id: lid, title: title, etag: listData["etag"] as? String ?? "")
        let eid = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        let calendarURL = "https://www.googleapis.com/calendar/v3/calendars/\(part(calendar.id))/events/\(eid)"
        do {
            print("google_live_stage task_create")
            try await saveTask(nil, list: lid, title: title, notes: "Temporary acceptance data", due: dayKey(Date()))
            let url = "https://tasks.googleapis.com/tasks/v1/lists/\(part(lid))/tasks"
            guard let raw = try await pages(url).first else { throw GoogleError.invalid }
            let task = GoogleTask(raw, list: lid)
            print("google_live_stage task_edit")
            try await saveTask(task, list: lid, title: title + " edited", notes: "updated", due: dayKey(Date()))
            let edited = GoogleTask(try await request(url + "/" + part(task.taskID)), list: lid)
            print("google_live_stage task_complete")
            try await complete(edited)
            let done = GoogleTask(try await request(url + "/" + part(task.taskID)), list: lid)
            guard done.completed else { throw GoogleError.invalid }
            print("google_live_stage task_restore")
            try await complete(done)
            print("google_live_stage task_subtask")
            try await saveTask(nil, list: lid, title: "验收子任务", notes: "", due: "", parent: task.taskID)
            guard let subRaw = try await pages(url).first(where: { $0["parent"] as? String == task.taskID }) else { throw GoogleError.invalid }
            let sub = GoogleTask(subRaw, list: lid)
            print("google_live_stage task_move")
            try await move(sub, parent: "")
            let moved = GoogleTask(try await request(url + "/" + part(sub.taskID)), list: lid)
            guard moved.parent.isEmpty else { throw GoogleError.invalid }
            try await deleteTask(moved)
            let liveTask = GoogleTask(try await request(url + "/" + part(task.taskID)), list: lid)
            try await deleteTask(liveTask)
            let start = Calendar.current.date(byAdding: .day, value: 1, to: Calendar.current.startOfDay(for: Date()))!
            let end = Calendar.current.date(byAdding: .day, value: 1, to: start)!
            print("google_live_stage calendar_create")
            try await saveEvent(nil, calendar: calendar.id, title: title, notes: "", location: "", start: start, end: end, allDay: true, zone: TimeZone.current.identifier, recurrence: "FREQ=DAILY;COUNT=3", series: false, creationID: eid)
            let event = GoogleEvent(try await request(calendarURL), calendar: calendar.id)
            guard event.allDay else { throw GoogleError.invalid }
            print("google_live_stage calendar_edit")
            try await saveEvent(event, calendar: calendar.id, title: title + " edited", notes: "updated", location: "", start: start, end: end, allDay: true, zone: TimeZone.current.identifier, recurrence: "FREQ=DAILY;COUNT=3", series: false, creationID: eid)
            let instances = try await pages(calendarURL + "/instances")
            guard let instanceData = instances.first else { throw GoogleError.invalid }
            let instance = GoogleEvent(instanceData, calendar: calendar.id)
            print("google_live_stage calendar_instance_edit")
            try await saveEvent(instance, calendar: calendar.id, title: title + " instance", notes: "", location: "", start: start, end: end, allDay: true, zone: TimeZone.current.identifier, recurrence: "", series: false, creationID: "")
            let fresh = GoogleEvent(try await request("https://www.googleapis.com/calendar/v3/calendars/\(part(calendar.id))/events/\(part(instance.eventID))"), calendar: calendar.id)
            print("google_live_stage calendar_instance_delete")
            try await deleteEvent(fresh, series: false)
            print("google_live_stage calendar_series_delete")
            try await deleteEvent(event, series: true)
            try await deleteList(list)
        } catch {
            _ = try? await request(calendarURL, "DELETE")
            try? await deleteList(list)
            throw error
        }
    }

}
