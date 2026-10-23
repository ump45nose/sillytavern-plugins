import Foundation

/// Sample data matching the v1 design mockup. Replaced module by module from stage 2 onward.
public enum Sample {
    public static let snapshot = Snapshot(
        now: Now(date: "10 月 20 日", week: "周二", time: "17:58", hour: 17.97),
        cycle: Cycle(index: 3, day: 23, total: 42, start: "10/01", end: "11/11"),
        mainline: "构建可持续的个人系统",
        goals: [
            Goal(domain: "身体", tone: .olive, title: "每周 3 次力量训练", progress: 66, value: "本周 2 / 3"),
            Goal(domain: "事业", tone: .clay, title: "上线个人信息中心 v1", progress: 40, value: "设计中"),
            Goal(domain: "财务", tone: .kraft, title: "月支出低于 ¥5,000", progress: 86, value: "¥4,312"),
            Goal(domain: "关系", tone: .rose, title: "每周联系 2 位老朋友", progress: 50, value: "本周 1 / 2"),
            Goal(domain: "生活", tone: .sage, title: "每月读完 1 本书", progress: 62, value: "62%"),
        ],
        events: [
            CalendarEvent(start: 10, end: 11, title: "周会", location: "腾讯会议", tone: .sky),
            CalendarEvent(start: 14, end: 15.5, title: "迁移方案评审", location: "3F 会议室", tone: .steel),
            CalendarEvent(start: 19, end: 20.5, title: "羽毛球", location: "体育馆 3 号场", tone: .olive),
        ],
        tasks: TaskGroups(
            overdue: [TaskItem(title: "提交 Q4 迁移方案", list: "工作", due: "10/19", done: false)],
            today: [
                TaskItem(title: "给妈妈打电话", list: "个人", due: nil, done: false),
                TaskItem(title: "续费域名", list: "个人", due: nil, done: false),
                TaskItem(title: "整理 brainstorm 文档", list: "个人项目", due: nil, done: true),
            ],
            upcoming: [TaskItem(title: "准备阶段中期回顾", list: "复盘", due: "周五", done: false)]
        ),
        attention: [
            Attention(tone: .clay, title: "昨日日报草稿待确认", subtitle: "Hermes 21:30 生成 · 9,377 字", action: "查看"),
            Attention(tone: .ochre, title: "Claude Code 本周额度 61%", subtitle: "周四 09:00 重置", action: "详情"),
            Attention(tone: .clay, title: "「提交 Q4 迁移方案」逾期 1 天", subtitle: "Google Tasks · 工作", action: "处理"),
            Attention(tone: .olive, title: "PR #2790 等待 review 9 天", subtitle: "modelcontextprotocol/servers", action: "催一下"),
            Attention(tone: .rose, title: "赵六 46 天未联系", subtitle: "老朋友", action: "记一条"),
        ],
        health: Health(
            steps: 6842, stepGoal: 8000, kcal: 412, kcalGoal: 500, exercise: 18, exerciseGoal: 30,
            sleepMinutes: 432, restingHR: 58, spo2: 97,
            steps14: [9120, 7400, 10230, 5320, 8810, 12400, 3900, 7600, 8020, 9930, 6120, 11020, 8450, 6842],
            restingHR14: [61, 60, 60, 59, 61, 58, 57, 59, 58, 58, 60, 57, 58, 58],
            sleepStages: [("深睡", 106, .steel), ("浅睡", 228, .sky), ("REM", 82, .plum), ("清醒", 16, .ochre)]
        ),
        bills: Bills(
            today: 128.5, month: 4312.6, budget: 5000, daysLeft: 11,
            items: [("午餐", "餐饮", "12:14", 38), ("咖啡", "餐饮", "15:02", 26), ("地铁", "交通", "08:41", 6), ("京东 · 数据线", "购物", "16:30", 58.5)],
            d14: [210, 86, 132, 450, 98, 301, 1200, 76, 154, 220, 92, 180, 66, 128.5],
            categories: [("餐饮", 1420, .clay), ("购物", 1180, .kraft), ("居住", 900, .sage), ("交通", 312, .sky), ("其他", 500, .ink)],
            netWorth: 286430, netWorth6: [251, 259, 263, 270, 279, 286],
            accounts: [("招商银行", "¥182,300"), ("支付宝", "¥64,210"), ("基金", "¥40,010"), ("微信", "¥3,120"), ("信用卡", "−¥3,210")]
        ),
        crm: CRM(
            today: [
                Interaction(initial: "李", who: "李雷", relation: "同事", channel: "微信", time: "10:20", summary: "讨论 Q4 迁移排期，约定周五前给出第一版方案。", tone: .sky),
                Interaction(initial: "韩", who: "韩梅梅", relation: "同事", channel: "面对面", time: "14:00", summary: "迁移方案评审：同意分两期，第一期只迁读接口。", recording: "方案评审", duration: "1:28:40", tone: .steel),
                Interaction(initial: "陈", who: "陈老师", relation: "导师", channel: "电话", time: "12:30", summary: "聊到下一阶段要不要转向产品方向，建议先做出一个自己天天用的东西。", recording: "通话录音", duration: "18:12", tone: .kraft),
                Interaction(initial: "王", who: "王五", relation: "朋友", channel: "微信", time: "16:40", summary: "约周六一起吃饭。", tone: .sage),
            ],
            stagePeople: 23, stageInteractions: 87, stageRecordings: 11,
            stale: [("赵六", 46), ("孙七", 38), ("周八", 33)]
        ),
        media: Media(
            continueWatching: [
                Poster(title: "沙丘：预言", sub: "S1 · E4", progress: 62, gradient: ["#C9A27A", "#7B4B2A", "#3B2414"]),
                Poster(title: "繁花", sub: "E18", progress: 35, gradient: ["#B8C4D6", "#4F6A8A", "#1F2E44"]),
                Poster(title: "奥本海默", sub: "剩 52 分钟", progress: 72, gradient: ["#E7B98B", "#B5532E", "#3D1A0F"]),
                Poster(title: "漫长的季节", sub: "E6", progress: 20, gradient: ["#C8D1A9", "#6F8150", "#27311A"]),
                Poster(title: "葬送的芙莉莲", sub: "E12", progress: 55, gradient: ["#D9D3EA", "#8C7BB5", "#3A2F57"]),
                Poster(title: "三体", sub: "E9", progress: 10, gradient: ["#9FB2B8", "#2F4A55", "#0E1A20"]),
            ],
            latest: [("好东西", "电影 · 2024"), ("异形：夺命舰", "电影 · 2024"), ("小巷人家", "剧集 · E1–E12")],
            albums: [["#E8C9A8", "#B76E4B"], ["#C7D3E3", "#5E7FA6"], ["#D7DDBF", "#7D8F5E"], ["#E2D3E6", "#9C7BA0"], ["#F0DFB0", "#C9A23F"]],
            downloads: [("小巷人家 S01", 73), ("Interstellar 4K", 21)]
        ),
        token: TokenUsage(
            today: 18.6, cost: 42.17,
            d14: [12, 9, 21, 15, 7, 4, 18, 22, 16, 25, 14, 8, 19, 18.6],
            tools: [ToolUsage(name: "Claude Code", today: 8.2, tone: .clay), ToolUsage(name: "Codex", today: 5.1, tone: .steel),
                    ToolUsage(name: "Cursor", today: 3.6, tone: .kraft), ToolUsage(name: "Hermes", today: 1.7, tone: .sage)],
            limits: [
                UsageLimit(tool: "Claude Code", plan: "Max", tone: .clay, rows: [("当前会话 · 5 小时", 42, "2 小时 18 分后重置"), ("本周 · 全部模型", 61, "周四 09:00 重置")]),
                UsageLimit(tool: "Codex", plan: "Pro", tone: .steel, rows: [("5 小时窗口", 18, "3 小时 40 分后重置"), ("本周", 35, "周日 21:00 重置")]),
                UsageLimit(tool: "Cursor", plan: "Pro", tone: .kraft, rows: [("本月用量", 54, "11 月 1 日重置")]),
            ],
            devices: [("MacPro", 11.2), ("MacAir", 5.7), ("NAS", 1.7)]
        ),
        git: GitHubStatus(
            commitsToday: 7, repos: 3, commits30: 142, streak: 12,
            waiting: [
                GitWait(kind: .reply, repo: "modelcontextprotocol/servers", number: 2817, title: "fix(fetch): respect robots.txt timeout", who: "olivia-l", ago: "5 小时前", quote: "Could you add a test for the redirect case? Otherwise LGTM.", action: "回复"),
                GitWait(kind: .review, repo: "ump45nose/personal-crm", number: 41, title: "feat: 交流记录支持录音附件", who: "hermes-bot", ago: "2 小时前", quote: "请求你 review · +412 −38 · 9 个文件", action: "Review"),
                GitWait(kind: .mention, repo: "ump45nose/plaud-archive", number: 18, title: "相对音频链接在 Obsidian 中失效", who: "k-chen", ago: "昨天 22:10", quote: "@ump45nose 能确认一下 Windows 下的路径格式吗？", action: "回复"),
            ],
            blocked: [
                GitBlocked(repo: "modelcontextprotocol/servers", number: 2790, title: "feat(memory): add search by tag", reason: "等待 review", tone: .steel, ageDays: 9, ageText: nil, detail: "没有 reviewer 回应 · 已 ping 1 次"),
                GitBlocked(repo: "ump45nose/personal-review", number: 63, title: "fix(epic): reconcile old intents", reason: "CI 失败", tone: .rose, ageDays: 0, ageText: "3 小时", detail: "pytest · test_cycle_close 失败"),
                GitBlocked(repo: "astral-sh/uv", number: 15203, title: "docs: clarify index-strategy", reason: "需要修改", tone: .ochre, ageDays: 2, ageText: nil, detail: "维护者要求修改 2 处"),
                GitBlocked(repo: "ump45nose/personal-records", number: 27, title: "feat: assets snapshot API", reason: "合并冲突", tone: .clay, ageDays: 1, ageText: nil, detail: "与 main 冲突 · 3 个文件"),
            ]
        ),
        net: Network(
            pools: [
                TrafficPool(name: "主力机场", used: 317.6, total: 500, expiry: "11 月 30 日到期", daysLeft: 41),
                TrafficPool(name: "备用机场", used: 22.4, total: 100, expiry: "2027 年 3 月到期", daysLeft: 160),
            ],
            down: 6.8, up: 0.9, month: 142,
            hourly: [0.1, 0.05, 0.02, 0.01, 0.01, 0.02, 0.1, 0.3, 0.5, 0.6, 0.4, 0.7, 0.9, 0.5, 0.4, 0.8, 0.6, 0.3]
        ),
        subs: Subscriptions(monthly: 1486, list: [
            Subscription(glyph: "C", name: "Claude Max", price: "$100 / 月", renew: "8 天后", soon: true, color: "#D97757"),
            Subscription(glyph: "D", name: "域名 ×2", price: "¥96 / 年", renew: "5 天后", soon: true, color: "#5F7A99"),
            Subscription(glyph: "G", name: "ChatGPT Plus", price: "$20 / 月", renew: "14 天", soon: false, color: "#4E7F6E"),
            Subscription(glyph: "C", name: "Cursor Pro", price: "$20 / 月", renew: "12 天", soon: false, color: "#1F1E1B"),
            Subscription(glyph: "G", name: "Google One 2TB", price: "¥68 / 月", renew: "23 天", soon: false, color: "#6A9BCC"),
            Subscription(glyph: "V", name: "VPS", price: "$6 / 月", renew: "19 天", soon: false, color: "#9C7BA0"),
            Subscription(glyph: "机", name: "主力机场", price: "¥25 / 月", renew: "41 天", soon: false, color: "#C9A23F"),
        ]),
        sky: [
            SkyWindow(start: "12:00", end: "18:00", device: "MacPro", title: "个人信息中心详细设计", summary: "在 Cursor 中重做模块与主页设计，绘制 logo，并核对 NAS 上 personal-review 的阶段模型。", apps: ["#1F1E1B", "#6A9BCC", "#7D8F5E", "#D97757"], usage: [46, 24, 18, 12], yesterday: false),
            SkyWindow(start: "09:30", end: "12:00", device: "MacPro", title: "Hermes 日报投递故障修复", summary: "定位 Telegram 代理节点超时，切换 selector 后验证 getMe；CRM 读取改为本机 API。", apps: ["#1F1E1B", "#5F7A99", "#C9A23F"], usage: [52, 30, 18], yesterday: false),
            SkyWindow(start: "06:00", end: "12:00", device: "MacAir", title: "阅读与资料整理", summary: "浏览 Google Tasks API 文档和几个桌面客户端仓库，记录接口限制。", apps: ["#6A9BCC", "#9C7BA0"], usage: [70, 30], yesterday: false),
            SkyWindow(start: "18:00", end: "24:00", device: "MacPro", title: "Plaud 归档布局迁移", summary: "迁移旧 transcript.md 布局，修正音频相对链接并补测试。", apps: ["#1F1E1B", "#7D8F5E", "#6A9BCC"], usage: [58, 27, 15], yesterday: true),
            SkyWindow(start: "12:00", end: "18:00", device: "MacPro", title: "personal-records 部署", summary: "迁移 Health 与账单数据到独立 SQLite，核对审计报告。", apps: ["#1F1E1B", "#7D8F5E", "#C99A6E", "#5F7A99"], usage: [40, 30, 20, 10], yesterday: true),
            SkyWindow(start: "06:00", end: "12:00", device: "MacAir", title: "周末计划与采购", summary: "整理周末安排，比较两款跑鞋并下单。", apps: ["#6A9BCC", "#C97B84"], usage: [65, 35], yesterday: true),
        ],
        memos: [
            Memo(time: "今天 17:42", text: "方向定下来了：按模块组装，不按领域；任务和复盘目标合进主页。", tags: ["#日报"]),
            Memo(time: "今天 12:10", text: "KiteTasks 的中文日期只认「明日」，我们自己写规则。", tags: []),
            Memo(time: "昨天 22:31", text: "上线个人信息中心 v1 —— 进行中", tags: ["#阶段目标"]),
        ]
    )
}
