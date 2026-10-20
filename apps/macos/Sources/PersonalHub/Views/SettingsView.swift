import AppKit
import HubKit
import ServiceManagement
import SwiftUI

struct SettingsView: View {
    @Environment(AppState.self) private var state
    @ViewState private var tab = 0

    var body: some View {
        VStack(spacing: 0) {
            Segmented(options: [(0, "通用"), (1, "快捷键"), (2, "账户"), (3, "关于")], selection: $tab)
                .padding(.top, 18)
            Group {
                switch tab {
                case 0: GeneralSettings()
                case 1: ShortcutSettings()
                case 2: AccountSettings()
                default: AboutSettings()
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(width: 520, height: 380)
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
            SettingRow(title: "布局", note: "页面布局保存在本机，阶段 3 起在设备间同步") {
                Button("恢复默认") { state.resetLayout() }
            }
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
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SettingRow(title: "Google 日历与任务", note: "阶段 2：本机 OAuth，令牌保存在钥匙串") { Chip(text: "未连接") }
            SettingRow(title: "Personal Hub 后端", note: "阶段 3：Authelia 登录后签发设备令牌") { Chip(text: "未连接") }
            SettingRow(title: "数据来源", note: "当前显示设计稿示例数据") { Chip(text: "示例数据", tone: .ochre) }
        }
    }
}

private struct AboutSettings: View {
    var body: some View {
        VStack(spacing: 12) {
            LogoMark(animated: true).frame(width: 88, height: 88)
            Text("Personal Hub").font(Typo.serif(24))
            Text("版本 \(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev") · 阶段 1 骨架")
                .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            Text("汇聚，然后看清方向").font(Typo.serif(14)).foregroundStyle(Palette.ink2)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 10)
    }
}
