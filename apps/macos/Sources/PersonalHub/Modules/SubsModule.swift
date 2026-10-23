import AppKit
import HubKit
import SwiftUI

// MARK: - 订阅

/// Compact: the monthly spend converted to ¥ or $, the next renewal and the tightest quota.
/// Detail: the converted total and the original currencies, who pays, the next 30 days of renewals, and the
/// list by category with each product's accounts together, edited in place.
struct SubsModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state
    @AppStorage(Subs.targetKey) private var target = "CNY"
    @ViewState private var adding = false

    var body: some View {
        HubGate(envelope: state.hub.data.subs, unconfigured: "独立订阅服务尚未接入") { s in
            if size == .compact { compact(s) } else { SubsDetail(data: s) }
        }
    }

    private func compact(_ data: SubsData) -> some View {
        let items = (data.items ?? []).filter(Subs.active)
        let total = data.monthly(in: target), other = Subs.other(target)
        let next = items.filter { Subs.days($0).map { $0 >= 0 } ?? false }.min { Subs.days($0)! < Subs.days($1)! }
        let tight = Subs.tightest(items)
        let unknown = items.filter { ($0.payer ?? "unknown") == "unknown" }.count
        let currencies = Set(items.compactMap(\.currency)).count
        let meta: [String?] = [data.monthly(in: other).map { "≈ " + Subs.approx($0, other) }, currencies > 1 ? "\(currencies) 种货币" : nil,
                               Subs.rateDate(items).map { "汇率 " + $0 }]
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(total.map { Subs.approx($0, target) } ?? "—").font(Typo.serif(30)).tracking(-0.5).monospacedDigit()
                Text("/ 月 · 折合").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                Spacer()
                Button { adding = true } label: {
                    Image(systemName: "plus").font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.ink3)
                        .frame(width: 24, height: 22).contentShape(Rectangle())
                }
                .buttonStyle(.plain).help("新增订阅")
                .popover(isPresented: $adding, arrowEdge: .bottom) {
                    SubEditCard(item: nil, close: { adding = false }).frame(width: 640).padding(4).environment(state)
                }
            }
            (Text(meta.compactMap { $0 }.joined(separator: " · ")).foregroundStyle(Palette.ink3)
             + Text(unknown > 0 ? " · \(unknown) 项待确认" : "").foregroundStyle(Subs.warn))
                .font(Typo.sans(11.5)).lineLimit(1)
                .padding(.top, 3)
            Spacer(minLength: 8)
            if let next {
                HStack(spacing: 8) {
                    SubLogo(name: next.name, size: 20, iconURL: next.iconUrl, themeColor: next.themeColor)
                    Text(next.name + ((next.accountLabel ?? "").isEmpty ? "" : " · " + next.accountLabel!)).font(Typo.sans(12.5)).lineLimit(1)
                    Spacer(minLength: 4)
                    RenewBadge(text: Subs.renewText(next) + (next.price.map { $0 > 0 ? " · " + Subs.money($0, next.currency ?? "CNY") : "" } ?? ""),
                               soon: (Subs.days(next) ?? .max) <= 7)
                }
            }
            if let tight {
                HStack(spacing: 8) {
                    Text(tight.item.name.split(separator: " ").first.map(String.init).map { $0 + " · " + tight.window.label } ?? tight.window.label)
                        .font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1).fixedSize()
                    Track(value: tight.percent, color: Subs.quotaTone(tight.percent).color, height: 4)
                    Text("\(Int(tight.percent.rounded()))%").font(Typo.sans(11)).foregroundStyle(Palette.ink2).monospacedDigit()
                }
                .padding(.top, 8)
            }
        }
    }
}

/// Formatting and sums shared by the subscription cards.
enum Subs {
    static let categories: [(String, String)] = [("ai", "AI"), ("network", "网络"), ("membership", "会员"), ("other", "其他")]
    static let payers: [(String, String)] = [("self", "个人"), ("company", "公司"), ("other", "其他"), ("none", "免费"), ("unknown", "待确认")]
    static let cycles: [(String, String)] = [("month", "月"), ("year", "年"), ("week", "周"), ("day", "天"), ("one_time", "一次性")]
    static let currencies = ["CNY", "USD"]
    /// Offered under 付费区域 after the ones already in use.
    static let regions = ["中国", "美国", "印度", "土耳其", "尼日利亚", "巴基斯坦", "阿根廷", "埃及"]
    /// Which currency the totals are converted to: CNY or USD.
    static let targetKey = "subs.convertTo"
    static let warn = Color(hex: "#9A7414")

    static func active(_ s: SubsData.Item) -> Bool { s.active != false }

    static func other(_ target: String) -> String { target == "USD" ? "CNY" : "USD" }

    /// CNY, then USD, then the rest.
    static func order(_ currency: String) -> Int { ["CNY": 0, "USD": 1][currency] ?? 2 }

    /// "¥855", "$23", "$3.5": whole numbers from 10 up.
    static func approx(_ amount: Double, _ currency: String) -> String {
        symbol(currency) + Fmt.number(amount, amount >= 10 || amount == 0 ? 0 : 1)
    }

    /// "≈ ¥167 · $23", leaving out the item's own currency.
    static func converted(_ values: [String: Double]?, from currency: String?) -> String? {
        let parts = ["CNY", "USD"].filter { $0 != currency }.compactMap { c in values?[c].map { approx($0, c) } }
        return parts.isEmpty ? nil : "≈ " + parts.joined(separator: " · ")
    }

    /// The newest rate date among the items, as M/D.
    static func rateDate(_ items: [SubsData.Item]) -> String? {
        items.compactMap(\.exchangeRateDate).max().flatMap(HubFormat.day).map(HubFormat.md)
    }

    /// Traffic in GB for byte windows; the rest as numbers with their unit.
    static func amount(_ v: Double, unit: String?) -> String {
        unit == "bytes" ? HubFormat.gb(v, v >= 10 * 1_073_741_824 ? 0 : 1) : Fmt.number(v, 0)
    }

    static func category(_ key: String?) -> String { categories.first { $0.0 == key }?.1 ?? "其他" }

    static func tone(_ category: String?) -> Tone {
        switch category {
        case "ai": .clay
        case "network": .olive
        case "membership": .sky
        default: .steel
        }
    }

    /// The label a row shows for who pays; personal payment is the default and shows nothing.
    static func payerLabel(_ payer: String?) -> (String, Tone)? {
        switch payer ?? "unknown" {
        case "self": nil
        case "company": ("公司付", .sky)
        case "other": ("其他付款方", .plum)
        case "none": ("免费", .sage)
        default: ("付款方待确认", .ochre)
        }
    }

    static func payerTone(_ payer: String) -> Color {
        switch payer {
        case "self": Palette.ink2
        case "company": Tone.sky.color
        case "other": Tone.plum.color
        case "none": Tone.sage.color
        default: Tone.ochre.color
        }
    }

    static func symbol(_ currency: String) -> String {
        ["CNY": "¥", "USD": "$", "EUR": "€", "GBP": "£", "HKD": "HK$", "JPY": "JP¥", "INR": "₹", "TRY": "₺", "NGN": "₦",
         "BOB": "Bs ", "PKR": "Rs ", "ARS": "AR$", "EGP": "E£", "BRL": "R$", "KRW": "₩"][currency] ?? currency + " "
    }

    static func money(_ amount: Double, _ currency: String) -> String {
        symbol(currency) + Fmt.number(amount, amount.rounded() == amount || amount >= 100 ? 0 : 2)
    }

    /// In the item's own currency; nil for one-time, unpriced or stopped subscriptions.
    static func monthly(_ s: SubsData.Item) -> Double? {
        guard active(s), let price = s.price else { return nil }
        let every = Double(max(s.frequency ?? 1, 1))
        switch s.cycle {
        case "day": return price * 30.44 / every
        case "week": return price * 4.345 / every
        case "month": return price / every
        case "year": return price / 12 / every
        default: return nil
        }
    }

    static func totals(_ items: [SubsData.Item], payer: String? = nil) -> [String: Double] {
        var out: [String: Double] = [:]
        for s in items where payer == nil || (s.payer ?? "unknown") == payer {
            guard let m = monthly(s), m > 0 else { continue }
            out[s.currency ?? "CNY", default: 0] += m
        }
        return out
    }

    /// RMB when there is any, otherwise the largest.
    static func mainCurrency(_ totals: [String: Double]) -> String? {
        totals["CNY"] != nil ? "CNY" : totals.max { $0.value < $1.value }?.key
    }

    static func cycleText(_ s: SubsData.Item) -> String {
        guard let cycle = s.cycle else { return "周期未设置" }
        if cycle == "one_time" { return "一次性" }
        let unit = cycles.first { $0.0 == cycle }?.1 ?? cycle
        let every = s.frequency ?? 1
        return every > 1 ? "每 \(every) \(unit)" : "每\(unit)"
    }

    static func priceText(_ s: SubsData.Item) -> String {
        guard let price = s.price else { return "金额未知" }
        return price == 0 ? "免费" : money(price, s.currency ?? "CNY")
    }

    static func days(_ s: SubsData.Item) -> Int? {
        HubFormat.day(s.nextRenewal ?? s.expiresOn).flatMap {
            Calendar.hub.dateComponents([.day], from: Calendar.hub.startOfDay(for: HubFormat.current()), to: $0).day
        }
    }

    static func renewText(_ s: SubsData.Item) -> String {
        guard let d = days(s), let date = HubFormat.day(s.nextRenewal ?? s.expiresOn) else {
            return s.cycle == "one_time" && s.expiresOn == nil ? (s.plan == "永久会员" ? "永久" : "一次性") : "—"
        }
        let action = s.nextRenewal == nil ? "到期" : "续费"
        switch d {
        case ..<0: return "已过期"
        case 0: return "今天" + action
        case 1: return "明天" + action
        case ...7: return "\(d) 天后"
        default: return HubFormat.md(date)
        }
    }

    static func percent(_ w: SubscriptionQuota.Window) -> Double? {
        if let p = w.usedPercent { return p }
        if let used = w.used, let limit = w.limit, limit > 0 { return used / limit * 100 }
        return nil
    }

    static func quotaTone(_ percent: Double) -> Tone { percent >= 90 ? .rose : percent >= 75 ? .ochre : .clay }

    /// The fullest fresh quota window across all subscriptions.
    static func tightest(_ items: [SubsData.Item]) -> (item: SubsData.Item, window: SubscriptionQuota.Window, percent: Double)? {
        items.flatMap { s in
            (s.quota?.stale == false ? s.quota?.reading?.windows ?? [] : []).compactMap { w in percent(w).map { (item: s, window: w, percent: $0) } }
        }
        .max { $0.percent < $1.percent }
    }

    /// "2:10" under a day, then "4 天".
    static func resets(_ date: Date?) -> String? {
        guard let date else { return nil }
        let s = date.timeIntervalSince(HubFormat.current())
        guard s > 0 else { return nil }
        if s < 86_400 { return "\(Int(s / 3600)):" + String(format: "%02d", Int(s.truncatingRemainder(dividingBy: 3600) / 60)) }
        return "\(Int((s / 86_400).rounded(.up))) 天"
    }

    static func ago(_ date: Date) -> String {
        let s = HubFormat.current().timeIntervalSince(date)
        if s < 3600 { return "\(max(1, Int(s / 60))) 分钟前" }
        if s < 86_400 { return "\(Int(s / 3600)) 小时前" }
        return "\(Int(s / 86_400)) 天前"
    }
}

// MARK: - Detail

private struct SubsDetail: View {
    var data: SubsData
    @Environment(AppState.self) private var state
    @AppStorage(Subs.targetKey) private var target = "CNY"
    @ViewState private var category: String?
    @ViewState private var unknownOnly = false
    /// Item id being edited, or `""` for a new one.
    @ViewState private var editing: String?
    @ViewState private var folded: Set<String> = []
    @ViewState private var width: CGFloat = 1000

    private var items: [SubsData.Item] { data.items ?? [] }
    private var narrow: Bool { width < 900 }

    var body: some View {
        let live = items.filter(Subs.active)
        let shown = items.filter { s in
            (category == nil || (s.category ?? "other") == category) && (!unknownOnly || (s.payer ?? "unknown") == "unknown")
        }
        VStack(alignment: .leading, spacing: 0) {
            summary(live)
            SectionTitle("未来 30 天续费").padding(.top, 16)
            SubsRenewals(items: live) { id in withAnimation(Motion.spring) { editing = id } }
            HStack(spacing: 6) {
                chip("全部 \(items.count)", on: category == nil && !unknownOnly) { category = nil; unknownOnly = false }
                ForEach(Subs.categories, id: \.0) { key, name in
                    let n = items.filter { ($0.category ?? "other") == key }.count
                    if n > 0 { chip("\(name) \(n)", on: category == key) { category = category == key ? nil : key } }
                }
                if unknownOnly { chip("付款方待确认 ✕", on: true) { unknownOnly = false } }
                Spacer()
                Text("按下次续费排序").font(Typo.sans(11)).foregroundStyle(Palette.ink4)
            }
            .padding(.top, 14).padding(.bottom, 4)
            if editing == "" {
                SubEditCard(item: nil, close: { withAnimation(Motion.spring) { editing = nil } })
                    .padding(.vertical, 8)
                    .transition(.opacity.combined(with: .offset(y: -6)))
            }
            ForEach(groups(shown), id: \.0) { title, products in
                Text("\(title) · \(products.reduce(0) { $0 + $1.items.count })").font(Typo.sans(11, .semibold)).foregroundStyle(Palette.ink3)
                    .padding(.leading, 12).padding(.top, 12).padding(.bottom, 2)
                ForEach(products) { p in
                    if p.items.count > 1 {
                        let open = !folded.contains(p.id) || p.items.contains { $0.id == editing }
                        ProductRow(product: p, open: open)
                            .opacity(editing == nil ? 1 : 0.4)
                            .contentShape(Rectangle())
                            .onTapGesture { withAnimation(Motion.spring) { if open { folded.insert(p.id) } else { folded.remove(p.id) } } }
                        if open {
                            ForEach(p.items) { account($0, nested: true) }
                                .transition(.opacity.combined(with: .move(edge: .top)))
                        }
                    } else {
                        account(p.lead, nested: false)
                    }
                }
            }
            if shown.isEmpty {
                Text(items.isEmpty ? "还没有订阅，点「新增订阅」记下第一项" : "这个分类下没有订阅").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
                    .frame(maxWidth: .infinity).padding(.vertical, 24)
            }
        }
        .environment(\.subsNarrow, narrow)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
    }

    @ViewBuilder private func account(_ s: SubsData.Item, nested: Bool) -> some View {
        if editing == s.id {
            SubEditCard(item: s, close: { withAnimation(Motion.spring) { editing = nil } })
                .padding(.vertical, 8)
                .transition(.asymmetric(insertion: .opacity.combined(with: .scale(scale: 0.98, anchor: .top)), removal: .opacity))
        } else {
            SubRow(item: s, nested: nested)
                .opacity(editing == nil ? (Subs.active(s) ? 1 : 0.6) : 0.4)
                .contentShape(Rectangle())
                .onTapGesture { withAnimation(Motion.spring) { editing = s.id } }
                .transition(.opacity)
        }
    }

    /// The converted total leads; the original currencies, the rate date and the ¥/$ switch sit beside it.
    private func summary(_ live: [SubsData.Item]) -> some View {
        let other = Subs.other(target)
        let split = [("self", "个人付"), ("company", "公司付"), ("unknown", "待确认")].compactMap { key, name -> String? in
            let v = live.filter { ($0.payer ?? "unknown") == key }.compactMap { $0.monthlyConverted?[target] }.reduce(0, +)
            return v > 0 ? name + " " + Subs.approx(v, target) : nil
        }
        let originals = (data.monthlyByCurrency ?? Subs.totals(live)).filter { $0.value > 0 }
            .sorted { (Subs.order($0.key), $0.key) < (Subs.order($1.key), $1.key) }
        let stale = data.exchangeRates?.stale == true || live.contains { $0.exchangeRateStale == true }
        let unconverted = data.unconvertedCurrencies ?? []
        let counts = Subs.payers.map { key, name in (key, name, live.filter { ($0.payer ?? "unknown") == key }.count) }.filter { $0.2 > 0 }
        let total = max(counts.reduce(0) { $0 + $1.2 }, 1)
        let totalBlock = VStack(alignment: .leading, spacing: 4) {
            Label11("每月 · 折合")
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(data.monthly(in: target).map { Subs.approx($0, target) } ?? "—").font(Typo.serif(38)).tracking(-0.8).monospacedDigit()
                    .contentTransition(.numericText())
                Text("/ 月").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
            Text(([data.monthly(in: other).map { "≈ " + Subs.approx($0, other) }] + split).compactMap { $0 }.joined(separator: " · "))
                .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit().contentTransition(.numericText())
        }
        .fixedSize()
        .animation(Motion.spring, value: target)
        let originalsBlock = VStack(alignment: .leading, spacing: 6) {
            Label11("按原币种")
            HStack(spacing: 5) {
                ForEach(originals, id: \.key) { c, v in Chip(text: Subs.money(v, c)) }
            }
            HStack(spacing: 6) {
                if let date = Subs.rateDate(live) {
                    Text(stale ? "汇率 \(date) · 可能过期" : "汇率 \(date)").foregroundStyle(stale ? Subs.warn : Palette.ink3)
                        .help(stale ? "hub 没能更新汇率，折合金额按旧汇率算" : "折合按这天的汇率")
                }
                Segmented(options: [("CNY", "¥"), ("USD", "$")], selection: $target, small: true).fixedSize()
                if !unconverted.isEmpty {
                    Text(unconverted.joined(separator: "、") + " 未折算").foregroundStyle(Subs.warn).help("没有这些货币的汇率，折合总额里不含它们")
                }
            }
            .font(Typo.sans(11))
        }
        .fixedSize()
        let payerBlock = VStack(alignment: .leading, spacing: 5) {
            Label11("付款方")
            GeometryReader { g in
                HStack(spacing: 2) {
                    ForEach(counts, id: \.0) { key, _, n in
                        RoundedRectangle(cornerRadius: 2.5).fill(Subs.payerTone(key))
                            .frame(width: max(4, (g.size.width - CGFloat(counts.count - 1) * 2) * CGFloat(n) / CGFloat(total)))
                    }
                }
            }
            .frame(height: 7)
            HStack(spacing: 10) {
                ForEach(counts, id: \.0) { key, name, n in
                    if key == "unknown" {
                        Button { withAnimation(Motion.spring) { unknownOnly.toggle(); category = nil } } label: {
                            Text("\(name) \(n)").underline(unknownOnly)
                        }
                        .buttonStyle(.plain).foregroundStyle(Subs.warn).help("只看付款方待确认的订阅")
                    } else {
                        Text("\(name) \(n)").foregroundStyle(key == "self" ? Palette.ink3 : Subs.payerTone(key))
                    }
                }
            }
            .font(Typo.sans(11)).monospacedDigit()
        }
        .frame(width: 210)
        let add = Button { withAnimation(Motion.spring) { editing = "" } } label: { Label("新增订阅", systemImage: "plus") }
            .buttonStyle(.hubSecondary)
            .disabled(editing == "")
        return Group {
            if narrow {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .bottom, spacing: 20) {
                        totalBlock
                        Spacer(minLength: 0)
                        add
                    }
                    HStack(alignment: .bottom, spacing: 20) {
                        if !originals.isEmpty { originalsBlock }
                        Spacer(minLength: 0)
                        if !counts.isEmpty { payerBlock }
                    }
                }
            } else {
                HStack(alignment: .bottom, spacing: 28) {
                    totalBlock
                    if !originals.isEmpty { originalsBlock }
                    Spacer(minLength: 0)
                    if !counts.isEmpty { payerBlock }
                    add
                }
            }
        }
    }

    private func chip(_ text: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button { withAnimation(Motion.spring, action) } label: {
            Text(text).font(Typo.sans(11.5, on ? .semibold : .regular)).foregroundStyle(on ? Palette.ink : Palette.ink2)
                .padding(.horizontal, 10).frame(height: 24)
                .background(Capsule().fill(on ? Palette.card : Palette.sunk))
                .overlay(Capsule().strokeBorder(on ? Palette.line : .clear))
        }
        .buttonStyle(.plain)
    }

    /// By category in the fixed order, products by their soonest renewal; stopped subscriptions last on their own.
    private func groups(_ shown: [SubsData.Item]) -> [(String, [SubsProduct])] {
        let order = { (s: SubsData.Item) in Subs.days(s).map { $0 < 0 ? 10_000 - $0 : $0 } ?? 20_000 }
        let live = shown.filter(Subs.active)
        var out = Subs.categories.compactMap { key, name -> (String, [SubsProduct])? in
            let group = live.filter { ($0.category ?? "other") == key }.sorted { order($0) < order($1) }
            return group.isEmpty ? nil : (name, SubsProduct.group(group))
        }
        let stopped = shown.filter { !Subs.active($0) }
        if !stopped.isEmpty { out.append(("已停用", SubsProduct.group(stopped.sorted { $0.name < $1.name }))) }
        return out
    }
}

private struct SubsNarrowKey: EnvironmentKey { static let defaultValue = false }

extension EnvironmentValues {
    /// Subscription rows put the quota bars under the name instead of in their own column.
    fileprivate var subsNarrow: Bool {
        get { self[SubsNarrowKey.self] }
        set { self[SubsNarrowKey.self] = newValue }
    }
}

/// A product with several accounts: the count, their plans, the combined monthly spend and the soonest renewal.
private struct ProductRow: View {
    var product: SubsProduct
    var open: Bool
    @AppStorage(Subs.targetKey) private var target = "CNY"
    @Environment(\.subsNarrow) private var narrow
    @ViewState private var hovering = false

    var body: some View {
        let lead = product.lead, items = product.items
        let currencies = Set(items.map { $0.currency ?? "CNY" }), cycles = Set(items.map { $0.cycle ?? "" })
        let same = currencies.count == 1 && cycles.count == 1 && items.allSatisfy { $0.price != nil }
        let next = items.filter { Subs.days($0).map { $0 >= 0 } ?? false }.min { Subs.days($0)! < Subs.days($1)! } ?? lead
        HStack(alignment: .center, spacing: 14) {
            SubLogo(name: lead.name, size: 30, iconURL: lead.iconUrl, themeColor: lead.themeColor)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(lead.name).font(Typo.sans(13.5, .semibold)).lineLimit(1)
                    Chip(text: "\(items.count) 个账号")
                }
                Text(items.compactMap { $0.plan.flatMap { $0.isEmpty ? nil : $0 } }.joined(separator: " · "))
                    .font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
            }
            .frame(maxWidth: narrow ? .infinity : 250, alignment: .leading)
            if !narrow {
                Text(items.contains { !($0.quota?.reading?.windows ?? []).isEmpty } ? "额度见各账号" : "")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink4).frame(maxWidth: .infinity, alignment: .leading)
            }
            if same {
                let sum = items.compactMap(\.price).reduce(0, +)
                let converted = ["CNY", "USD"].reduce(into: [String: Double]()) { out, c in
                    let v = items.compactMap { $0.priceConverted?[c] }
                    if v.count == items.count { out[c] = v.reduce(0, +) }
                }
                SubMoney(main: Subs.money(sum, lead.currency ?? "CNY"),
                         sub: ([Subs.cycleText(lead)] + [Subs.converted(converted, from: lead.currency)]).compactMap { $0 }.joined(separator: " · "))
            } else {
                let v = items.compactMap { $0.monthlyConverted?[target] }.reduce(0, +)
                SubMoney(main: Subs.approx(v, target), sub: "每月 · 折合")
            }
            SubWhen(item: next)
            Image(systemName: "chevron.down").font(.system(size: 10, weight: .semibold)).foregroundStyle(Palette.ink3)
                .rotationEffect(.degrees(open ? 180 : 0)).frame(width: 20)
                .animation(Motion.spring, value: open)
        }
        .padding(.horizontal, 12).padding(.vertical, 11)
        .background(RoundedRectangle(cornerRadius: 10).fill(hovering ? Palette.sunk : .clear))
        .animation(.easeOut(duration: 0.15), value: hovering)
        .onHover { hovering = $0 }
    }
}

/// The original amount large, its cycle and the conversion small.
private struct SubMoney: View {
    var main: String
    var sub: String
    var size: CGFloat = 16
    @Environment(\.subsNarrow) private var narrow

    var body: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(main).font(Typo.serif(size)).monospacedDigit().lineLimit(1)
            Text(sub).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit().lineLimit(1).minimumScaleFactor(0.85)
        }
        .frame(width: narrow ? 124 : 150, alignment: .trailing)
    }
}

private struct SubWhen: View {
    var item: SubsData.Item

    var body: some View {
        VStack(alignment: .trailing, spacing: 2) {
            let d = Subs.days(item)
            if let d, d <= 7 {
                RenewBadge(text: Subs.renewText(item), soon: true)
                if let date = HubFormat.day(item.nextRenewal ?? item.expiresOn) { Text(HubFormat.md(date)).font(Typo.sans(10.5)).foregroundStyle(Palette.ink3) }
            } else {
                Text(Subs.renewText(item)).font(Typo.sans(12)).foregroundStyle(Palette.ink2).monospacedDigit()
                if let d { Text(item.nextRenewal == nil ? "到期" : "\(d) 天后").font(Typo.sans(10.5)).foregroundStyle(Palette.ink3) }
            }
        }
        .frame(width: 70, alignment: .trailing)
    }
}

/// Each charge in the next 30 days as a dot on a line, coloured by category; labels alternate rows to stay apart.
private struct SubsRenewals: View {
    var items: [SubsData.Item]
    var pick: (String) -> Void

    var body: some View {
        let marks = Self.marks(items)
        VStack(spacing: 0) {
            if marks.isEmpty {
                Text("30 天内没有续费").font(Typo.sans(11.5)).foregroundStyle(Palette.ink4).frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            } else {
                GeometryReader { g in
                    let w = g.size.width
                    ZStack(alignment: .topLeading) {
                        Rectangle().fill(Palette.line).frame(width: w, height: 1).offset(y: 54)
                        ForEach(marks, id: \.item.id) { m in
                            let x = min(max(CGFloat(m.day) / 30 * w, 4), w - 4)
                            Button { pick(m.item.id) } label: {
                                VStack(spacing: 3) {
                                    Text(m.label).font(Typo.sans(10.5)).foregroundStyle(Palette.ink2).lineLimit(1).fixedSize()
                                    Rectangle().fill(Palette.line).frame(width: 1, height: 8 + CGFloat(m.row) * 14)
                                    Circle().fill(Subs.tone(m.item.category).color).frame(width: 8, height: 8)
                                        .overlay(Circle().strokeBorder(Palette.card, lineWidth: 1.5))
                                }
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .help("\(m.item.name)\((m.item.accountLabel ?? "").isEmpty ? "" : " · " + (m.item.accountLabel ?? "")) · \(Subs.renewText(m.item))")
                            .alignmentGuide(.leading) { d in d.width / 2 - x }
                            .alignmentGuide(.top) { d in d.height - 58 }
                        }
                    }
                }
                .frame(height: 60)
            }
            HStack(spacing: 0) {
                ForEach([0, 7, 14, 21, 30], id: \.self) { d in
                    Text(d == 0 ? "今天" : HubFormat.md(Calendar.hub.date(byAdding: .day, value: d, to: HubFormat.current())!))
                        .font(Typo.sans(10)).foregroundStyle(Palette.ink4).monospacedDigit()
                    if d < 30 { Spacer(minLength: 0) }
                }
            }
            .padding(.top, 4)
        }
    }

    struct Mark { var item: SubsData.Item; var day: Int; var label: String; var row: Int }

    static func marks(_ items: [SubsData.Item]) -> [Mark] {
        var last = [-100, -100, -100], out: [Mark] = []
        for s in items.filter({ $0.nextRenewal != nil }).sorted(by: { (Subs.days($0) ?? 99) < (Subs.days($1) ?? 99) }) {
            guard let d = Subs.days(s), (0...30).contains(d) else { continue }
            let name = s.name.count > 10 ? String(s.name.prefix(9)) + "…" : s.name
            let label = name + (s.price.map { $0 > 0 ? " " + Subs.money($0, s.currency ?? "CNY") : "" } ?? "")
            let row = last.firstIndex { d - $0 >= 4 } ?? last.indices.min { last[$0] < last[$1] }!
            last[row] = d
            out.append(Mark(item: s, day: d, label: label, row: row))
        }
        return out
    }
}

/// One subscription: on its own as a product row, or `nested` under a product as one of its accounts.
private struct SubRow: View {
    var item: SubsData.Item
    var nested = false
    @Environment(\.subsNarrow) private var narrow
    @ViewState private var hovering = false

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            if nested { Color.clear.frame(width: 30, height: 1) } else {
                SubLogo(name: item.name, size: 30, iconURL: item.iconUrl, themeColor: item.themeColor)
            }
            if narrow {
                VStack(alignment: .leading, spacing: 8) {
                    Group { if nested { who } else { title } }
                    quotas
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Group { if nested { who } else { title } }
                    .frame(width: 250, alignment: .leading)
                quotas.frame(maxWidth: .infinity, alignment: .leading)
            }
            SubMoney(main: Subs.priceText(item),
                     sub: ([Subs.cycleText(item)] + [Subs.converted(item.priceConverted, from: item.currency)]).compactMap { $0 }.joined(separator: " · "),
                     size: nested ? 15 : 16)
            SubWhen(item: item)
            Image(systemName: "ellipsis").font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.ink3).frame(width: 20)
        }
        .padding(.horizontal, 12).padding(.vertical, nested ? 8 : 11)
        .background(RoundedRectangle(cornerRadius: 10).fill(hovering ? Palette.sunk : .clear))
        .animation(.easeOut(duration: 0.15), value: hovering)
        .onHover { hovering = $0 }
    }

    @ViewBuilder private var quotas: some View {
        let windows = Array((item.quota?.reading?.windows ?? []).prefix(2))
        VStack(alignment: .leading, spacing: 7) {
            if windows.isEmpty, let note = quotaNote {
                Text(note).font(Typo.sans(12)).foregroundStyle(Palette.ink4).lineLimit(2)
            }
            ForEach(windows) { w in quota(w) }
        }
    }

    /// Name with region, link state and payer beside it; account, plan and renewal below.
    private var title: some View {
        let meta = [item.accountLabel, item.plan, item.cycle == "one_time" ? nil : item.autoRenew == false ? "自动续费关" : nil]
            .compactMap { $0.flatMap { $0.isEmpty ? nil : $0 } }
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(item.name).font(Typo.sans(13.5, .semibold)).lineLimit(1)
                if let region = item.billingRegion, !region.isEmpty { Chip(text: region) }
                if let (text, tone) = Subs.payerLabel(item.payer) { Chip(text: text, tone: tone) }
            }
            if !meta.isEmpty { Text(meta.joined(separator: " · ")).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
        }
    }

    private var who: some View {
        HStack(spacing: 5) {
            Text(item.accountLabel.flatMap { $0.isEmpty ? nil : $0 } ?? "未命名账号").font(Typo.sans(12.5)).lineLimit(1)
            if let plan = item.plan, !plan.isEmpty { Chip(text: plan) }
            if let (text, tone) = Subs.payerLabel(item.payer) { Chip(text: text, tone: tone) }
            if let region = item.billingRegion, !region.isEmpty { Chip(text: region) }
        }
    }

    private var quotaNote: String? {
        guard let q = item.quota else {
            return item.category == "network" ? "暂无流量数据" : item.category == "ai" ? "没有绑定额度来源" : nil
        }
        if q.status == "error" || q.error != nil { return item.category == "network" ? "流量获取失败" : "额度获取失败" }
        return q.stale ? "额度读数已过期" : "暂无额度窗口"
    }

    private func quota(_ w: SubscriptionQuota.Window) -> some View {
        let stale = item.quota?.stale ?? false
        let pct = Subs.percent(w)
        let value: String = {
            if let used = w.used, let limit = w.limit, w.usedPercent == nil || w.unit == "bytes" {
                return "\(Subs.amount(used, unit: w.unit)) / \(Subs.amount(limit, unit: w.unit)) \(w.unit == "bytes" ? "GB" : w.unit ?? "")"
            }
            if let pct { return "\(Int(pct.rounded()))%" }
            if let r = w.remaining { return "剩 \(Subs.amount(r, unit: w.unit)) \(w.unit == "bytes" ? "GB" : w.unit ?? "")" }
            return "上限未知"
        }()
        let tail = stale ? Subs.ago(w.observedAt) : Subs.resets(w.resetsAt)
        let tone = item.category == "network" && (pct ?? 0) < 75 ? Tone.olive : Subs.quotaTone(pct ?? 0)
        return HStack(spacing: 10) {
            Text(w.label).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1).frame(width: 64, alignment: .leading)
            Track(value: pct ?? 0, color: stale ? Palette.ink4 : tone.color, height: 6)
                .frame(minWidth: 80, maxWidth: 240)
            Text(value + (tail.map { " · " + $0 } ?? "")).font(Typo.sans(12, .medium)).foregroundStyle(stale ? Palette.ink4 : Palette.ink)
                .monospacedDigit().lineLimit(1).fixedSize()
        }
    }
}

// MARK: - Editing

/// The editable record for one subscription, opened in place of its row. Saving sends the version as
/// `If-Match`; if it changed elsewhere the card offers to reload.
struct SubEditCard: View {
    var item: SubsData.Item?
    /// Category for a new subscription.
    var category = "other"
    var close: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var draft: SubscriptionRecord
    /// The record as last read; a fresher copy only replaces the draft while it is untouched.
    @ViewState private var initial: SubscriptionRecord
    @ViewState private var accounts = SubsCatalog.accounts
    @ViewState private var brands = SubsCatalog.brands
    @ViewState private var error: String?
    @ViewState private var conflict = false
    @ViewState private var busy = false
    @ViewState private var confirmDelete = false

    init(item: SubsData.Item?, category: String = "other", close: @escaping () -> Void) {
        self.item = item
        self.category = category
        self.close = close
        var r = item.map(Self.record) ?? SubscriptionRecord()
        if item == nil { r.category = category }
        _draft = ViewState(initialValue: r)
        _initial = ViewState(initialValue: r)
    }

    private var isNew: Bool { draft.version == 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            HStack(alignment: .top, spacing: 14) {
                field("账号标签") { input($draft.accountLabel, "比如：个人账号") }
                field("套餐") { input($draft.plan, "比如：Max 5×") }
                field("金额") {
                    HStack(spacing: 6) {
                        currencyMenu
                        TextField("留空为未知，0 为免费", text: optional(\.price)).textFieldStyle(.plain).font(Typo.sans(13)).monospacedDigit()
                        if let hint = convertedHint { Text(hint).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit().fixedSize() }
                    }
                    .modifier(SubInput(invalid: draft.price.map { Double($0) == nil } ?? false))
                }
            }
            .padding(.top, 16)
            HStack(alignment: .top, spacing: 14) {
                field("付费区域") { regionField }
                field("付款方") { Segmented(options: Subs.payers, selection: $draft.payer, small: true).fixedSize() }
                Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
            }
            .padding(.top, 12)
            sentence.padding(.top, 14)
            Grid(alignment: .leading, horizontalSpacing: 18, verticalSpacing: 12) {
                if draft.category == "ai" || draft.category == "network" {
                    GridRow {
                        Label11("额度来源")
                        HStack(spacing: 10) {
                            bindingMenu
                            if let note = quotaPreview { Text(note).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
                        }
                    }
                }
                GridRow {
                    Label11("购买网址")
                    input(optional(\.subscriptionUrl), "可选，https://…").frame(maxWidth: 420)
                }
                GridRow {
                    Label11("备注")
                    TextField("比如：发票抬头、取消方式…", text: $draft.note, axis: .vertical).textFieldStyle(.plain).font(Typo.sans(13))
                        .lineLimit(1...4).modifier(SubInput())
                }
            }
            .padding(.top, 14)
            footer
        }
        .padding(.horizontal, 20).padding(.vertical, 18)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Color(hex: "#E3D6C4")))
        .shadow(color: Color(hex: "#3C280A").opacity(0.08), radius: 14, y: 6)
        .task { await load() }
        .onChange(of: draft.category) { _, category in
            if let b = draft.binding, (b.collector == "subboost") != (category == "network") || !["ai", "network"].contains(category) { draft.binding = nil }
        }
        .confirmationDialog("删除「\(draft.name)」？", isPresented: $confirmDelete) {
            Button("删除", role: .destructive) { Task { await remove() } }
        } message: {
            Text("删除后记录不能恢复。只是不再续费的话，可以选「停用」保留记录。")
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Menu {
                Button("自定义 · 名称首字") { brand(nil) }
                if !brands.isEmpty { Divider() }
                ForEach(brands) { b in Button(b.name) { brand(b) } }
            } label: {
                SubLogo(name: draft.name.isEmpty ? "?" : draft.name, size: 36, iconURL: draft.iconUrl, themeColor: draft.themeColor)
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize().help("选择品牌图标")
            VStack(alignment: .leading, spacing: 2) {
                TextField("订阅名称", text: $draft.name).textFieldStyle(.plain).font(Typo.sans(15, .semibold))
                Text(isNew ? "新增订阅" : "版本 \(draft.version)" + (draft.active ? "" : " · 已停用")).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            }
            Spacer()
            Segmented(options: Subs.categories, selection: $draft.category, small: true).fixedSize()
        }
    }

    /// "每 1 月 续费一次，下次在 …，自动续费；到期日 …"
    private var sentence: some View {
        HStack(spacing: 6) {
            if draft.cycle == "one_time" {
                cycleMenu
                Text("，到期日")
            } else {
                Text("每")
                TextField("", value: $draft.frequency, format: .number).textFieldStyle(.plain).font(Typo.sans(13)).monospacedDigit()
                    .multilineTextAlignment(.center).frame(width: 34).modifier(SubInput(compact: true))
                cycleMenu
                Text("续费一次，下次在")
                dateField(\.nextRenewal)
                Text("，")
                Toggle(isOn: $draft.autoRenew) { Text("自动续费") }.toggleStyle(.checkbox).font(Typo.sans(12.5))
                Text("；到期日")
            }
            dateField(\.expiresOn)
            Spacer(minLength: 0)
        }
        .font(Typo.sans(13)).foregroundStyle(Palette.ink2)
        .padding(.horizontal, 12).padding(.vertical, 9)
        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk.opacity(0.6)))
    }

    private var data: SubsData? { state.hub.data.subs?.data }

    /// CNY and USD, then the currencies already in use, then every currency the hub has a rate for.
    private var currencyMenu: some View {
        let used = Set((data?.items ?? []).compactMap(\.currency)).subtracting(Subs.currencies).sorted()
        let all = (data?.exchangeRates?.rates?.keys.sorted() ?? []).filter { !Subs.currencies.contains($0) && !used.contains($0) }
        return Menu {
            ForEach(Subs.currencies, id: \.self) { c in Button(c + " " + Subs.symbol(c)) { draft.currency = c } }
            if !used.isEmpty {
                Divider()
                ForEach(used, id: \.self) { c in Button(c + " " + Subs.symbol(c)) { draft.currency = c } }
            }
            if !all.isEmpty {
                Menu("全部币种") { ForEach(all, id: \.self) { c in Button(c) { draft.currency = c } } }
            }
        } label: {
            HStack(spacing: 3) {
                Text(draft.currency).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Image(systemName: "chevron.down").font(.system(size: 7, weight: .bold)).foregroundStyle(Palette.ink4)
            }
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
    }

    /// "≈ $3.5" for the amount being typed, at the hub's current rates.
    private var convertedHint: String? {
        guard let price = draft.price.flatMap(Double.init), price > 0, let rates = data?.exchangeRates else { return nil }
        let to = draft.currency == "CNY" ? "USD" : "CNY"
        return rates.convert(price, from: draft.currency, to: to).map { "≈ " + Subs.approx($0, to) }
    }

    /// Free text, with the regions already used and a few common cheaper ones to pick from.
    private var regionField: some View {
        let used = Set((data?.items ?? []).compactMap { $0.billingRegion.flatMap { $0.isEmpty ? nil : $0 } }).sorted()
        let common = Subs.regions.filter { !used.contains($0) }
        return HStack(spacing: 6) {
            TextField("比如：美国；留空为未设置", text: optional(\.billingRegion)).textFieldStyle(.plain).font(Typo.sans(13))
            Menu {
                ForEach(used, id: \.self) { r in Button(r) { draft.billingRegion = r } }
                if !used.isEmpty { Divider() }
                ForEach(common, id: \.self) { r in Button(r) { draft.billingRegion = r } }
                if draft.billingRegion != nil {
                    Divider()
                    Button("清除") { draft.billingRegion = nil }
                }
            } label: {
                Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold)).foregroundStyle(Palette.ink4).frame(width: 18, height: 22).contentShape(Rectangle())
            }
            .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize().help("常用区域")
        }
        .modifier(SubInput())
    }

    private var cycleMenu: some View {
        Menu {
            ForEach(Subs.cycles, id: \.0) { key, name in Button(name) { draft.cycle = key } }
            Divider()
            Button("未设置") { draft.cycle = nil }
        } label: {
            HStack(spacing: 3) {
                Text(Subs.cycles.first { $0.0 == draft.cycle }?.1 ?? "周期").foregroundStyle(draft.cycle == nil ? Palette.ink4 : Palette.ink)
                Image(systemName: "chevron.down").font(.system(size: 7, weight: .bold)).foregroundStyle(Palette.ink4)
            }
            .font(Typo.sans(13)).modifier(SubInput(compact: true))
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
    }

    private func dateField(_ key: WritableKeyPath<SubscriptionRecord, String?>) -> some View {
        SubDateButton(value: Binding(get: { draft[keyPath: key] }, set: { draft[keyPath: key] = $0 }))
    }

    private var bindingMenu: some View {
        let options = accounts.filter { ($0.collector == "subboost") == (draft.category == "network") }
        let current = options.first { $0.id == bindingID }
        return Menu {
            Button("不绑定") { draft.binding = nil }
            if !options.isEmpty { Divider() }
            ForEach(options) { a in Button(a.collector == "subboost" ? "SubBoost · " + a.label : "Token Monitor · " + a.label) { draft.binding = a.binding } }
        } label: {
            HStack(spacing: 6) {
                Text(current.map { ($0.collector == "subboost" ? "SubBoost · " : "Token Monitor · ") + $0.label }
                     ?? (bindingID.isEmpty ? "不绑定" : "原账号（当前未发现）"))
                    .font(Typo.sans(12.5)).foregroundStyle(bindingID.isEmpty ? Palette.ink3 : Palette.ink).lineLimit(1)
                Spacer(minLength: 6)
                Image(systemName: "chevron.down").font(.system(size: 7, weight: .bold)).foregroundStyle(Palette.ink4)
            }
            .frame(width: 300).modifier(SubInput())
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
    }

    private var quotaPreview: String? {
        guard draft.binding != nil, let item, let q = item.quota, item.id == draft.id else { return nil }
        let windows = (q.reading?.windows ?? []).compactMap { w in Subs.percent(w).map { "\(w.label) \(Int($0.rounded()))%" } }
        return windows.isEmpty ? nil : "当前：" + windows.prefix(3).joined(separator: " · ")
    }

    private var footer: some View {
        HStack(spacing: 12) {
            if !isNew {
                Button("删除订阅") { confirmDelete = true }.buttonStyle(.plain).font(Typo.sans(12)).foregroundStyle(Tone.rose.color)
                Button(draft.active ? "停用（保留记录，不计入月均）" : "重新启用") { Task { await toggleActive() } }
                    .buttonStyle(.plain).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }
            Spacer()
            if let error {
                Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).lineLimit(2)
                if conflict { Button("重新载入") { Task { await load(force: true) } }.buttonStyle(.plain).font(Typo.sans(11.5, .semibold)).foregroundStyle(Tone.clay.color) }
            }
            Button("取消", action: close).buttonStyle(.hubSecondary).keyboardShortcut(.cancelAction)
            Button { Task { await save() } } label: {
                HStack(spacing: 6) { Text(busy ? "保存中…" : "保存"); Text("⌘↩").font(Typo.sans(11)).opacity(0.6) }
            }
            .buttonStyle(.hubPrimary)
            .keyboardShortcut(.return, modifiers: .command)
            .disabled(busy || draft.name.trimmingCharacters(in: .whitespaces).isEmpty)
        }
        .padding(.top, 14).padding(.top, 4)
        .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1).padding(.top, 4) }
        .padding(.top, 14)
    }

    private func field(_ label: String, @ViewBuilder _ content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Label11(label)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func input(_ text: Binding<String>, _ placeholder: String) -> some View {
        TextField(placeholder, text: text).textFieldStyle(.plain).font(Typo.sans(13)).modifier(SubInput())
    }

    private var bindingID: String {
        guard let b = draft.binding else { return "" }
        return b.collector + ":" + b.provider + ":" + b.account
    }

    private func optional(_ key: WritableKeyPath<SubscriptionRecord, String?>) -> Binding<String> {
        Binding(get: { draft[keyPath: key] ?? "" }, set: { draft[keyPath: key] = $0.isEmpty ? nil : $0 })
    }

    private func brand(_ b: SubscriptionBrandCatalog.Brand?) {
        let previous = brands.first { $0.serviceKey == draft.serviceKey }
        draft.serviceKey = b?.serviceKey
        draft.iconUrl = b?.iconUrl
        if draft.themeColor == nil || draft.themeColor == previous?.themeColor { draft.themeColor = b?.themeColor }
        if draft.subscriptionUrl == nil || draft.subscriptionUrl == previous?.subscriptionUrl { draft.subscriptionUrl = b?.subscriptionUrl }
        if draft.name.isEmpty, let b { draft.name = b.name }
    }

    /// The card opens on the module's copy at once; the full record and the catalogs arrive in the background.
    private func load(force: Bool = false) async {
        if force {
            error = nil
            conflict = false
        }
        if let item {
            do {
                let fallback = initial
                let fresh = try await state.hub.review(demo: { fallback }, live: { try await $0.subscriptionRecord(id: item.id) })
                if force || draft == initial { draft = fresh }
                initial = fresh
            } catch where force {
                self.error = (error as? HubError)?.message ?? "读取失败"
            } catch {}
        }
        await SubsCatalog.load(state)
        if brands.isEmpty { brands = SubsCatalog.brands }
        if accounts.isEmpty { accounts = SubsCatalog.accounts }
    }

    private func save() async {
        if let price = draft.price, Double(price) == nil { error = "金额要是数字"; return }
        for d in [draft.nextRenewal, draft.expiresOn].compactMap({ $0 }) where HubFormat.day(d) == nil {
            error = "日期请写成 YYYY-MM-DD"
            return
        }
        draft.frequency = max(draft.frequency, 1)
        await write { try await $0.saveSubscription(draft) }
    }

    private func toggleActive() async {
        var record = draft
        record.active.toggle()
        await write { try await $0.saveSubscription(record) }
    }

    private func remove() async {
        let record = draft
        await write { try await $0.deleteSubscription(record); return record }
    }

    private func write(_ work: @escaping (HubAPI) async throws -> SubscriptionRecord) async {
        busy = true
        defer { busy = false }
        error = nil
        conflict = false
        do {
            _ = try await state.hub.review(demo: { throw HubError.rejected("示例数据不能保存，请先连接 hub", field: nil) }, live: work)
            state.hub.refresh()
            close()
        } catch let e as HubError {
            switch e {
            case .http(409), .http(412):
                conflict = true
                error = "别处已经改过这项订阅"
            case .rejected(let message, let field):
                conflict = field == "version"
                error = message
            default:
                error = e.message
            }
        } catch {
            self.error = "未保存，请稍后再试"
        }
    }

    /// Stand-in built from the module data, for sample mode or when the record list is unavailable.
    static func record(_ s: SubsData.Item) -> SubscriptionRecord {
        var r = SubscriptionRecord()
        r.id = s.id
        r.version = s.version ?? 0
        r.name = s.name
        r.serviceKey = s.serviceKey
        r.iconUrl = s.iconUrl
        r.themeColor = s.themeColor
        r.subscriptionUrl = s.subscriptionUrl
        r.accountLabel = s.accountLabel ?? ""
        r.category = s.category ?? "other"
        r.plan = s.plan ?? ""
        r.price = s.price.map { $0.rounded() == $0 ? String(Int($0)) : String($0) }
        r.currency = s.currency ?? "CNY"
        r.cycle = s.cycle
        r.frequency = s.frequency ?? 1
        r.nextRenewal = s.nextRenewal
        r.expiresOn = s.expiresOn
        r.payer = s.payer ?? "unknown"
        r.active = s.active ?? true
        r.autoRenew = s.autoRenew ?? false
        r.billingRegion = s.billingRegion
        r.binding = s.binding
        r.quota = s.quota
        r.note = s.note ?? ""
        return r
    }
}

/// Brand icons and quota-source accounts for the editor, kept for ten minutes so opening it doesn't wait on the hub.
@MainActor
enum SubsCatalog {
    static var brands: [SubscriptionBrandCatalog.Brand] = []
    static var accounts: [SubscriptionSourceCatalog.Source.Account] = []
    private static var fetched: Date?

    static func load(_ state: AppState) async {
        if let fetched, Date().timeIntervalSince(fetched) < 600, !brands.isEmpty || !accounts.isEmpty { return }
        fetched = Date()
        async let b = try? state.hub.review(demo: { [] }, live: { try await $0.subscriptionBrands().items })
        async let a = try? state.hub.review(demo: { [] }, live: { try await $0.subscriptionSources().sources.flatMap(\.accounts) })
        let (brandList, accountList) = await (b, a)
        if let brandList { brands = brandList }
        if let accountList { accounts = accountList }
    }
}

/// A `YYYY-MM-DD` date picked from a month calendar, with one month / one year ahead as shortcuts; nil shows 无.
private struct SubDateButton: View {
    @Binding var value: String?
    @ViewState private var open = false
    @ViewState private var day = Date()
    @ViewState private var month = Date()

    var body: some View {
        let date = value.flatMap(HubFormat.day)
        Button { open.toggle() } label: {
            HStack(spacing: 6) {
                Image(systemName: "calendar").font(.system(size: 11, weight: .medium)).foregroundStyle(date == nil ? Palette.ink4 : Palette.ink3)
                Text(date.map { GoogleDate.dayString($0, calendar: .hub) } ?? "无").font(Typo.sans(13)).monospacedDigit()
                    .foregroundStyle(date == nil ? Palette.ink4 : Palette.ink)
            }
            .modifier(SubInput(compact: true))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .popover(isPresented: $open, arrowEdge: .bottom) { panel(base: date) }
    }

    private func panel(base: Date?) -> some View {
        let cal = Calendar.hub, today = cal.startOfDay(for: HubFormat.current())
        let from = base ?? today
        let quick: [(String, Date)] = [("今天", today), ("一个月后", cal.date(byAdding: .month, value: 1, to: from)!),
                                       ("一年后", cal.date(byAdding: .year, value: 1, to: from)!)]
        return VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 6) {
                ForEach(quick, id: \.0) { name, d in
                    Button { pick(d) } label: {
                        Text(name).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).frame(maxWidth: .infinity).frame(height: 30)
                            .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            MonthCalendar(day: Binding(get: { day }, set: { pick($0) }), month: $month, today: today, allowPast: true)
            HStack {
                Button("清除") { value = nil; open = false }.buttonStyle(.hubSecondary)
                Spacer()
                Button("完成") { open = false }.buttonStyle(.hubPrimary).keyboardShortcut(.defaultAction)
            }
        }
        .padding(18).frame(width: 330).background(Palette.card)
        .onAppear { day = from; month = from }
    }

    private func pick(_ d: Date) {
        day = d
        month = d
        value = GoogleDate.dayString(d, calendar: .hub)
    }
}

private struct SubInput: ViewModifier {
    var compact = false
    var invalid = false

    func body(content: Content) -> some View {
        content
            .padding(.horizontal, compact ? 7 : 10).frame(height: compact ? 26 : 30)
            .background(RoundedRectangle(cornerRadius: 7).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(invalid ? Tone.rose.color.opacity(0.7) : Palette.line))
    }
}

/// Network subscriptions with their plans, from the network card.
struct SubsPopover: View {
    var category: String
    var close: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var editing: String?

    var body: some View {
        let items = (state.hub.data.subs?.data?.items ?? []).filter { ($0.category ?? "other") == category }
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("\(Subs.category(category))订阅").font(Typo.serif(17))
                Spacer()
                Button { editing = "" } label: { Label("新增", systemImage: "plus") }.buttonStyle(.hubSecondary)
                Button("完成", action: close).buttonStyle(.hubSecondary)
            }
            if editing == "" {
                SubEditCard(item: nil, category: category, close: { editing = nil }).padding(.vertical, 4)
            }
            ForEach(items) { s in
                if editing == s.id {
                    SubEditCard(item: s, close: { editing = nil }).padding(.vertical, 4)
                } else {
                    SubRow(item: s).contentShape(Rectangle()).onTapGesture { editing = s.id }
                }
            }
            if items.isEmpty && editing == nil {
                Text("还没有\(Subs.category(category))订阅").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).padding(.vertical, 16)
            }
        }
        .padding(18).frame(width: 760)
        .background(Palette.bg)
    }
}
