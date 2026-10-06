import AppKit
import SwiftUI
import Combine

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = HubModel()
    var statusItem: NSStatusItem!
    var window: NSWindow?
    var quick: QuickWindow?
    var previousApp: NSRunningApplication?
    var hotkey: GlobalHotkey?
    var shortcutSubscription: AnyCancellable?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "tray.full", accessibilityDescription: "个人信息归档")
        let menu = NSMenu()
        menu.addItem(withTitle: "打开个人信息归档", action: #selector(showWindow), keyEquivalent: "")
        menu.addItem(withTitle: "刷新来源状态", action: #selector(refresh), keyEquivalent: "")
        menu.addItem(withTitle: "立即同步电脑活动", action: #selector(sync), keyEquivalent: "")
        menu.addItem(NSMenuItem.separator())
        menu.addItem(withTitle: "退出客户端", action: #selector(quit), keyEquivalent: "q")
        for item in menu.items { item.target = self }
        statusItem.menu = menu
        let taskItem = NSMenuItem(title: "新增任务", action: #selector(newTask), keyEquivalent: "n")
        taskItem.target = self; menu.insertItem(taskItem, at: 1)
        let eventItem = NSMenuItem(title: "新增日程", action: #selector(newEvent), keyEquivalent: "N")
        eventItem.keyEquivalentModifierMask = [.command]; eventItem.target = self; menu.insertItem(eventItem, at: 2)
        let searchItem = NSMenuItem(title: "搜索", action: #selector(search), keyEquivalent: "f")
        searchItem.target = self; menu.insertItem(searchItem, at: 3)
        for i in 1...3 {
            let item = NSMenuItem(title: ["今日概览", "数据趋势", "最近动态"][i-1], action: #selector(switchOverview(_:)), keyEquivalent: String(i))
            item.tag = i; item.target = self; menu.insertItem(item, at: 3+i)
        }
        let mainMenu = NSMenu()
        let appMenuItem = NSMenuItem(title: "Personal Hub", action: nil, keyEquivalent: "")
        let appMenu = NSMenu()
        for item in menu.items { if let copy = item.copy() as? NSMenuItem { appMenu.addItem(copy) } }
        appMenuItem.submenu = appMenu; mainMenu.addItem(appMenuItem); NSApp.mainMenu = mainMenu
        hotkey = GlobalHotkey { [weak self] in self?.toggleQuick() }
        shortcutSubscription = model.$preferences.sink { [weak self] prefs in
            guard let self = self else { return }
            self.model.hotkeyError = self.hotkey?.register(code: prefs.hotkeyCode, modifiers: prefs.hotkeyModifiers) == true ? nil : "快捷键已被占用，请在设置中更换。"
        }
        if !CommandLine.arguments.contains("--ui-smoke") { model.start() }
        if CommandLine.arguments.contains("--show") { showWindow() }
        if CommandLine.arguments.contains("--ui-smoke") {
            Task { await checkWindow() }
        }
        if CommandLine.arguments.contains("--interaction-smoke") { Task { await checkInteractions() } }
    }

    func checkWindow() async {
        showWindow()
        await model.refreshStatus()
        await model.loadDisplay()
        await model.loadTimeline()
        if let sectionIndex = CommandLine.arguments.firstIndex(of: "--qa-section"), CommandLine.arguments.count > sectionIndex+1 {
            let section = CommandLine.arguments[sectionIndex+1]
            if ["trends", "recent"].contains(section) { model.overviewMode = section }
            else { model.section = section; await model.loadDisplay() }
        }
        await model.refreshGoogle()
        await model.loadDisplay()
        await model.loadTimeline()
        if CommandLine.arguments.contains("--qa-week") { model.calendarWeek = true; await model.refreshGoogle() }
        if CommandLine.arguments.contains("--qa-dark") { window?.appearance = NSAppearance(named: .darkAqua) }
        if CommandLine.arguments.contains("--qa-narrow") { window?.setContentSize(NSSize(width: 980, height: 680)) }
        try? await Task.sleep(nanoseconds: 600_000_000)
        guard model.sources.count > 0, model.dashboard != nil, let view = window?.contentView else {
            fputs("client_ui_load_failed\\n", stderr); exit(1)
        }
        var captureView = view
        if let detailIndex = CommandLine.arguments.firstIndex(of: "--qa-detail"), CommandLine.arguments.count > detailIndex+1 {
            let kind = CommandLine.arguments[detailIndex+1]
            let domain = ["people": "social", "bill": "finance", "health_payloads": "health", "recording": "recordings", "computer_summary": "activity", "hermes_execution_report": "reports"][kind] ?? "notes"
            let page: TimelinePage? = try? await model.api.get("api/v1/timeline", query: [URLQueryItem(name: "kind", value: kind), URLQueryItem(name: "domains", value: domain), URLQueryItem(name: "limit", value: "1")])
            if let item = page?.items.first {
                await model.select(item.id)
                let detailView = NSHostingView(rootView: ReadableDetailView(model: model))
                detailView.frame = NSRect(x: 0, y: 0, width: 740, height: 700)
                let detailWindow = NSWindow(contentRect: detailView.frame, styleMask: [.titled], backing: .buffered, defer: false)
                detailWindow.contentView = detailView; detailWindow.orderFront(nil)
                window?.addChildWindow(detailWindow, ordered: .above)
                if CommandLine.arguments.contains("--qa-dark") { detailWindow.appearance = NSAppearance(named: .darkAqua) }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                captureView = detailView
            } else { fputs("client_qa_detail_missing\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--qa-quick") {
            toggleQuick(refresh: false); await model.refreshQuickGoogle()
            try? await Task.sleep(nanoseconds: 400_000_000)
            quick?.appearance = window?.appearance
            guard let panelView = quick?.contentView else { exit(1) }; captureView = panelView
            quick?.cancelOperation(nil)
            guard quick?.isVisible == false else { fputs("quick_escape_failed\\n", stderr); exit(1) }
            toggleQuick(refresh: false)
            try? await Task.sleep(nanoseconds: 400_000_000)
        }
        captureView.layoutSubtreeIfNeeded()
        guard let bitmap = captureView.bitmapImageRepForCachingDisplay(in: captureView.bounds) else {
            fputs("client_ui_render_failed\n", stderr); exit(1)
        }
        captureView.cacheDisplay(in: captureView.bounds, to: bitmap)
        do {
            guard let data = bitmap.representation(using: .png, properties: [:]) else { throw HubError.response }
            let path = Connection.directory.appendingPathComponent("client-qa.png")
            try data.write(to: path, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
            print("client_ui_smoke_ok sources=\(model.sources.count) modules=\(model.dashboard?.modules.count ?? 0) timeline=\(model.timeline.count) window=\(Int(captureView.bounds.width))x\(Int(captureView.bounds.height))")
            exit(0)
        } catch { fputs("client_ui_capture_failed\n", stderr); exit(1) }
    }

    func checkInteractions() async {
        func require(_ passed: Bool, _ name: String) { if !passed { fputs("interaction_failed: \(name)\n", stderr); exit(1) } }
        showWindow()
        let loaded = LocalAgents.inspect().filter { $0.loaded }.map { $0.id }.sorted()
        model.preferences.save()
        let restored = UIPreferences.load()
        require(restored.enabled == model.preferences.enabled && restored.hotkeyCode == model.preferences.hotkeyCode && restored.modules.map { $0.metrics } == model.preferences.modules.map { $0.metrics }, "preferences")
        let conflict = GlobalHotkey {}
        require(!conflict.register(code: restored.hotkeyCode, modifiers: restored.hotkeyModifiers), "hotkey_conflict")
        for (key, modifiers, kind) in [("n", NSEvent.ModifierFlags.command, "task"), ("n", [.command, .shift], "event"), ("1", .command, "today"), ("2", .command, "trends"), ("3", .command, "recent")] {
            let characters = modifiers.contains(.shift) ? key.uppercased() : key
            let event = NSEvent.keyEvent(with: .keyDown, location: .zero, modifierFlags: modifiers, timestamp: 0, windowNumber: window!.windowNumber, context: nil, characters: characters, charactersIgnoringModifiers: characters, isARepeat: false, keyCode: 0)!
            require(NSApp.mainMenu?.performKeyEquivalent(with: event) == true, "menu_\(kind)")
            try? await Task.sleep(nanoseconds: 300_000_000)
            if kind == "task" { require(model.taskEditor, "task_action"); model.taskEditor = false }
            else if kind == "event" { require(model.eventEditor, "event_action"); model.eventEditor = false }
            else { require(model.overviewMode == kind, "mode_\(kind)") }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        var searches = 0
        let observer = NotificationCenter.default.addObserver(forName: .hubSearch, object: nil, queue: .main) { _ in searches += 1 }
        search(); NotificationCenter.default.removeObserver(observer); require(searches == 1, "search")
        var writes = 0
        model.googleOperation { writes += 1; try await Task.sleep(nanoseconds: 100_000_000) }
        model.googleOperation { writes += 1 }
        try? await Task.sleep(nanoseconds: 200_000_000)
        require(writes == 1, "duplicate_submit")
        window?.close()
        require(NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "").count > 0, "resident")
        let finder = NSRunningApplication.runningApplications(withBundleIdentifier: "com.apple.finder").first
        finder?.activate(options: [.activateIgnoringOtherApps])
        try? await Task.sleep(nanoseconds: 300_000_000)
        require(hotkey?.dispatchForAcceptance() == true, "carbon_handler")
        try? await Task.sleep(nanoseconds: 700_000_000)
        print("quick_acceptance_state visible=\(quick?.isVisible ?? false) key=\(quick?.isKeyWindow ?? false) active=\(NSApp.isActive)")
        require(quick?.isVisible == true && quick?.isKeyWindow == true, "quick_window")
        require(quick?.firstResponder is NSTextView, "quick_input_focus")
        quick?.cancelOperation(nil)
        try? await Task.sleep(nanoseconds: 300_000_000)
        require(quick?.isVisible == false, "escape")
        if let finder = finder { require(NSWorkspace.shared.frontmostApplication?.processIdentifier == finder.processIdentifier, "return_to_application") }
        require(LocalAgents.inspect().filter { $0.loaded }.map { $0.id }.sorted() == loaded, "background_agents")
        print("interaction_smoke_ok preferences hotkey_conflict Carbon_handler menu_commands duplicate_submit input_focus Esc_return background_agents")
        exit(0)
    }

    @objc func showWindow() {
        if window == nil {
            let content = NSHostingView(rootView: ContentView(model: model))
            let value = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                                 styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                 backing: .buffered, defer: false)
            value.title = "Personal Data Hub"
            value.contentView = content
            value.isReleasedWhenClosed = false
            if !CommandLine.arguments.contains("--ui-smoke") && !CommandLine.arguments.contains("--interaction-smoke") { value.setFrameAutosaveName("PersonalDataHubArchive") }
            value.center()
            window = value
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    @objc func newTask() { showWindow(); model.editingTask = nil; model.taskEditor = true }
    @objc func newEvent() { showWindow(); model.editingEvent = nil; model.eventEditor = true }
    @objc func search() { showWindow(); NotificationCenter.default.post(name: .hubSearch, object: nil) }
    @objc func switchOverview(_ item: NSMenuItem) { showWindow(); model.section = "overview"; model.overviewMode = ["today", "trends", "recent"][item.tag-1] }
    func toggleQuick(refresh: Bool = true) {
        if quick?.isVisible == true { closeQuick(); return }
        previousApp = NSWorkspace.shared.frontmostApplication
        if quick == nil {
            let panel = QuickWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 560), styleMask: [.titled, .fullSizeContentView], backing: .buffered, defer: false)
            panel.titleVisibility = .hidden; panel.titlebarAppearsTransparent = true
            panel.hidesOnDeactivate = false
            panel.isFloatingPanel = true; panel.level = .floating; panel.isReleasedWhenClosed = false
            panel.collectionBehavior = [.moveToActiveSpace, .fullScreenAuxiliary]
            panel.contentView = NSHostingView(rootView: QuickPanelView(model: model, close: { [weak self] in self?.closeQuick() }, openMain: { [weak self] in self?.quick?.orderOut(nil); self?.showWindow() }))
            panel.onEscape = { [weak self] in self?.closeQuick() }; panel.center(); quick = panel
        }
        quick?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        if refresh { Task { await model.refreshQuickGoogle() } }
    }
    func closeQuick() { quick?.orderOut(nil); if previousApp?.processIdentifier != ProcessInfo.processInfo.processIdentifier { previousApp?.activate(options: [.activateIgnoringOtherApps]) } }
    @objc func refresh() { Task { await model.refreshStatus() } }
    @objc func sync() { Task { await model.synchronize() } }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow(); return true
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main
enum Main {
    @MainActor static func main() {
        if CommandLine.arguments.contains("--google-cleanup") {
            Task {
                do { try await GoogleClient(diagnostics: true).cleanupAcceptance(); exit(0) }
                catch { fputs((error.localizedDescription + "\\n"), stderr); exit(1) }
            }
            RunLoop.main.run(); return
        }
        if CommandLine.arguments.contains("--google-smoke") {
            Task {
                do { try await GoogleClient(diagnostics: true).smoke(); print("google_live_smoke_ok tasks=CRUD+completion+subtask+move calendar=CRUD+allDay+recurrence+instance cleanup=ok"); exit(0) }
                catch { fputs(("google_live_smoke_failed: " + error.localizedDescription + "\n"), stderr); exit(1) }
            }
            RunLoop.main.run(); return
        }
        if CommandLine.arguments.contains("--authorize-google") {
            Task {
                do { try await GoogleClient().authorize(); print("google_authorized"); exit(0) }
                catch { fputs(("google_authorization_failed: " + error.localizedDescription + "\n"), stderr); exit(1) }
            }
            RunLoop.main.run(); return
        }
        if CommandLine.arguments.contains("--provision-google") {
            do {
                let data = FileHandle.standardInput.readDataToEndOfFile()
                guard let values = try JSONSerialization.jsonObject(with: data) as? [String: String], values["client_id"] != nil else { throw GoogleError.invalid }
                var config = values
                if let existing = try? JSONSerialization.jsonObject(with: GoogleKeychain.read("oauth")) as? [String: String], existing["client_id"] == values["client_id"], let refresh = existing["refresh_token"] {
                    config["refresh_token"] = refresh
                }
                try GoogleKeychain.write("oauth", JSONSerialization.data(withJSONObject: config))
                print("Google desktop OAuth configuration stored in Keychain"); exit(0)
            } catch { fputs("google_provision_failed\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--provision") {
            // 部署入口从 stdin 收取凭据，避免参数、日志和仓库中出现秘密。
            do {
                let data = FileHandle.standardInput.readDataToEndOfFile()
                guard let values = try JSONSerialization.jsonObject(with: data) as? [String: String],
                      let endpoint = values["endpoint"], let token = values["token"], !token.isEmpty else { throw HubError.credentials }
                try Connection(endpoint: endpoint).save(token: token)
                print("Connection saved; credential stored in Keychain")
                exit(0)
            } catch { fputs("connection_provision_failed\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--smoke") {
            Task {
                do {
                    let api = HubAPI(Connection.load())
                    let sources: [SourceStatus] = try await api.get("api/v1/sources")
                    let page: RecordPage = try await api.get("api/v1/browse", query: [URLQueryItem(name: "limit", value: "3")])
                    let kinds: [KindCount] = try await api.get("api/v1/kinds")
                    if let first = page.records.first { _ = try await api.record(first.id) }
                    let summaries: RecordPage = try await api.get("api/v1/browse", query: [URLQueryItem(name: "source", value: "skysight-summaries"), URLQueryItem(name: "limit", value: "1")])
                    guard let summary = summaries.records.first else { throw HubError.response }
                    let detail = try await api.record(summary.id)
                    guard let asset = detail.assets.first else { throw HubError.response }
                    let file = try await api.download(asset)
                    defer { try? FileManager.default.removeItem(at: file) }
                    try asset.verifyFile(file)
                    let agents = await Task.detached { LocalAgents.inspect() }.value
                    print("client_smoke_ok sources=\(sources.count) records=\(page.total) kinds=\(kinds.count) agents_loaded=\(agents.filter { $0.loaded }.count) asset_sha256=ok")
                    exit(0)
                } catch { fputs("client_smoke_failed: \(error.localizedDescription)\n", stderr); exit(1) }
            }
            RunLoop.main.run()
            return
        }
        if CommandLine.arguments.contains("--sync") {
            do { try LocalAgents.synchronize(); print("sync_requested_existing_agent"); exit(0) }
            catch { fputs("sync_request_failed\n", stderr); exit(1) }
        }
        if let identifier = Bundle.main.bundleIdentifier,
           let existing = NSRunningApplication.runningApplications(withBundleIdentifier: identifier)
            .first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
            existing.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
            exit(0)
        }
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
