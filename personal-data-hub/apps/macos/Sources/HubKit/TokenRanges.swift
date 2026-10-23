import Foundation

public enum TokenRange: String, CaseIterable, Sendable, Codable {
    case day, week, month, year

    public var label: String {
        switch self { case .day: "日"; case .week: "周"; case .month: "月"; case .year: "年" }
    }

    /// Rolling window length in days.
    public var days: Int {
        switch self { case .day: 1; case .week: 7; case .month: 30; case .year: 371 }
    }
}

public struct TokenHeatmap: Sendable {
    public var title: String
    public var rowLabels: [String]
    public var columnLabels: [String]
    /// Row-major values in millions of tokens; nil marks an unknown or future slot.
    public var values: [[Double?]]
    public var tips: [[String]]
    public var dense: Bool

    public var columns: Int { columnLabels.count }
    public var maxValue: Double { values.flatMap { $0.compactMap { $0 } }.max() ?? 1 }
    public var isEmpty: Bool { values.allSatisfy { $0.allSatisfy { $0 == nil } } }

    /// Six intensity levels; -1 means no value.
    public func level(_ v: Double?) -> Int {
        guard let v else { return -1 }
        let r = v / max(maxValue, 0.000_001)
        switch r {
        case ..<0.08: return 0
        case ..<0.25: return 1
        case ..<0.45: return 2
        case ..<0.65: return 3
        case ..<0.85: return 4
        default: return 5
        }
    }
}

/// What the Token detail view shows for one range, derived from hub data. Values are in millions
/// of tokens; anything the source does not provide stays nil.
public struct TokenRangeSummary: Sendable {
    public struct Part: Sendable, Identifiable {
        public var id: String
        public var name: String
        public var total: Double?
        public var cost: Double? = nil

        public init(id: String, name: String, total: Double?, cost: Double? = nil) {
            self.id = id
            self.name = name
            self.total = total
            self.cost = cost
        }

        /// The first `limit` parts, the rest folded into one「其他」row.
        public static func top(_ parts: [Part], _ limit: Int) -> [Part] {
            guard parts.count > limit else { return parts }
            let rest = parts.dropFirst(limit)
            let cost = rest.contains { $0.cost != nil } ? rest.compactMap(\.cost).reduce(0, +) : nil
            return Array(parts.prefix(limit)) + [Part(id: "_other", name: "其他 \(rest.count) 个", total: rest.compactMap(\.total).reduce(0, +), cost: cost)]
        }
    }
    public var range: TokenRange
    public var periodLabel: String
    public var total: Double?
    public var previous: Double?
    public var cost: Double?
    public var comparisonLabel: String
    public var peakLabel: String?
    public var peakValue: Double?
    public var averageLabel: String
    public var average: Double?
    public var tools: [Part]?
    public var devices: [Part]?
    public var models: [Part]?
    public var sessions: [TokenData.Session]?
    public var heatmap: TokenHeatmap?

    public var deltaPercent: Int? {
        guard let total, let previous, previous > 0 else { return nil }
        return Int(((total / previous) - 1) * 100)
    }

    /// Daily totals keyed by `YYYY-MM-DD`, taken from the year range's per-day grid.
    public static func daily(from year: TokenData?, calendar: Calendar = .hub) -> [String: Double] {
        guard let year, year.range == .year, let start = year.period.flatMap({ TokenText.day($0.start, calendar) }),
              let cells = year.buckets?.series.first?.values else { return [:] }
        var out: [String: Double] = [:]
        for (i, v) in cells.enumerated() {
            guard let v else { continue }
            out[TokenText.key(calendar.date(byAdding: .day, value: i, to: start)!, calendar)] = v
        }
        return out
    }

    /// `daily` (raw tokens per day, see `daily(from:)`) fills in what week and month lack.
    public init(_ d: TokenData, now: Date, daily: [String: Double] = [:], calendar: Calendar = .hub) {
        func m(_ v: Double?) -> Double? { v.map { $0 / 1_000_000 } }
        let today = calendar.startOfDay(for: now)
        let start = d.period.flatMap { TokenText.day($0.start, calendar) } ?? calendar.date(byAdding: .day, value: 1 - d.range.days, to: today)!
        let end = d.period.flatMap { TokenText.day($0.end, calendar) } ?? today
        range = d.range
        total = m(d.total)
        previous = m(d.previous)
        cost = d.cost
        func parts(_ ps: [TokenData.Part]?) -> [Part]? {
            ps?.map { Part(id: $0.id, name: $0.name, total: m($0.total), cost: $0.cost) }.sorted { ($0.total ?? 0) > ($1.total ?? 0) }
        }
        tools = parts(d.tools)
        devices = parts(d.devices)
        models = parts(d.models)
        sessions = d.sessions?.map { var s = $0; s.total = m(s.total); return s }.sorted { ($0.total ?? 0) > ($1.total ?? 0) }
        let hour = calendar.component(.hour, from: now)
        let series = (d.buckets?.series ?? []).map { (key: $0.key, values: $0.values.map(m)) }
        func sum(_ vs: [Double?]) -> Double? { vs.contains { $0 != nil } ? vs.reduce(0) { $0 + ($1 ?? 0) } : nil }

        switch d.range {
        case .day:
            periodLabel = "今天 · \(TokenText.longDay(today, calendar))"
            comparisonLabel = "较昨天"
            averageLabel = "本小时"
            let byHour = (0..<24).map { h in sum(series.map { $0.values.indices.contains(h) ? $0.values[h] : nil }) }
            if let peak = byHour.indices.filter({ byHour[$0] != nil }).max(by: { byHour[$0]! < byHour[$1]! }) {
                peakLabel = String(format: "%02d:00", peak)
                peakValue = byHour[peak]
            }
            average = byHour.indices.contains(hour) ? byHour[hour] : nil
            let names = Dictionary((d.tools ?? []).map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a })
            heatmap = series.isEmpty ? nil : TokenHeatmap(
                title: "按小时 × 工具", rowLabels: series.map { names[$0.key] ?? $0.key }, columnLabels: TokenText.hourLabels,
                values: series.map { Array($0.values.prefix(24)) }, tips: series.map { s in (0..<24).map { "\(names[s.key] ?? s.key) · \(String(format: "%02d", $0)):00" } }, dense: false)
        case .week, .month:
            let n = d.range.days
            periodLabel = "近 \(n) 天 · \(TokenText.md(start, calendar)) – \(TokenText.md(end, calendar))"
            comparisonLabel = "较前 \(n) 天"
            averageLabel = "日均"
            average = total.map { $0 / Double(n) }
            if d.range == .week {
                let daily = series.map { (key: $0.key, total: sum($0.values)) }
                if let best = daily.filter({ $0.total != nil }).max(by: { $0.total! < $1.total! }), let date = TokenText.day(best.key, calendar) {
                    peakLabel = "\(TokenText.weekday(date, calendar)) \(TokenText.md(date, calendar))"
                    peakValue = best.total
                }
                heatmap = series.isEmpty ? nil : TokenHeatmap(
                    title: "按小时 × 日期",
                    rowLabels: series.map { s in TokenText.day(s.key, calendar).map { calendar.isDate($0, inSameDayAs: today) ? "今天" : TokenText.weekday($0, calendar) } ?? s.key },
                    columnLabels: TokenText.hourLabels, values: series.map { Array($0.values.prefix(24)) },
                    tips: series.map { s in (0..<24).map { "\(s.key) · \(String(format: "%02d", $0)):00" } }, dense: false)
            } else if !series.isEmpty {
                let names = Dictionary((d.tools ?? []).map { ($0.id, $0.name) }, uniquingKeysWith: { a, _ in a })
                let days = (0..<n).map { calendar.date(byAdding: .day, value: $0, to: start)! }
                let labels = days.indices.map { k in (n - 1 - k) % 7 != 0 ? "" : k == n - 1 ? "今天" : TokenText.md(days[k], calendar) }
                heatmap = TokenHeatmap(title: "按日期 × 工具", rowLabels: series.map { names[$0.key] ?? $0.key }, columnLabels: labels,
                                       values: series.map { Array($0.values.prefix(n)) },
                                       tips: series.map { s in days.map { "\(names[s.key] ?? s.key) · \(TokenText.md($0, calendar))" } }, dense: false)
            }
            if heatmap?.isEmpty ?? true {
                let days = (0..<n).map { calendar.date(byAdding: .day, value: $0, to: start)! }
                let values = days.map { daily[TokenText.key($0, calendar)].map { $0 / 1_000_000 } }
                if peakLabel == nil, let best = values.indices.filter({ values[$0] != nil }).max(by: { values[$0]! < values[$1]! }) {
                    peakLabel = "\(TokenText.weekday(days[best], calendar)) \(TokenText.md(days[best], calendar))"
                    peakValue = values[best]
                }
                let labels = days.indices.map { k in
                    n == 7 ? (calendar.isDate(days[k], inSameDayAs: today) ? "今天" : TokenText.weekday(days[k], calendar))
                        : (n - 1 - k) % 7 != 0 ? "" : k == n - 1 ? "今天" : TokenText.md(days[k], calendar)
                }
                heatmap = TokenHeatmap(title: "按日期", rowLabels: ["合计"], columnLabels: labels, values: [values],
                                       tips: [days.map { "\(TokenText.weekday($0, calendar)) \(TokenText.md($0, calendar))" }], dense: false)
            }
        case .year:
            periodLabel = "近一年 · \(TokenText.ymd(start, calendar)) – \(TokenText.ymd(end, calendar))"
            comparisonLabel = "较前一年"
            averageLabel = "日均"
            let cells = series.first?.values ?? []
            let known = cells.compactMap { $0 }
            average = known.isEmpty ? nil : known.reduce(0, +) / Double(known.count)
            if let best = cells.indices.filter({ cells[$0] != nil }).max(by: { cells[$0]! < cells[$1]! }) {
                peakLabel = TokenText.md(calendar.date(byAdding: .day, value: best, to: start)!, calendar)
                peakValue = cells[best]
            }
            if cells.count >= 7 {
                let weeks = cells.count / 7
                var values = Array(repeating: [Double?](repeating: nil, count: weeks), count: 7)
                var tips = Array(repeating: [String](repeating: "", count: weeks), count: 7)
                var labels = [String](repeating: "", count: weeks)
                var lastMonth = -1
                for c in 0..<weeks {
                    for r in 0..<7 {
                        let i = c * 7 + r, date = calendar.date(byAdding: .day, value: i, to: start)!
                        values[r][c] = cells[i]
                        tips[r][c] = "\(TokenText.ymd(date, calendar)) \(TokenText.weekday(date, calendar))"
                        let month = calendar.component(.month, from: date)
                        if r == 0, month != lastMonth { lastMonth = month; if c < weeks - 2 { labels[c] = "\(month)月" } }
                    }
                }
                heatmap = TokenHeatmap(title: "按周 × 星期", rowLabels: ["一", "", "三", "", "五", "", "日"], columnLabels: labels,
                                       values: values, tips: tips, dense: true)
            }
        }
        if heatmap?.isEmpty == true { heatmap = nil }
    }
}

/// Every recorded day up to today, for the all-time heatmap and trend. Values are in millions of tokens.
public struct TokenHistory: Sendable {
    public struct Day: Sendable, Equatable {
        public var date: Date
        public var total: Double?
        public var cost: Double?
    }
    public struct Cell: Sendable, Equatable {
        public var date: Date
        /// nil before the first record and after today.
        public var day: Day?
    }
    public struct Year: Sendable {
        public var year: Int
        /// Monday-first weeks; every week has seven cells.
        public var weeks: [[Cell]]
        /// Week index where each month's first day falls.
        public var months: [(week: Int, month: Int)]
    }

    public var days: [Day]
    /// From hub's own history; false means it was rebuilt from the year grid, which has no daily cost.
    public var exact: Bool
    private var rangeCost: Double?

    public var first: Date { days[0].date }
    public var total: Double { days.reduce(0) { $0 + ($1.total ?? 0) } }
    public var cost: Double? {
        guard exact else { return rangeCost }
        let known = days.compactMap(\.cost)
        return known.isEmpty ? nil : known.reduce(0, +)
    }
    public var average: Double { total / Double(days.count) }
    public var best: Day? { days.filter { $0.total != nil }.max { $0.total! < $1.total! } }
    public var maxValue: Double { days.compactMap(\.total).max() ?? 0 }

    public func years(_ calendar: Calendar = .hub) -> [Int] {
        let a = calendar.component(.year, from: first), b = calendar.component(.year, from: days[days.count - 1].date)
        return Array(a...b)
    }

    /// Trailing mean over `n` days; days without a record count as zero.
    public func movingAverage(_ n: Int) -> [Double] {
        var out: [Double] = [], sum = 0.0
        for (i, d) in days.enumerated() {
            sum += d.total ?? 0
            if i >= n { sum -= days[i - n].total ?? 0 }
            out.append(sum / Double(min(i + 1, n)))
        }
        return out
    }

    public func year(_ year: Int, calendar: Calendar = .hub) -> Year {
        var cal = calendar
        cal.firstWeekday = 2
        let jan1 = cal.date(from: DateComponents(year: year, month: 1, day: 1))!
        let dec31 = cal.date(from: DateComponents(year: year, month: 12, day: 31))!
        let start = cal.dateInterval(of: .weekOfYear, for: jan1)!.start
        let byDay = Dictionary(days.map { (cal.startOfDay(for: $0.date), $0) }, uniquingKeysWith: { a, _ in a })
        var weeks: [[Cell]] = [], months: [(Int, Int)] = []
        var day = start
        while day <= dec31 {
            var week: [Cell] = []
            for _ in 0..<7 {
                let inYear = cal.component(.year, from: day) == year
                if inYear, cal.component(.day, from: day) == 1 { months.append((weeks.count, cal.component(.month, from: day))) }
                week.append(Cell(date: day, day: inYear ? byDay[day] : nil))
                day = cal.date(byAdding: .day, value: 1, to: day)!
            }
            weeks.append(week)
        }
        return Year(year: year, weeks: weeks, months: months)
    }

    /// hub's `history` when it has one; otherwise the year range's daily grid, starting at its first non-zero day.
    public static func make(history: [TokenData.Day]?, yearGrid: TokenData?, now: Date, calendar: Calendar = .hub) -> TokenHistory? {
        let today = calendar.startOfDay(for: now)
        var values: [Date: (Double?, Double?)] = [:]
        let exact = !(history ?? []).isEmpty
        if exact {
            for d in history! { if let date = TokenText.day(d.date, calendar) { values[date] = (d.total, d.cost) } }
        } else {
            for (key, v) in TokenRangeSummary.daily(from: yearGrid, calendar: calendar) where v > 0 {
                if let date = TokenText.day(key, calendar) { values[date] = (v, nil) }
            }
        }
        guard let first = values.filter({ ($0.value.0 ?? 0) > 0 }).keys.min(), first <= today else { return nil }
        var days: [Day] = [], day = first
        while day <= today {
            let v = values[day]
            days.append(Day(date: day, total: v?.0.map { $0 / 1_000_000 }, cost: v?.1))
            day = calendar.date(byAdding: .day, value: 1, to: day)!
        }
        var out = TokenHistory(days: days, exact: exact)
        if !exact { out.rangeCost = yearGrid?.cost }
        return out
    }

    init(days: [Day], exact: Bool) {
        self.days = days
        self.exact = exact
    }
}

public enum TokenFormat {
    /// `v` in millions of tokens.
    public static func short(_ v: Double) -> String {
        if v >= 1000 { return String(format: "%.2fB", v / 1000) }
        if v >= 100 { return "\(Int(v.rounded()))M" }
        return String(format: "%.1fM", v)
    }
}

enum TokenText {
    static let weekdays = ["日", "一", "二", "三", "四", "五", "六"]
    static let hourLabels = (0..<24).map { $0 % 3 == 0 ? String(format: "%02d", $0) : "" }

    static func day(_ s: String, _ c: Calendar) -> Date? {
        let p = s.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return nil }
        return c.date(from: DateComponents(year: p[0], month: p[1], day: p[2]))
    }
    static func key(_ d: Date, _ c: Calendar) -> String {
        let p = c.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", p.year!, p.month!, p.day!)
    }
    static func md(_ d: Date, _ c: Calendar) -> String { "\(c.component(.month, from: d))/\(c.component(.day, from: d))" }
    static func ymd(_ d: Date, _ c: Calendar) -> String { "\(c.component(.year, from: d))/\(md(d, c))" }
    static func weekday(_ d: Date, _ c: Calendar) -> String { "周" + weekdays[c.component(.weekday, from: d) - 1] }
    static func longDay(_ d: Date, _ c: Calendar) -> String {
        "\(c.component(.month, from: d)) 月 \(c.component(.day, from: d)) 日 \(weekday(d, c))"
    }
}

/// Park–Miller minimal standard generator, the same sequence the design mockup uses.
struct ParkMiller {
    var state: Int64
    init(seed: Int64) { state = seed }
    mutating func next() -> Double {
        state = (state * 16807) % 2147483647
        return Double(state) / 2147483647
    }
}
