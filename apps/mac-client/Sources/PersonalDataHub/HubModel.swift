import AppKit
import Combine
import CryptoKit
import ServiceManagement

@MainActor
final class HubModel: ObservableObject {
    @Published var connection = Connection.load()
    @Published var sources: [SourceStatus] = []
    @Published var agents: [AgentStatus] = []
    @Published var checkpoint: CheckpointStatus?
    @Published var records: [RecordCard] = []
    @Published var kinds: [KindCount] = []
    @Published var total = 0
    @Published var nextOffset: Int?
    @Published var offset = 0
    @Published var source = ""
    @Published var kind = ""
    @Published var query = ""
    @Published var days = 0
    @Published var selectedID: String?
    @Published var detail: RecordDetail?
    @Published var busy = false
    @Published var loadingDetail = false
    @Published var downloading = false
    @Published var error: String?
    @Published var syncMessage: String?
    @Published var refreshedAt: Date?
    @Published var loginEnabled = SMAppService.mainApp.status == .enabled
    private var browseGeneration = 0
    private var detailGeneration = 0
    private var statusGeneration = 0
    private var timer: AnyCancellable?

    var api: HubAPI { HubAPI(connection) }
    var recordCount: Int { sources.reduce(0) { $0 + $1.count } }

    func start() {
        Task { await refreshStatus(); await browse(reset: true) }
        timer = Timer.publish(every: 60, on: .main, in: .common).autoconnect().sink { [weak self] _ in
            Task { await self?.refreshStatus() }
        }
    }

    func refreshStatus() async {
        statusGeneration += 1
        let generation = statusGeneration
        let client = api
        async let local = Task.detached { (LocalAgents.inspect(), LocalAgents.checkpoint()) }.value
        do {
            let values: [SourceStatus] = try await client.get("api/v1/sources")
            if generation == statusGeneration {
                sources = values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
                refreshedAt = Date()
            }
        } catch { if generation == statusGeneration { self.error = error.localizedDescription } }
        let localStatus = await local
        agents = localStatus.0; checkpoint = localStatus.1
    }

    func browse(reset: Bool) async {
        browseGeneration += 1
        let generation = browseGeneration
        if reset {
            offset = 0; records = []; selectedID = nil; detail = nil
            detailGeneration += 1; loadingDetail = false
        }
        busy = true; error = nil
        let client = api
        var params = [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: "50")]
        if !source.isEmpty { params.append(URLQueryItem(name: "source", value: source)) }
        if !kind.isEmpty { params.append(URLQueryItem(name: "kind", value: kind)) }
        if !query.isEmpty { params.append(URLQueryItem(name: "query", value: query)) }
        if days > 0 {
            let date = Calendar.current.date(byAdding: .day, value: -days, to: Date())!
            params.append(URLQueryItem(name: "start", value: ISO8601DateFormatter().string(from: date)))
        }
        do {
            async let page: RecordPage = client.get("api/v1/browse", query: params)
            async let types: [KindCount] = client.get("api/v1/kinds", query: source.isEmpty ? [] : [URLQueryItem(name: "source", value: source)])
            let (result, values) = try await (page, types)
            guard generation == browseGeneration else { return }
            records = result.records; total = result.total; nextOffset = result.next_offset; kinds = values
        } catch { if generation == browseGeneration { self.error = error.localizedDescription } }
        if generation == browseGeneration { busy = false }
    }

    func select(_ id: String?) async {
        detailGeneration += 1
        let generation = detailGeneration
        detail = nil
        guard let id = id else { loadingDetail = false; return }
        loadingDetail = true
        do {
            let result = try await api.record(id)
            if generation == detailGeneration { detail = result }
        } catch { if generation == detailGeneration { self.error = error.localizedDescription } }
        if generation == detailGeneration { loadingDetail = false }
    }

    func synchronize() async {
        do {
            try await Task.detached { try LocalAgents.synchronize() }.value
            syncMessage = "已启动电脑活动同步；已有任务继续执行，提交完成后可刷新查看。"
            await refreshStatus()
        } catch { self.error = error.localizedDescription }
    }

    func saveConnection(endpoint: String, token: String) async {
        do {
            let value = Connection(endpoint: endpoint)
            try value.save(token: token.isEmpty ? nil : token)
            connection = value
            await refreshStatus(); await browse(reset: true)
        } catch { self.error = error.localizedDescription }
    }

    func setLogin(_ enabled: Bool) {
        do {
            if enabled { try SMAppService.mainApp.register() }
            else { try SMAppService.mainApp.unregister() }
        } catch { self.error = "无法更新开机启动，请查看系统登录项设置。" }
        loginEnabled = SMAppService.mainApp.status == .enabled
    }

    func download(_ asset: ArchiveAsset) async {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = (asset.name as NSString).lastPathComponent
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        downloading = true
        defer { downloading = false }
        do {
            let temp = try await api.download(asset)
            defer { try? FileManager.default.removeItem(at: temp) }
            // 文件流式校验，不把录音等大附件读入内存。
            try await Task.detached {
                let handle = try FileHandle(forReadingFrom: temp)
                defer { try? handle.close() }
                var hash = SHA256(); var size: Int64 = 0
                while let block = try handle.read(upToCount: 1024 * 1024), !block.isEmpty {
                    hash.update(data: block); size += Int64(block.count)
                }
                let digest = hash.finalize().map { String(format: "%02x", $0) }.joined()
                guard digest == asset.id, size == asset.size else { throw HubError.integrity }
                let data = try Data(contentsOf: temp, options: .mappedIfSafe)
                try data.write(to: destination, options: .atomic)
            }.value
        } catch { self.error = error.localizedDescription }
    }

    func exportRecord() {
        guard let detail = detail else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "record-\(detail.id.prefix(12)).json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do { try detail.rawJSON.write(to: url, atomically: true, encoding: .utf8) }
        catch { self.error = "无法保存信息文件。" }
    }
}
