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
        tools = d.tools?.map { Part(id: $0.id, name: $0.name, total: m($0.total)) }
        devices = d.devices?.map { Part(id: $0.id, name: $0.name, total: m($0.total)) }
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
