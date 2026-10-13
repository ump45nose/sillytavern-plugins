import SwiftUI

struct NetworkSummary: Decodable {
    let date: String
    let source: String
    let sources: [String]
    let totals: [String: Double?]
    let dimensions: [String: [NetworkDimension]]
    let updated_at: String?
    let coverage_note: String
}
struct NetworkDimension: Decodable, Identifiable {
    let name: String
    let upload_bytes: Double
    let download_bytes: Double
    var id: String { name }
}

extension HubModel {
    func loadNetwork() async {
        networkGeneration += 1; let generation = networkGeneration
        let key = dayKey(displayDate) + "|" + networkSource
        networkLoading = true
        defer { if generation == networkGeneration { networkLoading = false } }
        do {
            let value: NetworkSummary = try await api.get("api/v1/network", query: [URLQueryItem(name: "date", value: dayKey(displayDate)), URLQueryItem(name: "tz", value: TimeZone.current.identifier), URLQueryItem(name: "source", value: networkSource)])
            guard generation == networkGeneration, !Task.isCancelled else { return }
            networkSummary = value; networkResultKey = key
        } catch { if generation == networkGeneration && !Task.isCancelled { self.error = error.localizedDescription } }
    }
    var networkMatchesPage: Bool { networkSummary != nil && networkResultKey == dayKey(displayDate) + "|" + networkSource }
}

struct NetworkView: View {
    @ObservedObject var model: HubModel
    private func bytes(_ value: Double?) -> String {
        value.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) } ?? "—"
    }
    var body: some View {
        if model.networkMatchesPage, let value = model.networkSummary {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("代理流量").font(.title2.bold())
                    Spacer()
                    Picker("采集位置", selection: $model.networkSource) {
                        Text("默认采集位置").tag("")
                        ForEach(value.sources, id: \.self) { source in
                            Text(source == "shellcrash" ? "NAS · ShellCrash" : "Mac · " + source.suffix(6)).tag(source)
                        }
                    }.frame(maxWidth: 280)
                }
                Text(value.source == "shellcrash" ? "当前统计 NAS 代理层" : "当前统计所选 Mac 代理入口")
                    .font(.caption).foregroundStyle(.secondary)
                HStack(spacing: 40) {
                    VStack(alignment: .leading) { Text("上传").foregroundStyle(.secondary); Text(bytes(value.totals["upload_bytes"] ?? nil)).font(.title.bold()) }
                    VStack(alignment: .leading) { Text("下载").foregroundStyle(.secondary); Text(bytes(value.totals["download_bytes"] ?? nil)).font(.title.bold()) }
                }
                Text(value.coverage_note).font(.caption).foregroundStyle(.secondary)
                Text("最近归档：\(displayDate(value.updated_at))").font(.caption).foregroundStyle(.secondary)
                if (value.totals["upload_bytes"] ?? nil) == nil {
                    Text("所选日期暂无已归档流量。").foregroundStyle(.secondary)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 340), alignment: .topLeading)], alignment: .leading, spacing: 16) {
                    ForEach([("process", "应用"), ("host", "域名"), ("exit_node", "出口节点"), ("category", "策略组")], id: \.0) { key, title in
                        HubCard(title: title, icon: key == "process" ? "app" : "network") {
                            ForEach(value.dimensions[key] ?? []) { row in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(row.name == "unknown" ? "未知" + title : row.name).font(.subheadline).lineLimit(2)
                                    HStack { Text("↑ " + bytes(row.upload_bytes)); Spacer(); Text("↓ " + bytes(row.download_bytes)) }
                                        .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                                }.padding(.vertical, 5)
                            }
                        }
                    }
                }
            }
        }
    }
}
