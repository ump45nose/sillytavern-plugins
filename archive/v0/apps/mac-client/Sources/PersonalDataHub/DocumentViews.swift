import SwiftUI
import AppKit

struct DocumentListView: View {
    @ObservedObject var model: HubModel
    @ObservedObject var list: DocumentListModel
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if model.section == "reports" {
                Picker("报告类型", selection: $model.reportMode) {
                    Text("日报正文").tag("daily"); Text("执行记录").tag("execution")
                }.pickerStyle(.segmented).frame(width: 280)
                Text(model.reportMode == "daily" ? "按来源的文档日期阅读日报。" : "定时任务的执行日志，与日报正文分开。").font(.caption).foregroundStyle(.secondary)
            } else if model.section == "documents" {
                Picker("来源", selection: $model.documentSource) {
                    Text("全部阅读内容").tag("")
                    ForEach(model.sources) { source in Text(source.name).tag(source.id) }
                }.frame(width: 240)
                Text("默认排除执行记录；选择其来源后可读取。搜索覆盖完整正文。").font(.caption).foregroundStyle(.secondary)
            }
            if let error = list.error {
                Text(error).foregroundStyle(.orange)
                Button("重试") { Task { await model.loadDocuments(reset: list.items.isEmpty) } }
            }
            if list.items.isEmpty && !list.loading && list.error == nil {
                Label("没有符合条件的阅读内容", systemImage: "doc.text").foregroundStyle(.secondary).frame(maxWidth: .infinity, minHeight: 200)
            }
            ForEach(list.items) { item in
                Button { model.readingSelection = DocumentSelection(item: item, query: model.query) } label: {
                    VStack(alignment: .leading, spacing: 9) {
                        HStack(alignment: .top) {
                            Text(item.title).font(.headline)
                            Spacer(); Text(item.stateLabel).font(.caption).foregroundStyle(item.ready ? Color.secondary : .orange)
                        }
                        if let match = item.match, item.ready {
                            Text("正文命中").font(.caption).foregroundStyle(.indigo)
                            Text(highlightedText(match.excerpt, query: model.query)).font(.subheadline).lineLimit(4)
                        } else { Text(item.preview).font(.subheadline).foregroundStyle(.secondary).lineLimit(3) }
                        Text(sourceName(item.source) + " · " + item.dateLabel).font(.caption).foregroundStyle(.secondary)
                    }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                }.buttonStyle(.plain)
            }
            if list.cursor != nil {
                Button(list.loading ? "正在读取…" : "查看更多") { Task { await model.loadDocuments(reset: false) } }
                    .disabled(list.loading).frame(maxWidth: .infinity)
            }
        }
    }
}

struct DocumentReaderView: View {
    @ObservedObject var model: HubModel
    let selection: DocumentSelection
    @StateObject private var reader = DocumentReader()
    @Environment(\.dismiss) private var dismiss
    @State private var sourceText = false
    @State private var showingOriginal = false
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("文档阅读").font(.headline); Spacer()
                Button(reader.checking ? "正在核对…" : "核对更新") { Task { await reader.verifyCurrent() } }
                    .disabled(reader.header == nil || reader.checking)
                Button("重新读取") { Task { await reader.reload() } }.disabled(reader.loading || reader.removed)
                Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction)
            }.padding(18).background(.bar)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        if reader.removed { Label("这份内容已被删除。", systemImage: "trash").font(.title3) }
                        if let message = reader.message { Text(message).font(.caption).foregroundStyle(.secondary) }
                        if let warning = reader.verificationError { Label(warning, systemImage: "wifi.exclamationmark").foregroundStyle(.orange) }
                        if let header = reader.header {
                            documentHeader(header)
                            if !header.readable {
                                Label(stateMessage(header), systemImage: "doc.badge.clock").foregroundStyle(.orange)
                                if header.processing.state == "failed" {
                                    Button("查看整理失败原因") { model.section = "status"; dismiss() }
                                }
                            } else {
                                if let summary = header.summary, !summary.isEmpty {
                                    VStack(alignment: .leading, spacing: 8) { Text("摘要").font(.headline); Text(summary).textSelection(.enabled) }
                                }
                                if !header.warnings.isEmpty {
                                    ForEach(header.warnings, id: \.self) { warning in
                                        Text(warning == "nul_replaced_in_reading_copy" ? "阅读副本已替换 NUL 字符，归档原件保留原始内容。" : warning).font(.caption).foregroundStyle(.orange)
                                    }
                                }
                                HStack {
                                    Text(reader.complete ? "完整正文" : "正文 · 尚有内容待加载").font(.headline)
                                    Spacer(); Toggle("Markdown 原文", isOn: $sourceText).toggleStyle(.switch).font(.caption)
                                }
                                if reader.complete && reader.body.isEmpty { Text("这份文档的正文为空。").foregroundStyle(.secondary) }
                                else if sourceText {
                                    // No preview limit and no transport separator: source whitespace is preserved.
                                    Text(highlightedText(reader.body, query: selection.query)).font(.system(size: 14, design: .monospaced)).textSelection(.enabled)
                                } else {
                                    DocumentMarkdownView(text: reader.body, query: selection.query)
                                }
                                if reader.seeking {
                                    HStack { ProgressView().controlSize(.small); Text("正在加载到正文命中位置…"); Button("停止定位") { reader.cancelSearch() } }.font(.caption)
                                } else if reader.nextAfter != nil {
                                    Button(reader.loading ? "正在读取正文…" : "加载下一页正文") { Task { await reader.loadNext() } }.disabled(reader.loading)
                                }
                                attachments(header)
                            }
                            originalEvidence(header)
                        }
                        if reader.loading { LoadingBanner(message: "正在读取正文…") }
                        if let error = reader.error {
                            Text(error).foregroundStyle(.orange)
                            Button("重试读取") { Task { if reader.header != nil && reader.nextAfter != nil { await reader.loadNext() } else { await reader.reload() } } }
                        }
                    }.padding(28).frame(maxWidth: .infinity, alignment: .leading)
                }
                .onChange(of: reader.matchResolved) { found in
                    if found, let offset = reader.matchOffset,
                       let paragraph = DocumentMarkdown.paragraphs(reader.body).first(where: { $0.sourceOffsets?.contains(offset) == true }) {
                        withAnimation { proxy.scrollTo(paragraph.id, anchor: .center) }
                    }
                }
            }
        }.frame(width: 780, height: 740).background(Color(nsColor: .windowBackgroundColor))
        .task(id: selection.id) {
            reader.onInvalidated = { id, removed in
                showingOriginal = false
                if removed { model.documents.remove(id) }
                Task { await model.select(nil); await model.loadDocuments() }
            }
            await reader.open(selection, api: model.api)
        }
        .task {
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 30_000_000_000) } catch { return }
                await reader.verifyCurrent()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in Task { await reader.verifyCurrent() } }
        .onDisappear { reader.close() }
        .onChange(of: reader.header?.revision) { _ in showingOriginal = false }
        .onChange(of: reader.header?.processing.state) { _ in showingOriginal = false }
        .sheet(isPresented: $showingOriginal) { ReadableDetailView(model: model) }
    }
    private func documentHeader(_ header: DocumentContent) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(header.title).font(.title.bold()).textSelection(.enabled)
            Text(sourceName(header.source) + " · " + header.dateLabel).foregroundStyle(.secondary)
            Text(header.stateLabel).font(.caption).foregroundStyle(header.readable ? Color.secondary : .orange)
            if let tags = header.metadata?.tags, !tags.isEmpty { Text(tags.map { "#" + $0 }.joined(separator: "  ")).font(.caption).foregroundStyle(.indigo) }
        }
    }
    private func stateMessage(_ header: DocumentContent) -> String {
        if !header.supported || (header.ready && header.metadata?.format != "markdown") { return "当前客户端暂不支持此文档格式，可核对归档原件。" }
        if header.processing.state == "ready" { return "尚无可阅读的正文版本，请稍后刷新。" }
        return header.processing.label + "。可刷新状态或查看原件。"
    }
    @ViewBuilder private func attachments(_ header: DocumentContent) -> some View {
        if let assets = header.assets, !assets.isEmpty {
            Divider(); Text("归档附件").font(.headline)
            ForEach(assets) { asset in
                HStack {
                    Label(asset.name, systemImage: "paperclip").lineLimit(2)
                    Spacer(); Text(ByteCountFormatter.string(fromByteCount: asset.size, countStyle: .file)).font(.caption).foregroundStyle(.secondary)
                    Button("保存") { Task { await reader.save(asset) } }.disabled(reader.saving)
                }
            }
            if reader.saving { LoadingBanner(message: "正在下载并校验附件…") }
        }
    }
    private func openOriginal(_ id: String) {
        model.detail = nil; model.loadingDetail = true
        Task { await model.select(id) }; showingOriginal = true
    }
    private func originalEvidence(_ header: DocumentContent) -> some View {
        DisclosureGroup("来源记录与原件版本") {
            VStack(alignment: .leading, spacing: 12) {
                Text("阅读版本 \(header.revision) · 来源时区 \(header.timezone)").font(.caption).foregroundStyle(.secondary)
                if let id = header.metadata?.record_id { Button("查看来源记录") { openOriginal(id) } }
                if header.revision > 0 {
                    Button(reader.evidenceLoading ? "正在核对依据…" : "核对本阅读版本的依据") { Task { await reader.loadEvidence() } }.disabled(reader.evidenceLoading)
                }
                if let evidence = reader.evidence {
                    ForEach(evidence.inputs) { input in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(input.current_matches ? "与当前原件一致" : "原件版本已变化").foregroundStyle(input.current_matches ? Color.secondary : .orange)
                            Text("输入 SHA-256：" + input.input_hash).textSelection(.enabled)
                            Text("当前 SHA-256：" + (input.current_hash ?? "原件不可用")).textSelection(.enabled)
                            Button("查看归档原件") { openOriginal(input.record_id) }
                        }.font(.caption)
                    }
                }
                if let error = reader.evidenceError { Text(error).foregroundStyle(.orange) }
                if let relations = header.metadata?.relations, !relations.isEmpty {
                    Text("来源关系（可在原件中核对）").font(.caption)
                    ForEach(Array(relations.enumerated()), id: \.offset) { _, relation in Text(relation.description).font(.caption).textSelection(.enabled) }
                }
                ForEach(header.coverage.keys.sorted(), id: \.self) { key in Text("覆盖 \(key)：\(header.coverage[key] ?? "")").font(.caption).foregroundStyle(.secondary) }
            }.padding(.top, 12)
        }
    }
}

struct MarkdownParagraph: Identifiable {
    let id: Int; let text: AttributedString; let heading: Int?; let marker: String?; let quoted: Bool; let code: Bool
    let sourceOffsets: Range<Int>?
    var plain: String { String(text.characters) }
}
enum DocumentMarkdown {
    static func paragraphs(_ text: String) -> [MarkdownParagraph] {
        guard let parsed = try? AttributedString(markdown: text, options: .init(interpretedSyntax: .full, appliesSourcePositionAttributes: true)) else {
            return [MarkdownParagraph(id: 0, text: AttributedString(text), heading: nil, marker: nil, quoted: false, code: false, sourceOffsets: 0..<text.unicodeScalars.count)]
        }
        return parsed.runs[\.presentationIntent].enumerated().map { index, run in
            let (intent, range) = run
            var heading: Int?; var ordinal: Int?; var ordered = false; var quoted = false; var code = false
            for component in intent?.components ?? [] {
                switch component.kind {
                case .header(let level): heading = level
                case .listItem(let n): ordinal = n
                case .orderedList: ordered = true
                case .blockQuote: quoted = true
                case .codeBlock: code = true
                default: break
                }
            }
            let positions = parsed[range].runs.compactMap { run -> Range<Int>? in
                guard let position = run.markdownSourcePosition, let source = Range<String.Index>(position, in: text) else { return nil }
                return text.unicodeScalars.distance(from: text.startIndex, to: source.lowerBound)..<text.unicodeScalars.distance(from: text.startIndex, to: source.upperBound)
            }
            let offsets = positions.map(\.lowerBound).min().flatMap { lower in positions.map(\.upperBound).max().map { lower..<$0 } }
            return MarkdownParagraph(id: index, text: AttributedString(parsed[range]), heading: heading,
                                     marker: ordinal.map { ordered ? "\($0)." : "•" }, quoted: quoted, code: code, sourceOffsets: offsets)
        }
    }
}
func highlightedText(_ text: String, query: String) -> AttributedString { highlightedText(AttributedString(text), query: query) }
func highlightedText(_ text: AttributedString, query: String) -> AttributedString {
    var value = text
    guard !query.isEmpty else { return value }
    var cursor = value.startIndex
    while cursor < value.endIndex, let range = value[cursor..<value.endIndex].range(of: query, options: .caseInsensitive) {
        value[range].backgroundColor = .yellow.opacity(0.35)
        cursor = range.upperBound
    }
    return value
}
struct DocumentMarkdownView: View {
    let text: String; let query: String
    var body: some View {
        LazyVStack(alignment: .leading, spacing: 12) {
            ForEach(DocumentMarkdown.paragraphs(text)) { paragraph in
                HStack(alignment: .top, spacing: 10) {
                    if paragraph.quoted { Rectangle().fill(Color.secondary.opacity(0.35)).frame(width: 3) }
                    if let marker = paragraph.marker { Text(marker).foregroundStyle(.secondary) }
                    Text(highlightedText(paragraph.text, query: query))
                        .font(paragraph.code ? .system(size: 14, design: .monospaced) : paragraph.heading.map { $0 == 1 ? .title2.bold() : $0 == 2 ? .title3.bold() : .headline } ?? .system(size: 15))
                        .lineSpacing(6).frame(maxWidth: .infinity, alignment: .leading)
                }.padding(.vertical, paragraph.heading == nil ? 0 : 6)
                    .padding(paragraph.code ? 10 : 0)
                    .background(paragraph.code ? Color.primary.opacity(0.04) : .clear, in: RoundedRectangle(cornerRadius: 6))
                    .id(paragraph.id)
            }
        }.textSelection(.enabled)
    }
}

struct ProcessingStatusView: View {
    let status: ProcessingStatus?
    let error: String?
    var body: some View {
        HubCard(title: "内容整理", icon: "doc.text.magnifyingglass") {
            if let error { Text(error).foregroundStyle(.orange) }
            if let status, status.schema_version == 1 {
                Text("采集入库与内容整理分别统计。").font(.caption).foregroundStyle(.secondary)
                ForEach(status.jobs.keys.sorted(), id: \.self) { state in
                    HStack { Text(["pending": "等待整理", "running": "整理中", "ready": "已整理", "stale": "待更新", "failed": "整理失败"][state] ?? state); Spacer(); Text("任务 \(status.jobs[state] ?? 0) · 阅读对象 \(status.objects[state] ?? 0)") }
                }
                DisclosureGroup("来源覆盖") {
                    ForEach(Array(status.source_coverage.enumerated()), id: \.offset) { _, coverage in
                        HStack { Text(sourceName(coverage.source) + " · " + kindName(coverage.kind)); Spacer(); Text("\(coverage.records) 条 · " + (coverage.supported ? "支持整理" : "尚未支持")) }.font(.caption).padding(.vertical, 4)
                    }
                }
                ForEach(status.errors) { failure in
                    Text(sourceName(failure.source) + " · " + (failure.error_code ?? "整理失败") + " · 已尝试 \(failure.attempts) 次").font(.caption).foregroundStyle(.orange)
                }
            } else if status != nil { Text("当前客户端暂不支持此整理状态格式。").foregroundStyle(.orange) }
            else if error == nil { Text("正在读取整理状态…").foregroundStyle(.secondary) }
        }
    }
}
