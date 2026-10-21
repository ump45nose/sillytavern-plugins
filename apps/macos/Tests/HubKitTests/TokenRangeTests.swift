import Foundation
import Testing
@testable import HubKit

private let now = HubJSON.parseDate("2026-10-20T17:58:00+08:00")!
private let cal: Calendar = {
    var c = Calendar.hub
    c.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    return c
}()

private func sample(_ r: TokenRange) -> TokenRangeSummary {
    let data = HubSample.data(now: now, calendar: cal)
    return TokenRangeSummary(data.token[r]!.data!, now: now, daily: TokenRangeSummary.daily(from: data.token[.year]?.data, calendar: cal), calendar: cal)
}

@Test func sampleRangesHaveConsistentHeatmapShapes() {
    for r in TokenRange.allCases {
        let h = sample(r).heatmap!
        #expect(h.values.count == h.rowLabels.count)
        #expect(h.tips.count == h.rowLabels.count)
        for row in h.values { #expect(row.count == h.columns) }
    }
    #expect(sample(.day).heatmap!.columns == 24)
    #expect(sample(.week).heatmap!.rowLabels.count == 7)
    #expect(sample(.month).heatmap!.columns == 30)
    #expect(sample(.year).heatmap!.columns == 53)
    #expect(sample(.week).periodLabel == "近 7 天 · 10/14 – 10/20")
    #expect(sample(.day).periodLabel == "今天 · 10 月 20 日 周二")
}

@Test func futureHoursAreEmpty() {
    for row in sample(.day).heatmap!.values {
        #expect(row[17] != nil)
        #expect(row[18...].allSatisfy { $0 == nil })
    }
    #expect(sample(.day).heatmap!.level(nil) == -1)
}

/// hub-api today: no hourly tokens, no per-tool history, year total unknown.
@Test func sourceGapsStayUnknownInsteadOfZero() throws {
    let hours = [Double?](repeating: nil, count: 24)
    let day = TokenData(range: .day, period: .init(start: "2026-10-20", end: "2026-10-20"), total: 25_000_000, previous: 0, cost: 56.7,
                        tools: [.init(id: "codex", name: "Codex", total: 20_000_000)],
                        buckets: .init(unit: "hour", rows: "tool", series: [.init(key: "codex", values: hours)]))
    let d = TokenRangeSummary(day, now: now, calendar: cal)
    #expect(d.heatmap == nil)
    #expect(d.peakLabel == nil && d.average == nil)
    #expect(d.deltaPercent == nil)
    #expect(d.tools?.first?.total == 20)

    var cells = [Double?](repeating: nil, count: 371)
    cells[364] = 4_000_000; cells[365] = 9_000_000
    let year = TokenData(range: .year, period: .init(start: "2025-10-20", end: "2026-10-20"),
                         buckets: .init(unit: "day", rows: "year", series: [.init(key: "year", values: cells)]))
    let y = TokenRangeSummary(year, now: now, calendar: cal)
    #expect(y.total == nil)
    #expect(y.peakValue == 9)
    #expect(y.heatmap?.values.flatMap { $0 }.compactMap { $0 }.count == 2)

    let week = TokenData(range: .week, period: .init(start: "2026-10-14", end: "2026-10-20"), total: 70_000_000, previous: 35_000_000,
                         buckets: .init(unit: "hour", rows: "date", series: (14...20).map { .init(key: "2026-10-\($0)", values: hours) }))
    let w = TokenRangeSummary(week, now: now, daily: TokenRangeSummary.daily(from: year, calendar: cal), calendar: cal)
    #expect(w.deltaPercent == 100)
    #expect(w.average == 10)
    // Hourly cells are unknown, so the week falls back to the daily totals from the year grid.
    #expect(w.heatmap?.rowLabels == ["合计"])
    #expect(w.heatmap?.values[0].compactMap { $0 } == [4, 9])
    #expect(w.peakLabel == "周二 10/20" && w.peakValue == 9)
}

@Test func tokenFormatting() {
    #expect(TokenFormat.short(3830) == "3.83B")
    #expect(TokenFormat.short(122.6) == "123M")
    #expect(TokenFormat.short(18.6) == "18.6M")
}

@Test func historyPrefersHubAndFallsBackToTheYearGrid() throws {
    let days: [TokenData.Day] = [
        .init(date: "2026-10-16", total: 2_000_000, cost: 1.5),
        .init(date: "2026-10-18", total: 6_000_000, cost: 4),
        .init(date: "2026-10-20", total: 4_000_000, cost: nil),
    ]
    let h = try #require(TokenHistory.make(history: days, yearGrid: nil, now: now, calendar: cal))
    #expect(h.exact && h.days.count == 5, "contiguous from the first record to today")
    #expect(h.days[1].total == nil)
    #expect(h.total == 12 && h.cost == 5.5)
    #expect(h.best?.total == 6)
    #expect(h.movingAverage(2) == [2, 1, 3, 3, 2])

    var cells = [Double?](repeating: 0, count: 371)
    cells[364] = 4_000_000; cells[365] = 9_000_000
    let year = TokenData(range: .year, period: .init(start: "2025-10-20", end: "2026-10-20"), cost: 30,
                         buckets: .init(unit: "day", rows: "year", series: [.init(key: "year", values: cells)]))
    let f = try #require(TokenHistory.make(history: [], yearGrid: year, now: now, calendar: cal))
    #expect(!f.exact && f.cost == 30, "no daily cost in the grid, so the range's own cost")
    #expect(f.days.count == 2 && f.total == 13)
    #expect(TokenHistory.make(history: nil, yearGrid: nil, now: now, calendar: cal) == nil)
}

@Test func historyYearsAreMondayFirstWeeks() throws {
    let days = (1...20).map { TokenData.Day(date: String(format: "2026-10-%02d", $0), total: 1_000_000, cost: nil) }
    let h = try #require(TokenHistory.make(history: days, yearGrid: nil, now: now, calendar: cal))
    let y = h.year(2026, calendar: cal)
    #expect(y.weeks.allSatisfy { $0.count == 7 })
    #expect(cal.component(.weekday, from: y.weeks[0][0].date) == 2)
    #expect(y.months.count == 12 && y.months[0].week == 0)
    let filled = y.weeks.flatMap { $0 }.filter { $0.day != nil }
    #expect(filled.count == 20)
}
