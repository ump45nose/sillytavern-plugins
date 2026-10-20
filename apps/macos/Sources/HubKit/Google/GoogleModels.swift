import Foundation

public struct TaskListRecord: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var title: String
    public var updated: String?

    public init(id: String, title: String, updated: String? = nil) {
        self.id = id
        self.title = title
        self.updated = updated
    }
}

public struct TaskRecord: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var listID: String
    public var title: String
    public var notes: String?
    /// `yyyy-MM-dd`; Google Tasks keeps only the date part of `due`.
    public var due: String?
    public var completed: Bool
    public var completedAt: String?
    public var parent: String?
    public var position: String?
    public var updated: String?
    public var deleted: Bool
    public var webLink: String?

    public init(id: String, listID: String, title: String, notes: String? = nil, due: String? = nil, completed: Bool = false,
                completedAt: String? = nil, parent: String? = nil, position: String? = nil, updated: String? = nil,
                deleted: Bool = false, webLink: String? = nil) {
        self.id = id
        self.listID = listID
        self.title = title
        self.notes = notes
        self.due = due
        self.completed = completed
        self.completedAt = completedAt
        self.parent = parent
        self.position = position
        self.updated = updated
        self.deleted = deleted
        self.webLink = webLink
    }

    init(api: [String: Any], listID: String) {
        self.init(id: api["id"] as? String ?? "", listID: listID, title: api["title"] as? String ?? "",
                  notes: (api["notes"] as? String).flatMap { $0.isEmpty ? nil : $0 },
                  due: (api["due"] as? String).map { String($0.prefix(10)) },
                  completed: api["status"] as? String == "completed", completedAt: api["completed"] as? String,
                  parent: api["parent"] as? String, position: api["position"] as? String, updated: api["updated"] as? String,
                  deleted: api["deleted"] as? Bool ?? false, webLink: api["webViewLink"] as? String)
    }
}

public struct CalendarRecord: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var title: String
    public var primary: Bool
    public var colorHex: String?
    /// `owner`, `writer`, `reader` or `freeBusyReader`.
    public var accessRole: String
    public var selected: Bool

    public init(id: String, title: String, primary: Bool = false, colorHex: String? = nil, accessRole: String = "owner", selected: Bool = true) {
        self.id = id
        self.title = title
        self.primary = primary
        self.colorHex = colorHex
        self.accessRole = accessRole
        self.selected = selected
    }

    init(api: [String: Any]) {
        self.init(id: api["id"] as? String ?? "",
                  title: api["summaryOverride"] as? String ?? api["summary"] as? String ?? "",
                  primary: api["primary"] as? Bool ?? false, colorHex: api["backgroundColor"] as? String,
                  accessRole: api["accessRole"] as? String ?? "reader",
                  selected: (api["selected"] as? Bool ?? false) && !(api["hidden"] as? Bool ?? false))
    }
}

public struct EventRecord: Codable, Sendable, Identifiable, Hashable {
    public var id: String
    public var calendarID: String
    public var title: String
    public var location: String?
    public var start: Date
    public var end: Date
    public var allDay: Bool
    public var cancelled: Bool
    public var link: String?
    /// Google event colour 1–11, mapped to the app palette by the UI.
    public var colorID: String?

    public init(id: String, calendarID: String, title: String, location: String? = nil, start: Date, end: Date,
                allDay: Bool = false, cancelled: Bool = false, link: String? = nil, colorID: String? = nil) {
        self.id = id
        self.calendarID = calendarID
        self.title = title
        self.location = location
        self.start = start
        self.end = end
        self.allDay = allDay
        self.cancelled = cancelled
        self.link = link
        self.colorID = colorID
    }

    /// Cancelled instances in incremental syncs carry only `id` and `status`.
    init?(api: [String: Any], calendarID: String, calendar: Calendar) {
        guard let id = api["id"] as? String else { return nil }
        let cancelled = api["status"] as? String == "cancelled"
        let s = api["start"] as? [String: Any] ?? [:], e = api["end"] as? [String: Any] ?? [:]
        let allDay = s["date"] != nil
        let start = GoogleDate.parse(s, calendar: calendar), end = GoogleDate.parse(e, calendar: calendar)
        guard cancelled || start != nil else { return nil }
        self.init(id: id, calendarID: calendarID, title: api["summary"] as? String ?? "（无标题）",
                  location: (api["location"] as? String).flatMap { $0.isEmpty ? nil : $0 },
                  start: start ?? .distantPast, end: end ?? start ?? .distantPast, allDay: allDay,
                  cancelled: cancelled, link: api["htmlLink"] as? String, colorID: api["colorId"] as? String)
    }
}

public enum GoogleDate {
    private static let internet: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private static let fractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    public static func rfc3339(_ s: String) -> Date? { internet.date(from: s) ?? fractional.date(from: s) }

    public static func string(_ d: Date) -> String { internet.string(from: d) }

    /// `yyyy-MM-dd` in the given calendar's time zone.
    public static func day(_ s: String, calendar: Calendar) -> Date? {
        let parts = s.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
    }

    public static func dayString(_ d: Date, calendar: Calendar) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year!, c.month!, c.day!)
    }

    static func parse(_ value: [String: Any], calendar: Calendar) -> Date? {
        if let dt = value["dateTime"] as? String { return rfc3339(dt) }
        if let d = value["date"] as? String { return day(d, calendar: calendar) }
        return nil
    }
}
