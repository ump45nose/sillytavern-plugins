import SwiftUI

struct ContentView: View {
    @ObservedObject var model: HubModel
    @State private var settings = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("个人信息归档").font(.title2.bold())
                    Text("\(model.sources.count) 个来源 · \(model.recordCount.formatted()) 条信息")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                if let date = model.refreshedAt {
                    Text("更新于 \(date.formatted(date: .omitted, time: .shortened))").font(.caption).foregroundStyle(.secondary)
                }
                Button { Task { await model.refreshStatus(); await model.browse(reset: true) } } label: {
                    Label("刷新", systemImage: "arrow.clockwise")
                }.disabled(model.busy)
                Button { settings = true } label: { Image(systemName: "gearshape") }.help("连接与开机启动")
            }.padding(20)
            Divider()
            if let error = model.error {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Text(error).textSelection(.enabled)
                    Spacer()
                    Button("关闭") { model.error = nil }.buttonStyle(.borderless)
                }.padding(10).background(Color.orange.opacity(0.08))
            }
            HSplitView {
                sidebar.frame(minWidth: 230, idealWidth: 255, maxWidth: 310)
                archive.frame(minWidth: 330, idealWidth: 390)
                detail.frame(minWidth: 350, idealWidth: 480)
            }
        }
        .frame(minWidth: 1000, minHeight: 680)
        .background(Color(nsColor: .windowBackgroundColor))
        .sheet(isPresented: $settings) { SettingsView(model: model) }
        .onChange(of: model.source) { _ in
            model.kind = ""
            Task { await model.browse(reset: true) }
        }
        .onChange(of: model.kind) { _ in Task { await model.browse(reset: true) } }
        .onChange(of: model.days) { _ in Task { await model.browse(reset: true) } }
        .onChange(of: model.selectedID) { id in Task { await model.select(id) } }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("数据来源").font(.headline).padding()
            List(selection: Binding<String?>(get: { model.source }, set: { model.source = $0 ?? "" })) {
                Label("全部信息", systemImage: "tray.full").tag("")
                ForEach(model.sources) { source in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack {
                            Text(source.name).lineLimit(1)
                            Spacer()
                            Text(source.count.formatted()).font(.caption).foregroundStyle(.secondary)
                        }
                        HStack(spacing: 5) {
                            Circle().fill(source.needsAttention ? Color.orange : Color.green).frame(width: 6, height: 6)
                            Text(source.state).font(.caption).foregroundStyle(.secondary)
                        }
                        Text(displayDate(source.last_observed_at)).font(.caption2).foregroundStyle(.secondary)
                    }.padding(.vertical, 4).tag(source.id)
                }
            }.listStyle(.sidebar)
            Divider()
            VStack(alignment: .leading, spacing: 10) {
                Text("本机采集").font(.headline)
                ForEach(model.agents) { agent in
                    HStack {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(agent.name).font(.subheadline)
                            Text(agent.state).font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: agent.loaded ? "checkmark.circle" : "exclamationmark.circle")
                            .foregroundStyle(agent.loaded ? Color.green : Color.orange)
                    }
                }
                Button { Task { await model.synchronize() } } label: {
                    Label("立即同步电脑活动", systemImage: "arrow.triangle.2.circlepath")
                }.disabled(!model.agents.contains { $0.id.contains("skysight") && $0.loaded })
                if let message = model.syncMessage {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
                if let checkpoint = model.checkpoint {
                    Text("已交付 \(checkpoint.segments.formatted()) 个片段、\(checkpoint.summaries.formatted()) 份摘要")
                        .font(.caption2).foregroundStyle(.secondary)
                    Text("上次完整同步：\(displayDate(checkpoint.lastSuccess))")
                        .font(.caption2).foregroundStyle(.secondary)
                    if checkpoint.invalid > 0 {
                        Text("\(checkpoint.invalid) 个片段等待来源检查").font(.caption2).foregroundStyle(.orange)
                    }
                }
                Text("后台每 15 分钟同步；关闭窗口后继续采集。")
                    .font(.caption2).foregroundStyle(.secondary)
            }.padding()
        }
    }

    private var archive: some View {
        VStack(spacing: 0) {
            VStack(spacing: 10) {
                HStack {
                    TextField("搜索标题、摘要", text: $model.query)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit { Task { await model.browse(reset: true) } }
                    Button("搜索") { Task { await model.browse(reset: true) } }
                }
                HStack {
                    Picker("类型", selection: $model.kind) {
                        Text("全部类型").tag("")
                        ForEach(model.kinds) { value in Text(kindName(value.kind)).tag(value.kind) }
                    }.labelsHidden()
                    Picker("时间", selection: $model.days) {
                        Text("全部时间").tag(0)
                        Text("最近 7 天").tag(7)
                        Text("最近 30 天").tag(30)
                    }.labelsHidden()
                }
            }.padding(14)
            Divider()
            ZStack {
                List(selection: $model.selectedID) {
                    ForEach(model.records) { record in
                        VStack(alignment: .leading, spacing: 7) {
                            Text(record.displayTitle).font(.headline).lineLimit(2)
                            Text(record.displayPreview.replacingOccurrences(of: "\u{0000}", with: ""))
                                .font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                            HStack {
                                Text(sourceName(record.source))
                                Spacer()
                                Text(displayDate(record.occurred_at))
                            }.font(.caption2).foregroundStyle(.secondary)
                        }.padding(.vertical, 7).tag(record.id)
                    }
                }.listStyle(.inset)
                if model.busy { ProgressView().padding().background(.regularMaterial).cornerRadius(10) }
                if !model.busy && model.records.isEmpty {
                    VStack(spacing: 10) {
                        Image(systemName: "tray").font(.largeTitle).foregroundStyle(.secondary)
                        Text(model.error == nil ? "没有符合条件的信息" : "暂时无法读取信息").foregroundStyle(.secondary)
                    }
                }
            }
            Divider()
            HStack {
                Text("共 \(model.total.formatted()) 条").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("上一页") {
                    model.offset = max(0, model.offset - 50)
                    model.selectedID = nil; model.detail = nil
                    Task { await model.browse(reset: false) }
                }.disabled(model.offset == 0 || model.busy)
                Text("\(model.offset / 50 + 1)").font(.caption).monospacedDigit()
                Button("下一页") {
                    guard let next = model.nextOffset else { return }
                    model.offset = next; model.selectedID = nil; model.detail = nil
                    Task { await model.browse(reset: false) }
                }.disabled(model.nextOffset == nil || model.busy)
            }.padding(12)
        }
    }

    @ViewBuilder private var detail: some View {
        if model.loadingDetail {
            VStack { Spacer(); ProgressView("读取信息…"); Spacer() }.frame(maxWidth: .infinity)
        } else if let record = model.detail {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        Text(kindName(record.kind)).font(.title2.bold())
                        Spacer()
                        Button("导出") { model.exportRecord() }
                    }
                    Text(sourceName(record.source)).foregroundStyle(.secondary)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("发生时间：\(displayDate(record.occurredAt))")
                        Text("归档时间：\(displayDate(record.observedAt))")
                        Text("来源时区：\(record.timezone)")
                    }.font(.caption).foregroundStyle(.secondary)
                    Divider()
                    ForEach(record.fields) { field in
                        VStack(alignment: .leading, spacing: 7) {
                            Text(fieldName(field.id)).font(.caption.bold()).foregroundStyle(.secondary)
                            Text(String(field.value.prefix(50000))).textSelection(.enabled)
                            if field.value.count > 50000 {
                                Text("内容较长，此处为预览；导出可查看完整数据。")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    if !record.assets.isEmpty {
                        Divider()
                        Text("附件").font(.headline)
                        ForEach(record.assets) { asset in
                            HStack {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(asset.name).lineLimit(2)
                                    Text(ByteCountFormatter.string(fromByteCount: asset.size, countStyle: .file))
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button { Task { await model.download(asset) } } label: {
                                    Image(systemName: "arrow.down.to.line")
                                }.disabled(model.downloading).help("保存附件")
                            }
                        }
                        if model.downloading { ProgressView("下载并校验附件…") }
                    }
                    DisclosureGroup("查看原始数据") {
                        Text(String(record.rawJSON.prefix(50000))).font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        if record.rawJSON.count > 50000 {
                            Text("此处预览前 50,000 字符，可导出完整数据。")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }.padding(22).frame(maxWidth: .infinity, alignment: .leading)
            }
        } else {
            VStack(spacing: 12) {
                Image(systemName: "doc.text.magnifyingglass").font(.largeTitle).foregroundStyle(.secondary)
                Text("选择一条信息查看内容").foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

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
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("连接设置").font(.title2.bold())
            TextField("HTTPS 服务地址", text: $endpoint).textFieldStyle(.roundedBorder)
            SecureField("只读访问凭据（留空保留当前凭据）", text: $token).textFieldStyle(.roundedBorder)
            Text("访问凭据保存在系统钥匙串。客户端只查看归档信息。")
                .font(.caption).foregroundStyle(.secondary)
            Toggle("开机启动", isOn: Binding(get: { model.loginEnabled }, set: { model.setLogin($0) }))
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
