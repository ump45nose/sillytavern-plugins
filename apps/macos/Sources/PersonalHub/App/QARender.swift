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
        if let id = state.newPage() {
            await shot("page-custom-edit", width: 1320, height: 900, MainView().background(Palette.bg))
            state.editing = false
            await shot("page-custom-empty", width: 1320, height: 900, MainView().background(Palette.bg))
            state.layout.update(id) { $0.add(.memos, size: .detail); $0.add(.subs); $0.add(.net) }
            state.renamePage(id, title: "随手记", subtitle: "Memos、订阅与网络")
            state.movePage(id, to: 1)
            await shot("page-custom", width: 1320, height: 900, MainView().background(Palette.bg))
            if let page = state.layout.page(id) {
                await shot("page-name", width: 280, PageNameField(page: page) { _, _ in }.background(Palette.card))
            }
            state.deletePage(id)
            state.go("home")
        }
        await shot("popover", width: 380, PopoverView())
        await shot("popover-life", width: 380, PopoverView(page: "life"))
        await shot("popover-work", width: 380, PopoverView(page: "work"))
        await shot("popover-edit", width: 380, PopoverView(page: "today", editing: true))
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

        for size in [ModuleSize.compact, .detail] {
            await shot("goals-\(size.rawValue)", width: size == .compact ? 340 : 640, ModuleCard(item: LayoutItem(.goals, size), index: 0, count: 1).padding(20).background(Palette.bg))
        }
        let review = state.review
        for target in [ReviewTarget.latest(.daily), .latest(.weekly), .stage] {
            review.open(target)
            await review.reload()
            if case .session(let id) = review.selection { await review.load(id) }
            let name = switch target { case .latest(let k): "review-\(k.rawValue)"; default: "review-stage" }
            await shot(name, width: 1180, height: 780, ReviewView())
        }
        if let finalized = review.lists[.daily]?.first(where: { $0.status == .finalized }) {
            review.open(.session(finalized.id))
            await review.load(finalized.id)
            await shot("review-daily-done", width: 1180, height: 780, ReviewView())
        }
        if CommandLine.arguments.contains("--qa-cache") { return }
        state.hub.previewClose()
        review.open(.stage)
        await shot("review-stage-close", width: 1180, height: 1500, ReviewView())
    }
}

/// `PersonalHub --qa-bench [--qa-cache]` lays out each module card repeatedly and prints the cost per pass.
@MainActor
enum QABench {
    static func run() async {
        let state = AppState.shared
        state.agenda.start()
        if CommandLine.arguments.contains("--qa-cache") { await state.hub.previewCache() } else { state.hub.preview(now: Date()) }
        try? await Task.sleep(for: .milliseconds(400))

        func measure(_ name: String, width: CGFloat, _ view: some View) async {
            let host = NSHostingView(rootView: AnyView(view.environment(state)))
            let window = NSWindow(contentRect: NSRect(x: -20_000, y: -20_000, width: width, height: 900),
                                  styleMask: [.borderless], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.contentView = host
            let first = ContinuousClock.now
            host.frame = NSRect(x: 0, y: 0, width: width, height: 900)
            host.layoutSubtreeIfNeeded()
            let initial = ContinuousClock.now - first
            try? await Task.sleep(for: .milliseconds(1500))
            let passes = 20
            let start = ContinuousClock.now
            for i in 0..<passes {
                host.frame.size.width = width + CGFloat(i % 2)
                host.layoutSubtreeIfNeeded()
                host.displayIfNeeded()
            }
            let each = (ContinuousClock.now - start) / passes
            print(String(format: "%-28@ first %7.1f ms   relayout %7.2f ms", name as NSString,
                         Double(initial.components.attoseconds) / 1e15 + Double(initial.components.seconds) * 1000,
                         Double(each.components.attoseconds) / 1e15 + Double(each.components.seconds) * 1000))
            window.contentView = nil
        }

        for module in ModuleID.allCases {
            for size in [ModuleSize.compact, .detail] {
                let width: CGFloat = size == .compact ? 300 : 1240
                await measure("\(module.rawValue).\(size.rawValue)", width: width, ModuleCard(item: LayoutItem(module, size), index: 0, count: 1))
            }
        }
        for page in state.layout.pages.map(\.id) {
            state.go(page)
            await measure("page.\(page)", width: 1320, MainView())
        }
        await measure("popover", width: 380, PopoverView())
    }
}

extension CommandLine {
    static func value(after flag: String) -> String? {
        guard let i = arguments.firstIndex(of: flag), i + 1 < arguments.count else { return nil }
        return arguments[i + 1]
    }
}
#endif
