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
        dismiss()
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

struct QuickPanelView: View {
    var kind: QuickKind
    var close: () -> Void
    @ViewState private var text = ""
    @ViewState private var mode = 0
    @ViewState private var submitted = false
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(kind == .task ? HotKeyCenter.shared.shortcut(for: .quickTask).display : HotKeyCenter.shared.shortcut(for: .quickMemo).display)
                    .font(Typo.sans(10.5, .semibold)).foregroundStyle(Palette.ink3)
                    .padding(.horizontal, 6).padding(.vertical, 2)
                    .background(RoundedRectangle(cornerRadius: 5).fill(Palette.sunk))
                Text(kind == .task ? "快速任务" : "快速 Memo").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Spacer()
                Segmented(options: kind == .task ? [(0, "新增"), (1, "搜索"), (2, "今天")] : [(0, "私密"), (1, "公开")], selection: $mode)
                    .scaleEffect(0.9, anchor: .trailing)
            }
            Group {
                if kind == .task {
                    TextField("明天下午3点 和李雷对齐迁移方案 #工作", text: $text)
                        .font(Typo.serif(22))
                        .onSubmit(submit)
                } else {
                    TextField("现在的想法是…", text: $text, axis: .vertical)
                        .font(Typo.serif(18))
                        .lineLimit(4...8)
                }
            }
            .textFieldStyle(.plain)
            .focused($focused)
            .padding(.top, 14)
            .padding(.bottom, 12)
            .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }

            HStack(spacing: 6) {
                if submitted {
                    Chip(text: "已记录到本地草稿（阶段 2 起写入 \(kind == .task ? "Google Tasks" : "Memos")）", tone: .olive, systemImage: "checkmark")
                        .transition(.opacity.combined(with: .offset(y: 4)))
                } else if kind == .task {
                    Chip(text: "自然语言日期在阶段 2 接入", tone: .sky)
                    Chip(text: "#清单", tone: .olive)
                } else {
                    Chip(text: "#日报", tone: .sky)
                    Chip(text: "#想法", tone: .sky)
                }
            }
            .padding(.top, 12)
            .frame(minHeight: 26, alignment: .leading)

            HStack(spacing: 16) {
                if kind == .task {
                    Text("↩ 添加"); Text("⌘↩ 添加并打开"); Text("⇥ 切换模式")
                } else {
                    Text("⌘↩ 发布到 Memos"); Text("⌘⇧↩ 发布并打开")
                }
                Spacer()
                Text("Esc 关闭")
            }
            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            .padding(.top, 14)
        }
        .padding(.horizontal, 22).padding(.vertical, 18)
        .frame(width: kind == .task ? 640 : 560)
        .background(RoundedRectangle(cornerRadius: 18).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(Palette.line))
        .background {
            Button("", action: submit).keyboardShortcut(.return, modifiers: .command).opacity(0)
        }
        .preferredColorScheme(.light)
        .onAppear {
            text = ""
            submitted = false
            DispatchQueue.main.async { focused = true }
        }
    }

    private func submit() {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        QuickDrafts.append(kind: kind, text: text)
        withAnimation(Motion.spring) { submitted = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.7, execute: close)
    }
}

/// Stage 1 keeps quick entries locally so nothing typed is lost before the real integrations exist.
enum QuickDrafts {
    static func append(kind: QuickKind, text: String) {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PersonalHub", isDirectory: true)
        let url = base.appendingPathComponent(kind == .task ? "drafts-tasks.jsonl" : "drafts-memos.jsonl")
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
