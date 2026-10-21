import AppKit
import HubKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSPopoverDelegate {
    private let state = AppState.shared
    private var statusItem: NSStatusItem!
    private let popover = NSPopover()
    private var mainWindow: NSWindow?
    private var settingsWindow: NSWindow?
    private var taskPanel: QuickPanel?
    private var memoPanel: QuickPanel?
    private var titleObserver: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = MainMenu.build(target: self)
        state.openMainWindow = { [weak self] page in self?.showMainWindow(page: page) }
        state.openSettings = { [weak self] in self?.showSettings() }
        state.pagesChanged = { [weak self] in
            guard let self, let view = NSApp.mainMenu?.item(withTitle: "视图")?.submenu else { return }
            MainMenu.fillPages(view, state: self.state, target: self)
        }
        state.showQuickTask = { [weak self] in self?.toggleQuickPanel(.task) }
        state.showQuickMemo = { [weak self] in self?.toggleQuickPanel(.memo) }

        state.agenda.start()
        state.hub.start()
        setUpStatusItem()
        HotKeyCenter.shared.bind(.quickTask) { [weak self] in self?.toggleQuickPanel(.task) }
        HotKeyCenter.shared.bind(.quickMemo) { [weak self] in self?.toggleQuickPanel(.memo) }
        HotKeyCenter.shared.bind(.tray) { [weak self] in self?.togglePopover() }

        if !CommandLine.arguments.contains("--background") { showMainWindow(page: nil) }
        #if DEBUG
        applyQAOverrides()
        #endif
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showMainWindow(page: nil)
        return true
    }

    // MARK: Status item & popover

    private func setUpStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = LogoImage.template(size: 15)
        statusItem.button?.imagePosition = .imageLeading
        statusItem.button?.target = self
        statusItem.button?.action = #selector(togglePopover)
        updateStatusTitle()

        popover.behavior = .transient
        popover.animates = true
        popover.delegate = self
        let host = NSHostingController(rootView: PopoverView().environment(state))
        host.sizingOptions = .preferredContentSize
        popover.contentViewController = host
    }

    private func updateStatusTitle() {
        let title = NSMutableAttributedString(string: " " + state.statusTitle, attributes: [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 13, weight: .regular),
        ])
        if !state.attention.isEmpty {
            title.append(NSAttributedString(string: " ●", attributes: [
                .font: NSFont.systemFont(ofSize: 8),
                .foregroundColor: NSColor(Tone.clay.color),
                .baselineOffset: 1.5,
            ]))
        }
        statusItem.button?.attributedTitle = title
        withObservationTracking { _ = state.statusTitle; _ = state.attention.isEmpty } onChange: { [weak self] in
            DispatchQueue.main.async { self?.updateStatusTitle() }
        }
    }

    @objc private func togglePopover() {
        guard let button = statusItem.button else { return }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            state.syncIfStale()
            NSApp.activate(ignoringOtherApps: true)
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
            watchOutsideClicks()
        }
    }

    /// `.transient` misses clicks in other apps while ours is an accessory, and clicks in our own
    /// windows; close on both. Menus and editors opened from the panel live in child popovers.
    private var clickMonitors: [Any] = []

    private func watchOutsideClicks() {
        guard clickMonitors.isEmpty else { return }
        let mask: NSEvent.EventTypeMask = [.leftMouseDown, .rightMouseDown, .otherMouseDown]
        if let global = NSEvent.addGlobalMonitorForEvents(matching: mask, handler: { [weak self] _ in
            MainActor.assumeIsolated { self?.closePopover() }
        }) { clickMonitors.append(global) }
        if let local = NSEvent.addLocalMonitorForEvents(matching: mask, handler: { [weak self] event in
            MainActor.assumeIsolated {
                guard let self, let window = event.window else { return event }
                let panel = self.popover.contentViewController?.view.window
                let inside = window === panel || window.className.contains("Popover") || window.className.contains("Menu")
                    || window === self.statusItem.button?.window
                if !inside { self.closePopover() }
                return event
            }
        }) { clickMonitors.append(local) }
    }

    private func closePopover() {
        if popover.isShown { popover.performClose(nil) }
        clickMonitors.forEach(NSEvent.removeMonitor)
        clickMonitors = []
    }

    func popoverDidClose(_ notification: Notification) {
        clickMonitors.forEach(NSEvent.removeMonitor)
        clickMonitors = []
    }

    // MARK: Windows

    @objc func showMainWindowAction() { showMainWindow(page: nil) }

    func showMainWindow(page: String?) {
        popover.performClose(nil)
        if let page { state.go(page) }
        if mainWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1320, height: 900),
                             styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                             backing: .buffered, defer: false)
            w.titlebarAppearsTransparent = true
            w.titleVisibility = .hidden
            w.isReleasedWhenClosed = false
            w.title = "Personal Hub"
            w.backgroundColor = NSColor(Palette.bg)
            w.contentView = NSHostingView(rootView: MainView().environment(state))
            w.minSize = NSSize(width: 1100, height: 720)
            w.setFrameAutosaveName("PersonalHubMain")
            if !w.setFrameUsingName("PersonalHubMain") { w.center() }
            w.delegate = self
            mainWindow = w
        }
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        mainWindow?.makeKeyAndOrderFront(nil)
        state.syncIfStale()
    }

    #if DEBUG
    /// `-QAPage usage -QAWindowSize 1320x2400` lets screenshots cover a whole page.
    private func applyQAOverrides() {
        let defaults = UserDefaults.standard
        guard defaults.object(forKey: "QAPage") != nil || defaults.object(forKey: "QAShow") != nil
            || defaults.object(forKey: "QAWindowSize") != nil else { return }
        // Occluded windows stop redrawing, so keep the QA window above the terminal.
        mainWindow?.level = .floating
        if let page = defaults.string(forKey: "QAPage") { state.go(page) }
        if let size = defaults.string(forKey: "QAWindowSize")?.split(separator: "x").compactMap({ Double($0) }), size.count == 2 {
            mainWindow?.setFrame(NSRect(x: 0, y: 0, width: size[0], height: size[1]), display: true)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [self] in
            switch defaults.string(forKey: "QAShow") {
            case "popover": togglePopover()
            case "task": toggleQuickPanel(.task)
            case "memo": toggleQuickPanel(.memo)
            case "settings": showSettings()
            case "review": state.openReview(.latest(.daily))
            case "edit": toggleEditing()
            default: break
            }
        }
    }
    #endif

    @objc func showSettings() {
        popover.performClose(nil)
        if settingsWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 440),
                             styleMask: [.titled, .closable, .fullSizeContentView], backing: .buffered, defer: false)
            w.titlebarAppearsTransparent = true
            w.title = "设置"
            w.isReleasedWhenClosed = false
            w.contentView = NSHostingView(rootView: SettingsView().environment(state))
            w.center()
            w.delegate = self
            settingsWindow = w
        }
        NSApp.activate(ignoringOtherApps: true)
        settingsWindow?.makeKeyAndOrderFront(nil)
    }

    @objc func showReviewAction() { state.openReview(.latest(.daily)) }

    func windowWillClose(_ notification: Notification) {
        guard let w = notification.object as? NSWindow else { return }
        DispatchQueue.main.async {
            let others = [self.mainWindow, self.settingsWindow].compactMap { $0 }.filter { $0 !== w && $0.isVisible }
            if others.isEmpty { NSApp.setActivationPolicy(.accessory) }
        }
    }

    // MARK: Quick panels

    private func toggleQuickPanel(_ kind: QuickKind) {
        let existing = kind == .task ? taskPanel : memoPanel
        if let existing, existing.isVisible { existing.dismiss(); return }
        popover.performClose(nil)
        let panel = existing ?? QuickPanel(width: kind == .task ? 640 : 560)
        let root = switch kind {
        case .task:
            AnyView(QuickTaskView(close: { [weak panel] in panel?.dismiss() },
                                  resize: { [weak panel] in panel?.fit() },
                                  openMain: { [weak self] in self?.showMainWindow(page: nil) }))
        case .memo:
            AnyView(QuickMemoView { [weak panel] in panel?.dismiss() })
        }
        let host = NSHostingView(rootView: root.environment(state))
        // Empty options make fittingSize (0, 0). Intrinsic size is only a measurement;
        // present() and fit() still place the frame so the top edge stays put.
        host.sizingOptions = [.intrinsicContentSize]
        panel.contentView = host
        if kind == .task { taskPanel = panel } else { memoPanel = panel }
        panel.present()
    }

    // MARK: Menu actions

    @objc func goPage(_ sender: NSMenuItem) {
        guard let id = sender.representedObject as? String else { return }
        showMainWindow(page: id)
    }

    @objc func toggleEditing() {
        guard state.page.kind == .grid else { return }
        withAnimation(Motion.spring) { state.editing.toggle() }
    }

    @objc func refresh() { state.sync() }

    @objc func quickTaskAction() { toggleQuickPanel(.task) }

    @objc func quickMemoAction() { toggleQuickPanel(.memo) }
}

enum MainMenu {
    @MainActor
    static func build(target: AppDelegate) -> NSMenu {
        let main = NSMenu()

        let app = NSMenu()
        app.addItem(withTitle: "关于 Personal Hub", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(item("设置…", #selector(AppDelegate.showSettings), ",", target))
        app.addItem(.separator())
        app.addItem(withTitle: "隐藏 Personal Hub", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(.separator())
        app.addItem(withTitle: "退出 Personal Hub", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        main.addItem(submenu(app, "Personal Hub"))

        let edit = NSMenu(title: "编辑")
        edit.addItem(withTitle: "撤销", action: Selector(("undo:")), keyEquivalent: "z")
        edit.addItem(withTitle: "重做", action: Selector(("redo:")), keyEquivalent: "Z")
        edit.addItem(.separator())
        edit.addItem(withTitle: "剪切", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "拷贝", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "粘贴", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "全选", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        main.addItem(submenu(edit, "编辑"))

        let view = NSMenu(title: "视图")
        fillPages(view, state: AppState.shared, target: target)
        view.addItem(.separator())
        view.addItem(item("编辑布局", #selector(AppDelegate.toggleEditing), "e", target))
        view.addItem(item("刷新", #selector(AppDelegate.refresh), "r", target))
        view.addItem(.separator())
        view.addItem(item("快速任务", #selector(AppDelegate.quickTaskAction), "", target))
        view.addItem(item("快速 Memo", #selector(AppDelegate.quickMemoAction), "", target))
        main.addItem(submenu(view, "视图"))

        let window = NSMenu(title: "窗口")
        window.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        window.addItem(withTitle: "关闭", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        window.addItem(.separator())
        window.addItem(item("主窗口", #selector(AppDelegate.showMainWindowAction), "0", target))
        let review = item("复盘", #selector(AppDelegate.showReviewAction), "r", target)
        review.keyEquivalentModifierMask = [.command, .shift]
        window.addItem(review)
        main.addItem(submenu(window, "窗口"))
        NSApp.windowsMenu = window
        return main
    }

    private static let pageTag = 7_001

    /// Page items (⌘1–⌘9 by position) lead the View menu and are replaced whenever the pages change.
    @MainActor
    static func fillPages(_ menu: NSMenu, state: AppState, target: AnyObject) {
        for old in menu.items where old.tag == pageTag { menu.removeItem(old) }
        for (i, page) in state.layout.pages.enumerated() {
            let it = item(page.title, #selector(AppDelegate.goPage(_:)), NavEntry.shortcut(i) == nil ? "" : "\(i + 1)", target)
            it.representedObject = page.id
            it.tag = pageTag
            menu.insertItem(it, at: i)
        }
    }

    @MainActor
    private static func item(_ title: String, _ action: Selector, _ key: String, _ target: AnyObject) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: action, keyEquivalent: key)
        it.target = target
        return it
    }

    private static func submenu(_ menu: NSMenu, _ title: String) -> NSMenuItem {
        let it = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        it.submenu = menu
        return it
    }
}
