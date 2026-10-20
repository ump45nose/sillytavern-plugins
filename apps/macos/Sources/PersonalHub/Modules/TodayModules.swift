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
                Text("\(state.dueCount) 项任务到期 · 19:00 羽毛球 · 日报待确认")
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
        var s = AttributedString("今天有 ")
        s += link("\(state.dueCount) 项任务", .agenda)
        s += AttributedString("到期，其中 1 项已经逾期；")
        s += link("19:00", .agenda)
        s += AttributedString(" 去打羽毛球。步数完成了 86%，支出 ¥128.50，仍在预算之内。昨天的")
        s += link("日报", .goals)
        s += AttributedString("还在等你确认，GitHub 上有 ")
        s += link("3 条回复", .git)
        s += AttributedString("在等你。")
        return s
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

    var body: some View {
        if size == .compact { compact } else { detail }
    }

    private var compact: some View {
        let t = state.snapshot.tasks, all = t.overdue + t.today
        let done = all.filter { state.doneTasks.contains($0.title) }.count
        return VStack(alignment: .leading, spacing: 0) {
            EventBlock(event: state.snapshot.events[2], caption: "下一个 · 1 小时后", compact: true)
            Spacer(minLength: 8)
            Hero(value: Double(state.dueCount), unit: "项今天到期 · 1 项逾期", size: 30)
            Track(value: Double(done) / Double(all.count) * 100, color: Tone.sky.color, height: 4).padding(.top, 10)
            Text("已完成 \(done) / \(all.count)").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
        }
    }

    private var detail: some View {
        let d = state.snapshot
        return HStack(alignment: .top, spacing: 22) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 6) {
                    Chip(text: "全天 · 阶段第 \(d.cycle.day) 天", tone: .clay)
                    Chip(text: "妈妈生日还有 6 天")
                }
                DayTimeline(events: d.events, nowHour: d.now.hour, nowText: d.now.time)
            }
            .frame(maxWidth: .infinity)
            VStack(alignment: .leading, spacing: 0) {
                SectionTitle("逾期").padding(.top, -18)
                ForEach(d.tasks.overdue) { TaskRow(task: $0, late: true) }
                SectionTitle("今天 · \(d.tasks.today.count)")
                ForEach(d.tasks.today) { TaskRow(task: $0) }
                SectionTitle("即将")
                ForEach(d.tasks.upcoming) { TaskRow(task: $0) }
                Button { state.showQuickTask() } label: {
                    MiniInput(placeholder: "明天下午3点 和李雷对齐方案", shortcut: "↩")
                }
                .buttonStyle(.plain).padding(.top, 14)
                FlowChips(chips: [("10 月 21 日 周三", .sky), ("15:00 · 同时建时间块", .clay), ("清单：工作", .olive)]).padding(.top, 8)
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

struct EventBlock: View {
    var event: CalendarEvent
    var caption: String
    var compact = false

    var body: some View {
        HStack(spacing: 0) {
            RoundedRectangle(cornerRadius: 2).fill(event.tone.color).frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                Text(caption).font(Typo.sans(11)).foregroundStyle(Palette.ink2)
                HStack(spacing: 4) {
                    Text(compact ? "\(Clock.hhmm(event.start)) \(event.title)" : event.title).font(Typo.sans(13, .semibold))
                    if !compact { Text("· \(event.location)").font(Typo.sans(11)).foregroundStyle(Palette.ink2) }
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            Spacer(minLength: 0)
        }
        .background(RoundedRectangle(cornerRadius: 9).fill(event.tone.tint))
        .clipShape(RoundedRectangle(cornerRadius: 9))
    }
}

struct DayTimeline: View {
    var events: [CalendarEvent]
    var nowHour: Double
    var nowText: String
    private let pph: CGFloat = 30, h0 = 8.0, top: CGFloat = 12

    var body: some View {
        ZStack(alignment: .topLeading) {
            ForEach([8, 10, 12, 14, 16, 18, 20, 22], id: \.self) { h in
                HStack(spacing: 8) {
                    Text(abs(Double(h) - nowHour) < 0.6 ? "" : String(format: "%02d:00", h))
                        .font(Typo.sans(10)).foregroundStyle(Palette.ink4).monospacedDigit().frame(width: 34, alignment: .trailing)
                    Rectangle().fill(Palette.line2).frame(height: 1)
                }
                .offset(y: y(Double(h)) - 6)
            }
            ForEach(events.indices, id: \.self) { i in
                let e = events[i]
                EventBlock(event: e, caption: "\(Clock.hhmm(e.start)) – \(Clock.hhmm(e.end))")
                    .frame(height: CGFloat(e.end - e.start) * pph - 4, alignment: .top)
                    .padding(.leading, 46)
                    .offset(y: y(e.start) + 2)
                    .rise(i + 2)
            }
            HStack(spacing: 4) {
                Text(nowText).font(Typo.sans(10, .semibold)).foregroundStyle(Tone.clay.color).monospacedDigit().frame(width: 34, alignment: .trailing)
                Dot(color: Tone.clay.color, pulse: true)
                Rectangle().fill(Tone.clay.color).frame(height: 1.5)
            }
            .offset(y: y(nowHour) - 6)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(height: 440, alignment: .topLeading)
        .padding(.horizontal, 6)
        .background(RoundedRectangle(cornerRadius: 12).fill(Palette.sunk.opacity(0.7)))
    }

    private func y(_ hour: Double) -> CGFloat { CGFloat(hour - h0) * pph + top }
}

struct TaskRow: View {
    var task: TaskItem
    var late = false
    var showList = true
    @Environment(AppState.self) private var state

    var body: some View {
        let done = state.doneTasks.contains(task.title)
        HStack(spacing: 10) {
            Button { state.toggleTask(task.title) } label: {
                ZStack {
                    Circle().strokeBorder(done ? Tone.olive.color : Palette.ink4, lineWidth: 1.5)
                    Circle().fill(Tone.olive.color).scaleEffect(done ? 1 : 0.01)
                    Image(systemName: "checkmark").font(.system(size: 8, weight: .heavy)).foregroundStyle(.white)
                        .scaleEffect(done ? 1 : 0.3).opacity(done ? 1 : 0)
                }
                .frame(width: 16, height: 16)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 1) {
                Text(task.title).font(Typo.sans(13)).foregroundStyle(done ? Palette.ink3 : Palette.ink).strikethrough(done, color: Palette.ink3).lineLimit(1)
                if showList { Text(task.list).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
            }
            Spacer(minLength: 4)
            if let due = task.due {
                Text(due).font(Typo.sans(11, late ? .semibold : .regular)).monospacedDigit()
                    .foregroundStyle(late ? Tone.rose.color : Palette.ink2)
                    .padding(.horizontal, 7).padding(.vertical, 2)
                    .background(Capsule().fill(late ? Tone.rose.tint : Palette.sunk))
            }
        }
        .padding(.vertical, 8)
        .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
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
