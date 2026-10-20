import Foundation
import Testing
@testable import HubKit

private let cal: Calendar = {
    var c = Calendar.hub
    c.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    return c
}()

/// Tuesday 2026-10-20 17:58.
private let now = cal.date(from: DateComponents(year: 2026, month: 10, day: 20, hour: 17, minute: 58))!

private func parse(_ s: String, at date: Date = now) -> QuickEntry { QuickEntryParser.parse(s, now: date, calendar: cal) }

private func stamp(_ e: QuickEntry) -> String? {
    guard let due = e.due else { return nil }
    let c = cal.dateComponents([.month, .day, .hour, .minute], from: due)
    let day = String(format: "%02d-%02d", c.month!, c.day!)
    return e.hasTime ? day + String(format: " %02d:%02d", c.hour!, c.minute!) : day
}

@Test(arguments: [
    ("今天 交周报", "10-20"),
    ("明天 交周报", "10-21"),
    ("后天交周报", "10-22"),
    ("大后天交周报", "10-23"),
    ("3天后 交周报", "10-23"),
    ("三天后交周报", "10-23"),
    ("周五交周报", "10-23"),
    ("周二交周报", "10-20"),
    ("周一交周报", "10-26"),
    ("这周一交周报", "10-19"),
    ("下周五交周报", "10-30"),
    ("下个星期三交周报", "10-28"),
    ("下下周一交周报", "11-02"),
    ("周日交周报", "10-25"),
    ("礼拜天交周报", "10-25"),
    ("下周交周报", "10-26"),
    ("周末交周报", "10-24"),
    ("下周末交周报", "10-31"),
    ("月底交周报", "10-31"),
    ("下个月底交周报", "11-30"),
    ("月初交周报", "11-01"),
    ("25号交周报", "10-25"),
    ("二十五号交周报", "10-25"),
    ("5号交周报", "11-05"),
    ("下个月3号交周报", "11-03"),
    ("11月2日交周报", "11-02"),
    ("十一月二日交周报", "11-02"),
    ("1月5号交周报", "01-05"),
    ("10/25 交周报", "10-25"),
    ("2026-12-01 交周报", "12-01"),
])
func dates(_ input: String, _ expected: String) {
    let e = parse(input)
    #expect(stamp(e) == expected, "\(input)")
    #expect(e.title == "交周报", "\(input) → \(e.title)")
}

@Test(arguments: [
    ("明天下午3点 开会", "10-21 15:00"),
    ("明天下午三点半开会", "10-21 15:30"),
    ("明天上午10点开会", "10-21 10:00"),
    ("明天上午十点一刻开会", "10-21 10:15"),
    ("明天9点20分开会", "10-21 09:20"),
    ("明天3点开会", "10-21 15:00"),
    ("明天中午1点开会", "10-21 13:00"),
    ("明天晚上8点开会", "10-21 20:00"),
    ("今晚8点开会", "10-20 20:00"),
    ("今晚开会", "10-20 20:00"),
    ("明早开会", "10-21 08:00"),
    ("明天下午开会", "10-21 15:00"),
    ("下周五 14:30 开会", "10-30 14:30"),
    ("周三19：00开会", "10-21 19:00"),
    ("19:00开会", "10-20 19:00"),
    ("下午3点开会", "10-21 15:00"),
    ("8点开会", "10-21 08:00"),
    ("凌晨2点开会", "10-21 02:00"),
])
func times(_ input: String, _ expected: String) {
    let e = parse(input)
    #expect(stamp(e) == expected, "\(input)")
    #expect(e.title == "开会", "\(input) → \(e.title)")
}

@Test func titleAndListTag() {
    let e = parse("明天下午3点 和李雷对齐迁移方案 #工作")
    #expect(e.title == "和李雷对齐迁移方案")
    #expect(e.listTag == "工作")
    #expect(stamp(e) == "10-21 15:00")
    #expect(e.datePhrases == ["明天", "下午3点"])
}

@Test func phraseInsideSentenceClosesUp() {
    #expect(parse("提醒我明天交报告").title == "提醒我交报告")
    #expect(parse("Review PR 明天 before standup").title == "Review PR before standup")
}

@Test func noDate() {
    let e = parse("买牛奶 #生活")
    #expect(e.due == nil)
    #expect(!e.hasTime)
    #expect(e.title == "买牛奶")
    #expect(e.listTag == "生活")
}

@Test func wordsThatLookLikeNumbersStayInTitle() {
    #expect(parse("一起吃饭").due == nil)
    #expect(parse("一起吃饭").title == "一起吃饭")
    #expect(parse("写周报").due == nil)
    #expect(parse("读第一章").due == nil)
}

@Test func invalidDatesAreIgnored() {
    #expect(parse("2月30日 交周报").due == nil)
    #expect(parse("32号 交周报").due == nil)
}

@Test func monthEndOnLastDayIsToday() {
    let last = cal.date(from: DateComponents(year: 2026, month: 10, day: 31, hour: 9))!
    #expect(stamp(parse("月底交", at: last)) == "10-31")
}

@Test func chineseNumbers() {
    #expect(QuickEntryParser.number("十") == 10)
    #expect(QuickEntryParser.number("十五") == 15)
    #expect(QuickEntryParser.number("二十") == 20)
    #expect(QuickEntryParser.number("三十一") == 31)
    #expect(QuickEntryParser.number("两") == 2)
    #expect(QuickEntryParser.number("一二三") == nil)
}
