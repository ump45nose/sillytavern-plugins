import AppKit
import HubKit
import SwiftUI

/// What the task page shows; the sidebar lists the same entries under 任务.
enum TaskScope: Hashable {
    case overdue, today, upcoming, calendar, completed, all
    case list(String)

    var title: String {
        switch self {
        case .overdue: "逾期"
        case .today: "今天"
        case .upcoming: "即将"
        case .calendar: "日历"
        case .completed: "已完成"
        case .all: "所有任务"
        case .list: "清单"
        }
    }

    var symbol: String {
        switch self {
        case .overdue: "exclamationmark.circle"
        case .today: "sun.max"
        case .upcoming: "calendar.day.timeline.left"
        case .calendar: "calendar"
        case .completed: "checkmark.circle"
        case .all: "tray.full"
        case .list: "list.bullet"
        }
    }
}

struct TasksPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let scope = resolved
        let selected = scope == .calendar ? nil : state.taskSelection.flatMap(find)
        VStack(alignment: .leading, spacing: 14) {
            TasksHeader(scope: scope)
            SyncNotice()
            content(scope).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .overlay(alignment: .topTrailing) {
            if let selected {
                TaskInspector(task: selected)
                    .padding(.top, 64)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .padding(.horizontal, 28).padding(.top, 4).padding(.bottom, 24)
        .animation(Motion.spring, value: state.taskSelection)
        .onChange(of: scope) { state.taskSelection = nil }
        .onExitCommand { state.taskSelection = nil }
    }

    /// A list removed elsewhere falls back to the board.
    private var resolved: TaskScope {
        if case .list(let id) = state.taskScope, !state.agenda.lists.contains(where: { $0.id == id }) { return .all }
        return state.taskScope
    }

    @ViewBuilder private func content(_ scope: TaskScope) -> some View {
        switch scope {
        case .overdue: OverdueTasks()
        case .today: TodayTasks()
        case .upcoming: UpcomingTasks()
        case .calendar: TaskCalendar()
        case .completed: CompletedTasks()
        case .all: ListBoard()
        case .list(let id): SingleList(listID: id)
        }
    }

    private func find(_ id: String) -> AgendaTask? {
        let v = state.agenda.view
        func search(_ items: [AgendaTask]) -> AgendaTask? {
            for t in items {
                if t.id == id { return t }
                if let hit = search(t.subtasks) { return hit }
            }
            return nil
        }
        return search(v.allTasks) ?? search(v.completed)
    }
}

// MARK: - Header

private struct TasksHeader: View {
    var scope: TaskScope
    @Environment(AppState.self) private var state
    @AppStorage("taskListByDue") private var byDue = false
    @ViewState private var creating = false

    var body: some View {
        HStack(alignment: .bottom, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(Typo.serif(34)).tracking(-0.6).lineLimit(1)
                Text(subtitle).font(Typo.sans(13)).foregroundStyle(Palette.ink2)
            }
            Spacer()
            trailing
        }
    }

    private var title: String {
        if case .list(let id) = scope { return state.agenda.lists.first { $0.id == id }?.title ?? "清单" }
        return scope.title
    }

    private var subtitle: String {
        let agenda = state.agenda, v = agenda.view
        switch scope {
        case .overdue:
            return v.overdue.isEmpty ? "没有过了截止日的任务" : "\(v.overdue.count) 项过了截止日 · 按清单分列"
        case .today:
            let open = v.today.filter { !$0.completed }.count
            let events = v.events.count + v.allDay.count
            return [Agenda.longDay(agenda.now), "\(open) 项待办", events > 0 ? "\(events) 个日程" : nil,
                    v.todayDone > 0 ? "已完成 \(v.todayDone)" : nil].compactMap { $0 }.joined(separator: " · ")
        case .upcoming:
            return "明天起 · \((v.upcoming + v.later).count) 项"
        case .calendar:
            return "任务按到期日放进月历，和日程排在一起"
        case .completed:
            return "共 \(v.completed.count) 项 · 最近完成的在前"
        case .all:
            return "\(agenda.lists.count) 个清单 · \(v.allTasks.filter { !$0.completed }.count) 项未完成"
        case .list(let id):
            let pinned = agenda.todayLists.contains { $0.id == id }
            return "\(v.open(in: id).count) 项未完成" + (pinned ? " · 显示在「今天」" : "")
        }
    }

    @ViewBuilder private var trailing: some View {
        let agenda = state.agenda
        HStack(spacing: 8) {
            switch scope {
            case .overdue:
                if !agenda.view.overdue.isEmpty {
                    ToolButton(symbol: "sun.max", title: "全部改到今天") {
                        let today = Calendar.hub.startOfDay(for: agenda.now)
                        withAnimation(Motion.spring) { agenda.view.overdue.forEach { agenda.reschedule($0, to: today) } }
                    }
                }
            case .today:
                if !agenda.view.overdue.isEmpty {
                    Button { withAnimation(Motion.spring) { state.taskScope = .overdue } } label: {
                        Chip(text: "\(agenda.view.overdue.count) 项逾期", tone: .rose, systemImage: "arrow.right")
                    }
                    .buttonStyle(.plain)
                }
                HStack(spacing: 6) {
                    Text("「今天」显示的清单").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    TodayListsMenu()
                }
                .padding(.horizontal, 10).frame(height: 30)
                .background(RoundedRectangle(cornerRadius: 9).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Palette.line))
            case .list(let id):
                Segmented(options: [(false, "我的顺序"), (true, "到期日")], selection: $byDue, small: true).fixedSize()
                if let list = agenda.lists.first(where: { $0.id == id }) { ListMenu(list: list) }
            case .all:
                ToolButton(symbol: "plus", title: "新建清单") { creating = true }
                    .popover(isPresented: $creating) {
                        NameField(title: "新建清单", initial: "") { name in
                            if let name { state.taskScope = .list(agenda.createList(name)) }
                            creating = false
                        }
                    }
            default:
                EmptyView()
            }
            if scope != .completed { NewTaskButton(scope: scope) }
        }
    }
}

/// 新建任务: the quick-add field with list and date pickers, preset from the current view.
private struct NewTaskButton: View {
    var scope: TaskScope
    @Environment(AppState.self) private var state
    @ViewState private var open = false

    var body: some View {
        ToolButton(symbol: "plus", title: "新建任务", prominent: true) { open = true }
            .popover(isPresented: $open, arrowEdge: .bottom) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("新建任务").font(Typo.serif(17))
                    InlineQuickAdd(placeholder: "任务名称，可写「明天下午3点」", list: list, due: due, autofocus: true)
                    Text("↩ 添加，可以连续添加 · Esc 关闭").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                }
                .padding(16)
                .frame(width: 440)
                .background(Palette.card)
                .environment(state)
            }
    }

    private var list: TaskListRecord? {
        if case .list(let id) = scope { return state.agenda.lists.first { $0.id == id } }
        return nil
    }

    private var due: Date? {
        let cal = Calendar.hub, today = cal.startOfDay(for: state.agenda.now)
        switch scope {
        case .today, .overdue: return today
        case .upcoming: return cal.date(byAdding: .day, value: 1, to: today)
        default: return nil
        }
    }
}

/// Rename, pin to 今天, or delete a list.
struct ListMenu: View {
    var list: TaskListRecord
    @Environment(AppState.self) private var state
    @ViewState private var renaming = false
    @ViewState private var confirmDelete = false

    var body: some View {
        let agenda = state.agenda, pinned = agenda.todayLists.contains { $0.id == list.id }
        Menu {
            Button("打开清单") { state.taskScope = .list(list.id) }
            Button(pinned ? "不在「今天」显示" : "在「今天」显示") { agenda.showInToday(list.id, !pinned) }
            Divider()
            Button("重命名…") { renaming = true }
            Button("删除清单…", role: .destructive) { confirmDelete = true }
        } label: {
            Image(systemName: "ellipsis").font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.ink3)
                .frame(width: 26, height: 22).contentShape(Rectangle())
        }
        .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().tint(Palette.ink3)
        .popover(isPresented: $renaming) {
            NameField(title: "重命名清单", initial: list.title) { name in
                if let name, name != list.title { agenda.renameList(list.id, to: name) }
                renaming = false
            }
        }
        .alert("删除清单「\(list.title)」？", isPresented: $confirmDelete) {
            Button("删除", role: .destructive) {
                if state.taskScope == .list(list.id) { state.taskScope = .all }
                agenda.deleteList(list.id)
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("清单里的任务也会一起从 Google Tasks 删除。")
        }
    }
}

// MARK: - Building blocks

/// A titled card of task rows with an add row and an optional fold of finished tasks.
private struct TaskSection<Trailing: View>: View {
    var title: String?
    var caption: String? = nil
    var tone: Tone? = nil
    var tasks: [AgendaTask]
    var events: [AgendaEvent] = []
    var showList = true
    var showDue = true
    var empty: String? = nil
    var add: AddTaskRow? = nil
    var completed: [AgendaTask] = []
    @ViewBuilder var trailing: Trailing
    @Environment(AppState.self) private var state
    @ViewState private var showDone = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if title != nil || caption != nil {
                HStack(spacing: 8) {
                    if let tone { Circle().fill(tone.color).frame(width: 7, height: 7) }
                    if let title { Text(title).font(Typo.sans(13.5, .semibold)).foregroundStyle(tone == .rose ? Tone.rose.color : Palette.ink) }
                    let open = tasks.filter { !$0.completed }.count
                    if !tasks.isEmpty { Text("\(open > 0 ? open : tasks.count)").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit() }
                    if let caption { Text(caption).font(Typo.sans(12)).foregroundStyle(Palette.ink3).lineLimit(1) }
                    Spacer(minLength: 4)
                    trailing
                }
                .frame(minHeight: 24)
                .padding(.bottom, 6)
            }
            if !events.isEmpty {
                Flow(spacing: 6) { ForEach(events) { EventPill(event: $0) } }.padding(.bottom, 8)
            }
            ForEach(tasks) { t in
                TaskRow(task: t, showList: showList, showDue: showDue, onSelect: { state.taskSelection = $0.id }, selectedID: state.taskSelection)
            }
            if tasks.isEmpty, let empty {
                Text(empty).font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).padding(.vertical, 8)
            }
            if let add { add.overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) } }
            if !completed.isEmpty {
                Button { withAnimation(Motion.spring) { showDone.toggle() } } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.right").font(.system(size: 9, weight: .bold)).rotationEffect(.degrees(showDone ? 90 : 0))
                        Text("已完成 \(completed.count)").font(Typo.sans(12))
                        Spacer()
                    }
                    .foregroundStyle(Palette.ink3).padding(.vertical, 8).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                if showDone {
                    ForEach(completed.prefix(50)) { t in
                        TaskRow(task: t, showList: false, onSelect: { state.taskSelection = $0.id }, selectedID: state.taskSelection)
                    }
                }
            }
        }
        .padding(.horizontal, 18).padding(.top, 14).padding(.bottom, 8)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
        .animation(Motion.spring, value: tasks.map(\.id))
        .animation(Motion.spring, value: tasks.map(\.completed))
    }
}

extension TaskSection where Trailing == EmptyView {
    init(title: String?, caption: String? = nil, tone: Tone? = nil, tasks: [AgendaTask], events: [AgendaEvent] = [],
         showList: Bool = true, showDue: Bool = true, empty: String? = nil, add: AddTaskRow? = nil, completed: [AgendaTask] = []) {
        self.init(title: title, caption: caption, tone: tone, tasks: tasks, events: events, showList: showList, showDue: showDue,
                  empty: empty, add: add, completed: completed) { EmptyView() }
    }
}

/// "+ 添加任务" that turns into a field; dates and #lists parse like the quick panel, else the row's day and list apply.
struct AddTaskRow: View {
    var due: Date? = nil
    var list: TaskListRecord? = nil
    var parent: AgendaTask? = nil
    @Environment(AppState.self) private var state
    @ViewState private var editing = false
    @ViewState private var text = ""
    @ViewState private var listID: String?
    @ViewState private var picking = false
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 10) {
            if editing {
                Circle().strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1.5, dash: [2.5, 2])).frame(width: 16, height: 16)
                TextField(parent == nil ? "任务名称，可写「明天下午3点」" : "子任务名称", text: $text)
                    .textFieldStyle(.plain).font(Typo.sans(13)).focused($focused)
                    .onSubmit(submit)
                    .onExitCommand { text = ""; editing = false }
                    .onChange(of: focused) { _, on in
                        // Focus moves to the list picker on mouse-down, before it reports open.
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { if !on, !focused, text.isEmpty, !picking { editing = false } }
                    }
                if let hint { Text(hint).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
                if parent == nil {
                    ListPickerButton(listID: $listID, fallback: list) { open in
                        picking = open
                        if !open { focused = true }
                    }
                }
            } else {
                Button {
                    editing = true
                    DispatchQueue.main.async { focused = true }
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "plus").font(.system(size: 11, weight: .semibold)).frame(width: 16)
                        Text(parent == nil ? "添加任务" : "添加子任务").font(Typo.sans(12.5))
                        Spacer()
                    }
                    .foregroundStyle(Palette.ink3).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .frame(height: 36)
    }

    private var entry: QuickEntry {
        var e = QuickEntryParser.parse(text, now: state.agenda.now)
        if e.due == nil, let due { e.due = Calendar.hub.startOfDay(for: due) }
        ListPickerButton.apply(listID ?? list?.id, to: &e, lists: state.agenda.lists)
        return e
    }

    private var hint: String? {
        guard parent == nil, !text.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
        let e = entry
        return e.due.map { Agenda.relativeDay($0, now: state.agenda.now) + (e.hasTime ? " " + Agenda.clock($0) : "") }
    }

    private func submit() {
        let t = text.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { editing = false; return }
        if let parent {
            state.agenda.addSubtask(to: parent, title: t)
        } else if !state.agenda.add(entry, timeBlock: false) {
            return
        }
        text = ""
        focused = true
    }
}

/// An event as a small tinted pill: time and title; opens the editor.
struct EventPill: View {
    var event: AgendaEvent
    @Environment(AppState.self) private var state
    @ViewState private var editing = false

    var body: some View {
        Button { editing = true } label: {
            HStack(spacing: 6) {
                RoundedRectangle(cornerRadius: 1.5).fill(event.tone.color).frame(width: 3, height: 12)
                if !event.allDay { Text(Agenda.clock(event.start)).font(Typo.sans(11.5)).monospacedDigit().foregroundStyle(Palette.ink2) }
                Text(event.title).font(Typo.sans(12, .medium)).foregroundStyle(Palette.ink).lineLimit(1)
            }
            .padding(.leading, 6).padding(.trailing, 10).frame(height: 26)
            .background(RoundedRectangle(cornerRadius: 7).fill(event.tone.tint))
        }
        .buttonStyle(.plain)
        .popover(isPresented: $editing, arrowEdge: .bottom) {
            EventEditor(mode: .edit(event)) { editing = false }.environment(state)
        }
    }
}

// MARK: - Views

private struct ColumnHeightKey: EnvironmentKey { static let defaultValue: CGFloat = 600 }

extension EnvironmentValues {
    /// How tall a task column may grow before it scrolls inside.
    fileprivate var columnHeight: CGFloat {
        get { self[ColumnHeightKey.self] }
        set { self[ColumnHeightKey.self] = newValue }
    }
}

/// Columns side by side, each as tall as its content up to the page; the row scrolls sideways when it doesn't fit.
private struct ColumnBoard<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        GeometryReader { g in
            let height = max(g.size.height - HubScroller.barHeight, 120)
            HubScroll(.horizontal, bar: true) {
                HStack(alignment: .top, spacing: 14) { content }
                    .padding(.bottom, 2)
                    .frame(height: height, alignment: .top)
            }
            .environment(\.columnHeight, height - 2)
        }
    }
}

/// Stable colour per list, by its place in the sidebar.
private func listTone(_ id: String, in lists: [TaskListRecord]) -> Tone {
    let tones: [Tone] = [.sky, .olive, .ochre, .plum, .rose, .clay, .steel]
    return tones[(lists.firstIndex { $0.id == id } ?? 0) % tones.count]
}

/// One list of tasks as a card column: header, rows that scroll inside, the add row pinned at the bottom.
private struct TaskColumn<Trailing: View>: View {
    var title: String
    var caption: String? = nil
    var dot: Color? = nil
    var titleColor: Color = Palette.ink
    var width: CGFloat = 292
    var dim = false
    var tasks: [AgendaTask]
    var events: [AgendaEvent] = []
    var showList = true
    var showDue = true
    var empty: String? = nil
    var add: AddTaskRow? = nil
    var completed: [AgendaTask] = []
    @ViewBuilder var trailing: Trailing
    @Environment(AppState.self) private var state
    @Environment(\.columnHeight) private var maxHeight
    @ViewState private var showDone = false

    var body: some View {
        let chrome: CGFloat = 46 + (add == nil ? 8 : 38)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                if let dot { Circle().fill(dot).frame(width: 7, height: 7) }
                Text(title).font(Typo.sans(13.5, .semibold)).foregroundStyle(titleColor).lineLimit(1)
                let open = tasks.filter { !$0.completed }.count
                if open > 0 { Text("\(open)").font(Typo.sans(12)).foregroundStyle(Palette.ink4).monospacedDigit() }
                if let caption { Text(caption).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1) }
                Spacer(minLength: 4)
                trailing
            }
            .padding(.horizontal, 16).frame(height: 46)
            HubScroll {
                VStack(alignment: .leading, spacing: 0) {
                    if !events.isEmpty {
                        Flow(spacing: 6) { ForEach(events) { EventPill(event: $0) } }.padding(.bottom, 8)
                    }
                    ForEach(tasks) { t in
                        TaskRow(task: t, showList: showList, showDue: showDue, onSelect: { state.taskSelection = $0.id },
                                selectedID: state.taskSelection)
                    }
                    if tasks.isEmpty, let empty {
                        Text(empty).font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6)
                    }
                    if !completed.isEmpty { doneFold }
                }
                .padding(.horizontal, 16).padding(.bottom, 4)
            }
            .scrollIndicators(.automatic)
            .frame(maxHeight: max(maxHeight - chrome, 80))
            .fixedSize(horizontal: false, vertical: true)
            if let add {
                add.padding(.horizontal, 16).overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
            }
        }
        .frame(width: width, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
        .opacity(dim ? 0.62 : 1)
        .animation(Motion.spring, value: tasks.map(\.id))
        .animation(Motion.spring, value: tasks.map(\.completed))
    }

    @ViewBuilder private var doneFold: some View {
        Button { withAnimation(Motion.spring) { showDone.toggle() } } label: {
            HStack(spacing: 6) {
                Image(systemName: "chevron.right").font(.system(size: 9, weight: .bold)).rotationEffect(.degrees(showDone ? 90 : 0))
                Text("已完成 \(completed.count)").font(Typo.sans(12))
                Spacer()
            }
            .foregroundStyle(Palette.ink3).padding(.vertical, 8).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
        if showDone {
            ForEach(completed.prefix(50)) { t in
                TaskRow(task: t, showList: false, onSelect: { state.taskSelection = $0.id }, selectedID: state.taskSelection)
            }
            .transition(.opacity.combined(with: .move(edge: .top)))
        }
    }
}

extension TaskColumn where Trailing == EmptyView {
    init(title: String, caption: String? = nil, dot: Color? = nil, titleColor: Color = Palette.ink, width: CGFloat = 292, dim: Bool = false,
         tasks: [AgendaTask], events: [AgendaEvent] = [], showList: Bool = true, showDue: Bool = true, empty: String? = nil,
         add: AddTaskRow? = nil, completed: [AgendaTask] = []) {
        self.init(title: title, caption: caption, dot: dot, titleColor: titleColor, width: width, dim: dim, tasks: tasks, events: events,
                  showList: showList, showDue: showDue, empty: empty, add: add, completed: completed) { EmptyView() }
    }
}

/// A day's events on the serif-clock timeline: all-day ones as pills, then a 现在 marker between past and future.
struct DaySchedule: View {
    var day: Date
    @Environment(AppState.self) private var state

    private enum Stop: Identifiable {
        case event(AgendaEvent), task(AgendaTask, Date), now(Date)
        var id: String {
            switch self {
            case .event(let e): e.id
            case .task(let t, _): "task:" + t.id
            case .now: "now"
            }
        }
        var start: Date {
            switch self {
            case .event(let e): e.start
            case .task(_, let at): at
            case .now(let at): at
            }
        }
    }

    var body: some View {
        let agenda = state.agenda, now = agenda.now
        let events = agenda.view.events(on: day), allDay = events.filter(\.allDay)
        let tasks = agenda.view.timedTasks(on: day)
        let timed = (events.filter { !$0.allDay }.map(Stop.event) + tasks.map { Stop.task($0.task, $0.at) }).sorted { $0.start < $1.start }
        let isToday = Calendar.hub.isDate(day, inSameDayAs: now)
        let split = timed.firstIndex { $0.start > now } ?? timed.count
        let stops: [Stop] = isToday && !timed.isEmpty ? Array(timed.prefix(split)) + [.now(now)] + timed.dropFirst(split) : timed
        VStack(alignment: .leading, spacing: 0) {
            if !allDay.isEmpty {
                Flow(spacing: 6) { ForEach(allDay) { EventPill(event: $0) } }.padding(.bottom, 12)
            }
            ForEach(Array(stops.enumerated()), id: \.1.id) { i, stop in
                switch stop {
                case .now(let at):
                    TimelineEntry(time: Agenda.clock(at), first: i == 0, last: i == stops.count - 1, dot: Tone.clay.color,
                                  timeColor: Tone.clay.color, timeWidth: 40, timeSize: 14, gap: 16) {
                        Text("现在").font(Typo.sans(11.5, .medium)).foregroundStyle(Tone.clay.color).padding(.top, 2)
                    }
                case .event(let e):
                    TimelineEntry(time: Agenda.clock(e.start), first: i == 0, last: i == stops.count - 1,
                                  timeColor: isToday && e.end <= now ? Palette.ink4 : Palette.ink3, timeWidth: 40, timeSize: 14, gap: 16) {
                        EventLine(event: e, past: isToday && e.end <= now)
                    }
                case .task(let t, let at):
                    let past = t.completed || (isToday && at <= now)
                    TimelineEntry(time: Agenda.clock(at), first: i == 0, last: i == stops.count - 1, dot: Tone.olive.color.opacity(0.8),
                                  timeColor: past ? Palette.ink4 : Palette.ink3, timeWidth: 40, timeSize: 14, gap: 16) {
                        ScheduledTask(task: t)
                    }
                }
            }
            if events.isEmpty && tasks.isEmpty {
                Text(isToday ? "今天没有日程" : "没有日程").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6)
            }
        }
    }
}

/// A timed task inside the schedule: tick it off where it stands.
private struct ScheduledTask: View {
    var task: AgendaTask
    @Environment(AppState.self) private var state

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Button { withAnimation(Motion.spring) { state.agenda.toggle(task) } } label: {
                Image(systemName: task.completed ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 13)).foregroundStyle(task.completed ? Tone.olive.color : Palette.ink3)
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 2) {
                Text(task.title).font(Typo.sans(13)).foregroundStyle(task.completed ? Palette.ink3 : Palette.ink)
                    .strikethrough(task.completed, color: Palette.ink4).lineLimit(2)
                Text("任务 · " + task.listTitle).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
            }
        }
    }
}

private struct ScheduleColumn: View {
    var day: Date
    @Environment(AppState.self) private var state
    @Environment(\.columnHeight) private var maxHeight
    @ViewState private var newEvent = false

    var body: some View {
        let agenda = state.agenda, now = agenda.now
        let count = agenda.view.events(on: day).count + agenda.view.timedTasks(on: day).count
        let isToday = Calendar.hub.isDate(day, inSameDayAs: now)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(isToday ? "今天的日程" : "日程").font(Typo.sans(13.5, .semibold))
                if count > 0 { Text("\(count)").font(Typo.sans(12)).foregroundStyle(Palette.ink4).monospacedDigit() }
                Spacer()
                if agenda.writableCalendar != nil {
                    Button { newEvent = true } label: {
                        Image(systemName: "plus").font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.ink3)
                            .frame(width: 22, height: 22).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain).help("新建日程")
                    .popover(isPresented: $newEvent, arrowEdge: .bottom) {
                        EventEditor(mode: .create(AgendaModule.nextSlot(after: now))) { newEvent = false }.environment(state)
                    }
                }
            }
            .padding(.horizontal, 16).frame(height: 46)
            HubScroll {
                DaySchedule(day: day).padding(.horizontal, 16).padding(.top, 2).padding(.bottom, 14)
            }
            .scrollIndicators(.automatic)
            .frame(maxHeight: max(maxHeight - 46, 80))
            .fixedSize(horizontal: false, vertical: true)
        }
        .frame(width: 264, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }
}

/// An event's title and span on the timeline; click to edit.
struct EventLine: View {
    var event: AgendaEvent
    var past = false
    @Environment(AppState.self) private var state
    @ViewState private var editing = false

    var body: some View {
        Button { editing = true } label: {
            VStack(alignment: .leading, spacing: 2) {
                Text(event.title).font(Typo.sans(13, .medium)).foregroundStyle(past ? Palette.ink3 : Palette.ink).lineLimit(2)
                Text(caption).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .popover(isPresented: $editing, arrowEdge: .leading) {
            EventEditor(mode: .edit(event)) { editing = false }.environment(state)
        }
    }

    private var caption: String {
        let minutes = Int(event.end.timeIntervalSince(event.start) / 60)
        let span = minutes >= 60 ? (minutes % 60 == 0 ? "\(minutes / 60) 小时" : String(format: "%.1f 小时", Double(minutes) / 60)) : "\(minutes) 分钟"
        return [span, event.location].compactMap { $0?.isEmpty == false ? $0 : nil }.joined(separator: " · ")
    }
}

private struct OverdueTasks: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, v = agenda.view
        let groups = agenda.lists.compactMap { l -> (TaskListRecord, [AgendaTask])? in
            let tasks = v.overdue.filter { $0.listID == l.id }
            return tasks.isEmpty ? nil : (l, tasks)
        }
        if groups.isEmpty {
            VStack(spacing: 8) {
                Image(systemName: "checkmark.circle").font(.system(size: 26, weight: .light)).foregroundStyle(Tone.olive.color)
                Text("没有逾期的任务").font(Typo.serif(19))
                Text("过了截止日还没完成的任务会出现在这里。").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
            }
            .frame(maxWidth: .infinity).padding(.vertical, 60)
        } else {
            ColumnBoard {
                ForEach(groups, id: \.0.id) { list, tasks in
                    TaskColumn(title: list.title, dot: listTone(list.id, in: agenda.lists).color, tasks: tasks, showList: false) {
                        Button {
                            let today = Calendar.hub.startOfDay(for: agenda.now)
                            withAnimation(Motion.spring) { tasks.forEach { agenda.reschedule($0, to: today) } }
                        } label: {
                            Text("改到今天").font(Typo.sans(11.5)).foregroundStyle(Palette.ink2)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

private struct TodayTasks: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, v = agenda.view, today = Calendar.hub.startOfDay(for: agenda.now)
        ColumnBoard {
            TaskColumn(title: "今天到期", tasks: v.today, showDue: false, empty: "今天没有到期的任务", add: AddTaskRow(due: today))
            ForEach(agenda.todayExtras, id: \.list.id) { list, tasks in
                TaskColumn(title: list.title, dot: listTone(list.id, in: agenda.lists).color, tasks: tasks, showList: false,
                           empty: "清单里没有其他未完成的任务", add: AddTaskRow(list: list)) {
                    Button { withAnimation(Motion.spring) { agenda.showInToday(list.id, false) } } label: {
                        Image(systemName: "pin.slash").font(.system(size: 11)).foregroundStyle(Palette.ink3)
                    }
                    .buttonStyle(.plain).help("不在「今天」显示这个清单")
                }
            }
            ScheduleColumn(day: today)
        }
    }
}

/// The next seven days one column each, then everything later in one.
private struct UpcomingTasks: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, v = agenda.view, cal = Calendar.hub
        let today = cal.startOfDay(for: agenda.now)
        ColumnBoard {
            ForEach(1...7, id: \.self) { i in
                let day = cal.date(byAdding: .day, value: i, to: today)!
                let tasks = v.tasks(on: day).filter { !$0.completed }, events = v.events(on: day)
                TaskColumn(title: title(day), caption: caption(day), width: 252, dim: tasks.isEmpty && events.isEmpty,
                           tasks: tasks, events: events, showDue: false, empty: "没有安排", add: AddTaskRow(due: day))
            }
            TaskColumn(title: "之后", caption: "一周以后", width: 252, tasks: v.later, empty: "一周以后没有任务")
        }
    }

    private func title(_ day: Date) -> String {
        let rel = Agenda.relativeDay(day, now: state.agenda.now)
        return rel.contains("/") ? Agenda.weekdayName(day) : rel
    }

    private func caption(_ day: Date) -> String {
        let c = Calendar.hub.dateComponents([.month, .day], from: day)
        let rel = Agenda.relativeDay(day, now: state.agenda.now)
        return (["明天", "后天"].contains(rel) ? Agenda.weekdayName(day) + " · " : "") + "\(c.month!)/\(c.day!)"
    }
}

private struct CompletedTasks: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, cal = Calendar.hub
        let done = Array(agenda.view.completed.prefix(300))
        let groups = Dictionary(grouping: done) { cal.startOfDay(for: $0.completedAt ?? .distantPast) }
        HubScroll {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(groups.keys.sorted(by: >), id: \.self) { day in
                    TaskSection(title: day == .distantPast ? "更早" : Agenda.relativeDay(day, now: agenda.now),
                                caption: day == .distantPast ? nil : Agenda.longDay(day), tasks: groups[day]!, showDue: false)
                }
                if done.isEmpty {
                    TaskSection(title: nil, tasks: [], empty: "还没有完成的任务")
                }
            }
            .frame(maxWidth: 820, alignment: .leading)
            .padding(.bottom, 12)
        }
        .scrollIndicators(.never)
    }
}

/// Every list as a column, in sidebar order.
private struct ListBoard: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, v = agenda.view
        ColumnBoard {
            ForEach(agenda.lists) { list in
                TaskColumn(title: list.title, dot: listTone(list.id, in: agenda.lists).color, tasks: v.open(in: list.id),
                           showList: false, empty: "没有未完成的任务", add: AddTaskRow(list: list), completed: v.completed(in: list.id)) {
                    ListMenu(list: list)
                }
            }
        }
    }
}

private struct SingleList: View {
    var listID: String
    @Environment(AppState.self) private var state
    @AppStorage("taskListByDue") private var byDue = false

    var body: some View {
        let agenda = state.agenda, v = agenda.view
        let list = agenda.lists.first { $0.id == listID }
        HubScroll {
            TaskSection(title: nil, tasks: v.open(in: listID, byDue: byDue), showList: false, empty: "清单里没有未完成的任务",
                        add: list.map { AddTaskRow(list: $0) }, completed: v.completed(in: listID))
                .frame(maxWidth: 820, alignment: .leading)
                .padding(.bottom, 12)
        }
        .scrollIndicators(.never)
    }
}

// MARK: - Calendar

private struct TaskCalendar: View {
    @Environment(AppState.self) private var state
    @ViewState private var month: Date?
    @ViewState private var day: Date?

    private enum Item: Identifiable {
        case event(AgendaEvent), task(AgendaTask)
        var id: String {
            switch self {
            case .event(let e): "e-" + e.id
            case .task(let t): "t-" + t.id
            }
        }
    }

    var body: some View {
        let cal = Calendar.hub, now = state.agenda.now
        let today = cal.startOfDay(for: now)
        let first = cal.date(from: cal.dateComponents([.year, .month], from: month ?? now))!
        let lead = (cal.component(.weekday, from: first) + 5) % 7
        let count = cal.range(of: .day, in: .month, for: first)!.count
        let weeks = Int(ceil(Double(lead + count) / 7))
        let start = cal.date(byAdding: .day, value: -lead, to: first)!
        let cells = (0..<weeks * 7).map { cal.date(byAdding: .day, value: $0, to: start)! }
        let selected = day ?? today
        HStack(alignment: .top, spacing: 18) {
            VStack(spacing: 8) {
                HStack(spacing: 8) {
                    Text(verbatim: "\(cal.component(.year, from: first)) 年 \(cal.component(.month, from: first)) 月").font(Typo.serif(22))
                    Spacer()
                    Button("今天") { withAnimation(Motion.spring) { month = nil; day = nil } }
                        .buttonStyle(.plain).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2)
                        .padding(.horizontal, 12).frame(height: 28)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Palette.card))
                        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.line))
                    ForEach([-1, 1], id: \.self) { step in
                        Button { withAnimation(Motion.spring) { month = cal.date(byAdding: .month, value: step, to: first) } } label: {
                            Image(systemName: step < 0 ? "chevron.left" : "chevron.right")
                                .font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.ink2)
                                .frame(width: 30, height: 28)
                                .background(RoundedRectangle(cornerRadius: 8).fill(Palette.card))
                                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.line))
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                HStack(spacing: 6) {
                    ForEach(MonthCalendar.weekdays, id: \.self) {
                        Text("周" + $0).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.leading, 8)
                    }
                }
                GeometryReader { g in
                    let h = (g.size.height - CGFloat(weeks - 1) * 6) / CGFloat(weeks)
                    VStack(spacing: 6) {
                        ForEach(0..<weeks, id: \.self) { w in
                            HStack(spacing: 6) {
                                ForEach(cells[(w * 7)..<(w * 7 + 7)], id: \.self) { d in
                                    cell(d, height: h, inMonth: cal.isDate(d, equalTo: first, toGranularity: .month),
                                         today: today, selected: cal.isDate(d, inSameDayAs: selected))
                                }
                            }
                        }
                    }
                }
                .frame(minHeight: 420)
            }
            DayPanel(day: selected).frame(width: 320)
        }
    }

    private func items(_ d: Date) -> [Item] {
        let v = state.agenda.view
        return v.events(on: d).map(Item.event) + v.tasks(on: d).map(Item.task)
    }

    private func cell(_ d: Date, height: CGFloat, inMonth: Bool, today: Date, selected: Bool) -> some View {
        let cal = Calendar.hub, all = items(d), isToday = cal.isDate(d, inSameDayAs: today)
        let fit = max(0, Int((height - 34) / 18))
        let shown = all.count > fit ? Array(all.prefix(max(fit - 1, 0))) : all
        return Button {
            withAnimation(Motion.spring) {
                day = d
                if !inMonth { month = d }
            }
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text(verbatim: "\(cal.component(.day, from: d))")
                    .font(Typo.sans(12.5, isToday ? .semibold : .regular)).monospacedDigit()
                    .foregroundStyle(isToday ? Color.white : inMonth ? Palette.ink : Palette.ink4)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(isToday ? Tone.clay.color : .clear))
                ForEach(shown) { line($0, today: today) }
                if all.count > shown.count {
                    Text("还有 \(all.count - shown.count) 项").font(Typo.sans(10.5)).foregroundStyle(Palette.ink3).padding(.leading, 4)
                }
                Spacer(minLength: 0)
            }
            .padding(5)
            .frame(maxWidth: .infinity, minHeight: height, maxHeight: height, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: 10).fill(inMonth ? Palette.card : Palette.card.opacity(0.45)))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(selected ? Palette.ink : Palette.line, lineWidth: selected ? 1.5 : 1))
            .opacity(inMonth ? 1 : 0.7)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    @ViewBuilder private func line(_ item: Item, today: Date) -> some View {
        switch item {
        case .event(let e):
            HStack(spacing: 4) {
                RoundedRectangle(cornerRadius: 1).fill(e.tone.color).frame(width: 2.5, height: 10)
                Text(e.allDay ? e.title : "\(Agenda.clock(e.start)) \(e.title)").lineLimit(1)
            }
            .font(Typo.sans(10.5)).foregroundStyle(Palette.ink)
            .padding(.horizontal, 4).frame(maxWidth: .infinity, minHeight: 15, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 4).fill(e.tone.tint))
        case .task(let t):
            let late = !t.completed && (t.due ?? today) < today
            HStack(spacing: 4) {
                Image(systemName: t.completed ? "checkmark.circle.fill" : "circle").font(.system(size: 8.5))
                    .foregroundStyle(t.completed ? Tone.olive.color : late ? Tone.rose.color : Palette.ink3)
                Text(t.title).lineLimit(1).strikethrough(t.completed, color: Palette.ink4)
            }
            .font(Typo.sans(10.5)).foregroundStyle(t.completed ? Palette.ink3 : late ? Tone.rose.color : Palette.ink)
            .padding(.horizontal, 4).frame(maxWidth: .infinity, minHeight: 15, alignment: .leading)
        }
    }
}

/// The picked day: its events, its tasks and an add row due that day.
private struct DayPanel: View {
    var day: Date
    @Environment(AppState.self) private var state
    @ViewState private var newEvent = false

    var body: some View {
        let agenda = state.agenda, v = agenda.view
        let events = v.events(on: day), tasks = v.tasks(on: day)
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(Agenda.relativeDay(day, now: agenda.now)).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Text(Agenda.longDay(day)).font(Typo.serif(22))
            }
            HStack {
                Label11(events.isEmpty ? "没有日程" : "日程 \(events.count)")
                Spacer()
                if agenda.writableCalendar != nil {
                    Button { newEvent = true } label: { Chip(text: "日程", systemImage: "plus") }
                        .buttonStyle(.plain)
                        .popover(isPresented: $newEvent, arrowEdge: .leading) {
                            EventEditor(mode: .create(Calendar.hub.date(bySettingHour: 9, minute: 0, second: 0, of: day) ?? day)) { newEvent = false }
                                .environment(state)
                        }
                }
            }
            ForEach(events) { e in
                EventBlock(event: e, caption: e.allDay ? "全天" : "\(Agenda.clock(e.start)) – \(Agenda.clock(e.end))")
                    .fixedSize(horizontal: false, vertical: true)
            }
            Label11(tasks.isEmpty ? "没有任务" : "任务 \(tasks.count)").padding(.top, 4)
            VStack(spacing: 0) {
                ForEach(tasks) { TaskRow(task: $0) }
                AddTaskRow(due: day).overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
            }
            Spacer(minLength: 0)
        }
        .padding(18)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
        .id(day)
    }
}

// MARK: - Details

private struct TaskInspector: View {
    var task: AgendaTask
    @Environment(AppState.self) private var state

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            TaskEditor(task: task, mode: .edit) { state.taskSelection = nil }
                .id(task.id)
                .overlay(alignment: .topTrailing) {
                    Button { state.taskSelection = nil } label: {
                        Image(systemName: "xmark").font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.ink3)
                            .frame(width: 24, height: 24).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain).padding(10).help("关闭详情")
                }
            if task.parentID == nil {
                VStack(alignment: .leading, spacing: 0) {
                    Label11(task.subtasks.isEmpty ? "子任务" : "子任务 \(task.subtasks.filter(\.completed).count)/\(task.subtasks.count)")
                        .padding(.bottom, 4)
                    ForEach(task.subtasks) { TaskRow(task: $0, showList: false) }
                    AddTaskRow(parent: task).overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                }
                .padding(.horizontal, 16).padding(.bottom, 8)
            }
            if task.completedAt != nil || task.link != nil {
            VStack(alignment: .leading, spacing: 6) {
                if let at = task.completedAt { fact("完成于", Agenda.relativeDay(at, now: state.agenda.now) + " " + Agenda.clock(at)) }
                if let link = task.link.flatMap(URL.init(string:)) {
                    Button { NSWorkspace.shared.open(link) } label: {
                        Text("在 Google Tasks 中打开 ↗").font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
            }
        }
        .frame(width: 360)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .clipShape(RoundedRectangle(cornerRadius: Metrics.cardRadius))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
        .shadow(color: Color(hex: "#3C280A").opacity(0.14), radius: 22, y: 10)
    }

    private func fact(_ label: String, _ value: String) -> some View {
        HStack(spacing: 8) {
            Text(label).font(Typo.sans(12)).foregroundStyle(Palette.ink3).frame(width: 48, alignment: .leading)
            Text(value).font(Typo.sans(12)).foregroundStyle(Palette.ink2)
        }
    }
}

// MARK: - Sidebar

/// The task page's second-level menu: smart views, then 所有任务 with every list beneath it.
struct TaskNav: View {
    @Environment(AppState.self) private var state
    @AppStorage("taskNavListsOpen") private var listsOpen = true
    /// Mirrors the stored flag; toggling stored defaults directly skips the transition.
    @ViewState private var open = true
    @ViewState private var creating = false

    var body: some View {
        let agenda = state.agenda, v = agenda.view
        VStack(spacing: 1) {
            if !v.overdue.isEmpty || state.taskScope == .overdue {
                row(.overdue, count: v.overdue.count, alert: true)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
            row(.today, count: v.today.filter { !$0.completed }.count)
            row(.upcoming, count: (v.upcoming + v.later).count)
            row(.calendar)
            row(.completed)
            row(.all, count: v.allTasks.filter { !$0.completed }.count) {
                Button { open.toggle() } label: {
                    Image(systemName: "chevron.right").font(.system(size: 9, weight: .bold)).foregroundStyle(Palette.ink3)
                        .rotationEffect(.degrees(open ? 90 : 0)).frame(width: 16, height: 16).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help(open ? "收起清单" : "展开清单")
            }
            if open {
                VStack(spacing: 1) {
                    ForEach(agenda.lists) { list in
                        let pinned = agenda.todayLists.contains { $0.id == list.id }
                        row(.list(list.id), title: list.title, count: v.open(in: list.id).count, indent: 18, pinned: pinned)
                            .contextMenu {
                                Button(pinned ? "不在「今天」显示" : "在「今天」显示") { agenda.showInToday(list.id, !pinned) }
                            }
                    }
                    Button { creating = true } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "plus").font(.system(size: 10, weight: .semibold)).frame(width: 16)
                            Text("新建清单").font(Typo.sans(12))
                            Spacer()
                        }
                        .foregroundStyle(Palette.ink3).padding(.leading, 46).frame(height: 26).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .popover(isPresented: $creating, arrowEdge: .trailing) {
                        NameField(title: "新建清单", initial: "") { name in
                            if let name { state.taskScope = .list(agenda.createList(name)) }
                            creating = false
                        }
                    }
                }
                .transition(.asymmetric(insertion: .opacity.combined(with: .offset(y: -8)), removal: .opacity.combined(with: .offset(y: -4))))
            }
        }
        .padding(.top, 2).padding(.bottom, 6)
        .clipped()
        .animation(Motion.spring, value: open)
        .animation(Motion.spring, value: v.overdue.isEmpty)
        .onAppear { open = listsOpen }
        .onChange(of: open) { listsOpen = open }
    }

    private func row(_ scope: TaskScope, title: String? = nil, count: Int? = nil, indent: CGFloat = 0,
                     alert: Bool = false, pinned: Bool = false) -> some View {
        row(scope, title: title, count: count, indent: indent, alert: alert, pinned: pinned) { EmptyView() }
    }

    private func row<Accessory: View>(_ scope: TaskScope, title: String? = nil, count: Int? = nil, indent: CGFloat = 0,
                                      alert: Bool = false, pinned: Bool = false, @ViewBuilder accessory: () -> Accessory) -> some View {
        let on = state.taskScope == scope
        return HStack(spacing: 8) {
            Button { withAnimation(Motion.spring) { state.taskScope = scope } } label: {
                HStack(spacing: 8) {
                    Image(systemName: scope.symbol).font(.system(size: 11)).frame(width: 16)
                        .foregroundStyle(on ? Tone.clay.color : Palette.ink3)
                    Text(title ?? scope.title).font(Typo.sans(12.5, on ? .semibold : .regular)).lineLimit(1)
                    if pinned { Image(systemName: "pin.fill").font(.system(size: 8)).foregroundStyle(Palette.ink4) }
                    Spacer(minLength: 4)
                    if let count, count > 0 {
                        Text("\(count)").font(Typo.sans(11, alert ? .semibold : .regular)).monospacedDigit()
                            .foregroundStyle(alert ? Tone.rose.color : Palette.ink3)
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            accessory()
        }
        .foregroundStyle(on ? Palette.ink : Palette.ink2)
        .padding(.leading, 28 + indent).padding(.trailing, 10).frame(height: 28)
        .background { if on { RoundedRectangle(cornerRadius: 8).fill(Palette.card.opacity(0.7)) } }
    }
}
