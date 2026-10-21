import Foundation

/// Owns the hub cache: refreshes every module from hub-api and keeps the last good copy on disk,
/// so the app opens instantly and keeps showing data while the NAS is unreachable.
public actor HubSync {
    public enum Status: Equatable, Sendable {
        case idle
        case syncing
        case offline
        /// The device token was rejected; the user must sign in again.
        case needsSignIn
        case failed(String)
    }

    private var api: HubAPI?
    private var data: HubData
    private let file: URL?
    private let now: @Sendable () -> Date
    private var running: Task<Void, Never>?
    private var observer: (@Sendable (HubData, Status) -> Void)?
    public private(set) var status: Status = .idle

    public init(file: URL?, now: @escaping @Sendable () -> Date = { Date() }) {
        self.file = file
        self.now = now
        data = file.flatMap { try? Data(contentsOf: $0) }.flatMap { try? HubJSON.decoder.decode(HubData.self, from: $0) } ?? HubData()
    }

    /// In-memory and never connected (demo mode).
    public init(seed: HubData) {
        file = nil
        now = { Date() }
        data = seed
    }

    public var snapshot: HubData { data }

    public func observe(_ handler: @escaping @Sendable (HubData, Status) -> Void) {
        observer = handler
        handler(data, status)
    }

    public func connect(api: HubAPI?) {
        if let old = self.api?.credential.baseURL, old != api?.credential.baseURL {
            data = HubData()
            save()
        }
        self.api = api
        publish()
    }

    public func disconnect() {
        api = nil
        data = HubData()
        save()
        status = .idle
        publish()
    }

    /// Coalesces concurrent requests into the running refresh.
    public func refresh() async {
        guard api != nil else { return }
        if let running { return await running.value }
        let task = Task { await refreshOnce() }
        running = task
        await task.value
        running = nil
    }

    private func refreshOnce() async {
        guard let api else { return }
        set(.syncing)
        do {
            async let batch = api.modules()
            async let sources = api.status()
            async let week = try? api.token(range: .week)
            async let month = try? api.token(range: .month)
            async let year = try? api.token(range: .year)
            var next = try await batch
            next.sources = (try? await sources) ?? data.sources
            for (range, envelope) in [(TokenRange.week, await week), (.month, await month), (.year, await year)] {
                next.token[range] = envelope ?? data.token[range]
            }
            next.fetchedAt = now()
            data = next
            save()
            set(.idle)
        } catch let error as HubError {
            switch error {
            case .offline: set(.offline)
            case .unauthorized: set(.needsSignIn)
            default: set(.failed(error.message))
            }
        } catch {
            set(.failed(error.localizedDescription))
        }
    }

    /// Optimistically shows a memo that was just posted, until the next refresh brings the real one.
    public func inserted(memo id: String, content: String, visibility: String) {
        guard var envelope = data.memos, var d = envelope.data else { return }
        let tags = content.split(whereSeparator: \.isWhitespace).filter { $0.hasPrefix("#") && $0.count > 1 }.map { String($0.dropFirst()) }
        d.recent = [MemosData.Memo(id: id, createdAt: now(), content: content, tags: tags, visibility: visibility)] + (d.recent ?? [])
        envelope.data = d
        data.memos = envelope
        save()
        publish()
    }

    private func set(_ s: Status) {
        status = s
        publish()
    }

    private func publish() { observer?(data, status) }

    private func save() {
        guard let file else { return }
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try HubJSON.encoder.encode(data).write(to: file, options: [.atomic])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        } catch {
            NSLog("Personal Hub: hub cache save failed")
        }
    }
}
