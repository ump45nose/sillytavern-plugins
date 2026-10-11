import Foundation
import SwiftUI

extension HubModel {
    var displayRequestKey: String { [dayKey(displayDate), displayModules.joined(separator: ","), String(trendDays)].joined(separator: "|") }
    var pageRequestKey: String { [section, overviewMode, displayRequestKey, timelineDomain, reportMode, networkSource, documentSource, isDocumentPage ? query : ""].joined(separator: "|") }
    var isDocumentPage: Bool { ["notes", "reports", "documents"].contains(section) }
    var isTimelinePage: Bool { section == "archive" || section == "recordings" || (section == "overview" && overviewMode == "recent") }
    var dashboardMatchesPage: Bool { dashboard != nil && displayResultKey == displayRequestKey }
    var pageLoading: Bool {
        if section == "network" { return networkLoading }
        if section == "status" { return statusLoading }
        if isDocumentPage { return documents.loading }
        if isTimelinePage { return timelineLoading }
        if section == "agenda" { return googleLoading }
        return displayLoading
    }
    var pageHasContent: Bool {
        if section == "network" { return networkMatchesPage }
        if section == "status" { return !sources.isEmpty || !agents.isEmpty }
        if isDocumentPage { return !documents.items.isEmpty }
        if isTimelinePage { return !timeline.isEmpty }
        if section == "agenda" { return googleSnapshot != nil }
        return dashboardMatchesPage
    }
    var pageLoadingMessage: String {
        if section == "status" { return "正在检查采集与来源状态…" }
        if isDocumentPage { return "正在读取文档列表…" }
        if isTimelinePage { return timeline.isEmpty ? "正在读取归档内容…" : "正在加载更多内容…" }
        if section == "agenda" { return "正在同步日程与任务…" }
        return "正在加载你的信息…"
    }
    func loadCurrentPage() async {
        error = nil
        if section == "status" {
            async let collection: Void = refreshStatus()
            async let processing: Void = refreshProcessing()
            _ = await (collection, processing)
        }
        else if section == "network" { await loadNetwork() }
        else if isDocumentPage { await loadDocuments() }
        else if isTimelinePage { await loadTimeline() }
        else if section == "agenda" { await refreshGoogle() }
        else {
            if displayModules.contains("agenda") {
                async let display: Void = loadDisplay()
                async let agenda: Void = refreshGoogle()
                _ = await (display, agenda)
            } else { await loadDisplay() }
        }
    }
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
        let resultKey = displayRequestKey
        let modules = displayModules
        let params = [URLQueryItem(name: "date", value: dayKey(displayDate)),
                      URLQueryItem(name: "tz", value: TimeZone.current.identifier),
                      URLQueryItem(name: "modules", value: modules.joined(separator: ","))]
        do {
            async let dashboard: Dashboard = api.get("api/v1/dashboard", query: params)
            async let trends: TrendPage = api.get("api/v1/trends", query: params + [URLQueryItem(name: "days", value: String(trendDays))])
            let (d, t) = try await (dashboard, trends)
            guard generation == displayGeneration else { return }
            self.dashboard = d; self.trends = t; self.displayResultKey = resultKey; self.error = nil
            let data = try JSONEncoder().encode(d)
            let path = Connection.directory.appendingPathComponent("dashboard-cache.json")
            try? data.write(to: path, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        } catch {
            if generation == displayGeneration && !Task.isCancelled {
                self.error = error.localizedDescription
                if dashboard == nil, let data = try? Data(contentsOf: Connection.directory.appendingPathComponent("dashboard-cache.json")) {
                    let cached = try? JSONDecoder().decode(Dashboard.self, from: data)
                    if let cached, cached.date == dayKey(displayDate), Set(cached.modules.map(\.id)) == Set(modules) {
                        dashboard = cached; displayResultKey = resultKey
                    }
                }
            }
        }
        if generation == displayGeneration { displayLoading = false }
    }
    func loadTimeline(reset: Bool = true, person: String? = nil) async {
        timelineGeneration += 1
        let generation = timelineGeneration
        timelineLoading = true
        defer { if generation == timelineGeneration { timelineLoading = false } }
        if reset { timelineCursor = nil; timeline = [] }
        let domain = section == "recordings" ? "recordings" : section == "reports" ? "reports" : timelineDomain
        var params = [URLQueryItem(name: "query", value: query), URLQueryItem(name: "domains", value: domain)]
        if !reset, let cursor = timelineCursor { params.append(URLQueryItem(name: "cursor", value: cursor)) }
        if let person = person { params.append(URLQueryItem(name: "person", value: person)) }
        do {
            let page: TimelinePage = try await api.get("api/v1/timeline", query: params)
            guard generation == timelineGeneration else { return }
            timeline = reset ? page.items : timeline + page.items
            timelineCursor = page.next_cursor
        } catch { if generation == timelineGeneration && !Task.isCancelled { self.error = error.localizedDescription } }
    }
    func refreshGoogle() async {
        googleGeneration += 1
        let generation = googleGeneration
        googleLoading = true
        defer { if generation == googleGeneration { googleLoading = false } }
        let date = displayDate, days = calendarWeek ? 7 : 1
        do {
            let snapshot = try await google.snapshot(date: date, days: days)
            guard generation == googleGeneration && !Task.isCancelled else { return }
            googleSnapshot = snapshot
            if !googleAuthorizing { googleMessage = nil }
            if quickSnapshot == nil && dayKey(displayDate) == dayKey(Date()) && !calendarWeek { quickSnapshot = snapshot }
        } catch {
            guard generation == googleGeneration && !Task.isCancelled else { return }
            if !googleAuthorizing { googleMessage = error.localizedDescription }
            if googleSnapshot == nil { googleSnapshot = GoogleSnapshot.load() }
        }
    }
    func refreshQuickGoogle() async {
        do { quickSnapshot = try await google.quickSnapshot(); if !googleAuthorizing { googleMessage = nil } }
        catch { if !googleAuthorizing { googleMessage = error.localizedDescription }; if quickSnapshot == nil { quickSnapshot = GoogleSnapshot.load(quick: true) } }
    }
    func connectGoogle() {
        googleOperation(authorizing: true) { try await self.google.authorize() }
    }
    func googleOperation(authorizing: Bool = false, _ action: @escaping () async throws -> Void) {
        guard !googleBusy else { return }
        googleBusy = true
        googleAuthorizing = authorizing
        if authorizing { googleMessage = "请在浏览器中选择 Google 账号并完成授权，完成后会自动返回连接结果。" }
        Task {
            do {
                try await action(); googleAuthorizing = false; googleMessage = nil; await refreshGoogle()
                if quickSnapshot != nil { await refreshQuickGoogle() }
            }
            catch { googleMessage = error.localizedDescription }
            googleAuthorizing = false
            googleBusy = false
        }
    }
    func openCard(_ card: DisplayCard) {
        selectedID = card.id
        Task { await select(card.id) }
        showingDetail = true
    }
    func persistPreferences() { preferences.save() }
}
