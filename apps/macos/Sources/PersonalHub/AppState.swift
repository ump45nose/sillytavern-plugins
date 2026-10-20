import Foundation
import HubKit
import Observation
import SwiftUI

@MainActor
@Observable
final class AppState {
    static let shared = AppState()

    let snapshot = Sample.snapshot
    let tokenSummaries = TokenSample.summaries(usage: Sample.snapshot.token)

    var layout: LayoutDocument { didSet { persistLayout() } }
    var currentPage = "home"
    var editing = false
    var tokenRange: TokenRange = .week
    var doneTasks: Set<String>
    var focusedModule: ModuleID?
    var skySelection = 0
    var syncing = false
    var lastSync = "17:58"

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
        let t = Sample.snapshot.tasks
        doneTasks = Set((t.overdue + t.today + t.upcoming).filter(\.done).map(\.title))
    }

    var page: Page { layout.page(currentPage) ?? layout.pages[0] }

    var dueCount: Int {
        let t = snapshot.tasks
        return (t.overdue + t.today).filter { !doneTasks.contains($0.title) }.count
    }

    var statusTitle: String {
        let next = snapshot.events.first { $0.start > snapshot.now.hour }
        return next.map { "\(dueCount) · \(Clock.hhmm($0.start)) \($0.title)" } ?? "\(dueCount)"
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

    func toggleTask(_ title: String) {
        withAnimation(Motion.spring) {
            if doneTasks.contains(title) { doneTasks.remove(title) } else { doneTasks.insert(title) }
        }
    }

    func editPage(_ change: (inout Page) -> Void) {
        withAnimation(Motion.spring) { layout.update(currentPage, change) }
    }

    func resetLayout() {
        withAnimation(Motion.spring) { layout = .default }
    }

    func sync() {
        guard !syncing else { return }
        syncing = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            self.syncing = false
            self.lastSync = "刚刚"
        }
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
