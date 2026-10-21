import Foundation

/// Demo data in hub-api's shape, placed relative to `now`, for when no hub is connected.
public enum HubSample {
    public static func data(now: Date = Date(), calendar: Calendar = .hub) -> HubData {
        let today = calendar.startOfDay(for: now)
        func day(_ n: Int) -> Date { calendar.date(byAdding: .day, value: n, to: today)! }
        func key(_ n: Int) -> String { TokenText.key(day(n), calendar) }
        func at(_ h: Int, _ m: Int, _ n: Int = 0) -> Date { calendar.date(byAdding: .minute, value: h * 60 + m, to: day(n))! }
        func env<T>(_ id: String, _ d: T, status: HubStatus = .ok) -> HubEnvelope<T> {
            HubEnvelope(module: id, status: status, updatedAt: now.addingTimeInterval(-120), data: d)
        }

        var out = HubData()
        let steps: [Double] = [9120, 7400, 10230, 5320, 8810, 12400, 3900, 7600, 8020, 9930, 6120, 11020, 8450, 6842]
        let hr: [Double] = [61, 60, 60, 59, 61, 58, 57, 59, 58, 58, 60, 57, 58, 58]
        out.health = env("health", HealthData(
            date: key(0), steps: 6842, stepGoal: 8000, activeKcal: 412, kcalGoal: 500, exerciseMinutes: 18, exerciseGoal: 30,
            sleepMinutes: 432, sleepStages: [.init(stage: "deep", minutes: 106), .init(stage: "core", minutes: 228), .init(stage: "rem", minutes: 82), .init(stage: "awake", minutes: 16)],
            restingHr: 58, spo2: 97,
            days: (0..<14).map { .init(date: key($0 - 13), steps: steps[$0], restingHr: hr[$0], sleepMinutes: 400 + Double($0 % 4) * 20) }))

        let spend: [Double] = [210, 86, 132, 450, 98, 301, 1200, 76, 154, 220, 92, 180, 66, 128.5]
        let monthEnd = calendar.range(of: .day, in: .month, for: today)!.count - calendar.component(.day, from: today)
        out.bills = env("bills", BillsData(
            date: key(0), todayTotal: 128.5, monthTotal: 4312.6, monthBudget: 5000, daysLeftInMonth: monthEnd,
            todayItems: [.init(id: "b1", title: "地铁", category: "交通", time: at(8, 41), amount: 6), .init(id: "b2", title: "午餐", category: "餐饮", time: at(12, 14), amount: 38),
                         .init(id: "b3", title: "咖啡", category: "餐饮", time: at(15, 2), amount: 26), .init(id: "b4", title: "京东 · 数据线", category: "购物", time: at(16, 30), amount: 58.5)],
            days: (0..<14).map { .init(date: key($0 - 13), total: spend[$0]) },
            monthCategories: [.init(name: "餐饮", amount: 1420), .init(name: "购物", amount: 1180), .init(name: "居住", amount: 900), .init(name: "交通", amount: 312), .init(name: "其他", amount: 500)],
            netWorth: 286430, netWorthMonths: [251, 259, 263, 270, 279, 286].enumerated().map { .init(month: "m\($0.offset)", value: $0.element * 1000) },
            accounts: [.init(name: "招商银行", balance: 182300), .init(name: "支付宝", balance: 64210), .init(name: "基金", balance: 40010), .init(name: "微信", balance: 3120), .init(name: "信用卡", balance: -3210)]))

        out.crm = env("crm", CRMData(
            today: [
                .init(id: "i1", personId: "p1", name: "李雷", relation: "同事", channel: "微信", time: at(10, 20), summary: "讨论 Q4 迁移排期，约定周五前给出第一版方案。"),
                .init(id: "i2", personId: "p2", name: "陈老师", relation: "导师", channel: "电话", time: at(12, 30), summary: "聊到下一阶段要不要转向产品方向，建议先做出一个自己天天用的东西。",
                      recording: .init(id: "sample:2", title: "通话录音", durationSeconds: 1092)),
                .init(id: "i3", personId: "p3", name: "韩梅梅", relation: "同事", channel: "面谈", time: at(14, 0), summary: "迁移方案评审：同意分两期，第一期只迁读接口。",
                      recording: .init(id: "sample:1", title: "方案评审", durationSeconds: 5320)),
                .init(id: "i4", personId: "p4", name: "王五", relation: "朋友", channel: "微信", time: at(16, 40), summary: "约周六一起吃饭。"),
            ],
            cycle: .init(start: key(-22), days: 42, people: 23, interactions: 87, recordings: 11),
            stale: [.init(personId: "p5", name: "赵六", days: 46), .init(personId: "p6", name: "孙七", days: 38), .init(personId: "p7", name: "周八", days: 33)]))

        out.media = env("media", MediaData(
            continueWatching: [("沙丘：预言", "S1 · E4", 0.62), ("繁花", "E18", 0.35), ("奥本海默", "剩 52 分钟", 0.72), ("漫长的季节", "E6", 0.2), ("葬送的芙莉莲", "E12", 0.55), ("三体", "E9", 0.1)]
                .enumerated().map { .init(id: "c\($0.offset)", title: $0.element.0, subtitle: $0.element.1, progress: $0.element.2) },
            latest: [("好东西", "电影 · 2024"), ("异形：夺命舰", "电影 · 2024"), ("小巷人家", "剧集 · E1–E12")]
                .enumerated().map { .init(id: "l\($0.offset)", title: $0.element.0, subtitle: $0.element.1) },
            recentAlbums: [("Random Access Memories", "Daft Punk"), ("范特西", "周杰伦"), ("Blue", "Joni Mitchell"), ("OK Computer", "Radiohead"), ("Kind of Blue", "Miles Davis")]
                .enumerated().map { .init(id: "a\($0.offset)", title: $0.element.0, artist: $0.element.1) },
            downloads: [.init(id: "d1", title: "小巷人家 S01", progress: 0.73, state: "downloading", speedBps: 9_800_000, etaSeconds: 600),
                        .init(id: "d2", title: "Interstellar 4K", progress: 0.21, state: "downloading", speedBps: 3_200_000, etaSeconds: 5400)],
            services: ["emby", "navidrome", "moviepilot", "qbittorrent"].map { .init(id: $0, status: .ok, link: nil) }))

        out.git = env("git", GitData(
            waiting: [
                .init(id: "w1", kind: "reply", repo: "modelcontextprotocol/servers", number: 2817, title: "fix(fetch): respect robots.txt timeout", who: "olivia-l", since: now.addingTimeInterval(-5 * 3600), quote: "Could you add a test for the redirect case? Otherwise LGTM."),
                .init(id: "w2", kind: "review", repo: "ump45nose/personal-crm", number: 41, title: "feat: 交流记录支持录音附件", who: "hermes-bot", since: now.addingTimeInterval(-2 * 3600), quote: "请求你 review · +412 −38 · 9 个文件"),
                .init(id: "w3", kind: "mention", repo: "ump45nose/plaud-archive", number: 18, title: "相对音频链接在 Obsidian 中失效", who: "k-chen", since: now.addingTimeInterval(-20 * 3600), quote: "@ump45nose 能确认一下 Windows 下的路径格式吗？"),
            ],
            blocked: [
                .init(id: "k1", repo: "modelcontextprotocol/servers", number: 2790, title: "feat(memory): add search by tag", reason: "no_review", since: day(-9), detail: "没有 reviewer 回应 · 已 ping 1 次"),
                .init(id: "k2", repo: "ump45nose/personal-review", number: 63, title: "fix(epic): reconcile old intents", reason: "ci_failed", since: now.addingTimeInterval(-3 * 3600), detail: "pytest · test_cycle_close 失败"),
                .init(id: "k3", repo: "astral-sh/uv", number: 15203, title: "docs: clarify index-strategy", reason: "changes_requested", since: day(-2), detail: "维护者要求修改 2 处"),
                .init(id: "k4", repo: "ump45nose/personal-records", number: 27, title: "feat: assets snapshot API", reason: "conflict", since: day(-1), detail: "与 main 冲突 · 3 个文件"),
            ],
            activity: .init(commitsToday: 7, commits30d: 142, repos30d: 3, streakDays: 12)))

        let gb = 1_073_741_824.0
        let hourly: [Double] = [0.1, 0.05, 0.02, 0.01, 0.01, 0.02, 0.1, 0.3, 0.5, 0.6, 0.4, 0.7, 0.9, 0.5, 0.4, 0.8, 0.6, 0.3, 0.4, 0.5, 0.6, 0.4, 0.3, 0.2]
        let hourNow = calendar.component(.hour, from: now)
        out.net = env("net", NetData(
            pools: [.init(id: "main", name: "主力机场", usedBytes: 317.6 * gb, totalBytes: 500 * gb, expiresOn: key(41)),
                    .init(id: "spare", name: "备用机场", usedBytes: 22.4 * gb, totalBytes: 100 * gb, expiresOn: key(160))],
            today: .init(downBytes: 6.8 * gb, upBytes: 0.9 * gb), monthBytes: 142 * gb,
            hourly: (0..<24).map { .init(hour: at($0, 0), bytes: $0 > hourNow ? nil : hourly[$0] * gb) }))

        func sub(_ id: String, _ name: String, _ price: Double, _ currency: String, _ cycle: String, _ renewIn: Int, _ monthly: Double) -> SubsData.Item {
            .init(id: id, name: name, price: price, currency: currency, cycle: cycle, nextRenewal: key(renewIn), monthlyEquivalent: monthly)
        }
        out.subs = env("subs", SubsData(monthlyTotal: 1486, items: [
            sub("claude", "Claude Max", 100, "USD", "month", 8, 712), sub("domain", "域名 ×2", 96, "CNY", "year", 5, 8),
            sub("chatgpt", "ChatGPT Plus", 20, "USD", "month", 14, 142.4), sub("cursor", "Cursor Pro", 20, "USD", "month", 12, 142.4),
            sub("google", "Google One 2TB", 68, "CNY", "month", 23, 68), sub("vps", "VPS", 6, "USD", "month", 19, 42.7), sub("proxy", "主力机场", 25, "CNY", "month", 41, 25),
        ]))

        out.memos = env("memos", MemosData(
            recent: [.init(id: "m1", createdAt: now.addingTimeInterval(-16 * 60), content: "方向定下来了：按模块组装，不按领域；任务和复盘目标合进主页。 #日报", tags: ["日报"]),
                     .init(id: "m2", createdAt: at(12, 10), content: "KiteTasks 的中文日期只认「明日」，我们自己写规则。", tags: []),
                     .init(id: "m3", createdAt: at(22, 31, -1), content: "上线个人信息中心 v1 —— 进行中 #阶段目标", tags: ["阶段目标"]),
                     .init(id: "m4", createdAt: at(9, 40, -2), content: "## 本周要做\n\n- [x] 复盘页并入主窗口\n- [ ] Plaud 转录着色\n- [ ] Memos **原生页**\n\n#周计划", tags: ["周计划"],
                           visibility: "PROTECTED", pinned: true),
                     .init(id: "m5", createdAt: at(23, 10, -3), content: "《置身事内》第 3 章：地方政府的土地财政。\n\n> 理解了激励，就理解了行为。\n\n#读书", tags: ["读书"]),
                     .init(id: "m6", createdAt: at(15, 2, -6), content: "菜单栏面板做成模块化以后，「今天」页应该只放今天能处理的东西，其他的进「生活」「工作」。 #想法", tags: ["想法"], visibility: "PUBLIC"),
                     .init(id: "m7", createdAt: at(21, 0, -9), content: "跑步 5km，配速 `5'48\"`，比上周快了 12 秒。 #健康", tags: ["健康"]),
                     .init(id: "m8", createdAt: at(11, 30, -16), content: "试了一下 [Memos 的 API](https://usememos.com/docs)，过滤语法比想象中好用。 #想法", tags: ["想法"]),
                     .init(id: "m9", createdAt: at(20, 15, -30), content: "一句话总结这个月：把散落的工具收进一个地方。 #日报", tags: ["日报"])],
            tags: [.init(name: "日报", count: 31), .init(name: "周报", count: 6), .init(name: "主线", count: 4), .init(name: "阶段目标", count: 9), .init(name: "想法", count: 18)]))

        let goals = ReviewSample.goals(now: now, calendar: calendar)
        out.goals = env("goals", goals)
        let label = goals.reviews?.daily?.label ?? ""
        let day = label.split(separator: "-").compactMap { Int($0) }
        out.attention = env("attention", AttentionData(items: [
            .init(id: "review:daily:\(label)", rule: "review_pending", severity: "warn",
                  title: day.count == 3 ? "\(day[1])/\(day[2]) 日报待确认" : "日报待确认",
                  subtitle: "6 小时后过期", target: .init(module: "goals")),
            .init(id: "token-limit:claude:week", rule: "token_limit", severity: "warn", title: "Claude Code 本周额度 61%", subtitle: "周四 09:00 重置", target: .init(module: "token")),
            .init(id: "pr-blocked:2790", rule: "pr_blocked", severity: "warn", title: "PR #2790 等待 review 9 天", subtitle: "modelcontextprotocol/servers", target: .init(module: "git")),
            .init(id: "stale-contact", rule: "stale_contact", severity: "info", title: "赵六 46 天未联系", subtitle: "老朋友", target: .init(module: "crm")),
        ]))

        for range in TokenRange.allCases { out.token[range] = env("token", tokenSample(range, now: now, calendar: calendar)) }
        out.sources = [("records_health", "健康"), ("records_bills", "账单"), ("crm", "CRM"), ("plaud", "Plaud"), ("memos", "Memos"), ("token", "Token Monitor"),
                       ("usage", "usage-monitor"), ("emby", "Emby"), ("navidrome", "Navidrome"), ("moviepilot", "MoviePilot"), ("qbittorrent", "qBittorrent"), ("github", "GitHub")]
            .map { HubSourceStatus(id: $0.0, name: $0.1, status: .ok, lastSuccess: now.addingTimeInterval(-120)) }
        out.fetchedAt = now
        return out
    }

    static let tools: [(id: String, name: String, weight: Double)] = [("claude", "Claude Code", 0.44), ("codex", "Codex", 0.27), ("cursor", "Cursor", 0.19), ("hermes", "Hermes", 0.10)]
    static let models: [(id: String, name: String, provider: String, weight: Double, rate: Double)] = [
        ("claude-sonnet", "Claude Sonnet", "anthropic", 0.33, 2.1), ("gpt-codex", "GPT Codex", "openai", 0.25, 1.6),
        ("claude-opus", "Claude Opus", "anthropic", 0.14, 7.5), ("cursor-auto", "Cursor Auto", "cursor", 0.12, 0.9),
        ("gemini-pro", "Gemini Pro", "google", 0.09, 1.3), ("grok", "Grok", "xai", 0.07, 1.1),
    ]
    static let sessions: [(String, String, String, String)] = [
        ("Token 模块重做：全部时间热力图", "claude", "Claude Sonnet", "MacPro"), ("hub-api 网络套餐接口", "codex", "GPT Codex", "MacPro"),
        ("复盘页并入主窗口", "claude", "Claude Opus", "MacAir"), ("Plaud 转录说话人着色", "cursor", "Cursor Auto", "MacPro"),
        ("Memos 分页与标签筛选", "codex", "GPT Codex", "MacAir"), ("修 skysight-sync 的 YAML 解析", "claude", "Claude Sonnet", "MacPro"),
        ("Android 布局同步", "hermes", "Gemini Pro", "NAS"), ("MCP 服务的写入确认", "claude", "Claude Opus", "MacPro"),
        ("阶段目标评论草稿", "codex", "GPT Codex", "MacAir"), ("周报模板整理", "cursor", "Grok", "MacPro"),
        ("账单识别规则", "claude", "Claude Sonnet", "MacAir"), ("Emby 播放记录接入", "codex", "GPT Codex", "NAS"),
    ]
    static let hourWeights: [Double] = [0.06, 0.03, 0.01, 0.01, 0.01, 0.02, 0.05, 0.2, 0.55, 0.85, 1, 0.9, 0.55, 0.7, 1, 1, 0.9, 0.8, 0.45, 0.4, 0.65, 0.75, 0.5, 0.2]

    /// Deterministic per-range token data so the heatmaps look plausible and stable between launches.
    static func tokenSample(_ range: TokenRange, now: Date, calendar: Calendar) -> TokenData {
        var rng = ParkMiller(seed: 29)
        let today = calendar.startOfDay(for: now), hour = calendar.component(.hour, from: now)
        let recent: [Double] = [12, 9, 21, 15, 7, 4, 18, 22, 16, 25, 14, 8, 19, 18.6]
        var daily: [Int: Double] = [:]
        for n in -800...0 {
            if n > -14 { daily[n] = recent[13 + n] * 1e6; continue }
            let weekday = calendar.component(.weekday, from: calendar.date(byAdding: .day, value: n, to: today)!)
            daily[n] = (weekday == 1 || weekday == 7 ? 0.45 : 1) * (9 + rng.next() * 18) * 1e6 * (n < -200 ? 0.35 : 1)
        }
        let hourSum = hourWeights.reduce(0, +)
        func hours(_ total: Double, upTo: Int) -> [Double?] {
            hourWeights.enumerated().map { h, w in h > upTo ? nil : (total * w / hourSum * (0.6 + rng.next() * 0.8)).rounded() }
        }
        func sum(_ a: Int, _ b: Int) -> Double { (a...b).reduce(0) { $0 + daily[$1]! } }
        func key(_ n: Int) -> String { TokenText.key(calendar.date(byAdding: .day, value: n, to: today)!, calendar) }

        let length = range == .year ? (calendar.component(.weekday, from: today) + 5) % 7 + 52 * 7 + 1 : range.days
        let start = 1 - length
        let total = sum(start, 0), previous = sum(start - length, start - 1)
        var d = TokenData(range: range, period: .init(start: key(start), end: key(0)), total: total, previous: previous, cost: total / 1e6 * 2.267,
                          limits: [.init(tool: "Claude Code", plan: "Max", windows: [.init(label: "当前会话 · 5 小时", percent: 42, resetsAt: now.addingTimeInterval(8280)), .init(label: "本周 · 全部模型", percent: 61, resetsAt: now.addingTimeInterval(2.6 * 86400))]),
                                   .init(tool: "Codex", plan: "Pro", windows: [.init(label: "5 小时窗口", percent: 18, resetsAt: now.addingTimeInterval(13200)), .init(label: "本周", percent: 35, resetsAt: now.addingTimeInterval(5.1 * 86400))])],
                          today: .init(total: daily[0], cost: daily[0]! / 1e6 * 2.267))
        if range != .year {
            let span = sum(start, 0), rate = 2.267 / 1e6
            d.history = (-400...0).map { .init(date: key($0), total: daily[$0], cost: daily[$0]! * rate) }
            d.tools = tools.map { .init(id: $0.id, name: $0.name, total: (span * $0.weight).rounded(), cost: span * $0.weight * rate) }
            d.devices = [("macpro", "MacPro", 0.6), ("macair", "MacAir", 0.31), ("nas", "NAS", 0.09)].map { .init(id: $0.0, name: $0.1, total: (span * $0.2).rounded()) }
            d.models = models.map { .init(id: $0.id, name: $0.name, total: (span * $0.weight).rounded(), cost: span * $0.weight * $0.rate / 1e6, provider: $0.provider) }
            let count = range == .day ? 6 : 12
            d.sessions = sessions.prefix(count).enumerated().map { i, x in
                let share = span * 0.42 * pow(0.78, Double(i)) / 3.2
                return .init(id: "s\(i)", title: x.0, tool: x.1, model: x.2, device: x.3, total: share.rounded(), cost: share * rate,
                             updatedAt: now.addingTimeInterval(-Double(i) * (range == .day ? 2400 : 26_000)))
            }
        }
        switch range {
        case .day:
            d.buckets = .init(unit: "hour", rows: "tool", series: tools.map { .init(key: $0.id, values: hours(daily[0]! * $0.weight, upTo: hour)) })
        case .week:
            d.buckets = .init(unit: "hour", rows: "date", series: (start...0).map { .init(key: key($0), values: hours(daily[$0]!, upTo: $0 == 0 ? hour : 23)) })
        case .month:
            d.buckets = .init(unit: "day", rows: "tool", series: tools.map { t in .init(key: t.id, values: (start...0).map { (daily[$0]! * t.weight * (0.7 + rng.next() * 0.6)).rounded() }) })
        case .year:
            d.buckets = .init(unit: "day", rows: "year", series: [.init(key: "year", values: (0..<371).map { start + $0 <= 0 ? daily[start + $0] : nil })])
        }
        return d
    }
}

/// Demo recordings and a transcript in the fused Plaud format.
public enum PlaudSample {
    static let items: [(day: Int, hour: Int, minute: Int, minutes: Double, title: String, people: [String])] = [
        (0, 14, 20, 52, "迁移方案评审", ["李雷", "韩梅梅"]), (0, 10, 5, 54, "周会", ["项目组"]),
        (-1, 20, 30, 18, "和妈妈通话", ["妈妈"]), (-1, 15, 10, 33, "面试复盘", ["陈老师"]),
        (-2, 11, 0, 41, "季度规划", ["李雷", "王五"]), (-3, 19, 40, 26, "健身课", ["教练"]),
        (-4, 9, 30, 47, "读书会", ["赵六", "钱七"]), (-5, 16, 0, 22, "和房东沟通", ["房东"]),
    ]

    public static func list(now: Date, calendar: Calendar = .hub) -> PlaudList {
        let today = calendar.startOfDay(for: now)
        var days: [PlaudList.Day] = []
        for (n, group) in Dictionary(grouping: items.indices, by: { items[$0].day }).sorted(by: { $0.key > $1.key }) {
            let date = calendar.date(byAdding: .day, value: n, to: today)!
            let recordings = group.map { i in
                PlaudList.Recording(id: "sample:plaud:\(i)", title: items[i].title,
                                    startAt: calendar.date(bySettingHour: items[i].hour, minute: items[i].minute, second: 0, of: date),
                                    durationSeconds: items[i].minutes * 60)
            }
            days.append(.init(date: TokenText.key(date, calendar), recordings: recordings, hasTranscript: true,
                              people: Array(Set(group.flatMap { items[$0].people })).sorted()))
        }
        return PlaudList(days: days)
    }

    public static func people(_ id: String) -> [String] {
        Int(id.split(separator: ":").last ?? "").flatMap { items.indices.contains($0) ? items[$0].people : nil } ?? []
    }

    public static func transcript(_ id: String) -> String? {
        guard id.hasPrefix("sample:plaud:") else { return nil }
        return """
        ## 摘要

        确定先迁健康与账单两个数据源；交流数据等 CRM 接口稳定后再迁。周五前给出回滚预案，下周一灰度。

        - 健康：SQLite 已独立，审计报告核对完毕
        - 账单：AutoAccounting 导入口径不变

        ## 逐字稿

        [00:12] 【他人】健康这块的 SQLite 已经独立出来了，审计报告也核对过，我觉得可以先切。
        [00:31] 【我】那账单一起切，AutoAccounting 的导入口径没变。交流先别动。
        [00:44] 【他人】交流那边 CRM 的接口还在改字段，等它稳定了再说。
        [01:02] 【我】好，那就先这两个。回滚怎么做？
        [01:15] Speaker 3: 回滚预案我来写，周五前发群里。
        [01:28] 【我?】[听不清] 下周一灰度可以吗？
        [01:34] Speaker 3: 可以，先灰度一半设备。

        > 决定：健康、账单本周切换；交流延后。
        """
    }
}
