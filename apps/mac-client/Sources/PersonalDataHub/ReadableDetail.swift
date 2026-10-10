import SwiftUI
import AVFoundation
import Charts

@MainActor final class AudioPlayback: ObservableObject {
    @Published var playing = false
    @Published var loading = false
    @Published var message: String?
    private var player: AVAudioPlayer?
    private var file: URL?
    func toggle(_ asset: ArchiveAsset, api: HubAPI) async {
        if let player = player {
            if player.isPlaying { player.pause(); playing = false } else { player.play(); playing = true }
            return
        }
        loading = true
        do {
            let url = try await api.download(asset)
            do { try asset.verifyFile(url) } catch { try? FileManager.default.removeItem(at: url); throw error }
            file = url; player = try AVAudioPlayer(contentsOf: url); player?.play(); playing = true
        } catch { message = "无法播放录音，请保存附件后查看。" }
        loading = false
    }
    func stop() { player?.stop(); player = nil; playing = false; if let file = file { try? FileManager.default.removeItem(at: file) }; file = nil }
}
struct ReadableDetailView: View {
    @ObservedObject var model: HubModel
    @Environment(\.dismiss) var dismiss
    @StateObject private var audio = AudioPlayback()
    @State private var personTimeline: [DisplayCard] = []
    var body: some View {
        VStack(spacing: 0) {
            HStack { Text("信息详情").font(.headline); Spacer(); Button("导出完整数据") { model.exportRecord() }.disabled(model.detail == nil); Button("关闭") { dismiss() }.keyboardShortcut(.cancelAction) }.padding(20).background(.bar)
            ScrollView {
                if model.loadingDetail { PageLoadingView(message: "正在读取完整内容…").padding(28) }
                else if let error = model.detailError {
                    VStack(spacing: 16) {
                        Image(systemName: "wifi.exclamationmark").font(.largeTitle).foregroundStyle(.orange)
                        Text(error).foregroundStyle(.secondary)
                        Button("重新加载") { Task { await model.select(model.selectedID) } }
                    }.frame(maxWidth: .infinity, minHeight: 300)
                }
                else if let record = model.detail {
                    let object = (try? JSONSerialization.jsonObject(with: Data(record.rawJSON.utf8))) as? [String: Any] ?? [:]
                    let raw = object["raw"] as? [String: Any] ?? [:], normal = object["normalized"] as? [String: Any] ?? [:]
                    let content = record.wechatContent ?? record.fields.first { ["content", "body", "summary", "message"].contains($0.id) }?.value ?? ""
                    let name = (record.wechatContent == nil ? frontTitle(content) : nil) ?? record.fields.first { ["title", "subject", "display_name", "name"].contains($0.id) }?.value ?? kindName(record.kind)
                    VStack(alignment: .leading, spacing: 24) {
                        HStack(alignment: .top, spacing: 16) {
                            Image(systemName: moduleIcons[domain(record.kind)] ?? "doc.text").font(.title).foregroundStyle(.indigo).frame(width: 54, height: 54).background(Color.indigo.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                            VStack(alignment: .leading, spacing: 7) {
                                Text(name).font(.title.bold()).textSelection(.enabled)
                                Text(sourceName(record.source) + " · " + displayDate(record.occurredAt)).font(.subheadline).foregroundStyle(.secondary)
                            }
                        }
                        if record.kind == "bill" {
                            let bill = raw["bill"] as? [String: Any] ?? raw
                            HStack(alignment: .firstTextBaseline) {
                                Text(String(describing: bill["money"] ?? normal["amount"] ?? "—")).font(.system(size: 40, weight: .semibold, design: .rounded))
                                Text(String(describing: bill["currency"] ?? "")).foregroundStyle(.secondary)
                                Spacer(); Text(String(describing: bill["state"] ?? "") == "Wait2Edit" ? "待确认" : "已归档").font(.caption).foregroundStyle(.secondary)
                            }
                            ForEach(["cateName", "shopName", "accountNameFrom", "accountNameTo", "remark"], id: \.self) { key in
                                if let v = bill[key] as? String, !v.isEmpty { HStack { Text(["cateName": "分类", "shopName": "商户", "accountNameFrom": "付款账户", "accountNameTo": "收款账户", "remark": "备注"][key]!).foregroundStyle(.secondary).frame(width: 90, alignment: .leading); Text(v).textSelection(.enabled) } }
                            }
                        } else if record.kind == "people" {
                            ForEach(["relationship_to_me", "organizations", "tags", "profile_notes"], id: \.self) { key in
                                if let text = profileText(raw[key]) {
                                    VStack(alignment: .leading, spacing: 5) { Text(["relationship_to_me": "关系", "organizations": "组织", "tags": "标签", "profile_notes": "个人资料"][key]!).font(.caption).foregroundStyle(.secondary); Text(text).textSelection(.enabled) }
                                }
                            }
                            Text("交流时间线").font(.headline)
                            ForEach(personTimeline) { c in
                                Button { model.openCard(c) } label: {
                                    VStack(alignment: .leading, spacing: 6) { Text(displayDate(c.occurred_at)).font(.caption).foregroundStyle(.secondary); Text(c.preview).lineLimit(4) }.frame(maxWidth: .infinity, alignment: .leading).padding(12).background(Color.primary.opacity(0.03), in: RoundedRectangle(cornerRadius: 8))
                                }.buttonStyle(.plain)
                            }
                        } else if record.kind == "health_payloads" {
                            VStack(alignment: .leading, spacing: 14) {
                                Text("这次同步的健康数据").font(.headline)
                                ForEach(record.fields.filter { $0.id.hasPrefix("health_") }) { field in
                                    let samples = ((try? JSONSerialization.jsonObject(with: Data(field.value.utf8))) as? [[String: Any]]) ?? []
                                    VStack(alignment: .leading, spacing: 8) {
                                        Text(fieldName(field.id)).foregroundStyle(.secondary)
                                        let points = healthPoints(samples, field: field.id)
                                        if !points.isEmpty {
                                            Chart(points) { point in
                                                BarMark(x: .value("时间", point.time), y: .value(point.unit, point.value)).foregroundStyle(.indigo.opacity(0.75))
                                            }.frame(height: 140)
                                            Text(points.first?.unit ?? "").font(.caption).foregroundStyle(.secondary)
                                        } else { Text("暂无有效样本").font(.caption).foregroundStyle(.secondary) }
                                        ForEach(Array(samples.prefix(8).enumerated()), id: \.offset) { _, sample in
                                            let value = sample["count"] ?? sample["duration_seconds"] ?? sample["bpm"] ?? sample["calories"] ?? sample["percentage"] ?? sample["watts"]
                                            let time = sample["end_time"] ?? sample["session_end_time"] ?? sample["time"]
                                            let point = healthPoints([sample], field: field.id).first
                                            HStack { Text(point.map { $0.value.formatted(.number.precision(.fractionLength(0...2))) + " " + $0.unit } ?? String(describing: value ?? "—")).font(.title3.weight(.semibold)); Spacer(); Text(displayDate(time as? String)).font(.caption).foregroundStyle(.secondary) }
                                        }
                                    }
                                }
                            }
                        } else {
                            let body = record.fields.first { ["content", "body", "summary", "message"].contains($0.id) }?.value
                            if let original = record.wechatContent {
                                Text(verbatim: original.replacingOccurrences(of: "\u{0000}", with: ""))
                                    .font(.system(size: 15)).lineSpacing(6).textSelection(.enabled)
                            } else if let body = body, !body.isEmpty {
                                let preview = readingBody(String(body.prefix(50000))).replacingOccurrences(of: "\u{0000}", with: "")
                                MarkdownReadingView(text: preview)
                                if body.count > 50000 { Text("此处显示部分正文，导出可获取完整内容。").font(.caption).foregroundStyle(.secondary) }
                            } else if record.kind == "recording" {
                                let duration = (normal["duration_ms"] as? Double ?? 0) / 60000
                                Text("\(duration.formatted(.number.precision(.fractionLength(1)))) 分钟").font(.title)
                            } else {
                                ForEach(record.fields.filter { !$0.id.hasPrefix("health_") }) { f in VStack(alignment: .leading, spacing: 6) { Text(fieldName(f.id)).font(.caption).foregroundStyle(.secondary); Text(String(f.value.prefix(1000))).textSelection(.enabled) } }
                            }
                            if record.kind == "interactions", let pid = raw["person_id"] as? String {
                                Button("查看联系人资料") {
                                    Task {
                                        do {
                                        let page: RecordPage = try await model.api.get("api/v1/browse", query: [URLQueryItem(name: "source", value: "crm"), URLQueryItem(name: "kind", value: "people"), URLQueryItem(name: "limit", value: "100")])
                                        for c in page.records {
                                            let p = try await model.api.record(c.id)
                                            if let obj = try? JSONSerialization.jsonObject(with: Data(p.rawJSON.utf8)) as? [String: Any], (obj["raw"] as? [String: Any])?["id"] as? String == pid { await model.select(c.id); break }
                                        }
                                        } catch { model.error = error.localizedDescription }
                                    }
                                }
                            }
                        }
                        if !record.assets.isEmpty {
                            Divider()
                            Text("附件").font(.headline)
                            ForEach(record.assets) { asset in
                                HStack {
                                    Image(systemName: asset.media_type.hasPrefix("audio") ? "waveform" : "paperclip").foregroundStyle(.secondary)
                                    VStack(alignment: .leading, spacing: 4) { Text(asset.name).lineLimit(1); Text(ByteCountFormatter.string(fromByteCount: asset.size, countStyle: .file)).font(.caption).foregroundStyle(.secondary) }
                                    Spacer()
                                    if asset.media_type.hasPrefix("audio") || ["wav", "mp3", "m4a"].contains((asset.name as NSString).pathExtension.lowercased()) {
                                        Button { Task { await audio.toggle(asset, api: model.api) } } label: {
                                            HStack { if audio.loading { ProgressView().controlSize(.small) }; Text(audio.loading ? "正在读取音频…" : audio.playing ? "暂停" : "播放") }
                                        }.disabled(audio.loading)
                                    }
                                    Button("保存") { Task { await model.download(asset) } }.disabled(model.downloading)
                                }.padding(.vertical, 4)
                            }
                            if let message = audio.message { Text(message).foregroundStyle(.orange).font(.caption) }
                            if model.downloading { LoadingBanner(message: "正在下载并校验附件…") }
                        }
                        Divider()
                        DisclosureGroup("归档信息与原始数据") {
                            VStack(alignment: .leading, spacing: 12) {
                                Text("归档于 \(displayDate(record.observedAt)) · 来源时区 \(record.timezone)").font(.caption).foregroundStyle(.secondary)
                                Text(String(record.rawJSON.prefix(50000))).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                            }.padding(.top, 12)
                        }.font(.caption)
                    }.padding(28).frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }.frame(width: 740, height: 700)
        .background(Color(nsColor: .windowBackgroundColor))
        .onDisappear { audio.stop() }
        .task(id: model.detail?.id) {
            guard let detail = model.detail, detail.kind == "people",
                  let object = try? JSONSerialization.jsonObject(with: Data(detail.rawJSON.utf8)) as? [String: Any],
                  let pid = (object["raw"] as? [String: Any])?["id"] as? String else { return }
            do {
                let p: TimelinePage = try await model.api.get("api/v1/timeline", query: [URLQueryItem(name: "domains", value: "social"), URLQueryItem(name: "person", value: pid)])
                personTimeline = p.items
            } catch { model.error = error.localizedDescription }
        }
    }
    private func domain(_ kind: String) -> String { ["people": "social", "interactions": "social", "bill": "finance", "health_payloads": "health", "recording": "recordings", "computer_summary": "activity"][kind] ?? "notes" }
}
private func profileText(_ value: Any?) -> String? {
    if let text = value as? String { return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text }
    if let array = value as? [Any] { let texts = array.compactMap(profileText); return texts.isEmpty ? nil : texts.joined(separator: "、") }
    if let object = value as? [String: Any] { return ["name", "title", "label"].compactMap { profileText(object[$0]) }.first }
    return nil
}
private func frontTitle(_ text: String) -> String? {
    if text.hasPrefix("#日报 ") { return text.components(separatedBy: .newlines).first }
    if text.hasPrefix("# ") { return text.components(separatedBy: .newlines).first.map { String($0.dropFirst(2)) } }
    guard text.hasPrefix("---\n") else { return nil }
    return text.components(separatedBy: "\n").prefix(30).first { $0.hasPrefix("title:") }.map { String($0.dropFirst(6)).trimmingCharacters(in: CharacterSet(charactersIn: " \"'")) }
}
private func readingBody(_ text: String) -> String {
    if text.hasPrefix("---\n"), let end = text.range(of: "\n---", range: text.index(text.startIndex, offsetBy: 4)..<text.endIndex) {
        return String(text[end.upperBound...]).trimmingCharacters(in: .whitespacesAndNewlines)
    }
    return text
}
private struct MarkdownReadingView: View {
    let text: String
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { _, line in
                if line.hasPrefix("# ") { Text(String(line.dropFirst(2))).font(.title2.bold()).padding(.top, 10) }
                else if line.hasPrefix("## ") { Text(String(line.dropFirst(3))).font(.title3.bold()).padding(.top, 8) }
                else if line.hasPrefix("### ") { Text(String(line.dropFirst(4))).font(.headline).padding(.top, 6) }
                else if line.isEmpty { Spacer().frame(height: 4) }
                else { Text((try? AttributedString(markdown: line, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(line)).font(.system(size: 15)).lineSpacing(6) }
            }
        }.textSelection(.enabled)
    }
}
private struct HealthDetailPoint: Identifiable {
    let id: Int; let time: Date; let value: Double; let unit: String
}
private func healthPoints(_ samples: [[String: Any]], field: String) -> [HealthDetailPoint] {
    samples.enumerated().compactMap { index, sample in
        let raw = sample["count"] ?? sample["duration_seconds"] ?? sample["bpm"] ?? sample["calories"]
        let time = sample["end_time"] ?? sample["session_end_time"] ?? sample["time"]
        guard let number = raw as? NSNumber, let date = archiveDate(time as? String) else { return nil }
        let sleep = field.contains("sleep")
        return HealthDetailPoint(id: index, time: date, value: sleep ? number.doubleValue / 3600 : number.doubleValue,
                                 unit: sleep ? "小时" : field.contains("heart") ? "次/分" : field.contains("calor") ? "千卡" : "步")
    }.sorted { $0.time < $1.time }
}
