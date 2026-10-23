import Foundation

public struct AgendaTask: Sendable, Identifiable, Hashable {
    public var id: String
    public var listID: String
    public var listTitle: String
    public var title: String
    public var notes: String?
    public var due: Date?
    public var completed: Bool
    public var parentID: String?
    public var subtasks: [AgendaTask]
    public var link: String?
    /// Days past due (0 when due today or later).
    public var overdueDays: Int
    public var completedAt: Date? = nil
    /// Google's manual order within the list; sorts lexically.
    public var position: String? = nil

    private static let timeLine = #"(?m)^时间\s*([01]?\d|2[0-3])[:：]([0-5]\d)\s*$"#

    /// The first line of notes worth showing under the title; the "时间 15:00" line is shown as the time instead.
    public var summaryLine: String? {
        notes?.split(separator: "\n").lazy.map { $0.trimmingCharacters(in: .whitespaces) }
            .first { !$0.isEmpty && $0.range(of: Self.timeLine, options: .regularExpression) == nil }
    }

    /// Google Tasks keeps only the date; a time typed without a time block is saved as a
    /// "时间 15:00" line in the notes.
    public func scheduled(calendar: Calendar = .hub) -> Date? {
        guard let due, let notes,
              let r = notes.range(of: Self.timeLine, options: .regularExpression) else { return nil }
        let digits = notes[r].dropFirst(2).trimmingCharacters(in: .whitespaces).split(whereSeparator: { $0 == ":" || $0 == "：" })
        guard digits.count == 2, let h = Int(digits[0]), let m = Int(digits[1]) else { return nil }
        return calendar.date(bySettingHour: h, minute: m, second: 0, of: calendar.startOfDay(for: due))
    }
}

public struct AgendaEvent: Sendable, Identifiable, Hashable {
    public var id: String
    public var calendarID: String
    public var title: String
    public var location: String?
    public var start: Date
    public var end: Date
    public var allDay: Bool
    public var colorID: String?
    /// Position of the calendar in the calendar list, for a stable fallback colour.
    public var calendarIndex: Int
    public var calendarTitle: String
    public var link: String?
    public var notes: String?
    public var recurring: Bool
    /// On a calendar we can write to, and not a locked invitation.
    public var editable: Bool

    public var draft: EventDraft {
        EventDraft(title: title, start: start, end: end, allDay: allDay, location: location, notes: notes)
    }
}

public struct AgendaView: Sendable {
    public var overdue: [AgendaTask] = []
    public var today: [AgendaTask] = []
    /// Due within the next seven days, after today.
    public var upcoming: [AgendaTask] = []
    public var later: [AgendaTask] = []
    public var undated: [AgendaTask] = []
    /// Every finished top-level task, most recently completed first.
    public var completed: [AgendaTask] = []
    /// Today's timed events, then all-day ones separately.
    public var events: [AgendaEvent] = []
    public var allDay: [AgendaEvent] = []
    /// Everything ahead in the cache, for the popover's "即将" tab.
    public var upcomingEvents: [AgendaEvent] = []
    /// Everything in the cache, cancelled ones removed, by start.
    public var allEvents: [AgendaEvent] = []
    public var nextEvent: AgendaEvent?
    public var currentEvent: AgendaEvent?

    public init() {}

    public var dueCount: Int { overdue.count + today.filter { !$0.completed }.count }
    public var todayDone: Int { today.filter(\.completed).count }
    public var todayTotal: Int { overdue.count + today.count }
    public var allTasks: [AgendaTask] { overdue + today + upcoming + later + undated }
    public var dueNow: [AgendaTask] { overdue + today }

    /// Open tasks of one list in Google's manual order, or by due date (undated last).
    public func open(in listID: String, byDue: Bool = false) -> [AgendaTask] {
        allTasks.filter { $0.listID == listID && !$0.completed }.sorted {
            if byDue, $0.due != $1.due { return ($0.due ?? .distantFuture) < ($1.due ?? .distantFuture) }
            return ($0.position ?? "~") < ($1.position ?? "~")
        }
    }

    public func completed(in listID: String) -> [AgendaTask] { completed.filter { $0.listID == listID } }

    /// Dated open tasks after `today`, one group per day; today and overdue have their own views.
    public func days(from today: Date, calendar: Calendar = .hub) -> [(day: Date, tasks: [AgendaTask])] {
        let start = calendar.startOfDay(for: today)
        let ahead = (upcoming + later).filter { !$0.completed && $0.due != nil }
        let grouped = Dictionary(grouping: ahead) { calendar.startOfDay(for: $0.due!) }
        return grouped.keys.filter { $0 > start }.sorted().map { ($0, grouped[$0]!) }
    }

    /// Tasks due on a day (open, plus ones finished) and the events touching it.
    public func tasks(on day: Date, calendar: Calendar = .hub) -> [AgendaTask] {
        let open = allTasks, seen = Set(open.map(\.id))
        return (open + completed.filter { !seen.contains($0.id) })
            .filter { $0.due.map { calendar.isDate($0, inSameDayAs: day) } ?? false }
            .sorted { $0.completed != $1.completed ? !$0.completed : ($0.position ?? "~") < ($1.position ?? "~") }
    }

    /// Tasks due on a day that carry a time, for the day's schedule.
    public func timedTasks(on day: Date, calendar: Calendar = .hub) -> [(task: AgendaTask, at: Date)] {
        tasks(on: day, calendar: calendar).compactMap { t in t.scheduled(calendar: calendar).map { (t, $0) } }.sorted { $0.at < $1.at }
    }

    public func events(on day: Date, calendar: Calendar = .hub) -> [AgendaEvent] {
        let start = calendar.startOfDay(for: day), end = calendar.date(byAdding: .day, value: 1, to: start)!
        return allEvents.filter { $0.start < end && $0.end > start }.sorted { ($0.allDay ? 0 : 1, $0.start) < ($1.allDay ? 0 : 1, $1.start) }
    }
}

public enum Agenda {
    public static func build(_ store: AgendaStore, now: Date, calendar: Calendar = .hub) -> AgendaView {
        let today = calendar.startOfDay(for: now)
        let tomorrow = calendar.date(byAdding: .day, value: 1, to: today)!
        let week = calendar.date(byAdding: .day, value: 8, to: today)!
        let titles = Dictionary(store.lists.map { ($0.id, $0.title) }, uniquingKeysWith: { a, _ in a })
        let order = Dictionary(store.lists.enumerated().map { ($1.id, $0) }, uniquingKeysWith: { a, _ in a })

        func make(_ r: TaskRecord) -> AgendaTask {
            let due = r.due.flatMap { GoogleDate.day($0, calendar: calendar) }
            let late = due.map { calendar.dateComponents([.day], from: $0, to: today).day ?? 0 } ?? 0
            return AgendaTask(id: r.id, listID: r.listID, listTitle: titles[r.listID] ?? "", title: r.title.isEmpty ? "（无标题）" : r.title,
                              notes: r.notes, due: due, completed: r.completed, parentID: r.parent, subtasks: [], link: r.webLink,
                              overdueDays: max(0, late), completedAt: r.completed ? r.completedAt.flatMap(GoogleDate.rfc3339) : nil,
                              position: r.position)
        }

        let visible = store.tasks.filter { !$0.deleted && titles[$0.listID] != nil }
        let byPosition = visible.sorted { ($0.position ?? "~") < ($1.position ?? "~") }
        let children = Dictionary(grouping: byPosition.filter { $0.parent != nil }, by: { $0.parent! })
        let ids = Set(visible.map(\.id))
        // Orphaned subtasks (parent filtered out) are shown at top level.
        let roots = byPosition.filter { $0.parent == nil || !ids.contains($0.parent!) }.map { r -> AgendaTask in
            var t = make(r)
            t.subtasks = (children[r.id] ?? []).map(make)
            return t
        }

        func completedToday(_ t: AgendaTask) -> Bool {
            guard let r = store.tasks.first(where: { $0.id == t.id }), let at = r.completedAt.flatMap(GoogleDate.rfc3339) else { return false }
            return at >= today
        }

        func sorted(_ items: [AgendaTask]) -> [AgendaTask] {
            items.sorted {
                if $0.completed != $1.completed { return !$0.completed }
                if $0.due != $1.due { return ($0.due ?? .distantFuture) < ($1.due ?? .distantFuture) }
                return (order[$0.listID] ?? 0) < (order[$1.listID] ?? 0)
            }
        }

        var v = AgendaView()
        v.completed = roots.filter(\.completed).sorted { ($0.completedAt ?? .distantPast) > ($1.completedAt ?? .distantPast) }
        for t in roots {
            guard let due = t.due else {
                if !t.completed { v.undated.append(t) }
                continue
            }
            if due < today {
                if !t.completed { v.overdue.append(t) } else if completedToday(t) { v.today.append(t) }
            } else if due < tomorrow {
                v.today.append(t)
            } else if !t.completed {
                if due < week { v.upcoming.append(t) } else { v.later.append(t) }
            }
        }
        v.overdue = sorted(v.overdue)
        v.today = sorted(v.today)
        v.upcoming = sorted(v.upcoming)
        v.later = sorted(v.later)
        v.undated = sorted(v.undated)

        let calendarIndex = Dictionary(store.calendars.enumerated().map { ($1.id, $0) }, uniquingKeysWith: { a, _ in a })
        let calendars = Dictionary(store.calendars.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        let events = store.events.filter { !$0.cancelled }.map { e in
            let cal = calendars[e.calendarID]
            return AgendaEvent(id: e.id, calendarID: e.calendarID, title: e.title, location: e.location, start: e.start, end: e.end,
                               allDay: e.allDay, colorID: e.colorID, calendarIndex: calendarIndex[e.calendarID] ?? 0,
                               calendarTitle: cal?.title ?? "", link: e.link, notes: e.notes, recurring: e.recurring,
                               editable: (cal?.writable ?? false) && e.organizerAllowsEdits)
        }.sorted { $0.start < $1.start }
        let todays = events.filter { $0.start < tomorrow && $0.end > today }
        v.events = todays.filter { !$0.allDay }
        v.allDay = todays.filter(\.allDay)
        v.upcomingEvents = events.filter { $0.end > now && !$0.allDay }
        v.allEvents = events
        v.currentEvent = v.events.first { $0.start <= now && $0.end > now }
        v.nextEvent = events.first { !$0.allDay && $0.start > now }
        return v
    }

    /// Cross-list search over titles, notes and list names; open tasks first, then by due date.
    public static func search(_ store: AgendaStore, query: String, calendar: Calendar = .hub, limit: Int = 30) -> [AgendaTask] {
        let terms = query.split(whereSeparator: \.isWhitespace).map(String.init)
        guard !terms.isEmpty else { return [] }
        let titles = Dictionary(store.lists.map { ($0.id, $0.title) }, uniquingKeysWith: { a, _ in a })
        let today = calendar.startOfDay(for: Date())
        let options: String.CompareOptions = [.caseInsensitive, .diacriticInsensitive, .widthInsensitive]
        return store.tasks
            .filter { r in
                guard !r.deleted, let list = titles[r.listID] else { return false }
                let haystack = [r.title, r.notes ?? "", list].joined(separator: "\n")
                return terms.allSatisfy { haystack.range(of: $0, options: options) != nil }
            }
            .map { r in
                let due = r.due.flatMap { GoogleDate.day($0, calendar: calendar) }
                let late = due.map { calendar.dateComponents([.day], from: $0, to: today).day ?? 0 } ?? 0
                return AgendaTask(id: r.id, listID: r.listID, listTitle: titles[r.listID] ?? "", title: r.title.isEmpty ? "（无标题）" : r.title,
                                  notes: r.notes, due: due, completed: r.completed, parentID: r.parent, subtasks: [], link: r.webLink,
                                  overdueDays: r.completed ? 0 : max(0, late))
            }
            .sorted {
                if $0.completed != $1.completed { return !$0.completed }
                return ($0.due ?? .distantFuture) < ($1.due ?? .distantFuture)
            }
            .prefix(limit).map { $0 }
    }

    // MARK: Text

    /// "45 分钟后", "1 小时 5 分钟后", "明天 09:00".
    public static func countdown(to date: Date, now: Date, calendar: Calendar = .hub) -> String {
        let minutes = Int((date.timeIntervalSince(now) / 60).rounded(.up))
        if minutes <= 0 { return "现在" }
        if minutes < 60 { return "\(minutes) 分钟后" }
        if minutes < 6 * 60 {
            let h = minutes / 60, m = minutes % 60
            return m == 0 ? "\(h) 小时后" : "\(h) 小时 \(m) 分钟后"
        }
        return relativeDay(date, now: now, calendar: calendar) + " " + clock(date, calendar: calendar)
    }

    /// Menu bar text: due count plus the next event, with a countdown once it is within two hours.
    public static func menuTitle(_ v: AgendaView, now: Date, calendar: Calendar = .hub) -> String {
        var parts = ["\(v.dueCount)"]
        if let current = v.currentEvent {
            parts.append("\(current.title) 进行中")
        } else if let next = v.nextEvent, calendar.isDate(next.start, inSameDayAs: now) {
            let minutes = next.start.timeIntervalSince(now) / 60
            parts.append(minutes <= 120 ? "\(next.title) \(shortCountdown(next.start, now: now))" : "\(clock(next.start, calendar: calendar)) \(next.title)")
        }
        return parts.joined(separator: " · ")
    }

    static func shortCountdown(_ date: Date, now: Date) -> String {
        let minutes = Int((date.timeIntervalSince(now) / 60).rounded(.up))
        if minutes < 60 { return "\(max(minutes, 1))m" }
        return "\(minutes / 60)h\(minutes % 60 == 0 ? "" : "\(minutes % 60)m")"
    }

    public static func clock(_ d: Date, calendar: Calendar = .hub) -> String {
        let c = calendar.dateComponents([.hour, .minute], from: d)
        return String(format: "%02d:%02d", c.hour!, c.minute!)
    }

    /// "今天", "明天", "后天", "周五" (within a week), else "10/19".
    public static func relativeDay(_ d: Date, now: Date, calendar: Calendar = .hub) -> String {
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: now), to: calendar.startOfDay(for: d)).day ?? 0
        switch days {
        case 0: return "今天"
        case 1: return "明天"
        case 2: return "后天"
        case -1: return "昨天"
        case 3..<7: return weekdayName(d, calendar: calendar)
        default:
            let c = calendar.dateComponents([.month, .day], from: d)
            return "\(c.month!)/\(c.day!)"
        }
    }

    public static func weekdayName(_ d: Date, calendar: Calendar = .hub) -> String {
        ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][calendar.component(.weekday, from: d) - 1]
    }

    /// "10 月 21 日 周三".
    public static func longDay(_ d: Date, calendar: Calendar = .hub) -> String {
        let c = calendar.dateComponents([.month, .day], from: d)
        return "\(c.month!) 月 \(c.day!) 日 \(weekdayName(d, calendar: calendar))"
    }

    /// Fractional hour of day, for timeline layout.
    public static func hour(_ d: Date, calendar: Calendar = .hub) -> Double {
        let c = calendar.dateComponents([.hour, .minute], from: d)
        return Double(c.hour!) + Double(c.minute!) / 60
    }
}
