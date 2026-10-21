import Foundation

/// Demo goals and review sessions in hub-api's shape, placed relative to `now`.
public enum ReviewSample {
    public static let rules = ReviewSession.Rules(
        fields: ["情绪", "健康", "财务", "留痕", "未解", "明天唯一重点", "瞬间"], autoFields: ["健康", "财务"],
        summaryMaxChars: 45, summaryMaxListSeparators: 1, maxUnresolved: 2, momentMinChars: 6,
        emotionWords: ["愉快", "满足", "期待", "平静", "疲惫", "焦虑", "烦躁", "低落", "愤怒", "委屈", "孤独", "麻木"])

    public static func dailyTemplate(_ day: String) -> String {
        ["#日报 \(day)", "一句话总结今天：", "", "情绪：", "健康：", "财务：", "留痕：", "未解：", "明天唯一重点：", "瞬间："].joined(separator: "\n")
    }

    public static func weeklyTemplate(_ label: String) -> String {
        ["#周报 \(label)", "", "可验证变化：", "重复模式：", "沉淀：", "",
         "状态：", "- 关系：", "- 事业 / 时间 / 钱：", "- 身体：（设备数据自动补充）", "",
         "阶段性目标：", "- 当前交付｜主要阻碍｜下周投入｜状态", "",
         "阶段进度：[目标ID] 当前交付｜主要阻碍｜下周投入｜状态",
         "下周行动：[目标ID] 用户明确选择的行动", "",
         "下周资源分配：", "- 继续 / 降级 / 停止", "",
         "决定日志：", "- 判断｜理由｜预期｜复盘时间"].joined(separator: "\n")
    }

    public static func closeTemplate(_ cycle: String) -> String {
        "#阶段总结 \(cycle)\n\n这个 loop 成了没成（成功 / 失败 / 停止）：\n下个 loop 与判定标准、截止日期、中止信号：\n这套模板哪个字段我在敷衍，删掉：\n主线的可观察指标动了吗："
    }

    struct Clock {
        let now: Date, calendar: Calendar
        var today: Date { calendar.startOfDay(for: now) }
        func day(_ n: Int) -> Date { calendar.date(byAdding: .day, value: n, to: today)! }
        func at(_ n: Int, _ h: Int, _ m: Int) -> Date { calendar.date(byAdding: .minute, value: h * 60 + m, to: day(n))! }
        func key(_ n: Int) -> String { TokenText.key(day(n), calendar) }
        var week: String {
            let c = calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: calendar.date(byAdding: .day, value: -7, to: now)!)
            return String(format: "%04d-W%02d", c.yearForWeekOfYear ?? 0, c.weekOfYear ?? 0)
        }
    }

    public static func goals(now: Date, calendar: Calendar = .hub) -> GoalsData {
        let c = Clock(now: now, calendar: calendar)
        let cycleID = "2026-S3"
        func goal(_ n: Int, _ domain: String, _ title: String, _ progress: String, comment: String? = nil) -> GoalsData.Goal {
            .init(id: "\(cycleID)-g\(n)", domain: domain, status: "active", goal: title, progress: progress, deadline: c.key(19),
                  successCriteria: "到期前可以被别人验证", stopSignal: "连续两周没有推进", memoName: "memos/g\(n)",
                  latestComment: comment.map { .init(text: $0, createdAt: c.at(-2, 22, 10)) })
        }
        return GoalsData(
            mainline: .init(domain: "总主线", direction: "构建可持续的个人系统", purpose: "让每天的注意力花在真正重要的事上",
                            meaning: "少一些被动反应", status: "推进中", recentChange: "从工具堆叠转向一个自己天天用的入口",
                            memoName: "memos/mainline", updatedAt: c.at(-22, 21, 0)),
            cycle: .init(id: cycleID, index: 3, status: "active", startsAt: c.at(-22, 9, 0), endsAt: c.at(20, 9, 0), day: 23, total: 42,
                         precloseAt: c.at(19, 9, 0)),
            goals: [
                goal(1, "事业", "上线个人信息中心 v1", "Mac 端模块接入真实数据", comment: "复盘入口进 App，Telegram 只做提醒"),
                goal(2, "身体", "每周 3 次力量训练", "本周 2 / 3"),
                goal(3, "关系", "每周联系 2 位老朋友", "本周 1 / 2"),
                goal(4, "财务", "月支出低于 ¥5,000", "本月 ¥4,312"),
            ],
            reviews: .init(
                daily: .init(id: "daily:\(c.key(-1))", kind: .daily, label: c.key(-1), status: .open,
                             preparedAt: c.at(-1, 21, 20), expiresAt: c.at(1, 0, 30)),
                weekly: .init(id: "weekly:\(c.week)", kind: .weekly, label: c.week, status: .finalized,
                              preparedAt: c.at(-3, 21, 50), expiresAt: c.at(4, 21, 50), memoName: "memos/weekly"),
                nextDailyAt: c.at(0, 21, 30), nextWeeklyAt: c.at(4, 21, 50)),
            close: .init(status: .none, cycleId: cycleID, template: nil))
    }

    public static func sessions(_ kind: ReviewKind, now: Date, calendar: Calendar = .hub) -> [ReviewSummary] {
        let c = Clock(now: now, calendar: calendar)
        switch kind {
        case .daily:
            return (1...6).map { n in
                let status: ReviewSummary.State = n == 1 ? .open : n == 4 ? .expired : .finalized
                return ReviewSummary(id: "daily:\(c.key(-n))", kind: .daily, label: c.key(-n), status: status,
                                     preparedAt: c.at(-n, 21, 20), expiresAt: c.at(-n + 2, 0, 30),
                                     memoName: status == .finalized ? "memos/d\(n)" : nil)
            }
        case .weekly:
            return [ReviewSummary(id: "weekly:\(c.week)", kind: .weekly, label: c.week, status: .finalized,
                                  preparedAt: c.at(-3, 21, 50), expiresAt: c.at(4, 21, 50), memoName: "memos/weekly")]
        }
    }

    public static func session(id: String, now: Date, calendar: Calendar = .hub) -> ReviewSession {
        let summary = (sessions(.daily, now: now, calendar: calendar) + sessions(.weekly, now: now, calendar: calendar)).first { $0.id == id }
            ?? ReviewSummary(id: id, kind: .daily, label: String(id.split(separator: ":").last ?? ""), status: .open)
        let kind = summary.resolvedKind
        let template = kind == .daily ? dailyTemplate(summary.label) : weeklyTemplate(summary.label)
        let sections: [ReviewSession.Section] = [
            .init(title: "Skysight", blocks: ["- **09:00–12:00** 在 Personal Hub 里把模块接到 hub-api，排查 NPM 403。", "- **14:00–17:30** 写复盘入口的方案，和 NAS 侧对齐接口。"]),
            .init(title: "健康", blocks: ["- 步数 6842，睡眠 7 小时 12 分"]),
            .init(title: "财务", blocks: ["- 今日支出 ¥128.50（餐饮 ¥64）"]),
            .init(title: "CRM", blocks: ["- 陈老师：聊到下一阶段要不要转向产品方向"]),
            .init(title: "当前主线与阶段目标", blocks: ["- 事业：上线个人信息中心 v1；Mac 端模块接入真实数据"]),
        ]
        let delivered = """
        **今天的材料**

        上午在 Personal Hub 里把模块接上了 hub-api，下午写了复盘入口的方案。和陈老师聊到下一阶段的方向。

        **灵珺的话**
        方案里「先确认者生效」这一条很关键，它让两个入口不会互相打架。

        **想问你的**
        如果 App 里确认变成习惯，Telegram 还需要保留到什么程度？
        """
        let finalized = summary.status == .finalized
        return ReviewSession(
            id: summary.id, kind: kind, label: summary.label, status: summary.status, preparedAt: summary.preparedAt,
            expiresAt: summary.expiresAt, memoName: summary.memoName,
            material: .init(sections: sections, template: template),
            delivered: .init(text: delivered, deliveredAt: summary.preparedAt?.addingTimeInterval(120)),
            finalContent: finalized && kind == .daily
                ? "#日报 \(summary.label)\n一句话总结今天：把复盘入口的方案定下来了\n\n情绪：平静\n健康：步数 6842，睡眠 7 小时 12 分\n财务：今日支出 ¥128.50"
                : finalized ? "#周报 \(summary.label)\n\n可验证变化：Mac 端接入了真实数据" : nil,
            rules: kind == .daily ? rules : .init(fields: ["可验证变化", "重复模式", "沉淀", "状态", "阶段性目标", "下周资源分配", "决定日志"], autoFields: ["身体"]))
    }

    /// What `preview` returns in demo mode: empty optional fields dropped, health and finance filled in.
    public static func preview(_ content: String) -> String {
        let optional: Set<String> = ["情绪", "留痕", "未解", "明天唯一重点", "瞬间"]
        return content.components(separatedBy: "\n").compactMap { line -> String? in
            let t = line.trimmingCharacters(in: .whitespaces)
            guard let colon = t.firstIndex(of: "：") else { return line }
            let label = String(t[..<colon]), value = t[t.index(after: colon)...].trimmingCharacters(in: .whitespaces)
            if label == "健康" { return "健康：步数 6842，睡眠 7 小时 12 分" }
            if label == "财务" { return "财务：今日支出 ¥128.50" }
            return optional.contains(label) && value.isEmpty ? nil : line
        }.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
