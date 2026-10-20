import HubKit
import SwiftUI

// MARK: - 今日简报

struct BriefModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let d = state.snapshot
        if size == .compact {
            HStack(alignment: .bottom) {
                VStack(alignment: .leading, spacing: 4) {
                    Label11("\(d.now.date) · \(d.now.week)")
                    Text("下午好，玮康").font(Typo.serif(30))
                }
                Spacer()
                Text(([Self.dueLine(state.agenda.view)] + [Self.eventLine(state.agenda.view)].compactMap { $0 } + ["日报待确认"]).joined(separator: " · "))
                    .font(Typo.serif(15)).foregroundStyle(Palette.ink2)
            }
            .padding(.trailing, 70)
        } else {
            HStack(alignment: .bottom, spacing: 40) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 10) {
                        Label11("\(d.now.date) · \(d.now.week)")
                        Chip(text: "第 \(d.cycle.index) 阶段 · 第 \(d.cycle.day) 天", tone: .clay)
                    }
                    Text("下午好，玮康").font(Typo.serif(44)).tracking(-0.8)
                    Text(summary)
                        .font(Typo.serif(18.5)).foregroundStyle(Palette.ink2).lineSpacing(6)
                        .tint(Palette.clayDeep)
                        .environment(\.openURL, OpenURLAction { url in
                            if let m = ModuleID(rawValue: url.host() ?? "") { state.focus(m) }
                            return .handled
                        })
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .leading, spacing: 8) {
                    CommandBar()
                    HStack {
                        Text("试试「明天下午3点 评审 #工作」")
                        Spacer()
                        Text("⌘K 搜索全部")
                    }
                    .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.horizontal, 4)
                }
                .frame(width: 420)
            }
            .padding(.trailing, 4).padding(.top, 2)
        }
    }

    private var summary: AttributedString {
        let v = state.agenda.view
        var s = AttributedString()
        if v.dueCount == 0 {
            s += AttributedString("今天的任务都完成了；")
        } else {
            s += AttributedString("今天有 ")
            s += link("\(v.dueCount) 项任务", .agenda)
            s += AttributedString(v.overdue.isEmpty ? "到期；" : "到期，其中 \(v.overdue.count) 项已经逾期；")
        }
        if let e = v.currentEvent {
            s += AttributedString("「\(e.title)」正在进行，")
            s += link(Agenda.clock(e.end), .agenda)
            s += AttributedString(" 结束。")
        } else if let e = v.nextEvent, Calendar.hub.isDate(e.start, inSameDayAs: state.agenda.now) {
            s += AttributedString("接下来 ")
            s += link(Agenda.clock(e.start), .agenda)
            s += AttributedString(" 是「\(e.title)」。")
        } else {
            s += AttributedString("今天没有别的日程了。")
        }
        s += AttributedString("步数完成了 86%，支出 ¥128.50，仍在预算之内。昨天的")
        s += link("日报", .goals)
        s += AttributedString("还在等你确认，GitHub 上有 ")
        s += link("3 条回复", .git)
        s += AttributedString("在等你。")
        return s
    }

    static func dueLine(_ v: AgendaView) -> String {
        v.dueCount == 0 ? "任务都完成了" : "\(v.dueCount) 项任务到期"
    }

    static func eventLine(_ v: AgendaView) -> String? {
        if let e = v.currentEvent { return "\(e.title) 进行中" }
        guard let e = v.nextEvent, Calendar.hub.isDateInToday(e.start) else { return nil }
        return "\(Agenda.clock(e.start)) \(e.title)"
    }

    private func link(_ text: String, _ module: ModuleID) -> AttributedString {
        var a = AttributedString(text)
        a.link = URL(string: "hub://\(module.rawValue)")
        a.underlineStyle = .single
        return a
    }
}

struct CommandBar: View {
    @Environment(AppState.self) private var state

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "sparkle").font(.system(size: 13)).foregroundStyle(Tone.clay.color)
            Text("记一条任务或想法…").font(Typo.sans(13)).foregroundStyle(Palette.ink3)
            Spacer()
            HStack(spacing: 0) {
                seg("任务 ⌃⌥Space", on: true) { state.showQuickTask() }
                seg("Memo ⌃⌥M", on: false) { state.showQuickMemo() }
            }
            .padding(2).background(RoundedRectangle(cornerRadius: 9).fill(Palette.sunk))
        }
        .padding(.leading, 14).padding(.trailing, 6).frame(height: 46)
        .background(RoundedRectangle(cornerRadius: 14).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Palette.line))
        .shadow(color: .black.opacity(0.04), radius: 2, y: 1)
        .contentShape(Rectangle())
        .onTapGesture { state.showQuickTask() }
    }

    private func seg(_ text: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text).font(Typo.sans(12)).foregroundStyle(on ? Palette.ink : Palette.ink3)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(RoundedRectangle(cornerRadius: 7).fill(on ? Palette.card : .clear).shadow(color: .black.opacity(on ? 0.06 : 0), radius: 1, y: 1))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - 日程与任务

struct AgendaModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state
    @ViewState private var listFilter: String?

    var body: some View {
        if size == .compact { compact } else { detail }
    }

    private var compact: some View {
        let v = state.agenda.view, now = state.agenda.now
        return VStack(alignment: .leading, spacing: 0) {
            if let e = v.currentEvent {
                EventBlock(event: e, caption: "进行中 · \(Agenda.clock(e.end)) 结束", compact: true)
            } else if let e = v.nextEvent {
                EventBlock(event: e, caption: "下一个 · \(Agenda.countdown(to: e.start, now: now))", compact: true)
            } else {
                Text("接下来没有日程").font(Typo.sans(12)).foregroundStyle(Palette.ink3).frame(height: 44)
            }
            Spacer(minLength: 8)
            Hero(value: Double(v.dueCount), unit: v.overdue.isEmpty ? "项今天到期" : "项到期 · \(v.overdue.count) 项逾期", size: 30)
            Track(value: v.todayTotal == 0 ? 0 : Double(v.todayDone) / Double(v.todayTotal) * 100, color: Tone.sky.color, height: 4).padding(.top, 10)
            Text("已完成 \(v.todayDone) / \(v.todayTotal)").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
        }
    }

    private var detail: some View {
        let v = state.agenda.view, d = state.snapshot
        let keep = { (t: AgendaTask) in listFilter == nil || t.listID == listFilter }
        let groups: [(String, [AgendaTask])] = [
            ("逾期", v.overdue.filter(keep)), ("今天 · \(v.today.filter(keep).count)", v.today.filter(keep)),
            ("即将", v.upcoming.filter(keep)), ("以后", v.later.filter(keep)), ("无日期", v.undated.filter(keep)),
        ]
        return HStack(alignment: .top, spacing: 22) {
            VStack(alignment: .leading, spacing: 10) {
                Flow(spacing: 6) {
                    Chip(text: "全天 · 阶段第 \(d.cycle.day) 天", tone: .clay)
                    ForEach(v.allDay) { Chip(text: $0.title, tone: $0.tone) }
                }
                DayTimeline(events: v.events, now: state.agenda.now)
            }
            .frame(maxWidth: .infinity)
            VStack(alignment: .leading, spacing: 0) {
                ListChips(selection: $listFilter).padding(.bottom, 2)
                SyncNotice().padding(.top, 6)
                ScrollView {
                    VStack(alignment: .leading, spacing: 0) {
                        ForEach(groups.filter { !$0.1.isEmpty || $0.0.hasPrefix("今天") }, id: \.0) { title, tasks in
                            SectionTitle(title)
                            ForEach(tasks) { TaskRow(task: $0, showList: listFilter == nil) }
                            if tasks.isEmpty {
                                Text("今天没有到期的任务").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6)
                            }
                        }
                    }
                    .animation(Motion.spring, value: v.allTasks.map(\.completed))
                }
                .scrollIndicators(.never)
                .frame(maxHeight: 360)
                InlineQuickAdd().padding(.top, 12)
            }
            .frame(maxWidth: .infinity)
        }
    }
}

struct FlowChips: View {
    var chips: [(String, Tone)]
    var body: some View {
        Flow(spacing: 6) { ForEach(chips.indices, id: \.self) { Chip(text: chips[$0].0, tone: chips[$0].1) } }
    }
}

/// Left-aligned wrapping layout; each child keeps its ideal size.
struct Flow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(width: proposal.width ?? .infinity, subviews: subviews)
        let width = rows.map { $0.width }.max() ?? 0
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width.map { min($0, width) } ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for i in row.indices {
                let size = subviews[i].sizeThatFits(.unspecified)
                subviews[i].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row { var indices: [Int] = []; var width: CGFloat = 0; var height: CGFloat = 0 }

    private func arrange(width: CGFloat, subviews: Subviews) -> [Row] {
        var rows = [Row()]
        for i in subviews.indices {
            let size = subviews[i].sizeThatFits(.unspecified)
            let extra = rows[rows.count - 1].indices.isEmpty ? size.width : size.width + spacing
            if rows[rows.count - 1].width + extra > width, !rows[rows.count - 1].indices.isEmpty {
                rows.append(Row())
            }
            let added = rows[rows.count - 1].indices.isEmpty ? size.width : size.width + spacing
            rows[rows.count - 1].indices.append(i)
            rows[rows.count - 1].width += added
            rows[rows.count - 1].height = max(rows[rows.count - 1].height, size.height)
        }
        return rows
    }
}

// MARK: - 主线与复盘

struct GoalsModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let d = state.snapshot
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Label11("总主线")
                Mainline(text: d.mainline, size: 17).padding(.top, 3)
                CycleTicks(cycle: d.cycle, height: 12, spacing: 2).padding(.top, 12)
                HStack {
                    Text("第 \(d.cycle.day) / \(d.cycle.total) 天")
                    Spacer()
                    Text("剩 \(d.cycle.remaining) 天")
                }
                .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.top, 4)
                Spacer(minLength: 6)
                HStack(spacing: 6) {
                    Dot(color: Tone.clay.color, pulse: true)
                    Text("昨日日报待确认").font(Typo.sans(11.5, .medium)).foregroundStyle(Tone.clay.color)
                }
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(Capsule().fill(Tone.clay.tint))
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Label11("总主线")
                Mainline(text: d.mainline, size: 24).padding(.top, 4)
                CycleTicks(cycle: d.cycle, height: 22, spacing: 3).padding(.top, 14)
                HStack {
                    Text("\(d.cycle.start) 开始")
                    Spacer()
                    Text("今天 · 第 \(d.cycle.day) 天").fontWeight(.semibold).foregroundStyle(Palette.clayDeep)
                    Spacer()
                    Text("\(d.cycle.end) 结案")
                }
                .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.top, 6)
                SectionTitle("第 \(d.cycle.index) 阶段目标 · \(d.goals.count) / 5")
                ForEach(Array(d.goals.enumerated()), id: \.1.id) { i, g in
                    HStack(spacing: 12) {
                        Text(g.domain).font(Typo.sans(11.5, .medium)).foregroundStyle(g.tone.color)
                            .frame(width: 46, height: 22).background(Capsule().fill(g.tone.tint))
                        Text(g.title).font(Typo.sans(13)).lineLimit(1)
                        Spacer(minLength: 8)
                        Track(value: g.progress, color: g.tone.color, height: 5, delay: Double(i) * 80).frame(width: 84)
                        Text(g.value).font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).monospacedDigit().frame(width: 64, alignment: .trailing)
                    }
                    .padding(.vertical, 7)
                }
                HStack(spacing: 8) {
                    ReviewTile(title: "昨日日报", sub: "草稿 · 待确认", hot: true)
                    ReviewTile(title: "本周周报", sub: "周日 21:50")
                    ReviewTile(title: "阶段结案", sub: "11/10 预备材料")
                }
                .padding(.top, 14)
            }
        }
    }
}

struct Mainline: View {
    var text: String
    var size: CGFloat

    var body: some View {
        (Text("“").foregroundColor(Tone.clay.color) + Text(text) + Text("”").foregroundColor(Tone.clay.color))
            .font(Typo.serif(size)).tracking(-0.3).lineLimit(2)
    }
}

struct CycleTicks: View {
    var cycle: Cycle
    var height: CGFloat
    var spacing: CGFloat

    var body: some View {
        HStack(spacing: spacing) {
            ForEach(0..<cycle.total, id: \.self) { i in
                let past = i < cycle.day - 1, now = i == cycle.day - 1, last = i == cycle.total - 1
                RoundedRectangle(cornerRadius: 2)
                    .fill(now ? Tone.clay.color : past ? Tone.clay.color.opacity(0.42) : Color(hex: "#EBE5D9"))
                    .overlay(RoundedRectangle(cornerRadius: 2).strokeBorder(last ? Palette.ink3 : .clear, style: StrokeStyle(lineWidth: 1, dash: [2, 2])))
                    .frame(height: now ? height + 6 : height)
                    .rise(i / 3)
            }
        }
        .frame(height: height + 6)
    }
}

struct ReviewTile: View {
    var title: String
    var sub: String
    var hot = false

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(Typo.sans(12.5, .semibold)).foregroundStyle(hot ? Palette.clayDeep : Palette.ink)
            Text(sub).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(hot ? Tone.clay.tint : Palette.sunk))
    }
}

// MARK: - 需要注意

struct AttentionModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let items = state.snapshot.attention
        if size == .compact {
            HStack(spacing: 10) {
                ForEach(Array(items.enumerated()), id: \.1.id) { i, a in
                    AttentionCard(item: a, pulse: i == 0).rise(i)
                }
            }
        } else {
            VStack(spacing: 0) {
                ForEach(items) { a in
                    HStack(spacing: 10) {
                        Dot(color: a.tone.color)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(a.title).font(Typo.sans(13))
                            Text(a.subtitle).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                        }
                        Spacer()
                        Chip(text: a.action, tone: a.tone)
                    }
                    .padding(.vertical, 9)
                    .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                }
            }
        }
    }
}

struct AttentionCard: View {
    var item: Attention
    var pulse = false
    @ViewState private var hover = false

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Dot(color: item.tone.color, pulse: pulse).padding(.top, 5)
            VStack(alignment: .leading, spacing: 3) {
                Text(item.title).font(Typo.sans(12.5, .semibold)).lineLimit(2).fixedSize(horizontal: false, vertical: true)
                Text(item.subtitle).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "arrow.right").font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.ink3)
                .opacity(hover ? 1 : 0).offset(x: hover ? 0 : -4)
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12).fill(hover ? item.tone.tint : Palette.sunk))
        .animation(Motion.fast, value: hover)
        .onHover { hover = $0 }
    }
}
