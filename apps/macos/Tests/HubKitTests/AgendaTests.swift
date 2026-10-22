import Foundation
import Testing
@testable import HubKit

private let cal: Calendar = {
    var c = Calendar.hub
    c.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    return c
}()

private func at(_ day: Int, _ hour: Int, _ minute: Int = 0) -> Date {
    cal.date(from: DateComponents(year: 2026, month: 10, day: day, hour: hour, minute: minute))!
}

@Test func sampleMatchesTheDesign() {
    let now = at(20, 17, 58)
    let v = Agenda.build(AgendaSample.store(now: now, calendar: cal), now: now, calendar: cal)
    #expect(v.overdue.map(\.title) == ["提交 Q4 迁移方案"])
    #expect(v.overdue[0].overdueDays == 1)
    #expect(v.today.map(\.title) == ["给妈妈打电话", "续费域名", "整理 brainstorm 文档"])
    #expect(v.upcoming.map(\.title) == ["迁移方案评审纪要", "体检预约", "准备阶段中期回顾"])
    #expect(Agenda.weekdayName(v.upcoming[2].due!, calendar: cal) == "周五")
    #expect(v.completed.map(\.title) == ["整理 brainstorm 文档", "交水电费", "周报 W42", "修复卡片头部"])
    #expect(v.open(in: "work").map(\.title) == ["提交 Q4 迁移方案", "迁移方案评审纪要", "整理 OKR 草稿", "回复安全组邮件"])
    #expect(v.open(in: "project").first?.subtasks.map(\.title) == ["保留未知页面", "写回前校验"])
    let days = v.days(from: now, calendar: cal)
    #expect(days.map { $0.tasks.count } == [4, 1, 1, 1, 1])
    #expect(days[0].tasks.first?.title == "提交 Q4 迁移方案")
    #expect(v.dueCount == 3)
    #expect(v.events.map(\.title) == ["周会", "迁移方案评审", "羽毛球"])
    #expect(v.nextEvent?.title == "羽毛球")
    #expect(Agenda.menuTitle(v, now: now, calendar: cal) == "3 · 羽毛球 1h2m")
    func title(_ t: Date) -> String {
        Agenda.menuTitle(Agenda.build(AgendaSample.store(now: now, calendar: cal), now: t, calendar: cal), now: t, calendar: cal)
    }
    #expect(title(at(20, 18, 30)) == "3 · 羽毛球 30m")
    #expect(title(at(20, 11, 30)) == "3 · 14:00 迁移方案评审")
    #expect(title(at(20, 10, 30)) == "3 · 周会 进行中")
    #expect(title(at(20, 21)) == "3")
}

@Test func subtasksNestUnderParents() {
    var s = AgendaStore()
    s.lists = [TaskListRecord(id: "l", title: "工作")]
    s.tasks = [
        TaskRecord(id: "p", listID: "l", title: "发布", due: "2026-10-20", position: "1"),
        TaskRecord(id: "c2", listID: "l", title: "写说明", parent: "p", position: "2"),
        TaskRecord(id: "c1", listID: "l", title: "打包", parent: "p", position: "1"),
        TaskRecord(id: "orphan", listID: "l", title: "孤儿", parent: "missing", position: "3"),
    ]
    let v = Agenda.build(s, now: at(20, 9), calendar: cal)
    #expect(v.today.count == 1)
    #expect(v.today[0].subtasks.map(\.title) == ["打包", "写说明"])
    #expect(v.undated.map(\.title) == ["孤儿"])
}

@Test func completedTasksLeaveOverdueButStayInToday() {
    var s = AgendaStore()
    s.lists = [TaskListRecord(id: "l", title: "工作")]
    s.tasks = [
        TaskRecord(id: "old", listID: "l", title: "上周的", due: "2026-10-12", completed: true, completedAt: "2026-10-13T01:00:00Z"),
        TaskRecord(id: "late", listID: "l", title: "昨天完成的逾期", due: "2026-10-18", completed: true, completedAt: "2026-10-20T02:00:00Z"),
        TaskRecord(id: "far", listID: "l", title: "下个月", due: "2026-11-20"),
    ]
    let v = Agenda.build(s, now: at(20, 12), calendar: cal)
    #expect(v.overdue.isEmpty)
    #expect(v.today.map(\.id) == ["late"])
    #expect(v.later.map(\.id) == ["far"])
    #expect(v.dueCount == 0)
}

@Test func tasksInUnknownListsAreHidden() {
    var s = AgendaStore()
    s.lists = [TaskListRecord(id: "l", title: "工作")]
    s.tasks = [TaskRecord(id: "x", listID: "gone", title: "旧清单的", due: "2026-10-20")]
    #expect(Agenda.build(s, now: at(20, 12), calendar: cal).allTasks.isEmpty)
}

@Test func searchAcrossLists() {
    var s = AgendaStore()
    s.lists = [TaskListRecord(id: "w", title: "工作"), TaskListRecord(id: "p", title: "Personal")]
    s.tasks = [
        TaskRecord(id: "1", listID: "w", title: "迁移方案评审", notes: "带上 Q4 数据"),
        TaskRecord(id: "2", listID: "p", title: "Renew domain", due: "2026-10-22"),
        TaskRecord(id: "3", listID: "w", title: "旧的方案", completed: true),
        TaskRecord(id: "4", listID: "w", title: "已删除的方案", deleted: true),
    ]
    #expect(Agenda.search(s, query: "方案", calendar: cal).map(\.id) == ["1", "3"])
    #expect(Agenda.search(s, query: "q4", calendar: cal).map(\.id) == ["1"])
    #expect(Agenda.search(s, query: "personal renew", calendar: cal).map(\.id) == ["2"])
    #expect(Agenda.search(s, query: "  ", calendar: cal).isEmpty)
}

@Test func countdownText() {
    let now = at(20, 17, 58)
    #expect(Agenda.countdown(to: at(20, 18, 30), now: now, calendar: cal) == "32 分钟后")
    #expect(Agenda.countdown(to: at(20, 19), now: now, calendar: cal) == "1 小时 2 分钟后")
    #expect(Agenda.countdown(to: at(20, 19, 58), now: now, calendar: cal) == "2 小时后")
    #expect(Agenda.countdown(to: at(21, 9), now: now, calendar: cal) == "明天 09:00")
    #expect(Agenda.relativeDay(at(23, 9), now: now, calendar: cal) == "周五")
    #expect(Agenda.relativeDay(at(19, 9), now: now, calendar: cal) == "昨天")
    #expect(Agenda.relativeDay(at(30, 9), now: now, calendar: cal) == "10/30")
    #expect(Agenda.longDay(at(21, 9), calendar: cal) == "10 月 21 日 周三")
}

@Test func allDayAndMultiDayEvents() {
    var s = AgendaStore()
    s.calendars = [CalendarRecord(id: "c", title: "我")]
    s.events = [
        EventRecord(id: "a", calendarID: "c", title: "妈妈生日", start: at(20, 0), end: at(21, 0), allDay: true),
        EventRecord(id: "b", calendarID: "c", title: "出差", start: at(19, 9), end: at(20, 18)),
        EventRecord(id: "t", calendarID: "c", title: "明天的会", start: at(21, 10), end: at(21, 11)),
    ]
    let v = Agenda.build(s, now: at(20, 12), calendar: cal)
    #expect(v.allDay.map(\.title) == ["妈妈生日"])
    #expect(v.events.map(\.title) == ["出差"])
    #expect(v.currentEvent?.title == "出差")
    #expect(v.nextEvent?.title == "明天的会")
    #expect(Agenda.menuTitle(v, now: at(20, 12), calendar: cal) == "0 · 出差 进行中")
}
