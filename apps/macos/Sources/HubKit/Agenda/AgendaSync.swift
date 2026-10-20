import Foundation

/// Owns the agenda cache: applies local changes, uploads the queue in order, then pulls from Google.
public actor AgendaSync {
    public enum Status: Equatable, Sendable {
        case idle
        case syncing
        case offline
        /// Credentials were rejected; the user must reconnect.
        case needsReconnect
        case failed(String)
    }

    private var api: GoogleAPI?
    private var store: AgendaStore
    private let file: URL?
    private let calendar: Calendar
    private let now: @Sendable () -> Date
    private var running: Task<Void, Never>?
    private var again = false
    private var observer: (@Sendable (AgendaStore, Status) -> Void)?
    public private(set) var status: Status = .idle

    /// Events are kept from one day back to this many days ahead.
    public static let horizonDays = 60

    public init(file: URL?, calendar: Calendar = .hub, now: @escaping @Sendable () -> Date = { Date() }) {
        self.file = file
        self.calendar = calendar
        self.now = now
        store = file.flatMap { try? Data(contentsOf: $0) }.flatMap { try? JSONDecoder().decode(AgendaStore.self, from: $0) } ?? AgendaStore()
    }

    /// In-memory and never connected: local changes apply but are never uploaded (demo mode).
    public init(seed: AgendaStore, calendar: Calendar = .hub) {
        file = nil
        self.calendar = calendar
        now = { Date() }
        store = seed
    }

    public var snapshot: AgendaStore { store }

    public func observe(_ handler: @escaping @Sendable (AgendaStore, Status) -> Void) {
        observer = handler
        handler(store, status)
    }

    public func connect(api: GoogleAPI?, account: String?) {
        self.api = api
        if store.account != account {
            // A different account must never see the previous account's cache or queue.
            store = AgendaStore(account: account)
            save()
        }
        publish()
    }

    public func disconnect() {
        api = nil
        store = AgendaStore()
        save()
        setStatus(.idle)
    }

    public func perform(_ change: Change) {
        store.enqueue(change, at: now())
        save()
        publish()
        requestSync()
    }

    public func dismissFailures() {
        store.failures.removeAll()
        save()
        publish()
    }

    /// Coalesces requests; a request during a running sync triggers one more pass afterwards.
    public func requestSync() {
        guard api != nil else { return }
        if running != nil { again = true; return }
        running = Task { await loop() }
    }

    /// Runs a sync and waits for it, for callers that need the result (tests, manual refresh).
    public func syncNow() async {
        requestSync()
        await running?.value
    }

    private func loop() async {
        repeat {
            again = false
            await syncOnce()
        } while again
        running = nil
    }

    func syncOnce() async {
        guard let api else { return }
        setStatus(.syncing)
        do {
            try await flush(api)
            try await pull(api)
            store.lastSync = now()
            save()
            setStatus(.idle)
        } catch let error as GoogleAPIError {
            save()
            switch error {
            case .offline: setStatus(.offline)
            case .unauthorized: setStatus(.needsReconnect)
            default: setStatus(.failed(Self.describe(error)))
            }
        } catch {
            save()
            setStatus(.failed(error.localizedDescription))
        }
    }

    // MARK: Upload

    private func flush(_ api: GoogleAPI) async throws {
        while let next = store.pending.first {
            do {
                let created = try await upload(next.change, api)
                // The user deleted the item while its creation was in flight.
                if let created, !store.pending.contains(where: { $0.id == next.id }) {
                    store.pending.insert(PendingChange(change: created, queuedAt: now()), at: 0)
                }
                store.pending.removeAll { $0.id == next.id }
            } catch let error as GoogleAPIError where error.isTransient {
                throw error
            } catch let error as GoogleAPIError where error == .notFound && next.change.isDelete {
                store.pending.removeAll { $0.id == next.id }
            } catch {
                store.pending.removeAll { $0.id == next.id }
                store.invalidate(for: next.change)
                let reason = (error as? GoogleAPIError).map(Self.describe) ?? error.localizedDescription
                store.failures.append(SyncFailure(id: next.id, summary: "\(next.change.summary)未能同步：\(reason)", at: now()))
            }
            save()
            publish()
        }
    }

    /// Returns the delete that undoes a creation, for when the local item vanished meanwhile.
    private func upload(_ change: Change, _ api: GoogleAPI) async throws -> Change? {
        switch change {
        case let .createTask(id, listID, title, notes, due, parent):
            guard !AgendaStore.isLocal(listID), !(parent.map(AgendaStore.isLocal) ?? false) else { throw GoogleAPIError.invalidResponse }
            let created = try await api.insertTask(listID: listID, title: title, notes: notes, due: due, parent: parent)
            guard store.tasks.contains(where: { $0.id == id }) else { return .deleteTask(id: created.id, listID: listID) }
            store.remap(task: id, to: created.id)
            if let i = store.tasks.firstIndex(where: { $0.id == created.id }) { store.tasks[i] = created }
        case let .updateTask(id, listID, patch):
            let updated = try await api.patchTask(listID: listID, id: id, patch: patch)
            if let i = store.tasks.firstIndex(where: { $0.id == id }) { store.tasks[i] = updated }
        case let .deleteTask(id, listID):
            try await api.deleteTask(listID: listID, id: id)
        case let .moveTask(id, listID, toList, parent):
            let moved = try await api.moveTask(listID: listID, id: id, parent: parent, destinationList: toList == listID ? nil : toList)
            if let i = store.tasks.firstIndex(where: { $0.id == id }) { store.tasks[i] = moved }
        case let .createList(id, title):
            let created = try await api.insertList(title: title)
            guard store.lists.contains(where: { $0.id == id }) else { return .deleteList(id: created.id) }
            store.remap(list: id, to: created.id)
        case let .renameList(id, title):
            try await api.renameList(id: id, title: title)
        case let .deleteList(id):
            try await api.deleteList(id: id)
        case let .createEvent(id, calendarID, title, start, end, notes):
            let created = try await api.insertEvent(calendarID: calendarID, title: title, start: start, end: end, notes: notes)
            store.remap(event: id, to: created)
        }
        return nil
    }

    // MARK: Download

    private func pull(_ api: GoogleAPI) async throws {
        let started = now()
        // Overlap pulls a little so server/client clock skew never drops an update.
        let since = GoogleDate.string(started.addingTimeInterval(-300))

        let lists = try await api.taskLists()
        let ids = Set(lists.map(\.id))
        store.lists = lists
        store.tasks.removeAll { !ids.contains($0.listID) && !AgendaStore.isLocal($0.listID) }
        store.tasksPulledAt = store.tasksPulledAt.filter { ids.contains($0.key) }
        for list in lists {
            let previous = store.tasksPulledAt[list.id]
            let records = try await api.tasks(listID: list.id, updatedMin: previous)
            store.mergeTasks(list: list.id, records: records, full: previous == nil)
            store.tasksPulledAt[list.id] = since
        }

        // calendar.events.owned can only read calendars the account owns; subscribed ones return 403.
        let calendars = try await api.calendars().filter { $0.selected && $0.accessRole == "owner" }
        store.calendars = calendars
        let calendarIDs = Set(calendars.map(\.id))
        store.events.removeAll { !calendarIDs.contains($0.calendarID) }
        store.calendarSyncTokens = store.calendarSyncTokens.filter { calendarIDs.contains($0.key) }
        let windowStart = calendar.date(byAdding: .day, value: -1, to: calendar.startOfDay(for: started))!
        let windowEnd = calendar.date(byAdding: .day, value: Self.horizonDays, to: windowStart)!
        for cal in calendars {
            let token = store.calendarSyncTokens[cal.id]
            let page: GoogleAPI.EventPage
            var full = token == nil
            do {
                page = try await api.events(calendarID: cal.id, syncToken: token, timeMin: windowStart)
            } catch GoogleAPIError.gone {
                full = true
                page = try await api.events(calendarID: cal.id, syncToken: nil, timeMin: windowStart)
            }
            store.mergeEvents(calendar: cal.id, records: page.events, full: full)
            store.calendarSyncTokens[cal.id] = page.nextSyncToken
        }
        store.pruneEvents(keepingFrom: windowStart, to: windowEnd)
        store.reapplyPending()
    }

    // MARK: Plumbing

    private func save() {
        guard let file else { return }
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(store).write(to: file, options: [.atomic])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        } catch {
            status = .failed("本地缓存写入失败")
        }
    }

    private func setStatus(_ s: Status) {
        status = s
        publish()
    }

    private func publish() { observer?(store, status) }

    static func describe(_ e: GoogleAPIError) -> String {
        switch e {
        case .unauthorized: "Google 授权已失效"
        case .notFound: "内容已在其他设备删除"
        case .gone: "需要重新同步"
        case .http(let code): "Google 返回 \(code)"
        case .offline: "网络不可用"
        case .invalidResponse: "Google 返回了无法识别的数据"
        }
    }
}

extension Change {
    var isDelete: Bool {
        switch self {
        case .deleteTask, .deleteList: true
        default: false
        }
    }
}
