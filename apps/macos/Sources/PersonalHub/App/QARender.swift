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

        let only = CommandLine.value(after: "--qa-only")?.split(separator: ",")
        func shot(_ name: String, width: CGFloat, height: CGFloat? = nil, _ view: some View) async {
            if let only, !only.contains(where: { name.hasPrefix($0) }) { return }
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
        let scopes: [(String, TaskScope)] = [("overdue", .overdue), ("today", .today), ("upcoming", .upcoming), ("calendar", .calendar),
                                             ("completed", .completed), ("all", .all), ("list", .list("work"))]
        for (name, scope) in scopes {
            state.go("tasks")
            state.taskScope = scope
            state.taskSelection = name == "list" ? "s7" : nil
            await shot("tasks-\(name)", width: 1320, height: 860, MainView().background(Palette.bg))
        }
        state.taskSelection = nil
        state.go("home")
        for tab in 0..<4 {
            await shot("tray-tasks-\(tab)", width: 380, TrayTasks(tab: tab).padding(16).background(Palette.card))
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
        await shot("settings-general", width: 560, height: 520, SettingsView(tab: 0))
        await shot("settings-account", width: 560, height: 520, SettingsView(tab: 2))
        await shot("settings-data", width: 560, height: 520, SettingsView(tab: 3))
        await shot("settings-ai", width: 560, height: 520, SettingsView(tab: 4))
        state.go("home")
        state.paletteOpen = true
        await shot("palette-empty", width: 1320, height: 860, MainView().background(Palette.bg))
        await shot("palette-search", width: 1320, height: 860, MainView(palette: "周会").background(Palette.bg))
        let clock = state.agenda.now
        state.aiRun.preview("明天下午 3 点和 Lin 对一下方案，帮我加到日程", output: QASample.aiAnswer, agent: .codex, seconds: 14)
        state.aiPending.seed([
            AIPendingChange(createdAt: Date(), agent: "codex-mcp-client", kind: .event(
                title: "和 Lin 对齐方案", start: clock.addingTimeInterval(86_400), end: clock.addingTimeInterval(90_000), location: "线上", notes: nil)),
            AIPendingChange(createdAt: Date(), agent: "codex-mcp-client", kind: .task(
                title: "准备方案对齐的材料", due: GoogleDate.dayString(clock, calendar: .hub), time: nil, notes: nil, list: nil)),
        ])
        await shot("palette-answer", width: 1320, height: 860, MainView(palette: state.aiRun.prompt).background(Palette.bg))
        state.paletteOpen = false
        state.aiRun.reset()
        await shot("ai-pending", width: 460, AIPendingList())
        await shot("quick-memo", width: 600, QuickMemoView(close: {}))
        await shot("git-detail", width: 1240, ModuleCard(item: LayoutItem(.git, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        await shot("git-narrow", width: 680, ModuleCard(item: LayoutItem(.git, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        await shot("net-detail", width: 640, ModuleCard(item: LayoutItem(.net, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        await shot("compact-narrow", width: 760, HStack(alignment: .top, spacing: 14) {
            ForEach([ModuleID.git, .net, .bills], id: \.self) { m in ModuleCard(item: LayoutItem(m, .compact), index: 0, count: 1).frame(width: 230) }
        }.padding(20).background(Palette.bg))
        await shot("plaud-compact", width: 340, ModuleCard(item: LayoutItem(.plaud, .compact), index: 0, count: 1).padding(20).background(Palette.bg))
        await shot("plaud-detail", width: 1100, ModuleCard(item: LayoutItem(.plaud, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        await shot("markdown", width: 560, height: 520, MarkdownEditor(text: .constant(QASample.markdown)).background(Palette.card))
        await shot("subs-compact", width: 340, ModuleCard(item: LayoutItem(.subs, .compact), index: 0, count: 1).padding(20).background(Palette.bg))
        await shot("subs-detail", width: 1100, ModuleCard(item: LayoutItem(.subs, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        if let sub = state.hub.data.subs?.data?.items?.first {
            await shot("subs-edit", width: 1000, SubEditCard(item: sub) {}.padding(20).background(Palette.bg))
        }
        for (id, name) in [("proxy", "subs-edit-link"), ("spare", "subs-edit-nolink")] {
            if let sub = state.hub.data.subs?.data?.items?.first(where: { $0.id == id }) {
                await shot(name, width: 1000, SubEditCard(item: sub) {}.padding(20).background(Palette.bg))
            }
        }
        UserDefaults.standard.set(QASample.memoDraft, forKey: "qa.memos.draft")
        await shot("memo-composer", width: 860, MemoComposer(maxHeight: 420, open: true, draftKey: "qa.memos.draft").padding(20).background(Palette.bg))
        func swatch(_ hex: String) -> NSImage {
            NSImage(size: NSSize(width: 34, height: 34), flipped: false) { r in NSColor(Color(hex: hex)).setFill(); r.fill(); return true }
        }
        let files = MemoUploads([
            .init(filename: "白板照片.jpg", type: "image/jpeg", size: 1_240_000, preview: swatch("#C9B89A"), phase: .done("attachments/a")),
            .init(filename: "任务页草图.pdf", type: "application/pdf", size: 320_000, phase: .uploading),
            .init(filename: "录屏.mov", type: "video/quicktime", size: 90_000_000, phase: .failed("超过 64 MB，没有上传")),
        ])
        await shot("memo-composer-files", width: 860,
                   MemoComposer(maxHeight: 420, open: true, draftKey: "qa.memos.draft", uploads: files).padding(20).background(Palette.bg))
        UserDefaults.standard.removeObject(forKey: "qa.memos.draft")
        await shot("markdown-reveal", width: 560, height: 660, VStack(spacing: 0) {
            ForEach([0, 2, 5], id: \.self) { MarkdownRevealPreview(text: QASample.memoDraft, line: $0).frame(height: 220) }
        }.background(Palette.card))
        await shot("memo-composer-empty", width: 860, MemoComposer(maxHeight: 420, draftKey: "qa.memos.empty").padding(20).background(Palette.bg))
        if let day = state.hub.skyDays.first {
            await shot("sky-month", width: 280, SkyMonth(selected: day) { _ in })
        }
        await shot("due-picker", width: 372, DuePickerPanel(picked: .constant(PickedDue(day: state.agenda.now, time: DateComponents(hour: 15, minute: 0))), now: state.agenda.now) {})
        if let history = state.hub.tokenHistory() {
            if let y = history.years().last.map({ history.year($0) }) {
                await shot("token-hover", width: 1000, VStack(spacing: 30) {
                    HistoryHeatmap(year: y, maxValue: history.maxValue, hovered: (y.weeks.count - 3, 4))
                    HistoryHeatmap(year: y, maxValue: history.maxValue, hovered: (1, 0))
                }.padding(20).background(Palette.card))
            }
            await shot("token-trend", width: 1200, TokenTrend(history: history).frame(height: 168).padding(20).background(Palette.card))
        }
        for range in [TokenRange.day, .week, .month] {
            state.tokenRange = range
            await shot("token-\(range.rawValue)", width: 1240, ModuleCard(item: LayoutItem(.token, .detail), index: 0, count: 1).padding(20).background(Palette.bg))
        }
        state.tokenRange = .week

        for size in [ModuleSize.compact, .detail] {
            await shot("goals-\(size.rawValue)", width: size == .compact ? 340 : 640, ModuleCard(item: LayoutItem(.goals, size), index: 0, count: 1).padding(20).background(Palette.bg))
        }
        state.go("home")
        if let goals = state.page.items.firstIndex(where: { $0.module == .goals }) {
            let before = state.layout
            state.editPage { $0.setHeight(.medium, at: goals) }
            state.editing = true
            await shot("page-heights", width: 1320, height: 1100, MainView().background(Palette.bg))
            state.editing = false
            state.layout = before
        }

        let review = state.review
        state.go("review")
        for target in [ReviewTarget.latest(.daily), .latest(.weekly), .stage] {
            review.open(target)
            await review.reload()
            if case .session(let id) = review.selection { await review.load(id) }
            let name = switch target { case .latest(let k): "review-\(k.rawValue)"; default: "review-stage" }
            await shot(name, width: 1320, height: 860, MainView().background(Palette.bg))
            if name == "review-daily" { await shot("review-daily-narrow", width: 1100, height: 760, MainView().background(Palette.bg)) }
        }
        if let finalized = review.lists[.daily]?.first(where: { $0.status == .finalized }) {
            review.open(.session(finalized.id))
            await review.load(finalized.id)
            await shot("review-daily-done", width: 1320, height: 860, MainView().background(Palette.bg))
        }
        if CommandLine.arguments.contains("--qa-cache") { return }
        state.hub.previewClose()
        review.open(.stage)
        await shot("review-stage-close", width: 1320, height: 1500, MainView().background(Palette.bg))
    }
}

enum QASample {
    static let aiAnswer = """
    明天下午 3 点前后你的日程是空的，**15:00–16:00** 可以放这次对齐。

    - 已提议新建日程「和 Lin 对齐方案」，线上
    - 顺手加了一个今天的任务：准备方案对齐的材料

    两项都在下面，**确认后**才会写入 Google 日历和任务。
    """
    static let memoDraft = """
    ## 周三复盘
    今天最大的收获是把任务页的**分类边界**理清了。
    - [x] 逾期单独成类
    - [ ] 菜单任务区渐进展开
    - 参考 [Things 3](https://culturedcode.com/things/) 的列表动画
    #工作 #复盘
    """

    static let markdown = """
    # 第 42 周 · 周报
    ## 本周完成
    - 托盘面板模块化：**今天 / 生活 / 工作** 三页
    - [x] 主窗口卡顿修复，用量页 388ms → 10ms
    - [ ] 网络套餐总量等 hub 接口
    1. 先切健康和账单
    2. 交流延后，见 [迁移方案](https://example.com/plan)
    > 决定：本周只做能验证的部分。
    阶段进度：
    - 目标 [G3]：完成 60%，`hub-api` 布局接口已上线
    ---
    *下周* 重点：复盘进主窗口
    """
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

/// The editor's styling as if the caret sat on `line`, which offscreen windows can't otherwise show.
private struct MarkdownRevealPreview: NSViewRepresentable {
    var text: String
    var line: Int

    func makeNSView(context: Context) -> MarkdownTextView {
        let view = MarkdownTextView(frame: NSRect(x: 0, y: 0, width: 560, height: 220))
        view.size = 14
        view.drawsBackground = false
        view.textContainerInset = NSSize(width: 14, height: 12)
        view.string = text
        let ns = text as NSString
        var start = 0
        for _ in 0..<line { start = NSMaxRange(ns.lineRange(for: NSRange(location: start, length: 0))) }
        MarkdownStyle(size: 14).apply(to: view, reveal: ns.lineRange(for: NSRange(location: start, length: 0)))
        return view
    }

    func updateNSView(_ view: MarkdownTextView, context: Context) {}
}

extension CommandLine {
    static func value(after flag: String) -> String? {
        guard let i = arguments.firstIndex(of: flag), i + 1 < arguments.count else { return nil }
        return arguments[i + 1]
    }
}
#endif
