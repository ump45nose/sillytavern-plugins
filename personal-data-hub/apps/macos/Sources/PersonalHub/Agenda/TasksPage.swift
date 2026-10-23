import AppKit
import HubKit
import SwiftUI

/// What the task page shows; the sidebar lists the same entries under 任务.
enum TaskScope: Hashable {
    case today, upcoming, calendar, completed, all
    case list(String)

    static let smart: [TaskScope] = [.today, .upcoming, .calendar, .completed]

    var title: String {
        switch self {
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
        HStack(alignment: .top, spacing: 20) {
            VStack(alignment: .leading, spacing: 14) {
                TasksHeader(scope: scope)
                SyncNotice()
                content(scope).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
            if let selected {
                TaskInspector(task: selected)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .padding(.horizontal, 28).padding(.top, 4).padding(.bottom, 24)
        .animation(Motion.spring, value: state.taskSelection)
        .onChange(of: scope) { state.taskSelection = nil }
    }

    /// A list removed elsewhere falls back to the board.
    private var resolved: TaskScope {
        if case .list(let id) = state.taskScope, !state.agenda.lists.contains(where: { $0.id == id }) { return .all }
        return state.taskScope
    }

    @ViewBuilder private func content(_ scope: TaskScope) -> some View {
        switch scope {
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
        case .today:
            let open = v.dueNow.filter { !$0.completed }.count
            return [Agenda.longDay(agenda.now), "\(open) 项到期", v.overdue.isEmpty ? nil : "\(v.overdue.count) 项逾期",
                    v.todayDone > 0 ? "已完成 \(v.todayDone)" : nil].compactMap { $0 }.joined(separator: " · ")
        case .upcoming:
            return "从今天起按日期排列 · \((v.upcoming + v.later).count + v.dueNow.filter { !$0.completed }.count) 项有日期"
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
        switch scope {
        case .today:
            HStack(spacing: 6) {
                Text("今天显示的清单").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                TodayListsMenu()
            }
            .padding(.horizontal, 10).frame(height: 30)
            .background(RoundedRectangle(cornerRadius: 9).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Palette.line))
        case .list(let id):
            HStack(spacing: 8) {
                Segmented(options: [(false, "我的顺序"), (true, "到期日")], selection: $byDue, small: true).fixedSize()
                if let list = state.agenda.lists.first(where: { $0.id == id }) { ListMenu(list: list) }
            }
        case .all:
            ToolButton(symbol: "plus", title: "新建清单") { creating = true }
                .popover(isPresented: $creating) {
                    NameField(title: "新建清单", initial: "") { name in
                        if let name { state.taskScope = .list(state.agenda.createList(name)) }
                        creating = false
                    }
                }
        default:
            EmptyView()
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
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 10) {
            if editing {
                Circle().strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1.5, dash: [2.5, 2])).frame(width: 16, height: 16)
                TextField(parent == nil ? "任务名称，可写「明天下午3点」或 #清单" : "子任务名称", text: $text)
                    .textFieldStyle(.plain).font(Typo.sans(13)).focused($focused)
                    .onSubmit(submit)
                    .onExitCommand { text = ""; editing = false }
                    .onChange(of: focused) { _, on in if !on, text.isEmpty { editing = false } }
                if let hint { Text(hint).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
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
        if e.listTag == nil, let list { e.listTag = list.title }
        return e
    }

    private var hint: String? {
        guard parent == nil, !text.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
        let e = entry
        let day = e.due.map { Agenda.relativeDay($0, now: state.agenda.now) + (e.hasTime ? " " + Agenda.clock($0) : "") }
        return [day, e.listTag ?? state.agenda.defaultList?.title].compactMap { $0 }.joined(separator: " · ")
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
private struct EventPill: View {
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

private struct TodayTasks: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda, v = agenda.view, today = Calendar.hub.startOfDay(for: agenda.now)
        HubScroll {
            VStack(alignment: .leading, spacing: 14) {
                if !v.overdue.isEmpty {
                    TaskSection(title: "逾期", tone: .rose, tasks: v.overdue)
                }
                TaskSection(title: "今天", caption: Agenda.longDay(agenda.now), tasks: v.today, events: v.events(on: today),
                            empty: "今天没有到期的任务", add: AddTaskRow(due: today))
                ForEach(agenda.todayExtras, id: \.list.id) { list, tasks in
                    TaskSection(title: list.title, caption: "清单", tone: .sky, tasks: tasks, showList: false,
                                empty: "清单里没有其他未完成的任务", add: AddTaskRow(list: list)) {
                        Button { agenda.showInToday(list.id, false) } label: {
                            Image(systemName: "pin.slash").font(.system(size: 11)).foregroundStyle(Palette.ink3)
                        }
                        .buttonStyle(.plain).help("不在「今天」显示这个清单")
                    }
                }
                if agenda.todayLists.isEmpty {
                    Text("用右上角的图钉把常用清单固定到「今天」。").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
            }
            .frame(maxWidth: 820, alignment: .leading)
            .padding(.bottom, 12)
        }
        .scrollIndicators(.never)
    }
}

private struct UpcomingTasks: View {
    @Environment(AppState.self) private var state
    private static let horizon = 14

    var body: some View {
        let agenda = state.agenda, v = agenda.view, cal = Calendar.hub
        let today = cal.startOfDay(for: agenda.now)
        let end = cal.date(byAdding: .day, value: Self.horizon, to: today)!
        let days: [(Date, [AgendaTask], [AgendaEvent])] = (0..<Self.horizon).compactMap { i in
            let day = cal.date(byAdding: .day, value: i, to: today)!
            let tasks = i == 0 ? v.dueNow : v.tasks(on: day).filter { !$0.completed }
            let events = v.events(on: day)
            return i < 2 || !tasks.isEmpty || !events.isEmpty ? (day, tasks, events) : nil
        }
        let later = v.later.filter { ($0.due ?? .distantFuture) >= end }
        HubScroll {
            VStack(alignment: .leading, spacing: 14) {
                ForEach(days, id: \.0) { day, tasks, events in
                    TaskSection(title: title(day), caption: Agenda.longDay(day), tasks: tasks, events: events,
                                showDue: false, empty: "没有到期的任务", add: AddTaskRow(due: day))
                }
                if !later.isEmpty {
                    TaskSection(title: "更晚", caption: "两周以后", tasks: later)
                }
            }
            .frame(maxWidth: 820, alignment: .leading)
            .padding(.bottom, 12)
        }
        .scrollIndicators(.never)
    }

    private func title(_ day: Date) -> String {
        let rel = Agenda.relativeDay(day, now: state.agenda.now)
        return rel.contains("/") ? Agenda.weekdayName(day) : rel
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
        HubScroll([.horizontal, .vertical]) {
            HStack(alignment: .top, spacing: 14) {
                ForEach(agenda.lists) { list in
                    TaskSection(title: list.title, tasks: v.open(in: list.id), showList: false, empty: "没有未完成的任务",
                                add: AddTaskRow(list: list), completed: v.completed(in: list.id)) {
                        ListMenu(list: list)
                    }
                    .frame(width: 300)
                }
            }
            .padding(.bottom, 12)
        }
        .scrollIndicators(.never)
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
        .shadow(color: .black.opacity(0.05), radius: 8, y: 2)
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
    @ViewState private var creating = false

    var body: some View {
        let agenda = state.agenda, v = agenda.view
        VStack(spacing: 1) {
            row(.today, count: v.dueNow.filter { !$0.completed }.count, alert: !v.overdue.isEmpty)
            row(.upcoming, count: (v.upcoming + v.later).count)
            row(.calendar)
            row(.completed)
            row(.all, count: v.allTasks.filter { !$0.completed }.count) {
                Button { withAnimation(Motion.spring) { listsOpen.toggle() } } label: {
                    Image(systemName: "chevron.right").font(.system(size: 9, weight: .bold)).foregroundStyle(Palette.ink3)
                        .rotationEffect(.degrees(listsOpen ? 90 : 0)).frame(width: 16, height: 16).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            if listsOpen {
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
        }
        .padding(.top, 2).padding(.bottom, 6)
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
