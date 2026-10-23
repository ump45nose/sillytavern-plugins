import AppKit
import HubKit
import SwiftUI

// MARK: - Token 用量

enum TokenTone {
    static func name(_ tool: String) -> String { Vendor.tool(tool).label }

    /// What tells two quotas of the same tool apart: the hub's account, else the plan, else a number.
    static func subtitle(_ l: TokenData.Limit, in all: [TokenData.Limit]) -> String? {
        let plan = l.plan.flatMap { $0.isEmpty ? nil : $0 }
        if let account = l.account, !account.isEmpty { return [account, plan].compactMap { $0 }.joined(separator: " · ") }
        let same = all.filter { Vendor.tool($0.tool).id == Vendor.tool(l.tool).id }
        guard same.count > 1 else { return plan }
        if let plan, same.filter({ $0.plan == plan }).count == 1 { return plan }
        let n = (same.firstIndex(of: l) ?? 0) + 1
        return [plan, "账号 \(n)"].compactMap { $0 }.joined(separator: " · ")
    }

    /// Tools with at least one known percentage, duplicates dropped, busiest first; windows busiest first.
    static func visible(_ limits: [TokenData.Limit]) -> [TokenData.Limit] {
        var seen = Set<String>()
        return limits.compactMap { l -> TokenData.Limit? in
            var l = l
            l.windows = l.windows.filter { $0.percent != nil }.sorted { $0.percent! > $1.percent! }
            let key = l.tool.lowercased() + "|" + (l.plan ?? "") + "|" + (l.account ?? "") + "|" + l.windows.map { "\($0.label)=\($0.percent!)" }.joined(separator: ",")
            guard !l.windows.isEmpty, seen.insert(key).inserted else { return nil }
            return l
        }
        .sorted { ($0.windows.first?.percent ?? 0) > ($1.windows.first?.percent ?? 0) }
    }

    static func resets(_ date: Date?, now: Date = HubFormat.current()) -> String? {
        guard let date else { return nil }
        let s = date.timeIntervalSince(now)
        if s <= 0 { return "即将重置" }
        if s < 3600 { return "\(Int(s / 60)) 分钟后重置" }
        if s < 86_400 { return "\(HubFormat.clock(date)) 重置 · \(Int(s / 3600)) 小时后" }
        return "\(HubFormat.stamp(date, now: now) ?? "") 重置 · \(Int(s / 86_400)) 天后"
    }
}

struct TokenModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        if size == .compact {
            HubGate(envelope: state.hub.data.token[.day]) { t in compact(t) }
        } else {
            TokenDetail()
        }
    }

    private func compact(_ t: TokenData) -> some View {
        let total = (t.today?.total ?? t.total).map { $0 / 1_000_000 }, cost = t.today?.cost ?? t.cost
        let visible = TokenTone.visible(t.limits ?? [])
        let windows = visible.flatMap { l in
            l.windows.map { w in
                ([TokenTone.name(l.tool), TokenTone.subtitle(l, in: visible), w.label].compactMap { $0 }.joined(separator: " · "), w.percent ?? 0, Vendor.tool(l.tool))
            }
        }
        .sorted { $0.1 > $1.1 }.prefix(2)
        return VStack(alignment: .leading, spacing: 0) {
            if let total {
                let big = total >= 1000
                Hero(value: big ? total / 1000 : total, decimals: big ? 2 : 1, unit: big ? "B" : "M")
                Text("tokens\(cost.map { " · ≈ $\(Fmt.number($0, $0 >= 100 ? 0 : 2))" } ?? "")").font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1)
            } else {
                Hero.empty("M tokens")
            }
            Spacer(minLength: 6)
            ForEach(Array(windows), id: \.0) { label, v, vendor in
                VStack(spacing: 5) {
                    HStack(spacing: 6) {
                        VendorMark(vendor: vendor, size: 12)
                        Text(label).foregroundStyle(Palette.ink2).lineLimit(1)
                        Spacer()
                        Text("\(Int(v))%").monospacedDigit()
                    }
                    .font(Typo.sans(11.5))
                    Track(value: v, color: vendor.color, height: 4)
                }
                .padding(.top, 8)
            }
        }
    }
}

private struct TokenDetail: View {
    @Environment(AppState.self) private var state
    @ViewState private var trend = false
    @ViewState private var year: Int?
    @ViewState private var allSessions = false

    private static let ranges: [TokenRange] = [.day, .week, .month]

    var body: some View {
        @Bindable var state = state
        let range = state.tokenRange == .year ? .month : state.tokenRange
        VStack(alignment: .leading, spacing: 0) {
            allTime
            limits.padding(.top, 10)
            HStack(spacing: 12) {
                Segmented(options: Self.ranges.map { ($0, $0.label) }, selection: $state.tokenRange)
                if let s = state.hub.token(range) { rangeLine(s) }
                Spacer(minLength: 0)
            }
            .padding(.top, 26)
            if let s = state.hub.token(range) {
                AdaptiveRow(threshold: 900, spacing: 28, stackSpacing: 6) {
                    parts("工具", s.tools, .tool)
                    parts("模型", s.models, .model, limit: 8)
                    parts("设备", s.devices, .device)
                }
                .id(range)
                sessions(s.sessions, range: range)
            } else {
                HubGate(envelope: state.hub.data.token[range]) { _ in EmptyView() }.frame(minHeight: 200)
            }
        }
    }

    // MARK: All time

    @ViewBuilder private var allTime: some View {
        if let h = state.hub.tokenHistory() {
            let years = h.years()
            let shown = year.flatMap { years.contains($0) ? $0 : nil } ?? years.last!
            let big = h.total >= 1000
            HStack(alignment: .bottom, spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    Label11("全部时间 · \(Calendar.hub.isDate(h.first, equalTo: state.agenda.now, toGranularity: .year) ? HubFormat.md(h.first) : HubFormat.ymd(h.first)) 起 \(h.days.count) 天")
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        CountUp(value: big ? h.total / 1000 : h.total, decimals: big ? 2 : 1).font(Typo.serif(40))
                        Text(big ? "B tokens" : "M tokens").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    }
                }
                .padding(.trailing, 28)
                stat(h.exact ? "估算成本" : "估算成本 · 近一年", h.cost.map { "$" + Fmt.number($0, $0 >= 100 ? 0 : 2) } ?? "—")
                stat("日均", TokenFormat.short(h.average))
                stat("最高一天", h.best.map { "\(HubFormat.md($0.date)) · \(TokenFormat.short($0.total ?? 0))" } ?? "—")
                Spacer(minLength: 12)
                Segmented(options: [(false, "热力图"), (true, "趋势")], selection: $trend, small: true).fixedSize()
            }
            Group {
                if trend {
                    TokenTrend(history: h).frame(height: 168)
                } else {
                    VStack(alignment: .leading, spacing: 10) {
                        HistoryHeatmap(year: h.year(shown), maxValue: h.maxValue).id(shown)
                        HStack(spacing: 10) {
                            if years.count > 1 {
                                HStack(spacing: 2) {
                                    pager("chevron.left", disabled: shown == years.first) { year = shown - 1 }
                                    Text(verbatim: "\(shown)").font(Typo.sans(11.5, .medium)).monospacedDigit().frame(width: 40)
                                    pager("chevron.right", disabled: shown == years.last) { year = shown + 1 }
                                }
                            }
                            Text(h.exact ? "空格为 Token Monitor 接入前" : "hub 还没提供全部历史，暂按近一年的每日数据显示")
                                .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                            Spacer()
                            HeatLegend()
                        }
                    }
                }
            }
            .padding(.top, 16)
        } else {
            VStack(alignment: .leading, spacing: 6) {
                Label11("全部时间")
                note("hub 还没有每日用量记录")
            }
        }
    }

    private func stat(_ label: String, _ value: String) -> some View {
        HStack(spacing: 14) {
            Rectangle().fill(Palette.line2).frame(width: 1, height: 40)
            VStack(alignment: .leading, spacing: 4) {
                Label11(label)
                Text(value).font(Typo.serif(20)).foregroundStyle(value == "—" ? Palette.ink3 : Palette.ink).monospacedDigit().lineLimit(1)
            }
        }
        .padding(.trailing, 24)
        .rise(1)
    }

    private func pager(_ symbol: String, disabled: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 9.5, weight: .semibold)).foregroundStyle(Palette.ink2)
                .frame(width: 20, height: 20).background(RoundedRectangle(cornerRadius: 6).fill(Palette.sunk)).contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(disabled).opacity(disabled ? 0.4 : 1)
    }

    // MARK: Range

    private func rangeLine(_ s: TokenRangeSummary) -> some View {
        let delta = s.deltaPercent.map { d in Text(" · \(s.comparisonLabel) ") + Text("\(d >= 0 ? "↑" : "↓") \(abs(d))%").foregroundColor(d >= 0 ? Tone.clay.color : Tone.olive.color) }
        let main = Text([s.periodLabel, s.total.map(TokenFormat.short), s.cost.map { "$" + Fmt.number($0, $0 >= 100 ? 0 : 2) }].compactMap { $0 }.joined(separator: " · "))
        return (main + (delta ?? Text(""))).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).monospacedDigit().lineLimit(1)
    }

    enum PartKind { case tool, model, device }

    private func parts(_ title: String, _ parts: [TokenRangeSummary.Part]?, _ kind: PartKind, limit: Int = 6) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle(title)
            if let parts, !parts.isEmpty {
                let top = parts.compactMap(\.total).max() ?? 1
                ForEach(Array(TokenRangeSummary.Part.top(parts, limit).enumerated()), id: \.1.id) { i, p in
                    partRow(p, kind, (p.total ?? 0) / max(top, 0.000_001) * 100, i)
                }
            } else {
                note("hub 还没提供这一区间的\(title)分布")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func partRow(_ p: TokenRangeSummary.Part, _ kind: PartKind, _ pct: Double, _ i: Int) -> some View {
        let other = p.id == "_other"
        let vendor: Vendor? = switch kind {
        case _ where other: nil
        case .tool: Vendor.tool(p.id)
        case .model: Vendor.model(p.name) ?? Vendor.model(p.id)
        case .device: nil
        }
        let color: Color = switch kind {
        case _ where other: Palette.ink4
        case .tool: Vendor.tool(p.id).color
        case .model: Vendor.modelColor(p.name)
        case .device: Palette.ink2
        }
        return HStack(spacing: 8) {
            Group {
                if kind == .device && !other {
                    Image(systemName: Self.deviceSymbol(p.name)).font(.system(size: 11)).foregroundStyle(Palette.ink3)
                } else {
                    VendorMark(vendor: vendor, color: other ? Palette.ink4 : color, size: 14)
                }
            }
            .frame(width: 16)
            Text(p.name).font(Typo.sans(12)).lineLimit(1).truncationMode(.middle).frame(width: kind == .model ? 128 : 92, alignment: .leading)
                .help(p.name)
            Track(value: pct, color: color, delay: Double(i) * 80)
            Text(p.total.map(TokenFormat.short) ?? "—").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 50, alignment: .trailing)
            if kind != .device {
                Text(p.cost.map { "$" + Fmt.number($0, $0 >= 100 ? 0 : 2) } ?? "—").font(Typo.sans(12)).foregroundStyle(Palette.ink2).monospacedDigit()
                    .frame(width: 56, alignment: .trailing)
            }
        }
        .padding(.vertical, 5)
    }

    static func deviceSymbol(_ name: String) -> String {
        let n = name.lowercased()
        if n.contains("nas") || n.contains("server") { return "server.rack" }
        if n.contains("air") || n.contains("book") { return "laptopcomputer" }
        if n.contains("phone") || n.contains("android") { return "iphone" }
        return "desktopcomputer"
    }

    @ViewBuilder private func sessions(_ list: [TokenData.Session]?, range: TokenRange) -> some View {
        SectionTitle("会话 · 用量最高")
        if let list, !list.isEmpty {
            let shown = allSessions ? list : Array(list.prefix(8))
            if list.allSatisfy({ ($0.title ?? "").isEmpty }) {
                note("hub 还没提供会话标题，暂显示模型和会话编号")
            }
            VStack(spacing: 0) {
                ForEach(Array(shown.enumerated()), id: \.1.id) { i, x in
                    sessionRow(x)
                    if i < shown.count - 1 { Rectangle().fill(Palette.line2).frame(height: 1) }
                }
            }
            if list.count > 8 {
                Button { withAnimation(Motion.spring) { allSessions.toggle() } } label: {
                    Text(allSessions ? "收起" : "显示全部 \(list.count) 个").font(Typo.sans(12)).foregroundStyle(Tone.clay.color)
                }
                .buttonStyle(.plain).padding(.top, 8)
            }
        } else {
            note(range == .day ? "hub 还没提供会话数据" : "hub 目前只提供「日」的会话，周和月还没有")
        }
    }

    private func sessionRow(_ x: TokenData.Session) -> some View {
        let vendor = x.tool.map(Vendor.tool)
        let title = x.title.flatMap { $0.isEmpty ? nil : $0 }
        return HStack(spacing: 10) {
            VendorMark(vendor: vendor, size: 14).frame(width: 16)
            Group {
                if let title {
                    Text(title).foregroundStyle(Palette.ink)
                } else {
                    Text("\(x.model ?? "会话") · \(String(x.id.suffix(6)))").foregroundStyle(Palette.ink3)
                }
            }
            .font(Typo.sans(12.5)).lineLimit(1).layoutPriority(1).help(title ?? x.id)
            Spacer(minLength: 8)
            Text([vendor?.label, title == nil ? nil : x.model, x.device].compactMap { $0 }.joined(separator: " · "))
                .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1)
            Text(x.total.map(TokenFormat.short) ?? "—").font(Typo.sans(12)).monospacedDigit().frame(width: 58, alignment: .trailing)
            Text(x.cost.map { "$" + Fmt.number($0, $0 >= 100 ? 0 : 2) } ?? "—").font(Typo.sans(12)).foregroundStyle(Palette.ink2).monospacedDigit()
                .frame(width: 62, alignment: .trailing)
            Text(x.updatedAt.map { HubFormat.ago($0) } ?? "").font(Typo.sans(11)).foregroundStyle(Palette.ink4).frame(width: 64, alignment: .trailing)
        }
        .padding(.vertical, 8)
    }

    private func note(_ text: String) -> some View {
        Text(text).font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6)
    }

    private var limits: some View {
        let all = TokenTone.visible(state.hub.data.token[.day]?.data?.limits ?? [])
        return VStack(alignment: .leading, spacing: 0) {
            SectionTitle("额度 · 实时")
            if all.isEmpty {
                note("来源暂无额度信息")
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 236), spacing: 10, alignment: .top)], alignment: .leading, spacing: 10) {
                    ForEach(Array(all.enumerated()), id: \.offset) { i, l in
                        LimitTile(limit: l, subtitle: TokenTone.subtitle(l, in: all), index: i)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// One quota: the tool's mark and account, its two busiest windows, and when the busiest resets.
private struct LimitTile: View {
    var limit: TokenData.Limit
    var subtitle: String?
    var index: Int

    var body: some View {
        let vendor = Vendor.tool(limit.tool)
        let windows = Array(limit.windows.prefix(2))
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 7) {
                VendorMark(vendor: vendor, size: 15)
                Text(vendor.label).font(Typo.sans(12.5, .semibold)).lineLimit(1).fixedSize()
                if let subtitle { Text(subtitle).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1).truncationMode(.middle) }
                Spacer(minLength: 0)
            }
            ForEach(Array(windows.enumerated()), id: \.offset) { i, w in
                let pct = w.percent ?? 0
                HStack(spacing: 8) {
                    Text(w.label).font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(1).frame(width: 82, alignment: .leading)
                    Track(value: pct, color: vendor.color, height: 5, delay: Double(index * 2 + i) * 70)
                    Text("\(Int(pct))%").font(Typo.sans(11.5, .medium)).monospacedDigit()
                        .foregroundStyle(pct >= 85 ? Tone.rose.color : Palette.ink)
                        .frame(width: 34, alignment: .trailing)
                }
                .help(TokenTone.resets(w.resetsAt) ?? w.label)
            }
            let more = limit.windows.count - windows.count
            Text([TokenTone.resets(windows.first?.resetsAt), more > 0 ? "另 \(more) 个窗口" : nil].compactMap { $0 }.joined(separator: " · "))
                .font(Typo.sans(10.5)).foregroundStyle(Palette.ink4).lineLimit(1)
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
    }
}

/// GitHub-style year of days: Monday-first weeks as columns, square cells up to 20pt.
struct HistoryHeatmap: View {
    var year: TokenHistory.Year
    var maxValue: Double
    @ViewState private var hovered: (week: Int, day: Int)?

    init(year: TokenHistory.Year, maxValue: Double, hovered: (week: Int, day: Int)? = nil) {
        self.year = year
        self.maxValue = maxValue
        _hovered = ViewState(initialValue: hovered)
    }
    @ViewState private var shown: CGFloat = AppState.isQA ? 1 : 0
    @ViewState private var width: CGFloat = 0

    private let gap: CGFloat = 3, labelWidth: CGFloat = 20, monthHeight: CGFloat = 16
    private static let rows = ["一", "", "三", "", "五", "", "日"]

    private func cell(_ width: CGFloat) -> CGFloat {
        max(6, min(20, (width - labelWidth - gap * CGFloat(year.weeks.count - 1)) / CGFloat(year.weeks.count)))
    }

    var body: some View {
        let c = cell(width), step = c + gap
        let gridWidth = CGFloat(year.weeks.count) * step - gap, gridHeight = 7 * step - gap
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .topLeading) {
                ForEach(year.months, id: \.week) { m in
                    Text("\(m.month)月").font(Typo.sans(10)).foregroundStyle(Palette.ink4).fixedSize()
                        .offset(x: labelWidth + CGFloat(m.week) * step)
                }
            }
            .frame(height: monthHeight, alignment: .topLeading)
            HStack(alignment: .top, spacing: 0) {
                VStack(alignment: .leading, spacing: gap) {
                    ForEach(Self.rows.indices, id: \.self) { r in
                        Text(Self.rows[r]).font(Typo.sans(10)).foregroundStyle(Palette.ink4).frame(height: c)
                    }
                }
                .frame(width: labelWidth, alignment: .leading)
                Canvas { ctx, _ in
                    for (w, week) in year.weeks.enumerated() {
                        for (d, cellData) in week.enumerated() {
                            let rect = CGRect(x: CGFloat(w) * step, y: CGFloat(d) * step, width: c, height: c)
                            let path = Path(roundedRect: rect, cornerRadius: min(3, c / 4))
                            if let day = cellData.day {
                                let level = Self.level(day.total, maxValue)
                                ctx.fill(path, with: .color(Palette.heat[level].opacity(0.25 + 0.75 * shown)))
                            } else {
                                ctx.stroke(path, with: .color(Palette.line.opacity(0.7)), lineWidth: 0.8)
                            }
                            if let h = hovered, h.week == w, h.day == d {
                                ctx.stroke(Path(roundedRect: rect.insetBy(dx: -1, dy: -1), cornerRadius: min(4, c / 3)), with: .color(Palette.ink.opacity(0.7)), lineWidth: 1.2)
                            }
                        }
                    }
                }
                .frame(width: gridWidth, height: gridHeight)
                .contentShape(Rectangle())
                .onContinuousHover(coordinateSpace: .local) { phase in
                    switch phase {
                    case .active(let p):
                        let w = Int(p.x / step), d = Int(p.y / step)
                        let inside = year.weeks.indices.contains(w) && (0..<7).contains(d) && p.x - CGFloat(w) * step <= c && p.y - CGFloat(d) * step <= c
                        if inside { hovered = (w, d) } else if !(year.weeks.indices.contains(w) && (0..<7).contains(d)) { hovered = nil }
                    case .ended: hovered = nil
                    }
                }
                .overlay {
                    if let h = hovered { tooltip(h, step: step, c: c, gridWidth: gridWidth) }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onGeometryChange(for: CGFloat.self, of: { $0.size.width }) { width = $0 }
        .onAppear { withAnimation(.easeOut(duration: 0.6)) { shown = 1 } }
    }

    static func level(_ v: Double?, _ maxValue: Double) -> Int {
        guard let v, v > 0, maxValue > 0 else { return 0 }
        switch v / maxValue {
        case ..<0.15: return 1
        case ..<0.35: return 2
        case ..<0.55: return 3
        case ..<0.8: return 4
        default: return 5
        }
    }

    /// Sits above the hovered cell (below it on the top rows) so it never covers the pointer.
    @ViewBuilder private func tooltip(_ h: (week: Int, day: Int), step: CGFloat, c: CGFloat, gridWidth: CGFloat) -> some View {
        let cellData = year.weeks[h.week][h.day]
        let date = "\(HubFormat.md(cellData.date)) \(HubFormat.weekday(cellData.date))"
        let text = cellData.day.map { d in
            [date, d.total.map(TokenFormat.short) ?? "无记录", d.cost.map { "$" + Fmt.number($0, $0 >= 100 ? 0 : 2) }].compactMap { $0 }.joined(separator: " · ")
        } ?? date + " · 未接入"
        let below = h.day < 2
        let x = CGFloat(h.week) * step + c / 2
        let estimated = CGFloat(text.count) * 6.2 + 18
        let center = min(max(x, estimated / 2), gridWidth - estimated / 2)
        Text(text).font(Typo.sans(11)).foregroundStyle(.white).fixedSize()
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(RoundedRectangle(cornerRadius: 6).fill(Palette.ink))
            .position(x: center, y: below ? CGFloat(h.day) * step + c + 19 : CGFloat(h.day) * step - 19)
            .allowsHitTesting(false)
    }
}

/// Daily totals as an area with a dashed seven-day mean; hovering shows the day.
struct TokenTrend: View {
    var history: TokenHistory
    @ViewState private var hovered: Int?
    @ViewState private var shown: CGFloat = AppState.isQA ? 1 : 0

    var body: some View {
        let values = history.days.map { $0.total ?? 0 }
        let avg = history.movingAverage(7)
        let top = max(values.max() ?? 1, 0.000_001) * 1.08
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { geo in
                let w = geo.size.width, h = geo.size.height
                let x = { (i: Int) in values.count > 1 ? CGFloat(i) / CGFloat(values.count - 1) * w : w / 2 }
                let y = { (v: Double) in h - CGFloat(v / top) * h * shown }
                ZStack(alignment: .topLeading) {
                    Canvas { ctx, _ in
                        for k in 1...3 {
                            let gy = h * CGFloat(k) / 4
                            ctx.stroke(Path { $0.move(to: CGPoint(x: 0, y: gy)); $0.addLine(to: CGPoint(x: w, y: gy)) }, with: .color(Palette.line2), lineWidth: 1)
                        }
                        var line = Path(), area = Path(), mean = Path()
                        for (i, v) in values.enumerated() {
                            let p = CGPoint(x: x(i), y: y(v))
                            if i == 0 { line.move(to: p); area.move(to: CGPoint(x: p.x, y: h)); area.addLine(to: p) } else { line.addLine(to: p); area.addLine(to: p) }
                            let m = CGPoint(x: x(i), y: y(avg[i]))
                            if i == 0 { mean.move(to: m) } else { mean.addLine(to: m) }
                        }
                        area.addLine(to: CGPoint(x: x(values.count - 1), y: h))
                        area.closeSubpath()
                        ctx.fill(area, with: .linearGradient(Gradient(colors: [Tone.clay.color.opacity(0.24), Tone.clay.color.opacity(0.02)]),
                                                             startPoint: .zero, endPoint: CGPoint(x: 0, y: h)))
                        ctx.stroke(line, with: .color(Tone.clay.color.opacity(values.count > 90 ? 0.4 : 0.9)), style: StrokeStyle(lineWidth: 1, lineJoin: .round))
                        ctx.stroke(mean, with: .color(Palette.heat[5]), style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round))
                        if let i = hovered {
                            ctx.stroke(Path { $0.move(to: CGPoint(x: x(i), y: 0)); $0.addLine(to: CGPoint(x: x(i), y: h)) }, with: .color(Palette.ink4), lineWidth: 1)
                            ctx.fill(Path(ellipseIn: CGRect(x: x(i) - 3.5, y: y(values[i]) - 3.5, width: 7, height: 7)), with: .color(Tone.clay.color))
                        }
                    }
                    Color.clear.contentShape(Rectangle()).onContinuousHover { phase in
                        switch phase {
                        case .active(let p): hovered = values.isEmpty ? nil : min(values.count - 1, max(0, Int((p.x / max(w, 1) * CGFloat(values.count - 1)).rounded())))
                        case .ended: hovered = nil
                        }
                    }
                    if let i = hovered {
                        let d = history.days[i]
                        Text([HubFormat.md(d.date) + " " + HubFormat.weekday(d.date), d.total.map(TokenFormat.short) ?? "无记录",
                              "7 日均 " + TokenFormat.short(avg[i]), d.cost.map { "$" + Fmt.number($0, $0 >= 100 ? 0 : 2) }].compactMap { $0 }.joined(separator: " · "))
                            .font(Typo.sans(11)).foregroundStyle(.white).fixedSize()
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Palette.ink))
                            .position(x: min(max(x(i), 110), w - 110), y: 12)
                            .allowsHitTesting(false)
                    }
                }
            }
            HStack {
                Text(HubFormat.ymd(history.first))
                Spacer()
                HStack(spacing: 4) {
                    RoundedRectangle(cornerRadius: 1).fill(Tone.clay.color.opacity(0.5)).frame(width: 14, height: 1.5)
                    Text("每日").padding(.trailing, 8)
                    RoundedRectangle(cornerRadius: 1).fill(Palette.heat[5]).frame(width: 14, height: 2.5)
                    Text("7 日均线")
                }
                Spacer()
                Text("今天")
            }
            .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
        }
        .onAppear { withAnimation(.easeOut(duration: 0.7)) { shown = 1 } }
    }
}

struct HeatLegend: View {
    var body: some View {
        HStack(spacing: 3) {
            Text("少").padding(.trailing, 2)
            ForEach(Palette.heat.indices, id: \.self) { RoundedRectangle(cornerRadius: 2).fill(Palette.heat[$0]).frame(width: 10, height: 10) }
            Text("多").padding(.leading, 2)
        }
        .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
    }
}

/// Drawn in one canvas with a single hover tracker: hundreds of cell views, each with its own
/// tooltip and hover handler, made the token page stutter.
struct TokenHeatmapView: View {
    var map: TokenHeatmap
    @ViewState private var hovered: Cell?
    @ViewState private var shown: CGFloat = 0

    struct Cell: Equatable { var row: Int, column: Int }

    /// Cells stretch horizontally; heights are tuned per range so they read as roughly square at module widths.
    private var cellHeight: CGFloat { map.dense ? 9 : map.columns >= 30 ? 16 : 20 }
    private var gap: CGFloat { map.dense ? 2 : 3 }
    private var labelWidth: CGFloat { map.dense ? 28 : 78 }
    private var gridHeight: CGFloat { CGFloat(map.rowLabels.count) * (cellHeight + gap) - gap }

    var body: some View {
        VStack(alignment: .leading, spacing: gap + 2) {
            HStack(alignment: .top, spacing: gap) {
                VStack(alignment: .leading, spacing: gap) {
                    ForEach(map.rowLabels.indices, id: \.self) { r in
                        Text(map.rowLabels[r]).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
                            .frame(width: labelWidth, height: cellHeight, alignment: .leading)
                    }
                }
                HeatCanvas(map: map, cellHeight: cellHeight, gap: gap, hovered: hovered, shown: shown)
                    .frame(height: gridHeight)
                    .overlay {
                        GeometryReader { geo in
                            ZStack {
                                Color.clear.contentShape(Rectangle())
                                    .onContinuousHover { phase in
                                        switch phase {
                                        case .active(let p):
                                            let c = cell(at: p, width: geo.size.width)
                                            if c != hovered { hovered = c }
                                        case .ended: hovered = nil
                                        }
                                    }
                                tooltip(in: geo.size)
                            }
                        }
                    }
            }
            HStack(spacing: gap) {
                Color.clear.frame(width: labelWidth, height: 1)
                ForEach(0..<map.columns, id: \.self) { c in
                    Text(map.columnLabels[c]).font(Typo.sans(10)).foregroundStyle(Palette.ink4).fixedSize()
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .frame(height: 14)
        }
        .onAppear { withAnimation(.easeOut(duration: 0.6)) { shown = 1 } }
    }

    private func cellWidth(_ width: CGFloat) -> CGFloat {
        max(1, (width - gap * CGFloat(map.columns - 1)) / CGFloat(max(1, map.columns)))
    }

    private func cell(at p: CGPoint, width: CGFloat) -> Cell? {
        let w = cellWidth(width)
        let c = Int(p.x / (w + gap)), r = Int(p.y / (cellHeight + gap))
        guard map.values.indices.contains(r), (0..<map.columns).contains(c) else { return nil }
        return Cell(row: r, column: c)
    }

    @ViewBuilder private func tooltip(in size: CGSize) -> some View {
        if let h = hovered {
            let w = cellWidth(size.width), v = map.values[h.row][h.column]
            let text = map.tips[h.row][h.column] + (v.map { " · " + TokenFormat.short($0) } ?? " · 暂无数据")
            let x = CGFloat(h.column) * (w + gap) + w / 2, y = CGFloat(h.row) * (cellHeight + gap)
            Text(text).font(Typo.sans(11)).foregroundStyle(.white).fixedSize()
                .padding(.horizontal, 8).padding(.vertical, 4)
                .background(RoundedRectangle(cornerRadius: 6).fill(Palette.ink))
                .position(x: min(max(x, 70), size.width - 70), y: max(10, y - 14))
                .allowsHitTesting(false)
        }
    }
}

private struct HeatCanvas: View {
    var map: TokenHeatmap
    var cellHeight: CGFloat
    var gap: CGFloat
    var hovered: TokenHeatmapView.Cell?
    var shown: CGFloat

    var body: some View {
        Canvas { ctx, size in
            let columns = max(1, map.columns)
            let w = max(1, (size.width - gap * CGFloat(columns - 1)) / CGFloat(columns))
            let radius: CGFloat = map.dense ? 2 : 3
            for r in map.values.indices {
                for c in 0..<map.columns {
                    let rect = CGRect(x: CGFloat(c) * (w + gap), y: CGFloat(r) * (cellHeight + gap), width: w, height: cellHeight)
                    let lv = map.level(map.values[r][c])
                    let path = Path(roundedRect: rect, cornerRadius: radius)
                    if lv < 0 {
                        ctx.stroke(Path(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), cornerRadius: radius), with: .color(Palette.line2), lineWidth: 1)
                    } else {
                        ctx.fill(path, with: .color(Palette.heat[lv].opacity(Double(shown))))
                    }
                    if hovered == TokenHeatmapView.Cell(row: r, column: c) {
                        ctx.stroke(Path(roundedRect: rect.insetBy(dx: -1.5, dy: -1.5), cornerRadius: radius + 1), with: .color(Palette.ink2), lineWidth: 1.5)
                    }
                }
            }
        }
    }
}

// MARK: - GitHub

struct GitModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        HubGate(envelope: state.hub.data.git, unconfigured: "GitHub 尚未接入\n需要在 hub 上配置只读令牌") { g in
            if size == .compact { compact(g) } else { detail(g) }
        }
    }

    private func age(_ d: Date?) -> Int { HubFormat.days(since: d) ?? 0 }

    private func compact(_ g: GitData) -> some View {
        let waiting = g.waiting ?? [], blocked = g.blocked ?? []
        let oldest = blocked.map { age($0.since) }.max() ?? 0
        return VStack(alignment: .leading, spacing: 0) {
            Hero(value: Double(waiting.count), unit: "条等你回复 · \(blocked.count) 个 PR 阻塞")
            Spacer(minLength: 6)
            if let w = waiting.first {
                miniRow(Self.kindLabel(w.kind), w.title, HubFormat.ago(w.since).replacingOccurrences(of: "前", with: ""), Self.kindTone(w.kind).color, Palette.ink3)
            }
            if let b = blocked.first {
                miniRow(Self.reasonLabel(b.reason), b.title, "\(age(b.since)) 天", Self.reasonTone(b.reason).color, ageColor(age(b.since)))
            }
            Text("最久阻塞 \(oldest) 天 · 今日提交 \(g.activity?.commitsToday.map(String.init) ?? "—")")
                .font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
        }
    }

    private func detail(_ g: GitData) -> some View {
        let waiting = g.waiting ?? [], blocked = g.blocked ?? []
        let oldest = blocked.map { age($0.since) }.max() ?? 0
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                gitKPI("等我回复") { Hero(value: Double(waiting.count), unit: "条", size: 30) }
                gitKPI("我的 PR 阻塞", divider: true) { Hero(value: Double(blocked.count), unit: "个", size: 30) }
                gitKPI("最久阻塞", divider: true) { valueText("\(oldest)", "天", oldest >= 7 ? Tone.rose.color : Palette.ink) }
                gitKPI("今日提交", divider: true) {
                    valueText(g.activity?.commitsToday.map(String.init) ?? "—", g.activity?.streakDays.map { "· 连续 \($0) 天" } ?? "", Palette.ink)
                }
            }
            HubScroll {
                AdaptiveRow(threshold: 360 * 2 + 28, spacing: 28) {
                    waitList(waiting)
                    blockedList(blocked)
                }
                .padding(.top, 2).padding(.bottom, 6)
            }
            .frame(maxHeight: .infinity)
            .overlay(alignment: .bottom) {
                LinearGradient(colors: [Palette.card.opacity(0), Palette.card], startPoint: .top, endPoint: .bottom)
                    .frame(height: 20).allowsHitTesting(false)
            }
            if let a = g.activity {
                Text(["近 30 天 \(a.commits30d.map(String.init) ?? "—") 次提交", a.repos30d.map { "\($0) 个仓库" }].compactMap { $0 }.joined(separator: " · "))
                    .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.top, 14)
            }
        }
    }

    private func miniRow(_ kind: String, _ title: String, _ age: String, _ dot: Color, _ ageTint: Color) -> some View {
        HStack(spacing: 8) {
            Circle().fill(dot).frame(width: 7, height: 7)
            Text("\(kind) · \(title)").font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1)
            Spacer(minLength: 4)
            Text(age).font(Typo.sans(11, .semibold)).foregroundStyle(ageTint).monospacedDigit()
        }
        .padding(.top, 7)
    }

    private func gitKPI(_ label: String, divider: Bool = false, @ViewBuilder _ content: () -> some View) -> some View {
        HStack(spacing: 14) {
            if divider { Rectangle().fill(Palette.line2).frame(width: 1, height: 44) }
            VStack(alignment: .leading, spacing: 4) { Label11(label); content() }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity)
    }

    private func valueText(_ v: String, _ unit: String, _ color: Color) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 4) {
            Text(v).font(Typo.serif(20)).foregroundStyle(color).monospacedDigit()
            Text(unit).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
        }
    }

    private func waitList(_ waiting: [GitData.Waiting]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("等我回复 · \(waiting.count)")
            if waiting.isEmpty { Text("没有等你回复的").font(Typo.sans(12)).foregroundStyle(Palette.ink3) }
            ForEach(Array(waiting.enumerated()), id: \.1.id) { i, w in
                let tone = Self.kindTone(w.kind)
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: Self.kindSymbol(w.kind)).font(.system(size: 12, weight: .medium)).foregroundStyle(tone.color)
                        .frame(width: 28, height: 28).background(RoundedRectangle(cornerRadius: 9).fill(tone.tint))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(w.title).font(Typo.sans(13, .medium)).lineLimit(1)
                        HStack(spacing: 8) {
                            PRRef(repo: w.repo, number: w.number)
                            Text([Self.kindLabel(w.kind), w.who, HubFormat.ago(w.since)].compactMap { $0 }.joined(separator: " · "))
                                .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1)
                        }
                        if let q = w.quote, !q.isEmpty {
                            Text(q).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(2)
                                .padding(.horizontal, 10).padding(.vertical, 6)
                                .background(UnevenRoundedRectangle(cornerRadii: .init(bottomTrailing: 8, topTrailing: 8)).fill(Palette.bg))
                                .overlay(alignment: .leading) { Rectangle().fill(Palette.line).frame(width: 2) }
                                .padding(.top, 4)
                        }
                    }
                    Spacer(minLength: 4)
                    if let url = w.url.flatMap(URL.init(string:)) {
                        Button { NSWorkspace.shared.open(url) } label: { Chip(text: (w.kind == "review" ? "去 review" : "去回复") + " ↗") }.buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 11)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                .rise(i)
            }
        }
    }

    private func blockedList(_ blocked: [GitData.Blocked]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("我的 PR 阻塞 · \(blocked.count)")
            if blocked.isEmpty { Text("没有阻塞的 PR").font(Typo.sans(12)).foregroundStyle(Palette.ink3) }
            ForEach(Array(blocked.enumerated()), id: \.1.id) { i, b in
                let tone = Self.reasonTone(b.reason), days = age(b.since)
                HStack(alignment: .top, spacing: 12) {
                    Text(Self.reasonLabel(b.reason)).font(Typo.sans(11, .semibold)).foregroundStyle(tone.color)
                        .frame(minWidth: 72).padding(.horizontal, 8).padding(.vertical, 4)
                        .background(RoundedRectangle(cornerRadius: 7).fill(tone.tint))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(b.title).font(Typo.sans(13, .medium)).lineLimit(1)
                        HStack(spacing: 8) {
                            PRRef(repo: b.repo, number: b.number)
                            if let d = b.detail { Text(d).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1) }
                        }
                    }
                    Spacer(minLength: 4)
                    Text(days == 0 ? HubFormat.ago(b.since) : "\(days) 天").font(Typo.sans(12, days >= 7 ? .semibold : .regular))
                        .foregroundStyle(ageColor(days)).monospacedDigit().padding(.top, 3)
                }
                .padding(.vertical, 11)
                .contentShape(Rectangle())
                .onTapGesture { if let url = b.url.flatMap(URL.init(string:)) { NSWorkspace.shared.open(url) } }
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                .rise(i + 3)
            }
        }
    }

    private func ageColor(_ days: Int) -> Color {
        days >= 7 ? Tone.rose.color : days >= 2 ? Tone.ochre.color : Palette.ink3
    }

    static func kindLabel(_ kind: String) -> String {
        ["reply": "评论回复", "review": "请求 review", "mention": "@提及"][kind] ?? kind
    }
    static func kindTone(_ kind: String) -> Tone {
        ["reply": .sky, "review": .plum, "mention": .ochre][kind] ?? .sky
    }
    static func kindSymbol(_ kind: String) -> String {
        ["reply": "bubble.left", "review": "eye", "mention": "at"][kind] ?? "bubble.left"
    }
    static func reasonLabel(_ reason: String) -> String {
        ["ci_failed": "CI 失败", "changes_requested": "要求修改", "conflict": "有冲突", "no_review": "等 review"][reason] ?? reason
    }
    static func reasonTone(_ reason: String) -> Tone {
        ["ci_failed": .rose, "changes_requested": .ochre, "conflict": .plum, "no_review": .steel][reason] ?? .steel
    }
}

struct PRRef: View {
    var repo: String
    var number: Int

    var body: some View {
        (Text(repo.replacingOccurrences(of: "ump45nose/", with: "")).foregroundColor(Palette.ink2)
            + Text("#\(String(number))").fontWeight(.semibold).foregroundColor(Palette.ink))
            .font(Typo.mono(11))
            .lineLimit(1).fixedSize()
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(RoundedRectangle(cornerRadius: 5).fill(Palette.sunk))
    }
}

// MARK: - 网络

struct NetModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        HubGate(envelope: state.hub.data.net) { n in
            if size == .compact { compact(n) } else { detail(n) }
        }
    }

    @ViewState private var editing = false

    private struct PoolView {
        var name: String, used: Double?, total: Double, daysLeft: Int?, expires: String?, periodEnd: String?
        var remaining: Double? { used.map { max(0, total - $0) } }
        var pct: Double { total > 0 ? min(100, (used ?? 0) / total * 100) : 0 }
    }

    private func pools(_ n: NetData) -> [PoolView] {
        (n.pools ?? []).compactMap { p in
            guard let total = p.totalBytes, total > 0 else { return nil }
            let left = HubFormat.day(p.expiresOn).flatMap { d in Calendar.hub.dateComponents([.day], from: Calendar.hub.startOfDay(for: HubFormat.current()), to: d).day }
            return PoolView(name: p.name, used: p.usedBytes.map { $0 / 1_073_741_824 }, total: total / 1_073_741_824,
                            daysLeft: left, expires: p.expiresOn, periodEnd: p.periodEnd)
        }
    }

    private var editButton: some View {
        Button { editing = true } label: {
            Label("管理订阅", systemImage: "slider.horizontal.3").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
        }
        .buttonStyle(.plain)
        .popover(isPresented: $editing, arrowEdge: .bottom) { SubscriptionManager { editing = false }.environment(state) }
    }

    private func usageTone(_ pct: Double) -> Tone { pct >= 90 ? .rose : pct >= 75 ? .ochre : .sage }

    @ViewBuilder private func compact(_ n: NetData) -> some View {
        if let p = pools(n).first {
            VStack(spacing: 0) {
                ZStack(alignment: .bottom) {
                    ArcGauge(value: p.pct, color: usageTone(p.pct).color)
                    VStack(spacing: 0) {
                        HStack(alignment: .firstTextBaseline, spacing: 2) {
                            if let used = p.used { CountUp(value: used).font(Typo.serif(24)) } else { Text("—").font(Typo.serif(24)) }
                            Text("/ \(Int(p.total.rounded())) GB").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                        }
                        Text("已用").font(Typo.sans(10.5)).foregroundStyle(Palette.ink3)
                    }
                }
                Spacer(minLength: 4)
                Text("\(p.name)\(p.remaining.map { " · 剩 \(HubFormat.gb($0 * 1_073_741_824, 0)) GB" } ?? "")\(p.daysLeft.map { " · \($0) 天后到期" } ?? "")")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1)
            }
            .frame(maxWidth: .infinity)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Label11("本月已用")
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(HubFormat.gb(n.monthBytes, 1)).font(Typo.serif(38)).monospacedDigit()
                    Text("GB").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
                Text("今日 \(HubFormat.gb(n.today.map { ($0.downBytes ?? 0) + ($0.upBytes ?? 0) })) GB · ↓ \(HubFormat.gb(n.today?.downBytes)) ↑ \(HubFormat.gb(n.today?.upBytes))")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 4)
                Spacer(minLength: 6)
                HStack {
                    Text("供应商套餐用量暂无数据").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                    Spacer()
                    editButton
                }
            }
        }
    }

    private func detail(_ n: NetData) -> some View {
        let hourly = n.hourly ?? []
        return VStack(alignment: .leading, spacing: 10) {
            let ps = pools(n)
            HStack {
                Text(ps.isEmpty ? "还没设置套餐总量，先显示路由器统计的实际流量" : "套餐由你在这里设置，已用来自路由器计数")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Spacer()
                editButton
            }
            ForEach(Array(ps.enumerated()), id: \.1.name) { i, p in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(p.name).font(Typo.sans(13, .semibold))
                        Spacer()
                        Text("已用").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                        if let used = p.used { CountUp(value: used, decimals: 1).font(Typo.serif(18)) } else { Text("—").font(Typo.serif(18)) }
                        Text("/ \(Int(p.total.rounded())) GB").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    }
                    Track(value: p.pct, color: usageTone(p.pct).color, delay: Double(i) * 100)
                    HStack {
                        if let r = p.remaining { Text("剩 \(String(format: "%.1f", r)) GB") } else { Text("这个重置日的已用量 hub 还算不出") }
                        if let e = p.expires { Text("· \(e) 到期") } else if let end = p.periodEnd { Text("· \(end) 重置") }
                        Spacer()
                        if let d = p.daysLeft, d > 0, let r = p.remaining { Text("日均可用 \(String(format: "%.1f", r / Double(d))) GB") }
                    }
                    .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                }
                .padding(14)
                .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
            }
            HStack {
                Stat(label: "今日下载", value: HubFormat.gb(n.today?.downBytes), unit: "GB")
                Stat(label: "今日上传", value: HubFormat.gb(n.today?.upBytes), unit: "GB")
                Stat(label: "本月", value: HubFormat.gb(n.monthBytes, 0), unit: "GB")
            }
            .padding(.top, 4)
            if !hourly.isEmpty {
                SectionTitle("今日逐小时").padding(.top, -10)
                let hours = hourly.map { Calendar.hub.component(.hour, from: $0.hour) }
                Bars(values: hourly.map { $0.bytes.map { $0 / 1_073_741_824 } }, height: 48, color: Tone.sage.color, highlight: Set(hourly.indices),
                     labels: hours.indices.map { hours[$0] % 3 == 0 || $0 == hours.count - 1 ? "\(hours[$0])" : "" })
            }
        }
    }
}

/// Traffic plans entered by hand and stored on hub-api.
// MARK: - 订阅

struct SubsModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state
    @ViewState private var editing = false

    var body: some View {
        HubGate(envelope: state.hub.data.subs, unconfigured: "独立订阅服务尚未接入") { s in
            let items = (s.items ?? []).sorted { (Self.daysUntil($0) ?? .max) < (Self.daysUntil($1) ?? .max) }
            let soon = items.filter { (Self.daysUntil($0) ?? .max) <= 7 }.count
            if size == .compact {
                VStack(alignment: .leading, spacing: 0) {
                    monthly(s)
                    Text("\(items.count) 项订阅 · 7 天内续费 \(soon) 项").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
                    HStack { Spacer(); Button("管理") { editing = true }.buttonStyle(.plain).font(Typo.sans(11)) }
                    Spacer(minLength: 6)
                    ForEach(items.prefix(2)) { sub in
                        HStack(spacing: 8) {
                            SubLogo(name: sub.name, size: 20)
                            Text(sub.name).font(Typo.sans(12.5))
                            Spacer()
                            RenewBadge(text: Self.renewText(sub), soon: (Self.daysUntil(sub) ?? .max) <= 7)
                        }
                        .padding(.top, 6)
                    }
                }
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(alignment: .lastTextBaseline) {
                        monthly(s)
                        Spacer()
                        Button("管理") { editing = true }.buttonStyle(.plain).font(Typo.sans(11))
                    }
                    .padding(.bottom, 10)
                    ForEach(Array(items.enumerated()), id: \.1.id) { i, sub in
                        HStack(spacing: 12) {
                            SubLogo(name: sub.name, size: 30)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(sub.name + ((sub.accountLabel ?? "").isEmpty ? "" : " · " + (sub.accountLabel ?? ""))).font(Typo.sans(13))
                                Text(Self.priceText(sub)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
                                if let quota = sub.quota { Text(Self.quotaText(quota)).font(Typo.sans(10)).foregroundStyle(Palette.ink3) }
                            }
                            Spacer()
                            RenewBadge(text: Self.renewText(sub), soon: (Self.daysUntil(sub) ?? .max) <= 7)
                        }
                        .padding(.vertical, 9)
                        .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                        .rise(i)
                    }
                }
            }
        }
        .popover(isPresented: $editing) { SubscriptionManager { editing = false }.environment(state) }
    }

    @ViewBuilder private func monthly(_ data: SubsData) -> some View {
        let totals = data.monthlyByCurrency ?? [:]
        VStack(alignment: .leading, spacing: 3) {
            if totals.isEmpty { Hero.empty("个人预计 / 月") }
            else {
                ForEach(totals.keys.sorted(), id: \.self) { currency in
                    Hero(value: totals[currency] ?? 0, prefix: currency + " ", unit: "/ 月")
                }
            }
            if let count = data.unclassifiedPayerCount, count > 0 {
                Text("\(count) 项付款方待确认，未计入个人费用").font(Typo.sans(10)).foregroundStyle(Palette.ink3)
            }
        }
    }

    static func quotaText(_ quota: SubscriptionQuota) -> String {
        if quota.status == "error" { return "额度获取失败 · 保留上次读数" }
        if quota.stale { return "额度读数已过期" }
        return (quota.reading?.windows ?? []).prefix(3).map { w in
            if let percent = w.usedPercent { return "\(w.label) 已用 \(Fmt.number(percent, 0))%" }
            if let remaining = w.remaining { return "\(w.label) 剩余 \(Fmt.number(remaining, 0)) \(w.unit ?? "")" }
            return w.label + " · 上限未知"
        }.joined(separator: " · ")
    }

    static func daysUntil(_ s: SubsData.Item) -> Int? {
        HubFormat.day(s.nextRenewal).flatMap { Calendar.hub.dateComponents([.day], from: Calendar.hub.startOfDay(for: HubFormat.current()), to: $0).day }
    }

    static func renewText(_ s: SubsData.Item) -> String {
        guard let d = daysUntil(s), let date = HubFormat.day(s.nextRenewal) else { return "—" }
        switch d {
        case ..<0: return "已过期"
        case 0: return "今天续费"
        case 1: return "明天续费"
        case ...7: return "\(d) 天后"
        default: return "\(Calendar.hub.component(.month, from: date))/\(Calendar.hub.component(.day, from: date))"
        }
    }

    static func priceText(_ s: SubsData.Item) -> String {
        let symbol = ["CNY": "¥", "USD": "$", "EUR": "€", "HKD": "HK$", "JPY": "¥"][s.currency ?? "CNY"] ?? (s.currency ?? "")
        let unit = ["day": "天", "week": "周", "month": "月", "year": "年", "one_time": "一次性"][s.cycle ?? ""] ?? "周期未设置"
        let frequency = (s.frequency ?? 1) > 1 ? String(s.frequency ?? 1) : ""
        let payer = ["self": "个人", "company": "公司", "other": "其他付款方", "none": "无需付费", "unknown": "付款方待确认"][s.payer ?? "unknown"] ?? ""
        return (s.price.map { $0 == 0 ? "免费" : "\(symbol)\(Fmt.number($0, $0.rounded() == $0 ? 0 : 2)) / \(frequency)\(unit)" } ?? "金额未知") + " · " + payer
    }
}

struct SubLogo: View {
    var name: String
    var size: CGFloat

    var body: some View {
        Text(String(name.prefix(1)).uppercased()).font(Typo.sans(size * 0.48, .bold)).foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(RoundedRectangle(cornerRadius: size * 0.3).fill(HubFormat.tone(for: name).color))
    }
}

struct RenewBadge: View {
    var text: String
    var soon: Bool

    var body: some View {
        Text(text).font(Typo.sans(11, soon ? .semibold : .regular)).monospacedDigit()
            .foregroundStyle(soon ? Color(hex: "#9A7414") : Palette.ink2)
            .padding(.horizontal, 8).padding(.vertical, 2.5)
            .background(Capsule().fill(soon ? Tone.ochre.tint : Palette.sunk))
    }
}
