import Foundation

/// A quick-task line such as "明天下午3点 和李雷对齐方案 #工作", split into its parts.
public struct QuickEntry: Equatable, Sendable {
    public var title: String
    /// Start of day when `hasTime` is false.
    public var due: Date?
    public var hasTime: Bool
    /// Text after `#`, matched against list names by the caller.
    public var listTag: String?
    /// The phrases that produced `due`, e.g. ["明天", "下午3点"].
    public var datePhrases: [String]

    public init(title: String, due: Date? = nil, hasTime: Bool = false, listTag: String? = nil, datePhrases: [String] = []) {
        self.title = title
        self.due = due
        self.hasTime = hasTime
        self.listTag = listTag
        self.datePhrases = datePhrases
    }
}

public enum QuickEntryParser {
    public static func parse(_ text: String, now: Date = Date(), calendar: Calendar = .hub) -> QuickEntry {
        var working = text
        var phrases: [String] = []

        var listTag: String?
        if let m = firstMatch(tagPattern, in: working) {
            listTag = String(working[m.range(1)])
            working.replaceSubrange(m.range(0), with: gap)
        }

        let today = calendar.startOfDay(for: now)
        var day: Date?
        var impliedPeriod: Period?
        if let found = DayRule.all.compactMap({ rule in rule.match(working, today: today, calendar: calendar).map { (rule, $0) } })
            .min(by: { a, b in
                a.1.range.lowerBound != b.1.range.lowerBound
                    ? a.1.range.lowerBound < b.1.range.lowerBound
                    : working.distance(from: a.1.range.lowerBound, to: a.1.range.upperBound) > working.distance(from: b.1.range.lowerBound, to: b.1.range.upperBound)
            }) {
            day = found.1.date
            impliedPeriod = found.1.period
            phrases.append(String(working[found.1.range]))
            working.replaceSubrange(found.1.range, with: gap)
        }

        var time: (hour: Int, minute: Int)?
        if let t = matchTime(working, impliedPeriod: impliedPeriod) {
            time = (t.hour, t.minute)
            phrases.append(String(working[t.range]))
            working.replaceSubrange(t.range, with: gap)
        } else if let p = impliedPeriod {
            time = (p.defaultHour, 0)
        }

        var due: Date?
        if let time {
            let base = day ?? today
            var at = calendar.date(bySettingHour: time.hour, minute: time.minute, second: 0, of: base) ?? base
            if day == nil, at <= now { at = calendar.date(byAdding: .day, value: 1, to: at) ?? at }
            due = at
        } else {
            due = day
        }

        let title = cleanTitle(working)
        return QuickEntry(title: title, due: due, hasTime: time != nil, listTag: listTag, datePhrases: phrases)
    }

    // MARK: Time of day

    enum Period: String, CaseIterable {
        case dawn = "凌晨", morning = "早上", morning2 = "早晨", forenoon = "上午", noon = "中午"
        case afternoon = "下午", dusk = "傍晚", evening = "晚上", night = "夜里"

        var defaultHour: Int {
            switch self {
            case .dawn: 6
            case .morning, .morning2: 8
            case .forenoon: 9
            case .noon: 12
            case .afternoon: 15
            case .dusk: 18
            case .evening, .night: 20
            }
        }

        func hour24(_ h: Int) -> Int {
            switch self {
            case .afternoon, .dusk, .evening, .night: h < 12 ? h + 12 : h
            case .noon: h <= 2 ? h + 12 : h
            default: h == 12 ? 0 : h
            }
        }
    }

    private static let periodAlternation = Period.allCases.map(\.rawValue).joined(separator: "|")

    private static func matchTime(_ s: String, impliedPeriod: Period?) -> (hour: Int, minute: Int, range: Range<String.Index>)? {
        let clock = #"(?:("# + periodAlternation + #")\s*)?(\d{1,2})\s*[:：]\s*(\d{2})"#
        let spoken = #"(?:("# + periodAlternation + #")\s*)?("# + num + #")\s*[点點时](?:\s*(半|一刻|三刻|("# + num + #")\s*分?))?"#
        let bare = #"("# + periodAlternation + #")"#
        for (pattern, kind) in [(clock, 0), (spoken, 1), (bare, 2)] {
            guard let m = firstMatch(pattern, in: s) else { continue }
            let period = m.optional(1, in: s).flatMap { Period(rawValue: $0) } ?? impliedPeriod
            if kind == 2 {
                guard let p = period else { continue }
                return (p.defaultHour, 0, m.range(0))
            }
            guard var hour = number(String(s[m.range(2)])), hour <= 24 else { continue }
            var minute = 0
            if kind == 0 {
                minute = Int(s[m.range(3)]) ?? 0
            } else if let extra = m.optional(3, in: s) {
                switch extra {
                case "半": minute = 30
                case "一刻": minute = 15
                case "三刻": minute = 45
                default: minute = m.optional(4, in: s).flatMap(number) ?? 0
                }
            }
            guard minute < 60 else { continue }
            if let period {
                hour = period.hour24(hour)
            } else if kind == 1, (1...6).contains(hour) {
                // Spoken "3点" in a task almost always means the afternoon.
                hour += 12
            }
            if hour == 24 { hour = 0 }
            return (hour, minute, m.range(0))
        }
        return nil
    }

    // MARK: Days

    struct DayMatch {
        var date: Date
        var range: Range<String.Index>
        var period: Period?
    }

    struct DayRule {
        var pattern: String
        var resolve: (_ m: Match, _ s: String, _ today: Date, _ cal: Calendar) -> (Date, Period?)?

        func match(_ s: String, today: Date, calendar: Calendar) -> DayMatch? {
            guard let m = firstMatch(pattern, in: s), let (date, period) = resolve(m, s, today, calendar) else { return nil }
            return DayMatch(date: date, range: m.range(0), period: period)
        }

        static let all: [DayRule] = [
            DayRule(pattern: #"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})\s*[日号]?"#) { m, s, _, cal in
                guard let y = Int(s[m.range(1)]), let mo = Int(s[m.range(2)]), let d = Int(s[m.range(3)]) else { return nil }
                return cal.date(from: DateComponents(year: y, month: mo, day: d)).map { ($0, nil) }
            },
            DayRule(pattern: "(" + num + #")\s*月\s*("# + num + #")\s*[日号]?"#) { m, s, today, cal in
                guard let mo = number(String(s[m.range(1)])), let d = number(String(s[m.range(2)])) else { return nil }
                return nextMonthDay(month: mo, day: d, today: today, cal: cal).map { ($0, nil) }
            },
            DayRule(pattern: #"(?<![\d:：])(\d{1,2})/(\d{1,2})(?![\d/])"#) { m, s, today, cal in
                guard let mo = Int(s[m.range(1)]), let d = Int(s[m.range(2)]) else { return nil }
                return nextMonthDay(month: mo, day: d, today: today, cal: cal).map { ($0, nil) }
            },
            DayRule(pattern: #"(下下个?|下个?|这个?|本|上个?)?(?:周|星期|礼拜)([一二三四五六日天七1-7])"#) { m, s, today, cal in
                guard let target = weekday(String(s[m.range(2)])) else { return nil }
                let prefix = m.optional(1, in: s) ?? ""
                let current = mondayIndex(today, cal)
                let monday = cal.date(byAdding: .day, value: -current, to: today)!
                let weeks: Int
                switch prefix {
                case "": weeks = target >= current ? 0 : 1
                case let p where p.hasPrefix("下下"): weeks = 2
                case let p where p.hasPrefix("下"): weeks = 1
                case let p where p.hasPrefix("上"): weeks = -1
                default: weeks = 0
                }
                return cal.date(byAdding: .day, value: weeks * 7 + target, to: monday).map { ($0, nil) }
            },
            DayRule(pattern: #"(下下个?|下个?|这个?|本)?周末"#) { m, s, today, cal in
                let prefix = m.optional(1, in: s) ?? ""
                let current = mondayIndex(today, cal)
                let monday = cal.date(byAdding: .day, value: -current, to: today)!
                let weeks = prefix.hasPrefix("下下") ? 2 : prefix.hasPrefix("下") ? 1 : (current == 6 ? 1 : 0)
                return cal.date(byAdding: .day, value: weeks * 7 + 5, to: monday).map { ($0, nil) }
            },
            DayRule(pattern: #"(下个?月|本月|这个?月)?(?:月底|月末|底)"#) { m, s, today, cal in
                let prefix = m.optional(1, in: s) ?? ""
                // A bare "底" only counts after a month word.
                if prefix.isEmpty, !s[m.range(0)].hasPrefix("月") { return nil }
                let month = cal.date(byAdding: .month, value: prefix.hasPrefix("下") ? 1 : 0, to: today)!
                guard let interval = cal.dateInterval(of: .month, for: month) else { return nil }
                return (cal.date(byAdding: .day, value: -1, to: interval.end)!, nil)
            },
            DayRule(pattern: #"(下个?月)?月初"#) { _, _, today, cal in
                guard let interval = cal.dateInterval(of: .month, for: today) else { return nil }
                return (interval.end, nil)
            },
            DayRule(pattern: #"下个?月\s*("# + num + #")\s*[号日]"#) { m, s, today, cal in
                guard let d = number(String(s[m.range(1)])),
                      let next = cal.date(byAdding: .month, value: 1, to: today) else { return nil }
                var c = cal.dateComponents([.year, .month], from: next)
                c.day = d
                return validDate(c, cal).map { ($0, nil) }
            },
            DayRule(pattern: #"(?<![月\d])("# + num + #")\s*[号](?!码)"#) { m, s, today, cal in
                guard let d = number(String(s[m.range(1)])) else { return nil }
                var c = cal.dateComponents([.year, .month], from: today)
                c.day = d
                guard var date = validDate(c, cal) else { return nil }
                if date < today {
                    let next = cal.date(byAdding: .month, value: 1, to: today)!
                    var n = cal.dateComponents([.year, .month], from: next)
                    n.day = d
                    guard let nd = validDate(n, cal) else { return nil }
                    date = nd
                }
                return (date, nil)
            },
            DayRule(pattern: "(" + num + #")\s*(?:天|日)\s*(?:之后|以后|后)"#) { m, s, today, cal in
                guard let n = number(String(s[m.range(1)])) else { return nil }
                return cal.date(byAdding: .day, value: n, to: today).map { ($0, nil) }
            },
            DayRule(pattern: #"大后天|后天|明天|明日|明儿|今天|今日|今儿|今晚|明晚|今早|明早|下周|下星期|下礼拜"#) { m, s, today, cal in
                let word = String(s[m.range(0)])
                let offsets: [String: (Int, Period?)] = [
                    "今天": (0, nil), "今日": (0, nil), "今儿": (0, nil), "明天": (1, nil), "明日": (1, nil), "明儿": (1, nil),
                    "后天": (2, nil), "大后天": (3, nil), "今晚": (0, .evening), "明晚": (1, .evening),
                    "今早": (0, .morning), "明早": (1, .morning),
                ]
                if let (days, period) = offsets[word] {
                    return cal.date(byAdding: .day, value: days, to: today).map { ($0, period) }
                }
                let current = mondayIndex(today, cal)
                return cal.date(byAdding: .day, value: 7 - current, to: today).map { ($0, nil) }
            },
        ]
    }

    // MARK: Helpers

    private static let gap = "\u{1}"

    /// Removed phrases leave a gap; between CJK text it closes up, elsewhere it becomes one space.
    static func cleanTitle(_ s: String) -> String {
        var out = ""
        let chars = Array(s)
        for (i, c) in chars.enumerated() {
            guard c == Character(gap) else { out.append(c); continue }
            let before = out.last
            let after = chars[(i + 1)...].first { $0 != Character(gap) }
            guard let before, let after, !before.isWhitespace, !after.isWhitespace else { continue }
            if !(isCJK(before) || isCJK(after)) { out.append(" ") }
        }
        return out.split(whereSeparator: \.isWhitespace).joined(separator: " ")
            .trimmingCharacters(in: CharacterSet(charactersIn: "，,、 "))
    }

    private static func isCJK(_ c: Character) -> Bool {
        c.unicodeScalars.contains { (0x3000...0x9FFF).contains($0.value) || (0xFF00...0xFFEF).contains($0.value) }
    }

    static let num = "[0-9]{1,2}|[零〇一二两三四五六七八九十]{1,3}"
    private static let tagPattern = #"#([^\s#]+)"#

    static func number(_ s: String) -> Int? {
        if let n = Int(s) { return n }
        let digits: [Character: Int] = ["零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9]
        let chars = Array(s)
        guard !chars.isEmpty else { return nil }
        if let i = chars.firstIndex(of: "十") {
            let tens = i == 0 ? 1 : (chars.count > 1 ? digits[chars[0]] : nil)
            let ones = i == chars.count - 1 ? 0 : digits[chars[chars.count - 1]]
            guard let tens, let ones, i <= 1, chars.count - i <= 2 else { return nil }
            return tens * 10 + ones
        }
        guard chars.count == 1 else { return nil }
        return digits[chars[0]]
    }

    static func weekday(_ s: String) -> Int? {
        let map: [String: Int] = ["一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6, "七": 6,
                                  "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6]
        return map[s]
    }

    /// Monday = 0 … Sunday = 6.
    static func mondayIndex(_ date: Date, _ cal: Calendar) -> Int {
        (cal.component(.weekday, from: date) + 5) % 7
    }

    static func validDate(_ c: DateComponents, _ cal: Calendar) -> Date? {
        guard let date = cal.date(from: c), cal.component(.day, from: date) == c.day else { return nil }
        return date
    }

    static func nextMonthDay(month: Int, day: Int, today: Date, cal: Calendar) -> Date? {
        let year = cal.component(.year, from: today)
        guard let date = validDate(DateComponents(year: year, month: month, day: day), cal) else { return nil }
        if date >= today { return date }
        return validDate(DateComponents(year: year + 1, month: month, day: day), cal)
    }

    struct Match {
        var result: NSTextCheckingResult
        var string: String
        func range(_ i: Int) -> Range<String.Index> { Range(result.range(at: i), in: string)! }
        func optional(_ i: Int, in s: String) -> String? {
            let r = result.range(at: i)
            guard r.location != NSNotFound, let range = Range(r, in: s) else { return nil }
            return String(s[range])
        }
    }

    static func firstMatch(_ pattern: String, in s: String) -> Match? {
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let r = regex.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) else { return nil }
        return Match(result: r, string: s)
    }
}

extension Calendar {
    /// Gregorian, Monday-first, in the user's time zone.
    public static var hub: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.firstWeekday = 2
        c.locale = Locale(identifier: "zh_CN")
        c.timeZone = .current
        return c
    }
}
