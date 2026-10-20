import Foundation

/// The design mockup's agenda as a cache, placed around `now`, shown until Google is connected.
public enum AgendaSample {
    public static func store(now: Date, calendar: Calendar = .hub) -> AgendaStore {
        let today = calendar.startOfDay(for: now)
        func day(_ offset: Int) -> String { GoogleDate.dayString(calendar.date(byAdding: .day, value: offset, to: today)!, calendar: calendar) }
        func at(_ hour: Double) -> Date { today.addingTimeInterval(hour * 3600) }
        let friday = (13 - calendar.component(.weekday, from: today)) % 7

        var s = AgendaStore(account: nil)
        s.lists = [TaskListRecord(id: "work", title: "工作"), TaskListRecord(id: "personal", title: "个人"),
                   TaskListRecord(id: "project", title: "个人项目"), TaskListRecord(id: "review", title: "复盘")]
        s.tasks = [
            TaskRecord(id: "s1", listID: "work", title: "提交 Q4 迁移方案", due: day(-1), position: "1"),
            TaskRecord(id: "s2", listID: "personal", title: "给妈妈打电话", due: day(0), position: "1"),
            TaskRecord(id: "s3", listID: "personal", title: "续费域名", due: day(0), position: "2"),
            TaskRecord(id: "s4", listID: "project", title: "整理 brainstorm 文档", due: day(0), completed: true,
                       completedAt: GoogleDate.string(at(11)), position: "1"),
            TaskRecord(id: "s5", listID: "review", title: "准备阶段中期回顾", due: day(friday == 0 ? 7 : friday), position: "1"),
        ]
        s.calendars = [CalendarRecord(id: "sample", title: "日历", primary: true)]
        s.events = [
            EventRecord(id: "e1", calendarID: "sample", title: "周会", location: "腾讯会议", start: at(10), end: at(11), colorID: "7"),
            EventRecord(id: "e2", calendarID: "sample", title: "迁移方案评审", location: "3F 会议室", start: at(14), end: at(15.5), colorID: "9"),
            EventRecord(id: "e3", calendarID: "sample", title: "羽毛球", location: "体育馆 3 号场", start: at(19), end: at(20.5), colorID: "10"),
        ]
        return s
    }
}
