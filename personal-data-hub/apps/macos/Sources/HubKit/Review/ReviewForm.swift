import Foundation

/// The daily review template as editable fields. The template comes from personal-review and stays
/// authoritative: field order, blank lines and the header are kept, so the rendered text is exactly
/// what the Telegram flow would hand to `finalize`.
public struct ReviewForm: Codable, Equatable, Sendable {
    public enum Line: Codable, Equatable, Sendable {
        case text(String)
        case field(String)
    }

    public static let summaryLabel = "一句话总结今天"

    public var header: String
    public var lines: [Line]
    public var values: [String: String] = [:]

    public init(template: String) {
        let rows = template.components(separatedBy: "\n")
        header = rows.first?.trimmingCharacters(in: .whitespaces) ?? ""
        lines = rows.dropFirst().map { row in
            let t = row.trimmingCharacters(in: .whitespaces)
            if t.hasSuffix("："), let label = t.split(separator: "：", maxSplits: 1).first, !label.isEmpty,
               !label.contains(" "), !label.hasPrefix("-"), !label.hasPrefix("#") {
                return .field(String(label))
            }
            return .text(row)
        }
    }

    public var labels: [String] {
        lines.compactMap { if case .field(let l) = $0 { l } else { nil } }
    }

    public subscript(label: String) -> String {
        get { values[label] ?? "" }
        set { values[label] = newValue }
    }

    /// Fields are single lines in the ledger; auto fields stay blank for personal-review to fill.
    public func content(auto: Set<String> = []) -> String {
        var out = [header]
        for line in lines {
            switch line {
            case .text(let t): out.append(t)
            case .field(let label):
                let value = auto.contains(label) ? "" : Self.oneLine(self[label])
                out.append("\(label)：\(value)")
            }
        }
        return out.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    public var isEmpty: Bool { values.values.allSatisfy { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty } }

    static func oneLine(_ s: String) -> String {
        s.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }.joined(separator: " ")
    }

    // MARK: Checks

    public struct Issue: Equatable, Sendable {
        public var field: String?
        public var message: String

        public init(field: String?, message: String) {
            self.field = field
            self.message = message
        }
    }

    /// The cheap subset of personal-review's checks, for instant feedback; preview stays authoritative.
    public func issues(rules: ReviewSession.Rules?) -> [Issue] {
        var out: [Issue] = []
        let summary = Self.oneLine(self[Self.summaryLabel])
        if labels.contains(Self.summaryLabel), summary.isEmpty {
            out.append(Issue(field: Self.summaryLabel, message: "日报必须包含一句话总结"))
        }
        if let max = rules?.summaryMaxChars, Self.length(summary) > max {
            out.append(Issue(field: Self.summaryLabel, message: "一句话总结不能超过 \(max) 个字符"))
        }
        if let max = rules?.summaryMaxListSeparators, Self.separators(summary) > max {
            out.append(Issue(field: Self.summaryLabel, message: "一句话总结不能写成事项清单"))
        }
        if let max = rules?.maxUnresolved, Self.unresolved(Self.oneLine(self["未解"])) > max {
            out.append(Issue(field: "未解", message: "日报未解项不能超过两项"))
        }
        let moment = Self.oneLine(self["瞬间"])
        if let min = rules?.momentMinChars, !moment.isEmpty, Self.length(moment) < min {
            out.append(Issue(field: "瞬间", message: "瞬间必须包含可重现的场景、动作或感官细节"))
        }
        return out
    }

    /// Python's `len`: code points, not grapheme clusters.
    public static func length(_ s: String) -> Int { s.unicodeScalars.count }

    public static func separators(_ s: String) -> Int { s.filter { $0 == "；" || $0 == "、" }.count }

    /// Mirrors personal-review: `[` marks items, otherwise any value is one.
    public static func unresolved(_ s: String) -> Int {
        guard !s.isEmpty else { return 0 }
        return s.contains("[") ? max(1, s.filter { $0 == "[" }.count) : 1
    }
}
