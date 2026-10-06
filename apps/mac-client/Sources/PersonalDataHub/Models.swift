import Foundation
import CryptoKit

let sourceNames: [String: String] = [
    "crm": "联系人与微信", "skysight-raw": "电脑活动", "skysight-summaries": "电脑活动摘要",
    "plaud": "Plaud 录音", "finance": "财务账单", "health": "健康数据", "hermes": "Hermes 日报",
    "hermes-reports": "Hermes 日报", "google": "Google 日历与任务", "email": "邮件", "git": "Git 提交",
    "memos": "Memos 笔记", "mem0": "长期记忆", "token": "Token 用量", "token-monitor": "Token 用量",
    "shellcrash": "网络流量", "legacy-evidence": "历史资料", "legacy-review-output": "历史复盘"
]
let kindNames: [String: String] = [
    "computer_summary": "活动摘要", "computer_segment": "活动片段", "computer_segment_invalid": "异常活动片段",
    "people": "联系人", "interactions": "交流记录", "facts": "人物事实", "reminders": "历史跟进",
    "sync_clients": "设备", "recording": "录音", "bill": "账单", "health_payloads": "健康记录",
    "calendar_event": "日历事件", "google_task": "任务", "email": "邮件", "git_commit": "提交",
    "memo": "笔记", "memory": "记忆", "token_day": "每日用量", "token_device": "用量设备",
    "subscription_config": "订阅配置", "traffic_hourly": "小时流量", "collector_gaps": "采集缺口",
    "collector_meta": "流量采集状态", "source_artifact": "归档文件", "execution_report": "执行报告",
    "hermes_execution_report": "执行日报", "recording_artifact": "录音历史资料",
    "legacy_review_report": "历史复盘", "legacy_source_evidence": "历史资料"
]
func sourceName(_ id: String) -> String { sourceNames[id] ?? id }
func kindName(_ id: String) -> String { kindNames[id] ?? id }

func archiveDate(_ value: String?) -> Date? {
    guard let value = value else { return nil }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter.date(from: value) ?? ISO8601DateFormatter().date(from: value)
}
func displayDate(_ value: String?) -> String {
    guard let date = archiveDate(value) else { return "时间未提供" }
    return date.formatted(date: .abbreviated, time: .shortened)
}

struct SourceStatus: Decodable, Identifiable {
    let id: String
    let count: Int
    let last_observed_at: String?
    let last_run: CollectionRun?
    let deletion_support: String
    var name: String { sourceName(id) }
    var state: String {
        switch last_run?.status {
        case "failed": return "采集失败"
        case "partial": return "已归档，含历史异常"
        case "running": return "采集中"
        case "ok": return "正常"
        default: return count > 0 ? "已接收" : "等待数据"
        }
    }
    var needsAttention: Bool { last_run?.status == "failed" || last_run?.status == "partial" }
}
struct CollectionRun: Decodable {
    let status: String
    let started_at: String
    let ended_at: String?
    let error: String?
}
struct RecordCard: Decodable, Identifiable {
    let id: String
    let source: String
    let kind: String
    let occurred_at: String?
    let observed_at: String
    let timezone: String
    let title: String
    let preview: String
    func summaryField(_ name: String) -> String? {
        guard kind == "computer_summary" else { return nil }
        return preview.components(separatedBy: .newlines).first(where: { $0.hasPrefix(name + ":") })
            .map { String($0.dropFirst(name.count + 1)).trimmingCharacters(in: .whitespaces) }
    }
    var displayTitle: String { summaryField("title") ?? (title == kind ? kindName(kind) : title) }
    var displayPreview: String { summaryField("description") ?? preview }
}
struct RecordPage: Decodable {
    let records: [RecordCard]
    let total: Int
    let next_offset: Int?
}
struct KindCount: Decodable, Identifiable {
    let kind: String
    let count: Int
    var id: String { kind }
}
struct ArchiveAsset: Decodable, Identifiable {
    let id: String
    let name: String
    let media_type: String
    let size: Int64
    func verifyFile(_ url: URL) throws {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hash = SHA256(); var bytes: Int64 = 0
        while let block = try handle.read(upToCount: 1024 * 1024), !block.isEmpty {
            hash.update(data: block); bytes += Int64(block.count)
        }
        let digest = hash.finalize().map { String(format: "%02x", $0) }.joined()
        guard digest == id, bytes == size else { throw HubError.integrity }
    }
}
struct DetailField: Identifiable {
    let id: String
    let value: String
}
struct RecordDetail {
    let id: String
    let source: String
    let kind: String
    let occurredAt: String?
    let observedAt: String?
    let timezone: String
    let fields: [DetailField]
    let assets: [ArchiveAsset]
    let rawJSON: String

    init(data: Data) throws {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = object["id"] as? String, let source = object["source"] as? String,
              let kind = object["kind"] as? String else { throw HubError.response }
        self.id = id; self.source = source; self.kind = kind
        occurredAt = object["occurred_at"] as? String; observedAt = object["observed_at"] as? String
        timezone = object["timezone"] as? String ?? ""
        var raw = object["raw"] as? [String: Any] ?? [:]
        if let bill = raw["bill"] as? [String: Any] { raw.merge(bill) { current, _ in current } }
        let normalized = object["normalized"] as? [String: Any] ?? [:]
        let readable = ["title", "subject", "sender", "content", "message", "summary", "name", "display_name", "body", "amount", "currency", "type", "remark", "duration_ms", "repo", "date", "state", "status", "upload_bytes", "download_bytes", "download_state", "validation_error", "device", "tokens", "estimated_cost_usd", "cache_read_tokens", "cache_write_tokens", "output_tokens"]
        var items: [DetailField] = readable.compactMap { key in
            guard let value = normalized[key] ?? raw[key], !(value is NSNull) else { return nil }
            if let text = value as? String, !text.isEmpty { return DetailField(id: key, value: text) }
            if let number = value as? NSNumber { return DetailField(id: key, value: number.stringValue) }
            return nil
        }
        if kind == "health_payloads", let payload = normalized["payload"] as? [String: Any] {
            for key in ["steps", "sleep", "heart_rate", "active_calories", "oxygen_saturation", "resting_heart_rate", "basal_metabolic_rate"] {
                guard let samples = payload[key] as? [Any], !samples.isEmpty else { continue }
                let json = try JSONSerialization.data(withJSONObject: samples, options: [.prettyPrinted, .sortedKeys])
                items.append(DetailField(id: "health_" + key, value: String(data: json, encoding: .utf8) ?? ""))
            }
        }
        fields = items
        let assetsData = try JSONSerialization.data(withJSONObject: object["assets"] ?? [])
        assets = try JSONDecoder().decode([ArchiveAsset].self, from: assetsData)
        rawJSON = String(data: try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys]), encoding: .utf8) ?? ""
    }
}
