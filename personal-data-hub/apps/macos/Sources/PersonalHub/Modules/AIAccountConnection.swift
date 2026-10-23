import HubKit
import SwiftUI

struct AIAccountConnection: View {
    var initialProvider: String?
    var connected: (LocalTokenMonitor.Account, String) async -> Void
    @Environment(\.dismiss) private var dismiss
    @ViewState private var bridge: LocalTokenMonitor?
    @ViewState private var providers: [LocalTokenMonitor.Provider] = []
    @ViewState private var accounts: [LocalTokenMonitor.Account] = []
    @ViewState private var provider = "cursor"
    @ViewState private var method = "credential"
    @ViewState private var credential = ""
    @ViewState private var region = "global"
    @ViewState private var selected = ""
    @ViewState private var replace = false
    @ViewState private var flow: LocalTokenMonitor.Connection?
    @ViewState private var workspace = ""
    @ViewState private var error: String?
    @ViewState private var starting = false
    @ViewState private var requestID = UUID().uuidString
    @ViewState private var pollRevision = 0

    private var capability: LocalTokenMonitor.Provider? { providers.first { $0.id == provider } }
    private var existing: [LocalTokenMonitor.Account] { accounts.filter { $0.binding.provider == provider } }
    private var active: Bool { starting || flow.map { !$0.terminal } == true }
    private var needsReplacement: Bool { capability?.multiple == false && method != "discover" && !existing.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("连接 AI 账号").font(.headline)
            Text("由这台 Mac 的 Token Monitor 完成授权和额度采集。连接完成后，还需保存订阅资料。")
                .font(.caption).foregroundStyle(.secondary)
            if bridge == nil {
                Button("启动 Token Monitor") { LocalTokenMonitor.launch() }
                Button("重新检查") { Task { await load() } }
            } else {
                Picker("平台", selection: $provider) { ForEach(providers) { Text($0.name).tag($0.id) } }.disabled(active)
                Picker("接入方式", selection: $method) {
                    ForEach(capability?.methods ?? [], id: \.self) { Text(methodLabel($0)).tag($0) }
                }.disabled(active)
                if method == "credential" {
                    SecureField(provider == "zai" ? "API Key" : provider == "grok" ? "Bearer Token" : "Session Token / Cookie", text: $credential)
                        .textFieldStyle(.roundedBorder).disabled(active)
                    if provider == "zai" {
                        Picker("区域", selection: $region) { Text("全球").tag("global"); Text("中国大陆").tag("bigmodel-cn") }.disabled(active)
                    }
                }
                if method == "discover" {
                    Picker("本机账号", selection: $selected) {
                        Text(existing.isEmpty ? "刷新本机发现" : "请选择账号").tag("")
                        ForEach(existing) { Text($0.label).tag($0.binding.account) }
                    }.disabled(active)
                    if provider == "claude" { Text("仅使用本地桌面快照；旧读数及时间会保留。").font(.caption).foregroundStyle(.secondary) }
                }
                if needsReplacement {
                    Toggle("替换现有连接（原订阅台账保留）", isOn: $replace).disabled(active)
                }
            }
            if let flow {
                if active { ProgressView().controlSize(.small) }
                Text(flow.phase == "workspaceSelection" ? "选择授权工作区" : flow.status == "succeeded" ? "账号已连接" : "正在等待 Token Monitor 完成连接")
                    .font(.caption).foregroundStyle(.secondary)
                if let code = flow.userCode { Text("授权码：" + code).monospaced().textSelection(.enabled) }
                if let value = flow.loginUrl, let url = URL(string: value), url.scheme == "https" { Link("在浏览器完成授权", destination: url) }
                if let choices = flow.workspaces, !choices.isEmpty {
                    Picker("工作区", selection: $workspace) {
                        Text("请选择").tag("")
                        ForEach(choices) { Text($0.label).tag($0.id) }
                    }
                    Button("使用此工作区") {
                        Task {
                            do { _ = try await bridge?.select(flow.id, workspace: workspace) }
                            catch { self.error = error.localizedDescription }
                        }
                    }.disabled(workspace.isEmpty)
                }
            }
            if let error { Text(error).font(.caption).foregroundStyle(.red).textSelection(.enabled) }
            if error != nil, let flow, !flow.terminal {
                Button("重新检查连接进度") { error = nil; pollRevision += 1 }
            }
            HStack {
                Spacer()
                Button(active ? "取消连接" : "关闭") { Task { await cancel() } }
                Button("连接") { Task { await start() } }
                    .disabled(bridge == nil || active || (method == "credential" && credential.isEmpty) || (needsReplacement && !replace)
                              || (method == "discover" && existing.count > 1 && selected.isEmpty))
            }
        }
        .padding(22).frame(width: 490)
        .task { await load() }
        .task(id: (flow?.id ?? "") + ":\(pollRevision)") {
            guard let id = flow?.id, let bridge else { return }
            do {
                while !Task.isCancelled {
                    let next = try await bridge.status(id)
                    flow = next
                    if next.status == "succeeded", let account = next.account {
                        credential = ""
                        await connected(account, next.syncStatus ?? "pending")
                        dismiss(); return
                    }
                    if next.terminal { error = LocalTokenMonitor.Problem(code: next.error ?? "connection_failed").localizedDescription; return }
                    try await Task.sleep(for: .seconds(1))
                }
            } catch is CancellationError {} catch { self.error = error.localizedDescription }
        }
        .onChange(of: provider) { _, _ in
            method = capability?.methods.first ?? "discover"; selected = ""; credential = ""; replace = false; flow = nil; error = nil; requestID = UUID().uuidString
        }
        .onChange(of: credential) { _, _ in if !active { requestID = UUID().uuidString } }
        .onChange(of: method) { _, _ in if !active { requestID = UUID().uuidString; flow = nil; error = nil } }
        .onChange(of: region) { _, _ in if !active { requestID = UUID().uuidString } }
        .onChange(of: selected) { _, _ in if !active { requestID = UUID().uuidString } }
        .onChange(of: replace) { _, _ in if !active { requestID = UUID().uuidString } }
        .onDisappear {
            credential = ""
            if let flow, !flow.terminal, let bridge { Task { _ = try? await bridge.cancel(flow.id) } }
        }
    }

    private func methodLabel(_ value: String) -> String {
        ["oauth": "浏览器授权", "device": "设备码授权", "credential": "填写凭据", "discover": "选择本机已有账号"][value] ?? value
    }
    private func load() async {
        do {
            let service = try LocalTokenMonitor()
            let list = try await service.capabilities()
            let known = try await service.accounts()
            providers = list; accounts = known; bridge = service
            if let initialProvider, list.contains(where: { $0.id == initialProvider }) { provider = initialProvider }
            method = list.first { $0.id == provider }?.methods.first ?? "discover"
            error = nil
        } catch { bridge = nil; self.error = error.localizedDescription }
    }
    private func start() async {
        guard let bridge else { return }
        if flow?.terminal == true { requestID = UUID().uuidString; flow = nil }
        starting = true; error = nil
        defer { starting = false }
        var body: [String: Any] = ["provider": provider, "method": method, "requestId": requestID]
        if method == "credential" { body["credential"] = credential; if provider == "zai" { body["region"] = region } }
        if method == "discover", !selected.isEmpty { body["account"] = selected }
        if replace { body["replace"] = true }
        do { flow = try await bridge.connect(body) }
        catch { self.error = error.localizedDescription }
    }
    private func cancel() async {
        if let flow, !flow.terminal, let bridge {
            do { _ = try await bridge.cancel(flow.id) }
            catch { self.error = error.localizedDescription; return }
        }
        dismiss()
    }
}
