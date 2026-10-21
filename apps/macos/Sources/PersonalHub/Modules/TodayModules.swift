import HubKit
import SwiftUI

// MARK: - 今日简报

struct BriefModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        if size == .compact {
            HStack(alignment: .bottom) {
                VStack(alignment: .leading, spacing: 4) {
                    Label11(Self.dateLine(state.agenda.now))
                    Text(Self.greeting(state.agenda.now, name: state.displayName)).font(Typo.serif(30))
                }
                Spacer()
                Text(([Self.dueLine(state.agenda.view)] + [Self.eventLine(state.agenda.view)].compactMap { $0 }).joined(separator: " · "))
                    .font(Typo.serif(15)).foregroundStyle(Palette.ink2)
            }
            .padding(.trailing, 70)
        } else {
            HStack(alignment: .bottom, spacing: 40) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 10) {
                        Label11(Self.dateLine(state.agenda.now))
                        if let c = state.cycle { Chip(text: "\(c.name) · 第 \(c.day) 天", tone: .clay) }
                    }
                    Text(Self.greeting(state.agenda.now, name: state.displayName)).font(Typo.serif(44)).tracking(-0.8)
                    Text(summary)
                        .font(Typo.serif(18.5)).foregroundStyle(Palette.ink2).lineSpacing(6)
                        .tint(Palette.clayDeep)
                        .environment(\.openURL, OpenURLAction { url in
                            if url.host() == "review", let id = url.pathComponents.dropFirst().first { state.openReview(.session(id)) }
                            else if let m = ModuleID(rawValue: url.host() ?? "") { state.focus(m) }
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
        let data = state.hub.data
        var facts: [AttributedString] = []
        if let h = data.health?.data, let steps = h.steps, let goal = h.stepGoal, goal > 0 {
            facts.append(AttributedString("步数完成了 ") + link("\(Int(steps / goal * 100))%", .health))
        }
        if let b = data.bills?.data, let today = b.todayTotal {
            var f = AttributedString("今天支出 ") + link("¥" + Fmt.number(today, 2), .bills)
            if let month = b.monthTotal, let budget = b.monthBudget, budget > 0 {
                f += AttributedString(month <= budget ? "，仍在预算之内" : "，本月已超预算")
            }
            facts.append(f)
        }
        if let n = data.crm?.data?.today?.count, n > 0 {
            facts.append(AttributedString("和 ") + link("\(Set((data.crm?.data?.today ?? []).map { $0.personId ?? $0.name }).count) 个人", .crm) + AttributedString("有过交流"))
        }
        if !facts.isEmpty {
            s += AttributedString(" ")
            for (i, f) in facts.enumerated() { s += f; s += AttributedString(i == facts.count - 1 ? "。" : "，") }
        }
        if let w = data.git?.data?.waiting?.count, w > 0 {
            s += AttributedString("GitHub 上有 ")
            s += link("\(w) 条回复", .git)
            s += AttributedString("在等你。")
        }
        if let daily = state.goals?.reviews?.daily, daily.status == .open {
            let day = ReviewText.title(daily).components(separatedBy: " · ").first ?? ""
            s += AttributedString((day == "今天" || day == "昨天" ? day + "的" : "") + "")
            var a = AttributedString("日报")
            a.link = URL(string: "hub://review/" + (daily.id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? daily.id))
            a.underlineStyle = .single
            s += a
            s += AttributedString("还在等你确认。")
        }
        let remote = state.attention.filter { !$0.id.hasPrefix("task:") && !$0.id.hasPrefix("review:") }.count
        if remote > 0 {
            s += AttributedString("另外有 ")
            s += link("\(remote) 件事", .attention)
            s += AttributedString("需要留意。")
        }
        return s
    }

    static func greeting(_ now: Date, name: String) -> String {
        let part = switch Calendar.hub.component(.hour, from: now) {
        case 5..<11: "早上好"
        case 11..<13: "中午好"
        case 13..<18: "下午好"
        default: "晚上好"
        }
        return part + "，" + name
    }

    static func dateLine(_ now: Date) -> String {
        let c = Calendar.hub
        let weekday = ["日", "一", "二", "三", "四", "五", "六"][c.component(.weekday, from: now) - 1]
        return "\(c.component(.month, from: now)) 月 \(c.component(.day, from: now)) 日 · 星期\(weekday)"
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
                seg("任务 " + HotKeyCenter.shared.display(.quickTask), on: true) { state.showQuickTask() }
                seg("Memo " + HotKeyCenter.shared.display(.quickMemo), on: false) { state.showQuickMemo() }
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
    @ViewState private var newEventAt: Date?

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
        let v = state.agenda.view
        let keep = { (t: AgendaTask) in listFilter == nil || t.listID == listFilter }
        let groups: [(String, [AgendaTask])] = [
            ("逾期", v.overdue.filter(keep)), ("今天 · \(v.today.filter(keep).count)", v.today.filter(keep)),
            ("即将", v.upcoming.filter(keep)), ("以后", v.later.filter(keep)), ("无日期", v.undated.filter(keep)),
        ]
        return HStack(alignment: .top, spacing: 22) {
            VStack(alignment: .leading, spacing: 10) {
                Flow(spacing: 6) {
                    if let c = state.cycle { Chip(text: "全天 · 阶段第 \(c.day) 天", tone: .clay) }
                    ForEach(v.allDay) { e in
                        EventChip(event: e)
                    }
                    if state.agenda.writableCalendar != nil {
                        Button { newEventAt = Self.nextSlot(after: state.agenda.now) } label: { Chip(text: "日程", systemImage: "plus") }
                            .buttonStyle(.plain)
                            .help("新建日程；也可以双击时间轴空白处")
                    }
                }
                DayTimeline(events: v.events, now: state.agenda.now,
                            onCreate: state.agenda.writableCalendar == nil ? nil : { newEventAt = $0 })
                    .popover(isPresented: Binding(get: { newEventAt != nil }, set: { if !$0 { newEventAt = nil } }), arrowEdge: .trailing) {
                        if let at = newEventAt {
                            EventEditor(mode: .create(at)) { newEventAt = nil }.environment(state)
                        }
                    }
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

extension AgendaModule {
    /// The next full hour, for new events.
    static func nextSlot(after now: Date) -> Date {
        let cal = Calendar.hub
        let hour = cal.dateInterval(of: .hour, for: now)?.start ?? now
        return cal.date(byAdding: .hour, value: 1, to: hour) ?? now
    }
}

/// An all-day event as a chip that opens the editor.
struct EventChip: View {
    var event: AgendaEvent
    @Environment(AppState.self) private var state
    @ViewState private var editing = false

    var body: some View {
        Button { editing = true } label: { Chip(text: event.title, tone: event.tone) }
            .buttonStyle(.plain)
            .popover(isPresented: $editing, arrowEdge: .bottom) {
                EventEditor(mode: .edit(event)) { editing = false }.environment(state)
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
        if state.hub.mode == .hub, state.hub.data.goals == nil {
            ModuleEmpty(symbol: "puzzlepiece.extension", text: "等 hub 接入 personal-review")
        } else {
            HubGate(envelope: state.hub.data.goals, unconfigured: "personal-review 尚未接入") { d in
                if size == .compact { compact(d) } else { detail(d) }
            }
        }
    }

    private func compact(_ d: GoalsData) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Label11(d.mainline?.domain ?? "总主线")
            Mainline(text: d.mainline?.direction ?? "—", size: 17).padding(.top, 3)
            if let c = state.cycle {
                CycleTicks(cycle: c, height: 12, spacing: 2).padding(.top, 12)
                HStack {
                    Text("第 \(c.day) / \(c.total) 天")
                    Spacer()
                    Text("剩 \(c.remaining) 天")
                }
                .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.top, 4)
            }
            Spacer(minLength: 6)
            let pill = Self.pill(d)
            Button { state.openReview(pill.target) } label: {
                HStack(spacing: 6) {
                    Dot(color: pill.tone.color, pulse: pill.hot)
                    Text(pill.text).font(Typo.sans(11.5, .medium)).foregroundStyle(pill.tone.color)
                }
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(Capsule().fill(pill.tone.tint))
            }
            .buttonStyle(.plain)
        }
    }

    private func detail(_ d: GoalsData) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Label11(d.mainline?.domain ?? "总主线")
            Mainline(text: d.mainline?.direction ?? "—", size: 21).padding(.top, 4)
            if let c = state.cycle {
                CycleTicks(cycle: c, height: 22, spacing: 3).padding(.top, 14)
                HStack {
                    Text("\(c.start) 开始")
                    Spacer()
                    Text("今天 · 第 \(c.day) 天").fontWeight(.semibold).foregroundStyle(Palette.clayDeep)
                    Spacer()
                    Text("\(c.end) 结案")
                }
                .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.top, 6)
                SectionTitle("\(c.name)目标 · \(d.goals?.count ?? 0) / \(Stage.maxGoals)")
            } else {
                SectionTitle("阶段目标")
            }
            ForEach(Array((d.goals ?? []).enumerated()), id: \.1.id) { i, g in
                HStack(spacing: 12) {
                    Text(g.domain).font(Typo.sans(11.5, .medium)).foregroundStyle(StageTone.of(g.domain).color)
                        .frame(width: 46, height: 22).background(Capsule().fill(StageTone.of(g.domain).tint))
                    Text(g.goal).font(Typo.sans(13)).lineLimit(2).fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Text(g.progress ?? "").font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(2).multilineTextAlignment(.trailing)
                        .frame(width: 150, alignment: .trailing).help(g.progress ?? "")
                }
                .padding(.vertical, 7)
                .rise(i)
            }
            if (d.goals ?? []).isEmpty {
                Text(d.cycle == nil ? "上一阶段已结案，还没有开始新阶段" : "这个阶段还没有目标").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6)
            }
            HStack(spacing: 8) {
                tile(Self.dailyTile(d.reviews), .latest(.daily))
                tile(Self.weeklyTile(d.reviews), .latest(.weekly))
                tile(Self.closeTile(d), .stage)
            }
            .padding(.top, 14)
        }
    }

    private func tile(_ t: (title: String, sub: String, hot: Bool), _ target: ReviewTarget) -> some View {
        Button { state.openReview(target) } label: { ReviewTile(title: t.title, sub: t.sub, hot: t.hot) }.buttonStyle(.plain)
    }

    static func dailyTile(_ r: GoalsData.Reviews?) -> (title: String, sub: String, hot: Bool) {
        guard let s = r?.daily else { return ("日报", r?.nextDailyAt.map { "\(HubFormat.clock($0)) 生成" } ?? "还没有日报", false) }
        let title = ReviewText.title(s).components(separatedBy: " · ").first.map { $0 == "今天" || $0 == "昨天" ? $0 + "的日报" : "日报" } ?? "日报"
        switch s.status {
        case .open: return (title, "待确认 · " + (ReviewText.remaining(s.expiresAt, short: true) ?? ""), true)
        case .finalized: return (title, r?.nextDailyAt.map { "已归档 · 下篇 \(HubFormat.clock($0))" } ?? "已归档", false)
        case .expired: return (title, "已过期", false)
        }
    }

    static func weeklyTile(_ r: GoalsData.Reviews?) -> (title: String, sub: String, hot: Bool) {
        let next = r?.nextWeeklyAt.map { "\(ReviewText.md($0)) 生成" }
        guard let s = r?.weekly else { return ("周报", next ?? "还没有周报", false) }
        switch s.status {
        case .open: return ("本周周报", "待确认 · " + (ReviewText.remaining(s.expiresAt, short: true) ?? ""), true)
        case .finalized: return ("周报", r?.nextWeeklyAt.map { "已归档 · 下篇 " + ReviewText.md($0) } ?? "已归档", false)
        case .expired: return ("周报", next ?? "已过期", false)
        }
    }

    static func closeTile(_ d: GoalsData) -> (title: String, sub: String, hot: Bool) {
        switch d.close?.status {
        case .preclose: return ("阶段结案", d.cycle.map { "待结案 · \(ReviewText.md($0.endsAt)) 截止" } ?? "待结案", true)
        case .awaitingClose: return ("阶段结案", "已过结案日，待结案", true)
        case .closed: return ("阶段结案", "已结案 · 开始新阶段", false)
        default: return ("阶段结案", d.cycle?.precloseAt.map { "\(ReviewText.md($0)) 起可结案" } ?? "—", false)
        }
    }

    /// The one thing worth flagging on the compact card.
    static func pill(_ d: GoalsData) -> (text: String, tone: Tone, hot: Bool, target: ReviewTarget) {
        if let s = d.reviews?.daily, s.status == .open {
            let day = ReviewText.title(s).components(separatedBy: " · ").first ?? ""
            return ((day == "今天" || day == "昨天" ? day : "") + "日报待确认", .clay, true, .session(s.id))
        }
        if let s = d.reviews?.weekly, s.status == .open { return ("周报待确认", .clay, true, .session(s.id)) }
        if d.close?.status == .preclose || d.close?.status == .awaitingClose { return ("阶段待结案", .rose, true, .stage) }
        if d.reviews?.daily?.status == .finalized { return ("日报已归档", .olive, false, .latest(.daily)) }
        return ("查看复盘", .steel, false, .stage)
    }
}

struct Mainline: View {
    var text: String
    var size: CGFloat

    var body: some View {
        (Text("“").foregroundColor(Tone.clay.color) + Text(text) + Text("”").foregroundColor(Tone.clay.color))
            .font(Typo.serif(size)).tracking(-0.3).lineLimit(3)
            .fixedSize(horizontal: false, vertical: true)
            .help(text)
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

struct AttentionEntry: Identifiable, Equatable {
    var id: String
    var tone: Tone
    var title: String
    var subtitle: String
    var action: String
    var target: ModuleID?
    var url: URL?

    static func tone(rule: String, severity: String?) -> Tone {
        switch rule {
        case "token_limit": .clay
        case "traffic_low": .sage
        case "git_waiting": .sky
        case "pr_blocked", "source_down": .rose
        case "subs_renew": .ochre
        case "stale_contact": .plum
        case "review_pending": .clay
        case "stage_close": .rose
        default: severity == "critical" ? .rose : severity == "warn" ? .clay : .steel
        }
    }
}

struct AttentionModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let items = state.attention
        if items.isEmpty {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.circle").foregroundStyle(Tone.olive.color)
                Text(state.hub.data.attention?.status == .unconfigured ? "没有逾期任务 · 跨模块提醒等 hub 开启" : "没有需要注意的事")
                    .font(Typo.sans(12.5)).foregroundStyle(Palette.ink2)
            }
            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
        } else if size == .compact {
            HStack(spacing: 10) {
                ForEach(Array(items.prefix(4).enumerated()), id: \.1.id) { i, a in
                    Button { state.open(a) } label: { AttentionCard(item: a, pulse: i == 0) }.buttonStyle(.plain).rise(i)
                }
            }
        } else {
            VStack(spacing: 0) {
                ForEach(items) { a in
                    HStack(spacing: 10) {
                        Dot(color: a.tone.color)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(a.title).font(Typo.sans(13)).lineLimit(1)
                            Text(a.subtitle).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
                        }
                        Spacer()
                        Button { state.open(a) } label: { Chip(text: a.action, tone: a.tone) }.buttonStyle(.plain)
                    }
                    .padding(.vertical, 9)
                    .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                }
            }
        }
    }
}

struct AttentionCard: View {
    var item: AttentionEntry
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
