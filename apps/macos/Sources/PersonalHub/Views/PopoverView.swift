import HubKit
import SwiftUI

/// The menu bar panel: pages of widgets and compact modules the user arranges (`LayoutDocument.tray`).
struct PopoverView: View {
    @Environment(AppState.self) private var state
    @ViewState private var pageID: String
    @ViewState private var editing: Bool
    @ViewState private var contentHeight: CGFloat = 0
    @ViewState private var rowsHeight: CGFloat = 0

    init(page: String = "today", editing: Bool = false) {
        _pageID = ViewState(initialValue: page)
        _editing = ViewState(initialValue: editing)
    }

    var body: some View {
        let pages = state.layout.trayPages
        let page = pages.first { $0.id == pageID } ?? pages[0]
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Segmented(options: pages.map { ($0.id, $0.title) }, selection: Binding(get: { page.id }, set: { pageID = $0 }))
                Spacer(minLength: 0)
                Button { withAnimation(Motion.spring) { editing.toggle() } } label: {
                    Group {
                        if editing { Text("完成").font(Typo.sans(12, .semibold)).foregroundStyle(.white).padding(.horizontal, 10) }
                        else { Image(systemName: "slider.horizontal.3").font(.system(size: 12, weight: .medium)).foregroundStyle(Palette.ink2).frame(width: 28) }
                    }
                    .frame(height: 28)
                    .background(RoundedRectangle(cornerRadius: 8).fill(editing ? Palette.ink : Palette.sunk))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help(editing ? "完成编辑" : "编辑面板：调整组件和页面")
            }
            if editing {
                TrayPageTools(page: page, index: pages.firstIndex(of: page) ?? 0, count: pages.count) { pageID = $0 }
                    .padding(.top, 10)
                    .transition(.opacity.combined(with: .offset(y: -4)))
            }
            HubScroll {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(Array(page.items.enumerated()), id: \.1) { i, item in
                        TrayItem(id: item, editing: editing)
                            .modifier(TrayEditFrame(active: editing, title: TrayItem.title(item), first: i == 0, last: i == page.items.count - 1,
                                                    move: { offset in state.editLayout { $0.editTrayPage(page.id) { $0.move(item, by: offset) } } },
                                                    remove: { state.editLayout { $0.editTrayPage(page.id) { $0.remove(item) } } }))
                            .transition(.opacity.combined(with: .scale(scale: 0.97)))
                    }
                    if page.items.isEmpty, !editing {
                        VStack(spacing: 8) {
                            Text("这一页还没有组件").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
                            Button("添加组件") { withAnimation(Motion.spring) { editing = true } }.font(Typo.sans(12))
                        }
                        .frame(maxWidth: .infinity).padding(.vertical, 28)
                    }
                    if editing { TrayAddChips(page: page).transition(.opacity) }
                }
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { contentHeight = $0 }
                .onPreferenceChange(TrayTaskRowsHeight.self) { rowsHeight = $0 }
                .environment(\.trayTaskSpace, contentHeight > 0 ? Self.maxHeight - 16 - (contentHeight - rowsHeight) : nil)
                .padding(.top, 14).padding(.bottom, 2)
                .animation(Motion.spring, value: page.items)
            }
            .scrollIndicators(.never)
            .frame(maxHeight: Self.maxHeight)
            .fixedSize(horizontal: false, vertical: true)
            .id(page.id)
            .transition(.opacity)

            Rectangle().fill(Palette.line2).frame(height: 1).padding(.top, 12)
            HStack {
                Button { state.openMainWindow(nil) } label: {
                    HStack(spacing: 6) {
                        LogoMark().frame(width: 14, height: 14)
                        Text("打开 Personal Hub")
                    }
                }
                .buttonStyle(.plain)
                Spacer()
                Text(HotKeyCenter.shared.display(.tray)).foregroundStyle(Palette.ink4).help("在任何应用中打开这个面板")
                Button { state.openSettings() } label: { Text("设置 ⌘,") }.buttonStyle(.plain).padding(.leading, 8)
            }
            .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            .padding(.top, 10)
        }
        .padding(14)
        .frame(width: 380)
        .background(Palette.card)
        .preferredColorScheme(.light)
        .tint(Tone.clay.color)
        .animation(Motion.spring, value: page.id)
    }

    /// Leaves room for the menu bar and the panel chrome on the current screen.
    static var maxHeight: CGFloat { max(360, (NSScreen.main?.visibleFrame.height ?? 900) - 150) }
}

// MARK: - Items

struct TrayItem: View {
    var id: String
    var editing: Bool

    static func title(_ id: String) -> String {
        switch TrayWidget(rawValue: id) {
        case .attention: "需要注意"
        case .agenda: "日程"
        case .tasks: "任务"
        case .metrics: "数据小卡"
        case nil: ModuleID(rawValue: id)?.info.title ?? id
        }
    }

    static func symbol(_ id: String) -> String {
        switch TrayWidget(rawValue: id) {
        case .attention: "bell"
        case .agenda: "calendar"
        case .tasks: "checklist"
        case .metrics: "square.grid.2x2"
        case nil: ModuleID(rawValue: id)?.info.symbol ?? "questionmark"
        }
    }

    var body: some View {
        switch TrayWidget(rawValue: id) {
        case .attention: TrayAttention(editing: editing)
        case .agenda: TrayAgenda()
        case .tasks: TrayTasks()
        case .metrics: TrayMetrics()
        case nil:
            if let module = ModuleID(rawValue: id) { TrayModuleCard(module: module) }
        }
    }
}

private struct TrayHeading<Trailing: View>: View {
    var title: String
    @ViewBuilder var trailing: Trailing
    /// The edit frame already names the widget.
    @Environment(\.isEnabled) private var enabled

    var body: some View {
        HStack(spacing: 8) {
            if enabled {
                Text(title).font(Typo.sans(11)).foregroundStyle(Palette.ink3).tracking(0.5).fixedSize()
                Rectangle().fill(Palette.line2).frame(height: 1)
            } else {
                Spacer(minLength: 0)
            }
            trailing
        }
        .padding(.bottom, 8)
    }
}

extension TrayHeading where Trailing == EmptyView {
    init(title: String) { self.init(title: title) { EmptyView() } }
}

private struct TrayAttention: View {
    var editing: Bool
    @Environment(AppState.self) private var state

    var body: some View {
        let attention = state.attention
        VStack(alignment: .leading, spacing: 0) {
            if attention.isEmpty {
                if editing { Text("没有需要注意的事时，这里不占位置").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3) }
            } else {
                HStack(spacing: 8) {
                    ForEach(attention.prefix(2)) { a in
                        Button { state.open(a) } label: { AttentionCard(item: a) }.buttonStyle(.plain)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                if attention.count > 2 {
                    Button { state.openMainWindow("home"); state.focus(.attention) } label: {
                        Text("另有 \(attention.count - 2) 件 →").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                    }
                    .buttonStyle(.plain).padding(.top, 6)
                }
            }
            SyncNotice().padding(.top, attention.isEmpty ? 0 : 8)
        }
    }
}

/// Today's remaining events and timed tasks, one 24pt row each; when today is done, the next event ahead.
private struct TrayAgenda: View {
    @Environment(AppState.self) private var state

    private static let limit = 5

    private enum Row: Identifiable {
        case event(AgendaEvent)
        case task(AgendaTask, Date)
        var id: String { switch self { case .event(let e): "e" + e.id; case .task(let t, _): "t" + t.id } }
        var at: Date { switch self { case .event(let e): e.start; case .task(_, let d): d } }
    }

    var body: some View {
        let agenda = state.agenda, v = agenda.view, now = agenda.now
        let rows = (v.events.filter { $0.end > now }.map(Row.event)
            + v.timedTasks(on: now).filter { !$0.task.completed && $0.at >= now }.map { Row.task($0.task, $0.at) })
            .sorted { $0.at < $1.at }
        VStack(alignment: .leading, spacing: 2) {
            TrayHeading(title: "日程")
            if rows.isEmpty {
                if let e = v.upcomingEvents.first {
                    EventStrip(event: e, caption: Agenda.relativeDay(e.start, now: now), stacked: false)
                } else {
                    Text("接下来没有日程").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
            }
            ForEach(rows.prefix(Self.limit)) { row in
                switch row {
                case .event(let e):
                    let live = e.start <= now
                    EventStrip(event: e, caption: live ? "进行中" : e.id == v.nextEvent?.id ? Agenda.countdown(to: e.start, now: now) : nil,
                               stacked: false, accent: live)
                case .task(let t, let at):
                    AgendaLine(tone: listTone(t.listID, in: agenda.lists).color, time: Agenda.clock(at), title: t.title, caption: "任务")
                }
            }
            if rows.count > Self.limit {
                Text("还有 \(rows.count - Self.limit) 项").font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.leading, 11)
            }
        }
    }
}

private struct TrayTaskSpaceKey: EnvironmentKey { static let defaultValue: CGFloat? = nil }

extension EnvironmentValues {
    /// Height the task rows may take so the whole panel fits on screen; nil until measured.
    var trayTaskSpace: CGFloat? {
        get { self[TrayTaskSpaceKey.self] }
        set { self[TrayTaskSpaceKey.self] = newValue }
    }
}

struct TrayTaskRowsHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value += nextValue() }
}

/// 逾期 (only while something is late), 今天: due today plus the lists pinned to 今天, 所有: one list by chip or
/// every list, 即将: tomorrow onward by day. Rows fill what the screen leaves; the rest folds behind 还有 N 项.
struct TrayTasks: View {
    @Environment(AppState.self) private var state
    @Environment(\.trayTaskSpace) private var space
    @ViewState private var tab: Int
    @ViewState private var listID: String?
    @ViewState private var expanded = false
    @AppStorage("trayTasksByList") private var byList = false

    /// 0 今天, 1 所有, 2 即将, 3 逾期.
    init(tab: Int = 0) { _tab = ViewState(initialValue: tab) }

    struct Section: Identifiable {
        var id: String
        var title: String?
        var tasks: [AgendaTask]
        var showList = true
        var showDue = true
        var empty: String?
        var pinMenu = false
    }

    var body: some View {
        let agenda = state.agenda, late = agenda.view.overdue.count
        let current = tab == 3 && late == 0 ? 0 : tab
        let list = listID.flatMap { id in agenda.lists.first { $0.id == id } } ?? agenda.lists.first
        let all = sections(current, list: list)
        let room = (space ?? 300) - (current == 1 ? 34 : 0)
        let (shown, hidden) = expanded ? (all, 0) : Self.fit(all, height: room)
        VStack(alignment: .leading, spacing: 0) {
            TrayHeading(title: heading(current, all)) {
                Segmented(options: (late > 0 ? [(3, "逾期 \(late)")] : []) + [(0, "今天"), (1, "所有"), (2, "即将")],
                          selection: Binding(get: { current }, set: { t in withAnimation(Motion.spring) { tab = t; expanded = false } }), small: true)
            }
            if current == 1 { allBar(list) }
            Group {
                if expanded {
                    HubScroll { rows(shown, all: all) }
                        .scrollIndicators(.automatic)
                        .frame(maxHeight: max(room - 36, 160))
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    rows(shown, all: all)
                }
            }
            .background(GeometryReader { g in Color.clear.preference(key: TrayTaskRowsHeight.self, value: g.size.height) })
            if hidden > 0 || expanded {
                foldBar(hidden: hidden, scope: scope(current))
                    .background(GeometryReader { g in Color.clear.preference(key: TrayTaskRowsHeight.self, value: g.size.height) })
            }
            TrayTaskInput(dueToday: current == 0, list: current == 1 && !byList ? list : nil).padding(.top, 8)
        }
        .animation(Motion.spring, value: expanded)
        .animation(Motion.spring, value: current)
    }

    private func rows(_ shown: [Section], all: [Section]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(shown) { s in
                if let title = s.title { header(title, count: all.first { $0.id == s.id }?.tasks.count ?? 0, pin: s.pinMenu) }
                ForEach(s.tasks) { TaskRow(task: $0, showList: s.showList, showDue: s.showDue) }
                if s.tasks.isEmpty, let empty = s.empty {
                    Text(empty).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
                }
            }
        }
        .animation(Motion.spring, value: all.flatMap { $0.tasks.map(\.completed) })
    }

    private func foldBar(hidden: Int, scope: TaskScope) -> some View {
        HStack(spacing: 6) {
            Button { withAnimation(Motion.spring) { expanded.toggle() } } label: {
                HStack(spacing: 5) {
                    Text(expanded ? "收起" : "还有 \(hidden) 项")
                    Image(systemName: expanded ? "chevron.up" : "chevron.down").font(.system(size: 9, weight: .bold))
                }
                .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                .frame(maxWidth: .infinity).frame(height: 28)
                .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Button { state.showTasks(scope) } label: {
                Text("任务页 →").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    .padding(.horizontal, 10).frame(height: 28)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
        }
        .padding(.top, 6)
    }

    private func scope(_ tab: Int) -> TaskScope {
        switch tab {
        case 0: .today
        case 2: .upcoming
        case 3: .overdue
        default: byList ? .all : (listID ?? state.agenda.lists.first?.id).map(TaskScope.list) ?? .all
        }
    }

    /// Estimated row heights, matching `TaskRow` and `header` in the panel.
    static func fit(_ sections: [Section], height: CGFloat) -> ([Section], Int) {
        let fold: CGFloat = 34
        func cost(_ t: AgendaTask, showList: Bool) -> CGFloat {
            let meta = (showList && !t.listTitle.isEmpty) || !t.subtasks.isEmpty || t.notes?.isEmpty == false
            return (meta ? 47 : 34) + CGFloat(t.subtasks.count) * 30
        }
        let total = sections.reduce(CGFloat(0)) { sum, s in
            sum + (s.title == nil ? 0 : 30) + (s.tasks.isEmpty ? 33 : s.tasks.reduce(0) { $0 + cost($1, showList: s.showList) })
        }
        if total <= height { return (sections, 0) }
        var left = max(height - fold, 3 * 34), out: [Section] = [], hidden = 0, shownRows = 0
        for var s in sections {
            let head: CGFloat = s.title == nil ? 0 : 30
            if left < head + 34 && shownRows >= 3 { hidden += s.tasks.count; continue }
            left -= head
            var keep: [AgendaTask] = []
            for t in s.tasks {
                let c = cost(t, showList: s.showList)
                if left >= c || shownRows < 3 { keep.append(t); left -= c; shownRows += 1 } else { hidden += 1 }
            }
            if s.tasks.isEmpty { left -= 33 }
            if keep.isEmpty && !s.tasks.isEmpty { left += head; continue }
            s.tasks = keep
            out.append(s)
        }
        return (out, hidden)
    }

    private func allBar(_ list: TaskListRecord?) -> some View {
        HStack(spacing: 8) {
            Segmented(options: [(false, "标签"), (true, "按清单")], selection: $byList, small: true).fixedSize()
            if !byList {
                HubScroll(.horizontal) {
                    HStack(spacing: 6) {
                        ForEach(state.agenda.lists) { l in
                            Button { withAnimation(Motion.spring) { listID = l.id } } label: {
                                Chip(text: l.title, tone: l.id == list?.id ? .sky : nil)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 1)
                }
                .scrollIndicators(.never)
            }
            Spacer(minLength: 0)
        }
        .padding(.bottom, 6)
    }

    private func header(_ title: String, count: Int, pin: Bool) -> some View {
        HStack(spacing: 6) {
            Text(title).font(Typo.sans(11, .semibold)).foregroundStyle(Palette.ink2)
            if count > 0 { Text("\(count)").font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit() }
            Spacer()
            if pin { TodayListsMenu() }
        }
        .padding(.top, 10).padding(.bottom, 2)
    }

    private func sections(_ tab: Int, list: TaskListRecord?) -> [Section] {
        let agenda = state.agenda, v = agenda.view
        switch tab {
        case 0:
            return [Section(id: "due", title: "今天到期", tasks: v.today, showDue: false, empty: "今天没有到期的任务", pinMenu: true)]
                + agenda.todayExtras.filter { !$0.tasks.isEmpty }
                .map { Section(id: "list-" + $0.list.id, title: $0.list.title, tasks: $0.tasks, showList: false) }
        case 2:
            let days = v.days(from: agenda.now)
            if days.isEmpty { return [Section(id: "none", tasks: [], empty: "明天起没有有日期的任务")] }
            return days.map { day, tasks in
                Section(id: "day-\(day.timeIntervalSince1970)", title: Self.dayTitle(day, now: agenda.now), tasks: tasks, showDue: false)
            }
        case 3:
            return agenda.lists.compactMap { l in
                let tasks = v.overdue.filter { $0.listID == l.id }
                return tasks.isEmpty ? nil : Section(id: "late-" + l.id, title: l.title, tasks: tasks, showList: false)
            }
        default:
            if byList {
                return agenda.lists.map { Section(id: "list-" + $0.id, title: $0.title, tasks: v.open(in: $0.id), showList: false) }
                    .filter { !$0.tasks.isEmpty }
            }
            guard let list else { return [Section(id: "none", tasks: [], empty: "还没有任务清单")] }
            return [Section(id: "list-" + list.id, tasks: v.open(in: list.id), showList: false, empty: "「\(list.title)」里没有未完成的任务")]
        }
    }

    static func dayTitle(_ day: Date, now: Date) -> String {
        let rel = Agenda.relativeDay(day, now: now), long = Agenda.longDay(day)
        return ["今天", "明天", "后天"].contains(rel) ? "\(rel) · \(long)" : long
    }

    private func heading(_ tab: Int, _ sections: [Section]) -> String {
        let open = (tab == 0 ? state.agenda.view.today : sections.flatMap(\.tasks)).filter { !$0.completed }.count
        switch tab {
        case 0: return open == 0 ? "任务" : "任务 · 今天 \(open) 项"
        case 2: return "任务 · 即将 \(open) 项"
        case 3: return "任务 · 逾期 \(open) 项"
        default: return "任务 · \(open) 项未完成"
        }
    }
}

/// Picks which lists join 今天; shared by the menu bar, the task page and Settings.
struct TodayListsMenu: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, on = Set(agenda.todayLists.map(\.id))
        Menu {
            Section("在「今天」显示的清单") {
                ForEach(agenda.lists) { l in
                    Toggle(l.title, isOn: Binding(get: { on.contains(l.id) }, set: { agenda.showInToday(l.id, $0) }))
                }
            }
        } label: {
            Image(systemName: "pin").font(.system(size: 10.5, weight: .medium)).foregroundStyle(Palette.ink3)
        }
        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().tint(Palette.ink3)
        .help("选择在「今天」里显示的清单")
    }
}

/// Type and press return; dates and #lists are parsed like the quick task panel.
private struct TrayTaskInput: View {
    var dueToday: Bool
    var list: TaskListRecord?
    @Environment(AppState.self) private var state
    @ViewState private var text = ""
    @ViewState private var added: String?
    @ViewState private var picked: PickedDue?
    @ViewState private var listID: String?
    @FocusState private var focused: Bool

    var body: some View {
        let entry = parsed
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "plus").font(.system(size: 11, weight: .semibold)).foregroundStyle(focused ? Tone.clay.color : Palette.ink3)
                TextField(placeholder, text: $text)
                    .textFieldStyle(.plain).font(Typo.sans(12.5))
                    .focused($focused)
                    .onSubmit(submit)
                ListPickerButton(listID: $listID, fallback: list)
                DuePickerButton(picked: $picked, now: state.agenda.now)
                Button { state.showQuickTask() } label: { Kbd(HotKeyCenter.shared.display(.quickTask)) }
                    .buttonStyle(.plain).help("打开快速任务窗口")
            }
            .padding(.horizontal, 12).frame(height: 34)
            .background(RoundedRectangle(cornerRadius: 10).fill(focused ? Palette.card : Palette.sunk))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(focused ? Tone.clay.color.opacity(0.5) : Palette.line2))
            .contentShape(Rectangle())
            .onTapGesture { focused = true }
            .animation(Motion.fast, value: focused)
            if let added {
                Chip(text: added, tone: .olive, systemImage: "checkmark").transition(.opacity.combined(with: .offset(y: 3)))
            } else if !text.trimmingCharacters(in: .whitespaces).isEmpty || picked != nil {
                QuickEntryChips(entry: entry, timeBlock: false) {}.transition(.opacity)
            }
        }
        .animation(Motion.spring, value: added)
    }

    private var placeholder: String {
        if let list, listID == nil { return "添加到「\(list.title)」…" }
        return dueToday ? "添加今天的任务…" : "添加任务，可写「明天下午3点」"
    }

    private var parsed: QuickEntry {
        var e = QuickEntryParser.parse(text, now: state.agenda.now)
        picked?.apply(to: &e)
        ListPickerButton.apply(listID, to: &e, lists: state.agenda.lists)
        if dueToday, e.due == nil { e.due = Calendar.hub.startOfDay(for: state.agenda.now) }
        if let list, e.listTag == nil { e.listTag = list.title }
        return e
    }

    private func submit() {
        let entry = parsed
        guard state.agenda.add(entry, timeBlock: false) else { return }
        let target = entry.listTag ?? state.agenda.defaultList?.title ?? ""
        let when = entry.due.map { Agenda.relativeDay($0, now: state.agenda.now) + (entry.hasTime ? " " + Agenda.clock($0) : "") }
        added = "已添加到「\(target)」" + (when.map { " · " + $0 } ?? "")
        text = ""
        picked = nil
        focused = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { added = nil }
    }
}

/// Four small figures; health is wrapped in last night's sleep against an eight-hour night.
private struct TrayMetrics: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let d = state.hub.data
        let h = d.health?.data
        HStack(spacing: 8) {
            health(sleep: h?.sleepMinutes, steps: h?.steps)
            mini("今日支出", d.bills?.data?.todayTotal.map { "¥" + Fmt.number($0, $0 >= 1000 ? 0 : 2) } ?? "—")
            let token = d.token[.day]?.data
            mini("Token", (token?.today?.total ?? token?.total).map { TokenFormat.short($0 / 1_000_000) } ?? "—")
            let net = d.net?.data
            if let p = net?.pools?.first, let used = p.usedBytes, let total = p.totalBytes {
                mini("剩余流量", HubFormat.gb(max(0, total - used), 0) + "G")
            } else {
                mini("今日流量", net?.today.map { HubFormat.gb(($0.downBytes ?? 0) + ($0.upBytes ?? 0)) + "G" } ?? "—")
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private func health(sleep: Double?, steps: Double?) -> some View {
        Button { state.openMainWindow("life"); state.focus(.health) } label: {
            HStack(spacing: 8) {
                ZStack {
                    Ring(value: min(100, (sleep ?? 0) / 480 * 100), color: Tone.olive.color, size: 42, width: 4.5)
                    VStack(spacing: -1) {
                        Text(sleep.map { String(format: "%.1f", $0 / 60) } ?? "—").font(Typo.serif(13)).monospacedDigit()
                        Text("小时").font(Typo.sans(8.5)).foregroundStyle(Palette.ink3)
                    }
                }
                .help(sleep.map { "睡眠 \(HubFormat.minutes($0)) / 8 小时" } ?? "没有睡眠数据")
                VStack(alignment: .leading, spacing: 3) {
                    Label11("健康")
                    Text(steps.map { Fmt.number($0) } ?? "—").font(Typo.serif(15)).monospacedDigit().lineLimit(1)
                    Text("步").font(Typo.sans(10)).foregroundStyle(Palette.ink3)
                }
            }
            .padding(.horizontal, 9).padding(.vertical, 8)
            .frame(maxHeight: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .layoutPriority(1)
    }

    private func mini(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label11(label).lineLimit(1)
            Text(value).font(Typo.serif(15)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.7)
        }
        .padding(10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
    }
}

/// A module's compact view inside the panel; the arrow opens it in the main window.
private struct TrayModuleCard: View {
    var module: ModuleID
    @Environment(AppState.self) private var state

    var body: some View {
        let info = module.info
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: info.symbol).font(.system(size: 11.5, weight: .medium)).foregroundStyle(info.tone.color)
                    .frame(width: 22, height: 22).background(RoundedRectangle(cornerRadius: 7).fill(info.tone.tint))
                Text(info.title).font(Typo.sans(12.5, .semibold)).lineLimit(1)
                if let stamp = state.stamp(module) { Text(stamp).font(Typo.sans(10.5)).foregroundStyle(Palette.ink4).monospacedDigit().fixedSize() }
                if let status = state.hubStatus(module) { HubBadge(status: status) }
                Spacer(minLength: 0)
                Button { state.openMainWindow(nil); state.focus(module) } label: {
                    Image(systemName: "arrow.up.right").font(.system(size: 10, weight: .semibold)).foregroundStyle(Palette.ink3)
                        .frame(width: 22, height: 22).background(RoundedRectangle(cornerRadius: 6).fill(Palette.card))
                }
                .buttonStyle(.plain).help("在主窗口打开")
            }
            .padding(.bottom, 10)
            ModuleBody(id: module, size: .compact)
                .frame(maxWidth: .infinity, maxHeight: info.trayAutoHeight ? nil : .infinity, alignment: .topLeading)
        }
        .padding(14)
        .frame(height: info.trayAutoHeight ? nil : Metrics.compactHeight - 8)
        .background(RoundedRectangle(cornerRadius: 14).fill(Palette.bg.opacity(0.6)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Palette.line2))
        .environment(\.moduleTone, info.tone)
    }
}

// MARK: - Editing

private struct TrayEditFrame: ViewModifier {
    var active: Bool
    var title: String
    var first: Bool
    var last: Bool
    var move: (Int) -> Void
    var remove: () -> Void

    func body(content: Content) -> some View {
        if active {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 4) {
                    Text(title).font(Typo.sans(11, .semibold)).foregroundStyle(Tone.clay.color)
                    Spacer()
                    tool("chevron.up", disabled: first) { move(-1) }
                    tool("chevron.down", disabled: last) { move(1) }
                    tool("xmark", disabled: false, action: remove)
                }
                content.disabled(true).opacity(0.75)
                    .frame(maxHeight: 132, alignment: .top).clipped()
            }
            .padding(8)
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Tone.clay.color.opacity(0.5), style: StrokeStyle(lineWidth: 1.2, dash: [5, 4])))
        } else {
            content
        }
    }

    private func tool(_ symbol: String, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 9.5, weight: .bold)).foregroundStyle(Palette.ink2)
                .frame(width: 22, height: 20).background(RoundedRectangle(cornerRadius: 6).fill(Palette.sunk))
        }
        .buttonStyle(.plain).disabled(disabled).opacity(disabled ? 0.35 : 1)
    }
}

private struct TrayAddChips: View {
    var page: TrayPage
    @Environment(AppState.self) private var state

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("添加组件").font(Typo.sans(11.5, .semibold)).foregroundStyle(Palette.ink2)
            if page.unused.isEmpty {
                Text("所有组件都已在这一页").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            } else {
                Flow(spacing: 6) {
                    ForEach(page.unused, id: \.self) { item in
                        Button { state.editLayout { $0.editTrayPage(page.id) { $0.add(item) } } } label: {
                            HStack(spacing: 5) {
                                Image(systemName: TrayItem.symbol(item)).font(.system(size: 10))
                                Text(TrayItem.title(item))
                            }
                            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink2)
                            .padding(.horizontal, 10).padding(.vertical, 5)
                            .background(Capsule().fill(Palette.sunk))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1.2, dash: [5, 4])))
    }
}

/// Rename, reorder, add and delete panel pages.
private struct TrayPageTools: View {
    var page: TrayPage
    var index: Int
    var count: Int
    var select: (String) -> Void
    @Environment(AppState.self) private var state
    @ViewState private var title = ""
    @ViewState private var confirmDelete = false

    var body: some View {
        HStack(spacing: 6) {
            TextField("页名", text: $title)
                .textFieldStyle(.roundedBorder).font(Typo.sans(12)).frame(width: 84)
                .onSubmit(commit)
                .onChange(of: title) { _, t in if t.count > TrayPage.maxTitle { title = String(t.prefix(TrayPage.maxTitle)) } }
            tool("chevron.left", "前移", disabled: index == 0) { state.editLayout { $0.moveTrayPage(page.id, by: -1) } }
            tool("chevron.right", "后移", disabled: index == count - 1) { state.editLayout { $0.moveTrayPage(page.id, by: 1) } }
            Spacer()
            Button {
                var id: String?
                state.editLayout { id = $0.addTrayPage() }
                if let id { select(id) }
            } label: { Label("新页", systemImage: "plus").font(Typo.sans(11.5)) }
                .buttonStyle(.plain).foregroundStyle(Palette.ink2)
                .disabled(count >= TrayPage.maxPages).opacity(count >= TrayPage.maxPages ? 0.4 : 1)
                .help(count >= TrayPage.maxPages ? "最多 \(TrayPage.maxPages) 页" : "新增一页")
            Button { confirmDelete = true } label: { Label("删除", systemImage: "trash").font(Typo.sans(11.5)) }
                .buttonStyle(.plain).foregroundStyle(Tone.rose.color)
                .disabled(count <= 1).opacity(count <= 1 ? 0.4 : 1)
        }
        .onAppear { title = page.title }
        .onChange(of: page.id) { _, _ in title = page.title }
        .onDisappear(perform: commit)
        .alert("删除「\(page.title)」页？", isPresented: $confirmDelete) {
            Button("删除", role: .destructive) {
                let fallback = index > 0 ? index - 1 : 1
                let pages = state.layout.trayPages
                if pages.indices.contains(fallback) { select(pages[fallback].id) }
                state.editLayout { $0.removeTrayPage(page.id) }
            }
            Button("取消", role: .cancel) {}
        } message: { Text("只删除面板里的这一页，模块和数据不受影响。") }
    }

    private func commit() {
        guard title != page.title else { return }
        state.editLayout { $0.renameTrayPage(page.id, title: title) }
    }

    private func tool(_ symbol: String, _ help: String, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 10, weight: .semibold)).foregroundStyle(Palette.ink2)
                .frame(width: 24, height: 22).background(RoundedRectangle(cornerRadius: 6).fill(Palette.sunk))
        }
        .buttonStyle(.plain).disabled(disabled).opacity(disabled ? 0.35 : 1).help(help)
    }
}
