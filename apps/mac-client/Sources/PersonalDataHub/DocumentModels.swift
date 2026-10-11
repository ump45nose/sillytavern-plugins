import Foundation

// Content IDs belong to the reading API; record IDs only belong to archive/evidence routes.
struct DocumentContent: Decodable, Identifiable {
    let id: String
    let type: String
    let variant: String
    let schema_version: Int
    let revision: Int
    let source: String
    let account: String
    let scope_key: String
    let occurred_at: String?
    let business_date: String?
    let timezone: String
    let title: String
    let preview: String
    let summary: String?
    let warnings: [String]
    let coverage: [String: String]
    let processing: DocumentProcessing
    let content: String
    let evidence: String
    let match: DocumentMatch?
    let metadata: DocumentMetadata?
    let assets: [ArchiveAsset]?

    var supported: Bool { type == "document" && schema_version == 1 && ["note", "daily_review", "execution_log"].contains(variant) }
    var ready: Bool { supported && revision > 0 && processing.state == "ready" }
    var readable: Bool { ready && metadata?.format == "markdown" }
    var stateLabel: String { supported ? processing.label : "当前客户端暂不支持" }
    var dateLabel: String {
        if let day = business_date, !day.isEmpty { return day }
        guard let occurred_at else { return "时间未提供" }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let zoned = parser.date(from: occurred_at) ?? ISO8601DateFormatter().date(from: occurred_at)
        let local = DateFormatter(); local.locale = Locale(identifier: "en_US_POSIX")
        local.timeZone = TimeZone(identifier: timezone) ?? .gmt
        local.dateFormat = occurred_at.contains(".") ? "yyyy-MM-dd'T'HH:mm:ss.SSSSSS" : "yyyy-MM-dd'T'HH:mm:ss"
        guard let date = zoned ?? local.date(from: occurred_at) else { return "时间未提供" }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}
struct DocumentProcessing: Decodable {
    let state: String
    let published_at: String?
    var label: String {
        ["pending": "等待整理", "running": "整理中", "ready": "已整理", "stale": "原件已更新，等待整理", "failed": "整理失败"][state] ?? "未知整理状态"
    }
}
struct DocumentMatch: Decodable { let ordinal: Int; let excerpt: String }
struct DocumentMetadata: Decodable {
    let record_id: String?
    let format: String?
    let body_chars: Int?
    let empty: Bool?
    let origin: String?
    let record_kind: String?
    let state: String?
    let pinned: Bool?
    let tags: [String]?
    let relations: [ReadingValue]?
    let source_ref: ReadingValue?
}
// Source relationships can evolve without becoming invented content links.
enum ReadingValue: Decodable {
    case string(String), number(Double), bool(Bool), array([ReadingValue]), object([String: ReadingValue]), null
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode([ReadingValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: ReadingValue].self)) }
    }
    var description: String {
        switch self {
        case .string(let v): return v
        case .number(let v): return v.formatted()
        case .bool(let v): return v ? "是" : "否"
        case .array(let v): return v.map(\.description).joined(separator: "、")
        case .object(let v): return v.keys.sorted().map { "\($0): \(v[$0]!.description)" }.joined(separator: " · ")
        case .null: return ""
        }
    }
}
struct DocumentPage: Decodable { let schema_version: Int; let items: [DocumentContent]; let next_cursor: String? }
struct DocumentBlock: Decodable, Identifiable {
    let key: String; let ordinal: Int; let type: String; let text: String
    let refs: [DocumentReference]; let metadata: ReadingValue
    var id: Int { ordinal }
}
struct DocumentReference: Decodable {
    let record_id: String; let input_hash: String; let field: String
    let char_start: Int; let char_end: Int
}
struct DocumentBlocks: Decodable { let id: String; let revision: Int; let blocks: [DocumentBlock]; let next_after: Int? }
struct DocumentEvidence: Decodable {
    let id: String; let revision: Int; let inputs: [DocumentInput]
}
struct DocumentInput: Decodable, Identifiable {
    let record_id: String; let input_hash: String; let current_hash: String?
    let current_matches: Bool; let record: String
    var id: String { record_id }
}
struct ProcessingStatus: Decodable {
    let schema_version: Int; let jobs: [String: Int]; let objects: [String: Int]; let profiles: [String: Int]
    let source_coverage: [ProcessingCoverage]; let errors: [ProcessingFailure]
}
struct ProcessingCoverage: Decodable {
    let source: String; let kind: String; let records: Int; let supported: Bool
}
struct ProcessingFailure: Decodable, Identifiable {
    let id: String; let source: String; let state: String; let error_code: String?
    let attempts: Int; let retry_at: String?
}
struct DocumentFilter: Equatable {
    var source = ""; var variant = ""; var query = ""
    var start: Date?; var end: Date?
    func parameters(cursor: String? = nil) -> [URLQueryItem] {
        var p = [URLQueryItem(name: "limit", value: "30")]
        for (key, value) in [("source", source), ("variant", variant), ("query", query)] where !value.isEmpty {
            p.append(URLQueryItem(name: key, value: value))
        }
        if let cursor { p.append(URLQueryItem(name: "cursor", value: cursor)) }
        if let start { p.append(URLQueryItem(name: "start", value: ISO8601DateFormatter().string(from: start))) }
        if let end { p.append(URLQueryItem(name: "end", value: ISO8601DateFormatter().string(from: end))) }
        return p
    }
}
struct DocumentSelection: Identifiable { let item: DocumentContent; let query: String; var id: String { item.id } }
