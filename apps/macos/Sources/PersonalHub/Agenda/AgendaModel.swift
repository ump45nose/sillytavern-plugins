import Foundation
import HubKit
import Network
import Observation
import SwiftUI

/// Main-actor face of the agenda: mirrors the sync engine's cache and turns UI intents into changes.
/// Shows the design sample (demo) until a Google account is connected.
@MainActor
@Observable
final class AgendaModel {
    enum Mode: Equatable { case demo, google }
    enum Connect: Equatable { case idle, authorizing, failed(String) }

    private(set) var mode: Mode = .demo
    private(set) var store = AgendaStore()
    private(set) var status: AgendaSync.Status = .idle
    private(set) var view = AgendaView()
    private(set) var now = Date()
    var connect: Connect = .idle
    var account: String? { mode == .google ? store.account : nil }

    @ObservationIgnored private var sync: AgendaSync
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var tokens: AccessTokenCache?
    @ObservationIgnored private var credential: StoredCredential?
    @ObservationIgnored private var timers: [Timer] = []
    @ObservationIgnored private let path = NWPathMonitor()
    @ObservationIgnored private var online = true
    @ObservationIgnored private var authorizing: Task<Void, Never>?
    @ObservationIgnored private var chain: Task<Void, Never>?
    @ObservationIgnored private let transport = URLSessionTransport()
    @ObservationIgnored private let calendar = Calendar.hub
    /// Replaceable before `start()` so offscreen QA renders show a fixed moment.
    @ObservationIgnored var clock: () -> Date = { Date() }

    static let cacheFile = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PersonalHub/agenda.json")

    init() {
        sync = AgendaSync(seed: AgendaStore())
    }

    func start() {
        now = clock()
        attach(AgendaSync(seed: AgendaSample.store(now: now)), mode: .demo)
        Task { await restore() }

        let tick = Timer(timeInterval: 30, repeats: true) { _ in MainActor.assumeIsolated { self.tick() } }
        let poll = Timer(timeInterval: 5 * 60, repeats: true) { _ in MainActor.assumeIsolated { self.refresh() } }
        for t in [tick, poll] { RunLoop.main.add(t, forMode: .common); timers.append(t) }

        path.pathUpdateHandler = { [weak self] p in
            let up = p.status == .satisfied
            Task { @MainActor in
                guard let self else { return }
                if up, !self.online { self.refresh() }
                self.online = up
            }
        }
        path.start(queue: DispatchQueue(label: "hub.agenda.path"))
    }

    /// Opening the popover or window, ⌘R, the 5-minute poll and network recovery all land here.
    func refresh() {
        guard mode == .google else { return }
        let sync = self.sync
        Task { await sync.requestSync() }
    }

    // MARK: Account

    private func restore() async {
        guard GoogleAccount.client() != nil else { return }
        let stored = await Task.detached { try? CredentialStore.load() }.value
        guard let stored else { return }
        await activate(stored)
    }

    func connectGoogle() {
        guard authorizing == nil else { return }
        guard let client = GoogleAccount.client() else {
            connect = .failed(GoogleAccount.Failure.missingConfig.localizedDescription)
            return
        }
        connect = .authorizing
        authorizing = Task {
            defer { authorizing = nil }
            do {
                let credential = try await GoogleAccount.authorize(client: client, transport: transport)
                try await Task.detached { try CredentialStore.save(credential) }.value
                connect = .idle
                await activate(credential)
                Reminders.shared.requestAuthorization()
            } catch is CancellationError {
                connect = .idle
            } catch {
                connect = .failed(Self.describe(error))
            }
        }
    }

    func cancelConnect() {
        authorizing?.cancel()
    }

    func disconnectGoogle() {
        let refresh = credential?.refreshToken, sync = self.sync, transport = self.transport
        credential = nil
        tokens = nil
        Reminders.shared.clear()
        Task {
            await sync.disconnect()
            if let refresh { await GoogleAccount.revoke(refresh, transport: transport) }
            _ = try? await Task.detached { try CredentialStore.delete() }.value
        }
        attach(AgendaSync(seed: AgendaSample.store(now: clock())), mode: .demo)
    }

    private func activate(_ credential: StoredCredential) async {
        guard let client = GoogleAccount.client() else { return }
        self.credential = credential
        let refresh = credential.refreshToken
        let cache = AccessTokenCache(client: client, transport: transport) { refresh }
        tokens = cache
        let api = GoogleAPI(transport: transport) { force in try await cache.get(forceRefresh: force) }
        let real = AgendaSync(file: Self.cacheFile)
        await real.connect(api: api, account: credential.account)
        attach(real, mode: .google)
        await real.requestSync()
    }

    private func attach(_ next: AgendaSync, mode: Mode) {
        generation += 1
        let mine = generation
        sync = next
        self.mode = mode
        let handler: @Sendable (AgendaStore, AgendaSync.Status) -> Void = { [weak self] store, status in
            Task { @MainActor in
                guard let self, self.generation == mine else { return }
                self.store = store
                self.status = status
                self.rebuild()
            }
        }
        Task { await next.observe(handler) }
    }

    private func tick() {
        let previous = now
        now = clock()
        if Int(previous.timeIntervalSince1970 / 60) != Int(now.timeIntervalSince1970 / 60) { rebuild() }
    }

    private func rebuild() {
        view = Agenda.build(store, now: now, calendar: calendar)
        if mode == .google { Reminders.shared.schedule(view, now: now, calendar: calendar) }
    }

    // MARK: Intents

    var lists: [TaskListRecord] { store.lists }
    var pendingCount: Int { mode == .google ? store.pending.count : 0 }
    var failures: [SyncFailure] { mode == .google ? store.failures : [] }
    var lastSync: Date? { mode == .google ? store.lastSync : nil }

    /// Chained so dependent changes (a new list, then a task in it) reach the queue in order.
    func perform(_ change: Change) {
        let sync = self.sync, previous = chain
        chain = Task {
            await previous?.value
            await sync.perform(change)
        }
    }

    func dismissFailures() {
        let sync = self.sync
        Task { await sync.dismissFailures() }
    }

    func toggle(_ t: AgendaTask) {
        perform(.updateTask(id: t.id, listID: t.listID, patch: TaskPatch(completed: !t.completed)))
    }

    func reschedule(_ t: AgendaTask, to day: Date?) {
        perform(.updateTask(id: t.id, listID: t.listID, patch: TaskPatch(due: .some(day.map { GoogleDate.dayString($0, calendar: calendar) }))))
    }

    func update(_ t: AgendaTask, title: String, notes: String, due: Date?, listID: String) {
        let notesValue: String? = notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : notes
        let dueValue = due.map { GoogleDate.dayString($0, calendar: calendar) }
        let oldDue = t.due.map { GoogleDate.dayString($0, calendar: calendar) }
        var patch = TaskPatch()
        if title != t.title, !title.isEmpty { patch.title = title }
        if notesValue != t.notes { patch.notes = .some(notesValue) }
        if dueValue != oldDue { patch.due = .some(dueValue) }
        if patch != TaskPatch() { perform(.updateTask(id: t.id, listID: t.listID, patch: patch)) }
        if listID != t.listID { move(t, to: listID) }
    }

    func move(_ t: AgendaTask, to listID: String) {
        guard listID != t.listID else { return }
        perform(.moveTask(id: t.id, listID: t.listID, toList: listID, parent: nil))
    }

    func delete(_ t: AgendaTask) {
        perform(.deleteTask(id: t.id, listID: t.listID))
    }

    func addSubtask(to parent: AgendaTask, title: String) {
        perform(.createTask(id: AgendaStore.localID(), listID: parent.listID, title: title, notes: nil, due: nil, parent: parent.id))
    }

    func createList(_ title: String) -> String {
        let id = AgendaStore.localID()
        perform(.createList(id: id, title: title))
        return id
    }

    func renameList(_ id: String, to title: String) { perform(.renameList(id: id, title: title)) }
    func deleteList(_ id: String) { perform(.deleteList(id: id)) }

    /// The list a `#tag` names (case-insensitive), or nil when it would be created.
    func list(named tag: String) -> TaskListRecord? {
        store.lists.first { $0.title.compare(tag, options: [.caseInsensitive, .widthInsensitive]) == .orderedSame }
    }

    var defaultList: TaskListRecord? { store.lists.first }

    var writableCalendar: CalendarRecord? {
        store.calendars.first { $0.primary && ["owner", "writer"].contains($0.accessRole) }
    }

    /// Adds a quick-entry task; a timed entry can also block out an hour on the primary calendar.
    @discardableResult
    func add(_ entry: QuickEntry, timeBlock: Bool) -> Bool {
        guard !entry.title.isEmpty else { return false }
        let listID: String
        if let tag = entry.listTag {
            listID = list(named: tag)?.id ?? createList(tag)
        } else if let first = defaultList {
            listID = first.id
        } else {
            return false
        }
        let due = entry.due.map { GoogleDate.dayString($0, calendar: calendar) }
        let blocking = timeBlock && entry.hasTime && entry.due != nil && writableCalendar != nil
        let notes = entry.hasTime && !blocking ? entry.due.map { "时间 " + Agenda.clock($0, calendar: calendar) } : nil
        perform(.createTask(id: AgendaStore.localID(), listID: listID, title: entry.title, notes: notes, due: due, parent: nil))
        if blocking, let start = entry.due, let cal = writableCalendar {
            perform(.createEvent(id: AgendaStore.localID(), calendarID: cal.id, title: entry.title,
                                 start: start, end: start.addingTimeInterval(3600), notes: nil))
        }
        return true
    }

    func search(_ query: String) -> [AgendaTask] {
        Agenda.search(store, query: query, calendar: calendar)
    }

    private static func describe(_ error: Error) -> String {
        switch error {
        case LoopbackReceiver.Failure.timeout: "等待浏览器授权超时，请重试。"
        case LoopbackReceiver.Failure.denied: "浏览器里取消了授权。"
        case LoopbackReceiver.Failure.listener: "无法在本机启动授权回调，请重试。"
        case GoogleAPIError.offline: "网络不可用。"
        case GoogleAPIError.unauthorized: "Google 拒绝了授权，请重试。"
        default: error.localizedDescription
        }
    }
}
