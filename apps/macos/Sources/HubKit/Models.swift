import Foundation

public enum Tone: String, Codable, Sendable, CaseIterable {
    case clay, kraft, olive, sky, plum, sage, ochre, rose, steel, ink
}

public struct Snapshot: Sendable {
    public var now: Now
    public var cycle: Cycle
    public var mainline: String
    public var goals: [Goal]
    public var events: [CalendarEvent]
    public var tasks: TaskGroups
    public var attention: [Attention]
    public var health: Health
    public var bills: Bills
    public var crm: CRM
    public var media: Media
    public var token: TokenUsage
    public var git: GitHubStatus
    public var net: Network
    public var subs: Subscriptions
    public var sky: [SkyWindow]
    public var memos: [Memo]
}

public struct Now: Sendable {
    public var date: String, week: String, time: String
    /// Fractional hour of day, e.g. 17.97.
    public var hour: Double
}

public struct Cycle: Sendable {
    public var index: Int, day: Int, total: Int
    public var start: String, end: String
    public var remaining: Int { total - day }

    public init(index: Int, day: Int, total: Int, start: String, end: String) {
        self.index = index
        self.day = day
        self.total = total
        self.start = start
        self.end = end
    }
}

public struct Goal: Sendable, Identifiable {
    public var domain: String, tone: Tone, title: String
    public var progress: Double, value: String
    public var id: String { title }
}

public struct CalendarEvent: Sendable, Identifiable {
    public var start: Double, end: Double
    public var title: String, location: String, tone: Tone
    public var id: String { title }
}

public struct TaskItem: Sendable, Identifiable, Hashable {
    public var title: String, list: String
    public var due: String?
    public var done: Bool
    public var id: String { title }
}

public struct TaskGroups: Sendable {
    public var overdue: [TaskItem], today: [TaskItem], upcoming: [TaskItem]
    public var dueCount: Int { overdue.count + today.filter { !$0.done }.count }
}

public struct Attention: Sendable, Identifiable {
    public var tone: Tone, title: String, subtitle: String, action: String
    public var id: String { title }
}

public struct Health: Sendable {
    public var steps: Int, stepGoal: Int, kcal: Int, kcalGoal: Int, exercise: Int, exerciseGoal: Int
    public var sleepMinutes: Int, restingHR: Int, spo2: Int
    public var steps14: [Double], restingHR14: [Double]
    public var sleepStages: [(name: String, minutes: Int, tone: Tone)]
}

public struct Bills: Sendable {
    public var today: Double, month: Double, budget: Double, daysLeft: Int
    public var items: [(title: String, category: String, time: String, amount: Double)]
    public var d14: [Double]
    public var categories: [(name: String, amount: Double, tone: Tone)]
    public var netWorth: Double, netWorth6: [Double]
    public var accounts: [(name: String, value: String)]
}

public struct Interaction: Sendable, Identifiable {
    public var initial: String, who: String, relation: String, channel: String, time: String, summary: String
    public var recording: String?, duration: String?
    public var tone: Tone
    public var id: String { who + time }
}

public struct CRM: Sendable {
    public var today: [Interaction]
    public var stagePeople: Int, stageInteractions: Int, stageRecordings: Int
    public var stale: [(name: String, days: Int)]
}

public struct Poster: Sendable, Identifiable {
    public var title: String, sub: String, progress: Double
    public var gradient: [String]
    public var id: String { title }
}

public struct Media: Sendable {
    public var continueWatching: [Poster]
    public var latest: [(title: String, sub: String)]
    public var albums: [[String]]
    public var downloads: [(title: String, progress: Double)]
}

public struct ToolUsage: Sendable {
    public var name: String, today: Double, tone: Tone
}

public struct UsageLimit: Sendable, Identifiable {
    public var tool: String, plan: String, tone: Tone
    public var rows: [(label: String, percent: Double, reset: String)]
    public var id: String { tool }
}

public struct TokenUsage: Sendable {
    public var today: Double, cost: Double
    public var d14: [Double]
    public var tools: [ToolUsage]
    public var limits: [UsageLimit]
    public var devices: [(name: String, today: Double)]
}

public enum GitWaitKind: String, Sendable { case reply, review, mention }

public struct GitWait: Sendable, Identifiable {
    public var kind: GitWaitKind, repo: String, number: Int, title: String, who: String, ago: String, quote: String, action: String
    public var id: Int { number }
}

public struct GitBlocked: Sendable, Identifiable {
    public var repo: String, number: Int, title: String, reason: String, tone: Tone
    public var ageDays: Int, ageText: String?, detail: String
    public var id: Int { number }
}

public struct GitHubStatus: Sendable {
    public var commitsToday: Int, repos: Int, commits30: Int, streak: Int
    public var waiting: [GitWait], blocked: [GitBlocked]
}

public struct TrafficPool: Sendable, Identifiable {
    public var name: String, used: Double, total: Double, expiry: String, daysLeft: Int
    public var remaining: Double { total - used }
    public var id: String { name }
}

public struct Network: Sendable {
    public var pools: [TrafficPool]
    public var down: Double, up: Double, month: Double
    public var hourly: [Double]
}

public struct Subscription: Sendable, Identifiable {
    public var glyph: String, name: String, price: String, renew: String, soon: Bool, color: String
    public var id: String { name }
}

public struct Subscriptions: Sendable {
    public var monthly: Double
    public var list: [Subscription]
}

public struct SkyWindow: Sendable, Identifiable {
    public var start: String, end: String, device: String, title: String, summary: String
    public var apps: [String], usage: [Double]
    public var yesterday: Bool
    public var id: String { start + device + title }
}

public struct Memo: Sendable, Identifiable {
    public var time: String, text: String, tags: [String]
    public var id: String { time + text }
}
