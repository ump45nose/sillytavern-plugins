import Foundation
import HubKit
import Observation

/// The Memos page's timeline: hub's paged list with tag and text filters. Until hub ships the list
/// endpoint it shows the module's recent memos, filtered locally.
@MainActor @Observable
final class MemosStore {
    enum Source { case hub, recent, sample }
    enum Phase: Equatable { case idle, loading, ready, failed(String) }

    typealias Memo = MemosData.Memo

    private let hub: HubModel
    private(set) var items: [Memo] = []
    private(set) var next: String?
    private(set) var source: Source = .hub
    private(set) var phase: Phase = .idle
    private(set) var loadingMore = false
    private(set) var tag: String?
    var query = ""
    @ObservationIgnored private var generation = 0

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

    func select(tag: String?) async {
        self.tag = tag == self.tag ? nil : tag
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
            let page = try await api.memos(tag: tag, query: query.trimmingCharacters(in: .whitespaces))
            guard g == generation else { return }
            if let page {
                items = page.items
                next = page.nextPageToken
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
        guard let page = try? await api.memos(pageToken: token, tag: tag, query: query), g == generation else { return }
        let known = Set(items.map(\.id))
        items += page.items.filter { !known.contains($0.id) }
        next = page.nextPageToken
    }

    func create(_ content: String, visibility: String) async throws {
        try await hub.postMemo(content, visibility: visibility)
        await reload()
    }

    func update(_ memo: Memo, content: String? = nil, visibility: String? = nil, pinned: Bool? = nil) async throws {
        guard let api = hub.liveAPI else { throw HubModel.WriteError.demo }
        do {
            let saved = try await api.updateMemo(id: memo.id, content: content, visibility: visibility, pinned: pinned)
            if let i = items.firstIndex(where: { $0.id == memo.id }) { items[i] = saved }
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

    struct Failure: LocalizedError {
        var message: String
        var errorDescription: String? { message }
    }

    private func apply(_ list: [Memo], source: Source) {
        items = list
        next = nil
        self.source = source
        phase = .ready
    }

    private func local(_ list: [Memo]) -> [Memo] {
        let q = query.trimmingCharacters(in: .whitespaces)
        return list.filter { m in
            (tag.map { t in (m.tags ?? []).contains(t) || m.content.contains("#" + t) } ?? true)
                && (q.isEmpty || m.content.localizedCaseInsensitiveContains(q))
        }
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
