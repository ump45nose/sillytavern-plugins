import Foundation

/// The design mockup's agenda as a cache, placed around `now`, shown until Google is connected.
public enum AgendaSample {
    /// The sample with a long 循环任务 list and a pile of overdue work, so columns have to scroll.
    public static func long(now: Date, calendar: Calendar = .hub) -> AgendaStore {
        var s = store(now: now, calendar: calendar)
        let today = calendar.startOfDay(for: now)
        func day(_ offset: Int) -> String { GoogleDate.dayString(calendar.date(byAdding: .day, value: offset, to: today)!, calendar: calendar) }
        s.lists.insert(TaskListRecord(id: "routine", title: "循环任务"), at: 1)
        let routine = ["晨跑", "背单词", "记账", "整理收件箱", "喝水 8 杯", "读书 30 分钟", "冥想", "拉伸", "写日报", "复盘今天", "备好明天的衣服",
                       "倒垃圾", "给植物浇水", "洗漱睡觉", "周报", "清理桌面", "练字", "散步", "收衣服", "整理照片", "回消息", "洗漱睡觉 2"]
        s.tasks += routine.enumerated().map { i, t in
            TaskRecord(id: "r\(i)", listID: "routine", title: t, notes: i % 3 == 0 ? "一三五七" : nil, due: i % 4 == 0 ? day(-(i % 5) - 1) : nil,
                       position: String(format: "%02d", i))
        }
        s.tasks += (0..<16).map { i in TaskRecord(id: "o\(i)", listID: "work", title: "逾期事项 \(i + 1)", due: day(-2 - i), position: "9\(i)") }
        return s
    }

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
            TaskRecord(id: "s2", listID: "personal", title: "给妈妈打电话", notes: "时间 18:30", due: day(0), position: "1"),
            TaskRecord(id: "s3", listID: "personal", title: "续费域名", due: day(0), position: "2"),
            TaskRecord(id: "s4", listID: "project", title: "整理 brainstorm 文档", due: day(0), completed: true,
                       completedAt: GoogleDate.string(at(11)), position: "1"),
            TaskRecord(id: "s5", listID: "review", title: "准备阶段中期回顾", due: day(friday == 0 ? 7 : friday), position: "1"),
            TaskRecord(id: "s6", listID: "work", title: "迁移方案评审纪要", due: day(1), position: "2"),
            TaskRecord(id: "s7", listID: "work", title: "整理 OKR 草稿", notes: "对齐 Q4 主线", position: "3"),
            TaskRecord(id: "s8", listID: "work", title: "回复安全组邮件", position: "4"),
            TaskRecord(id: "s9", listID: "personal", title: "体检预约", due: day(2), position: "3"),
            TaskRecord(id: "s10", listID: "project", title: "安卓布局兼容", position: "2"),
            TaskRecord(id: "s11", listID: "project", title: "保留未知页面", parent: "s10", position: "1"),
            TaskRecord(id: "s12", listID: "project", title: "写回前校验", parent: "s10", position: "2"),
            TaskRecord(id: "s13", listID: "personal", title: "买羽毛球", due: day(12), position: "4"),
            TaskRecord(id: "d1", listID: "work", title: "周报 W42", due: day(-2), completed: true,
                       completedAt: GoogleDate.string(at(-24 * 2 + 21)), position: "5"),
            TaskRecord(id: "d2", listID: "personal", title: "交水电费", completed: true,
                       completedAt: GoogleDate.string(at(-24 + 9.5)), position: "5"),
            TaskRecord(id: "d3", listID: "project", title: "修复卡片头部", due: day(-3), completed: true,
                       completedAt: GoogleDate.string(at(-24 * 3 + 16)), position: "3"),
        ]
        s.calendars = [CalendarRecord(id: "sample", title: "日历", primary: true)]
        s.events = [
            EventRecord(id: "e1", calendarID: "sample", title: "周会", location: "腾讯会议", start: at(10), end: at(11), colorID: "7"),
            EventRecord(id: "e2", calendarID: "sample", title: "迁移方案评审", location: "3F 会议室", start: at(14), end: at(15.5), colorID: "9"),
            EventRecord(id: "e3", calendarID: "sample", title: "羽毛球", location: "体育馆 3 号场", start: at(19), end: at(20.5), colorID: "10"),
            EventRecord(id: "e4", calendarID: "sample", title: "牙医复诊", location: "口腔医院", start: at(24 * 2 + 15), end: at(24 * 2 + 16), colorID: "4"),
        ]
        return s
    }
}
