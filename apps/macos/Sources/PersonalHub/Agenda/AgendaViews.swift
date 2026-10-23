import AppKit
import HubKit
import SwiftUI

extension AgendaEvent {
    /// Google's event colours mapped onto the app palette; uncoloured events follow their calendar.
    var tone: Tone {
        switch colorID {
        case "1", "3": .plum
        case "2": .sage
        case "4": .rose
        case "5": .ochre
        case "6": .kraft
        case "7": .sky
        case "8": .ink
        case "9": .steel
        case "10": .olive
        case "11": .clay
        default: [Tone.sky, .olive, .steel, .plum, .sage, .ochre][calendarIndex % 6]
        }
    }
}

struct EventBlock: View {
    var event: AgendaEvent
    var caption: String
    var compact = false
    @Environment(AppState.self) private var state
    @ViewState private var editing = false

    var body: some View {
        HStack(spacing: 0) {
            RoundedRectangle(cornerRadius: 2).fill(event.tone.color).frame(width: 3)
            VStack(alignment: .leading, spacing: 2) {
                Text(caption).font(Typo.sans(11)).foregroundStyle(Palette.ink2).lineLimit(1)
                HStack(spacing: 4) {
                    Text(compact ? "\(Agenda.clock(event.start)) \(event.title)" : event.title).font(Typo.sans(13, .semibold)).lineLimit(1)
                    if !compact, let location = event.location, !location.isEmpty {
                        Text("· \(location)").font(Typo.sans(11)).foregroundStyle(Palette.ink2).lineLimit(1)
                    }
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            Spacer(minLength: 0)
        }
        .background(RoundedRectangle(cornerRadius: 9).fill(event.tone.tint))
        .clipShape(RoundedRectangle(cornerRadius: 9))
        .contentShape(Rectangle())
        .onTapGesture { editing = true }
        .contextMenu {
            Button(event.editable ? "编辑…" : "查看详情…") { editing = true }
            if let link = event.link.flatMap(URL.init(string:)) {
                Button("在 Google 日历中打开") { NSWorkspace.shared.open(link) }
            }
            if event.editable {
                Divider()
                Button(event.recurring ? "删除这一次" : "删除", role: .destructive) { state.agenda.deleteEvent(event) }
            }
        }
        .popover(isPresented: $editing, arrowEdge: .trailing) {
            EventEditor(mode: .edit(event)) { editing = false }.environment(state)
        }
    }
}

/// Create, edit or (for read-only calendars) inspect an event.
struct EventEditor: View {
    enum Mode {
        case edit(AgendaEvent)
        case create(Date)
    }

    var mode: Mode
    var done: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var title = ""
    @ViewState private var location = ""
    @ViewState private var notes = ""
    @ViewState private var allDay = false
    @ViewState private var start = Date()
    @ViewState private var end = Date()
    @ViewState private var calendarID = ""
    @ViewState private var confirmDelete = false
    @ViewState private var loaded = false
    @FocusState private var focused: Bool

    private var event: AgendaEvent? { if case .edit(let e) = mode { e } else { nil } }
    private var editable: Bool { event?.editable ?? true }

    var body: some View {
        let agenda = state.agenda
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label11(event == nil ? "新建日程" : editable ? "编辑日程" : "日程详情 · 只读")
                Spacer()
                if let name = event?.calendarTitle, !editable { Chip(text: name) }
            }
            Group {
                TextField("标题", text: $title)
                    .textFieldStyle(.plain).font(Typo.serif(17)).focused($focused)
                    .padding(.bottom, 6)
                    .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }
                Toggle("全天", isOn: $allDay).toggleStyle(.hub).font(Typo.sans(12.5))
                HStack(spacing: 6) {
                    DatePicker("", selection: $start, displayedComponents: allDay ? [.date] : [.date, .hourAndMinute])
                        .labelsHidden().datePickerStyle(.field)
                    Text("至").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    DatePicker("", selection: $end, displayedComponents: allDay ? [.date] : [.date, .hourAndMinute])
                        .labelsHidden().datePickerStyle(.field)
                }
                .onChange(of: start) { old, new in
                    // Moving the start keeps the duration, like Google Calendar.
                    if loaded { end = end.addingTimeInterval(new.timeIntervalSince(old)) }
                }
                TextField("地点", text: $location).textFieldStyle(.plain).font(Typo.sans(12.5))
                TextField("备注", text: $notes, axis: .vertical).textFieldStyle(.plain).font(Typo.sans(12.5)).lineLimit(2...5)
            }
            .disabled(!editable)
            if editable, agenda.writableCalendars.count > 1 {
                Picker("日历", selection: $calendarID) {
                    ForEach(agenda.writableCalendars) { Text($0.title).tag($0.id) }
                }
                .font(Typo.sans(12.5))
            }
            if event?.recurring == true, editable {
                Text("重复日程：修改和删除只影响这一次").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            }
            if !valid, editable {
                Text("结束时间要晚于开始时间").font(Typo.sans(11)).foregroundStyle(Tone.rose.color)
            }
            HStack {
                if event != nil, editable {
                    Button(event?.recurring == true ? "删除这一次" : "删除", role: .destructive) { confirmDelete = true }
                }
                Spacer()
                if editable {
                    Button("取消", action: done).keyboardShortcut(.cancelAction)
                    Button(event == nil ? "添加" : "保存", action: save).keyboardShortcut(.defaultAction)
                        .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty || !valid)
                } else {
                    Button("关闭", action: done).keyboardShortcut(.defaultAction)
                }
            }
            .font(Typo.sans(12.5))
        }
        .padding(16)
        .frame(width: 380)
        .background(Palette.card)
        .alert("删除「\(title)」？", isPresented: $confirmDelete) {
            Button("删除", role: .destructive) {
                if let event { agenda.deleteEvent(event) }
                done()
            }
            Button("取消", role: .cancel) {}
        }
        .onAppear(perform: load)
    }

    private var valid: Bool { allDay ? Calendar.hub.startOfDay(for: end) >= Calendar.hub.startOfDay(for: start) : end > start }

    private func load() {
        let cal = Calendar.hub
        switch mode {
        case .edit(let e):
            title = e.title
            location = e.location ?? ""
            notes = e.notes ?? ""
            allDay = e.allDay
            start = e.start
            // All-day ends are exclusive in Google; the editor shows the last day.
            end = e.allDay ? cal.date(byAdding: .day, value: -1, to: e.end) ?? e.end : e.end
            calendarID = e.calendarID
        case .create(let at):
            start = at
            end = at.addingTimeInterval(3600)
            calendarID = state.agenda.writableCalendar?.id ?? ""
        }
        DispatchQueue.main.async {
            loaded = true
            focused = editable
        }
    }

    private func save() {
        let cal = Calendar.hub
        let trimmed = { (s: String) -> String? in
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        let s = allDay ? cal.startOfDay(for: start) : start
        let e = allDay ? cal.date(byAdding: .day, value: 1, to: cal.startOfDay(for: end))! : end
        let draft = EventDraft(title: title.trimmingCharacters(in: .whitespaces), start: s, end: e, allDay: allDay,
                               location: trimmed(location), notes: trimmed(notes))
        if let event {
            state.agenda.updateEvent(event, draft: draft, calendarID: calendarID.isEmpty ? event.calendarID : calendarID)
        } else if !calendarID.isEmpty {
            state.agenda.createEvent(draft, calendarID: calendarID)
        }
        done()
    }
}

// MARK: - Tasks

struct CheckCircle: View {
    var done: Bool
    var size: CGFloat = 16
    @ViewState private var burst = false
    @ViewState private var drawn: CGFloat = 0
    @ViewState private var pop: CGFloat = 1
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Circle().stroke(Tone.olive.color.opacity(burst ? 0 : 0.55), lineWidth: burst ? 0.5 : 3)
                .scaleEffect(burst ? 2.1 : 1)
                .opacity(burst ? 1 : 0)
            Circle().strokeBorder(done ? Tone.olive.color : Palette.ink4, lineWidth: 1.5)
            Circle().fill(Tone.olive.color).scaleEffect(done ? 1 : 0.01)
            CheckMark().trim(from: 0, to: done ? drawn : 0)
                .stroke(.white, style: StrokeStyle(lineWidth: max(1.6, size * 0.13), lineCap: .round, lineJoin: .round))
                .padding(size * 0.27)
        }
        .frame(width: size, height: size)
        .scaleEffect(pop)
        .contentShape(Rectangle())
        .onAppear { drawn = done ? 1 : 0 }
        .onChange(of: done) { _, now in
            guard now else { drawn = 0; return }
            guard !reduceMotion else { drawn = 1; return }
            burst = false
            withAnimation(.easeOut(duration: 0.22).delay(0.06)) { drawn = 1 }
            withAnimation(.spring(response: 0.18, dampingFraction: 0.45)) { pop = 1.28 }
            withAnimation(.spring(response: 0.32, dampingFraction: 0.5).delay(0.14)) { pop = 1 }
            withAnimation(.easeOut(duration: 0.5)) { burst = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.55) { burst = false }
        }
    }
}

private struct CheckMark: Shape {
    func path(in r: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: r.minX, y: r.midY + r.height * 0.02))
        p.addLine(to: CGPoint(x: r.minX + r.width * 0.36, y: r.maxY - r.height * 0.08))
        p.addLine(to: CGPoint(x: r.maxX, y: r.minY + r.height * 0.1))
        return p
    }
}

struct TaskRow: View {
    var task: AgendaTask
    var showList = true
    var showDue = true
    var depth = 0
    /// Set on the task page: a click selects the row for the details panel instead of double-click editing.
    var onSelect: ((AgendaTask) -> Void)? = nil
    var selectedID: String? = nil
    @Environment(AppState.self) private var state
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ViewState private var editor: TaskEditor.Mode?
    /// Checked but not yet committed: the row celebrates in place before it re-sorts.
    @ViewState private var finishing = false

    var body: some View {
        VStack(spacing: 0) {
            row
            ForEach(task.subtasks) { TaskRow(task: $0, showList: false, depth: depth + 1, onSelect: onSelect, selectedID: selectedID) }
        }
    }

    private var done: Bool { task.completed || finishing }

    private func toggle() {
        guard !task.completed, !finishing else {
            if !finishing { withAnimation(Motion.spring) { state.agenda.toggle(task) } }
            return
        }
        NSHapticFeedbackManager.defaultPerformer.perform(.levelChange, performanceTime: .now)
        withAnimation(.easeOut(duration: 0.28)) { finishing = true }
        let task = self.task
        DispatchQueue.main.asyncAfter(deadline: .now() + (reduceMotion ? 0.1 : 0.65)) {
            withAnimation(Motion.spring) { state.agenda.toggle(task) }
            finishing = false
        }
    }

    private var row: some View {
        let late = task.overdueDays > 0 && !done
        return HStack(spacing: 10) {
            Button(action: toggle) {
                CheckCircle(done: done, size: depth > 0 ? 14 : 16)
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 1) {
                Text(task.title).font(Typo.sans(depth > 0 ? 12.5 : 13))
                    .foregroundStyle(done ? Palette.ink3 : Palette.ink)
                    .lineLimit(1)
                    .overlay(alignment: .leading) {
                        Rectangle().fill(Palette.ink3).frame(height: 1)
                            .scaleEffect(x: done ? 1 : 0, anchor: .leading)
                            .animation(.easeOut(duration: 0.3).delay(0.08), value: done)
                    }
                if let meta { Text(meta).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
            }
            Spacer(minLength: 4)
            if let label = dueLabel {
                Text(label).font(Typo.sans(11, late ? .semibold : .regular)).monospacedDigit()
                    .foregroundStyle(late ? Tone.rose.color : Palette.ink2)
                    .padding(.horizontal, 7).padding(.vertical, 2)
                    .background(Capsule().fill(late ? Tone.rose.tint : Palette.sunk))
            }
        }
        .padding(.vertical, depth > 0 ? 6 : 8)
        .padding(.leading, CGFloat(depth) * 26)
        .background {
            RoundedRectangle(cornerRadius: 8).fill(Tone.sky.tint)
                .opacity(selectedID == task.id && !finishing ? 1 : 0).padding(.horizontal, -8)
            RoundedRectangle(cornerRadius: 8).fill(Tone.olive.tint)
                .opacity(finishing ? 1 : 0).padding(.horizontal, -6)
                .animation(.easeOut(duration: finishing ? 0.2 : 0.5), value: finishing)
        }
        .overlay(alignment: .top) {
            Rectangle().fill(Palette.line2).frame(height: 1).padding(.leading, CGFloat(depth) * 26)
                .opacity(selectedID == task.id ? 0 : 1)
        }
        .contentShape(Rectangle())
        .gesture(onSelect == nil ? TapGesture(count: 2).onEnded { editor = .edit } : TapGesture().onEnded { onSelect?(task) })
        .contextMenu { TaskMenu(task: task) { editor = $0 } }
        .popover(item: $editor, arrowEdge: .leading) { mode in
            TaskEditor(task: task, mode: mode) { editor = nil }.environment(state)
        }
    }

    private var meta: String? {
        var parts: [String] = []
        if showList, !task.listTitle.isEmpty { parts.append(task.listTitle) }
        if !task.subtasks.isEmpty { parts.append("\(task.subtasks.filter(\.completed).count)/\(task.subtasks.count) 子任务") }
        if let notes = task.notes?.split(separator: "\n").first { parts.append(String(notes)) }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private var dueLabel: String? {
        guard let due = task.due, showDue || (task.overdueDays > 0 && !task.completed) else { return nil }
        if task.overdueDays > 0 && !task.completed {
            let c = Calendar.hub.dateComponents([.month, .day], from: due)
            return "\(c.month!)/\(c.day!)"
        }
        let rel = Agenda.relativeDay(due, now: state.agenda.now)
        return rel == "今天" ? nil : rel
    }
}

struct TaskMenu: View {
    var task: AgendaTask
    var open: (TaskEditor.Mode) -> Void
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda
        Button(task.completed ? "标为未完成" : "完成") { agenda.toggle(task) }
        Menu("改期") {
            ForEach(Self.reschedule(now: agenda.now), id: \.0) { title, day in
                Button(title) { agenda.reschedule(task, to: day) }
            }
            Divider()
            Button("无日期") { agenda.reschedule(task, to: nil) }
        }
        if task.parentID == nil {
            Menu("移到清单") {
                ForEach(agenda.lists) { list in
                    Button(list.title) { agenda.move(task, to: list.id) }.disabled(list.id == task.listID)
                }
            }
        }
        Divider()
        Button("编辑…") { open(.edit) }
        if task.parentID == nil { Button("添加子任务…") { open(.subtask) } }
        if let link = task.link.flatMap(URL.init(string:)) {
            Button("在 Google Tasks 中打开") { NSWorkspace.shared.open(link) }
        }
        Divider()
        Button("删除", role: .destructive) { agenda.delete(task) }
    }

    static func reschedule(now: Date, calendar: Calendar = .hub) -> [(String, Date)] {
        let today = calendar.startOfDay(for: now)
        func day(_ n: Int) -> Date { calendar.date(byAdding: .day, value: n, to: today)! }
        let monday = (9 - calendar.component(.weekday, from: today)) % 7
        return [("今天", day(0)), ("明天", day(1)), ("后天", day(2)), ("下周一", day(monday == 0 ? 7 : monday))]
    }
}

struct TaskEditor: View {
    enum Mode: Identifiable { case edit, subtask; var id: Self { self } }
    var task: AgendaTask
    var mode: Mode
    var done: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var title = ""
    @ViewState private var notes = ""
    @ViewState private var due: Date?
    @ViewState private var listID = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label11(mode == .edit ? "编辑任务" : "子任务 · \(task.title)")
            TextField(mode == .edit ? "标题" : "子任务标题", text: $title)
                .textFieldStyle(.plain).font(Typo.serif(17)).focused($focused)
                .onSubmit(save)
                .padding(.bottom, 6)
                .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }
            if mode == .edit {
                TextField("备注", text: $notes, axis: .vertical).textFieldStyle(.plain)
                    .font(Typo.sans(12.5)).lineLimit(2...5)
                HStack(spacing: 6) {
                    ForEach(TaskMenu.reschedule(now: state.agenda.now).prefix(2), id: \.0) { label, day in
                        dayChip(label, on: due.map { Calendar.hub.isDate($0, inSameDayAs: day) } ?? false) { due = day }
                    }
                    dayChip("无日期", on: due == nil) { due = nil }
                    Spacer(minLength: 4)
                    DatePicker("", selection: Binding(get: { due ?? Calendar.hub.startOfDay(for: state.agenda.now) }, set: { due = $0 }),
                               displayedComponents: .date)
                        .labelsHidden().datePickerStyle(.field).frame(width: 110)
                }
                if task.parentID == nil {
                    Picker("清单", selection: $listID) {
                        ForEach(state.agenda.lists) { Text($0.title).tag($0.id) }
                    }
                    .font(Typo.sans(12.5))
                }
            }
            HStack {
                if mode == .edit {
                    Button("删除", role: .destructive) { state.agenda.delete(task); done() }
                }
                Spacer()
                Button("取消", action: done).keyboardShortcut(.cancelAction)
                Button(mode == .edit ? "保存" : "添加", action: save).keyboardShortcut(.defaultAction)
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .font(Typo.sans(12.5))
        }
        .padding(16)
        .frame(width: 360)
        .background(Palette.card)
        .onAppear {
            if mode == .edit {
                title = task.title
                notes = task.notes ?? ""
                due = task.due
                listID = task.listID
            }
            DispatchQueue.main.async { focused = true }
        }
    }

    private func dayChip(_ label: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) { Chip(text: label, tone: on ? .sky : nil) }.buttonStyle(.plain)
    }

    private func save() {
        let t = title.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        switch mode {
        case .edit: state.agenda.update(task, title: t, notes: notes, due: due.map { Calendar.hub.startOfDay(for: $0) }, listID: listID)
        case .subtask: state.agenda.addSubtask(to: task, title: t)
        }
        done()
    }
}

struct NameField: View {
    var title: String
    var initial: String
    var done: (String?) -> Void
    @ViewState private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label11(title)
            TextField("名称", text: $text).textFieldStyle(.roundedBorder).focused($focused).frame(width: 200)
                .onSubmit(submit)
            HStack {
                Spacer()
                Button("取消") { done(nil) }.keyboardShortcut(.cancelAction)
                Button("好", action: submit).keyboardShortcut(.defaultAction)
            }
        }
        .padding(14)
        .onAppear { text = initial; DispatchQueue.main.async { focused = true } }
    }

    private func submit() {
        let t = text.trimmingCharacters(in: .whitespaces)
        done(t.isEmpty ? nil : t)
    }
}

// MARK: - Quick entry

/// What a quick-entry line will create, shown live under the input.
struct QuickEntryChips: View {
    var entry: QuickEntry
    var timeBlock: Bool
    var toggleTimeBlock: () -> Void
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda
        Flow(spacing: 6) {
            if let due = entry.due {
                Chip(text: Agenda.longDay(due), tone: .sky, systemImage: "calendar")
                if entry.hasTime {
                    Button(action: toggleTimeBlock) {
                        Chip(text: Agenda.clock(due) + (blockable && timeBlock ? " · 同时建时间块" : " · 仅记在备注"),
                             tone: blockable && timeBlock ? .clay : nil, systemImage: "clock")
                    }
                    .buttonStyle(.plain)
                    .disabled(!blockable)
                    .help(blockable ? "⌘T 切换是否在日历里占用一小时" : "没有可写入的日历")
                }
            } else {
                Chip(text: "无日期", systemImage: "calendar")
            }
            if let tag = entry.listTag {
                if let list = agenda.list(named: tag) {
                    Chip(text: "清单：\(list.title)", tone: .olive)
                } else {
                    Chip(text: "新清单：\(tag)", tone: .ochre, systemImage: "plus")
                }
            } else if let list = agenda.defaultList {
                Chip(text: "清单：\(list.title)")
            }
        }
    }

    private var blockable: Bool { state.agenda.writableCalendar != nil }
}

/// A due date picked by hand; overrides whatever date the typed text implies.
struct PickedDue: Equatable {
    var day: Date
    var time: DateComponents?

    func apply(to entry: inout QuickEntry) {
        var due = Calendar.hub.startOfDay(for: day)
        if let time, let at = Calendar.hub.date(bySettingHour: time.hour ?? 9, minute: time.minute ?? 0, second: 0, of: due) { due = at }
        entry.due = due
        entry.hasTime = time != nil
    }
}

/// Calendar button next to a task field: quick days, a month calendar and common times.
struct DuePickerButton: View {
    @Binding var picked: PickedDue?
    var now: Date
    @ViewState private var open = false

    var body: some View {
        Button { open.toggle() } label: {
            HStack(spacing: 4) {
                Image(systemName: picked == nil ? "calendar.badge.clock" : "calendar").font(.system(size: 12.5, weight: .medium))
                if let picked { Text(label(picked)).font(Typo.sans(11.5, .medium)).lineLimit(1) }
            }
            .foregroundStyle(picked == nil ? Palette.ink3 : Tone.sky.color)
            .padding(.horizontal, picked == nil ? 5 : 8).frame(height: 26)
            .background(RoundedRectangle(cornerRadius: 6).fill(picked == nil ? Color.clear : Tone.sky.tint))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("选择日期和时间")
        .popover(isPresented: $open, arrowEdge: .bottom) { DuePickerPanel(picked: $picked, now: now) { open = false } }
    }

    private func label(_ p: PickedDue) -> String {
        Agenda.relativeDay(p.day, now: now) + (p.time.map { String(format: " %02d:%02d", $0.hour ?? 0, $0.minute ?? 0) } ?? "")
    }
}

/// Which list a new task goes to; a typed #list still wins.
struct ListPickerButton: View {
    @Binding var listID: String?
    /// Shown, and used, until something is picked.
    var fallback: TaskListRecord? = nil
    var onToggle: ((Bool) -> Void)? = nil
    @Environment(AppState.self) private var state
    @ViewState private var open = false

    var body: some View {
        let agenda = state.agenda
        let current = listID.flatMap { id in agenda.lists.first { $0.id == id } } ?? fallback ?? agenda.defaultList
        Button { open.toggle() } label: {
            HStack(spacing: 4) {
                Image(systemName: "list.bullet").font(.system(size: 10.5, weight: .semibold))
                Text(current?.title ?? "清单").font(Typo.sans(11.5, .medium)).lineLimit(1)
                Image(systemName: "chevron.down").font(.system(size: 7.5, weight: .bold)).opacity(0.7)
            }
            .foregroundStyle(listID == nil ? Palette.ink3 : Tone.olive.color)
            .padding(.horizontal, 7).frame(height: 24)
            .background(RoundedRectangle(cornerRadius: 6).fill(listID == nil ? Palette.card.opacity(0.001) : Tone.olive.tint))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .fixedSize()
        .help("选择清单；也可以在标题里写 #清单")
        .onChange(of: open) { onToggle?(open) }
        .popover(isPresented: $open, arrowEdge: .bottom) {
            VStack(alignment: .leading, spacing: 1) {
                Label11("添加到清单").padding(.horizontal, 10).padding(.bottom, 4)
                ForEach(agenda.lists) { l in
                    Button {
                        listID = l.id
                        open = false
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "checkmark").font(.system(size: 10, weight: .bold))
                                .opacity(l.id == current?.id ? 1 : 0).foregroundStyle(Tone.olive.color)
                            Text(l.title).font(Typo.sans(12.5)).foregroundStyle(Palette.ink).lineLimit(1)
                            Spacer(minLength: 12)
                            let n = agenda.view.open(in: l.id).count
                            if n > 0 { Text("\(n)").font(Typo.sans(11)).foregroundStyle(Palette.ink4).monospacedDigit() }
                        }
                        .padding(.horizontal, 10).frame(height: 26)
                        .background(RoundedRectangle(cornerRadius: 6).fill(l.id == current?.id ? Palette.sunk : .clear))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.vertical, 10).padding(.horizontal, 4)
            .frame(minWidth: 180)
            .background(Palette.card)
        }
    }

    /// The entry with the picked list applied, unless the text names one.
    static func apply(_ listID: String?, to entry: inout QuickEntry, lists: [TaskListRecord]) {
        guard entry.listTag == nil, let listID, let list = lists.first(where: { $0.id == listID }) else { return }
        entry.listTag = list.title
    }
}

struct DuePickerPanel: View {
    @Binding var picked: PickedDue?
    var now: Date
    var close: () -> Void
    @ViewState private var day = Date()
    @ViewState private var time: DateComponents?

    @ViewState private var month = Date()

    private static let times = [(9, 0), (10, 0), (11, 0), (14, 0), (15, 0), (16, 0), (18, 0), (20, 0)]

    var body: some View {
        let cal = Calendar.hub, today = cal.startOfDay(for: now)
        let quick: [(String, Date)] = [("今天", today), ("明天", cal.date(byAdding: .day, value: 1, to: today)!),
                                       ("后天", cal.date(byAdding: .day, value: 2, to: today)!), ("下周一", nextMonday(today))]
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .firstTextBaseline) {
                Text(summary).font(Typo.serif(22)).foregroundStyle(Palette.ink)
                Spacer()
                Text(Agenda.relativeDay(day, now: now)).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
            HStack(spacing: 6) {
                ForEach(quick, id: \.0) { name, d in
                    choice(name, on: cal.isDate(day, inSameDayAs: d)) { day = d; month = d }
                }
            }
            MonthCalendar(day: $day, month: $month, today: today)
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Label11("时间")
                    Spacer()
                    TimeStepper(time: $time)
                }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 3), spacing: 6) {
                    choice("全天", on: time == nil) { time = nil }
                    ForEach(Self.times, id: \.0) { h, m in
                        choice(String(format: "%02d:%02d", h, m), on: time?.hour == h && time?.minute == m) {
                            time = DateComponents(hour: h, minute: m)
                        }
                    }
                }
            }
            HStack {
                Button("清除") { picked = nil; close() }.buttonStyle(.hubSecondary)
                Spacer()
                Button { picked = PickedDue(day: day, time: time); close() } label: { Text("确定") }
                    .buttonStyle(.hubPrimary).keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(width: 372)
        .background(Palette.card)
        .onAppear {
            day = picked?.day ?? today
            month = day
            time = picked?.time
        }
    }

    private var summary: String {
        let cal = Calendar.hub
        let date = "\(cal.component(.month, from: day))月\(cal.component(.day, from: day))日 周" + MonthCalendar.weekdays[(cal.component(.weekday, from: day) + 5) % 7]
        return date + (time.map { String(format: " · %02d:%02d", $0.hour ?? 0, $0.minute ?? 0) } ?? " · 全天")
    }

    private func choice(_ title: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(Typo.sans(13, on ? .semibold : .regular)).monospacedDigit()
                .foregroundStyle(on ? Tone.sky.color : Palette.ink2)
                .frame(maxWidth: .infinity).frame(height: 32)
                .background(RoundedRectangle(cornerRadius: 8).fill(on ? Tone.sky.tint : Palette.sunk))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(on ? Color.clear : Palette.line2))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func nextMonday(_ today: Date) -> Date {
        let cal = Calendar.hub, weekday = cal.component(.weekday, from: today)
        return cal.date(byAdding: .day, value: (9 - weekday) % 7 == 0 ? 7 : (9 - weekday) % 7, to: today)!
    }
}

/// Monday-first month grid; days before `today` are disabled.
struct MonthCalendar: View {
    @Binding var day: Date
    @Binding var month: Date
    var today: Date

    static let weekdays = ["一", "二", "三", "四", "五", "六", "日"]

    var body: some View {
        let cal = Calendar.hub
        let first = cal.date(from: cal.dateComponents([.year, .month], from: month))!
        let lead = (cal.component(.weekday, from: first) + 5) % 7
        let count = cal.range(of: .day, in: .month, for: first)!.count
        let cells: [Date?] = Array(repeating: nil, count: lead) + (0..<count).map { cal.date(byAdding: .day, value: $0, to: first) }
        VStack(spacing: 6) {
            HStack {
                Text(verbatim: "\(cal.component(.year, from: first)) 年 \(cal.component(.month, from: first)) 月")
                    .font(Typo.sans(14, .semibold)).foregroundStyle(Palette.ink)
                Spacer()
                ForEach([-1, 1], id: \.self) { step in
                    Button { month = cal.date(byAdding: .month, value: step, to: first)! } label: {
                        Image(systemName: step < 0 ? "chevron.left" : "chevron.right")
                            .font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.ink2)
                            .frame(width: 30, height: 28).background(RoundedRectangle(cornerRadius: 7).fill(Palette.sunk))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(step < 0 && first <= cal.date(from: cal.dateComponents([.year, .month], from: today))!)
                }
            }
            .padding(.bottom, 4)
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 4), count: 7), spacing: 4) {
                ForEach(Self.weekdays, id: \.self) { Text($0).font(Typo.sans(11)).foregroundStyle(Palette.ink3).frame(height: 20) }
                ForEach(cells.indices, id: \.self) { i in
                    if let d = cells[i] { cell(d) } else { Color.clear.frame(height: 36) }
                }
            }
        }
    }

    private func cell(_ d: Date) -> some View {
        let cal = Calendar.hub
        let selected = cal.isDate(d, inSameDayAs: day), isToday = cal.isDate(d, inSameDayAs: today), past = d < today
        return Button { day = d } label: {
            Text(verbatim: "\(cal.component(.day, from: d))").font(Typo.sans(13.5, selected || isToday ? .semibold : .regular)).monospacedDigit()
                .foregroundStyle(selected ? Color.white : past ? Palette.ink4 : isToday ? Tone.clay.color : Palette.ink)
                .frame(maxWidth: .infinity).frame(height: 36)
                .background(RoundedRectangle(cornerRadius: 9).fill(selected ? Palette.ink : Color.clear))
                .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(isToday && !selected ? Tone.clay.color.opacity(0.5) : .clear))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(past)
    }
}

/// Hour and five-minute steppers for times the preset chips don't cover.
private struct TimeStepper: View {
    @Binding var time: DateComponents?

    var body: some View {
        let h = time?.hour ?? 9, m = time?.minute ?? 0
        HStack(spacing: 2) {
            steps(60, "小时"); Text(String(format: "%02d", h)).frame(width: 24)
            Text(":").foregroundStyle(Palette.ink3)
            Text(String(format: "%02d", m)).frame(width: 24); steps(5, "分钟")
        }
        .font(Typo.sans(14, .semibold)).monospacedDigit().foregroundStyle(time == nil ? Palette.ink3 : Palette.ink)
        .padding(3).background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.line2))
    }

    private func steps(_ minutes: Int, _ name: String) -> some View {
        HStack(spacing: 0) {
            ForEach([-1, 1], id: \.self) { dir in
                Button { shift(dir * minutes) } label: {
                    Image(systemName: dir < 0 ? "minus" : "plus").font(.system(size: 9, weight: .bold)).foregroundStyle(Palette.ink2)
                        .frame(width: 22, height: 24).contentShape(Rectangle())
                }
                .buttonStyle(.plain).help(name + (dir < 0 ? " −" : " +"))
            }
        }
    }

    private func shift(_ minutes: Int) {
        let total = ((time?.hour ?? 9) * 60 + (time?.minute ?? 0) / 5 * 5 + minutes + 1440) % 1440
        time = DateComponents(hour: total / 60, minute: total % 60)
    }
}

/// Inline add field for the agenda module; the global quick panel has the full version.
struct InlineQuickAdd: View {
    var placeholder = "明天下午3点 和李雷对齐方案 #工作"
    /// Preset target list and day; the pickers and typed text override them.
    var list: TaskListRecord? = nil
    var due: Date? = nil
    var autofocus = false
    @Environment(AppState.self) private var state
    @ViewState private var text = ""
    @ViewState private var timeBlock = true
    @ViewState private var picked: PickedDue?
    @ViewState private var listID: String?
    @FocusState private var focused: Bool

    private var entry: QuickEntry {
        var e = QuickEntryParser.parse(text, now: state.agenda.now)
        picked?.apply(to: &e)
        ListPickerButton.apply(listID ?? list?.id, to: &e, lists: state.agenda.lists)
        if e.due == nil, let due { e.due = Calendar.hub.startOfDay(for: due) }
        return e
    }

    var body: some View {
        let entry = self.entry
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "plus").font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.ink3)
                TextField(placeholder, text: $text).textFieldStyle(.plain).font(Typo.sans(12.5))
                    .focused($focused)
                    .onSubmit {
                        if state.agenda.add(entry, timeBlock: timeBlock) { text = ""; picked = nil }
                    }
                    .onAppear { if autofocus { DispatchQueue.main.async { focused = true } } }
                ListPickerButton(listID: $listID, fallback: list)
                DuePickerButton(picked: $picked, now: state.agenda.now)
                Kbd("↩")
            }
            .padding(.horizontal, 12).frame(height: 34)
            .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.line2))
            if !text.trimmingCharacters(in: .whitespaces).isEmpty || picked != nil {
                QuickEntryChips(entry: entry, timeBlock: timeBlock) { timeBlock.toggle() }
                    .transition(.opacity.combined(with: .offset(y: -3)))
            }
        }
        .animation(Motion.fast, value: text.isEmpty)
        .animation(Motion.fast, value: picked)
    }
}

/// Offline, reconnect and rejected-change notices for the agenda surfaces.
struct SyncNotice: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let agenda = state.agenda
        VStack(alignment: .leading, spacing: 6) {
            switch agenda.status {
            case .offline:
                notice("离线 · \(agenda.pendingCount) 项改动待同步", tone: .ochre, symbol: "wifi.slash")
            case .needsReconnect:
                Button { state.openSettings() } label: {
                    notice("Google 授权已失效，点此重新连接", tone: .rose, symbol: "exclamationmark.triangle")
                }
                .buttonStyle(.plain)
            case .failed(let reason):
                notice("同步失败：\(reason)", tone: .rose, symbol: "exclamationmark.triangle")
            default:
                EmptyView()
            }
            if agenda.mode == .google, agenda.needsReauthorization, agenda.connect != .authorizing {
                Button { agenda.connectGoogle() } label: {
                    notice("重新授权一次，即可读取共享日历并编辑日程", tone: .sky, symbol: "key")
                }
                .buttonStyle(.plain)
            }
            if let failure = agenda.failures.last {
                HStack(spacing: 6) {
                    notice(agenda.failures.count > 1 ? "\(failure.summary)（另有 \(agenda.failures.count - 1) 项）" : failure.summary,
                           tone: .rose, symbol: "arrow.uturn.backward")
                    Button("知道了") { agenda.dismissFailures() }.buttonStyle(.plain)
                        .font(Typo.sans(11.5, .medium)).foregroundStyle(Palette.ink2)
                }
            }
        }
    }

    private func notice(_ text: String, tone: Tone, symbol: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).font(.system(size: 10, weight: .semibold))
            Text(text).lineLimit(2)
        }
        .font(Typo.sans(11.5, .medium)).foregroundStyle(tone.color)
        .padding(.horizontal, 10).padding(.vertical, 5)
        .background(RoundedRectangle(cornerRadius: 8).fill(tone.tint))
    }
}
