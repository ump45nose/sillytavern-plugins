import AppKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = HubModel()
    var statusItem: NSStatusItem!
    var window: NSWindow?

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
        model.start()
        if CommandLine.arguments.contains("--show") { showWindow() }
        if CommandLine.arguments.contains("--ui-smoke") {
            Task { await checkWindow() }
        }
    }

    func checkWindow() async {
        showWindow()
        await model.refreshStatus()
        model.source = "skysight-summaries"
        try? await Task.sleep(nanoseconds: 300_000_000)
        await model.browse(reset: true)
        guard model.sources.count > 0, let first = model.records.first else {
            fputs("client_ui_load_failed\n", stderr); exit(1)
        }
        model.selectedID = first.id
        try? await Task.sleep(nanoseconds: 300_000_000)
        await model.select(first.id)
        try? await Task.sleep(nanoseconds: 300_000_000)
        guard model.detail != nil, let view = window?.contentView else {
            fputs("client_ui_detail_failed\n", stderr); exit(1)
        }
        view.layoutSubtreeIfNeeded()
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
            fputs("client_ui_render_failed\n", stderr); exit(1)
        }
        view.cacheDisplay(in: view.bounds, to: bitmap)
        do {
            guard let data = bitmap.representation(using: .png, properties: [:]) else { throw HubError.response }
            let path = Connection.directory.appendingPathComponent("client-qa.png")
            try data.write(to: path, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
            print("client_ui_smoke_ok sources=\(model.sources.count) page=\(model.records.count) detail=loaded window=\(Int(view.bounds.width))x\(Int(view.bounds.height))")
            exit(0)
        } catch { fputs("client_ui_capture_failed\n", stderr); exit(1) }
    }

    @objc func showWindow() {
        if window == nil {
            let content = NSHostingView(rootView: ContentView(model: model))
            let value = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1240, height: 780),
                                 styleMask: [.titled, .closable, .miniaturizable, .resizable],
                                 backing: .buffered, defer: false)
            value.title = "Personal Data Hub"
            value.contentView = content
            value.isReleasedWhenClosed = false
            value.setFrameAutosaveName("PersonalDataHubArchive")
            value.center()
            window = value
        }
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
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
