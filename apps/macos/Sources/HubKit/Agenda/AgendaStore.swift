import Foundation

/// A local change waiting to be sent to Google, applied optimistically to the cache.
public enum Change: Codable, Equatable, Sendable {
    case createTask(id: String, listID: String, title: String, notes: String?, due: String?, parent: String?)
    case updateTask(id: String, listID: String, patch: TaskPatch)
    case deleteTask(id: String, listID: String)
    /// Re-parent within a list, or move to `toList`.
    case moveTask(id: String, listID: String, toList: String?, parent: String?)
    case createList(id: String, title: String)
    case renameList(id: String, title: String)
    case deleteList(id: String)
    case createEvent(id: String, calendarID: String, draft: EventDraft)
    case updateEvent(id: String, calendarID: String, draft: EventDraft)
    case deleteEvent(id: String, calendarID: String)
    case moveEvent(id: String, calendarID: String, to: String)
}

public struct PendingChange: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var change: Change
    public var queuedAt: Date

    public init(id: UUID = UUID(), change: Change, queuedAt: Date = Date()) {
        self.id = id
        self.change = change
        self.queuedAt = queuedAt
    }
}

public struct SyncFailure: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var summary: String
    public var at: Date
}

/// Everything the agenda shows, cached on disk so the app opens instantly and works offline.
public struct AgendaStore: Codable, Equatable, Sendable {
    public var account: String?
    public var lists: [TaskListRecord] = []
    public var tasks: [TaskRecord] = []
    public var calendars: [CalendarRecord] = []
    public var events: [EventRecord] = []
    public var calendarSyncTokens: [String: String] = [:]
    /// Per list, the RFC 3339 time the last pull started; used as `updatedMin`.
    public var tasksPulledAt: [String: String] = [:]
    public var pending: [PendingChange] = []
    public var failures: [SyncFailure] = []
    public var lastSync: Date?

    public init(account: String? = nil) { self.account = account }

    public static func localID() -> String { "local-" + UUID().uuidString }
    public static func isLocal(_ id: String) -> Bool { id.hasPrefix("local-") }

    // MARK: Optimistic application

    public mutating func apply(_ change: Change) {
        switch change {
        case let .createTask(id, listID, title, notes, due, parent):
            tasks.removeAll { $0.id == id }
            tasks.append(TaskRecord(id: id, listID: listID, title: title, notes: notes, due: due, parent: parent,
                                    position: "~", updated: GoogleDate.string(Date())))
        case let .updateTask(id, _, patch):
            guard let i = tasks.firstIndex(where: { $0.id == id }) else { return }
            if let title = patch.title { tasks[i].title = title }
            if let notes = patch.notes { tasks[i].notes = notes }
            if let due = patch.due { tasks[i].due = due }
            if let completed = patch.completed {
                tasks[i].completed = completed
                tasks[i].completedAt = completed ? GoogleDate.string(Date()) : nil
                // Google completes and reopens subtasks with their parent.
                for j in tasks.indices where tasks[j].parent == id { tasks[j].completed = completed }
            }
        case let .deleteTask(id, _):
            tasks.removeAll { $0.id == id || $0.parent == id }
        case let .moveTask(id, _, toList, parent):
            guard let i = tasks.firstIndex(where: { $0.id == id }) else { return }
            tasks[i].parent = parent
            if let toList {
                tasks[i].listID = toList
                for j in tasks.indices where tasks[j].parent == id { tasks[j].listID = toList }
            }
        case let .createList(id, title):
            lists.removeAll { $0.id == id }
            lists.append(TaskListRecord(id: id, title: title))
        case let .renameList(id, title):
            if let i = lists.firstIndex(where: { $0.id == id }) { lists[i].title = title }
        case let .deleteList(id):
            lists.removeAll { $0.id == id }
            tasks.removeAll { $0.listID == id }
        case let .createEvent(id, calendarID, d):
            events.removeAll { $0.id == id }
            events.append(EventRecord(id: id, calendarID: calendarID, title: d.title, location: d.location, notes: d.notes,
                                      start: d.start, end: d.end, allDay: d.allDay))
        case let .updateEvent(id, _, d):
            guard let i = events.firstIndex(where: { $0.id == id }) else { return }
            events[i].title = d.title
            events[i].location = d.location
            events[i].notes = d.notes
            events[i].start = d.start
            events[i].end = d.end
            events[i].allDay = d.allDay
        case let .deleteEvent(id, _):
            events.removeAll { $0.id == id }
        case let .moveEvent(id, _, to):
            if let i = events.firstIndex(where: { $0.id == id }) { events[i].calendarID = to }
        }
    }

    /// Applies locally and queues for upload, collapsing changes to items that never reached the server.
    public mutating func enqueue(_ change: Change, at date: Date = Date()) {
        let children = Set(tasks.filter { t in
            if case let .deleteTask(id, _) = change { return t.parent == id }
            return false
        }.map(\.id))
        apply(change)
        switch change {
        case let .deleteTask(id, _) where Self.isLocal(id):
            pending.removeAll { p in p.change.touches(task: id) || children.contains { p.change.touches(task: $0) } }
            return
        case let .deleteList(id) where Self.isLocal(id):
            pending.removeAll { $0.change.touches(list: id) }
            return
        case let .deleteEvent(id, _) where Self.isLocal(id):
            pending.removeAll { $0.change.touches(event: id) }
            return
        default:
            pending.append(PendingChange(change: change, queuedAt: date))
        }
    }

    /// Replaces a temporary ID everywhere once the server assigned the real one.
    mutating func remap(task old: String, to new: String) {
        for i in tasks.indices {
            if tasks[i].id == old { tasks[i].id = new }
            if tasks[i].parent == old { tasks[i].parent = new }
        }
        for i in pending.indices { pending[i].change = pending[i].change.replacing(task: old, with: new) }
    }

    mutating func remap(list old: String, to new: String) {
        for i in lists.indices where lists[i].id == old { lists[i].id = new }
        for i in tasks.indices where tasks[i].listID == old { tasks[i].listID = new }
        for i in pending.indices { pending[i].change = pending[i].change.replacing(list: old, with: new) }
    }

    mutating func remap(event old: String, to record: EventRecord) {
        events.removeAll { $0.id == old || $0.id == record.id }
        events.append(record)
        for i in pending.indices { pending[i].change = pending[i].change.replacing(event: old, with: record.id) }
    }

    // MARK: Merging pulled data

    /// Local-only items are dropped by a full merge too; `reapplyPending` restores the ones still queued.
    mutating func mergeTasks(list: String, records: [TaskRecord], full: Bool) {
        if full { tasks.removeAll { $0.listID == list } }
        for r in records {
            // A task moved to another list keeps its ID and leaves a deleted copy behind.
            if r.deleted {
                tasks.removeAll { $0.id == r.id && $0.listID == list }
            } else {
                tasks.removeAll { $0.id == r.id }
                tasks.append(r)
            }
        }
    }

    /// After a rejected change, the next pull re-reads what it touched in full so the server copy wins.
    mutating func invalidate(for change: Change) {
        switch change {
        case let .createTask(_, l, _, _, _, _), let .updateTask(_, l, _), let .deleteTask(_, l):
            tasksPulledAt[l] = nil
        case let .moveTask(_, l, to, _):
            tasksPulledAt[l] = nil
            if let to { tasksPulledAt[to] = nil }
        case .createList, .renameList, .deleteList:
            tasksPulledAt = [:]
        case let .createEvent(_, c, _), let .updateEvent(_, c, _), let .deleteEvent(_, c):
            calendarSyncTokens[c] = nil
        case let .moveEvent(_, c, to):
            calendarSyncTokens[c] = nil
            calendarSyncTokens[to] = nil
        }
    }

    mutating func mergeEvents(calendar: String, records: [EventRecord], full: Bool) {
        if full { events.removeAll { $0.calendarID == calendar } }
        for r in records {
            events.removeAll { $0.id == r.id && $0.calendarID == calendar }
            if !r.cancelled { events.append(r) }
        }
    }

    mutating func pruneEvents(keepingFrom start: Date, to end: Date) {
        events.removeAll { $0.end < start || $0.start > end }
    }

    /// Server data replaced the cache; local changes still queued must show on top of it.
    mutating func reapplyPending() {
        for p in pending { apply(p.change) }
    }
}

extension Change {
    var summary: String {
        switch self {
        case let .createTask(_, _, title, _, _, _): "新建任务「\(title)」"
        case .updateTask: "修改任务"
        case .deleteTask: "删除任务"
        case .moveTask: "移动任务"
        case let .createList(_, title): "新建清单「\(title)」"
        case .renameList: "重命名清单"
        case .deleteList: "删除清单"
        case let .createEvent(_, _, d): "新建日程「\(d.title)」"
        case let .updateEvent(_, _, d): "修改日程「\(d.title)」"
        case .deleteEvent: "删除日程"
        case .moveEvent: "移动日程"
        }
    }

    func touches(task id: String) -> Bool {
        switch self {
        case let .createTask(t, _, _, _, _, parent): t == id || parent == id
        case let .updateTask(t, _, _), let .deleteTask(t, _): t == id
        case let .moveTask(t, _, _, parent): t == id || parent == id
        default: false
        }
    }

    func touches(list id: String) -> Bool {
        switch self {
        case let .createTask(_, l, _, _, _, _), let .updateTask(_, l, _), let .deleteTask(_, l): l == id
        case let .moveTask(_, l, to, _): l == id || to == id
        case let .createList(l, _), let .renameList(l, _), let .deleteList(l): l == id
        default: false
        }
    }

    func touches(event id: String) -> Bool {
        switch self {
        case let .createEvent(e, _, _), let .updateEvent(e, _, _), let .deleteEvent(e, _), let .moveEvent(e, _, _): e == id
        default: false
        }
    }

    func replacing(event old: String, with new: String) -> Change {
        let r = { (s: String) in s == old ? new : s }
        switch self {
        case let .updateEvent(e, c, d): return .updateEvent(id: r(e), calendarID: c, draft: d)
        case let .deleteEvent(e, c): return .deleteEvent(id: r(e), calendarID: c)
        case let .moveEvent(e, c, to): return .moveEvent(id: r(e), calendarID: c, to: to)
        default: return self
        }
    }

    func replacing(task old: String, with new: String) -> Change {
        let r = { (s: String) in s == old ? new : s }
        let ro = { (s: String?) in s.map(r) }
        switch self {
        case let .createTask(t, l, title, notes, due, parent): return .createTask(id: r(t), listID: l, title: title, notes: notes, due: due, parent: ro(parent))
        case let .updateTask(t, l, p): return .updateTask(id: r(t), listID: l, patch: p)
        case let .deleteTask(t, l): return .deleteTask(id: r(t), listID: l)
        case let .moveTask(t, l, to, parent): return .moveTask(id: r(t), listID: l, toList: to, parent: ro(parent))
        default: return self
        }
    }

    func replacing(list old: String, with new: String) -> Change {
        let r = { (s: String) in s == old ? new : s }
        switch self {
        case let .createTask(t, l, title, notes, due, parent): return .createTask(id: t, listID: r(l), title: title, notes: notes, due: due, parent: parent)
        case let .updateTask(t, l, p): return .updateTask(id: t, listID: r(l), patch: p)
        case let .deleteTask(t, l): return .deleteTask(id: t, listID: r(l))
        case let .moveTask(t, l, to, parent): return .moveTask(id: t, listID: r(l), toList: to.map(r), parent: parent)
        case let .createList(l, title): return .createList(id: r(l), title: title)
        case let .renameList(l, title): return .renameList(id: r(l), title: title)
        case let .deleteList(l): return .deleteList(id: r(l))
        default: return self
        }
    }
}
