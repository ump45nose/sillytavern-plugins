import Foundation
import HubKit
import Observation

enum ReviewTarget: Hashable {
    case session(String)
    case latest(ReviewKind)
    case stage
}

/// State behind the review window: session lists, loaded sessions and unsent drafts.
@MainActor
@Observable
final class ReviewDesk {
    enum Selection: Hashable { case session(String), stage }

    var selection: Selection = .stage
    private(set) var lists: [ReviewKind: [ReviewSummary]] = [:]
    private(set) var sessions: [String: ReviewSession] = [:]
    private(set) var listError: String?
    private(set) var loadErrors: [String: String] = [:]
    private(set) var drafts: Drafts

    @ObservationIgnored private let hub: HubModel
    @ObservationIgnored private var saving: Task<Void, Never>?

    init(hub: HubModel) {
        self.hub = hub
        drafts = Drafts.load()
    }

    var goals: GoalsData? { hub.data.goals?.data }
    var now: Date { hub.clock() }

    func open(_ target: ReviewTarget) {
        switch target {
        case .session(let id): selection = .session(id)
        case .stage: selection = .stage
        case .latest(let kind):
            let latest = kind == .daily ? goals?.reviews?.daily : goals?.reviews?.weekly
            if let id = latest?.id ?? lists[kind]?.first?.id { selection = .session(id) }
        }
        Task { await reload() }
    }

    func reload() async {
        let now = self.now
        do {
            for kind in ReviewKind.allCases {
                lists[kind] = try await hub.review(demo: { ReviewSample.sessions(kind, now: now) }, live: { try await $0.reviewSessions(kind: kind) })
            }
            listError = nil
        } catch {
            listError = Self.message(error)
        }
        if case .session(let id) = selection { await load(id, force: true) }
    }

    func load(_ id: String, force: Bool = false) async {
        guard force || sessions[id] == nil else { return }
        let now = self.now
        do {
            sessions[id] = try await hub.review(demo: { ReviewSample.session(id: id, now: now) }, live: { try await $0.reviewSession(id: id) })
            loadErrors[id] = nil
        } catch {
            loadErrors[id] = Self.message(error)
        }
    }

    // MARK: Writes

    func preview(_ session: ReviewSession, content: String) async throws -> String {
        try await hub.review(demo: { ReviewSample.preview(content) }, live: { try await $0.previewReview(id: session.id, content: content) })
    }

    /// Returns true when the session had already been confirmed elsewhere (Telegram).
    func finalize(_ session: ReviewSession, content: String) async throws -> Bool {
        let done = try await hub.review(demo: { throw HubModel.WriteError.demo }, live: { try await $0.finalizeReview(id: session.id, content: content) })
        drafts.forms[session.id] = nil
        drafts.texts[session.id] = nil
        persist()
        await afterWrite()
        await load(session.id, force: true)
        return done.already == true
    }

    func stage(_ dryRun: Bool, _ write: @escaping (HubAPI) async throws -> StageResult, demo: @escaping () -> StageResult) async throws -> StageResult {
        let result = try await hub.review(demo: { if dryRun { return demo() } else { throw HubModel.WriteError.demo } }, live: write)
        if !dryRun { await afterWrite() }
        return result
    }

    private func afterWrite() async {
        hub.refresh()
        await reload()
    }

    // MARK: Drafts

    struct Drafts: Codable {
        var forms: [String: ReviewForm] = [:]
        var texts: [String: String] = [:]

        static let file = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/PersonalHub/review-drafts.json")

        static func load() -> Drafts {
            (try? Data(contentsOf: file)).flatMap { try? JSONDecoder().decode(Drafts.self, from: $0) } ?? Drafts()
        }
    }

    func setForm(_ form: ReviewForm, for id: String) {
        drafts.forms[id] = form.isEmpty ? nil : form
        persistSoon()
    }

    func setText(_ text: String, for id: String, template: String) {
        drafts.texts[id] = text == template || text.isEmpty ? nil : text
        persistSoon()
    }

    private func persistSoon() {
        saving?.cancel()
        saving = Task {
            try? await Task.sleep(for: .milliseconds(400))
            guard !Task.isCancelled else { return }
            persist()
        }
    }

    /// Unsent diary text is private: 0600, next to the hub cache.
    private func persist() {
        let file = Drafts.file
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try JSONEncoder().encode(drafts).write(to: file, options: [.atomic])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        } catch {
            NSLog("Personal Hub: review draft save failed")
        }
    }

    static func message(_ error: Error) -> String {
        if let e = error as? HubError { return e == .http(404) ? "hub 还没开放复盘接口" : e.message }
        if case .hub(let e) = error as? HubModel.WriteError { return message(e) }
        return (error as? LocalizedError)?.errorDescription ?? "没有完成，请重试。"
    }

    static func field(_ error: Error) -> String? {
        if case .rejected(_, let field) = error as? HubError { return field }
        if case .hub(.rejected(_, let field)) = error as? HubModel.WriteError { return field }
        return nil
    }
}
