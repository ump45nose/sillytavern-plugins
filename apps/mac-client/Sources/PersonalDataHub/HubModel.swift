import AppKit
import Combine
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
    @Published var detailError: String?
    @Published var statusLoading = false
    @Published var downloading = false
    @Published var error: String?
    @Published var syncMessage: String?
    @Published var collectionMessage: String?
    @Published var collectionNeedsAuthorization = false
    @Published var collectionBusy = false
    @Published var networkCollection: NetworkCollectionStatus?
    @Published var networkBusy = false
    @Published var networkSource = ""
    @Published var networkSummary: NetworkSummary?
    @Published var networkLoading = false
    @Published var networkResultKey: String?
    var networkGeneration = 0
    @Published var refreshedAt: Date?
    @Published var loginEnabled = SMAppService.mainApp.status == .enabled
    @Published var loginNeedsApproval = SMAppService.mainApp.status == .requiresApproval
    @Published var preferences = UIPreferences.load()
    @Published var section = "overview"
    @Published var overviewMode = "today"
    @Published var displayDate = Date()
    @Published var trendDays = 7
    @Published var dashboard: Dashboard?
    @Published var trends: TrendPage?
    @Published var timeline: [DisplayCard] = []
    @Published var timelineCursor: String?
    @Published var timelineDomain = "social,activity,recordings,reports,mail,git,notes"
    @Published var displayLoading = false
    @Published var displayResultKey: String?
    @Published var timelineLoading = false
    @Published var reportMode = "daily"
    @Published var documentSource = ""
    @Published var readingSelection: DocumentSelection?
    @Published var processingStatus: ProcessingStatus?
    @Published var processingError: String?
    let documents = DocumentListModel()
    @Published var googleLoading = false
    @Published var showingDetail = false
    @Published var taskEditor = false
    @Published var eventEditor = false
    @Published var quickSnapshot: GoogleSnapshot?
    @Published var googleSnapshot: GoogleSnapshot?
    @Published var googleMessage: String?
    @Published var googleBusy = false
    @Published var googleAuthorizing = false
    @Published var calendarWeek = false
    @Published var editingTask: GoogleTask?
    @Published var editingEvent: GoogleEvent?
    @Published var hotkeyError: String?
    let google = GoogleClient()
    var displayGeneration = 0
    var timelineGeneration = 0
    var googleGeneration = 0
    private var processingGeneration = 0
    private var browseGeneration = 0
    private var detailGeneration = 0
    private var statusGeneration = 0
    private var timer: AnyCancellable?
    private var documentsSubscription: AnyCancellable?

    init() {
        documentsSubscription = documents.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
    }

    var api: HubAPI { HubAPI(connection) }
    var recordCount: Int { sources.reduce(0) { $0 + $1.count } }

    var documentFilter: DocumentFilter {
        if section == "notes" { return DocumentFilter(source: "memos", variant: "note", query: query) }
        if section == "reports" { return DocumentFilter(variant: reportMode == "execution" ? "execution_log" : "daily_review", query: query) }
        return DocumentFilter(source: documentSource, query: query)
    }
    func loadDocuments(reset: Bool = true) async {
        await documents.load(api: api, filter: documentFilter, reset: reset)
    }
    func refreshProcessing() async {
        processingGeneration += 1; let ticket = processingGeneration
        do {
            let status: ProcessingStatus = try await api.get("api/v1/processing/status")
            guard ticket == processingGeneration, !Task.isCancelled else { return }
            processingStatus = status; processingError = nil
        } catch {
            if ticket == processingGeneration, !Task.isCancelled { processingError = error.localizedDescription }
        }
    }

    func start() {
        Task { await refreshStatus() }
        timer = Timer.publish(every: 60, on: .main, in: .common).autoconnect().sink { [weak self] _ in
            Task { await self?.refreshStatus(); await self?.loadCurrentPage() }
        }
    }

    func refreshStatus() async {
        statusGeneration += 1
        let generation = statusGeneration
        statusLoading = true
        defer { if generation == statusGeneration { statusLoading = false } }
        let client = api
        async let local = Task.detached { (LocalAgents.inspect(), LocalAgents.checkpoint(), LocalAgents.networkStatus()) }.value
        do {
            let values: [SourceStatus] = try await client.get("api/v1/sources")
            if generation == statusGeneration {
                sources = values.sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
                refreshedAt = Date()
            }
        } catch { if generation == statusGeneration && !Task.isCancelled { self.error = error.localizedDescription } }
        let localStatus = await local
        if generation == statusGeneration { agents = localStatus.0; checkpoint = localStatus.1; networkCollection = localStatus.2 }
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
        let parameters = params
        let kindParameters = source.isEmpty ? [] : [URLQueryItem(name: "source", value: source)]
        do {
            async let page: RecordPage = client.get("api/v1/browse", query: parameters)
            async let types: [KindCount] = client.get("api/v1/kinds", query: kindParameters)
            let (result, values) = try await (page, types)
            guard generation == browseGeneration else { return }
            records = result.records; total = result.total; nextOffset = result.next_offset; kinds = values
        } catch { if generation == browseGeneration { self.error = error.localizedDescription } }
        if generation == browseGeneration { busy = false }
    }

    func select(_ id: String?) async {
        detailGeneration += 1
        let generation = detailGeneration
        selectedID = id; detail = nil; detailError = nil
        guard let id = id else { loadingDetail = false; return }
        loadingDetail = true
        do {
            let result = try await api.record(id)
            if generation == detailGeneration { detail = result }
        } catch { if generation == detailGeneration { detailError = error.localizedDescription } }
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

    func configureCollection() async {
        guard !collectionBusy else { return }
        collectionBusy = true
        defer { collectionBusy = false }
        do {
            try await Task.detached { try LocalAgents.prepareBundledIfNeeded() }.value
            collectionNeedsAuthorization = false
            collectionMessage = "微信和电脑活动采集已启用，后台自动同步。"
            await refreshStatus()
        } catch CollectionFailure.authorizationRequired {
            collectionNeedsAuthorization = true
            collectionMessage = CollectionFailure.authorizationRequired.localizedDescription
        } catch {
            collectionNeedsAuthorization = false
            collectionMessage = error.localizedDescription
        }
    }

    func setNetworkCollection(_ enabled: Bool) async {
        guard !networkBusy else { return }; networkBusy = true
        defer { networkBusy = false }
        do {
            try await Task.detached { try LocalAgents.configureNetwork(enabled: enabled) }.value
            await refreshStatus()
        } catch { self.error = error.localizedDescription }
    }

    func setLogin(_ enabled: Bool) {
        do {
            try LoginItem.setEnabled(enabled)
        } catch { self.error = "无法更新开机启动，请查看系统登录项设置。" }
        loginEnabled = SMAppService.mainApp.status == .enabled
        loginNeedsApproval = SMAppService.mainApp.status == .requiresApproval
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
                try asset.verifyFile(temp)
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
