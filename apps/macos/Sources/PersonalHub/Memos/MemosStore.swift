import AppKit
import Foundation
import HubKit
import Observation

/// The Memos page's timeline: hub's paged list with tag, text and view filters. Until hub ships the list
/// endpoint it shows the module's recent memos, filtered locally.
@MainActor @Observable
final class MemosStore {
    enum Source { case hub, recent, sample }
    enum Phase: Equatable { case idle, loading, ready, failed(String) }
    enum Filter: CaseIterable { case all, pinned, attachments, archived }

    typealias Memo = MemosData.Memo

    private let hub: HubModel
    private(set) var items: [Memo] = [] { didSet { snapshot() } }
    private(set) var next: String? { didSet { snapshot() } }
    private(set) var source: Source = .hub
    private(set) var phase: Phase = .idle
    private(set) var loadingMore = false
    private(set) var tag: String?
    private(set) var filter: Filter = .all
    /// hub answered the archived view with ordinary memos: it doesn't know the `state` filter yet.
    private(set) var archiveUnsupported = false
    /// Creation dates from the last unfiltered list, so the activity grid holds still while filtering.
    private(set) var activity: [Date] = []
    private(set) var activityPartial = false
    var query = ""
    @ObservationIgnored private var generation = 0
    /// hub answered `has_attachments` with 501; filter on the client until the next launch.
    @ObservationIgnored private var attachmentsLocal = false

    private(set) var thumbnails: [String: NSImage] = [:]
    private(set) var missing: Set<String> = []
    @ObservationIgnored private var fetching: Set<String> = []

    init(hub: HubModel) {
        self.hub = hub
    }

    /// hub's counts when it has them, otherwise counted from what is loaded.
    var tags: [MemosData.Tag] {
        if let t = hub.data.memos?.data?.tags, !t.isEmpty { return t.sorted { ($0.count ?? 0) > ($1.count ?? 0) } }
        var counts: [String: Int] = [:]
        for m in items { for t in m.tags ?? [] { counts[t, default: 0] += 1 } }
        return counts.map { MemosData.Tag(name: $0.key, count: $0.value) }.sorted { ($0.count ?? 0) > ($1.count ?? 0) }
    }

    var filtered: Bool { tag != nil || !query.isEmpty || filter != .all }

    func select(tag: String?) async {
        self.tag = tag == self.tag ? nil : tag
        await reload()
    }

    func select(filter: Filter) async {
        guard filter != self.filter else { return }
        self.filter = filter
        items = []
        await reload()
    }

    func reload() async {
        generation += 1
        let g = generation
        if items.isEmpty { phase = .loading }
        guard let api = hub.liveAPI else {
            apply(local(hub.data.memos?.data?.recent ?? []), source: .sample)
            return
        }
        do {
            let page = try await fetch(api, token: nil)
            guard g == generation else { return }
            if let page {
                archiveUnsupported = filter == .archived && !page.items.isEmpty && page.items.allSatisfy { $0.state == nil }
                items = keep(page.items)
                next = archiveUnsupported ? nil : page.nextPageToken
                source = .hub
                phase = .ready
            } else {
                apply(local(hub.data.memos?.data?.recent ?? []), source: .recent)
            }
        } catch {
            guard g == generation else { return }
            if items.isEmpty || source != .hub {
                apply(local(hub.data.memos?.data?.recent ?? []), source: .recent)
            }
            phase = .failed(Self.message(error))
        }
    }

    func loadMore() async {
        guard let api = hub.liveAPI, let token = next, !loadingMore, source == .hub else { return }
        loadingMore = true
        defer { loadingMore = false }
        let g = generation
        guard let page = try? await fetch(api, token: token), g == generation else { return }
        let known = Set(items.map(\.id))
        items += keep(page.items).filter { !known.contains($0.id) }
        next = page.nextPageToken
    }

    func create(_ content: String, visibility: String, attachments: [String] = []) async throws {
        try await hub.postMemo(content, visibility: visibility, attachments: attachments)
        await reload()
    }

    /// Uploads one file for the composer; it stays unlinked until the memo is sent.
    func upload(_ bytes: Data, filename: String, type: String) async throws -> HubAPI.UploadedAttachment {
        guard let api = hub.liveAPI else { throw HubModel.WriteError.demo }
        do {
            return try await api.uploadMemoAttachment(bytes, filename: filename, type: type)
        } catch {
            throw Failure(message: Self.message(error))
        }
    }

    /// Best effort: an unlinked upload left behind only takes space in Memos.
    func discard(attachment name: String) async {
        try? await hub.liveAPI?.deleteMemoAttachment(name: name)
    }

    func update(_ memo: Memo, content: String? = nil, visibility: String? = nil, pinned: Bool? = nil) async throws {
        guard let api = hub.liveAPI else { throw HubModel.WriteError.demo }
        do {
            let saved = try await api.updateMemo(id: memo.id, content: content, visibility: visibility, pinned: pinned)
            if let i = items.firstIndex(where: { $0.id == memo.id }) { items[i] = saved }
            if filter == .pinned, saved.pinned != true { items.removeAll { $0.id == memo.id } }
            hub.refresh()
        } catch {
            throw Failure(message: Self.message(error))
        }
    }

    func archive(_ memo: Memo) async throws {
        guard let api = hub.liveAPI else { throw HubModel.WriteError.demo }
        do {
            try await api.archiveMemo(id: memo.id)
            items.removeAll { $0.id == memo.id }
            hub.refresh()
        } catch {
            throw Failure(message: Self.message(error))
        }
    }

    func restore(_ memo: Memo) async throws {
        guard let api = hub.liveAPI else { throw HubModel.WriteError.demo }
        do {
            _ = try await api.updateMemo(id: memo.id, state: "NORMAL")
            items.removeAll { $0.id == memo.id }
            hub.refresh()
        } catch {
            throw Failure(message: Self.message(error))
        }
    }

    /// Image attachments through hub's read proxy; nil until loaded, and for good once hub says no.
    func thumbnail(_ memo: Memo, _ file: Memo.Attachment) -> NSImage? {
        let key = memo.id + "|" + file.name
        if let hit = thumbnails[key] { return hit }
        guard let api = hub.liveAPI, !missing.contains(key), !fetching.contains(key) else { return nil }
        fetching.insert(key)
        Task {
            defer { fetching.remove(key) }
            if let bytes = try? await api.memoAttachment(memo: memo.id, name: file.name), let image = NSImage(data: bytes) {
                thumbnails[key] = image
            } else {
                missing.insert(key)
            }
        }
        return nil
    }

    struct Failure: LocalizedError {
        var message: String
        var errorDescription: String? { message }
    }

    /// One page as the current view sees it. While hub answers `has_attachments` with 501, the attachments view walks
    /// the plain list instead, a few pages at a time, until it has enough matches to show.
    private func fetch(_ api: HubAPI, token: String?) async throws -> MemoPage? {
        let q = query.trimmingCharacters(in: .whitespaces), state = filter == .archived ? "ARCHIVED" : nil
        if filter == .attachments, !attachmentsLocal {
            do {
                return try await api.memos(pageToken: token, tag: tag, query: q, hasAttachments: true)
            } catch HubError.http(501) {
                attachmentsLocal = true
            }
        }
        guard filter == .attachments else {
            return try await api.memos(pageToken: token, tag: tag, query: q, pinned: filter == .pinned, state: state)
        }
        var token = token, found: [Memo] = []
        for _ in 0..<Self.scanPages {
            guard let page = try await api.memos(pageSize: 50, pageToken: token, tag: tag, query: q) else { return nil }
            found += page.items.filter { !($0.attachments ?? []).isEmpty }
            token = page.nextPageToken
            if token == nil || found.count >= Self.scanTarget { break }
        }
        return MemoPage(items: found, nextPageToken: token)
    }

    private static let scanPages = 8, scanTarget = 20

    /// The view filter again on the client, for hubs that ignore it.
    private func keep(_ list: [Memo]) -> [Memo] {
        switch filter {
        case .all: list.filter { $0.state != "ARCHIVED" }
        case .pinned: list.filter { $0.pinned == true }
        case .attachments: list.filter { !($0.attachments ?? []).isEmpty }
        case .archived: list.filter { $0.state == "ARCHIVED" }
        }
    }

    private func snapshot() {
        guard !filtered else { return }
        activity = items.compactMap(\.createdAt)
        activityPartial = next != nil
    }

    private func apply(_ list: [Memo], source: Source) {
        items = list
        next = nil
        archiveUnsupported = false
        self.source = source
        phase = .ready
    }

    private func local(_ list: [Memo]) -> [Memo] {
        let q = query.trimmingCharacters(in: .whitespaces)
        return keep(list.filter { m in
            (tag.map { t in (m.tags ?? []).contains(t) || m.content.contains("#" + t) } ?? true)
                && (q.isEmpty || m.content.localizedCaseInsensitiveContains(q))
        })
        .sorted { ($0.pinned ?? false) && !($1.pinned ?? false) }
    }

    private static func message(_ error: Error) -> String {
        switch error {
        case HubError.http(404), HubError.http(405): "hub 还没提供这个 Memos 接口，可以先在 Memos 里操作"
        case let e as HubError: e.message
        default: error.localizedDescription
        }
    }
}
