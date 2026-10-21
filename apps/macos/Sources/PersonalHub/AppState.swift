import AppKit
import Foundation
import HubKit
import Observation
import SwiftUI

@MainActor
@Observable
final class AppState {
    static let shared = AppState()

    let agenda = AgendaModel()
    let hub = HubModel()
    let review: ReviewDesk
    let memos: MemosStore
    let aiPending = AIPendingModel(store: AppState.isQA
        ? AIPendingStore(dir: FileManager.default.temporaryDirectory.appendingPathComponent("PersonalHub-qa-\(ProcessInfo.processInfo.processIdentifier)/pending-ai"))
        : HubMCP.pending)
    let aiRun = AgentRun()
    var aiAgent: AIAgent { didSet { UserDefaults.standard.set(aiAgent.rawValue, forKey: Keys.aiAgent) } }
    var paletteOpen = false

    var layout: LayoutDocument { didSet { layoutChanged() } }
    var currentPage = "home"
    var editing = false
    var tokenRange: TokenRange = .week
    var focusedModule: ModuleID?
    var skySelection = 0

    var memosURL: String { didSet { UserDefaults.standard.set(memosURL, forKey: Keys.memosURL) } }
    var userName: String { didSet { UserDefaults.standard.set(userName, forKey: Keys.userName) } }
    private(set) var avatar: NSImage?

    /// Set by the app delegate so views can open windows and panels without knowing AppKit.
    var openMainWindow: (String?) -> Void = { _ in }
    var openSettings: () -> Void = {}
    var showQuickTask: () -> Void = {}
    var showQuickMemo: () -> Void = {}
    /// The View menu's ⌘1–⌘9 items follow the page order.
    var pagesChanged: () -> Void = {}

    /// Offscreen QA renders edit pages; they must not touch the real layout or its sync state.
    static let isQA = CommandLine.arguments.contains("--qa-render") || CommandLine.arguments.contains("--qa-bench")
    private let store = isQA
        ? LayoutStore(url: FileManager.default.temporaryDirectory.appendingPathComponent("PersonalHub-qa-\(ProcessInfo.processInfo.processIdentifier)/layout.json"))
        : LayoutStore.appSupport()
    @ObservationIgnored private var layoutSync: LayoutSyncState
    @ObservationIgnored private var adopting = false
    @ObservationIgnored private var layoutRound = false
    @ObservationIgnored private var layoutAgain = false
    @ObservationIgnored private var layoutPush: Task<Void, Never>?

    private enum Keys {
        static let memosURL = "memosURL"
        static let layoutSync = "layoutSync"
        static let userName = "userName"
        static let aiAgent = "aiAgent"
    }

    /// Square-cropped copy of the picked avatar, kept next to the layout.
    static let avatarURL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("PersonalHub/avatar.png")

    /// Name used in the greeting and sidebar; falls back to the macOS account name.
    var displayName: String {
        let n = userName.trimmingCharacters(in: .whitespaces)
        return n.isEmpty ? (NSFullUserName().isEmpty ? "你" : NSFullUserName()) : n
    }

    func setAvatar(from url: URL?) {
        guard let url else {
            try? FileManager.default.removeItem(at: Self.avatarURL)
            avatar = nil
            return
        }
        guard let image = NSImage(contentsOf: url), let png = Self.squarePNG(image, side: 256) else { return }
        try? FileManager.default.createDirectory(at: Self.avatarURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? png.write(to: Self.avatarURL, options: .atomic)
        avatar = NSImage(data: png)
    }

    private static func squarePNG(_ image: NSImage, side: CGFloat) -> Data? {
        guard let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        let w = CGFloat(cg.width), h = CGFloat(cg.height), s = min(w, h)
        guard let crop = cg.cropping(to: CGRect(x: (w - s) / 2, y: (h - s) / 2, width: s, height: s)),
              let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: Int(side), pixelsHigh: Int(side), bitsPerSample: 8,
                                         samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)
        else { return nil }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current?.imageInterpolation = .high
        NSGraphicsContext.current?.cgContext.draw(crop, in: CGRect(x: 0, y: 0, width: side, height: side))
        NSGraphicsContext.restoreGraphicsState()
        return rep.representation(using: .png, properties: [:])
    }

    private init() {
        review = ReviewDesk(hub: hub)
        memos = MemosStore(hub: hub)
        layout = store.load().withBuiltins()
        memosURL = UserDefaults.standard.string(forKey: Keys.memosURL) ?? "http://192.168.31.201:5230"
        userName = UserDefaults.standard.string(forKey: Keys.userName) ?? "玮康"
        aiAgent = UserDefaults.standard.string(forKey: Keys.aiAgent).flatMap(AIAgent.init(rawValue:)) ?? .codex
        avatar = Self.isQA ? nil : NSImage(contentsOf: Self.avatarURL)
        layoutSync = UserDefaults.standard.data(forKey: Keys.layoutSync).flatMap { try? JSONDecoder().decode(LayoutSyncState.self, from: $0) } ?? LayoutSyncState()
        if !Self.isQA { hub.onRefresh = { [weak self] in self?.syncLayout() } }
    }

    var page: Page { layout.page(currentPage) ?? layout.pages[0] }

    var dueCount: Int { agenda.view.dueCount }

    var statusTitle: String { Agenda.menuTitle(agenda.view, now: agenda.now) }

    var syncing: Bool { agenda.status == .syncing }

    var lastSync: String {
        switch agenda.status {
        case .offline: return "离线"
        case .needsReconnect: return "需重新连接"
        case .failed: return "同步失败"
        default: break
        }
        guard agenda.mode == .google else { return "示例数据" }
        guard let at = agenda.lastSync else { return "未同步" }
        return agenda.now.timeIntervalSince(at) < 60 ? "刚刚" : Agenda.clock(at)
    }

    func go(_ pageID: String) {
        guard pageID != currentPage, layout.page(pageID) != nil else { return }
        editing = false
        withAnimation(Motion.rise) { currentPage = pageID }
    }

    func focus(_ module: ModuleID) {
        if !page.items.contains(where: { $0.module == module }),
           let other = layout.pages.first(where: { p in p.items.contains { $0.module == module } }) {
            go(other.id)
        }
        focusedModule = module
    }

    func editPage(_ change: (inout Page) -> Void) {
        withAnimation(Motion.spring) { layout.update(currentPage, change) }
    }

    /// Menu bar panel pages live in the same synced document as the window's pages.
    func editLayout(_ change: (inout LayoutDocument) -> Void) {
        withAnimation(Motion.spring) { change(&layout) }
    }

    /// Built-in pages get their default modules back; a custom page is emptied.
    func resetPage() {
        withAnimation(Motion.spring) { layout.resetPage(currentPage) }
    }

    /// Every page back to the default set, custom pages included.
    func resetLayout() {
        withAnimation(Motion.spring) { layout = .default }
    }

    // MARK: Pages

    /// Creates an empty page, opens it and enters layout editing so modules can be added.
    @discardableResult
    func newPage() -> String? {
        var id: String?
        withAnimation(Motion.spring) { id = layout.addPage() }
        guard let id else { return nil }
        go(id)
        withAnimation(Motion.spring) { editing = true }
        return id
    }

    func renamePage(_ id: String, title: String, subtitle: String) {
        layout.renamePage(id, title: title, subtitle: subtitle)
    }

    func movePage(_ id: String, to index: Int) {
        withAnimation(Motion.spring) { layout.movePage(id, to: index) }
    }

    func movePage(_ id: String, by offset: Int) {
        withAnimation(Motion.spring) { layout.movePage(id, by: offset) }
    }

    func deletePage(_ id: String) {
        guard let i = layout.pages.firstIndex(where: { $0.id == id }), !LayoutDocument.isBuiltin(id) else { return }
        if currentPage == id {
            editing = false
            currentPage = layout.pages[i > 0 ? i - 1 : min(1, layout.pages.count - 1)].id
        }
        withAnimation(Motion.spring) { _ = layout.removePage(id) }
    }

    func sync() {
        agenda.refresh()
        hub.refresh()
    }

    /// Opening the panel or the window: skip sources synced within the last minute (⌘R still forces).
    func syncIfStale(_ age: TimeInterval = 60) {
        let now = Date()
        if agenda.lastSync.map({ now.timeIntervalSince($0) > age }) ?? true { agenda.refresh() }
        if hub.data.fetchedAt.map({ now.timeIntervalSince($0) > age }) ?? true { hub.refresh() }
    }

    var syncingAny: Bool { syncing || hub.status == .syncing }

    // MARK: Module freshness

    func updatedAt(_ module: ModuleID) -> Date? {
        switch module {
        case .agenda: return agenda.lastSync
        case .sky: return hub.sky.map { $0.segments.last?.end ?? $0.end }.max().map { min($0, HubFormat.current()) }
        case .brief, .attention: return nil
        default: return HubModule(rawValue: module.rawValue).flatMap { hub.data.updatedAt($0) }
        }
    }

    func stamp(_ module: ModuleID) -> String? { HubFormat.stamp(updatedAt(module)) }

    /// Only the states worth flagging on a module header.
    func hubStatus(_ module: ModuleID) -> HubStatus? {
        guard hub.mode == .hub, module != .attention, let m = HubModule(rawValue: module.rawValue),
              let status = hub.data.status(m) else { return nil }
        if status.hasData, hub.status == .offline { return .stale }
        return [.stale, .partial, .error].contains(status) ? status : nil
    }

    // MARK: Attention

    /// Local overdue tasks first, then whatever hub's rules raised.
    var attention: [AttentionEntry] {
        let local = agenda.view.overdue.prefix(2).map { t in
            AttentionEntry(id: "task:" + t.id, tone: .rose, title: "「\(t.title)」逾期 \(t.overdueDays) 天",
                           subtitle: t.listTitle, action: "处理", target: .agenda, url: nil)
        }
        let remote = (hub.data.attention?.data?.items ?? []).map { a in
            AttentionEntry(id: a.id, tone: AttentionEntry.tone(rule: a.rule, severity: a.severity), title: a.title,
                           subtitle: Self.readable(a.subtitle) ?? HubFormat.ago(a.since), action: a.url == nil ? "查看" : "打开",
                           target: a.target?.module.flatMap(ModuleID.init(rawValue:)), url: a.url.flatMap(URL.init(string:)))
        }
        return Array(local) + remote
    }

    /// Some rules put a bare ISO timestamp (a reset time) in the subtitle.
    private static func readable(_ subtitle: String?) -> String? {
        guard let subtitle, !subtitle.isEmpty else { return nil }
        guard let date = HubJSON.parseDate(subtitle) else { return subtitle }
        return date > HubFormat.current() ? TokenTone.resets(date) : HubFormat.ago(date)
    }

    func open(_ entry: AttentionEntry) {
        if let target = ReviewTarget(attention: entry.id) { return openReview(target) }
        if entry.id.hasPrefix("stage:close:") { return openReview(.stage) }
        if let url = entry.url { NSWorkspace.shared.open(url) } else if let m = entry.target { openMainWindow(nil); focus(m) }
    }

    /// Review lives on its built-in page in the main window.
    func openReview(_ target: ReviewTarget) {
        review.open(target)
        openMainWindow("review")
    }

    // MARK: Goals

    var goals: GoalsData? { hub.data.goals?.data }

    var cycle: Cycle? { goals?.cycle.map(StageTone.cycle) }

    // MARK: Layout persistence and hub sync

    private func layoutChanged() {
        do { try store.save(layout) } catch { NSLog("Personal Hub: layout save failed: \(error.localizedDescription)") }
        if layout.page(currentPage) == nil, let first = layout.pages.first { currentPage = first.id }
        pagesChanged()
        guard !adopting, !Self.isQA else { return }
        layoutSync.dirty = true
        saveLayoutSync()
        layoutPush?.cancel()
        layoutPush = Task {
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            syncLayout()
        }
    }

    /// One exchange with hub-api's layout store; overlapping calls fold into one more round.
    func syncLayout() {
        guard let api = hub.liveAPI else { return }
        if layoutRound { layoutAgain = true; return }
        layoutRound = true
        let local = layout, state = layoutSync
        Task {
            do {
                var outcome = try await LayoutSync.run(api: api, local: local, state: state)
                if layout != local {
                    outcome.state.dirty = true
                } else if let doc = outcome.adopt {
                    let migrated = doc.withBuiltins()
                    adopting = true
                    withAnimation(Motion.spring) { layout = migrated }
                    adopting = false
                    if migrated != doc { outcome.state.dirty = true }
                }
                layoutSync = outcome.state
                saveLayoutSync()
            } catch {
                NSLog("Personal Hub: layout sync skipped (\(type(of: error)))")
            }
            layoutRound = false
            if layoutAgain {
                layoutAgain = false
                syncLayout()
            }
        }
    }

    private func saveLayoutSync() {
        UserDefaults.standard.set(try? JSONEncoder().encode(layoutSync), forKey: Keys.layoutSync)
    }
}

enum Clock {
    static func hhmm(_ hour: Double) -> String {
        String(format: "%02d:%02d", Int(hour), Int((hour - floor(hour)) * 60 + 0.5))
    }
}
