import AppKit
import Carbon
import SwiftUI

final class GlobalHotkey {
    private let identifier = UInt32.random(in: 1...UInt32.max)
    private var reference: EventHotKeyRef?
    private var handler: EventHandlerRef?
    let callback: () -> Void
    init(callback: @escaping () -> Void) {
        self.callback = callback
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, data in
            guard let data = data else { return OSStatus(eventNotHandledErr) }
            let owner = Unmanaged<GlobalHotkey>.fromOpaque(data).takeUnretainedValue()
            var pressed = EventHotKeyID()
            guard GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), nil,
                                    MemoryLayout<EventHotKeyID>.size, nil, &pressed) == noErr,
                  pressed.signature == 0x50444842, pressed.id == owner.identifier else { return OSStatus(eventNotHandledErr) }
            DispatchQueue.main.async { owner.callback() }
            return noErr
        }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), &handler)
    }
    func register(code: UInt32, modifiers: UInt32) -> Bool {
        if let reference = reference { UnregisterEventHotKey(reference) }
        reference = nil
        return RegisterEventHotKey(code, modifiers, EventHotKeyID(signature: 0x50444842, id: identifier), GetApplicationEventTarget(), 0, &reference) == noErr
    }
    // Explicit acceptance entry: exercise the installed Carbon handler without synthesizing system keystrokes.
    func dispatchForAcceptance() -> Bool {
        var event: EventRef?
        guard CreateEvent(nil, OSType(kEventClassKeyboard), UInt32(kEventHotKeyPressed), 0, EventAttributes(kEventAttributeUserEvent), &event) == noErr, let event = event else { return false }
        defer { ReleaseEvent(event) }
        var key = EventHotKeyID(signature: 0x50444842, id: identifier)
        guard SetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID), MemoryLayout<EventHotKeyID>.size, &key) == noErr else { return false }
        return SendEventToEventTarget(event, GetApplicationEventTarget()) == noErr
    }
    deinit { if let reference = reference { UnregisterEventHotKey(reference) }; if let handler = handler { RemoveEventHandler(handler) } }
}
final class QuickWindow: NSPanel {
    var onEscape: (() -> Void)?
    override var canBecomeKey: Bool { true }
    override func cancelOperation(_ sender: Any?) { onEscape?() }
}
struct QuickPanelView: View {
    @ObservedObject var model: HubModel
    let close: () -> Void
    let openMain: () -> Void
    @State private var title = ""
    @State private var list = ""
    @State private var dated = true
    @State private var due = Date()
    @State private var saving = false
    @State private var message: String?
    @FocusState private var focused: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack { Text("日程与任务").font(.title3.bold()); Spacer(); Button(action: openMain) { Image(systemName: "arrow.up.right.square") }.buttonStyle(.plain); Button(action: close) { Image(systemName: "xmark") }.buttonStyle(.plain) }
            if let snapshot = model.quickSnapshot { Text("同步于 \(snapshot.fetchedAt.formatted(date: .abbreviated, time: .shortened))").font(.caption).foregroundStyle(.secondary) }
            if let next = model.quickSnapshot?.events.first(where: { ($0.endDate ?? .distantPast) > Date() }) {
                HStack(spacing: 12) {
                    Image(systemName: "calendar").foregroundStyle(.indigo)
                    VStack(alignment: .leading, spacing: 5) { Text(next.title).lineLimit(1); Text(next.allDay ? "全天" : displayDate(next.start)).font(.caption).foregroundStyle(.secondary) }
                }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(Color.indigo.opacity(0.07), in: RoundedRectangle(cornerRadius: 12))
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    let pending = (model.quickSnapshot?.tasks ?? []).filter { !$0.completed && ($0.due.isEmpty || $0.due <= dayKey(Date())) }.sorted { agendaTaskOrder($0, $1, today: dayKey(Date())) }
                    if pending.isEmpty { Text(model.quickSnapshot == nil ? "连接 Google 后显示任务" : "今天的待办已清空").foregroundStyle(.secondary).padding(.vertical, 18) }
                    ForEach(pending) { task in
                        HStack(spacing: 10) {
                            Button { model.googleOperation { try await model.google.complete(task) } } label: { Image(systemName: "circle") }.buttonStyle(.plain).disabled(model.googleBusy)
                            Text(task.title).lineLimit(2)
                            Spacer()
                            if !task.due.isEmpty && task.due < dayKey(Date()) { Text("逾期").font(.caption).foregroundStyle(.orange) }
                        }
                    }
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            Divider()
            TextField("新增任务…", text: $title).textFieldStyle(.roundedBorder).focused($focused).onSubmit { save() }
            HStack {
                Picker("清单", selection: $list) { ForEach(model.quickSnapshot?.lists ?? []) { Text($0.title).tag($0.id) } }.labelsHidden()
                Toggle("日期", isOn: $dated).toggleStyle(.checkbox)
                if dated { DatePicker("", selection: $due, displayedComponents: .date).labelsHidden().frame(width: 110) }
            }.font(.caption)
            if let text = message ?? model.googleMessage { Text(text).font(.caption).foregroundStyle(.orange).lineLimit(2) }
            HStack {
                Text("Enter 保存 · Esc 收起").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("新增") { save() }.disabled(saving || title.isEmpty || list.isEmpty || model.googleBusy)
            }
        }.padding(24).frame(width: 460, height: 560).background(Color(nsColor: .windowBackgroundColor)).tint(.indigo)
        .onAppear {
            let d = DraftStore.load("quick")
            title = d?["title"] ?? ""; list = d?["list"] ?? model.quickSnapshot?.lists.first?.id ?? ""
            if let dueText = d?["due"] { dated = !dueText.isEmpty; due = dateOnly(dueText) ?? Date() }
            focused = true
        }
        .onChange(of: title) { _ in persist() }
        .onChange(of: list) { _ in persist() }
        .onChange(of: due) { _ in persist() }
        .onChange(of: dated) { _ in persist() }
        .onChange(of: model.quickSnapshot?.lists.count) { _ in if list.isEmpty { list = model.quickSnapshot?.lists.first?.id ?? "" } }
    }
    private func persist() { DraftStore.save("quick", ["title": title, "list": list, "due": dated ? dayKey(due) : ""]) }
    private func save() {
        guard !saving, !title.trimmingCharacters(in: .whitespaces).isEmpty, !list.isEmpty else { return }
        saving = true
        Task {
            do {
                try await model.google.saveTask(nil, list: list, title: title, notes: "", due: dated ? dayKey(due) : "")
                title = ""; DraftStore.remove("quick"); await model.refreshQuickGoogle(); await model.refreshGoogle(); close()
            } catch { message = error.localizedDescription; persist() }
            saving = false
        }
    }
}
struct ShortcutRecorder: NSViewRepresentable {
    var recorded: (UInt32, UInt32, String) -> Void
    func makeNSView(context: Context) -> RecorderView { let v = RecorderView(); v.recorded = recorded; return v }
    func updateNSView(_ view: RecorderView, context: Context) { view.recorded = recorded }
}
final class RecorderView: NSView {
    var recorded: ((UInt32, UInt32, String) -> Void)?
    override var acceptsFirstResponder: Bool { true }
    override func viewDidMoveToWindow() { window?.makeFirstResponder(self) }
    override func keyDown(with event: NSEvent) {
        var modifiers: UInt32 = 0; var label = ""
        if event.modifierFlags.contains(.control) { modifiers |= UInt32(controlKey); label += "⌃" }
        if event.modifierFlags.contains(.option) { modifiers |= UInt32(optionKey); label += "⌥" }
        if event.modifierFlags.contains(.shift) { modifiers |= UInt32(shiftKey); label += "⇧" }
        if event.modifierFlags.contains(.command) { modifiers |= UInt32(cmdKey); label += "⌘" }
        guard modifiers != 0, event.keyCode != 53 else { return }
        label += event.keyCode == 49 ? "Space" : (event.charactersIgnoringModifiers ?? "").uppercased()
        recorded?(UInt32(event.keyCode), modifiers, label)
    }
}
