import Testing
@testable import HubKit

@Test func everyRangeHasConsistentHeatmapShape() {
    let all = TokenSample.summaries(usage: Sample.snapshot.token)
    #expect(Set(all.keys) == Set(TokenRange.allCases))
    for s in all.values {
        let h = s.heatmap
        #expect(h.values.count == h.rowLabels.count)
        #expect(h.tips.count == h.rowLabels.count)
        for row in h.values { #expect(row.count == h.columns) }
        #expect(s.toolTotals.count == Sample.snapshot.token.tools.count)
    }
    #expect(all[.day]!.heatmap.columns == 24)
    #expect(all[.week]!.heatmap.rowLabels.count == 7)
    #expect(all[.month]!.heatmap.columns == 30)
    #expect(all[.year]!.heatmap.columns == 53)
}

@Test func futureHoursAreEmpty() {
    let day = TokenSample.summaries(usage: Sample.snapshot.token, nowHour: 17)[.day]!
    for row in day.heatmap.values {
        #expect(row[17] != nil)
        #expect(row[18...].allSatisfy { $0 == nil })
    }
    #expect(day.heatmap.level(nil) == -1)
}

@Test func weekTotalUsesTheLastSevenDays() {
    let usage = Sample.snapshot.token
    let week = TokenSample.summaries(usage: usage)[.week]!
    let expected = usage.d14.suffix(7).reduce(0, +)
    #expect(abs(week.total - expected) < 0.001)
    #expect(week.periodLabel == "近 7 天 · 10/14 – 10/20")
}

@Test func generationIsDeterministic() {
    let a = TokenSample.summaries(usage: Sample.snapshot.token)[.year]!
    let b = TokenSample.summaries(usage: Sample.snapshot.token)[.year]!
    #expect(a.total == b.total)
    #expect(TokenFormat.short(3830) == "3.83B")
    #expect(TokenFormat.short(122.6) == "123M")
    #expect(TokenFormat.short(18.6) == "18.6M")
}
