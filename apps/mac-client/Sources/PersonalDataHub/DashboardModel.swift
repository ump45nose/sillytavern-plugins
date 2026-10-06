import Foundation
import SwiftUI

extension HubModel {
    var displayModules: [String] {
        switch section {
        case "health": return ["health"]
        case "social": return ["social"]
        case "finance": return ["finance", "usage", "network"]
        case "agenda": return ["agenda"]
        default: return preferences.enabled
        }
    }
    func loadDisplay() async {
        displayGeneration += 1
        let generation = displayGeneration
        displayLoading = true
        let modules = displayModules
        let params = [URLQueryItem(name: "date", value: dayKey(displayDate)),
                      URLQueryItem(name: "tz", value: TimeZone.current.identifier),
                      URLQueryItem(name: "modules", value: modules.joined(separator: ","))]
        do {
            async let dashboard: Dashboard = api.get("api/v1/dashboard", query: params)
            async let trends: TrendPage = api.get("api/v1/trends", query: params + [URLQueryItem(name: "days", value: String(trendDays))])
            let (d, t) = try await (dashboard, trends)
            guard generation == displayGeneration else { return }
            self.dashboard = d; self.trends = t; self.error = nil
            let data = try JSONEncoder().encode(d)
            let path = Connection.directory.appendingPathComponent("dashboard-cache.json")
            try? data.write(to: path, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        } catch {
            if generation == displayGeneration {
                self.error = error.localizedDescription
                if dashboard == nil, let data = try? Data(contentsOf: Connection.directory.appendingPathComponent("dashboard-cache.json")) {
                    dashboard = try? JSONDecoder().decode(Dashboard.self, from: data)
                }
            }
        }
        if generation == displayGeneration { displayLoading = false }
    }
    func loadTimeline(reset: Bool = true, person: String? = nil) async {
        timelineGeneration += 1
        let generation = timelineGeneration
        if reset { timelineCursor = nil; timeline = [] }
        var params = [URLQueryItem(name: "query", value: query), URLQueryItem(name: "domains", value: timelineDomain)]
        if !reset, let cursor = timelineCursor { params.append(URLQueryItem(name: "cursor", value: cursor)) }
        if let person = person { params.append(URLQueryItem(name: "person", value: person)) }
        do {
            let page: TimelinePage = try await api.get("api/v1/timeline", query: params)
            guard generation == timelineGeneration else { return }
            timeline = reset ? page.items : timeline + page.items
            timelineCursor = page.next_cursor
        } catch { if generation == timelineGeneration { self.error = error.localizedDescription } }
    }
    func refreshGoogle() async {
        do {
            let snapshot = try await google.snapshot(date: displayDate, days: calendarWeek ? 7 : 1)
            googleSnapshot = snapshot; googleMessage = nil
            if quickSnapshot == nil && dayKey(displayDate) == dayKey(Date()) && !calendarWeek { quickSnapshot = snapshot }
        } catch {
            googleMessage = error.localizedDescription
            if googleSnapshot == nil { googleSnapshot = GoogleSnapshot.load() }
        }
    }
    func refreshQuickGoogle() async {
        do { quickSnapshot = try await google.quickSnapshot(); googleMessage = nil }
        catch { googleMessage = error.localizedDescription; if quickSnapshot == nil { quickSnapshot = GoogleSnapshot.load(quick: true) } }
    }
    func googleOperation(_ action: @escaping () async throws -> Void) {
        guard !googleBusy else { return }
        googleBusy = true
        Task {
            do {
                try await action(); googleMessage = nil; await refreshGoogle()
                if quickSnapshot != nil { await refreshQuickGoogle() }
            }
            catch { googleMessage = error.localizedDescription }
            googleBusy = false
        }
    }
    func openCard(_ card: DisplayCard) {
        selectedID = card.id
        Task { await select(card.id) }
        showingDetail = true
    }
    func persistPreferences() { preferences.save(); Task { await loadDisplay() } }
}
