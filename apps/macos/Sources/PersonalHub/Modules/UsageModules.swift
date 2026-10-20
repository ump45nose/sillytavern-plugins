import HubKit
import SwiftUI

// MARK: - Token 用量

struct TokenModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let t = state.snapshot.token
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Hero(value: t.today, decimals: 1, unit: "M tokens · ≈ $\(Fmt.number(t.cost, 2))")
                Spacer(minLength: 6)
                ForEach([("Claude Code · 本周", 61.0, Tone.clay), ("Codex · 本周", 35.0, Tone.steel)], id: \.0) { label, v, tone in
                    VStack(spacing: 5) {
                        HStack {
                            Text(label).foregroundStyle(Palette.ink2)
                            Spacer()
                            Text("\(Int(v))%").monospacedDigit()
                        }
                        .font(Typo.sans(11.5))
                        Track(value: v, color: tone.color, height: 4)
                    }
                    .padding(.top, 8)
                }
            }
        } else {
            TokenDetail()
        }
    }
}

private struct TokenDetail: View {
    @Environment(AppState.self) private var state

    var body: some View {
        @Bindable var state = state
        let s = state.tokenSummaries[state.tokenRange]!
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 14) {
                Segmented(options: TokenRange.allCases.map { ($0, $0.label) }, selection: $state.tokenRange)
                HStack(spacing: 4) {
                    Image(systemName: "chevron.left").foregroundStyle(Palette.ink3)
                    Text(s.periodLabel).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).monospacedDigit()
                    Image(systemName: "chevron.right").foregroundStyle(Palette.ink4)
                }
                .font(.system(size: 10, weight: .semibold))
                Spacer()
                HeatLegend()
            }
            .padding(.bottom, 18)
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: 32) {
                    main(s).frame(minWidth: 560)
                    limits.frame(width: 320)
                }
                VStack(alignment: .leading, spacing: 4) {
                    main(s)
                    limits
                }
            }
        }
    }

    private func main(_ s: TokenRangeSummary) -> some View {
        let big = s.total >= 1000, tools = state.snapshot.token.tools
        let toolSum = s.toolTotals.reduce(0, +)
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                VStack(alignment: .leading, spacing: 4) {
                    Label11("总量")
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        CountUp(value: big ? s.total / 1000 : s.total, decimals: big ? 2 : 1).font(Typo.serif(40))
                        Text(big ? "B tokens" : "M tokens").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    }
                }
                .frame(minWidth: 170, alignment: .leading)
                kpi("估算成本", "$" + Fmt.number(s.cost, big ? 0 : 2))
                kpi(s.comparisonLabel, "\(s.deltaPercent >= 0 ? "↑" : "↓") \(abs(s.deltaPercent))%", color: s.deltaPercent >= 0 ? Tone.clay.color : Tone.olive.color)
                kpi("峰值", s.peakLabel, small: TokenFormat.short(s.peakValue))
                kpi(s.averageLabel, TokenFormat.short(s.average))
            }
            .id(s.range)
            SectionTitle("热力图 · \(s.heatmap.title)")
            TokenHeatmapView(map: s.heatmap).id(s.range)
            HStack(alignment: .top, spacing: 24) {
                VStack(alignment: .leading, spacing: 0) {
                    SectionTitle("按工具")
                    ForEach(tools.indices, id: \.self) { i in
                        barRow(tools[i].name, s.toolTotals[i], s.toolTotals[i] / toolSum * 200, tools[i].tone.color, i)
                    }
                }
                VStack(alignment: .leading, spacing: 0) {
                    SectionTitle("按设备")
                    ForEach(state.snapshot.token.devices.indices, id: \.self) { i in
                        let d = state.snapshot.token.devices[i], v = s.total * d.today / state.snapshot.token.today
                        barRow(d.name, v, v / s.total * 100, Palette.ink2, i)
                    }
                }
            }
            .id(s.range)
        }
    }

    private func kpi(_ label: String, _ value: String, small: String? = nil, color: Color = Palette.ink) -> some View {
        HStack(spacing: 14) {
            Rectangle().fill(Palette.line2).frame(width: 1, height: 44)
            VStack(alignment: .leading, spacing: 4) {
                Label11(label)
                let main = Text(value).font(Typo.serif(20)).foregroundStyle(color).monospacedDigit().lineLimit(1)
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

    private func barRow(_ name: String, _ v: Double, _ pct: Double, _ color: Color, _ i: Int) -> some View {
        HStack(spacing: 10) {
            Text(name).font(Typo.sans(12)).frame(width: 90, alignment: .leading)
            Track(value: pct, color: color, delay: Double(i) * 80)
            Text(TokenFormat.short(v)).font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 54, alignment: .trailing)
        }
        .padding(.vertical, 5)
    }

    private var limits: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle("额度 · 实时").padding(.bottom, -10)
            ForEach(Array(state.snapshot.token.limits.enumerated()), id: \.1.id) { k, l in
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(l.tool).font(Typo.sans(12.5, .semibold))
                        Spacer()
                        Chip(text: l.plan)
                    }
                    ForEach(l.rows.indices, id: \.self) { i in
                        let r = l.rows[i]
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text(r.label).font(Typo.sans(12.5))
                                Spacer()
                                Text("\(Int(r.percent))% 已用").font(Typo.serif(13)).monospacedDigit()
                            }
                            Track(value: r.percent, color: l.tone.color, height: 8, delay: Double(k * 2 + i) * 90)
                            Text(r.reset).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                        }
                        .padding(.top, i > 0 ? 6 : 0)
                    }
                }
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
            }
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
            .help(map.tips[r][c] + (v.map { " · " + TokenFormat.short($0) } ?? " · 尚未到达"))
    }
}

// MARK: - GitHub

struct GitModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let g = state.snapshot.git, oldest = g.blocked.map(\.ageDays).max() ?? 0
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Hero(value: Double(g.waiting.count), unit: "条等你回复 · \(g.blocked.count) 个 PR 阻塞")
                Spacer(minLength: 6)
                miniRow(g.waiting[0].kind.label, g.waiting[0].title, g.waiting[0].ago.replacingOccurrences(of: "前", with: ""), g.waiting[0].kind.tone.color, Palette.ink3)
                miniRow(g.blocked[0].reason, g.blocked[0].title, "\(g.blocked[0].ageDays) 天", g.blocked[0].tone.color, ageColor(g.blocked[0].ageDays))
                Text("最久阻塞 \(oldest) 天 · 今日提交 \(g.commitsToday)").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 0) {
                    gitKPI("等我回复") { Hero(value: Double(g.waiting.count), unit: "条", size: 30) }
                    gitKPI("我的 PR 阻塞", divider: true) { Hero(value: Double(g.blocked.count), unit: "个", size: 30) }
                    gitKPI("最久阻塞", divider: true) { valueText("\(oldest)", "天", Tone.rose.color) }
                    gitKPI("今日提交", divider: true) { valueText("\(g.commitsToday)", "· 连续 \(g.streak) 天", Palette.ink) }
                }
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 28) { waitList(g).frame(minWidth: 360); blockedList(g).frame(minWidth: 360) }
                    VStack(alignment: .leading, spacing: 0) { waitList(g); blockedList(g) }
                }
                .padding(.top, 2)
                SectionTitle("提交活动 · 近半年")
                HStack(spacing: 20) {
                    ContributionGrid(weeks: 26, seed: 11, cell: 9, gap: 3)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("近 30 天 \(g.commits30) 次")
                        Text("今天 \(g.commitsToday) 次 · \(g.repos) 个仓库")
                    }
                    .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                }
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

    private func waitList(_ g: GitHubStatus) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("等我回复 · \(g.waiting.count)")
            ForEach(Array(g.waiting.enumerated()), id: \.1.id) { i, w in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: w.kind.symbol).font(.system(size: 12, weight: .medium)).foregroundStyle(w.kind.tone.color)
                        .frame(width: 28, height: 28).background(RoundedRectangle(cornerRadius: 9).fill(w.kind.tone.tint))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(w.title).font(Typo.sans(13, .medium)).lineLimit(1)
                        HStack(spacing: 8) {
                            PRRef(repo: w.repo, number: w.number)
                            Text("\(w.kind.label) · \(w.who) · \(w.ago)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1)
                        }
                        Text(w.quote).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(2)
                            .padding(.horizontal, 10).padding(.vertical, 6)
                            .background(UnevenRoundedRectangle(cornerRadii: .init(bottomTrailing: 8, topTrailing: 8)).fill(Palette.bg))
                            .overlay(alignment: .leading) { Rectangle().fill(Palette.line).frame(width: 2) }
                            .padding(.top, 4)
                    }
                    Spacer(minLength: 4)
                    Chip(text: "\(w.action) ↗")
                }
                .padding(.vertical, 11)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                .rise(i)
            }
        }
    }

    private func blockedList(_ g: GitHubStatus) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("我的 PR 阻塞 · \(g.blocked.count)")
            ForEach(Array(g.blocked.enumerated()), id: \.1.id) { i, b in
                HStack(alignment: .top, spacing: 12) {
                    Text(b.reason).font(Typo.sans(11, .semibold)).foregroundStyle(b.tone.color)
                        .frame(minWidth: 72).padding(.horizontal, 8).padding(.vertical, 4)
                        .background(RoundedRectangle(cornerRadius: 7).fill(b.tone.tint))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(b.title).font(Typo.sans(13, .medium)).lineLimit(1)
                        HStack(spacing: 8) {
                            PRRef(repo: b.repo, number: b.number)
                            Text(b.detail).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1)
                        }
                    }
                    Spacer(minLength: 4)
                    Text(b.ageText ?? "\(b.ageDays) 天").font(Typo.sans(12, b.ageDays >= 7 ? .semibold : .regular))
                        .foregroundStyle(ageColor(b.ageDays)).monospacedDigit().padding(.top, 3)
                }
                .padding(.vertical, 11)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                .rise(i + 3)
            }
        }
    }

    private func ageColor(_ days: Int) -> Color {
        days >= 7 ? Tone.rose.color : days >= 2 ? Tone.ochre.color : Palette.ink3
    }
}

extension GitWaitKind {
    var label: String {
        switch self { case .reply: "评论回复"; case .review: "请求 review"; case .mention: "@提及" }
    }
    var tone: Tone {
        switch self { case .reply: .sky; case .review: .plum; case .mention: .ochre }
    }
    var symbol: String {
        switch self { case .reply: "bubble.left"; case .review: "eye"; case .mention: "at" }
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
        let n = state.snapshot.net
        if size == .compact {
            let p = n.pools[0]
            VStack(spacing: 0) {
                ZStack(alignment: .bottom) {
                    ArcGauge(value: p.remaining / p.total * 100, color: Tone.sage.color)
                    HStack(alignment: .firstTextBaseline, spacing: 2) {
                        CountUp(value: p.remaining).font(Typo.serif(26))
                        Text("GB").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    }
                }
                Spacer(minLength: 4)
                Text("\(p.name) · 剩 \(Int((p.remaining / p.total * 100).rounded()))% · \(p.daysLeft) 天后到期")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            }
            .frame(maxWidth: .infinity)
        } else {
            VStack(alignment: .leading, spacing: 10) {
                ForEach(Array(n.pools.enumerated()), id: \.1.id) { i, p in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(p.name).font(Typo.sans(13, .semibold))
                            Spacer()
                            CountUp(value: p.remaining, decimals: 1).font(Typo.serif(18))
                            Text("/ \(Int(p.total)) GB 剩余").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                        }
                        Track(value: p.remaining / p.total * 100, color: Tone.sage.color, delay: Double(i) * 100)
                        HStack {
                            Text(p.expiry)
                            Spacer()
                            Text("日均可用 \(String(format: "%.1f", p.remaining / Double(p.daysLeft))) GB")
                        }
                        .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    }
                    .padding(14)
                    .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
                }
                HStack {
                    Stat(label: "今日下载", value: String(format: "%.1f", n.down), unit: "GB")
                    Stat(label: "今日上传", value: String(format: "%.1f", n.up), unit: "GB")
                    Stat(label: "本月", value: "\(Int(n.month))", unit: "GB")
                }
                .padding(.top, 4)
                SectionTitle("今日逐小时").padding(.top, -10)
                Bars(values: n.hourly, height: 48, color: Tone.sage.color, highlight: Set(n.hourly.indices),
                     labels: n.hourly.indices.map { $0 % 3 == 0 ? "\($0)" : ($0 == n.hourly.count - 1 ? "\($0)" : "") })
            }
        }
    }
}

// MARK: - 订阅

struct SubsModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let s = state.snapshot.subs
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Hero(value: s.monthly, prefix: "¥", unit: "/ 月")
                Text("\(s.list.count) 项订阅 · 7 天内续费 \(s.list.filter(\.soon).count) 项").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
                Spacer(minLength: 6)
                ForEach(s.list.prefix(2)) { sub in
                    HStack(spacing: 8) {
                        SubLogo(sub: sub, size: 20)
                        Text(sub.name).font(Typo.sans(12.5))
                        Spacer()
                        RenewBadge(text: sub.renew, soon: sub.soon)
                    }
                    .padding(.top, 6)
                }
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .lastTextBaseline) {
                    Hero(value: s.monthly, prefix: "¥", unit: "/ 月合计")
                    Spacer()
                    Text("年付已折算 · 汇率 7.12").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                }
                .padding(.bottom, 10)
                ForEach(Array(s.list.enumerated()), id: \.1.id) { i, sub in
                    HStack(spacing: 12) {
                        SubLogo(sub: sub, size: 30)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(sub.name).font(Typo.sans(13))
                            Text(sub.price).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
                        }
                        Spacer()
                        RenewBadge(text: sub.renew, soon: sub.soon)
                    }
                    .padding(.vertical, 9)
                    .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                    .rise(i)
                }
            }
        }
    }
}

struct SubLogo: View {
    var sub: Subscription
    var size: CGFloat

    var body: some View {
        Text(sub.glyph).font(Typo.sans(size * 0.48, .bold)).foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(RoundedRectangle(cornerRadius: size * 0.3).fill(Color(hex: sub.color)))
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
