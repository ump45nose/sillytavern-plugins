import Foundation
import HubKit

/// `PersonalHub --mcp`: the hub as MCP tools for local agents. Reads come from the app's caches on disk;
/// writes only become pending changes that the user confirms in the app.
enum HubMCP {
    static let support = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PersonalHub")
    static let pending = AIPendingStore(dir: support.appendingPathComponent("pending-ai"))
    static let audit = AIAuditLog(file: support.appendingPathComponent("ai-audit.jsonl"))
    static let serverName = "personal_hub"

    static let instructions = """
    Nook 是用户的个人信息聚合中心：任务、日程、健康、账单、交流（CRM）、Token 用量、Memos、阶段目标等。
    读取类工具返回 App 最近一次同步的本地缓存（带 synced_at）。写入类工具（propose_*）只会生成待确认的变更，
    需要用户在 Nook 里确认后才会真正写入；调用后请告诉用户去确认，不要声称已经完成。
    """

    static func run() async -> Int32 {
        let server = makeServer()
        server.onCall = { [session = server.session] tool, ok in audit.record(tool: tool, ok: ok, client: session.client) }
        let out = FileHandle.standardOutput
        do {
            for try await line in FileHandle.standardInput.bytes.lines where !line.isEmpty {
                if let reply = await server.handle(line) {
                    out.write(Data((reply + "\n").utf8))
                }
            }
        } catch {
            return 1
        }
        return 0
    }

    static func makeServer(now: @escaping @Sendable () -> Date = { Date() }, hubFile: URL = support.appendingPathComponent("hub.json"),
                           agendaFile: URL = support.appendingPathComponent("agenda.json"), pending: AIPendingStore = pending) -> MCPServer {
        let data = Caches(hubFile: hubFile, agendaFile: agendaFile)
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        return MCPServer(name: serverName, version: version, instructions: instructions, tools: [
            MCPTool(name: "get_overview", description: "今天的概览：待办（逾期/今天）、今天的日程、需要关注的提醒、各模块同步状态。先调用这个。") { _, _ in
                try overview(data, now: now())
            },
            MCPTool(name: "get_agenda", description: "任务和日程明细（Google Tasks / Calendar）。返回的任务 id 可用于 propose_complete_task。",
                    properties: [
                        "days": ["type": "integer", "minimum": 1, "maximum": 30, "description": "从今天起向后几天，默认 7"],
                        "include_completed": ["type": "boolean", "description": "是否包含已完成任务，默认 false"],
                    ]) { args, _ in
                try agenda(data, now: now(), days: min(max(args.int("days") ?? 7, 1), 30), completed: args.bool("include_completed") ?? false)
            },
            MCPTool(name: "get_module", description: "某个模块的完整数据（hub 缓存）：health 健康、bills 账单、crm 交流、media 影音、token 用量、git 提交、net 网络、subs 订阅、memos 最近 Memo、attention 提醒、goals 阶段目标。",
                    properties: ["module": ["type": "string", "enum": HubModule.allCases.map(\.rawValue)]],
                    required: ["module"]) { args, _ in
                guard let raw = args.string("module"), let module = HubModule(rawValue: raw) else { throw MCPToolError("未知模块") }
                return try moduleData(data, module)
            },
            MCPTool(name: "search", description: "在任务、日程、最近的 Memo、今天的交流里按关键词搜索。",
                    properties: ["query": ["type": "string"]], required: ["query"]) { args, _ in
                guard let q = args.string("query") else { throw MCPToolError("缺少 query") }
                return try search(data, query: q)
            },
            MCPTool(name: "list_pending", description: "列出还在等用户确认的变更。") { _, _ in
                try json(["pending": pending.list().map(describe)])
            },
            MCPTool(name: "propose_task", description: "提议新建一个任务（需要用户确认）。",
                    properties: [
                        "title": ["type": "string"],
                        "due": ["type": "string", "description": "YYYY-MM-DD"],
                        "time": ["type": "string", "description": "HH:mm，可选"],
                        "notes": ["type": "string"],
                        "list": ["type": "string", "description": "任务列表名，默认第一个列表"],
                    ], required: ["title"]) { args, session in
                guard let title = args.string("title"), title.count <= 200 else { throw MCPToolError("title 不能为空，且不超过 200 字") }
                let due = args.string("due")
                if let due, GoogleDate.day(due, calendar: .hub) == nil { throw MCPToolError("due 需要是 YYYY-MM-DD") }
                let time = args.string("time")
                if let time, clock(time) == nil { throw MCPToolError("time 需要是 HH:mm") }
                if time != nil, due == nil { throw MCPToolError("给了 time 也需要 due") }
                let notes = args.string("notes")
                if (notes?.count ?? 0) > 2000 { throw MCPToolError("notes 不超过 2000 字") }
                return try stage(.task(title: title, due: due, time: time, notes: notes, list: args.string("list")), session, pending)
            },
            MCPTool(name: "propose_complete_task", description: "提议把一个任务标记为完成（需要用户确认）。task_id 来自 get_agenda。",
                    properties: ["task_id": ["type": "string"]], required: ["task_id"]) { args, session in
                guard let id = args.string("task_id") else { throw MCPToolError("缺少 task_id") }
                guard let task = data.agenda().tasks.first(where: { $0.id == id }) else { throw MCPToolError("找不到这个任务") }
                guard !task.completed else { throw MCPToolError("这个任务已经完成了") }
                return try stage(.completeTask(id: id, title: task.title), session, pending)
            },
            MCPTool(name: "propose_event", description: "提议在主日历上新建日程（需要用户确认）。时间用本地时间 YYYY-MM-DDTHH:mm。",
                    properties: [
                        "title": ["type": "string"],
                        "start": ["type": "string"],
                        "end": ["type": "string"],
                        "location": ["type": "string"],
                        "notes": ["type": "string"],
                    ], required: ["title", "start", "end"]) { args, session in
                guard let title = args.string("title"), title.count <= 200 else { throw MCPToolError("title 不能为空，且不超过 200 字") }
                guard let start = args.string("start").flatMap(parseTime), let end = args.string("end").flatMap(parseTime) else {
                    throw MCPToolError("start / end 需要是 YYYY-MM-DDTHH:mm")
                }
                guard end > start, end.timeIntervalSince(start) <= 14 * 86400 else { throw MCPToolError("结束时间需要晚于开始，且不超过 14 天") }
                return try stage(.event(title: title, start: start, end: end, location: args.string("location"), notes: args.string("notes")), session, pending)
            },
            MCPTool(name: "propose_memo", description: "提议发布一条 Memo（Markdown，需要用户确认）。",
                    properties: [
                        "content": ["type": "string"],
                        "visibility": ["type": "string", "enum": ["PRIVATE", "PROTECTED", "PUBLIC"], "description": "默认 PRIVATE"],
                    ], required: ["content"]) { args, session in
                guard let content = args.string("content"), content.count <= 8000 else { throw MCPToolError("content 不能为空，且不超过 8000 字") }
                let visibility = args.string("visibility") ?? "PRIVATE"
                guard ["PRIVATE", "PROTECTED", "PUBLIC"].contains(visibility) else { throw MCPToolError("visibility 不合法") }
                return try stage(.memo(content: content, visibility: visibility), session, pending)
            },
        ])
    }

    // MARK: Tools

    private static func stage(_ kind: AIPendingChange.Kind, _ session: MCPSession, _ pending: AIPendingStore) throws -> String {
        let change = AIPendingChange(agent: session.client, kind: kind)
        do {
            try pending.add(change)
        } catch let e as MCPToolError {
            throw e
        } catch {
            throw MCPToolError("保存待确认变更失败")
        }
        return try json(["status": "pending_confirmation", "pending_id": change.id,
                         "message": "已提交，等用户在 Nook 里确认后才会写入。"])
    }

    private static func overview(_ data: Caches, now: Date) throws -> String {
        let store = data.agenda()
        let view = Agenda.build(store, now: now)
        let hub = data.hub()
        let tasks: [String: Any] = ["overdue": view.overdue.map(task), "today": view.today.map(task), "upcoming_count": view.upcoming.count]
        let attention: [[String: Any]] = (hub.attention?.data?.items ?? []).map { item in
            ["title": item.title, "detail": item.subtitle ?? NSNull(), "severity": item.severity ?? NSNull()]
        }
        let modules: [[String: Any]] = HubModule.allCases.map { m in ["module": m.rawValue, "status": hub.status(m)?.rawValue ?? "missing"] }
        var out: [String: Any] = ["now": stamp(now), "tasks": tasks, "attention": attention, "modules": modules]
        out["agenda_synced_at"] = store.lastSync.map(stamp) ?? NSNull()
        out["hub_synced_at"] = hub.fetchedAt.map(stamp) ?? NSNull()
        out["events_today"] = (view.allDay + view.events).map(event)
        out["next_event"] = view.nextEvent.map(event) ?? NSNull()
        return try json(out)
    }

    private static func agenda(_ data: Caches, now: Date, days: Int, completed: Bool) throws -> String {
        let store = data.agenda()
        let view = Agenda.build(store, now: now)
        let start = Calendar.hub.startOfDay(for: now)
        let end = Calendar.hub.date(byAdding: .day, value: days, to: start)!
        let titles = Dictionary(store.calendars.map { ($0.id, $0.title) }, uniquingKeysWith: { a, _ in a })
        let tasks = view.allTasks.filter { completed || !$0.completed }
            .filter { $0.due.map { $0 < end } ?? true }
        let events = store.events.filter { !$0.cancelled && $0.end > start && $0.start < end }
            .sorted { $0.start < $1.start }
            .map { e -> [String: Any] in
                ["id": e.id, "title": e.title, "start": stamp(e.start), "end": stamp(e.end), "all_day": e.allDay,
                 "calendar": titles[e.calendarID] ?? "", "location": e.location ?? NSNull()]
            }
        return try json(["synced_at": store.lastSync.map(stamp) ?? NSNull(), "tasks": tasks.map(task), "events": events])
    }

    private static func moduleData(_ data: Caches, _ module: HubModule) throws -> String {
        let hub = data.hub()
        let encoded: Data? = switch module {
        case .health: try hub.health.map(HubJSON.encoder.encode)
        case .bills: try hub.bills.map(HubJSON.encoder.encode)
        case .crm: try hub.crm.map(HubJSON.encoder.encode)
        case .media: try hub.media.map(HubJSON.encoder.encode)
        case .token: try HubJSON.encoder.encode(Dictionary(uniqueKeysWithValues: hub.token.map { ($0.key.rawValue, $0.value) }))
        case .git: try hub.git.map(HubJSON.encoder.encode)
        case .net: try hub.net.map(HubJSON.encoder.encode)
        case .subs: try hub.subs.map(HubJSON.encoder.encode)
        case .memos: try hub.memos.map(HubJSON.encoder.encode)
        case .attention: try hub.attention.map(HubJSON.encoder.encode)
        case .goals: try hub.goals.map(HubJSON.encoder.encode)
        }
        guard let encoded else { throw MCPToolError("这个模块还没有同步过数据") }
        return String(decoding: encoded, as: UTF8.self)
    }

    private static func search(_ data: Caches, query: String) throws -> String {
        let store = data.agenda()
        let hub = data.hub()
        let terms = query.lowercased().split(whereSeparator: \.isWhitespace).map(String.init)
        func hit(_ texts: String?...) -> Bool {
            let text = texts.compactMap { $0?.lowercased() }.joined(separator: " ")
            return terms.allSatisfy(text.contains)
        }
        let tasks = Agenda.search(store, query: query, limit: 20).map(task)
        let events = store.events.filter { !$0.cancelled && hit($0.title, $0.location, $0.notes) }
            .sorted { $0.start > $1.start }.prefix(20)
            .map { ["id": $0.id, "title": $0.title, "start": stamp($0.start), "end": stamp($0.end)] as [String: Any] }
        let memos = (hub.memos?.data?.recent ?? []).filter { hit($0.content) }.prefix(20)
            .map { ["id": $0.id, "created_at": $0.createdAt.map(stamp) ?? NSNull(), "content": $0.content] as [String: Any] }
        let crm = try hub.crm.map { String(decoding: try HubJSON.encoder.encode($0), as: UTF8.self) }
        return try json(["tasks": tasks, "events": Array(events), "memos": Array(memos),
                         "crm_today_matches": crm.map { hit($0) } ?? false])
    }

    // MARK: Helpers

    struct Caches: Sendable {
        let hubFile: URL
        let agendaFile: URL

        func hub() -> HubData {
            (try? Data(contentsOf: hubFile)).flatMap { try? HubJSON.decoder.decode(HubData.self, from: $0) } ?? HubData()
        }

        func agenda() -> AgendaStore {
            (try? Data(contentsOf: agendaFile)).flatMap { try? JSONDecoder().decode(AgendaStore.self, from: $0) } ?? AgendaStore()
        }
    }

    static func describe(_ change: AIPendingChange) -> [String: Any] {
        var out: [String: Any] = ["id": change.id, "created_at": stamp(change.createdAt)]
        switch change.kind {
        case let .task(title, due, time, _, list):
            out["kind"] = "task"; out["title"] = title; out["due"] = due ?? NSNull(); out["time"] = time ?? NSNull(); out["list"] = list ?? NSNull()
        case let .completeTask(id, title):
            out["kind"] = "complete_task"; out["task_id"] = id; out["title"] = title
        case let .memo(content, visibility):
            out["kind"] = "memo"; out["content"] = content; out["visibility"] = visibility
        case let .event(title, start, end, _, _):
            out["kind"] = "event"; out["title"] = title; out["start"] = stamp(start); out["end"] = stamp(end)
        }
        return out
    }

    private static func task(_ t: AgendaTask) -> [String: Any] {
        ["id": t.id, "title": t.title, "list": t.listTitle, "due": t.due.map { GoogleDate.dayString($0, calendar: .hub) } ?? NSNull(),
         "completed": t.completed, "notes": t.notes ?? NSNull()]
    }

    private static func event(_ e: AgendaEvent) -> [String: Any] {
        ["title": e.title, "start": stamp(e.start), "end": stamp(e.end), "all_day": e.allDay, "calendar": e.calendarTitle,
         "location": e.location ?? NSNull()]
    }

    static func stamp(_ d: Date) -> String {
        let f = ISO8601DateFormatter()
        f.timeZone = Calendar.hub.timeZone
        return f.string(from: d)
    }

    static func clock(_ s: String) -> (Int, Int)? {
        let parts = s.split(separator: ":").compactMap { Int($0) }
        guard parts.count == 2, (0..<24).contains(parts[0]), (0..<60).contains(parts[1]) else { return nil }
        return (parts[0], parts[1])
    }

    /// Local wall time (`2026-10-22T15:00`, a space also works) or full RFC 3339.
    static func parseTime(_ s: String) -> Date? {
        if let d = ISO8601DateFormatter().date(from: s) { return d }
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = Calendar.hub.timeZone
        for format in ["yyyy-MM-dd'T'HH:mm", "yyyy-MM-dd HH:mm", "yyyy-MM-dd'T'HH:mm:ss"] {
            f.dateFormat = format
            if let d = f.date(from: s) { return d }
        }
        return nil
    }

    private static func json(_ object: [String: Any]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
        return String(decoding: data, as: UTF8.self)
    }
}
