import AppKit
import AVFoundation
import Foundation
import HubKit
import Network
import Observation

/// Main-actor face of hub-api: mirrors the sync cache for the module views. Shows the design
/// sample (demo) until a hub device token is stored.
@MainActor
@Observable
final class HubModel {
    enum Mode: Equatable { case demo, hub }
    enum SignIn: Equatable { case idle, waiting, failed(String) }

    private(set) var mode: Mode = .demo
    private(set) var data = HubData()
    private(set) var status: HubSync.Status = .idle
    private(set) var baseURL: URL?
    var signIn: SignIn = .idle
    /// Bumped when a cover finishes loading so posters re-render.
    private(set) var imageGeneration = 0
    /// Computer history comes from the local skysight archive, independent of hub.
    private(set) var sky: [SkyWindowItem] = [] { didSet { if !skyLive { seedSkyDays() } } }
    private(set) var skyLive = false
    /// Every local day the archive has, newest first, and the windows of the days opened so far.
    private(set) var skyDays: [Date] = []
    /// 10-minute segments per day, for the date picker's shading.
    private(set) var skyActivity: [Date: Int] = [:]
    private(set) var skyByDay: [Date: [SkyWindowItem]] = [:]
    @ObservationIgnored private var skyFiles: [SkyFile] = []
    @ObservationIgnored private var skyLoading: Set<Date> = []

    @ObservationIgnored private var sync = HubSync(seed: HubData())
    @ObservationIgnored private var api: HubAPI?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var timers: [Timer] = []
    @ObservationIgnored private let path = NWPathMonitor()
    @ObservationIgnored private var online = true
    @ObservationIgnored private var signingIn: Task<Void, Never>?
    @ObservationIgnored private let transport = URLSessionTransport()
    @ObservationIgnored private var images: [String: NSImage] = [:]
    @ObservationIgnored private var loading: Set<String> = []
    @ObservationIgnored var clock: () -> Date = { Date() }

    static let cacheFile = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/PersonalHub/hub.json")
    /// Public NPM entry: device sign-in needs it (Secure cookie, Authelia callback) and it also works on the LAN.
    nonisolated static let defaultBase = URL(string: "https://hub-home.172906573.xyz:28443")!
    /// Posted by `--hub-token-stdin` so a running app picks up the new credential.
    nonisolated static let changed = Notification.Name("com.yuwk.personal-hub.hub-credential-changed")

    func start() {
        attach(HubSync(seed: HubSample.data(now: clock())), mode: .demo)
        sky = SkyArchive.sample(now: clock())
        loadSky()
        Task { await restore() }

        let poll = Timer(timeInterval: 5 * 60, repeats: true) { _ in MainActor.assumeIsolated { self.refresh() } }
        RunLoop.main.add(poll, forMode: .common)
        timers.append(poll)
        path.pathUpdateHandler = { [weak self] p in
            let up = p.status == .satisfied
            Task { @MainActor in
                guard let self else { return }
                if up, !self.online { self.refresh() }
                self.online = up
            }
        }
        path.start(queue: DispatchQueue(label: "hub.data.path"))
        DistributedNotificationCenter.default().addObserver(forName: Self.changed, object: nil, queue: .main) { _ in
            Task { @MainActor in await self.restore() }
        }
    }

    /// Offscreen QA renders: the demo data at a fixed moment, no network.
    func preview(now: Date) {
        attach(HubSync(seed: HubSample.data(now: now)), mode: .demo)
        sky = SkyArchive.sample(now: now)
    }

    #if DEBUG
    /// Offscreen QA renders of the last synced hub data: reads the local cache only, no network or keychain.
    func previewCache() async {
        attach(HubSync(file: Self.cacheFile), mode: .hub)
        let windows = await Task.detached { SkyArchive.load() }.value
        if !windows.isEmpty { sky = windows; skyLive = true }
    }

    /// QA: the sample cycle on its last day, so the close form renders.
    func previewClose() {
        guard var g = data.goals?.data else { return }
        g.close = .init(status: .preclose, cycleId: g.cycle?.id, template: g.cycle.map { ReviewSample.closeTemplate($0.id) })
        data.goals?.data = g
    }
    #endif

    func refresh() {
        loadSky()
        guard mode == .hub else { return }
        let sync = self.sync
        Task { await sync.refresh() }
        onRefresh?()
    }

    /// Runs alongside every hub refresh (poll, network return, sign-in); the layout sync hangs off it.
    @ObservationIgnored var onRefresh: (() -> Void)?

    /// The signed-in API, or nil in demo mode.
    var liveAPI: HubAPI? { api }

    private func loadSky() {
        Task {
            let (files, windows) = await Task.detached(priority: .utility) { () -> ([SkyFile], [SkyWindowItem]) in
                let files = SkyArchive.index()
                return (files, SkyArchive.load())
            }.value
            guard !windows.isEmpty else { return }
            skyLive = true
            if files.count != skyFiles.count {
                skyFiles = files
                skyDays = SkyArchive.days(files)
                skyActivity = SkyArchive.activity(files)
                skyByDay = [:]
            }
            if windows != sky { sky = windows }
        }
    }

    /// The windows of one day; loads it from the archive the first time it is asked for.
    func skyWindows(_ day: Date) -> [SkyWindowItem]? {
        let key = Calendar.hub.startOfDay(for: day)
        if let hit = skyByDay[key] { return hit }
        guard skyLive, !skyLoading.contains(key) else { return nil }
        skyLoading.insert(key)
        let files = skyFiles
        Task {
            let windows = await Task.detached(priority: .userInitiated) { SkyArchive.load(files, day: key) }.value
            skyLoading.remove(key)
            skyByDay[key] = windows
        }
        return nil
    }

    private func seedSkyDays() {
        let grouped = Dictionary(grouping: sky) { Calendar.hub.startOfDay(for: $0.start) }
        skyByDay = grouped
        skyDays = grouped.keys.sorted(by: >)
        skyActivity = grouped.mapValues { $0.reduce(0) { $0 + $1.segments.count } }
    }

    // MARK: Account

    private func restore() async {
        let stored = await Task.detached { try? CredentialStore.load().hub }.value
        if let stored { activate(stored) } else if mode == .hub { forget() }
    }

    private func activate(_ credential: HubCredential) {
        Reminders.shared.requestAuthorization()
        let api = HubAPI(transport: transport, credential: credential)
        self.api = api
        baseURL = credential.baseURL
        images = [:]
        let engine = mode == .hub ? sync : HubSync(file: Self.cacheFile)
        if engine !== sync { attach(engine, mode: .hub) }
        Task {
            await engine.connect(api: api)
            await engine.refresh()
        }
        onRefresh?()
    }

    /// Browser sign-in through Authelia (hub-api §4.3).
    func signIn(base: URL) {
        guard signingIn == nil else { return }
        signIn = .waiting
        let transport = self.transport
        signingIn = Task {
            defer { signingIn = nil }
            do {
                let state = UUID().uuidString, pkce = OAuth.PKCE.make()
                let receiver = try LoopbackReceiver(state: state, success: "Personal Hub 已登录 hub")
                let name = Host.current().localizedName ?? "Mac"
                let code = try await receiver.code { uri in
                    guard let url = HubSignIn.startURL(base: base, deviceName: name, redirect: uri + "/callback", pkce: pkce, state: state) else { return }
                    DispatchQueue.main.async { NSWorkspace.shared.open(url) }
                }
                let credential = try await HubSignIn.exchange(base: base, code: code, verifier: pkce.verifier, transport: transport)
                try await Task.detached { try CredentialStore.update { $0.hub = credential } }.value
                signIn = .idle
                activate(credential)
            } catch is CancellationError {
                signIn = .idle
            } catch let e as HubError {
                signIn = .failed(e == .http(404) ? "这个 hub 还没开放设备登录。" : e.message)
            } catch {
                signIn = .failed((error as? CredentialStore.Failure)?.errorDescription ?? "登录没有完成，请重试。")
            }
        }
    }

    func cancelSignIn() { signingIn?.cancel() }

    private static let baseKey = "hubBaseURL"

    /// Address for sign-in and the one shown in settings; the LAN address works too once signed in.
    var preferredBase: URL {
        get { UserDefaults.standard.string(forKey: Self.baseKey).flatMap(URL.init(string:)) ?? baseURL ?? Self.defaultBase }
        set { UserDefaults.standard.set(newValue.absoluteString, forKey: Self.baseKey) }
    }

    static func parseBase(_ text: String) -> URL? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: t), let scheme = url.scheme, ["http", "https"].contains(scheme), url.host() != nil,
              url.path().isEmpty || url.path() == "/" else { return nil }
        return url
    }

    /// Points the stored device token at another address of the same hub, after checking it answers.
    func changeBase(_ url: URL) async -> String? {
        guard mode == .hub, let current = api?.credential else {
            preferredBase = url
            return nil
        }
        guard url != current.baseURL else { return nil }
        var next = current
        next.baseURL = url
        do {
            _ = try await HubAPI(transport: transport, credential: next).status()
        } catch let e as HubError {
            return e == .unauthorized ? "这个地址不认当前设备令牌，可能不是同一个 hub。" : e.message
        } catch {
            return "这个地址连不上。"
        }
        do {
            try await Task.detached { try CredentialStore.update { $0.hub = next } }.value
        } catch {
            return (error as? CredentialStore.Failure)?.errorDescription ?? "保存失败。"
        }
        preferredBase = url
        activate(next)
        return nil
    }

    /// Deletes the local device token. Revoking it on the server is done from another device or hub-api.
    func disconnect() {
        Task { _ = try? await Task.detached { try CredentialStore.update { $0.hub = nil } }.value }
        forget()
    }

    private func forget() {
        Reminders.shared.forgetAttention()
        let sync = self.sync
        api = nil
        baseURL = nil
        images = [:]
        Task { await sync.disconnect() }
        attach(HubSync(seed: HubSample.data(now: clock())), mode: .demo)
    }

    private func attach(_ next: HubSync, mode: Mode) {
        generation += 1
        let mine = generation
        sync = next
        self.mode = mode
        let handler: @Sendable (HubData, HubSync.Status) -> Void = { [weak self] data, status in
            Task { @MainActor in
                guard let self, self.generation == mine else { return }
                let fetched = data.fetchedAt != self.data.fetchedAt
                self.data = data
                self.status = status
                if self.mode == .hub, fetched, let attention = data.attention, attention.status.hasData {
                    Reminders.shared.announce(attention.data?.items ?? [])
                }
            }
        }
        Task { await next.observe(handler) }
    }

    // MARK: Reading

    func token(_ range: TokenRange) -> TokenRangeSummary? {
        guard let d = data.token[range]?.data else { return nil }
        return TokenRangeSummary(d, now: clock(), daily: TokenRangeSummary.daily(from: data.token[.year]?.data))
    }

    /// All-time daily totals; any range carries the same `history`.
    func tokenHistory() -> TokenHistory? {
        let history = [TokenRange.day, .week, .month].lazy.compactMap { self.data.token[$0]?.data?.history }.first { !$0.isEmpty }
        return TokenHistory.make(history: history, yearGrid: data.token[.year]?.data, now: clock())
    }

    var sourcesHealthy: (ok: Int, total: Int) {
        let configured = data.sources.filter { $0.status != .unconfigured }
        return (configured.filter { $0.status == .ok }.count, configured.count)
    }

    /// Covers are fetched through hub-api's signed proxy and kept in memory for the session.
    func image(_ ref: String?) -> NSImage? {
        guard let ref, let api else { return nil }
        if let hit = images[ref] { return hit }
        guard !loading.contains(ref) else { return nil }
        loading.insert(ref)
        Task {
            defer { loading.remove(ref) }
            guard let bytes = try? await api.image(ref: ref), let image = NSImage(data: bytes) else { return }
            images[ref] = image
            imageGeneration += 1
        }
        return nil
    }

    func subscriptionIcon(_ path: String?) -> NSImage? {
        guard let path, let api else { return nil }
        let key = "subscription:" + path
        if let hit = images[key] { return hit }
        guard !loading.contains(key) else { return nil }
        loading.insert(key)
        Task {
            defer { loading.remove(key) }
            guard let bytes = try? await api.subscriptionIcon(path), let image = NSImage(data: bytes) else { return }
            images[key] = image
            imageGeneration += 1
        }
        return nil
    }

    func player(recording id: String) -> AVPlayer? {
        guard let api, let request = try? api.audioRequest(recording: id), let url = request.url else { return nil }
        let asset = AVURLAsset(url: url, options: ["AVURLAssetHTTPHeaderFieldsKey": request.allHTTPHeaderFields ?? [:]])
        return AVPlayer(playerItem: AVPlayerItem(asset: asset))
    }

    func transcript(recording id: String) async -> String? {
        guard let api else { return PlaudSample.transcript(id) }
        return try? await api.transcript(recording: id)
    }

    enum PlaudSource { case hub, crm, sample }

    /// The recordings list; until hub ships it, today's Plaud recordings attached to CRM interactions.
    func plaudRecordings(before: String? = nil) async throws -> (list: PlaudList, source: PlaudSource) {
        guard let api else { return (PlaudSample.list(now: clock()), .sample) }
        do {
            if let list = try await api.plaudRecordings(before: before) { return (list, .hub) }
        } catch let e as HubError {
            throw WriteError.hub(e)
        }
        let today = data.crm?.data?.today ?? []
        let recordings = today.compactMap { i in
            i.recording.flatMap { r in r.id.hasPrefix("plaud:") ? PlaudList.Recording(id: r.id, title: r.title ?? i.summary, startAt: i.time, durationSeconds: r.durationSeconds) : nil }
        }
        let people = Array(Set(today.filter { $0.recording?.id.hasPrefix("plaud:") == true }.map(\.name))).sorted()
        let days = recordings.isEmpty ? [] : [PlaudList.Day(date: ReviewText.dayKey(clock()), recordings: recordings, hasTranscript: true, people: people)]
        return (PlaudList(days: days), .crm)
    }

    // MARK: Writing

    enum WriteError: LocalizedError {
        case demo
        case hub(HubError)
        var errorDescription: String? {
            switch self {
            case .demo: "还没连接 hub，示例模式下不会保存。"
            case .hub(let e): e.message
            }
        }
    }

    /// Reads fall back to the sample in demo mode; writes refuse with `.demo`.
    func review<T>(demo: () throws -> T, live: (HubAPI) async throws -> T) async throws -> T {
        guard let api else { return try demo() }
        return try await live(api)
    }

    func postMemo(_ content: String, visibility: String = "PRIVATE") async throws {
        guard let api else { throw WriteError.demo }
        do {
            let created = try await api.createMemo(content: content, visibility: visibility)
            await sync.inserted(memo: created.id, content: content, visibility: visibility)
        } catch let e as HubError {
            throw WriteError.hub(e)
        }
    }
}
