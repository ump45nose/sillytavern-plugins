import AppKit
import SwiftUI
import Combine
import Security

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
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
        let appMenuItem = NSMenuItem(title: "个人信息归档", action: nil, keyEquivalent: "")
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于个人信息归档", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        let settingsItem = appMenu.addItem(withTitle: "设置…", action: #selector(showSettings), keyEquivalent: ",")
        settingsItem.target = self
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "隐藏个人信息归档", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = appMenu.addItem(withTitle: "隐藏其他应用", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(withTitle: "显示全部", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        let quitItem = appMenu.addItem(withTitle: "退出个人信息归档", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        appMenuItem.submenu = appMenu; mainMenu.addItem(appMenuItem); NSApp.mainMenu = mainMenu
        let fileMenu = NSMenu(title: "文件")
        for item in menu.items where [#selector(showWindow), #selector(newTask), #selector(newEvent), #selector(search)].contains(item.action) {
            if let copy = item.copy() as? NSMenuItem { fileMenu.addItem(copy) }
        }
        fileMenu.addItem(NSMenuItem.separator())
        fileMenu.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        let viewMenu = NSMenu(title: "显示")
        for item in menu.items where item.action == #selector(switchOverview(_:)) {
            if let copy = item.copy() as? NSMenuItem { viewMenu.addItem(copy) }
        }
        let windowMenu = NSMenu(title: "窗口")
        windowMenu.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "缩放", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(NSMenuItem.separator())
        windowMenu.addItem(withTitle: "所有窗口置于前方", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        for submenu in [fileMenu, editMenu, viewMenu, windowMenu] {
            let item = NSMenuItem(title: submenu.title, action: nil, keyEquivalent: "")
            item.submenu = submenu; mainMenu.addItem(item)
        }
        NSApp.windowsMenu = windowMenu
        hotkey = GlobalHotkey { [weak self] in self?.toggleQuick() }
        shortcutSubscription = model.$preferences.sink { [weak self] prefs in
            guard let self = self else { return }
            self.model.hotkeyError = self.hotkey?.register(code: prefs.hotkeyCode, modifiers: prefs.hotkeyModifiers) == true ? nil : "快捷键已被占用，请在设置中更换。"
        }
        if !CommandLine.arguments.contains("--ui-smoke") { model.start() }
        if !CommandLine.arguments.contains("--ui-smoke") && !CommandLine.arguments.contains("--interaction-smoke") && !CommandLine.arguments.contains("--viewer-only") {
            Task {
                await model.configureCollection()
            }
        }
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
            else { model.section = section; await model.loadCurrentPage() }
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
        NSApp.setActivationPolicy(.regular)
        if window == nil {
            let content = NSHostingView(rootView: ContentView(model: model))
            let value = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 820),
                                 styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                 backing: .buffered, defer: false)
            value.title = "个人信息归档"
            value.contentView = content
            value.delegate = self
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
    @objc func showSettings() { showWindow(); NotificationCenter.default.post(name: .hubSettings, object: nil) }
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
    func windowWillClose(_ notification: Notification) {
        guard let closing = notification.object as? NSWindow, closing === window else { return }
        NSApp.setActivationPolicy(.accessory)
    }
}

@main
enum Main {
    @MainActor static func main() {
        if let index = CommandLine.arguments.firstIndex(of: "--prepare-update"), CommandLine.arguments.count > index + 1,
           let identifier = Bundle.main.bundleIdentifier {
            let destination = URL(fileURLWithPath: CommandLine.arguments[index + 1]).standardizedFileURL
            let clients = NSRunningApplication.runningApplications(withBundleIdentifier: identifier).filter {
                $0.processIdentifier != ProcessInfo.processInfo.processIdentifier && $0.activationPolicy != .prohibited &&
                $0.bundleURL?.standardizedFileURL == destination
            }
            for client in clients where !client.terminate() {
                fputs("client_update_requires_quit\n", stderr); exit(1)
            }
            let deadline = Date().addingTimeInterval(10)
            while clients.contains(where: { !$0.isTerminated }) && Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.1))
            }
            guard clients.allSatisfy(\.isTerminated) else { fputs("client_update_requires_quit\n", stderr); exit(1) }
            print("client_update_ready; collection_processes_preserved"); exit(0)
        }
        for (flag, source, check) in [("--collect-wechat", "wechat", false), ("--collect-activity", "activity", false), ("--collect-network", "network", false),
                                     ("--collection-check-wechat", "wechat", true), ("--collection-check-activity", "activity", true), ("--collection-check-network", "network", true)] {
            if let index = CommandLine.arguments.firstIndex(of: flag) {
                do { exit(try CollectionRuntime.run(source, checkAccess: check, arguments: Array(CommandLine.arguments.dropFirst(index + 1)))) }
                catch { fputs("collection_runtime_unavailable\n", stderr); exit(1) }
            }
        }
        if CommandLine.arguments.contains("--install-network") {
            do { try LocalAgents.configureNetwork(enabled: true); exit(0) }
            catch { fputs("network_install_failed\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--install-agents") || CommandLine.arguments.contains("--agent-bundle-status") {
            do { try LocalAgents.installBundled(statusOnly: CommandLine.arguments.contains("--agent-bundle-status")); exit(0) }
            catch CollectionFailure.authorizationRequired { fputs("collection_authorization_required\n", stderr); exit(2) }
            catch { fputs("bundled_agents_failed\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--enable-login") || CommandLine.arguments.contains("--disable-login") || CommandLine.arguments.contains("--login-status") {
            do {
                if !CommandLine.arguments.contains("--login-status") {
                    try LoginItem.setEnabled(CommandLine.arguments.contains("--enable-login"))
                }
                let value = LoginItem.status
                print("{\"loginItem\":\"\(value)\"}")
                exit(value == "requiresApproval" ? 2 : 0)
            } catch { fputs("login_item_update_failed\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--keychain-roundtrip-smoke") {
            SecKeychainSetUserInteractionAllowed(false)
            do {
                // Write the exact original bytes; never export or rotate live credentials.
                let viewer = try CredentialStore.read("viewer"), google = try CredentialStore.read("google")
                try CredentialStore.write("viewer", viewer); try CredentialStore.write("google", google)
                guard try CredentialStore.read("viewer") == viewer, try CredentialStore.read("google") == google else { throw HubError.integrity }
                print("keychain_roundtrip_smoke_ok viewer=unchanged google=unchanged interaction=disabled"); exit(0)
            } catch { fputs("keychain_roundtrip_smoke_failed: \(error.localizedDescription)\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--google-read-smoke") {
            SecKeychainSetUserInteractionAllowed(false)
            Task {
                do {
                    let client = GoogleClient()
                    let snapshot = try await client.snapshot(date: Date(), days: 1)
                    let quick = try await client.quickSnapshot()
                    print("google_read_smoke_ok lists=\(snapshot.lists.count) owned_calendars=\(snapshot.calendars.count) tasks=\(snapshot.tasks.count) events=\(snapshot.events.count) next_events=\(quick.events.count) interaction=disabled")
                    exit(0)
                } catch { fputs("google_read_smoke_failed: \(error.localizedDescription)\n", stderr); exit(1) }
            }
            RunLoop.main.run(); return
        }
        if CommandLine.arguments.contains("--keychain-prepare") {
            do {
                _ = try Connection.token(); _ = try GoogleKeychain.read("oauth")
                print("credential_reader_ready viewer=readable google=readable"); exit(0)
            } catch { fputs("credential_reader_prepare_failed: \(error.localizedDescription)\n", stderr); exit(1) }
        }
        if CommandLine.arguments.contains("--keychain-smoke") {
            // Fail immediately instead of displaying authorization dialogs during update checks.
            SecKeychainSetUserInteractionAllowed(false)
            do {
                _ = try Connection.token()
                guard let config = try JSONSerialization.jsonObject(with: GoogleKeychain.read("oauth")) as? [String: String],
                      !(config["refresh_token"] ?? "").isEmpty else { throw GoogleError.unconfigured }
                print("keychain_smoke_ok viewer=readable google=readable interaction=disabled"); exit(0)
            } catch { fputs("keychain_smoke_failed: \(error.localizedDescription)\n", stderr); exit(1) }
        }
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
        if CommandLine.arguments.contains("--google-config-status") {
            SecKeychainSetUserInteractionAllowed(false)
            Task {
                do {
                    let status = try await GoogleClient().configurationStatus()
                    let data = try JSONSerialization.data(withJSONObject: status, options: [.sortedKeys])
                    print(String(decoding: data, as: UTF8.self)); exit(0)
                } catch { fputs("google_config_status_failed: \(error.localizedDescription)\n", stderr); exit(1) }
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
                    print("client_smoke_stage sources_ok")
                    let page: RecordPage = try await api.get("api/v1/browse", query: [URLQueryItem(name: "limit", value: "3")])
                    let kinds: [KindCount] = try await api.get("api/v1/kinds")
                    print("client_smoke_stage browse_and_kinds_ok")
                    if let first = page.records.first { _ = try await api.record(first.id) }
                    let summaries: RecordPage = try await api.get("api/v1/browse", query: [URLQueryItem(name: "source", value: "skysight-summaries"), URLQueryItem(name: "limit", value: "1")])
                    guard let summary = summaries.records.first else { throw HubError.response }
                    let detail = try await api.record(summary.id)
                    print("client_smoke_stage details_ok")
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
        if CommandLine.arguments.contains("--reading-smoke") {
            SecKeychainSetUserInteractionAllowed(false)
            Task {
                do {
                    let api = HubAPI(Connection.load())
                    for variant in ["note", "daily_review", "execution_log"] {
                        let page: DocumentPage = try await api.get("api/v1/contents", query: DocumentFilter(variant: variant).parameters())
                        var longest: DocumentContent?
                        for item in page.items where item.ready {
                            let detail: DocumentContent = try await api.get("api/v1/contents/" + item.id)
                            if detail.readable && (longest == nil || (detail.metadata?.body_chars ?? 0) > (longest?.metadata?.body_chars ?? 0)) { longest = detail }
                        }
                        guard let document = longest else {
                            print("reading_smoke_pending variant=\(variant) listed=\(page.items.count)"); continue
                        }
                        let reader = DocumentReader()
                        await reader.open(DocumentSelection(item: document, query: ""), api: api)
                        while reader.nextAfter != nil && reader.error == nil { await reader.loadNext() }
                        await reader.loadEvidence()
                        guard reader.complete, let input = reader.evidence?.inputs.first, input.current_matches else { throw HubError.response }
                        let original = try await api.record(input.record_id)
                        let object = try JSONSerialization.jsonObject(with: Data(original.rawJSON.utf8)) as? [String: Any]
                        let normalized = object?["normalized"] as? [String: Any], raw = object?["raw"] as? [String: Any]
                        guard let sourceBody = normalized?["content"] as? String ?? raw?["content"] as? String else { throw HubError.response }
                        let expected = reader.header?.warnings.contains("nul_replaced_in_reading_copy") == true ? sourceBody.replacingOccurrences(of: "\u{0000}", with: "�") : sourceBody
                        guard reader.body == expected else { throw HubError.response }
                        if expected.unicodeScalars.count > 500 {
                            let term = String(expected.suffix(40)).trimmingCharacters(in: .whitespacesAndNewlines)
                            let search: DocumentPage = try await api.get("api/v1/contents", query: DocumentFilter(variant: variant, query: term).parameters())
                            guard let hit = search.items.first(where: { $0.id == document.id && $0.match != nil }) else { throw HubError.response }
                            let located = DocumentReader()
                            await located.open(DocumentSelection(item: hit, query: term), api: api)
                            guard located.matchResolved, let offset = located.matchOffset, offset > 500 else { throw HubError.response }
                            print("reading_smoke_search_ok variant=\(variant) body_offset=\(offset) beyond_preview=true")
                        }
                        if let asset = document.assets?.first(where: { $0.size < 1_000_000 }) {
                            let file = try await api.download(asset)
                            defer { try? FileManager.default.removeItem(at: file) }
                            try asset.verifyFile(file)
                            print("reading_smoke_asset_ok variant=\(variant) sha256=ok")
                        }
                        print("reading_smoke_ok variant=\(variant) listed=\(page.items.count) blocks=\(reader.blocks.count) body_characters=\(reader.body.count) original_body=equal evidence=current")
                    }
                    exit(0)
                } catch { fputs("reading_smoke_failed: \(error.localizedDescription)\n", stderr); exit(1) }
            }
            RunLoop.main.run(); return
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
