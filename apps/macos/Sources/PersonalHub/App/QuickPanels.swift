import AppKit
import HubKit
import SwiftUI

/// Borderless panel that takes keyboard focus without activating the app, so the previous app stays frontmost.
final class QuickPanel: NSPanel {
    var onClose: () -> Void = {}

    init(width: CGFloat) {
        super.init(contentRect: NSRect(x: 0, y: 0, width: width, height: 200),
                   styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isFloatingPanel = true
        level = .floating
        hidesOnDeactivate = false
        isMovableByWindowBackground = true
        backgroundColor = .clear
        isOpaque = false
        hasShadow = true
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient]
    }

    override var canBecomeKey: Bool { true }

    override func cancelOperation(_ sender: Any?) { dismiss() }

    override func resignKey() {
        super.resignKey()
        // Editors and menus opened from the panel take key focus without ending the session.
        DispatchQueue.main.async { [weak self] in
            guard let self, !self.isKeyWindow else { return }
            if let key = NSApp.keyWindow, key !== self, key.className.contains("Popover") || key.parent === self { return }
            self.dismiss()
        }
    }

    /// Resizes to the SwiftUI content while keeping the top edge in place.
    func fit() {
        guard let size = contentView?.fittingSize, size != frame.size, size.height > 0 else { return }
        setFrame(NSRect(x: frame.midX - size.width / 2, y: frame.maxY - size.height, width: size.width, height: size.height), display: true)
    }

    func present() {
        guard let screen = NSScreen.main?.visibleFrame else { return }
        let size = contentView?.fittingSize ?? frame.size
        setContentSize(size)
        setFrameOrigin(NSPoint(x: screen.midX - size.width / 2, y: screen.maxY - screen.height * 0.24 - size.height))
        alphaValue = 0
        makeKeyAndOrderFront(nil)
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.18
            animator().alphaValue = 1
        }
    }

    func dismiss() {
        guard isVisible else { return }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.12
            animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            self?.orderOut(nil)
            self?.onClose()
        })
    }
}

enum QuickKind { case task, memo }

/// Quick memo: kept as a local draft until the Memos integration lands.
struct QuickMemoView: View {
    var close: () -> Void
    @Environment(AppState.self) private var state
    @ViewState private var text = ""
    @ViewState private var visibility = 0
    @ViewState private var outcome: Outcome?
    @ViewState private var posting = false
    @FocusState private var focused: Bool

    private enum Outcome: Equatable {
        case posted, drafted(String)
    }

    private var tags: [String] {
        let top = (state.hub.data.memos?.data?.tags ?? []).sorted { ($0.count ?? 0) > ($1.count ?? 0) }.prefix(4).map(\.name)
        return top.isEmpty ? ["日报", "想法"] : Array(top)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(HotKeyCenter.shared.shortcut(for: .quickMemo).display)
                    .font(Typo.sans(10.5, .semibold)).foregroundStyle(Palette.ink3)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(RoundedRectangle(cornerRadius: 5).fill(Palette.sunk))
                Text("快速 Memo").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Spacer()
                Segmented(options: [(0, "私密"), (1, "公开")], selection: $visibility)
                    .scaleEffect(0.9, anchor: .trailing)
            }
            TextField("现在的想法是…", text: $text, axis: .vertical)
                .font(Typo.serif(18))
                .lineLimit(4...8)
                .textFieldStyle(.plain)
                .focused($focused)
                .padding(.top, 14)
                .padding(.bottom, 12)
                .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }

            HStack(spacing: 6) {
                switch outcome {
                case .posted:
                    Chip(text: "已发布到 Memos", tone: .olive, systemImage: "checkmark")
                        .transition(.opacity.combined(with: .offset(y: 4)))
                case .drafted(let why):
                    Chip(text: "\(why) 已存为本地草稿", tone: .ochre, systemImage: "tray.and.arrow.down")
                        .transition(.opacity.combined(with: .offset(y: 4)))
                case nil:
                    if posting {
                        Chip(text: "发布中…", tone: .sky)
                    } else {
                        ForEach(tags, id: \.self) { tag in
                            Button { insert(tag) } label: { Chip(text: "#" + tag, tone: .sky) }.buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(.top, 12)
            .frame(minHeight: 26, alignment: .leading)

            HStack(spacing: 16) {
                Text("⌘↩ 发布到 Memos"); Text("⌘⇧↩ 发布并打开")
                Spacer()
                Text("Esc 关闭")
            }
            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            .padding(.top, 14)
        }
        .padding(.horizontal, 22).padding(.vertical, 18)
        .frame(width: 560)
        .background(RoundedRectangle(cornerRadius: 18).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Palette.line))
        .background {
            Button("") { submit(open: false) }.keyboardShortcut(.return, modifiers: .command).opacity(0)
            Button("") { submit(open: true) }.keyboardShortcut(.return, modifiers: [.command, .shift]).opacity(0)
        }
        .preferredColorScheme(.light)
        .onAppear {
            text = ""
            outcome = nil
            posting = false
            DispatchQueue.main.async { focused = true }
        }
    }

    private func insert(_ tag: String) {
        let token = "#" + tag
        guard !text.contains(token) else { return }
        text += (text.isEmpty || text.hasSuffix(" ") || text.hasSuffix("\n") ? "" : " ") + token + " "
        focused = true
    }

    private func submit(open: Bool) {
        let content = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty, !posting else { return }
        posting = true
        Task {
            do {
                try await state.hub.postMemo(content, visibility: visibility == 0 ? "PRIVATE" : "PUBLIC")
                withAnimation(Motion.spring) { outcome = .posted }
            } catch {
                // Never lose what was typed: keep it locally when hub can't take it.
                QuickDrafts.appendMemo(content)
                let why = (error as? HubModel.WriteError).map { e -> String in
                    if case .demo = e { return "未连接 hub，" }
                    return (e.errorDescription ?? "发布失败") + "，"
                } ?? "发布失败，"
                withAnimation(Motion.spring) { outcome = .drafted(why) }
            }
            posting = false
            try? await Task.sleep(for: .milliseconds(outcome == .posted ? 700 : 1800))
            close()
            if open, outcome == .posted { state.openMainWindow("memos") }
        }
    }
}

/// Quick task: add with natural-language dates and #lists, search every list, or work through today.
struct QuickTaskView: View {
    var close: () -> Void
    var resize: () -> Void
    var openMain: () -> Void
    var initialText = ""
    var initialMode = 0
    @Environment(AppState.self) private var state
    @ViewState private var text = ""
    @ViewState private var mode = 0
    @ViewState private var timeBlock = true
    @ViewState private var added: String?
    @FocusState private var focused: Bool

    var body: some View {
        let agenda = state.agenda
        let entry = QuickEntryParser.parse(text, now: agenda.now)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(HotKeyCenter.shared.shortcut(for: .quickTask).display)
                    .font(Typo.sans(10.5, .semibold)).foregroundStyle(Palette.ink3)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(RoundedRectangle(cornerRadius: 5).fill(Palette.sunk))
                Text("快速任务").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                if agenda.mode == .demo { Chip(text: "示例数据", tone: .ochre) }
                Spacer()
                Segmented(options: [(0, "新增"), (1, "搜索"), (2, "今天")], selection: $mode)
                    .scaleEffect(0.9, anchor: .trailing)
            }
            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(Typo.serif(22))
                .focused($focused)
                .onSubmit { submit(entry, open: false) }
                .onKeyPress(.tab) {
                    withAnimation(Motion.spring) { mode = (mode + 1) % 3 }
                    return .handled
                }
                .padding(.top, 14)
                .padding(.bottom, 12)
                .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }

            Group {
                switch mode {
                case 1: results(text.isEmpty ? [] : agenda.search(text).prefix(8).map { $0 },
                                empty: text.isEmpty ? "输入关键词，搜索全部清单的标题和备注" : "没有找到「\(text)」")
                case 2: results(agenda.view.overdue + agenda.view.today, empty: "今天没有到期的任务")
                default: EmptyView()
                }
            }
            if mode != 1 {
                Group {
                    if let added {
                        Chip(text: added, tone: .olive, systemImage: "checkmark")
                            .transition(.opacity.combined(with: .offset(y: 4)))
                    } else if text.trimmingCharacters(in: .whitespaces).isEmpty {
                        Flow(spacing: 6) {
                            ForEach(["明天下午3点", "下周五", "月底", "后天晚上8点"], id: \.self) { Chip(text: $0, tone: .sky) }
                            Chip(text: "#清单", tone: .olive)
                        }
                    } else {
                        QuickEntryChips(entry: mode == 2 ? today(entry) : entry, timeBlock: timeBlock) { timeBlock.toggle() }
                    }
                }
                .padding(.top, 12)
                .frame(minHeight: 26, alignment: .leading)
            }

            HStack(spacing: 16) {
                if mode == 1 {
                    Text("右键任务可完成、改期或编辑")
                } else {
                    Text("↩ 添加"); Text("⌘↩ 添加并打开"); Text("⌘T 时间块")
                }
                Text("⇥ 切换模式")
                Spacer()
                Text("Esc 关闭")
            }
            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            .padding(.top, 14)
        }
        .padding(.horizontal, 22).padding(.vertical, 18)
        .frame(width: 640)
        .fixedSize(horizontal: false, vertical: true)
        .background(RoundedRectangle(cornerRadius: 18).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Palette.line))
        .background {
            Button("") { submit(entry, open: true) }.keyboardShortcut(.return, modifiers: .command).opacity(0)
            Button("") { timeBlock.toggle() }.keyboardShortcut("t", modifiers: .command).opacity(0)
        }
        .preferredColorScheme(.light)
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { _ in DispatchQueue.main.async(execute: resize) }
        .onAppear {
            text = initialText
            mode = initialMode
            added = nil
            timeBlock = true
            DispatchQueue.main.async { focused = true }
        }
    }

    private var placeholder: String {
        switch mode {
        case 1: "搜索任务…"
        case 2: "加一条今天的任务…"
        default: "明天下午3点 和李雷对齐迁移方案 #工作"
        }
    }

    private func results(_ tasks: [AgendaTask], empty: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(tasks) { TaskRow(task: $0) }
            if tasks.isEmpty {
                Text(empty).font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).padding(.vertical, 10)
            }
        }
        .padding(.top, 6)
        .animation(Motion.spring, value: tasks.map(\.completed))
    }

    /// In 今天 mode an undated entry is due today.
    private func today(_ entry: QuickEntry) -> QuickEntry {
        var e = entry
        if e.due == nil { e.due = Calendar.hub.startOfDay(for: state.agenda.now) }
        return e
    }

    private func submit(_ parsed: QuickEntry, open: Bool) {
        guard mode != 1 else { return }
        let entry = mode == 2 ? today(parsed) : parsed
        guard state.agenda.add(entry, timeBlock: timeBlock) else { return }
        let list = entry.listTag ?? state.agenda.defaultList?.title ?? ""
        let when = entry.due.map { Agenda.relativeDay($0, now: state.agenda.now) + (entry.hasTime ? " " + Agenda.clock($0) : "") }
        withAnimation(Motion.spring) { added = "已添加到「\(list)」" + (when.map { " · " + $0 } ?? "") }
        text = ""
        if open {
            state.focus(.agenda)
            openMain()
            close()
        } else if mode == 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.7, execute: close)
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { withAnimation(Motion.spring) { added = nil } }
        }
    }
}

/// Keeps quick memos locally so nothing typed is lost before the Memos integration exists.
enum QuickDrafts {
    static func appendMemo(_ text: String) {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PersonalHub", isDirectory: true)
        let url = base.appendingPathComponent("drafts-memos.jsonl")
        let line = (try? JSONSerialization.data(withJSONObject: ["at": ISO8601DateFormatter().string(from: Date()), "text": text])) ?? Data()
        do {
            try FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
            let h = try FileHandle(forWritingTo: url)
            defer { try? h.close() }
            try h.seekToEnd()
            try h.write(contentsOf: line + Data("\n".utf8))
        } catch {
            NSLog("Personal Hub: draft save failed: \(error.localizedDescription)")
        }
    }
}
