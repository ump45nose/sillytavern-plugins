import Foundation

public struct SubscriptionBinding: Codable, Equatable, Sendable {
    public var collector: String
    public var provider: String
    public var account: String
    public var accountEmail: String?
    public var profile: String?
}

public struct SubscriptionQuota: Codable, Equatable, Sendable {
    public struct Window: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var label: String
        public var unit: String?
        public var used: Double?, limit: Double?, remaining: Double?, usedPercent: Double?
        public var resetsAt: Date?, expiresAt: Date?
        public var observedAt: Date

        public init(id: String, label: String, unit: String? = nil, used: Double? = nil, limit: Double? = nil, remaining: Double? = nil,
                    usedPercent: Double? = nil, resetsAt: Date? = nil, expiresAt: Date? = nil, observedAt: Date) {
            self.id = id; self.label = label; self.unit = unit; self.used = used; self.limit = limit; self.remaining = remaining
            self.usedPercent = usedPercent; self.resetsAt = resetsAt; self.expiresAt = expiresAt; self.observedAt = observedAt
        }
    }
    public struct Reading: Codable, Equatable, Sendable {
        public var windows: [Window]
        public var observedAt: Date
        public var expiresAt: Date?

        public init(windows: [Window], observedAt: Date, expiresAt: Date? = nil) {
            self.windows = windows; self.observedAt = observedAt; self.expiresAt = expiresAt
        }
    }
    public var reading: Reading?
    public var status: String
    public var stale: Bool
    public var error: String?
    public var lastSuccessAt: Date? = nil

    enum CodingKeys: String, CodingKey { case reading, status, stale, error, lastSuccessAt }

    public init(reading: Reading?, status: String, stale: Bool, error: String? = nil, lastSuccessAt: Date? = nil) {
        self.reading = reading; self.status = status; self.stale = stale; self.error = error; self.lastSuccessAt = lastSuccessAt
    }
}

extension SubscriptionQuota {
    /// `error` may come as a plain message or as a problem object; a reading the decoder can't read is left out
    /// rather than failing the whole subscription list.
    public init(from decoder: Decoder) throws {
        struct Problem: Decodable { var message: String?; var detail: String?; var code: String? }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        reading = try? c.decodeIfPresent(Reading.self, forKey: .reading)
        status = (try? c.decodeIfPresent(String.self, forKey: .status)) ?? "unknown"
        stale = (try? c.decodeIfPresent(Bool.self, forKey: .stale)) ?? false
        if let text = try? c.decodeIfPresent(String.self, forKey: .error) {
            error = text
        } else if let p = try? c.decodeIfPresent(Problem.self, forKey: .error) {
            error = p.message ?? p.detail ?? p.code ?? "解析失败"
        } else {
            error = nil
        }
        lastSuccessAt = try? c.decodeIfPresent(Date.self, forKey: .lastSuccessAt)
    }
}

public struct SubscriptionRecord: Codable, Equatable, Sendable, Identifiable {
    public var id: String = ""
    public var version: Int = 0
    public var name: String = ""
    public var serviceKey: String?
    public var iconUrl: String?
    public var themeColor: String?
    public var subscriptionUrl: String?
    public var accountLabel: String = ""
    public var category: String = "other"
    public var plan: String = ""
    public var price: String?
    public var currency: String = "CNY"
    public var cycle: String?
    public var frequency: Int = 1
    public var nextRenewal: String?
    public var expiresOn: String?
    public var payer: String = "unknown"
    public var autoRenew: Bool = false
    public var active: Bool = true
    public var note: String = ""
    /// Free text: 美国, 印度…
    public var billingRegion: String?
    public var binding: SubscriptionBinding?
    public var quota: SubscriptionQuota?

    public init() {}

    public var document: [String: Any] {
        var result: [String: Any] = ["name": name,
            "service_key": serviceKey as Any? ?? NSNull(), "theme_color": themeColor as Any? ?? NSNull(),
            "subscription_url": subscriptionUrl as Any? ?? NSNull(), "account_label": accountLabel, "category": category,
            "plan": plan, "price": price as Any? ?? NSNull(), "currency": currency,
            "cycle": cycle as Any? ?? NSNull(), "frequency": frequency,
            "next_renewal": nextRenewal as Any? ?? NSNull(), "expires_on": expiresOn as Any? ?? NSNull(),
            "payer": payer, "auto_renew": autoRenew, "active": active, "note": note,
            "billing_region": billingRegion.flatMap { $0.trimmingCharacters(in: .whitespaces).isEmpty ? nil : $0 } as Any? ?? NSNull()]
        if let binding {
            result["binding"] = ["collector": binding.collector, "provider": binding.provider,
                "account": binding.account, "account_email": binding.accountEmail ?? "", "profile": binding.profile ?? ""]
        } else { result["binding"] = NSNull() }
        return result
    }
}

public struct SubscriptionBrandCatalog: Decodable, Sendable {
    public struct Brand: Decodable, Sendable, Identifiable {
        public var serviceKey: String
        public var name: String
        public var iconUrl: String
        public var themeColor: String
        public var subscriptionUrl: String?
        public var id: String { serviceKey }
    }
    public var items: [Brand]
}

public struct SubscriptionSourceCatalog: Decodable, Sendable {
    public struct Source: Decodable, Sendable {
        public struct Account: Decodable, Sendable, Identifiable {
            public var collector: String, provider: String, account: String
            public var accountEmail: String?, profile: String?
            public var id: String { collector + ":" + provider + ":" + account }
            public var label: String { provider + " · " + (profile.flatMap { $0.isEmpty ? nil : $0 } ?? accountEmail.flatMap { $0.isEmpty ? nil : $0 } ?? String(account.suffix(8))) }
            public var binding: SubscriptionBinding { SubscriptionBinding(collector: collector, provider: provider, account: account, accountEmail: accountEmail, profile: profile) }
        }
        public var accounts: [Account]
    }
    public var sources: [Source]
}

/// Accounts of one product: records sharing a `service_key`, or the exact name when there is none.
public struct SubsProduct: Identifiable, Equatable, Sendable {
    public var id: String
    public var items: [SubsData.Item]
    public var lead: SubsData.Item { items[0] }

    /// Keeps the order in which products first appear.
    public static func group(_ items: [SubsData.Item]) -> [SubsProduct] {
        var out: [SubsProduct] = [], index: [String: Int] = [:]
        for s in items {
            let key = s.serviceKey.flatMap { $0.isEmpty ? nil : "k:" + $0 } ?? "n:" + s.name.trimmingCharacters(in: .whitespaces)
            if let i = index[key] { out[i].items.append(s) } else {
                index[key] = out.count
                out.append(SubsProduct(id: key, items: [s]))
            }
        }
        return out
    }
}

extension SubsData {
    /// Monthly spend converted to `currency`: the hub's total when it sent one, else the active items' sum.
    public func monthly(in currency: String) -> Double? {
        if let v = monthlyConverted?[currency] { return v }
        let values = (items ?? []).filter { $0.active != false }.compactMap { $0.monthlyConverted?[currency] }
        return values.isEmpty ? nil : values.reduce(0, +)
    }
}

extension HubAPI {
    public func subscriptionRecords() async throws -> [SubscriptionRecord] {
        struct Page: Decodable { var items: [SubscriptionRecord]; var nextOffset: Int? }
        var result: [SubscriptionRecord] = [], offset = 0
        while true {
            let page = try await subscriptionPage(Page.self, offset: offset)
            result += page.items
            guard let next = page.nextOffset else { return result }
            guard next > offset else { throw HubError.invalidResponse }
            offset = next
        }
    }
}
