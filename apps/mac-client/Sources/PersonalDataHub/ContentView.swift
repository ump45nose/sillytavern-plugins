import SwiftUI
import Charts

struct HubCard<Content: View>: View {
    let title: String; let icon: String
    @ViewBuilder var content: () -> Content
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label(title, systemImage: icon).font(.headline)
            content()
        }
        .padding(20).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.primary.opacity(0.06), lineWidth: 1))
    }
}
struct ContentView: View {
    @ObservedObject var model: HubModel
    @State private var settings = false
    @State private var customize = false
    @State private var search = false
    @State private var contacts: [DisplayCard] = []
    @FocusState private var searchFocused: Bool
    private let navigation = [("overview", "概览", "square.grid.2x2"), ("agenda", "日程与任务", "calendar"),
                              ("health", "健康", "heart"), ("social", "社交", "person.2"),
                              ("archive", "内容档案", "tray.full"), ("finance", "财务与用量", "chart.bar")]
    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 200)
            Divider()
            VStack(spacing: 0) {
                header
                if let error = model.error { notice(error, icon: "wifi.exclamationmark") }
                if search {
                    HStack {
                        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                        TextField("搜索归档标题与内容摘要", text: $model.query).focused($searchFocused)
                            .textFieldStyle(.plain).onSubmit { model.section = "archive"; Task { await model.loadTimeline() } }
                        Button("搜索") { model.section = "archive"; Task { await model.loadTimeline() } }
                        Button { search = false; model.query = "" } label: { Image(systemName: "xmark") }.buttonStyle(.plain)
                    }.padding(16).background(.regularMaterial)
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        if model.section == "status" { statusPage }
                        else if model.section == "agenda" { AgendaView(model: model) }
                        else if model.section == "archive" || (model.section == "overview" && model.overviewMode == "recent") { timelinePage }
                        else if model.section == "overview" && model.overviewMode == "trends" { trendsPage }
                        else { dashboardPage }
                    }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
                }
                .background(Color(nsColor: .windowBackgroundColor))
            }
        }
        .tint(.indigo).frame(minWidth: 980, minHeight: 680)
        .sheet(isPresented: $settings) { SettingsView(model: model) }
        .sheet(isPresented: $customize) { CustomizeView(model: model) }
        .sheet(isPresented: $model.showingDetail) { ReadableDetailView(model: model) }
        .sheet(isPresented: $model.taskEditor) { TaskEditor(model: model) }
        .sheet(isPresented: $model.eventEditor) { EventEditor(model: model) }
        .onChange(of: model.section) { _ in Task { await model.loadDisplay(); await model.loadTimeline(); if model.section == "agenda" { await model.refreshGoogle() } } }
        .onChange(of: model.displayDate) { _ in Task { await model.loadDisplay(); await model.refreshGoogle() } }
        .onChange(of: model.trendDays) { _ in Task { await model.loadDisplay() } }
        .onReceive(NotificationCenter.default.publisher(for: .hubSearch)) { _ in search = true; searchFocused = true }
    }
    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "square.stack.3d.up.fill").font(.title2).foregroundStyle(.indigo)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Personal Hub").font(.headline)
                    Text("你的信息，尽在此处").font(.caption).foregroundStyle(.secondary)
                }
            }.padding(.horizontal, 20).padding(.top, 28).padding(.bottom, 28)
            ForEach(navigation, id: \.0) { item in nav(item.0, item.1, item.2) }
            Spacer()
            Divider().padding(.horizontal, 16).padding(.bottom, 12)
            nav("status", "采集状态", "arrow.triangle.2.circlepath")
            Button { settings = true } label: { Label("设置", systemImage: "gearshape").frame(maxWidth: .infinity, alignment: .leading).padding(12) }
                .buttonStyle(.plain).padding(.horizontal, 10)
            HStack(spacing: 6) {
                Circle().fill(model.sources.contains(where: \.needsAttention) ? Color.orange : Color.green).frame(width: 6, height: 6)
                Text("\(model.sources.count) 个来源已连接").font(.caption).foregroundStyle(.secondary)
            }.padding(20)
        }.background(.regularMaterial)
    }
    private func nav(_ id: String, _ title: String, _ icon: String) -> some View {
        Button { model.section = id } label: {
            Label(title, systemImage: icon).font(.system(size: 14, weight: model.section == id ? .semibold : .regular))
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 14).padding(.vertical, 12)
                .background(model.section == id ? Color.indigo.opacity(0.12) : .clear, in: RoundedRectangle(cornerRadius: 9))
                .foregroundStyle(model.section == id ? Color.indigo : Color.primary)
        }.buttonStyle(.plain).padding(.horizontal, 10).padding(.bottom, 4)
    }
    private var header: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                if model.section == "overview" {
                    Picker("", selection: $model.overviewMode) {
                        Text("今日概览").tag("today"); Text("数据趋势").tag("trends"); Text("最近动态").tag("recent")
                    }.labelsHidden().pickerStyle(.menu).font(.title2.bold()).fixedSize()
                } else {
                    Text(navigation.first(where: { $0.0 == model.section })?.1 ?? "采集状态").font(.title2.bold())
                }
                Text(model.displayDate.formatted(.dateTime.month(.wide).day().weekday(.wide)))
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer()
            if model.section != "archive" && model.section != "status" {
                DatePicker("", selection: $model.displayDate, displayedComponents: .date).labelsHidden().frame(width: 120)
                Button("今天") { model.displayDate = Date() }
            }
            Button { search.toggle(); searchFocused = search } label: { Image(systemName: "magnifyingglass") }.help("搜索 ⌘F")
            if model.section == "overview" { Button { customize = true } label: { Image(systemName: "slider.horizontal.3") }.help("定制首页") }
            Button { Task { await model.refreshStatus(); await model.loadDisplay(); await model.loadTimeline(); await model.refreshGoogle() } } label: { Image(systemName: "arrow.clockwise") }.help("刷新")
            Menu {
                Button("新增任务") { model.editingTask = nil; model.taskEditor = true }
                Button("新增日程") { model.editingEvent = nil; model.eventEditor = true }
            } label: { Label("新增", systemImage: "plus") }.menuStyle(.borderlessButton).fixedSize()
        }.padding(.horizontal, 24).padding(.vertical, 20).background(.bar)
    }
    private func notice(_ text: String, icon: String) -> some View {
        HStack {
            Image(systemName: icon); Text(text).font(.callout).lineLimit(2)
            Spacer(); Button("关闭") { model.error = nil }.buttonStyle(.plain)
        }.padding(12).background(Color.orange.opacity(0.08))
    }
    @ViewBuilder private var dashboardPage: some View {
        if let dashboard = model.dashboard {
            if dashboard.date != dayKey(model.displayDate) { Text("显示缓存数据 · \(dashboard.date)").font(.caption).foregroundStyle(.orange) }
            if dashboard.modules.isEmpty { empty("在定制首页中选择你想看的模块", "slider.horizontal.3") }
            let rows = dashboardRows(dashboard.modules)
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                if row.first?.id == "agenda", let agenda = row.first {
                    HubCard(title: "日程与任务", icon: "calendar") { AgendaSummary(model: model, archived: agenda) }
                } else {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 380), spacing: 16, alignment: .topLeading)], alignment: .leading, spacing: 16) {
                        ForEach(row) { module in moduleCard(module) }
                    }
                }
            }
            if model.section == "social" {
                HubCard(title: "联系人", icon: "person.crop.circle") {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 220))], spacing: 12) {
                        ForEach(contacts) { person in
                            Button { model.openCard(person) } label: {
                                HStack(spacing: 12) {
                                    Text(String(person.title.prefix(1))).font(.title3).frame(width: 40, height: 40).background(Color.indigo.opacity(0.08), in: Circle())
                                    VStack(alignment: .leading, spacing: 5) { Text(person.title).font(.headline); Text(person.metadata["relationship_to_me"]?.text ?? "").font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                                    Spacer()
                                }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(Color.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 10))
                            }.buttonStyle(.plain)
                        }
                    }
                }.task {
                    do {
                        let page: TimelinePage = try await model.api.get("api/v1/timeline", query: [URLQueryItem(name: "domains", value: "social"), URLQueryItem(name: "kind", value: "people"), URLQueryItem(name: "limit", value: "100")])
                        contacts = page.items
                    } catch { model.error = error.localizedDescription }
                }
            }
        } else if model.displayLoading {
            ProgressView("正在整理你的信息…").frame(maxWidth: .infinity, minHeight: 320)
        } else { empty("连接后即可查看你的信息", "square.stack.3d.up") }
    }
    private func dashboardRows(_ modules: [DisplayModule]) -> [[DisplayModule]] {
        var rows: [[DisplayModule]] = []; var pair: [DisplayModule] = []
        for module in modules {
            if module.id == "agenda" { if !pair.isEmpty { rows.append(pair); pair = [] }; rows.append([module]) }
            else { pair.append(module); if pair.count == 2 { rows.append(pair); pair = [] } }
        }
        if !pair.isEmpty { rows.append(pair) }; return rows
    }
    private func moduleCard(_ module: DisplayModule) -> some View {
        HubCard(title: moduleLabels[module.id] ?? module.id, icon: moduleIcons[module.id] ?? "doc") {
            let preference = model.preferences.modules.first { $0.id == module.id }
            let selected = module.metrics.filter { preference == nil || preference!.metrics.contains($0.id.components(separatedBy: ":")[0]) }
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(minimum: 80), alignment: .leading), count: min(3, max(1, selected.count))), alignment: .leading, spacing: 16) {
                ForEach(selected) { metric in
                    VStack(alignment: .leading, spacing: 5) {
                        Text(metric.label).font(.caption).foregroundStyle(.secondary)
                        Text(metric.formatted).font(.system(size: 28, weight: .semibold, design: .rounded)).monospacedDigit()
                        Text(metric.number == nil ? "暂无数据" : metric.unit == "bytes" ? " " : metric.unit).font(.caption).foregroundStyle(.secondary)
                        if metric.date != dayKey(model.displayDate) { Text(metric.date).font(.caption).foregroundStyle(.orange) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    .onTapGesture { if let id = metric.record_ids.first { model.selectedID = id; model.showingDetail = true; Task { await model.select(id) } } }
                }
            }
            if selected.isEmpty && module.items.isEmpty { Text("暂无可展示的数据").font(.subheadline).foregroundStyle(.secondary).padding(.vertical, 12) }
            if let first = selected.first { miniChart(module.id, first.id).frame(height: 56) }
            if !module.items.isEmpty {
                ForEach(module.items.prefix(module.id == "social" ? 3 : 2)) { item in
                    Button { model.openCard(item) } label: {
                        HStack(alignment: .top, spacing: 10) {
                            if module.id == "social" {
                                Text(String(item.title.prefix(1))).font(.headline).frame(width: 34, height: 34).background(Color.indigo.opacity(0.08), in: Circle())
                            }
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item.title).font(.subheadline.weight(.medium)).lineLimit(1)
                                Text(item.preview).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                                Text(displayDate(item.occurred_at)).font(.caption).foregroundStyle(.tertiary)
                            }
                            Spacer(); Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                        }.padding(.vertical, 3).contentShape(Rectangle())
                    }.buttonStyle(.plain)
                }
            }
            if let date = module.updated_at { Text("更新于 \(displayDate(date))").font(.caption).foregroundStyle(.tertiary) }
        }
    }
    @ViewBuilder private func miniChart(_ module: String, _ metric: String) -> some View {
        let points = model.trends?.days.compactMap { day -> TrendPoint? in
            guard let m = day.modules.first(where: { $0.id == module })?.metrics.first(where: { $0.id == metric }), let value = m.number else { return nil }
            return TrendPoint(day: day.date, value: value)
        } ?? []
        if points.count > 1 {
            Chart(points) { p in
                AreaMark(x: .value("日期", p.date), y: .value("数值", p.value)).foregroundStyle(Color.indigo.opacity(0.08))
                LineMark(x: .value("日期", p.date), y: .value("数值", p.value)).foregroundStyle(.indigo).lineStyle(StrokeStyle(lineWidth: 2))
            }.chartXAxis(.hidden).chartYAxis(.hidden)
        }
    }
    private var trendsPage: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                Text("查看变化，了解最近的状态").foregroundStyle(.secondary)
                Spacer()
                Picker("范围", selection: $model.trendDays) { Text("最近 7 天").tag(7); Text("最近 30 天").tag(30) }.pickerStyle(.segmented).frame(width: 220)
            }
            ForEach(model.dashboard?.modules ?? []) { module in
                HubCard(title: moduleLabels[module.id] ?? module.id, icon: moduleIcons[module.id] ?? "chart.xyaxis.line") {
                    let allowed = model.preferences.modules.first { $0.id == module.id }?.metrics ?? []
                    let metrics = module.metrics.filter { allowed.contains($0.id.components(separatedBy: ":")[0]) }
                    ForEach(metrics) { metric in
                        let heading = model.trends?.days.last?.modules.first(where: { $0.id == module.id })?.metrics.first(where: { $0.id == metric.id })?.label ?? metric.label
                        let points = model.trends?.days.compactMap { d -> TrendPoint? in
                            guard let v = d.modules.first(where: { $0.id == module.id })?.metrics.first(where: { $0.id == metric.id })?.number else { return nil }
                            return TrendPoint(day: d.date, value: v)
                        } ?? []
                        HStack { Text(heading); Spacer(); Text(metric.unit).foregroundStyle(.secondary) }
                        if points.isEmpty { Text("这段时间暂无数据").font(.caption).foregroundStyle(.secondary) }
                        else {
                            Chart(points) { p in
                                BarMark(x: .value("日期", p.date, unit: .day), y: .value(heading, p.value)).foregroundStyle(.indigo.opacity(0.75))
                            }.frame(height: 150).accessibilityLabel(metric.label + "每日趋势")
                            DisclosureGroup("每日明细") {
                                ForEach(points) { p in HStack { Text(p.day); Spacer(); Text(p.value.formatted(.number.precision(.fractionLength(0...2)))) }.font(.caption).padding(.vertical, 3) }
                            }.font(.caption)
                        }
                    }
                }
            }
        }
    }
    private var timelinePage: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(model.query.isEmpty ? "你的信息，按时间串联" : "搜索：\(model.query)").foregroundStyle(.secondary)
                Spacer()
                Picker("内容", selection: $model.timelineDomain) {
                    Text("全部动态").tag("social,activity,recordings,reports,mail,git,notes")
                    ForEach(["social", "activity", "recordings", "reports", "mail", "git", "notes", "finance", "usage", "network", "technical"], id: \.self) {
                        Text(moduleLabels[$0] ?? "原始归档").tag($0)
                    }
                }.frame(width: 160).onChange(of: model.timelineDomain) { _ in Task { await model.loadTimeline() } }
            }
            if model.timeline.isEmpty { empty("没有符合条件的内容", "tray") }
            ForEach(Array(model.timeline.enumerated()), id: \.element.id) { index, item in
                let day = archiveDate(item.occurred_at).map(dayKey) ?? "时间未知"
                let previous = index > 0 ? archiveDate(model.timeline[index-1].occurred_at).map(dayKey) ?? "时间未知" : ""
                if day != previous { Text(day).font(.headline).padding(.top, 12) }
                Button { model.openCard(item) } label: {
                    HStack(alignment: .top, spacing: 16) {
                        Image(systemName: moduleIcons[item.domain] ?? "doc").foregroundStyle(.indigo).frame(width: 36, height: 36)
                            .background(Color.indigo.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
                        VStack(alignment: .leading, spacing: 7) {
                            HStack { Text(item.title).font(.headline); Spacer(); Text(displayDate(item.occurred_at)).font(.caption).foregroundStyle(.secondary) }
                            Text(item.preview).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                            Text(sourceName(item.source)).font(.caption).foregroundStyle(.tertiary)
                        }
                    }.padding(18).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                }.buttonStyle(.plain)
            }
            if model.timelineCursor != nil { Button("查看更多") { Task { await model.loadTimeline(reset: false) } }.frame(maxWidth: .infinity) }
        }
    }
    private var statusPage: some View {
        VStack(spacing: 16) {
            HubCard(title: "本机采集", icon: "desktopcomputer") {
                ForEach(model.agents) { a in HStack { Text(a.name); Spacer(); Text(a.state).foregroundStyle(a.loaded ? Color.green : Color.orange) } }
                Button("立即同步电脑活动") { Task { await model.synchronize() } }
                if let msg = model.syncMessage { Text(msg).font(.caption).foregroundStyle(.secondary) }
                Text("关闭窗口后，后台采集继续运行。").font(.caption).foregroundStyle(.secondary)
            }
            HubCard(title: "数据来源", icon: "externaldrive.connected.to.line.below") {
                ForEach(model.sources) { s in
                    HStack {
                        VStack(alignment: .leading, spacing: 4) { Text(s.name); if let note = s.qualityNote { Text(note).font(.caption).foregroundStyle(.orange) } }
                        Spacer(); Text(s.count.formatted()).monospacedDigit().foregroundStyle(.secondary)
                        Text(s.state).foregroundStyle(s.needsAttention ? Color.orange : Color.green).frame(width: 120)
                    }.padding(.vertical, 6)
                }
            }
        }
    }
    private func empty(_ text: String, _ icon: String) -> some View {
        VStack(spacing: 12) { Image(systemName: icon).font(.largeTitle); Text(text) }.foregroundStyle(.secondary).frame(maxWidth: .infinity, minHeight: 250)
    }
}
struct TrendPoint: Identifiable { let day: String; let value: Double; var id: String { day }; var date: Date { dateOnly(day) ?? .distantPast } }
struct CustomizeView: View {
    @ObservedObject var model: HubModel
    @Environment(\.dismiss) var dismiss
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("定制你的首页").font(.title2.bold())
            Text("选择关心的内容，拖动调整顺序。").foregroundStyle(.secondary)
            List {
                ForEach($model.preferences.modules) { $item in
                    VStack(alignment: .leading, spacing: 8) {
                        Toggle(moduleLabels[item.id] ?? item.id, isOn: $item.enabled)
                        if item.enabled {
                            let choices = metricCatalogue[item.id] ?? [("count", "今日记录")]
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 100))], alignment: .leading) {
                                ForEach(choices, id: \.0) { key, label in
                                    Toggle(label, isOn: Binding(get: { item.metrics.contains(key) }, set: { on in if on { item.metrics.append(key) } else { item.metrics.removeAll { $0 == key } } })).toggleStyle(.checkbox)
                                }
                            }.font(.caption)
                        }
                    }.padding(.vertical, 5)
                }.onMove { from, to in model.preferences.modules.move(fromOffsets: from, toOffset: to) }
            }.frame(height: 400)
            HStack { Button("恢复默认") { model.preferences = UIPreferences() }; Spacer(); Button("完成") { model.persistPreferences(); dismiss() }.keyboardShortcut(.defaultAction) }
        }.padding(26).frame(width: 540)
    }
}
extension Notification.Name { static let hubSearch = Notification.Name("hub.search") }
