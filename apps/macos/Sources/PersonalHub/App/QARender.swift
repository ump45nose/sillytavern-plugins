#if DEBUG
import AppKit
import HubKit
import SwiftUI

/// `PersonalHub --qa-render DIR [--qa-now 2026-10-20T17:58]` renders the main surfaces to PNGs
/// in never-shown windows and exits: no activation, Dock icon or focus change.
@MainActor
enum QARender {
    static func run(to dir: URL, now: Date?) async {
        let state = AppState.shared
        if let now { state.agenda.clock = { now } }
        state.agenda.start()
        if let now {
            HubFormat.current = { now }
            state.hub.clock = { now }
        }
        if CommandLine.arguments.contains("--qa-cache") {
            await state.hub.previewCache()
        } else {
            state.hub.preview(now: now ?? Date())
        }
        try? await Task.sleep(for: .milliseconds(400))
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)

        func shot(_ name: String, width: CGFloat, height: CGFloat? = nil, _ view: some View) async {
            let host = NSHostingView(rootView: AnyView(view.environment(state)))
            host.sizingOptions = height == nil ? [.intrinsicContentSize] : []
            var size = NSSize(width: width, height: height ?? 800)
            let window = NSWindow(contentRect: NSRect(origin: NSPoint(x: -20_000, y: -20_000), size: size),
                                  styleMask: [.borderless], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.contentView = host
            host.frame = NSRect(origin: .zero, size: size)
            try? await Task.sleep(for: .milliseconds(1400))
            if height == nil {
                // Measure after onAppear has filled in initial state.
                size.height = max(host.fittingSize.height, 40)
                window.setContentSize(size)
                host.frame = NSRect(origin: .zero, size: size)
                try? await Task.sleep(for: .milliseconds(300))
            }
            host.layoutSubtreeIfNeeded()
            guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
            host.cacheDisplay(in: host.bounds, to: rep)
            try? rep.representation(using: .png, properties: [:])?.write(to: dir.appendingPathComponent(name + ".png"))
            window.contentView = nil
            print(dir.appendingPathComponent(name + ".png").path)
        }

        for page in (CommandLine.value(after: "--qa-pages") ?? "home").split(separator: ",") {
            state.go(String(page))
            await shot("page-\(page)", width: 1320, height: 1500, MainView().background(Palette.bg))
        }
        await shot("popover", width: 380, PopoverView())
        await shot("quick-add", width: 640, QuickTaskView(close: {}, resize: {}, openMain: {}, initialText: "明天下午3点 和李雷对齐方案 #工作"))
        await shot("quick-newlist", width: 640, QuickTaskView(close: {}, resize: {}, openMain: {}, initialText: "月底 交房租 #家务"))
        await shot("quick-search", width: 640, QuickTaskView(close: {}, resize: {}, openMain: {}, initialText: "方案", initialMode: 1))
        await shot("quick-today", width: 640, QuickTaskView(close: {}, resize: {}, openMain: {}, initialMode: 2))
        if let task = state.agenda.view.today.first {
            await shot("editor", width: 360, TaskEditor(task: task, mode: .edit) {})
        }
        if let event = state.agenda.view.events.last {
            await shot("event-edit", width: 380, EventEditor(mode: .edit(event)) {})
            var readOnly = event
            readOnly.editable = false
            readOnly.calendarTitle = "节假日"
            await shot("event-readonly", width: 380, EventEditor(mode: .edit(readOnly)) {})
        }
        await shot("event-create", width: 380, EventEditor(mode: .create(AgendaModule.nextSlot(after: state.agenda.now))) {})
        await shot("settings-account", width: 560, height: 440, SettingsView(tab: 2))
        await shot("settings-data", width: 560, height: 440, SettingsView(tab: 3))
        await shot("quick-memo", width: 600, QuickMemoView(close: {}))
        for range in TokenRange.allCases {
            state.tokenRange = range
            await shot("token-\(range.rawValue)", width: 1240, ModuleCard(item: LayoutItem(.token, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        }
        state.tokenRange = .week
    }
}

extension CommandLine {
    static func value(after flag: String) -> String? {
        guard let i = arguments.firstIndex(of: flag), i + 1 < arguments.count else { return nil }
        return arguments[i + 1]
    }
}
#endif
