import HubKit
import SwiftUI

struct SubscriptionManager: View {
    var close: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var records: [SubscriptionRecord] = []
    @ViewState private var editing: SubscriptionRecord?
    @ViewState private var error: String?
    @ViewState private var busy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("订阅与账号").font(.headline)
                Spacer()
                Button("新增") { editing = SubscriptionRecord() }
                Button("完成", action: close)
            }
            if let error { Text(error).foregroundStyle(.red).font(.caption) }
            if busy { ProgressView() }
            List(records) { record in
                HStack {
                    SubLogo(name: record.name, size: 28, iconURL: record.iconUrl, themeColor: record.themeColor)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(record.name + (record.accountLabel.isEmpty ? "" : " · " + record.accountLabel))
                        Text(payer(record.payer) + " · " + (record.plan.isEmpty ? record.category : record.plan)).font(.caption).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("编辑") { editing = record }
                    Button("删除", role: .destructive) { Task { await delete(record) } }
                }
                .disabled(busy)
            }
        }
        .padding(18).frame(width: 600, height: 460)
        .task { await reload() }
        .sheet(item: $editing, onDismiss: { Task { await reload() } }) { record in
            SubscriptionEditor(record: record, close: { editing = nil }).environment(state)
        }
    }

    private func payer(_ value: String) -> String {
        ["self": "个人付费", "company": "公司付费", "other": "其他付款方", "none": "无需付费", "unknown": "付款方待确认"][value] ?? value
    }

    private func reload() async {
        busy = true
        defer { busy = false }
        do {
            records = try await state.hub.review(demo: { [] }, live: { try await $0.subscriptionRecords() })
            error = nil
        } catch { self.error = (error as? HubError)?.message ?? "读取失败" }
    }

    private func delete(_ record: SubscriptionRecord) async {
        busy = true
        defer { busy = false }
        do {
            try await state.hub.review(demo: { throw HubError.rejected("请先连接 hub", field: nil) }, live: { try await $0.deleteSubscription(record) })
            state.hub.refresh()
            await reload()
        } catch { self.error = (error as? HubError)?.message ?? "删除失败，请重新读取后再试" }
    }
}

private struct SubscriptionEditor: View {
    var close: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var draft: SubscriptionRecord
    @ViewState private var accounts: [SubscriptionSourceCatalog.Source.Account] = []
    @ViewState private var brands: [SubscriptionBrandCatalog.Brand] = []
    @ViewState private var error: String?
    @ViewState private var busy = false

    init(record: SubscriptionRecord, close: @escaping () -> Void) {
        self.close = close
        _draft = ViewState(initialValue: record)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(draft.version == 0 ? "新增订阅" : "编辑订阅").font(.headline)
            ScrollView {
                Form {
                    TextField("名称", text: $draft.name)
                    Picker("品牌图标", selection: Binding(get: { draft.serviceKey ?? "" }, set: { key in
                        let previous = brands.first { $0.serviceKey == draft.serviceKey }
                        let brand = brands.first { $0.serviceKey == key }
                        draft.serviceKey = key.isEmpty ? nil : key
                        draft.iconUrl = brand?.iconUrl
                        if draft.themeColor == nil || draft.themeColor == previous?.themeColor { draft.themeColor = brand?.themeColor }
                        if draft.subscriptionUrl == nil || draft.subscriptionUrl == previous?.subscriptionUrl { draft.subscriptionUrl = brand?.subscriptionUrl }
                    })) {
                        Text("自定义／名称首字").tag("")
                        ForEach(brands) { brand in Text(brand.name).tag(brand.serviceKey) }
                        if let key = draft.serviceKey, !brands.contains(where: { $0.serviceKey == key }) {
                            Text("原品牌（暂不可用）").tag(key)
                        }
                    }
                    HStack {
                        SubLogo(name: draft.name, size: 24, iconURL: draft.iconUrl, themeColor: draft.themeColor)
                        TextField("主题色，例如 #4285F4", text: optional(\SubscriptionRecord.themeColor))
                    }
                    TextField("购买订阅的网址", text: optional(\SubscriptionRecord.subscriptionUrl))
                    TextField("账号别名", text: $draft.accountLabel)
                    Picker("类别", selection: $draft.category) {
                        Text("AI").tag("ai"); Text("网络").tag("network")
                        Text("会员").tag("membership"); Text("其他").tag("other")
                    }
                    TextField("套餐", text: $draft.plan)
                    TextField("金额（留空为未知，0 为免费）", text: optional(\SubscriptionRecord.price))
                    TextField("币种，例如 CNY / USD", text: $draft.currency)
                    Picker("周期", selection: Binding(get: { draft.cycle ?? "" }, set: { draft.cycle = $0.isEmpty ? nil : $0 })) {
                        Text("未设置").tag(""); Text("天").tag("day"); Text("周").tag("week")
                        Text("月").tag("month"); Text("年").tag("year"); Text("一次性").tag("one_time")
                    }
                    Stepper("每 \(draft.frequency) 个周期", value: $draft.frequency, in: 1...3650)
                    TextField("下次续费 YYYY-MM-DD", text: optional(\SubscriptionRecord.nextRenewal))
                    TextField("到期日期 YYYY-MM-DD", text: optional(\SubscriptionRecord.expiresOn))
                    Picker("付款方", selection: $draft.payer) {
                        Text("待确认").tag("unknown"); Text("个人").tag("self")
                        Text("公司").tag("company"); Text("其他").tag("other"); Text("无需付费").tag("none")
                    }
                    Toggle("自动续费", isOn: $draft.autoRenew)
                    Toggle("启用", isOn: $draft.active)
                    if draft.category == "ai" || draft.category == "network" {
                        Picker("额度来源账号", selection: Binding(get: { bindingID }, set: { id in
                            draft.binding = accounts.first(where: { $0.id == id })?.binding
                        })) {
                            Text("不采集").tag("")
                            ForEach(accounts.filter { ($0.collector == "subboost") == (draft.category == "network") }) { account in
                                Text(account.label).tag(account.id)
                            }
                            if !bindingID.isEmpty && !accounts.contains(where: { $0.id == bindingID }) {
                                Text("原账号（当前未发现）").tag(bindingID)
                            }
                        }
                    }
                    TextField("备注", text: $draft.note, axis: .vertical)
                }
                .formStyle(.grouped)
            }
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
            HStack {
                Spacer()
                Button("取消", action: close)
                Button(busy ? "保存中…" : "保存") { Task { await save() } }.disabled(busy || draft.name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(18).frame(width: 570, height: 650)
        .task {
            do { brands = try await state.hub.review(demo: { [] }, live: { try await $0.subscriptionBrands().items }) }
            catch { self.error = "品牌目录暂时无法读取；已有图标与主题色会保留" }
            do { accounts = try await state.hub.review(demo: { [] }, live: { try await $0.subscriptionSources().sources.flatMap(\.accounts) }) }
            catch { self.error = "来源账号暂时无法读取；已有绑定会保留" }
        }
        .onChange(of: draft.category) { _, category in
            if let b = draft.binding, (b.collector == "subboost") != (category == "network") || !["ai", "network"].contains(category) { draft.binding = nil }
        }
    }

    private var bindingID: String {
        guard let binding = draft.binding else { return "" }
        return binding.collector + ":" + binding.provider + ":" + binding.account
    }

    private func optional(_ key: WritableKeyPath<SubscriptionRecord, String?>) -> Binding<String> {
        Binding(get: { draft[keyPath: key] ?? "" }, set: { draft[keyPath: key] = $0.isEmpty ? nil : $0 })
    }

    private func save() async {
        busy = true
        defer { busy = false }
        do {
            draft.currency = draft.currency.uppercased()
            let record = draft
            _ = try await state.hub.review(demo: { throw HubError.rejected("请先连接 hub", field: nil) }, live: { try await $0.saveSubscription(record) })
            state.hub.refresh()
            close()
        } catch { self.error = (error as? HubError)?.message ?? "未保存，请检查金额和日期；发生冲突时关闭后重新打开" }
    }
}
