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
        .onTapGesture(count: 2) { if let link = event.link.flatMap(URL.init(string:)) { NSWorkspace.shared.open(link) } }
        .help(event.link == nil ? "" : "双击在 Google 日历中打开")
    }
}

/// Today's timed events on an hour grid that widens to fit early or late events.
struct DayTimeline: View {
    var events: [AgendaEvent]
    var now: Date
    var height: CGFloat = 440
    private let top: CGFloat = 12

    var body: some View {
        let today = Calendar.hub.startOfDay(for: now)
        let spans = events.map { e in
            (e, max(0, e.start.timeIntervalSince(today) / 3600), min(24, e.end.timeIntervalSince(today) / 3600))
        }
        let nowHour = Agenda.hour(now)
        let h0 = min(8, floor(min(spans.map(\.1).min() ?? 8, nowHour)))
        let h1 = min(24, max(22, ceil(max(spans.map(\.2).max() ?? 22, nowHour + 0.25))))
        let pph = (height - top - 8) / CGFloat(h1 - h0)
        let lanes = Self.lanes(spans.map { ($0.1, $0.2) })
        let ticks = stride(from: Int(h0), through: Int(h1), by: h1 - h0 > 16 ? 3 : 2).map { $0 }

        GeometryReader { geo in
            let width = geo.size.width - 46 - 12
            ZStack(alignment: .topLeading) {
                ForEach(ticks, id: \.self) { h in
                    HStack(spacing: 8) {
                        Text(abs(Double(h) - nowHour) < 0.6 ? "" : String(format: "%02d:00", h))
                            .font(Typo.sans(10)).foregroundStyle(Palette.ink4).monospacedDigit().frame(width: 34, alignment: .trailing)
                        Rectangle().fill(Palette.line2).frame(height: 1)
                    }
                    .offset(y: CGFloat(Double(h) - h0) * pph + top - 6)
                }
                ForEach(Array(spans.enumerated()), id: \.1.0.id) { i, span in
                    let (e, start, end) = span
                    let lane = lanes[i], w = width / CGFloat(lane.count)
                    EventBlock(event: e, caption: "\(Agenda.clock(e.start)) – \(Agenda.clock(e.end))")
                        .frame(width: w - 3, height: max(CGFloat(end - start) * pph - 4, 26), alignment: .top)
                        .offset(x: 46 + CGFloat(lane.index) * w, y: CGFloat(start - h0) * pph + top + 2)
                        .rise(i + 2)
                }
                if nowHour >= h0, nowHour <= h1 {
                    HStack(spacing: 4) {
                        Text(Agenda.clock(now)).font(Typo.sans(10, .semibold)).foregroundStyle(Tone.clay.color).monospacedDigit()
                            .frame(width: 34, alignment: .trailing)
                        Dot(color: Tone.clay.color, pulse: true)
                        Rectangle().fill(Tone.clay.color).frame(height: 1.5)
                    }
                    .offset(y: CGFloat(nowHour - h0) * pph + top - 6)
                }
            }
        }
        .frame(height: height, alignment: .topLeading)
        .overlay {
            if events.isEmpty {
                Text("今天没有日程").font(Typo.serif(15)).foregroundStyle(Palette.ink3)
            }
        }
        .padding(.horizontal, 6)
        .background(RoundedRectangle(cornerRadius: 12).fill(Palette.sunk.opacity(0.7)))
    }

    /// Side-by-side columns for overlapping events: each event's lane and its cluster's lane count.
    static func lanes(_ spans: [(Double, Double)]) -> [(index: Int, count: Int)] {
        var result = [(index: Int, count: Int)](repeating: (0, 1), count: spans.count)
        var cluster: [Int] = [], ends: [Double] = [], clusterEnd = -1.0
        func close() { for i in cluster { result[i].count = ends.count } }
        for (i, s) in spans.enumerated() {
            if s.0 >= clusterEnd { close(); cluster = []; ends = [] }
            if let free = ends.firstIndex(where: { $0 <= s.0 }) { ends[free] = s.1; result[i].index = free } else { ends.append(s.1); result[i].index = ends.count - 1 }
            cluster.append(i)
            clusterEnd = max(clusterEnd, s.1)
        }
        close()
        return result
    }
}

// MARK: - Tasks

struct CheckCircle: View {
    var done: Bool
    var size: CGFloat = 16

    var body: some View {
        ZStack {
            Circle().strokeBorder(done ? Tone.olive.color : Palette.ink4, lineWidth: 1.5)
            Circle().fill(Tone.olive.color).scaleEffect(done ? 1 : 0.01)
            Image(systemName: "checkmark").font(.system(size: size * 0.5, weight: .heavy)).foregroundStyle(.white)
                .scaleEffect(done ? 1 : 0.3).opacity(done ? 1 : 0)
        }
        .frame(width: size, height: size)
        .contentShape(Rectangle())
    }
}

struct TaskRow: View {
    var task: AgendaTask
    var showList = true
    var depth = 0
    @Environment(AppState.self) private var state
    @ViewState private var editor: TaskEditor.Mode?

    var body: some View {
        VStack(spacing: 0) {
            row
            ForEach(task.subtasks) { TaskRow(task: $0, showList: false, depth: depth + 1) }
        }
    }

    private var row: some View {
        let late = task.overdueDays > 0 && !task.completed
        return HStack(spacing: 10) {
            Button { withAnimation(Motion.spring) { state.agenda.toggle(task) } } label: {
                CheckCircle(done: task.completed, size: depth > 0 ? 14 : 16)
            }
            .buttonStyle(.plain)
            VStack(alignment: .leading, spacing: 1) {
                Text(task.title).font(Typo.sans(depth > 0 ? 12.5 : 13))
                    .foregroundStyle(task.completed ? Palette.ink3 : Palette.ink)
                    .strikethrough(task.completed, color: Palette.ink3).lineLimit(1)
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
        .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1).padding(.leading, CGFloat(depth) * 26) }
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { editor = .edit }
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
        guard let due = task.due else { return nil }
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

/// Task list chips: filter, create, rename and delete Google task lists.
struct ListChips: View {
    @Binding var selection: String?
    @Environment(AppState.self) private var state
    @ViewState private var creating = false
    @ViewState private var renaming: String?
    @ViewState private var confirmDelete: TaskListRecord?

    var body: some View {
        Flow(spacing: 6) {
            chip("全部", id: nil)
            ForEach(state.agenda.lists) { list in
                chip(list.title, id: list.id)
                    .contextMenu {
                        Button("重命名…") { renaming = list.id }
                        Button("删除清单…", role: .destructive) { confirmDelete = list }
                    }
                    .popover(isPresented: Binding(get: { renaming == list.id }, set: { if !$0 { renaming = nil } })) {
                        NameField(title: "重命名清单", initial: list.title) { name in
                            if let name, name != list.title { state.agenda.renameList(list.id, to: name) }
                            renaming = nil
                        }
                    }
            }
            Button { creating = true } label: { Chip(text: "清单", systemImage: "plus") }
                .buttonStyle(.plain)
                .popover(isPresented: $creating) {
                    NameField(title: "新建清单", initial: "") { name in
                        if let name { selection = state.agenda.createList(name) }
                        creating = false
                    }
                }
        }
        .alert("删除清单「\(confirmDelete?.title ?? "")」？", isPresented: Binding(get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } })) {
            Button("删除", role: .destructive) {
                if let list = confirmDelete {
                    if selection == list.id { selection = nil }
                    state.agenda.deleteList(list.id)
                }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("清单里的任务也会一起从 Google Tasks 删除。")
        }
    }

    private func chip(_ title: String, id: String?) -> some View {
        Button { withAnimation(Motion.spring) { selection = id } } label: {
            Chip(text: title, tone: selection == id ? .sky : nil)
        }
        .buttonStyle(.plain)
    }
}

private struct NameField: View {
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

/// Inline add field for the agenda module; the global quick panel has the full version.
struct InlineQuickAdd: View {
    var placeholder = "明天下午3点 和李雷对齐方案 #工作"
    @Environment(AppState.self) private var state
    @ViewState private var text = ""
    @ViewState private var timeBlock = true

    var body: some View {
        let entry = QuickEntryParser.parse(text, now: state.agenda.now)
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "plus").font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.ink3)
                TextField(placeholder, text: $text).textFieldStyle(.plain).font(Typo.sans(12.5))
                    .onSubmit {
                        if state.agenda.add(entry, timeBlock: timeBlock) { text = "" }
                    }
                Kbd("↩")
            }
            .padding(.horizontal, 12).frame(height: 34)
            .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.line2))
            if !text.trimmingCharacters(in: .whitespaces).isEmpty {
                QuickEntryChips(entry: entry, timeBlock: timeBlock) { timeBlock.toggle() }
                    .transition(.opacity.combined(with: .offset(y: -3)))
            }
        }
        .animation(Motion.fast, value: text.isEmpty)
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
