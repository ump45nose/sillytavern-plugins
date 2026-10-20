import Foundation
import HubKit
import Observation
import SwiftUI

@MainActor
@Observable
final class AppState {
    static let shared = AppState()

    let snapshot = Sample.snapshot
    let agenda = AgendaModel()
    let tokenSummaries = TokenSample.summaries(usage: Sample.snapshot.token)

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

    func sync() { agenda.refresh() }

    private func persistLayout() {
        do { try store.save(layout) } catch { NSLog("Personal Hub: layout save failed: \(error.localizedDescription)") }
    }
}

enum Clock {
    static func hhmm(_ hour: Double) -> String {
        String(format: "%02d:%02d", Int(hour), Int((hour - floor(hour)) * 60 + 0.5))
    }
}
