import Foundation
import SwiftUI

enum JSONValue: Codable {
    case string(String), number(Double), bool(Bool), object([String: JSONValue]), array([JSONValue]), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let x = try? c.decode(String.self) { self = .string(x) }
        else if let x = try? c.decode(Double.self) { self = .number(x) }
        else if let x = try? c.decode(Bool.self) { self = .bool(x) }
        else if let x = try? c.decode([String: JSONValue].self) { self = .object(x) }
        else { self = .array(try c.decode([JSONValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .string(let x): try c.encode(x)
        case .number(let x): try c.encode(x)
        case .bool(let x): try c.encode(x)
        case .object(let x): try c.encode(x)
        case .array(let x): try c.encode(x)
        case .null: try c.encodeNil()
        }
    }
    var text: String { if case .string(let v) = self { return v }; return "" }
    var numeric: Double? { if case .number(let v) = self { return v }; return Double(text) }
    var object: [String: JSONValue] { if case .object(let v) = self { return v }; return [:] }
}
struct DisplayMetric: Codable, Identifiable {
    let id: String
    let label: String
    let value: JSONValue
    let unit: String
    let date: String
    let updated_at: String?
    let record_ids: [String]
    var number: Double? { value.numeric }
    var formatted: String {
        guard let n = number else { return "—" }
        if unit == "bytes" { return ByteCountFormatter.string(fromByteCount: Int64(n), countStyle: .file) }
        if unit == "tokens", n > 1_000_000 { return String(format: "%.1f M", n/1_000_000) }
        if unit == "tokens", n > 1000 { return String(format: "%.1f K", n/1000) }
        return n.formatted(.number.precision(.fractionLength(0...2)))
    }
}
struct DisplayCard: Codable, Identifiable {
    let id: String
    let source: String
    let kind: String
    let domain: String
    let occurred_at: String?
    let observed_at: String
    let title: String
    let preview: String
    let subtitle: String
    let metadata: [String: JSONValue]
}
struct DisplayModule: Codable, Identifiable {
    let id: String
    let metrics: [DisplayMetric]
    let items: [DisplayCard]
    let updated_at: String?
}
struct Dashboard: Codable {
    let date: String
    let timezone: String
    let modules: [DisplayModule]
}
struct TrendPage: Codable { let days: [Dashboard] }
struct TimelinePage: Codable { let items: [DisplayCard]; let next_cursor: String? }

let moduleLabels = ["agenda": "日程与任务", "health": "健康", "social": "最近交流", "activity": "电脑活动",
                    "recordings": "录音", "reports": "执行日报", "mail": "邮件", "git": "Git 进展",
                    "notes": "笔记与记忆", "finance": "财务", "usage": "AI 用量", "network": "网络流量"]
let moduleIcons = ["agenda": "calendar", "health": "heart", "social": "person.2", "activity": "desktopcomputer",
                   "recordings": "waveform", "reports": "doc.text", "mail": "envelope", "git": "chevron.left.forwardslash.chevron.right",
                   "notes": "note.text", "finance": "creditcard", "usage": "sparkles", "network": "network"]
let metricCatalogue: [String: [(String, String)]] = [
    "agenda": [("events", "日程"), ("tasks", "任务")],
    "health": [("steps", "步数"), ("sleep", "睡眠"), ("resting_heart_rate", "静息心率"), ("active_calories", "活动热量")],
    "social": [("interactions", "交流记录"), ("people", "交流人数")],
    "finance": [("expense", "支出"), ("income", "收入"), ("transfer", "转账"), ("pending", "待确认")],
    "usage": [("tokens", "Token"), ("estimated_cost_usd", "估算费用")],
    "network": [("upload_bytes", "上传"), ("download_bytes", "下载")]
]
struct ModulePreference: Codable, Identifiable {
    let id: String
    var enabled: Bool
    var metrics: [String]
}
struct UIPreferences: Codable {
    var modules: [ModulePreference] = ["agenda", "health", "social", "activity", "recordings", "reports", "mail", "git", "notes", "finance", "usage", "network"].map {
        ModulePreference(id: $0, enabled: ["agenda", "health", "social"].contains($0), metrics: $0 == "health" ? ["steps", "sleep", "resting_heart_rate"] : (metricCatalogue[$0]?.map { $0.0 } ?? ["count"]))
    }
    var hotkeyCode: UInt32 = 49
    var hotkeyModifiers: UInt32 = 6144 // controlKey | optionKey
    var hotkeyLabel = "⌃⌥Space"
    var enabled: [String] { modules.filter(\.enabled).map(\.id) }
    static let path = Connection.directory.appendingPathComponent("ui-preferences.json")
    static func load() -> UIPreferences {
        (try? JSONDecoder().decode(Self.self, from: Data(contentsOf: path))) ?? Self()
    }
    func save() {
        do {
            try FileManager.default.createDirectory(at: Connection.directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            try JSONEncoder().encode(self).write(to: Self.path, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: Self.path.path)
        } catch { }
    }
}
func dayKey(_ date: Date) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = .current
    return f.string(from: date)
}
