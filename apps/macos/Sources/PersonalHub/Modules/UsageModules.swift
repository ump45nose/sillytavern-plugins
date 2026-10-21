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
                Hero(value: total, decimals: 1, unit: "M tokens" + (cost.map { " · ≈ $\(Fmt.number($0, 2))" } ?? ""))
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
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 32) {
                    main(range).frame(minWidth: 560)
                    limits.frame(width: 320)
                }
                VStack(alignment: .leading, spacing: 4) {
                    main(range)
                    limits
                }
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
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .firstTextBaseline, spacing: 4) { main.fixedSize(); note?.fixedSize() }
                    VStack(alignment: .leading, spacing: 1) { main.minimumScaleFactor(0.7); note }
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

struct TokenHeatmapView: View {
    var map: TokenHeatmap
    @ViewState private var hovered: [Int]?
    @ViewState private var shown = false

    /// Cells stretch horizontally; heights are tuned per range so they read as roughly square at module widths.
    private var cellHeight: CGFloat { map.dense ? 9 : map.columns >= 30 ? 16 : 20 }

    var body: some View {
        let gap: CGFloat = map.dense ? 2 : 3, labelWidth: CGFloat = map.dense ? 28 : 78
        VStack(alignment: .leading, spacing: gap) {
            ForEach(map.rowLabels.indices, id: \.self) { r in
                HStack(spacing: gap) {
                    Text(map.rowLabels[r]).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1).frame(width: labelWidth, alignment: .leading)
                    ForEach(0..<map.columns, id: \.self) { c in cellView(r, c) }
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
            .padding(.top, 2)
        }
        .onAppear { shown = true }
    }

    private func cellView(_ r: Int, _ c: Int) -> some View {
        let v = map.values[r][c], lv = map.level(v)
        let on = hovered == [r, c]
        return RoundedRectangle(cornerRadius: map.dense ? 2 : 3)
            .fill(lv < 0 ? Color.clear : Palette.heat[lv])
            .overlay(RoundedRectangle(cornerRadius: map.dense ? 2 : 3).strokeBorder(lv < 0 ? Palette.line2 : on ? Palette.ink2 : .clear, lineWidth: on ? 1.5 : 1))
            .frame(maxWidth: .infinity).frame(height: cellHeight)
            .scaleEffect(on ? 1.3 : 1)
            .zIndex(on ? 1 : 0)
            .opacity(shown ? 1 : 0)
            .animation(.easeOut(duration: 0.45).delay(Double(c + r * 2) * (map.dense ? 0.004 : 0.009)), value: shown)
            .animation(Motion.fast, value: on)
            .onHover { hovered = $0 ? [r, c] : (hovered == [r, c] ? nil : hovered) }
            .help(map.tips[r][c] + (v.map { " · " + TokenFormat.short($0) } ?? " · 暂无数据"))
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
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 28) { waitList(waiting).frame(minWidth: 360); blockedList(blocked).frame(minWidth: 360) }
                VStack(alignment: .leading, spacing: 0) { waitList(waiting); blockedList(blocked) }
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

    private struct PoolView {
        var name: String, remaining: Double, total: Double, daysLeft: Int?, expires: String?
        var pct: Double { total > 0 ? remaining / total * 100 : 0 }
    }

    private func pools(_ n: NetData) -> [PoolView] {
        (n.pools ?? []).compactMap { p in
            guard let used = p.usedBytes, let total = p.totalBytes, total > 0 else { return nil }
            let left = HubFormat.day(p.expiresOn).flatMap { d in Calendar.hub.dateComponents([.day], from: Calendar.hub.startOfDay(for: HubFormat.current()), to: d).day }
            return PoolView(name: p.name, remaining: max(0, total - used) / 1_073_741_824, total: total / 1_073_741_824, daysLeft: left, expires: p.expiresOn)
        }
    }

    @ViewBuilder private func compact(_ n: NetData) -> some View {
        if let p = pools(n).first {
            VStack(spacing: 0) {
                ZStack(alignment: .bottom) {
                    ArcGauge(value: p.pct, color: Tone.sage.color)
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        CountUp(value: p.remaining).font(Typo.serif(26))
                        Text("GB").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    }
                }
                Spacer(minLength: 4)
                Text("\(p.name) · 剩 \(Int(p.pct.rounded()))%\(p.daysLeft.map { " · \($0) 天后到期" } ?? "")")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            }
            .frame(maxWidth: .infinity)
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Label11("今日流量")
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(HubFormat.gb(n.today.map { ($0.downBytes ?? 0) + ($0.upBytes ?? 0) })).font(Typo.serif(38)).monospacedDigit()
                    Text("GB").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
                Text("↓ \(HubFormat.gb(n.today?.downBytes)) · ↑ \(HubFormat.gb(n.today?.upBytes)) GB").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 4)
                Spacer(minLength: 6)
                Text("本月 \(HubFormat.gb(n.monthBytes, 0)) GB · 流量包暂未接入").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }
        }
    }

    private func detail(_ n: NetData) -> some View {
        let hourly = n.hourly ?? []
        return VStack(alignment: .leading, spacing: 10) {
            let ps = pools(n)
            if ps.isEmpty {
                Text("流量包余量暂未接入，先显示实际流量").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
            ForEach(Array(ps.enumerated()), id: \.1.name) { i, p in
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(p.name).font(Typo.sans(13, .semibold))
                        Spacer()
                        CountUp(value: p.remaining, decimals: 1).font(Typo.serif(18))
                        Text("/ \(Int(p.total)) GB 剩余").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    }
                    Track(value: p.pct, color: Tone.sage.color, delay: Double(i) * 100)
                    HStack {
                        if let e = p.expires { Text("\(e) 到期") }
                        Spacer()
                        if let d = p.daysLeft, d > 0 { Text("日均可用 \(String(format: "%.1f", p.remaining / Double(d))) GB") }
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
