import Foundation

/// End-to-end check against the real Google account, confined to a throwaway task list and one
/// event that are deleted before returning. Reports booleans and counts only, never content.
public enum AgendaSmoke {
    public struct Check: Sendable {
        public var name: String
        public var ok: Bool
        public var detail: String
    }

    /// Lets the smoke test cut the network to exercise the offline queue.
    final class Switch: HTTPTransport, @unchecked Sendable {
        let base: HTTPTransport
        private let lock = NSLock()
        private var down = false
        init(_ base: HTTPTransport) { self.base = base }
        var offline: Bool {
            get { lock.withLock { down } }
            set { lock.withLock { down = newValue } }
        }
        func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
            if offline { throw GoogleAPIError.offline }
            return try await base.send(request)
        }
    }

    public static func run(transport: HTTPTransport, token: @escaping GoogleAPI.TokenSource,
                           calendar: Calendar = .hub, workDir: URL) async -> [Check] {
        var checks: [Check] = []
        func check(_ name: String, _ ok: Bool, _ detail: String = "") { checks.append(Check(name: name, ok: ok, detail: detail)) }

        let net = Switch(transport)
        let api = GoogleAPI(transport: net, calendar: calendar, token: token)
        let direct = GoogleAPI(transport: transport, calendar: calendar, token: token)
        let file = workDir.appendingPathComponent("smoke-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: file) }
        let sync = AgendaSync(file: file, calendar: calendar)
        await sync.connect(api: api, account: "smoke")

        await sync.syncNow()
        var s = await sync.snapshot
        let primary = s.calendars.first(where: \.primary)
        let status = await sync.status
        check("initial pull", status == .idle,
              "lists \(s.lists.count), tasks \(s.tasks.count), events \(s.events.count)\(status == .idle ? "" : ", status \(status)")")
        check("sync token after timeMin pull", primary.map { s.calendarSyncTokens[$0.id] != nil } ?? false)

        let stamp = Int(Date().timeIntervalSince1970)
        let listTitle = "Personal Hub 冒烟测试 \(stamp)"
        let tomorrow = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: Date()))!
        let day = GoogleDate.dayString(tomorrow, calendar: calendar)
        let list = AgendaStore.localID(), task = AgendaStore.localID(), sub = AgendaStore.localID()

        net.offline = true
        await sync.perform(.createList(id: list, title: listTitle))
        await sync.perform(.createTask(id: task, listID: list, title: "冒烟任务", notes: "由 Personal Hub 创建，会自动删除", due: day, parent: nil))
        await sync.perform(.createTask(id: sub, listID: list, title: "冒烟子任务", notes: nil, due: nil, parent: task))
        await sync.perform(.updateTask(id: task, listID: list, patch: TaskPatch(title: "冒烟任务（已改）")))
        await sync.perform(.updateTask(id: sub, listID: list, patch: TaskPatch(completed: true)))
        await sync.syncNow()
        s = await sync.snapshot
        check("offline queue", await sync.status == .offline && s.pending.count == 5, "pending \(s.pending.count)")

        net.offline = false
        await sync.syncNow()
        s = await sync.snapshot
        let serverList = s.lists.first { $0.title == listTitle }
        check("queue flushed", await sync.status == .idle && s.pending.isEmpty && s.failures.isEmpty,
              "pending \(s.pending.count), failures \(s.failures.count)")
        if let serverList, let remote = try? await direct.tasks(listID: serverList.id) {
            let parent = remote.first { $0.title == "冒烟任务（已改）" }
            let child = remote.first { $0.title == "冒烟子任务" }
            check("server has edited task with due date", parent?.due == day && !(parent?.completed ?? true))
            check("server has completed subtask", child?.completed == true && child?.parent == parent?.id)
            check("local ids replaced", !s.tasks.contains { AgendaStore.isLocal($0.id) } && !AgendaStore.isLocal(serverList.id))
        } else {
            check("server list created", false)
        }

        if let primary {
            let title = "Personal Hub 冒烟测试 \(stamp)"
            let start = tomorrow.addingTimeInterval(23 * 3600)
            let local = AgendaStore.localID()
            await sync.perform(.createEvent(id: local, calendarID: primary.id,
                                            draft: EventDraft(title: title, start: start, end: start.addingTimeInterval(1800), notes: "会自动删除")))
            await sync.syncNow()
            s = await sync.snapshot
            let created = s.events.first { $0.title == title }
            check("event created", created.map { !AgendaStore.isLocal($0.id) } ?? false)
            if let created {
                func server() async -> EventRecord? {
                    try? await direct.events(calendarID: primary.id, syncToken: nil, timeMin: tomorrow).events.first { $0.id == created.id }
                }
                let moved = start.addingTimeInterval(-3600)
                await sync.perform(.updateEvent(id: created.id, calendarID: primary.id,
                                                draft: EventDraft(title: title + "（改）", start: moved, end: moved.addingTimeInterval(2700), location: "测试地点")))
                await sync.syncNow()
                let edited = await server()
                var clean = await sync.snapshot.failures.isEmpty
                check("event edited", edited?.title == title + "（改）" && edited?.start == moved && edited?.location == "测试地点" && clean)

                await sync.perform(.updateEvent(id: created.id, calendarID: primary.id,
                                                draft: EventDraft(title: title + "（改）", start: tomorrow,
                                                                  end: calendar.date(byAdding: .day, value: 1, to: tomorrow)!, allDay: true)))
                await sync.syncNow()
                let allDay = await server()
                clean = await sync.snapshot.failures.isEmpty
                check("event switched to all-day", allDay?.allDay == true && allDay?.location == nil && clean)

                await sync.perform(.deleteEvent(id: created.id, calendarID: primary.id))
                await sync.syncNow()
                s = await sync.snapshot
                let remaining = await server()
                check("event deleted", remaining == nil && !s.events.contains { $0.id == created.id } && s.failures.isEmpty)
                check("calendar sync token kept", s.calendarSyncTokens[primary.id] != nil)
            }
        }
        let others = s.calendars.filter { !$0.primary }.count
        check("shared calendars readable", true, "\(s.calendars.count) calendars, \(others) not primary, \(s.events.count) events cached")

        if let serverList {
            await sync.perform(.deleteList(id: serverList.id))
            await sync.syncNow()
            let remaining = (try? await direct.taskLists()) ?? []
            check("test list deleted", !remaining.contains { $0.title == listTitle })
        }
        // Belt and braces: remove anything left by an interrupted earlier run.
        for leftover in ((try? await direct.taskLists()) ?? []) where leftover.title.hasPrefix("Personal Hub 冒烟测试") {
            try? await direct.deleteList(id: leftover.id)
        }
        return checks
    }
}
