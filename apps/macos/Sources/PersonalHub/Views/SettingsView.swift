import AppKit
import HubKit
import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @Environment(AppState.self) private var state
    @ViewState private var tab: Int

    init(tab: Int = 0) {
        _tab = ViewState(initialValue: tab)
    }

    var body: some View {
        VStack(spacing: 0) {
            Segmented(options: [(0, "通用"), (1, "快捷键"), (2, "账户"), (3, "数据"), (4, "关于")], selection: $tab)
                .padding(.top, 18)
            Group {
                switch tab {
                case 0: GeneralSettings()
                case 1: ShortcutSettings()
                case 2: AccountSettings()
                case 3: DataSettings()
                default: AboutSettings()
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(width: 560, height: 440)
        .background(Palette.bg)
        .preferredColorScheme(.light)
    }
}

private struct SettingRow<Content: View>: View {
    var title: String
    var note: String?
    @ViewBuilder var content: Content

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(Typo.sans(13))
                if let note { Text(note).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
            }
            Spacer()
            content
        }
        .padding(.vertical, 10)
        .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }
    }
}

private struct GeneralSettings: View {
    @Environment(AppState.self) private var state
    @ViewState private var launchAtLogin = SMAppService.mainApp.status == .enabled
    @ViewState private var loginError: String?
    @ViewState private var confirmReset = false

    var body: some View {
        @Bindable var state = state
        VStack(alignment: .leading, spacing: 0) {
            SettingRow(title: "登录时启动", note: loginError) {
                Toggle("", isOn: $launchAtLogin).toggleStyle(.switch).labelsHidden()
                    .onChange(of: launchAtLogin) { _, on in
                        do {
                            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                            loginError = nil
                        } catch {
                            loginError = "需要安装到「应用程序」后才能开启"
                            launchAtLogin = SMAppService.mainApp.status == .enabled
                        }
                    }
            }
            SettingRow(title: "Memos 地址", note: "Memos 页面直接嵌入此地址") {
                TextField("http://nas:5230", text: $state.memosURL).textFieldStyle(.roundedBorder).frame(width: 240)
            }
            SettingRow(title: "布局", note: state.hub.mode == .hub ? "页面与模块布局经 hub 在设备间同步" : "连接 hub 后在设备间同步") {
                Button("全部恢复默认…") { confirmReset = true }
            }
        }
        .alert("恢复默认布局？", isPresented: $confirmReset) {
            Button("恢复", role: .destructive) { state.resetLayout() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("所有页面回到默认模块，自定义页面会被删除。")
        }
    }
}

private struct ShortcutSettings: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(HotKeyCenter.Action.allCases, id: \.rawValue) { action in
                SettingRow(title: action.title, note: "在任何应用中呼出") { ShortcutRecorder(action: action) }
            }
            Text("快捷键需要包含 ⌃、⌥ 或 ⌘ 之一；与其他应用冲突时会保留原快捷键。")
                .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.top, 12)
        }
    }
}

private struct ShortcutRecorder: View {
    var action: HotKeyCenter.Action
    @ViewState private var current: Shortcut
    @ViewState private var recording = false
    @ViewState private var failed = false
    @ViewState private var monitor: Any?

    init(action: HotKeyCenter.Action) {
        self.action = action
        _current = ViewState(initialValue: HotKeyCenter.shared.shortcut(for: action))
    }

    var body: some View {
        Button { recording ? stop() : start() } label: {
            Text(recording ? "按下新的快捷键…" : current.display)
                .font(Typo.sans(12.5, .medium)).monospacedDigit()
                .foregroundStyle(failed ? Tone.rose.color : recording ? Tone.clay.color : Palette.ink)
                .frame(width: 150, height: 28)
                .background(RoundedRectangle(cornerRadius: 8).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(recording ? Tone.clay.color : Palette.line))
        }
        .buttonStyle(.plain)
        .onDisappear(perform: stop)
    }

    private func start() {
        recording = true
        failed = false
        HotKeyCenter.shared.suspend()
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 { stop(); return nil }
            guard let s = Shortcut(event: event) else { return nil }
            failed = !HotKeyCenter.shared.set(s, for: action)
            current = HotKeyCenter.shared.shortcut(for: action)
            stop()
            return nil
        }
    }

    private func stop() {
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
        if recording { HotKeyCenter.shared.resume() }
        recording = false
    }
}

private struct AccountSettings: View {
    @Environment(AppState.self) private var state
    @ViewState private var confirmDisconnect = false

    var body: some View {
        let agenda = state.agenda
        VStack(alignment: .leading, spacing: 0) {
            SettingRow(title: "Google 日历与任务", note: googleNote) { googleControl }
            if case .failed(let message) = agenda.connect {
                Text(message).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).padding(.top, 8)
            }
            if agenda.mode == .google {
                SettingRow(title: "同步", note: syncNote) {
                    Button(state.syncing ? "同步中…" : "立即同步") { agenda.refresh() }.disabled(state.syncing)
                }
            }
            SettingRow(title: "Personal Hub 后端", note: state.hub.mode == .hub ? state.hub.baseURL?.host() : "健康、账单等模块的数据来源，在「数据」里连接") {
                Chip(text: state.hub.mode == .hub ? "已连接" : "未连接", tone: state.hub.mode == .hub ? .olive : .ochre)
            }
        }
        .alert("断开 Google 账户？", isPresented: $confirmDisconnect) {
            Button("断开", role: .destructive) { agenda.disconnectGoogle() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会删除本机保存的授权并清空本地缓存；尚未同步的 \(agenda.pendingCount) 项改动会丢失。Google 上的数据不受影响。")
        }
    }

    private var googleNote: String {
        let agenda = state.agenda
        switch (agenda.mode, agenda.connect) {
        case (_, .authorizing): return "请在浏览器里完成授权…"
        case (.google, _) where agenda.needsReauthorization: return (agenda.account ?? "已连接") + " · 需重新授权以编辑日程和读取共享日历"
        case (.google, _): return agenda.account ?? "已连接"
        default: return "在浏览器中登录授权，令牌由凭据助手保存在钥匙串"
        }
    }

    @ViewBuilder private var googleControl: some View {
        let agenda = state.agenda
        if agenda.connect == .authorizing {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Button("取消") { agenda.cancelConnect() }
            }
        } else if agenda.mode == .google {
            HStack(spacing: 8) {
                if agenda.status == .needsReconnect || agenda.needsReauthorization {
                    Button(agenda.needsReauthorization ? "重新授权" : "重新连接") { agenda.connectGoogle() }.keyboardShortcut(.defaultAction)
                }
                Button("断开…") { confirmDisconnect = true }
            }
        } else {
            Button("连接 Google") { agenda.connectGoogle() }.keyboardShortcut(.defaultAction)
        }
    }

    private var syncNote: String {
        let agenda = state.agenda
        var parts = [agenda.lastSync.map { "上次同步 " + Agenda.relativeDay($0, now: agenda.now) + " " + Agenda.clock($0) } ?? "尚未同步"]
        if agenda.pendingCount > 0 { parts.append("\(agenda.pendingCount) 项待上传") }
        if !agenda.failures.isEmpty { parts.append("\(agenda.failures.count) 项未能同步") }
        switch agenda.status {
        case .offline: parts.append("离线")
        case .needsReconnect: parts.append("授权失效，请断开后重新连接")
        case .failed(let reason): parts.append(reason)
        default: break
        }
        return parts.joined(separator: " · ")
    }
}

private struct DataSettings: View {
    @Environment(AppState.self) private var state
    @ViewState private var address = ""
    @ViewState private var addressError: String?
    @ViewState private var applying = false
    @ViewState private var confirmDisconnect = false

    private var parsed: URL? { HubModel.parseBase(address) }
    private var current: URL { state.hub.baseURL ?? state.hub.preferredBase }

    var body: some View {
        let hub = state.hub
        VStack(alignment: .leading, spacing: 0) {
            SettingRow(title: "hub 地址", note: addressError ?? connectionNote) {
                HStack(spacing: 8) {
                    TextField("https://hub-home…:28443", text: $address)
                        .textFieldStyle(.roundedBorder).frame(width: 270)
                        .onSubmit(applyAddress)
                    if let parsed, parsed != current {
                        Button(applying ? "检查中…" : (hub.mode == .hub ? "切换" : "保存"), action: applyAddress).disabled(applying)
                    } else if parsed == nil, !address.isEmpty {
                        Text("地址无效").font(Typo.sans(11)).foregroundStyle(Tone.rose.color)
                    }
                }
            }
            SettingRow(title: "设备登录", note: hub.mode == .hub ? "令牌保存在钥匙串，断开只删除本机令牌" : signInNote) { control }
            if case .failed(let message) = hub.signIn {
                Text(message).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).padding(.top, 8)
            }
            if hub.mode == .hub {
                SectionTitle("来源 · \(hub.sourcesHealthy.ok) / \(hub.sourcesHealthy.total) 正常").padding(.top, 2)
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(hub.data.sources) { s in sourceRow(s) }
                        if hub.data.sources.isEmpty {
                            Text("还没有取到来源状态").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 8)
                        }
                    }
                }
                .scrollIndicators(.never)
            } else {
                Text("未连接时各模块显示设计稿示例数据。开发期也可以从终端写入令牌：\nPersonalHub --hub-token-stdin <地址>（令牌从标准输入读取）")
                    .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineSpacing(3).padding(.top, 12)
                    .textSelection(.enabled)
            }
        }
        .onAppear { address = current.absoluteString }
        .onChange(of: state.hub.baseURL) { _, url in if let url { address = url.absoluteString } }
        .onChange(of: address) { _, _ in addressError = nil }
        .alert("断开 hub？", isPresented: $confirmDisconnect) {
            Button("断开", role: .destructive) { state.hub.disconnect() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会删除本机保存的设备令牌和缓存，模块回到示例数据。hub 上的设备记录不受影响。")
        }
    }

    private var signInBase: URL? {
        let url = parsed ?? current
        return url.scheme == "https" ? url : nil
    }

    private var signInNote: String {
        signInBase == nil ? "登录要用 https 公网地址；登录后可以切换到局域网地址" : "通过 Authelia 在浏览器里登录"
    }

    private func applyAddress() {
        guard let url = parsed, url != current else { return }
        applying = true
        Task {
            addressError = await state.hub.changeBase(url)
            applying = false
        }
    }

    private var connectionNote: String {
        let hub = state.hub
        guard hub.mode == .hub else { return "公网入口或局域网 http://NAS:18190，同一个设备令牌都能用" }
        switch hub.status {
        case .syncing: return "同步中…"
        case .offline: return "离线 · 显示缓存"
        case .needsSignIn: return "令牌失效，请重新登录"
        case .failed(let m): return m
        case .idle: return HubFormat.stamp(hub.data.fetchedAt).map { "上次同步 " + $0 } ?? "尚未同步"
        }
    }

    @ViewBuilder private var control: some View {
        let hub = state.hub
        if hub.signIn == .waiting {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Button("取消") { hub.cancelSignIn() }
            }
        } else if hub.mode == .hub {
            HStack(spacing: 8) {
                if hub.status == .needsSignIn {
                    Button("重新登录") { hub.signIn(base: signInBase ?? HubModel.defaultBase) }.keyboardShortcut(.defaultAction)
                }
                Button(hub.status == .syncing ? "同步中…" : "立即同步") { hub.refresh() }.disabled(hub.status == .syncing)
                Button("断开…") { confirmDisconnect = true }
            }
        } else {
            Button("登录") {
                guard let base = signInBase else { return }
                hub.preferredBase = base
                hub.signIn(base: base)
            }
            .keyboardShortcut(.defaultAction)
            .disabled(signInBase == nil)
        }
    }

    private func sourceRow(_ s: HubSourceStatus) -> some View {
        let tone: Tone = switch s.status {
        case .ok: .olive
        case .error: .rose
        case .unconfigured: .ink
        default: .ochre
        }
        var detail: [String] = []
        if let e = s.lastError { detail.append(e.statusCode.map { "\(e.type) \($0)" } ?? e.type) }
        if let at = s.lastSuccess { detail.append("成功于 " + HubFormat.ago(at)) }
        if let ms = s.latencyMs { detail.append("\(ms) ms") }
        return HStack(spacing: 10) {
            Dot(color: s.status == .unconfigured ? Palette.ink4 : tone.color)
            Text(s.name).font(Typo.sans(12.5)).lineLimit(1)
            Spacer()
            Text(detail.joined(separator: " · ")).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
            Text(Self.label(s.status)).font(Typo.sans(11, .medium)).foregroundStyle(s.status == .unconfigured ? Palette.ink3 : tone.color)
                .frame(width: 52, alignment: .trailing)
        }
        .padding(.vertical, 7)
        .overlay(alignment: .bottom) { Rectangle().fill(Palette.line2).frame(height: 1) }
    }

    static func label(_ s: HubStatus) -> String {
        switch s {
        case .ok: "正常"
        case .partial: "部分可用"
        case .stale: "数据过旧"
        case .error: "故障"
        case .unconfigured: "未接入"
        }
    }
}

private struct AboutSettings: View {
    var body: some View {
        VStack(spacing: 12) {
            LogoMark(animated: true).frame(width: 88, height: 88)
            Text("Personal Hub").font(Typo.serif(24))
            Text("版本 \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev") · 阶段 5 · 主线与复盘")
                .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            Text("汇聚，然后看清方向").font(Typo.serif(14)).foregroundStyle(Palette.ink2)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 10)
    }
}
