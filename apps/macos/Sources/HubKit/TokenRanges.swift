import Foundation

public enum TokenRange: String, CaseIterable, Sendable, Codable {
    case day, week, month, year

    public var label: String {
        switch self { case .day: "日"; case .week: "周"; case .month: "月"; case .year: "年" }
    }
}

public struct TokenHeatmap: Sendable {
    public var title: String
    public var rowLabels: [String]
    public var columnLabels: [String]
    /// Row-major values in millions of tokens; nil marks a slot that has not happened yet.
    public var values: [[Double?]]
    public var tips: [[String]]
    public var dense: Bool

    public var columns: Int { columnLabels.count }
    public var maxValue: Double { values.flatMap { $0.compactMap { $0 } }.max() ?? 1 }

    /// Six intensity levels; -1 means a future slot.
    public func level(_ v: Double?) -> Int {
        guard let v else { return -1 }
        let r = v / maxValue
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

public struct TokenRangeSummary: Sendable {
    public var range: TokenRange
    public var periodLabel: String
    public var total: Double
    public var previous: Double
    public var comparisonLabel: String
    public var peakLabel: String
    public var peakValue: Double
    public var averageLabel: String
    public var average: Double
    public var toolTotals: [Double]
    public var heatmap: TokenHeatmap

    public static let costPerMillion = 2.267

    public var cost: Double { total * Self.costPerMillion }
    public var deltaPercent: Int { Int(((total / previous) - 1) * 100) }
}

public enum TokenFormat {
    public static func short(_ v: Double) -> String {
        if v >= 1000 { return String(format: "%.2fB", v / 1000) }
        if v >= 100 { return "\(Int(v.rounded()))M" }
        return String(format: "%.1fM", v)
    }
}

/// Deterministic sample generator so the heatmaps look plausible and stable between launches.
public enum TokenSample {
    static let toolWeights = [0.44, 0.27, 0.19, 0.10]
    static let hourWeights: [Double] = [0.06, 0.03, 0.01, 0.01, 0.01, 0.02, 0.05, 0.2, 0.55, 0.85, 1, 0.9, 0.55, 0.7, 1, 1, 0.9, 0.8, 0.45, 0.4, 0.65, 0.75, 0.5, 0.2]
    static let weekdays = ["一", "二", "三", "四", "五", "六", "日"]

    public static func summaries(usage: TokenUsage, today: Date = sampleToday, nowHour: Int = 17) -> [TokenRange: TokenRangeSummary] {
        var rng = ParkMiller(seed: 29)
        let cal = Calendar(identifier: .gregorian)
        func day(_ n: Int) -> Date { cal.date(byAdding: .day, value: n, to: today)! }
        func md(_ d: Date) -> String { "\(cal.component(.month, from: d))/\(cal.component(.day, from: d))" }
        func wd(_ d: Date) -> String { weekdays[(cal.component(.weekday, from: d) + 5) % 7] }
        func hh(_ h: Int) -> String { String(format: "%02d", h) }
        let hourSum = hourWeights.reduce(0, +)

        var daily: [Int: Double] = [:]
        for n in -400...0 {
            if n > -14 {
                daily[n] = usage.d14[13 + n]
            } else {
                let weekday = cal.component(.weekday, from: day(n))
                let weekend = weekday == 1 || weekday == 7
                daily[n] = ((weekend ? 0.45 : 1) * (9 + rng.next() * 18) * 10).rounded() / 10
            }
        }
        func sum(_ a: Int, _ b: Int) -> Double { (a...b).reduce(0) { $0 + daily[$1]! } }
        func hourly(_ total: Double, upTo: Int = 23) -> [Double?] {
            hourWeights.enumerated().map { h, w in h > upTo ? nil : total * w / hourSum * (0.6 + rng.next() * 0.8) }
        }
        let tools = usage.tools.map(\.name)
        let hourLabels = (0..<24).map { $0 % 3 == 0 ? hh($0) : "" }
        var out: [TokenRange: TokenRangeSummary] = [:]

        // Day: tools × hours.
        do {
            let values = tools.indices.map { hourly(daily[0]! * toolWeights[$0], upTo: nowHour) }
            let tips = tools.map { t in (0..<24).map { "\(t) · \(hh($0)):00" } }
            let byHour = (0..<24).map { h in values.reduce(0) { $0 + ($1[h] ?? 0) } }
            let peakHour = byHour.indices.max { byHour[$0] < byHour[$1] }!
            out[.day] = TokenRangeSummary(
                range: .day, periodLabel: "今天 · 10 月 20 日 周二", total: daily[0]!, previous: daily[-1]!, comparisonLabel: "较昨天",
                peakLabel: "\(hh(peakHour)):00", peakValue: byHour[peakHour], averageLabel: "本小时", average: byHour[nowHour],
                toolTotals: values.map { $0.reduce(0) { $0 + ($1 ?? 0) } },
                heatmap: TokenHeatmap(title: "按小时 × 工具", rowLabels: tools, columnLabels: hourLabels, values: values, tips: tips, dense: false))
        }

        // Week: last 7 days × hours.
        do {
            var values: [[Double?]] = [], tips: [[String]] = [], rows: [String] = []
            for k in 0..<7 {
                let n = k - 6, d = day(n)
                rows.append(n == 0 ? "今天" : "周\(wd(d))")
                values.append(hourly(daily[n]!, upTo: n == 0 ? nowHour : 23))
                tips.append((0..<24).map { "\(md(d)) 周\(wd(d)) · \(hh($0)):00" })
            }
            let best = (-6...0).max { daily[$0]! < daily[$1]! }!
            let total = sum(-6, 0)
            out[.week] = TokenRangeSummary(
                range: .week, periodLabel: "近 7 天 · \(md(day(-6))) – \(md(today))", total: total, previous: sum(-13, -7), comparisonLabel: "较前 7 天",
                peakLabel: "周\(wd(day(best))) \(md(day(best)))", peakValue: daily[best]!, averageLabel: "日均", average: total / 7,
                toolTotals: toolWeights.map { $0 * total },
                heatmap: TokenHeatmap(title: "按小时 × 日期", rowLabels: rows, columnLabels: hourLabels, values: values, tips: tips, dense: false))
        }

        // Month: tools × last 30 days.
        do {
            let values: [[Double?]] = tools.indices.map { ri in (0..<30).map { k in daily[k - 29]! * toolWeights[ri] * (0.7 + rng.next() * 0.6) } }
            let tips = tools.map { t in (0..<30).map { "\(t) · \(md(day($0 - 29)))" } }
            let labels = (0..<30).map { k in (29 - k) % 7 != 0 ? "" : k == 29 ? "今天" : md(day(k - 29)) }
            let best = (-29...0).max { daily[$0]! < daily[$1]! }!
            let total = sum(-29, 0)
            out[.month] = TokenRangeSummary(
                range: .month, periodLabel: "近 30 天 · \(md(day(-29))) – \(md(today))", total: total, previous: sum(-59, -30) * 0.92, comparisonLabel: "较前 30 天",
                peakLabel: md(day(best)), peakValue: daily[best]!, averageLabel: "日均", average: total / 30,
                toolTotals: values.map { $0.reduce(0) { $0 + ($1 ?? 0) } },
                heatmap: TokenHeatmap(title: "按日期 × 工具", rowLabels: tools, columnLabels: labels, values: values, tips: tips, dense: false))
        }

        // Year: weekdays × 53 weeks, GitHub style.
        do {
            let todayRow = (cal.component(.weekday, from: today) + 5) % 7
            let start = -(52 * 7 + todayRow)
            var values = Array(repeating: [Double?](repeating: nil, count: 53), count: 7)
            var tips = Array(repeating: [String](repeating: "", count: 53), count: 7)
            var labels = [String](repeating: "", count: 53)
            var lastMonth = -1
            var peak: (Double, String) = (-1, "")
            var total = 0.0, count = 0
            for c in 0..<53 {
                for r in 0..<7 {
                    let n = start + c * 7 + r, d = day(n)
                    let month = cal.component(.month, from: d)
                    if r == 0, month != lastMonth { lastMonth = month; if c < 51 { labels[c] = "\(month)月" } }
                    tips[r][c] = "\(cal.component(.year, from: d))/\(md(d)) 周\(wd(d))"
                    guard n <= 0 else { continue }
                    let v = daily[n]! * (n < -200 ? 0.35 : 1)
                    values[r][c] = v
                    total += v; count += 1
                    if v > peak.0 { peak = (v, md(d)) }
                }
            }
            out[.year] = TokenRangeSummary(
                range: .year, periodLabel: "近一年 · 2025/10/20 – 2026/10/20", total: total, previous: total * 0.38, comparisonLabel: "较前一年",
                peakLabel: peak.1, peakValue: peak.0, averageLabel: "日均", average: total / Double(count),
                toolTotals: toolWeights.map { $0 * total },
                heatmap: TokenHeatmap(title: "按周 × 星期", rowLabels: ["一", "", "三", "", "五", "", "日"], columnLabels: labels, values: values, tips: tips, dense: true))
        }
        return out
    }

    public static let sampleToday: Date = {
        var c = DateComponents(); c.year = 2026; c.month = 10; c.day = 20; c.hour = 12
        return Calendar(identifier: .gregorian).date(from: c)!
    }()
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
