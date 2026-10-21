import AppKit
import HubKit
import SwiftUI

// MARK: - Token 用量

enum TokenTone {
    static func of(_ key: String) -> Tone {
        switch key.lowercased() {
        case let k where k.contains("claude"): .clay
        case let k where k.contains("codex"): .steel
        case let k where k.contains("cursor"): .ink
        case let k where k.contains("hermes"): .plum
        case let k where k.contains("gemini"): .sky
        default: HubFormat.tone(for: key)
        }
    }

    static func name(_ tool: String) -> String {
        let known = ["claude": "Claude Code", "codex": "Codex", "cursor": "Cursor", "copilot": "Copilot", "antigravity": "Antigravity", "gemini": "Gemini"]
        return known[tool.lowercased()] ?? (tool.prefix(1).uppercased() + tool.dropFirst())
    }

    /// Tools with at least one known percentage, duplicates dropped, busiest first; windows busiest first.
    static func visible(_ limits: [TokenData.Limit]) -> [TokenData.Limit] {
        var seen = Set<String>()
        return limits.compactMap { l -> TokenData.Limit? in
            var l = l
            l.windows = l.windows.filter { $0.percent != nil }.sorted { $0.percent! > $1.percent! }
            let key = l.tool.lowercased() + "|" + (l.plan ?? "") + "|" + l.windows.map { "\($0.label)=\($0.percent!)" }.joined(separator: ",")
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
        let windows = TokenTone.visible(t.limits ?? []).flatMap { l in l.windows.map { ("\(TokenTone.name(l.tool)) · \($0.label)", $0.percent ?? 0, TokenTone.of(l.tool)) } }
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
            ForEach(Array(windows), id: \.0) { label, v, tone in
                VStack(spacing: 5) {
                    HStack {
                        Text(label).foregroundStyle(Palette.ink2).lineLimit(1)
                        Spacer()
                        Text("\(Int(v))%").monospacedDigit()
                    }
                    .font(Typo.sans(11.5))
                    Track(value: v, color: tone.color, height: 4)
                }
                .padding(.top, 8)
            }
        }
    }
}

private struct TokenDetail: View {
    @Environment(AppState.self) private var state

    var body: some View {
        @Bindable var state = state
        let range = state.tokenRange
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 14) {
                Segmented(options: TokenRange.allCases.map { ($0, $0.label) }, selection: $state.tokenRange)
                if let s = state.hub.token(range) {
                    Text(s.periodLabel).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).monospacedDigit()
                }
                Spacer()
                HeatLegend()
            }
            .padding(.bottom, 18)
            AdaptiveRow(threshold: 560 + 32 + 320, spacing: 32, stackSpacing: 4) {
                main(range)
                limits.adaptiveWidth(320)
            }
        }
    }

    @ViewBuilder private func main(_ range: TokenRange) -> some View {
        if let s = state.hub.token(range) {
            summary(s)
        } else {
            HubGate(envelope: state.hub.data.token[range]) { _ in EmptyView() }.frame(minHeight: 260)
        }
    }

    private func summary(_ s: TokenRangeSummary) -> some View {
        let big = (s.total ?? 0) >= 1000
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    Label11("总量")
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        if let total = s.total {
                            CountUp(value: big ? total / 1000 : total, decimals: big ? 2 : 1).font(Typo.serif(40))
                        } else {
                            Text("—").font(Typo.serif(40)).foregroundStyle(Palette.ink3)
                        }
                        Text(big ? "B tokens" : "M tokens").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    }
                }
                .frame(minWidth: 170, alignment: .leading)
                kpi("估算成本", s.cost.map { "$" + Fmt.number($0, big ? 0 : 2) } ?? "—")
                if let delta = s.deltaPercent {
                    kpi(s.comparisonLabel, "\(delta >= 0 ? "↑" : "↓") \(abs(delta))%", color: delta >= 0 ? Tone.clay.color : Tone.olive.color)
                } else {
                    kpi(s.comparisonLabel, "—")
                }
                kpi("峰值", s.peakLabel ?? "—", small: s.peakValue.map(TokenFormat.short))
                kpi(s.averageLabel, s.average.map(TokenFormat.short) ?? "—")
            }
            .id(s.range)
            if let map = s.heatmap {
                SectionTitle("热力图 · \(map.title)")
                TokenHeatmapView(map: map).id(s.range)
            } else {
                SectionTitle("热力图")
                note("来源暂未提供这一区间的分时数据")
            }
            HStack(alignment: .top, spacing: 24) {
                parts("按工具", s.tools, tinted: true)
                parts("按设备", s.devices, tinted: false)
            }
            .id(s.range)
        }
    }

    private func parts(_ title: String, _ parts: [TokenRangeSummary.Part]?, tinted: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle(title)
            if let parts, !parts.isEmpty {
                let top = parts.compactMap(\.total).max() ?? 1
                ForEach(Array(parts.prefix(6).enumerated()), id: \.1.id) { i, p in
                    barRow(p.name, p.total, (p.total ?? 0) / max(top, 0.000_001) * 100, tinted ? TokenTone.of(p.id).color : Palette.ink2, i)
                }
            } else {
                note("来源暂只提供当日分布")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func note(_ text: String) -> some View {
        Text(text).font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6)
    }

    private func kpi(_ label: String, _ value: String, small: String? = nil, color: Color = Palette.ink) -> some View {
        HStack(spacing: 14) {
            Rectangle().fill(Palette.line2).frame(width: 1, height: 44)
            VStack(alignment: .leading, spacing: 4) {
                Label11(label)
                let main = Text(value).font(Typo.serif(20)).foregroundStyle(value == "—" ? Palette.ink3 : color).monospacedDigit().lineLimit(1)
                let note = small.map { Text($0).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    main.minimumScaleFactor(0.7).layoutPriority(1)
                    note
                }
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity)
        .rise(1)
    }

    private func barRow(_ name: String, _ v: Double?, _ pct: Double, _ color: Color, _ i: Int) -> some View {
        HStack(spacing: 10) {
            Text(name).font(Typo.sans(12)).lineLimit(1).frame(width: 90, alignment: .leading)
            Track(value: pct, color: color, delay: Double(i) * 80)
            Text(v.map(TokenFormat.short) ?? "—").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 54, alignment: .trailing)
        }
        .padding(.vertical, 5)
    }

    private var limits: some View {
        let all = TokenTone.visible(state.hub.data.token[.day]?.data?.limits ?? [])
        let limits = Array(all.prefix(4))
        let hidden = all.count - limits.count + limits.reduce(0) { $0 + max(0, $1.windows.count - 3) }
        return VStack(alignment: .leading, spacing: 10) {
            SectionTitle("额度 · 实时").padding(.bottom, -10)
            if limits.isEmpty { note("来源暂无额度信息") }
            ForEach(Array(limits.enumerated()), id: \.offset) { k, l in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(TokenTone.name(l.tool)).font(Typo.sans(12.5, .semibold))
                        Spacer()
                        if let plan = l.plan, !plan.isEmpty { Chip(text: plan) }
                    }
                    ForEach(Array(l.windows.prefix(3).indices), id: \.self) { i in
                        let w = l.windows[i]
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(w.label).font(Typo.sans(12.5))
                                Spacer()
                                Text(w.percent.map { "\(Int($0))% 已用" } ?? "—").font(Typo.serif(13)).monospacedDigit()
                            }
                            Track(value: w.percent ?? 0, color: TokenTone.of(l.tool).color, height: 8, delay: Double(k * 2 + i) * 90)
                            if let r = TokenTone.resets(w.resetsAt) { Text(r).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
                        }
                        .padding(.top, i > 0 ? 6 : 0)
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
            }
            if hidden > 0 { note("另有 \(hidden) 个额度窗口用量较低") }
        }
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
            AdaptiveRow(threshold: 360 * 2 + 28, spacing: 28) {
                waitList(waiting)
                blockedList(blocked)
            }
            .padding(.top, 2)
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
            Label("设置套餐", systemImage: "slider.horizontal.3").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
        }
        .buttonStyle(.plain)
        .popover(isPresented: $editing, arrowEdge: .bottom) { NetPlanEditor { editing = false }.environment(state) }
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
                    Text("未设置套餐总量").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
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
struct NetPlanEditor: View {
    var close: () -> Void
    /// QA: start editing these instead of loading from hub.
    var seed: [NetPlan]? = nil
    @Environment(AppState.self) private var state
    @ViewState private var plans: [NetPlan] = []
    @ViewState private var phase = Phase.loading
    @ViewState private var error: String?
    @ViewState private var saving = false

    enum Phase: Equatable { case loading, unsupported, demo, ready }

    private static let gb = 1_073_741_824.0

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("流量套餐").font(Typo.serif(20))
            switch phase {
            case .loading:
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, minHeight: 80)
            case .unsupported:
                note("hub 还没提供套餐接口（已列入 hub v2 任务），上线后在这里设置。")
            case .demo:
                note("示例模式不会保存，连接 hub 后可以设置。")
            case .ready:
                ForEach($plans) { $plan in row($plan) }
                if plans.count < 5 {
                    Button { plans.append(NetPlan(name: plans.isEmpty ? "主套餐" : "套餐 \(plans.count + 1)", totalBytes: 200 * Self.gb)) } label: {
                        Label("添加套餐", systemImage: "plus").font(Typo.sans(12.5))
                    }
                    .buttonStyle(.hubSecondary)
                }
                Text("已用按路由器计数统计；多个套餐共用同一个计数。").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            }
            if let error { Text(error).font(Typo.sans(12)).foregroundStyle(Tone.rose.color) }
            HStack {
                Button("取消", action: close).buttonStyle(.hubSecondary)
                Spacer()
                if phase == .ready {
                    Button(saving ? "保存中…" : "保存", action: save).buttonStyle(.hubPrimary).keyboardShortcut(.defaultAction)
                        .disabled(saving || plans.contains { $0.name.trimmingCharacters(in: .whitespaces).isEmpty || $0.totalBytes <= 0 })
                }
            }
        }
        .padding(20)
        .frame(width: 400)
        .background(Palette.card)
        .task { await load() }
    }

    private func note(_ text: String) -> some View {
        Text(text).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).lineSpacing(3)
            .padding(12).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
    }

    private func row(_ plan: Binding<NetPlan>) -> some View {
        let total = Binding(get: { plan.wrappedValue.totalBytes / Self.gb }, set: { plan.wrappedValue.totalBytes = max(0, $0) * Self.gb })
        let expires = Binding(get: { HubFormat.day(plan.wrappedValue.expiresOn) },
                              set: { plan.wrappedValue.expiresOn = $0.map { ReviewText.dayKey($0) } })
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                TextField("名称", text: plan.name).textFieldStyle(.plain).font(Typo.sans(13, .semibold))
                Button { plans.removeAll { $0.id == plan.wrappedValue.id } } label: {
                    Image(systemName: "trash").font(.system(size: 11)).foregroundStyle(Palette.ink3)
                }
                .buttonStyle(.plain).help("删除这个套餐")
            }
            HStack(spacing: 14) {
                field("总量") {
                    TextField("", value: total, format: .number.precision(.fractionLength(0...1))).textFieldStyle(.plain)
                        .font(Typo.sans(13)).monospacedDigit().frame(width: 60)
                    Text("GB").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                }
                field("每月") {
                    ForEach([-1, 1], id: \.self) { step in
                        let next = plan.wrappedValue.resetDay + step
                        Button { plan.wrappedValue.resetDay = next } label: {
                            Image(systemName: step < 0 ? "minus" : "plus").font(.system(size: 9, weight: .bold)).foregroundStyle(Palette.ink2)
                                .frame(width: 20, height: 22).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain).disabled(!(1...28).contains(next))
                        if step < 0 { Text(verbatim: "\(plan.wrappedValue.resetDay) 日重置").font(Typo.sans(12.5)).monospacedDigit().frame(minWidth: 58) }
                    }
                }
            }
            HStack(spacing: 8) {
                Text("到期").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                ExpiryButton(date: expires)
                if expires.wrappedValue != nil {
                    Button("不设到期") { expires.wrappedValue = nil }.buttonStyle(.plain).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.line2))
    }

    private func field(_ label: String, @ViewBuilder _ content: () -> some View) -> some View {
        HStack(spacing: 6) {
            Text(label).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            content()
        }
        .padding(.horizontal, 10).frame(height: 30)
        .background(RoundedRectangle(cornerRadius: 8).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.line))
    }

    private func load() async {
        if let seed { plans = seed; phase = .ready; return }
        guard state.hub.mode == .hub else { phase = .demo; return }
        do {
            if let items = try await state.hub.netPlans() { plans = items; phase = .ready } else { phase = .unsupported }
        } catch {
            self.error = error.localizedDescription
            phase = .unsupported
        }
    }

    private func save() {
        saving = true
        error = nil
        Task {
            defer { saving = false }
            do {
                plans = try await state.hub.saveNetPlans(plans.map { var p = $0; p.name = p.name.trimmingCharacters(in: .whitespaces); return p })
                close()
            } catch { self.error = error.localizedDescription }
        }
    }
}

private struct ExpiryButton: View {
    @Binding var date: Date?
    @ViewState private var open = false
    @ViewState private var day = Date()
    @ViewState private var month = Date()

    var body: some View {
        Button { open = true } label: {
            Chip(text: date.map { ReviewText.dayKey($0) } ?? "长期有效 · 设置到期日", tone: date == nil ? nil : .sky, systemImage: "calendar")
        }
        .buttonStyle(.plain)
        .popover(isPresented: $open, arrowEdge: .bottom) {
            VStack(spacing: 14) {
                MonthCalendar(day: $day, month: $month, today: Calendar.hub.startOfDay(for: HubFormat.current()))
                HStack {
                    Button("取消") { open = false }.buttonStyle(.hubSecondary)
                    Spacer()
                    Button("确定") { date = day; open = false }.buttonStyle(.hubPrimary).keyboardShortcut(.defaultAction)
                }
            }
            .padding(18).frame(width: 340).background(Palette.card)
            .onAppear {
                day = date ?? Calendar.hub.date(byAdding: .month, value: 1, to: HubFormat.current())!
                month = day
            }
        }
    }
}

// MARK: - 订阅

struct SubsModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        HubGate(envelope: state.hub.data.subs, unconfigured: "订阅清单尚未接入\n在 hub 的偏好里登记后显示") { s in
            let items = (s.items ?? []).sorted { (Self.daysUntil($0) ?? .max) < (Self.daysUntil($1) ?? .max) }
            let soon = items.filter { (Self.daysUntil($0) ?? .max) <= 7 }.count
            if size == .compact {
                VStack(alignment: .leading, spacing: 0) {
                    if let m = s.monthlyTotal { Hero(value: m, prefix: "¥", unit: "/ 月") } else { Hero.empty("/ 月") }
                    Text("\(items.count) 项订阅 · 7 天内续费 \(soon) 项").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
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
                        if let m = s.monthlyTotal { Hero(value: m, prefix: "¥", unit: "/ 月合计") } else { Hero.empty("/ 月合计") }
                        Spacer()
                        Text("年付已折算为月").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    }
                    .padding(.bottom, 10)
                    ForEach(Array(items.enumerated()), id: \.1.id) { i, sub in
                        HStack(spacing: 12) {
                            SubLogo(name: sub.name, size: 30)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(sub.name).font(Typo.sans(13))
                                Text(Self.priceText(sub)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
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
        let unit = s.cycle == "year" ? "年" : "月"
        return s.price.map { "\(symbol)\(Fmt.number($0, $0.rounded() == $0 ? 0 : 2)) / \(unit)" } ?? "—"
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
