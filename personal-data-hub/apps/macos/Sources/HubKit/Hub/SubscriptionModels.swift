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
    }
    public struct Reading: Codable, Equatable, Sendable {
        public var windows: [Window]
        public var observedAt: Date
        public var expiresAt: Date?
    }
    public var reading: Reading?
    public var status: String
    public var stale: Bool
    public var error: String?
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
    public var billingRegion: String?
    public var cycle: String?
    public var frequency: Int = 1
    public var nextRenewal: String?
    public var renewalDay: Int?
    public var expiresOn: String?
    public var payer: String = "unknown"
    public var autoRenew: Bool = false
    public var active: Bool = true
    public var note: String = ""
    public var binding: SubscriptionBinding?
    public var quota: SubscriptionQuota?
    public var priceConverted: [String: String]?
    public var exchangeRateDate: String?
    public var exchangeRateStale: Bool?

    public init() {}

    public var document: [String: Any] {
        var result: [String: Any] = ["name": name,
            "service_key": serviceKey as Any? ?? NSNull(), "theme_color": themeColor as Any? ?? NSNull(),
            "subscription_url": subscriptionUrl as Any? ?? NSNull(), "account_label": accountLabel, "category": category,
            "plan": plan, "price": price as Any? ?? NSNull(), "currency": currency,
            "billing_region": billingRegion as Any? ?? NSNull(), "renewal_day": renewalDay as Any? ?? NSNull(),
            "cycle": cycle as Any? ?? NSNull(), "frequency": frequency,
            "next_renewal": nextRenewal as Any? ?? NSNull(), "expires_on": expiresOn as Any? ?? NSNull(),
            "payer": payer, "auto_renew": autoRenew, "active": active, "note": note]
        if let binding {
            result["binding"] = ["collector": binding.collector, "provider": binding.provider,
                "account": binding.account, "account_email": binding.accountEmail ?? "", "profile": binding.profile ?? ""]
        } else { result["binding"] = NSNull() }
        return result
    }
}

public struct SubscriptionExchangeRates: Codable, Equatable, Sendable {
    public var observedAt: Date?
    public var sourceUrl: String?
    public var stale: Bool?
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
