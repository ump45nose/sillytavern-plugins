import SwiftUI
import ServiceManagement

func fieldName(_ key: String) -> String {
    ["title": "标题", "subject": "主题", "sender": "发件人", "content": "内容", "message": "内容",
     "summary": "摘要", "name": "名称", "display_name": "姓名", "body": "正文", "amount": "金额",
     "currency": "币种", "type": "类型", "remark": "备注", "duration_ms": "时长（毫秒）", "repo": "仓库", "date": "日期",
     "state": "状态", "status": "状态", "upload_bytes": "上传字节", "download_bytes": "下载字节",
     "download_state": "录音下载状态", "validation_error": "来源验证记录", "device": "设备",
     "tokens": "Token 用量", "estimated_cost_usd": "估算费用（美元）", "cache_read_tokens": "缓存读取 Token",
     "cache_write_tokens": "缓存写入 Token", "output_tokens": "输出 Token", "health_steps": "步数",
     "health_sleep": "睡眠", "health_heart_rate": "心率", "health_active_calories": "活动热量",
     "health_oxygen_saturation": "血氧", "health_resting_heart_rate": "静息心率",
     "health_basal_metabolic_rate": "基础代谢"][key] ?? key
}

struct SettingsView: View {
    @ObservedObject var model: HubModel
    @Environment(\.dismiss) var dismiss
    @State private var endpoint = ""
    @State private var token = ""
    @State private var recordingShortcut = false
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("连接设置").font(.title2.bold())
            TextField("HTTPS 服务地址", text: $endpoint).textFieldStyle(.roundedBorder)
            SecureField("只读访问凭据（留空保留当前凭据）", text: $token).textFieldStyle(.roundedBorder)
            Text("归档凭据和 Google 授权分别保存在系统钥匙串。")
                .font(.caption).foregroundStyle(.secondary)
            Divider()
            HStack {
                Text("Google 日程与任务"); Spacer()
                Button(model.googleSnapshot == nil ? "连接 Google" : "重新授权") { model.googleOperation { try await model.google.authorize() } }.disabled(model.googleBusy)
            }
            if let msg = model.googleMessage { Text(msg).font(.caption).foregroundStyle(.orange) }
            HStack {
                Text("全局快捷键"); Spacer()
                Button(model.preferences.hotkeyLabel) { recordingShortcut = true }
            }
            if recordingShortcut {
                Text("按下新的快捷键组合（需包含修饰键）").font(.caption).foregroundStyle(.secondary)
                ShortcutRecorder { code, mods, label in
                    model.preferences.hotkeyCode = code; model.preferences.hotkeyModifiers = mods; model.preferences.hotkeyLabel = label
                    model.preferences.save(); recordingShortcut = false
                }.frame(height: 24)
            }
            if let err = model.hotkeyError { Text(err).font(.caption).foregroundStyle(.orange) }
            Toggle("开机启动", isOn: Binding(get: { model.loginEnabled }, set: { model.setLogin($0) }))
            if model.loginNeedsApproval {
                Text("开机启动等待系统登录项批准。")
                    .font(.caption).foregroundStyle(.secondary)
                Button("打开系统登录项设置") { SMAppService.openSystemSettingsLoginItems() }
            }
            HStack {
                Spacer()
                Button("取消") { token = ""; dismiss() }
                Button("保存并连接") {
                    let credential = token; token = ""
                    Task { await model.saveConnection(endpoint: endpoint, token: credential) }
                    dismiss()
                }.keyboardShortcut(.defaultAction)
            }
        }.padding(26).frame(width: 480)
        .onAppear { endpoint = model.connection.endpoint }
    }
}
