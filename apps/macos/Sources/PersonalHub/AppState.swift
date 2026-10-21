import Foundation
import HubKit
import Observation
import SwiftUI

@MainActor
@Observable
final class AppState {
    static let shared = AppState()

    /// Design sample, still the source for cycle and goals until personal-review is wired up.
    let snapshot = Sample.snapshot
    let agenda = AgendaModel()
    let hub = HubModel()

    var layout: LayoutDocument { didSet { persistLayout() } }
    var currentPage = "home"
    var editing = false
    var tokenRange: TokenRange = .week
    var focusedModule: ModuleID?
    var skySelection = 0

    var memosURL: String { didSet { UserDefaults.standard.set(memosURL, forKey: Keys.memosURL) } }

    /// Set by the app delegate so views can open windows and panels without knowing AppKit.
    var openMainWindow: (String?) -> Void = { _ in }
    var openSettings: () -> Void = {}
    var showQuickTask: () -> Void = {}
    var showQuickMemo: () -> Void = {}

    private let store = LayoutStore.appSupport()

    private enum Keys {
        static let memosURL = "memosURL"
    }

    private init() {
        layout = store.load()
        memosURL = UserDefaults.standard.string(forKey: Keys.memosURL) ?? "http://192.168.31.201:5230"
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

    func resetLayout() {
        withAnimation(Motion.spring) { layout = .default }
    }

    func sync() {
        agenda.refresh()
        hub.refresh()
    }

    var syncingAny: Bool { syncing || hub.status == .syncing }

    // MARK: Module freshness

    func updatedAt(_ module: ModuleID) -> Date? {
        switch module {
        case .agenda: return agenda.lastSync
        case .sky: return hub.sky.map { $0.segments.last?.end ?? $0.end }.max().map { min($0, HubFormat.current()) }
        case .brief, .goals, .attention: return nil
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
        if let url = entry.url { NSWorkspace.shared.open(url) } else if let m = entry.target { openMainWindow(nil); focus(m) }
    }

    private func persistLayout() {
        do { try store.save(layout) } catch { NSLog("Personal Hub: layout save failed: \(error.localizedDescription)") }
    }
}

enum Clock {
    static func hhmm(_ hour: Double) -> String {
        String(format: "%02d:%02d", Int(hour), Int((hour - floor(hour)) * 60 + 0.5))
    }
}
