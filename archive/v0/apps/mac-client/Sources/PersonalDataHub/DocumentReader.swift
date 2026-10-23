import AppKit
import Combine

@MainActor final class DocumentListModel: ObservableObject {
    @Published private(set) var items: [DocumentContent] = []
    @Published private(set) var cursor: String?
    @Published private(set) var loading = false
    @Published private(set) var error: String?
    private var generation = 0
    private var filter: DocumentFilter?

    func load(api: HubAPI, filter requested: DocumentFilter, reset: Bool = true) async {
        if !reset { guard !loading, filter == requested, cursor != nil else { return } }
        generation += 1; let ticket = generation
        let next = reset ? nil : cursor
        if reset { items = []; cursor = nil; filter = requested }
        loading = true; error = nil
        defer { if ticket == generation { loading = false } }
        do {
            let page: DocumentPage = try await api.get("api/v1/contents", query: requested.parameters(cursor: next))
            guard ticket == generation, !Task.isCancelled else { return }
            guard page.schema_version == 1 else { error = "当前客户端暂不支持此阅读列表格式。"; return }
            var seen = Set(items.map(\.id))
            items += page.items.filter { seen.insert($0.id).inserted }
            cursor = page.next_cursor
        } catch {
            if ticket == generation, !Task.isCancelled { self.error = error.localizedDescription }
        }
    }
    func remove(_ id: String) { items.removeAll { $0.id == id } }
}

@MainActor final class DocumentReader: ObservableObject {
    @Published private(set) var header: DocumentContent?
    @Published private(set) var blocks: [DocumentBlock] = []
    @Published private(set) var nextAfter: Int?
    @Published private(set) var evidence: DocumentEvidence?
    @Published private(set) var loading = false
    @Published private(set) var checking = false
    @Published private(set) var evidenceLoading = false
    @Published private(set) var saving = false
    @Published private(set) var seeking = false
    @Published private(set) var matchResolved = false
    @Published private(set) var matchOffset: Int?
    @Published private(set) var removed = false
    @Published private(set) var error: String?
    @Published private(set) var verificationError: String?
    @Published private(set) var evidenceError: String?
    @Published private(set) var message: String?
    private var api: HubAPI?
    private var selectedID: String?
    private var epoch = 0
    private var checkGeneration = 0
    private var match: DocumentMatch?
    private var searchRevision = 0
    private var searchQuery = ""
    private var seekCancelled = false
    var onInvalidated: ((String, Bool) -> Void)?
    var body: String { blocks.map(\.text).joined() }
    var complete: Bool { header?.readable == true && nextAfter == nil && !loading && error == nil }

    func open(_ selection: DocumentSelection, api: HubAPI) async {
        self.api = api; selectedID = selection.id; match = selection.item.match; searchRevision = selection.item.revision
        searchQuery = selection.query; seekCancelled = false
        clear(); let ticket = epoch
        await loadHeader(ticket: ticket)
        if ticket == epoch, match != nil { await locateMatch() }
    }
    // All volatile derivatives are discarded together before a new version is accepted.
    private func clear() {
        epoch += 1; checkGeneration += 1
        header = nil; blocks = []; nextAfter = nil; evidence = nil
        loading = false; checking = false; evidenceLoading = false; seeking = false
        removed = false; error = nil; evidenceError = nil; verificationError = nil; matchResolved = false
        matchOffset = nil; message = nil
    }
    func close() { clear(); selectedID = nil; api = nil }
    func reload() async {
        match = nil; clear(); await loadHeader(ticket: epoch)
    }
    private func install(_ result: DocumentContent) {
        header = result; nextAfter = result.readable ? -1 : nil
    }
    private func loadHeader(ticket: Int, recover: Bool = true) async {
        guard let api, let id = selectedID else { return }
        loading = true
        do {
            let result: DocumentContent = try await api.get("api/v1/contents/" + id)
            guard ticket == epoch, !Task.isCancelled else { return }
            guard result.id == id else { throw HubError.response }
            if match != nil, result.revision != searchRevision {
                match = nil; message = "文档已更新，搜索位置已失效，请重新搜索。"
            }
            install(result); loading = false
            if result.readable { await loadNext(recover: recover) }
        } catch {
            guard ticket == epoch, !Task.isCancelled else { return }
            loading = false; await handle(error, recover: recover)
        }
    }
    func loadNext(recover: Bool = true) async {
        guard !loading, let header, header.readable, let after = nextAfter, let api else { return }
        let ticket = epoch; loading = true; error = nil
        defer { if ticket == epoch { loading = false } }
        do {
            let page: DocumentBlocks = try await api.get("api/v1/contents/" + header.id + "/blocks", query: [
                URLQueryItem(name: "revision", value: String(header.revision)),
                URLQueryItem(name: "after", value: String(after)), URLQueryItem(name: "limit", value: "50")])
            guard ticket == epoch, !Task.isCancelled else { return }
            guard page.id == header.id, page.revision == header.revision else { throw HubError.contentChanged }
            var ordinal = after
            for block in page.blocks {
                guard block.ordinal == ordinal + 1 else { throw HubError.response }
                guard block.type == "markdown" else {
                    blocks = []; nextAfter = nil; evidence = nil
                    error = "当前客户端暂不支持此正文格式。"; return
                }
                ordinal = block.ordinal
            }
            if let next = page.next_after { guard next > after, next == ordinal else { throw HubError.response } }
            blocks += page.blocks; nextAfter = page.next_after
        } catch {
            guard ticket == epoch, !Task.isCancelled else { return }
            loading = false; await handle(error, recover: recover)
        }
    }
    private func handle(_ failure: Error, recover: Bool = true) async {
        switch failure {
        case HubError.contentRemoved:
            let id = selectedID; clear(); removed = true; message = "这份内容已被删除。"
            if let id { onInvalidated?(id, true) }
        case HubError.contentChanged:
            let id = selectedID; match = nil; clear(); message = "原件已更新，已清理旧正文并重新读取。"
            if let id { onInvalidated?(id, false) }
            if recover { await loadHeader(ticket: epoch, recover: false) }
            else { error = "正文仍在更新，请稍后刷新。" }
        default: error = failure.localizedDescription
        }
    }
    func verifyCurrent(force: Bool = false) async {
        guard let api, let id = selectedID, header != nil, (!checking || force) else { return }
        checkGeneration += 1; let check = checkGeneration; let ticket = epoch
        checking = true
        defer { if check == checkGeneration { checking = false } }
        do {
            let current: DocumentContent = try await api.get("api/v1/contents/" + id)
            guard ticket == epoch, check == checkGeneration, !Task.isCancelled else { return }
            guard current.id == id else { throw HubError.response }
            verificationError = nil
            if current.revision != header?.revision || current.processing.state != header?.processing.state || current.readable != header?.readable {
                match = nil; clear(); message = "内容状态已改变，已清理旧阅读版本。"
                onInvalidated?(id, false); install(current)
                if current.readable { await loadNext() }
            } else { header = current }
        } catch {
            guard ticket == epoch, check == checkGeneration, !Task.isCancelled else { return }
            if case HubError.contentRemoved = error { await handle(error) }
            else { verificationError = "尚未完成最新状态核对：" + error.localizedDescription }
        }
    }
    private func locateMatch() async {
        guard let match else { return }
        let ticket = epoch; seeking = true
        defer { if ticket == epoch { seeking = false } }
        while ticket == epoch, !Task.isCancelled, !seekCancelled, header?.readable == true, error == nil {
            // Search text may overlap the next transport block at a Unicode boundary.
            let reached = (blocks.last?.ordinal ?? -1) >= match.ordinal
            if reached, !searchQuery.isEmpty {
                let text = body
                let offset = blocks.filter { $0.ordinal < match.ordinal }.reduce(0) { $0 + $1.text.unicodeScalars.count }
                let start = text.unicodeScalars.index(text.unicodeScalars.startIndex, offsetBy: offset)
                if let range = text.range(of: searchQuery, options: .caseInsensitive, range: start..<text.endIndex) {
                    matchOffset = text.unicodeScalars.distance(from: text.unicodeScalars.startIndex, to: range.lowerBound)
                    matchResolved = true; return
                }
            }
            guard nextAfter != nil else { message = "未能在当前正文中定位命中，请刷新搜索结果。"; return }
            await loadNext()
        }
    }
    func cancelSearch() {
        seekCancelled = true; epoch += 1; checkGeneration += 1
        loading = false; seeking = false; checking = false; evidenceLoading = false
        message = "已停止定位，可继续逐页阅读。"
    }
    func loadEvidence() async {
        guard !evidenceLoading, let header, header.revision > 0, let api else { return }
        let ticket = epoch; evidenceLoading = true; evidenceError = nil
        defer { if ticket == epoch { evidenceLoading = false } }
        do {
            let result: DocumentEvidence = try await api.get("api/v1/contents/" + header.id + "/evidence")
            guard ticket == epoch, !Task.isCancelled else { return }
            guard result.id == header.id, result.revision == header.revision else { throw HubError.contentChanged }
            evidence = result
            if result.inputs.contains(where: { !$0.current_matches }) { await verifyCurrent() }
        } catch {
            guard ticket == epoch, !Task.isCancelled else { return }
            switch error {
            case HubError.contentChanged, HubError.contentRemoved: await handle(error)
            default: evidenceError = error.localizedDescription
            }
        }
    }
    func save(_ asset: ArchiveAsset) async {
        guard !saving, let api else { return }
        saving = true; defer { saving = false }
        await verifyCurrent(force: true)
        guard verificationError == nil, let header, header.readable, header.assets?.contains(where: { $0.id == asset.id }) == true else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = (asset.name as NSString).lastPathComponent
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        let ticket = epoch
        do {
            let file = try await api.download(asset)
            defer { try? FileManager.default.removeItem(at: file) }
            try await Task.detached { try asset.verifyFile(file) }.value
            await verifyCurrent(force: true)
            guard ticket == epoch, verificationError == nil, !removed else { return }
            try Data(contentsOf: file, options: .mappedIfSafe).write(to: destination, options: .atomic)
            message = "附件已保存，SHA-256 校验通过。"
        } catch {
            guard ticket == epoch else { return }
            await verifyCurrent()
            if !removed { self.error = error.localizedDescription }
        }
    }
}
