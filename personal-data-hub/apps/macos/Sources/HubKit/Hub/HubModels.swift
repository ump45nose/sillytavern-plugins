import Foundation

// Wire types for hub-api (docs/plans/2026-10-20-phase3-nas.md §5). Every field the contract allows
// to be null is optional; a missing measurement must never be shown as zero.

public enum HubModule: String, Codable, CaseIterable, Sendable {
    case health, bills, crm, media, token, git, net, subs, memos, attention, goals
}

public enum HubStatus: String, Codable, Sendable {
    case ok, partial, stale, error, unconfigured

    /// Data is present (possibly incomplete or old).
    public var hasData: Bool { self == .ok || self == .partial || self == .stale }
}

public struct HubSourceRef: Codable, Equatable, Sendable {
    public var id: String
    public var status: HubStatus
    public var updatedAt: Date?
}

public struct HubEnvelope<T: Codable & Sendable & Equatable>: Codable, Equatable, Sendable {
    public var module: String
    public var status: HubStatus
    public var updatedAt: Date?
    public var sources: [HubSourceRef]
    public var data: T?

    public init(module: String, status: HubStatus, updatedAt: Date?, sources: [HubSourceRef] = [], data: T?) {
        self.module = module
        self.status = status
        self.updatedAt = updatedAt
        self.sources = sources
        self.data = data
    }
}

public struct HubSourceStatus: Codable, Equatable, Sendable, Identifiable {
    public struct Failure: Codable, Equatable, Sendable {
        public var type: String
        public var statusCode: Int?
    }
    public var id: String
    public var name: String
    public var status: HubStatus
    public var lastSuccess: Date?
    public var lastError: Failure?
    public var latencyMs: Int?
}

public struct HubStatusPage: Codable, Equatable, Sendable {
    public var sources: [HubSourceStatus]
}

// MARK: Module data

public struct HealthData: Codable, Equatable, Sendable {
    public struct Stage: Codable, Equatable, Sendable { public var stage: String; public var minutes: Double? }
    public struct Day: Codable, Equatable, Sendable {
        public var date: String
        public var steps: Double?
        public var restingHr: Double?
        public var sleepMinutes: Double?
    }
    public var date: String
    public var steps: Double?, stepGoal: Double?
    public var activeKcal: Double?, kcalGoal: Double?
    public var exerciseMinutes: Double?, exerciseGoal: Double?
    public var sleepMinutes: Double?
    public var sleepStages: [Stage]?
    public var restingHr: Double?, spo2: Double?
    public var days: [Day]?
}

public struct BillsData: Codable, Equatable, Sendable {
    public struct Item: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var title: String?
        public var category: String?
        public var time: Date?
        public var amount: Double?
    }
    public struct Day: Codable, Equatable, Sendable { public var date: String; public var total: Double? }
    public struct Category: Codable, Equatable, Sendable { public var name: String; public var amount: Double? }
    public struct Month: Codable, Equatable, Sendable { public var month: String; public var value: Double? }
    public struct Account: Codable, Equatable, Sendable { public var name: String; public var balance: Double? }
    public var date: String
    public var todayTotal: Double?, monthTotal: Double?, monthBudget: Double?
    public var daysLeftInMonth: Int?
    public var todayItems: [Item]?
    public var days: [Day]?
    public var monthCategories: [Category]?
    public var netWorth: Double?
    public var netWorthMonths: [Month]?
    public var accounts: [Account]?
}

public struct CRMData: Codable, Equatable, Sendable {
    public struct Recording: Codable, Equatable, Sendable {
        public var id: String
        public var title: String?
        public var durationSeconds: Double?
    }
    public struct Interaction: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var personId: String?
        public var name: String
        public var relation: String?
        public var channel: String?
        public var time: Date?
        public var summary: String?
        public var recording: Recording?
    }
    public struct Cycle: Codable, Equatable, Sendable {
        public var start: String?
        public var days: Int?
        public var people: Int?, interactions: Int?, recordings: Int?
    }
    public struct Stale: Codable, Equatable, Sendable { public var personId: String?; public var name: String; public var days: Int? }
    public var today: [Interaction]?
    public var cycle: Cycle?
    public var stale: [Stale]?
}

public struct MediaData: Codable, Equatable, Sendable {
    public struct Item: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var title: String
        public var subtitle: String?
        /// 0–1.
        public var progress: Double?
        public var image: String?
        public var link: String?
    }
    public struct Album: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var title: String
        public var artist: String?
        public var image: String?
        public var link: String?
    }
    public struct Download: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var title: String
        public var progress: Double?
        public var state: String?
        public var speedBps: Double?
        public var etaSeconds: Double?
    }
    public struct Service: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var status: HubStatus
        public var link: String?
    }
    public var continueWatching: [Item]?
    public var latest: [Item]?
    public var recentAlbums: [Album]?
    public var downloads: [Download]?
    public var services: [Service]?
}

public struct TokenData: Codable, Equatable, Sendable {
    public struct Period: Codable, Equatable, Sendable { public var start: String; public var end: String }
    public struct Part: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var name: String
        public var total: Double?
        public var cost: Double? = nil
        public var provider: String? = nil
    }
    public struct Day: Codable, Equatable, Sendable { public var date: String; public var total: Double?; public var cost: Double? }
    /// Titles only: hub keeps no session content, paths or accounts.
    public struct Session: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var title: String?
        public var tool: String?
        public var model: String?
        public var device: String?
        public var total: Double?
        public var cost: Double?
        public var updatedAt: Date?
    }
    public struct Series: Codable, Equatable, Sendable { public var key: String; public var values: [Double?] }
    public struct Buckets: Codable, Equatable, Sendable {
        public var unit: String
        public var rows: String
        public var series: [Series]
    }
    public struct Window: Codable, Equatable, Sendable {
        public var label: String
        public var percent: Double?
        public var resetsAt: Date?
    }
    public struct Limit: Codable, Equatable, Sendable {
        public var tool: String
        public var plan: String?
        public var windows: [Window]
        /// Which login the quota belongs to when one tool has several (email or nickname).
        public var account: String? = nil
    }
    public struct Today: Codable, Equatable, Sendable { public var total: Double?; public var cost: Double? }
    public var range: TokenRange
    public var period: Period?
    /// Raw token counts; `cost` is the source's USD estimate.
    public var total: Double?, previous: Double?, cost: Double?
    public var tools: [Part]?
    public var devices: [Part]?
    public var buckets: Buckets?
    public var limits: [Limit]?
    public var today: Today?
    /// Every recorded day, the same whatever the range.
    public var history: [Day]? = nil
    public var models: [Part]? = nil
    public var sessions: [Session]? = nil
}

public struct GitData: Codable, Equatable, Sendable {
    public struct Waiting: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var kind: String
        public var repo: String
        public var number: Int
        public var title: String
        public var who: String?
        public var since: Date?
        public var quote: String?
        public var url: String?
    }
    public struct Blocked: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var repo: String
        public var number: Int
        public var title: String
        public var reason: String
        public var since: Date?
        public var detail: String?
        public var url: String?
    }
    public struct Activity: Codable, Equatable, Sendable {
        public var commitsToday: Int?, commits30d: Int?, repos30d: Int?, streakDays: Int?
    }
    public var waiting: [Waiting]?
    public var blocked: [Blocked]?
    public var activity: Activity?
}

public struct NetData: Codable, Equatable, Sendable {
    public struct Pool: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var name: String
        public var usedBytes: Double?, totalBytes: Double?
        public var expiresOn: String?
        public var periodStart: String?, periodEnd: String?
        /// "manual" when the plan was entered in settings.
        public var source: String?
    }
    public struct Traffic: Codable, Equatable, Sendable { public var downBytes: Double?; public var upBytes: Double? }
    public struct Hour: Codable, Equatable, Sendable { public var hour: Date; public var bytes: Double? }
    public var pools: [Pool]?
    public var today: Traffic?
    public var monthBytes: Double?
    public var hourly: [Hour]?
}

public struct SubsData: Codable, Equatable, Sendable {
    public struct Charge: Codable, Equatable, Sendable { public var date: String; public var amount: Double? }
    public struct Item: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var name: String
        public var price: Double?
        public var currency: String?
        public var cycle: String?
        public var nextRenewal: String?
        public var monthlyEquivalent: Double?
        public var lastCharge: Charge?
        public var version: Int?
        public var accountLabel: String?
        public var category: String?
        public var payer: String?
        public var frequency: Int?
        public var active: Bool?
        public var quota: SubscriptionQuota?
        public var serviceKey: String?
        public var iconUrl: String?
        public var themeColor: String?
        public var subscriptionUrl: String?
        public var expiresOn: String?
        public var plan: String?
        /// Free text: 美国, 印度…
        public var billingRegion: String?
        public var autoRenew: Bool?
        /// The price and the monthly spend in CNY and USD, at the rate of `exchangeRateDate`.
        public var priceConverted: [String: Double]?
        public var monthlyConverted: [String: Double]?
        public var exchangeRateDate: String?
        public var exchangeRateStale: Bool?
        public var binding: SubscriptionBinding?
        public var quotaSource: String?
        public var note: String?
    }
    /// Units per one `base`, as decimal strings.
    public struct ExchangeRates: Codable, Equatable, Sendable {
        public var base: String?
        public var stale: Bool?
        public var rates: [String: String]?

        public init(base: String? = nil, stale: Bool? = nil, rates: [String: String]? = nil) {
            self.base = base; self.stale = stale; self.rates = rates
        }

        public init(from decoder: Decoder) throws {
            enum K: String, CodingKey { case base, stale, rates }
            let c = try decoder.container(keyedBy: K.self)
            base = try? c.decodeIfPresent(String.self, forKey: .base)
            stale = try? c.decodeIfPresent(Bool.self, forKey: .stale)
            rates = (try? c.decodeIfPresent([String: String].self, forKey: .rates))
                ?? (try? c.decodeIfPresent([String: Double].self, forKey: .rates))?.mapValues { String($0) }
        }

        /// `amount` of `from` in `to`; nil when either rate is missing.
        public func convert(_ amount: Double, from: String, to: String) -> Double? {
            if from == to { return amount }
            guard let f = rates?[from].flatMap(Double.init), let t = rates?[to].flatMap(Double.init), f > 0 else { return nil }
            return amount / f * t
        }
    }
    public var monthlyTotal: Double?
    public var items: [Item]?
    public var monthlyByCurrency: [String: Double]?
    public var unclassifiedPayerCount: Int?
    public var monthlyConverted: [String: Double]?
    public var unconvertedCurrencies: [String]?
    public var exchangeRates: ExchangeRates?
}

public struct MemosData: Codable, Equatable, Sendable {
    public struct Memo: Codable, Equatable, Sendable, Identifiable {
        public struct Attachment: Codable, Equatable, Sendable { public var name: String; public var filename: String?; public var type: String? }
        public var id: String
        public var createdAt: Date?
        public var content: String
        public var tags: [String]?
        public var visibility: String?
        public var url: String?
        public var updatedAt: Date? = nil
        public var pinned: Bool? = nil
        public var attachments: [Attachment]? = nil
        /// `NORMAL` or `ARCHIVED`; older hubs leave it out.
        public var state: String? = nil
    }
    public struct Tag: Codable, Equatable, Sendable {
        public var name: String
        public var count: Int?
        public init(name: String, count: Int?) { self.name = name; self.count = count }
    }
    public var recent: [Memo]?
    public var tags: [Tag]?
}

/// One page of `GET /api/v1/memos`, newest first.
public struct MemoPage: Codable, Equatable, Sendable {
    public var items: [MemosData.Memo]
    public var nextPageToken: String?

    public init(items: [MemosData.Memo], nextPageToken: String? = nil) {
        self.items = items
        self.nextPageToken = nextPageToken
    }
}

public struct AttentionData: Codable, Equatable, Sendable {
    public struct Target: Codable, Equatable, Sendable { public var module: String? }
    public struct Item: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var rule: String
        public var severity: String?
        public var title: String
        public var subtitle: String?
        public var since: Date?
        public var target: Target?
        public var url: String?
    }
    public var items: [Item]?
}

/// The latest envelope of every module; what the views render and what is cached on disk.
public struct HubData: Codable, Equatable, Sendable {
    public var health: HubEnvelope<HealthData>?
    public var bills: HubEnvelope<BillsData>?
    public var crm: HubEnvelope<CRMData>?
    public var media: HubEnvelope<MediaData>?
    public var git: HubEnvelope<GitData>?
    public var net: HubEnvelope<NetData>?
    public var subs: HubEnvelope<SubsData>?
    public var memos: HubEnvelope<MemosData>?
    public var attention: HubEnvelope<AttentionData>?
    public var goals: HubEnvelope<GoalsData>?
    /// Token per range; the batch call only returns the day range.
    public var token: [TokenRange: HubEnvelope<TokenData>] = [:]
    public var sources: [HubSourceStatus] = []
    public var fetchedAt: Date?

    public init() {}

    public func status(_ module: HubModule) -> HubStatus? {
        switch module {
        case .health: health?.status
        case .bills: bills?.status
        case .crm: crm?.status
        case .media: media?.status
        case .token: token[.day]?.status
        case .git: git?.status
        case .net: net?.status
        case .subs: subs?.status
        case .memos: memos?.status
        case .attention: attention?.status
        case .goals: goals?.status
        }
    }

    public func updatedAt(_ module: HubModule) -> Date? {
        switch module {
        case .health: health?.updatedAt
        case .bills: bills?.updatedAt
        case .crm: crm?.updatedAt
        case .media: media?.updatedAt
        case .token: token[.day]?.updatedAt
        case .git: git?.updatedAt
        case .net: net?.updatedAt
        case .subs: subs?.updatedAt
        case .memos: memos?.updatedAt
        case .attention: attention?.updatedAt
        case .goals: goals?.updatedAt
        }
    }
}

/// `GET /api/v1/modules`: `{modules: {id: envelope}}` with a different data type per key.
struct HubBatch: Decodable {
    var data = HubData()

    private struct Key: CodingKey {
        var stringValue: String
        var intValue: Int? { nil }
        init(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { nil }
    }
    private enum Top: String, CodingKey { case modules }

    init(from decoder: Decoder) throws {
        let modules = try decoder.container(keyedBy: Top.self).nestedContainer(keyedBy: Key.self, forKey: .modules)
        func one<T>(_ id: HubModule, _: T.Type) -> HubEnvelope<T>? {
            // One malformed module must not take the others down.
            try? modules.decodeIfPresent(HubEnvelope<T>.self, forKey: Key(stringValue: id.rawValue))
        }
        data.health = one(.health, HealthData.self)
        data.bills = one(.bills, BillsData.self)
        data.crm = one(.crm, CRMData.self)
        data.media = one(.media, MediaData.self)
        data.git = one(.git, GitData.self)
        data.net = one(.net, NetData.self)
        data.subs = one(.subs, SubsData.self)
        data.memos = one(.memos, MemosData.self)
        data.attention = one(.attention, AttentionData.self)
        data.goals = one(.goals, GoalsData.self)
        if let day = one(.token, TokenData.self) { data.token[.day] = day }
    }
}

public enum HubJSON {
    public static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        d.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            guard let date = parseDate(text) else {
                throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath, debugDescription: "bad date"))
            }
            return date
        }
        return d
    }()

    public static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        e.dateEncodingStrategy = .custom { date, encoder in
            var c = encoder.singleValueContainer()
            try c.encode(format(date))
        }
        return e
    }()

    /// Python's isoformat emits 0 or 6 fractional digits; ISO8601DateFormatter only takes 3.
    public static func parseDate(_ text: String) -> Date? {
        var s = text
        if let dot = s.firstIndex(of: "."), let end = s[dot...].firstIndex(where: { !$0.isNumber && $0 != "." }) {
            let digits = s[s.index(after: dot)..<end]
            s.replaceSubrange(dot..<end, with: "." + String((digits + "000").prefix(3)))
        }
        return withFraction.date(from: s) ?? plain.date(from: s)
    }

    public static func format(_ date: Date) -> String { plain.string(from: date) }

    nonisolated(unsafe) private static let withFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    nonisolated(unsafe) private static let plain: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        f.timeZone = .current
        return f
    }()
}

extension TokenRange: CodingKeyRepresentable {}
