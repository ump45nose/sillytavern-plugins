import Foundation
import Testing
@testable import HubKit

private func api(_ hub: ScriptedHub) -> HubAPI {
    HubAPI(transport: hub, credential: HubCredential(baseURL: URL(string: "http://hub.test")!, token: "t"))
}

private func item(_ id: String, _ name: String, key: String? = nil) -> SubsData.Item {
    SubsData.Item(id: id, name: name, serviceKey: key)
}

@Test func accountsOfOneProductGroupByServiceKeyThenName() {
    let groups = SubsProduct.group([item("a", "Claude", key: "claude"), item("b", "ChatGPT"), item("c", "Claude Pro", key: "claude"),
                                    item("d", "ChatGPT "), item("e", "Claude")])
    #expect(groups.map { $0.items.map(\.id) } == [["a", "c"], ["b", "d"], ["e"]])
    #expect(groups[0].lead.name == "Claude")
}

@Test func newFieldsDecodeAndConvertedTotalsPreferTheHub() throws {
    let json = #"""
    {"items": [
      {"id": "1", "name": "ChatGPT", "price": 1950, "currency": "INR", "cycle": "year", "billing_region": "印度",
       "price_converted": {"CNY": 165.1, "USD": 23.2}, "monthly_converted": {"CNY": 13.8, "USD": 1.9},
       "exchange_rate_date": "2026-10-23", "exchange_rate_stale": false, "quota_url_configured": false, "active": true,
       "binding": {"collector": "subboost", "provider": "network", "account": "x", "account_email": "", "profile": ""},
       "quota": {"status": "error", "stale": true, "error": {"code": "unreachable", "message": "订阅链接无法访问"}, "reading": null}},
      {"id": "2", "name": "Off", "active": false, "monthly_converted": {"CNY": 50, "USD": 7}}
    ],
    "monthly_by_currency": {"INR": 162.5}, "unconverted_currencies": ["BOB"],
    "exchange_rates": {"base": "USD", "stale": false, "error": null, "rates": {"USD": "1", "CNY": "7.12", "INR": "84"}}}
    """#
    var data = try HubJSON.decoder.decode(SubsData.self, from: Data(json.utf8))
    let s = try #require(data.items?.first)
    #expect(s.billingRegion == "印度" && s.priceConverted?["CNY"] == 165.1 && s.binding?.collector == "subboost")
    #expect(s.quota?.error == "订阅链接无法访问" && s.quota?.status == "error")
    #expect(data.unconvertedCurrencies == ["BOB"])
    #expect(data.monthly(in: "CNY") == 13.8)
    data.monthlyConverted = ["CNY": 99]
    #expect(data.monthly(in: "CNY") == 99)
    let rates = try #require(data.exchangeRates)
    #expect(abs(rates.convert(10, from: "USD", to: "CNY")! - 71.2) < 0.001)
    #expect(abs(rates.convert(84, from: "INR", to: "USD")! - 1) < 0.001)
    #expect(rates.convert(1, from: "BOB", to: "CNY") == nil)
}

@Test func quotaErrorAsPlainTextStillDecodes() throws {
    let q = try HubJSON.decoder.decode(SubscriptionQuota.self, from: Data(#"{"status": "error", "stale": false, "error": "timeout"}"#.utf8))
    #expect(q.error == "timeout" && q.reading == nil)
}

@Test func billingRegionIsSavedAndBlankClearsIt() async throws {
    let hub = ScriptedHub { r in
        r.httpMethod == "PATCH" && r.url!.path == "/api/v1/subscriptions/records/s1"
            ? (200, #"{"id": "s1", "version": 5, "name": "机场", "account_label": "", "category": "network", "plan": "", "currency": "CNY", "frequency": 1, "payer": "self", "auto_renew": false, "active": true, "note": "", "billing_region": "美国"}"#)
            : (404, "{}")
    }
    var r = SubscriptionRecord()
    r.id = "s1"; r.version = 4; r.name = "机场"; r.category = "network"; r.billingRegion = "  "
    #expect(r.document["billing_region"] is NSNull)
    #expect(r.document["quota_url"] == nil)
    r.billingRegion = "美国"
    let saved = try await api(hub).saveSubscription(r)
    #expect(hub.requests.last?.body?["billing_region"] as? String == "美国")
    #expect(saved.billingRegion == "美国" && saved.version == 5)
}
