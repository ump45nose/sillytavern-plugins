import Foundation

/// A Plaud transcript.md split into blocks, with speaker turns pulled out so each speaker can be coloured.
public enum TranscriptBlock: Equatable, Sendable {
    case heading(level: Int, text: String)
    case turn(speaker: String, time: String?, text: String)
    case quote(String)
    case bullet(String)
    case paragraph(String)
    case rule
}

public enum Transcript {
    private static let time = #"(\d{1,2}:\d{2}(?::\d{2})?)"#
    /// `[19:57] 【我】文本` from the fused transcript; the colon is optional.
    private static let fused = try! NSRegularExpression(pattern: #"^(?:[-*]\s*)?\["# + time + #"\]\s*【([^】]{1,12})】\s*[:：]?\s*(.*)$"#)
    /// `[00:12] Speaker 1: 文本` or `- [00:12] 李雷：文本`.
    private static let timed = try! NSRegularExpression(pattern: #"^(?:[-*]\s*)?\["# + time + #"\]\s*([^:：\[\]【】]{1,24}?)\s*[:：]\s*(.+)$"#)
    /// `**00:01:02 Speaker 1**` on its own line; the following lines are that speaker's.
    private static let header = try! NSRegularExpression(pattern: #"^\*\*\s*"# + time + #"\s+([^*]{1,24}?)\s*\*\*\s*$"#)
    /// `【我】文本` without a time. Bold labels such as `**决定**：` stay ordinary text.
    private static let named = try! NSRegularExpression(pattern: #"^(?:[-*]\s*)?【([^】]{1,12})】\s*[:：]?\s*(.+)$"#)
    private static let ordered = try! NSRegularExpression(pattern: #"^\d{1,3}[.)、]\s+(.+)$"#)

    public static func parse(_ markdown: String) -> [TranscriptBlock] {
        var out: [TranscriptBlock] = []
        var paragraph: [String] = []
        var speaker: (name: String, time: String)?
        var speakerOpen = false

        func flush() {
            guard !paragraph.isEmpty else { return }
            out.append(.paragraph(paragraph.joined(separator: "\n")))
            paragraph = []
        }

        for raw in markdown.components(separatedBy: .newlines) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { flush(); continue }
            if let m = match(fused, line) ?? match(timed, line) {
                flush(); speaker = nil
                out.append(.turn(speaker: m[2], time: m[1], text: m[3]))
                continue
            }
            if let m = match(header, line) {
                flush()
                speaker = (m[2], m[1]); speakerOpen = false
                continue
            }
            if let m = match(named, line) {
                flush(); speaker = nil
                out.append(.turn(speaker: m[1], time: nil, text: m[2]))
                continue
            }
            if let level = heading(line) {
                flush(); speaker = nil
                out.append(.heading(level: level, text: String(line.drop { $0 == "#" }).trimmingCharacters(in: .whitespaces)))
                continue
            }
            if line.allSatisfy({ $0 == "-" || $0 == "*" || $0 == "_" }), line.count >= 3 {
                flush(); speaker = nil
                out.append(.rule)
                continue
            }
            if line.hasPrefix(">") {
                flush()
                let text = line.drop { $0 == ">" }.trimmingCharacters(in: .whitespaces)
                if case .quote(let prev)? = out.last { out[out.count - 1] = .quote(prev + "\n" + text) } else { out.append(.quote(text)) }
                continue
            }
            if let s = speaker {
                flush()
                if speakerOpen, case .turn(let name, let t, let prev)? = out.last {
                    out[out.count - 1] = .turn(speaker: name, time: t, text: prev + "\n" + line)
                } else {
                    out.append(.turn(speaker: s.name, time: s.time, text: line))
                    speakerOpen = true
                }
                continue
            }
            if line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("+ ") {
                flush()
                out.append(.bullet(String(line.dropFirst(2))))
                continue
            }
            if let m = match(ordered, line) {
                flush()
                out.append(.bullet(m[1]))
                continue
            }
            paragraph.append(line)
        }
        flush()
        return out
    }

    /// Speakers in order of first appearance.
    public static func speakers(_ blocks: [TranscriptBlock]) -> [String] {
        var seen: [String] = []
        for case .turn(let s, _, _) in blocks where !seen.contains(s) { seen.append(s) }
        return seen
    }

    /// The fused transcript's「我」/「我?」 is the owner of the recorder.
    public static func isSelf(_ speaker: String) -> Bool {
        speaker == "我" || speaker == "我?" || speaker.lowercased() == "me"
    }

    private static func heading(_ line: String) -> Int? {
        let hashes = line.prefix { $0 == "#" }.count
        guard (1...6).contains(hashes), line.dropFirst(hashes).first == " " else { return nil }
        return hashes
    }

    private static func match(_ re: NSRegularExpression, _ line: String) -> [String]? {
        let ns = line as NSString
        guard let m = re.firstMatch(in: line, range: NSRange(location: 0, length: ns.length)) else { return nil }
        return (0..<m.numberOfRanges).map { m.range(at: $0).location == NSNotFound ? "" : ns.substring(with: m.range(at: $0)) }
    }
}

/// One page of `GET /api/v1/recordings?source=plaud`, newest day first.
public struct PlaudList: Codable, Equatable, Sendable {
    public struct Recording: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var title: String?
        public var startAt: Date?
        public var durationSeconds: Double?

        public init(id: String, title: String?, startAt: Date?, durationSeconds: Double?) {
            self.id = id
            self.title = title
            self.startAt = startAt
            self.durationSeconds = durationSeconds
        }
    }
    public struct Day: Codable, Equatable, Sendable, Identifiable {
        public var date: String
        public var recordings: [Recording]
        public var hasTranscript: Bool?
        public var people: [String]?

        public var id: String { date }

        public init(date: String, recordings: [Recording], hasTranscript: Bool? = nil, people: [String]? = nil) {
            self.date = date
            self.recordings = recordings
            self.hasTranscript = hasTranscript
            self.people = people
        }
    }
    public var days: [Day]
    public var nextBefore: String?

    public init(days: [Day], nextBefore: String? = nil) {
        self.days = days
        self.nextBefore = nextBefore
    }
}
