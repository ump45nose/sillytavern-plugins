import SwiftUI

struct AgendaSummary: View {
    @ObservedObject var model: HubModel
    let archived: DisplayModule
    private var showEvents: Bool { model.preferences.modules.first(where: { $0.id == "agenda" })?.metrics.contains("events") ?? true }
    private var showTasks: Bool { model.preferences.modules.first(where: { $0.id == "agenda" })?.metrics.contains("tasks") ?? true }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let snapshot = model.googleSnapshot {
                if snapshot.queryDate != dayKey(model.displayDate) { Text("缓存日程日期：\(snapshot.queryDate ?? "未提供")").font(.caption).foregroundStyle(.orange) }
                ViewThatFits(in: .horizontal) {
                    HStack(alignment: .top, spacing: 28) {
                        if showEvents { events(snapshot).frame(minWidth: 280, maxWidth: .infinity) }
                        if showEvents && showTasks { Divider() }
                        if showTasks { tasks(snapshot).frame(minWidth: 280, maxWidth: .infinity) }
                    }
                    VStack(alignment: .leading, spacing: 20) { if showEvents { events(snapshot) }; if showEvents && showTasks { Divider() }; if showTasks { tasks(snapshot) } }
                }
                HStack {
                    Text("同步于 \(snapshot.fetchedAt.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                    Spacer(); Button("查看全部") { model.section = "agenda" }.buttonStyle(.plain).foregroundStyle(.indigo)
                }
            } else {
                HStack(alignment: .top, spacing: 28) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("今日日程").font(.subheadline.weight(.medium))
                        ForEach(archived.items.filter { $0.kind == "calendar_event" }.prefix(4)) { item in
                            Button { model.openCard(item) } label: { Label(item.title, systemImage: "clock").lineLimit(1) }.buttonStyle(.plain)
                        }
                        if archived.items.allSatisfy({ $0.kind != "calendar_event" }) { Text("今天暂无日程").foregroundStyle(.secondary) }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    VStack(alignment: .leading, spacing: 10) {
                        Text("待办任务").font(.subheadline.weight(.medium))
                        ForEach(archived.items.filter { $0.kind == "google_task" }.prefix(5)) { item in
                            Button { model.openCard(item) } label: { Label(item.title, systemImage: "circle").lineLimit(1) }.buttonStyle(.plain)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                Text("正在显示归档内容；连接 Google 后可实时查看与编辑。").font(.caption).foregroundStyle(.secondary)
            }
            if let message = model.googleMessage { Text(message).font(.caption).foregroundStyle(.orange) }
        }
    }
    private func events(_ snapshot: GoogleSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack { Text("今日日程").font(.subheadline.weight(.semibold)); Spacer(); Text("\(snapshot.events.count) 项").font(.caption).foregroundStyle(.secondary) }
            if snapshot.events.isEmpty { Label("今天没有安排", systemImage: "sun.max").foregroundStyle(.secondary).padding(.vertical, 20) }
            ForEach(snapshot.events.prefix(4)) { e in
                Button { model.editingEvent = e; model.eventEditor = true } label: {
                    HStack(alignment: .top, spacing: 12) {
                        Text(e.allDay ? "全天" : (e.startDate?.formatted(date: .omitted, time: .shortened) ?? "—")).font(.caption).monospacedDigit().frame(width: 46, alignment: .leading).foregroundStyle(.secondary)
                        Rectangle().fill(Color.indigo.opacity(0.65)).frame(width: 3, height: 32)
                        VStack(alignment: .leading, spacing: 3) { Text(e.title).lineLimit(1); if !e.location.isEmpty { Text(e.location).font(.caption).foregroundStyle(.secondary).lineLimit(1) } }
                        Spacer()
                    }.contentShape(Rectangle())
                }.buttonStyle(.plain)
            }
        }
    }
    private func tasks(_ snapshot: GoogleSnapshot) -> some View {
        let today = dayKey(model.displayDate)
        let pending = snapshot.tasks.filter { !$0.completed }.sorted { agendaTaskOrder($0, $1, today: today) }
        return VStack(alignment: .leading, spacing: 12) {
            HStack { Text("待办任务").font(.subheadline.weight(.semibold)); Spacer(); Text("\(pending.count) 项").font(.caption).foregroundStyle(.secondary) }
            if pending.isEmpty { Label("待办已清空", systemImage: "checkmark.circle").foregroundStyle(.secondary).padding(.vertical, 20) }
            ForEach(pending.prefix(5)) { task in
                HStack(spacing: 10) {
                    Button { model.googleOperation { try await model.google.complete(task) } } label: { Image(systemName: "circle").foregroundStyle(.secondary) }.buttonStyle(.plain).disabled(model.googleBusy)
                    Button { model.editingTask = task; model.taskEditor = true } label: { Text(task.title).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading) }.buttonStyle(.plain)
                    if !task.due.isEmpty { Text(task.due < today ? "逾期" : task.due == today ? "今天" : String(task.due.suffix(5))).font(.caption).foregroundStyle(task.due < today ? Color.orange : Color.secondary) }
                }
            }
        }
    }
}
struct AgendaView: View {
    @ObservedObject var model: HubModel
    @State private var listID = ""
    @State private var taskFilter = "pending"
    @State private var listEditor = false
    @State private var listTitle = ""
    @State private var editingList: GoogleList?
    @State private var deletingTask: GoogleTask?
    @State private var deletingList: GoogleList?
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            if let message = model.googleMessage { Text(message).font(.callout).foregroundStyle(.orange) }
            if let snapshot = model.googleSnapshot {
                Text("同步于 \(snapshot.fetchedAt.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                if snapshot.queryDate != dayKey(model.displayDate) { Text("缓存日程日期：\(snapshot.queryDate ?? "未提供")").font(.caption).foregroundStyle(.orange) }
                HStack {
                    Picker("日历", selection: $model.calendarWeek) { Text("日视图").tag(false); Text("周视图").tag(true) }.pickerStyle(.segmented).frame(width: 180)
                    Spacer(); Button("新增日程") { model.editingEvent = nil; model.eventEditor = true }
                }.onChange(of: model.calendarWeek) { _ in Task { await model.refreshGoogle() } }
                HubCard(title: model.calendarWeek ? "本周日程" : "今日日程", icon: "calendar") {
                    if snapshot.events.isEmpty { Text("这段时间没有日程").foregroundStyle(.secondary) }
                    if model.calendarWeek {
                        ScrollView(.horizontal) {
                            HStack(alignment: .top, spacing: 10) {
                                ForEach(0..<7, id: \.self) { offset in
                                    let day = Calendar.current.date(byAdding: .day, value: offset, to: Calendar.current.startOfDay(for: model.displayDate))!
                                    let end = Calendar.current.date(byAdding: .day, value: 1, to: day)!
                                    let events = snapshot.events.filter { ($0.startDate ?? .distantFuture) < end && ($0.endDate ?? .distantPast) > day }
                                    VStack(alignment: .leading, spacing: 12) {
                                        Text(day.formatted(.dateTime.weekday(.abbreviated).day())).font(.caption.weight(.semibold))
                                        if events.isEmpty { Text("暂无安排").font(.caption).foregroundStyle(.tertiary) }
                                        ForEach(events) { e in
                                            Button { model.editingEvent = e; model.eventEditor = true } label: {
                                                VStack(alignment: .leading, spacing: 5) {
                                                    Text(e.allDay ? "全天" : e.startDate?.formatted(date: .omitted, time: .shortened) ?? "").font(.caption).foregroundStyle(.secondary)
                                                    Text(e.title).font(.caption.weight(.medium)).lineLimit(3)
                                                }.padding(10).frame(maxWidth: .infinity, alignment: .leading).background(Color.indigo.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
                                            }.buttonStyle(.plain)
                                        }
                                        Spacer(minLength: 0)
                                    }.padding(10).frame(width: 120, alignment: .topLeading).frame(minHeight: 160).background(Color.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 10))
                                }
                            }
                        }
                    }
                    ForEach(model.calendarWeek ? [] : snapshot.events) { e in
                        Button { model.editingEvent = e; model.eventEditor = true } label: {
                            HStack {
                                VStack(alignment: .leading, spacing: 5) {
                                    Text(e.title).font(.headline)
                                    Text(e.allDay ? String(e.start.prefix(10)) + " · 全天" : displayDate(e.start) + " — " + displayDate(e.end)).font(.caption).foregroundStyle(.secondary)
                                    if !e.location.isEmpty { Text(e.location).font(.caption).foregroundStyle(.secondary) }
                                }
                                Spacer()
                                if !e.recurringID.isEmpty || !e.recurrence.isEmpty { Image(systemName: "repeat").foregroundStyle(.secondary) }
                                Image(systemName: "chevron.right").font(.caption).foregroundStyle(.secondary)
                            }.padding(.vertical, 8).contentShape(Rectangle())
                        }.buttonStyle(.plain)
                    }
                }
                HubCard(title: "任务清单", icon: "checklist") {
                    HStack {
                        Picker("清单", selection: $listID) {
                            Text("所有清单").tag("")
                            ForEach(snapshot.lists) { Text($0.title).tag($0.id) }
                        }.frame(width: 220)
                        Picker("", selection: $taskFilter) { Text("待办").tag("pending"); Text("已完成").tag("done"); Text("全部").tag("all") }.pickerStyle(.segmented).frame(width: 220)
                        Spacer()
                        Menu {
                            Button("新增清单") { editingList = nil; listTitle = ""; listEditor = true }
                            if let list = snapshot.lists.first(where: { $0.id == listID }) {
                                Button("重命名清单") { editingList = list; listTitle = list.title; listEditor = true }
                                Button("删除清单…", role: .destructive) { deletingList = list }
                            }
                        } label: { Image(systemName: "ellipsis.circle") }
                        Button("新增任务") { model.editingTask = nil; model.taskEditor = true }
                    }
                    let filtered = snapshot.tasks.filter { (listID.isEmpty || $0.listID == listID) && (taskFilter == "all" || ($0.completed == (taskFilter == "done"))) }
                    ForEach(["逾期", "今天", "未来", "无日期", "已完成"], id: \.self) { group in
                        let members = filtered.filter { taskGroup($0) == group }
                        if !members.isEmpty {
                            Text(group).font(.caption.weight(.semibold)).foregroundStyle(.secondary).padding(.top, 10)
                            ForEach(members) { task in
                                HStack(spacing: 12) {
                                    Button { model.googleOperation { try await model.google.complete(task) } } label: { Image(systemName: task.completed ? "checkmark.circle.fill" : "circle").foregroundStyle(task.completed ? Color.indigo : Color.secondary) }.buttonStyle(.plain).disabled(model.googleBusy)
                                    Button { model.editingTask = task; model.taskEditor = true } label: {
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(task.title).strikethrough(task.completed).lineLimit(2)
                                            if !task.notes.isEmpty { Text(task.notes).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                                        }.frame(maxWidth: .infinity, alignment: .leading)
                                    }.buttonStyle(.plain)
                                    Text(task.due).font(.caption).foregroundStyle(.secondary)
                                    Menu {
                                        Button("编辑") { model.editingTask = task; model.taskEditor = true }
                                        Menu("移动到清单") {
                                            ForEach(snapshot.lists.filter { $0.id != task.listID }) { list in
                                                Button(list.title) { model.googleOperation { try await model.google.move(task, destination: list.id) } }
                                            }
                                        }
                                        Button("移到清单顶部") { model.googleOperation { try await model.google.move(task, parent: task.parent) } }
                                        if let previous = filtered.first(where: { $0.listID == task.listID && $0.parent == task.parent && $0.position > task.position }) {
                                            Button("下移一项") { model.googleOperation { try await model.google.move(task, previous: previous.taskID, parent: task.parent) } }
                                        }
                                        if !task.parent.isEmpty { Button("移为顶级任务") { model.googleOperation { try await model.google.move(task) } } }
                                        Button("在 Google 中查看") { if let url = URL(string: task.link) { NSWorkspace.shared.open(url) } }
                                        Button("删除…", role: .destructive) { deletingTask = task }
                                    } label: { Image(systemName: "ellipsis") }.fixedSize()
                                }.padding(.leading, task.parent.isEmpty ? 0 : 22).padding(.vertical, 5)
                            }
                        }
                    }
                    if filtered.isEmpty { Text("没有符合条件的任务").foregroundStyle(.secondary).padding(.vertical, 20) }
                }
            } else {
                HubCard(title: "连接 Google", icon: "calendar.badge.plus") {
                    Text("连接后即可实时查看日程、管理任务，并使用快捷浮窗。").foregroundStyle(.secondary)
                    Button(model.googleAuthorizing ? "等待浏览器授权…" : "连接 Google") { model.connectGoogle() }.disabled(model.googleBusy)
                }
            }
        }
        .alert("清单名称", isPresented: $listEditor) {
            TextField("名称", text: $listTitle)
            Button("保存") { let list = editingList, title = listTitle; model.googleOperation { try await model.google.saveList(list, title: title) } }
            Button("取消", role: .cancel) {}
        }
        .confirmationDialog("删除任务？", isPresented: Binding(get: { deletingTask != nil }, set: { if !$0 { deletingTask = nil } })) {
            Button("删除任务", role: .destructive) { if let task = deletingTask { model.googleOperation { try await model.google.deleteTask(task) } }; deletingTask = nil }
        }
        .confirmationDialog("删除清单及其中所有任务？", isPresented: Binding(get: { deletingList != nil }, set: { if !$0 { deletingList = nil } })) {
            Button("删除清单", role: .destructive) { if let list = deletingList { model.googleOperation { try await model.google.deleteList(list) } }; deletingList = nil; listID = "" }
        }
    }
    private func taskGroup(_ t: GoogleTask) -> String {
        if t.completed { return "已完成" }
        if t.due.isEmpty { return "无日期" }
        let today = dayKey(model.displayDate)
        return t.due < today ? "逾期" : t.due == today ? "今天" : "未来"
    }
}
struct TaskEditor: View {
    @ObservedObject var model: HubModel
    @Environment(\.dismiss) var dismiss
    @State private var title = ""; @State private var notes = ""; @State private var list = ""
    @State private var parent = ""; @State private var dated = false; @State private var due = Date()
    @State private var saving = false; @State private var saved = false; @State private var message: String?
    @FocusState private var titleFocused: Bool
    private var draftKey: String { "task-" + (model.editingTask?.taskID ?? "new") }
    private var draft: [String: String] { ["title": title, "notes": notes, "list": list, "parent": parent, "due": dated ? dayKey(due) : ""] }
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(model.editingTask == nil ? "新增任务" : "编辑任务").font(.title2.bold())
            TextField("要做什么？", text: $title).textFieldStyle(.roundedBorder).focused($titleFocused)
            Picker("任务清单", selection: $list) { ForEach(model.googleSnapshot?.lists ?? []) { Text($0.title).tag($0.id) } }.disabled(model.editingTask != nil)
            if model.editingTask == nil {
                Picker("父任务", selection: $parent) {
                    Text("顶级任务").tag("")
                    ForEach((model.googleSnapshot?.tasks ?? []).filter { $0.listID == list && $0.parent.isEmpty && !$0.completed }) { Text($0.title).tag($0.taskID) }
                }
            }
            Toggle("安排日期", isOn: $dated)
            if dated { DatePicker("日期", selection: $due, displayedComponents: .date) }
            Text("备注").font(.caption).foregroundStyle(.secondary)
            TextEditor(text: $notes).frame(height: 100).padding(6).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.2)))
            if let message = message { Text(message).font(.caption).foregroundStyle(.orange) }
            if model.googleSnapshot == nil {
                Text("需要连接 Google 才能提交。草稿会保留。").font(.caption).foregroundStyle(.secondary)
                Button(model.googleAuthorizing ? "等待浏览器授权…" : "连接 Google") { model.connectGoogle() }.disabled(model.googleBusy)
            }
            HStack {
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                Spacer()
                if saving { ProgressView().controlSize(.small) }
                Button("保存") { save() }.keyboardShortcut(.defaultAction).disabled(saving || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || list.isEmpty || model.googleBusy)
            }
        }.padding(26).frame(width: 500)
        .onAppear {
            if let task = model.editingTask { title = task.title; notes = task.notes; list = task.listID; dated = !task.due.isEmpty; due = dateOnly(task.due) ?? Date() }
            else if let d = DraftStore.load(draftKey) { title = d["title"] ?? ""; notes = d["notes"] ?? ""; list = d["list"] ?? ""; parent = d["parent"] ?? ""; dated = !(d["due"] ?? "").isEmpty; due = dateOnly(d["due"] ?? "") ?? Date() }
            if list.isEmpty { list = model.googleSnapshot?.lists.first?.id ?? "" }
            titleFocused = true
        }
        .onChange(of: draft) { d in if !saved { DraftStore.save(draftKey, d) } }
        .onChange(of: model.googleSnapshot?.lists.count) { _ in if list.isEmpty { list = model.googleSnapshot?.lists.first?.id ?? "" } }
        .onChange(of: list) { _ in parent = "" }
    }
    private func save() {
        saving = true; DraftStore.save(draftKey, draft)
        Task {
            do {
                try await model.google.saveTask(model.editingTask, list: list, title: title, notes: notes, due: dated ? dayKey(due) : "", parent: parent)
                saved = true; DraftStore.remove(draftKey); await model.refreshGoogle(); dismiss()
            } catch { message = error.localizedDescription }
            saving = false
        }
    }
}
struct EventEditor: View {
    @ObservedObject var model: HubModel
    @Environment(\.dismiss) var dismiss
    @State private var title = ""; @State private var notes = ""; @State private var location = ""; @State private var calendar = ""
    @State private var start = Date(); @State private var end = Date().addingTimeInterval(3600); @State private var allDay = false
    @State private var zone = TimeZone.current.identifier; @State private var recurrence = ""; @State private var series = false
    @State private var actual: GoogleEvent?; @State private var loadingMaster = false; @State private var saving = false; @State private var saved = false; @State private var message: String?
    @State private var deletion = false; @State private var creationID = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
    private var draftKey: String { "event-" + (model.editingEvent?.eventID ?? "new") }
    private var draft: [String: String] { ["title": title, "notes": notes, "location": location, "calendar": calendar, "start": ISO8601DateFormatter().string(from: start), "end": ISO8601DateFormatter().string(from: end), "allDay": String(allDay), "zone": zone, "recurrence": recurrence, "creationID": creationID] }
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(model.editingEvent == nil ? "新增日程" : "编辑日程").font(.title2.bold())
            if model.editingEvent?.hasGuests == true || model.editingEvent?.ordinary == false {
                Text("这项日程需在 Google 日历中管理。").foregroundStyle(.secondary)
                Button("打开 Google 日历") { if let link = model.editingEvent?.link, let url = URL(string: link) { NSWorkspace.shared.open(url) } }
                Button("关闭") { dismiss() }
            } else {
                TextField("日程标题", text: $title).textFieldStyle(.roundedBorder)
                Picker("日历", selection: $calendar) { ForEach(model.googleSnapshot?.calendars ?? []) { Text($0.title).tag($0.id) } }.disabled(model.editingEvent != nil)
                Toggle("全天", isOn: $allDay)
                DatePicker("开始", selection: $start, displayedComponents: allDay ? .date : [.date, .hourAndMinute]).environment(\.timeZone, TimeZone(identifier: zone) ?? .current)
                DatePicker(allDay ? "结束日期（含当天）" : "结束", selection: $end, displayedComponents: allDay ? .date : [.date, .hourAndMinute]).environment(\.timeZone, TimeZone(identifier: zone) ?? .current)
                if !allDay { TextField("时区，例如 Asia/Shanghai", text: $zone).textFieldStyle(.roundedBorder) }
                if let e = model.editingEvent, !e.recurringID.isEmpty {
                    Picker("修改范围", selection: $series) { Text("仅本次").tag(false); Text("整个系列").tag(true) }
                        .onChange(of: series) { enabled in
                            if enabled {
                                loadingMaster = true
                                Task {
                                    do { let master = try await model.google.master(e); if series { populate(master) } }
                                    catch { message = error.localizedDescription }
                                    loadingMaster = false
                                }
                            }
                            else { populate(e) }
                        }
                }
                if model.editingEvent?.recurringID.isEmpty != false || series {
                    Picker("重复", selection: $recurrence) {
                        Text("不重复").tag(""); Text("每天").tag("FREQ=DAILY"); Text("每周").tag("FREQ=WEEKLY"); Text("每月").tag("FREQ=MONTHLY")
                        if !["", "FREQ=DAILY", "FREQ=WEEKLY", "FREQ=MONTHLY"].contains(recurrence) { Text("保留原重复规则").tag(recurrence) }
                    }
                }
                TextField("地点", text: $location).textFieldStyle(.roundedBorder)
                TextEditor(text: $notes).frame(height: 80).padding(6).overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.2)))
                if let message = message { Text(message).font(.caption).foregroundStyle(.orange) }
                HStack {
                    if model.editingEvent != nil { Button("删除…", role: .destructive) { deletion = true }.disabled(saving) }
                    Spacer(); Button("取消") { dismiss() }.keyboardShortcut(.cancelAction)
                    if saving || loadingMaster { ProgressView().controlSize(.small) }
                    Button("保存") { save() }.keyboardShortcut(.defaultAction).disabled(saving || loadingMaster || title.isEmpty || calendar.isEmpty || model.googleBusy)
                }
            }
        }.padding(26).frame(width: 520)
        .onAppear {
            if let e = model.editingEvent { populate(e) }
            else if let d = DraftStore.load(draftKey) {
                title = d["title"] ?? ""; notes = d["notes"] ?? ""; location = d["location"] ?? ""; calendar = d["calendar"] ?? ""
                start = archiveDate(d["start"]) ?? Date(); end = archiveDate(d["end"]) ?? Date().addingTimeInterval(3600)
                allDay = d["allDay"] == "true"; zone = d["zone"] ?? TimeZone.current.identifier; recurrence = d["recurrence"] ?? ""; creationID = d["creationID"] ?? creationID
            }
            if calendar.isEmpty { calendar = model.googleSnapshot?.calendars.first(where: \.primary)?.id ?? model.googleSnapshot?.calendars.first?.id ?? "" }
        }
        .onChange(of: draft) { d in if !saved { DraftStore.save(draftKey, d) } }
        .confirmationDialog(series ? "删除整个重复系列？" : "删除这项日程？", isPresented: $deletion) {
            Button("删除日程", role: .destructive) {
                guard let e = actual else { return }; saving = true
                Task { do { try await model.google.deleteEvent(e, series: series); saved = true; DraftStore.remove(draftKey); await model.refreshGoogle(); dismiss() } catch { message = error.localizedDescription }; saving = false }
            }
        }
    }
    private func populate(_ e: GoogleEvent) {
        actual = e; title = e.title; notes = e.notes; location = e.location; calendar = e.calendarID
        start = e.startDate ?? Date(); end = e.endDate ?? start.addingTimeInterval(3600)
        allDay = e.allDay; if allDay { end = Calendar.current.date(byAdding: .day, value: -1, to: end)! }
        zone = e.zone; recurrence = e.recurrence.first?.replacingOccurrences(of: "RRULE:", with: "") ?? ""
    }
    private func save() {
        saving = true; DraftStore.save(draftKey, draft)
        let ending = allDay ? Calendar.current.date(byAdding: .day, value: 1, to: Calendar.current.startOfDay(for: end))! : end
        Task {
            do {
                try await model.google.saveEvent(actual, calendar: calendar, title: title, notes: notes, location: location, start: start, end: ending, allDay: allDay, zone: zone, recurrence: recurrence, series: series, creationID: creationID)
                saved = true; DraftStore.remove(draftKey); await model.refreshGoogle(); dismiss()
            } catch { message = error.localizedDescription }
            saving = false
        }
    }
}
enum DraftStore {
    static func path(_ key: String) -> URL { Connection.directory.appendingPathComponent("draft-" + key.filter { $0.isLetter || $0.isNumber || $0 == "-" } + ".json") }
    static func load(_ key: String) -> [String: String]? { (try? Data(contentsOf: path(key))).flatMap { try? JSONDecoder().decode([String: String].self, from: $0) } }
    static func save(_ key: String, _ data: [String: String]) {
        try? JSONEncoder().encode(data).write(to: path(key), options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path(key).path)
    }
    static func remove(_ key: String) { try? FileManager.default.removeItem(at: path(key)) }
}

func agendaTaskOrder(_ a: GoogleTask, _ b: GoogleTask, today: String) -> Bool {
    func rank(_ task: GoogleTask) -> Int { task.due == today ? 0 : task.due.isEmpty ? 3 : task.due < today ? 1 : 2 }
    let ar = rank(a), br = rank(b)
    if ar != br { return ar < br }
    if a.due != b.due { return ar == 1 ? a.due > b.due : a.due < b.due }
    return a.title.localizedStandardCompare(b.title) == .orderedAscending
}
