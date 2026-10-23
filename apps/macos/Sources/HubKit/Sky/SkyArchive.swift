import Foundation

/// One summary file from the local skysight-sync archive
/// (`archive/<device>/objects/<sha>/<UTC start>-<id>-<10min|6h>-memory-summary.md`).
public struct SkySummary: Sendable, Equatable, Identifiable {
    public enum Span: String, Sendable { case tenMinutes = "10min", sixHours = "6h" }
    public var id: String
    public var device: String
    public var span: Span
    public var start: Date
    public var title: String
    public var summary: String
    /// Bundle identifiers, in the order the summary lists them.
    public var apps: [String]

    public var end: Date { start.addingTimeInterval(span == .sixHours ? 6 * 3600 : 600) }
}

public struct SkyFile: Sendable, Equatable {
    public var device: String
    public var url: URL
    public var span: SkySummary.Span
    public var start: Date
    public var id: String
}

/// A 6-hour window with the 10-minute segments inside it.
public struct SkyWindowItem: Sendable, Equatable, Identifiable {
    public var id: String
    public var device: String
    public var start: Date, end: Date
    public var title: String
    public var summary: String
    /// No 6-hour summary yet; title and summary come from the latest segment.
    public var inProgress: Bool
    public var segments: [SkySummary]
    /// Share of segments each app appears in, highest first.
    public var apps: [(bundle: String, share: Double)]

    public static func == (a: Self, b: Self) -> Bool { a.id == b.id && a.segments == b.segments && a.title == b.title }
}

public enum SkyArchive {
    public static let root = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex/skysight-sync/archive")
    /// Where Skysight writes this Mac's summaries as they happen; the archive only receives them at the next daily sync.
    public static let live = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex/memories/extensions/skysight/resources")
    public static let config = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex/skysight-sync/config.json")

    /// This Mac's device name in the archive, from skysight-sync's config.
    public static func localDevice(config: URL = config) -> String? {
        guard let data = try? Data(contentsOf: config),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return object["device_id"] as? String
    }

    /// Windows from the most recent local days that have data, newest first. This Mac's live
    /// summaries are merged in, so today shows up before the daily sync has run.
    public static func load(root: URL = root, live: URL? = live, liveDevice: String? = localDevice(),
                            calendar: Calendar = .hub, days: Int = 2) -> [SkyWindowItem] {
        let files = index(root: root, live: live, liveDevice: liveDevice)
        guard let oldest = self.days(files, calendar: calendar).prefix(days).last else { return [] }
        return windows(parse(files.filter { $0.start >= oldest.addingTimeInterval(-6 * 3600) }))
            .filter { $0.start >= oldest || $0.end > oldest }
    }

    /// Every summary file, from names alone; contents are read per day with `load(_:day:)`.
    public static func index(root: URL = root, live: URL? = live, liveDevice: String? = localDevice()) -> [SkyFile] {
        let fm = FileManager.default
        var files: [SkyFile] = []
        var seen = Set<String>()
        func add(_ device: String, _ url: URL) {
            guard url.pathExtension == "md", let (start, span, id) = parseName(url.lastPathComponent),
                  seen.insert(device + "/" + id).inserted else { return }
            files.append(SkyFile(device: device, url: url, span: span, start: start, id: id))
        }
        for device in (try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)) ?? [] where !device.lastPathComponent.hasPrefix(".") {
            guard let e = fm.enumerator(at: device.appendingPathComponent("objects"), includingPropertiesForKeys: nil) else { continue }
            for case let url as URL in e { add(device.lastPathComponent, url) }
        }
        if let live, let liveDevice {
            for url in (try? fm.contentsOfDirectory(at: live, includingPropertiesForKeys: nil)) ?? [] { add(liveDevice, url) }
        }
        return files
    }

    /// Local days that have at least one summary, newest first.
    public static func days(_ files: [SkyFile], calendar: Calendar = .hub) -> [Date] {
        Set(files.map { calendar.startOfDay(for: $0.start) }).sorted(by: >)
    }

    /// 10-minute segments per local day, from names alone: a cheap activity level for the date picker.
    public static func activity(_ files: [SkyFile], calendar: Calendar = .hub) -> [Date: Int] {
        var out: [Date: Int] = [:]
        var seen = Set<String>()
        for f in files where f.span == .tenMinutes && seen.insert(f.device + "/" + f.id).inserted {
            out[calendar.startOfDay(for: f.start), default: 0] += 1
        }
        return out
    }

    /// The windows that start on `day`, with their segments (a window from the evening before can spill in).
    public static func load(_ files: [SkyFile], day: Date, calendar: Calendar = .hub) -> [SkyWindowItem] {
        let start = calendar.startOfDay(for: day), end = calendar.date(byAdding: .day, value: 1, to: start)!
        let picked = files.filter { $0.start >= start.addingTimeInterval(-6 * 3600) && $0.start < end }
        return windows(parse(picked)).filter { calendar.isDate($0.start, inSameDayAs: start) }
    }

    static func parse(_ files: [SkyFile]) -> [SkySummary] {
        files.compactMap { f in
            guard let text = try? String(contentsOf: f.url, encoding: .utf8) else { return nil }
            return parse(text, id: f.device + "/" + f.id, device: f.device, span: f.span, start: f.start)
        }
    }

    public static func windows(_ summaries: [SkySummary]) -> [SkyWindowItem] {
        var out: [SkyWindowItem] = []
        let byDevice = Dictionary(grouping: summaries, by: \.device)
        for (device, items) in byDevice {
            let segments = items.filter { $0.span == .tenMinutes }.sorted { $0.start < $1.start }
            var covered = Set<String>()
            for w in items where w.span == .sixHours {
                let inside = segments.filter { $0.start >= w.start && $0.start < w.end }
                inside.forEach { covered.insert($0.id) }
                out.append(item(id: w.id, device: device, start: w.start, end: w.end, title: w.title, summary: w.summary,
                                inProgress: false, segments: inside, fallbackApps: w.apps))
            }
            // Segments newer than the last 6-hour summary form the window still in progress.
            let lastClosed = items.filter { $0.span == .sixHours }.map(\.end).max() ?? .distantPast
            let open = segments.filter { !covered.contains($0.id) && $0.start >= lastClosed }
            if let latest = open.last, let first = open.first {
                out.append(item(id: device + "/open", device: device, start: first.start, end: latest.end, title: latest.title, summary: latest.summary,
                                inProgress: true, segments: open, fallbackApps: latest.apps))
            }
        }
        return out.sorted { $0.end != $1.end ? $0.end > $1.end : $0.device < $1.device }
    }

    /// Always-running system processes that say nothing about what the window was spent on.
    static let ignoredApps: Set<String> = [
        "com.apple.dock", "com.apple.loginwindow", "com.apple.WindowManager", "com.apple.controlcenter",
        "com.apple.notificationcenterui", "com.apple.Spotlight", "com.apple.systemuiserver", "com.apple.finder",
    ]

    private static func item(id: String, device: String, start: Date, end: Date, title: String, summary: String,
                             inProgress: Bool, segments: [SkySummary], fallbackApps: [String]) -> SkyWindowItem {
        var counts: [String: Int] = [:]
        for s in segments { for a in Set(s.apps) where !ignoredApps.contains(a) { counts[a, default: 0] += 1 } }
        let fallbackApps = fallbackApps.filter { !ignoredApps.contains($0) }
        let apps: [(String, Double)] = counts.isEmpty
            ? fallbackApps.map { ($0, 1 / Double(max(fallbackApps.count, 1))) }
            : counts.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }.map { ($0.key, Double($0.value) / Double(segments.count)) }
        return SkyWindowItem(id: id, device: device, start: start, end: end, title: title, summary: summary,
                             inProgress: inProgress, segments: segments, apps: apps)
    }

    nonisolated(unsafe) private static let stampFormatter = ISO8601DateFormatter()

    /// `2026-10-13T03-40-00-hNeq-10min-memory-summary.md` → UTC start, span, id.
    static func parseName(_ name: String) -> (Date, SkySummary.Span, String)? {
        let parts = name.split(separator: "-")
        guard parts.count >= 7, parts.suffix(2) == ["memory", "summary.md"] else { return nil }
        guard let span = SkySummary.Span(rawValue: String(parts[parts.count - 3])) else { return nil }
        let stamp = parts[0...2].joined(separator: "-") + ":" + parts[3] + ":" + parts[4] + "Z"
        guard let start = stampFormatter.date(from: stamp) else { return nil }
        return (start, span, String(name.dropLast(3)))
    }

    static func parse(_ text: String, id: String, device: String, span: SkySummary.Span, start: Date) -> SkySummary? {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard lines.first == "---", let close = lines.dropFirst().firstIndex(of: "---") else { return nil }
        var fields: [String: String] = [:]
        for line in lines[1..<close] {
            guard let colon = line.firstIndex(of: ":") else { continue }
            fields[String(line[..<colon]).trimmingCharacters(in: .whitespaces)] = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
        }
        func unquote(_ s: String?) -> String {
            guard var s, !s.isEmpty else { return "" }
            if s.count >= 2, let f = s.first, f == s.last, f == "\"" || f == "'" { s = String(s.dropFirst().dropLast()) }
            return s
        }
        let apps = unquote(fields["applications"]).trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .split(separator: ",").map { unquote($0.trimmingCharacters(in: .whitespaces)) }.filter { !$0.isEmpty }
        let title = unquote(fields["title"])
        guard !title.isEmpty else { return nil }
        return SkySummary(id: id, device: device, span: span, start: start, title: title, summary: unquote(fields["description"]), apps: apps)
    }

    /// Demo windows for when there is no local archive.
    public static func sample(now: Date, calendar: Calendar = .hub) -> [SkyWindowItem] {
        let today = calendar.startOfDay(for: now)
        func at(_ h: Double, _ day: Int = 0) -> Date { calendar.date(byAdding: .day, value: day, to: today)!.addingTimeInterval(h * 3600) }
        let rows: [(String, Double, Double, Int, String, String, [String])] = [
            ("macpro", 12, 18, 0, "个人信息中心详细设计", "在 Cursor 中重做模块与主页设计，绘制 logo，并核对 NAS 上 personal-review 的阶段模型。", ["com.todesktop.230313mzl4w4u92", "com.google.Chrome", "com.apple.Terminal", "com.openai.codex"]),
            ("macpro", 6, 12, 0, "Hermes 日报投递故障修复", "定位 Telegram 代理节点超时，切换 selector 后验证 getMe；CRM 读取改为本机 API。", ["com.apple.Terminal", "ru.keepcoder.Telegram", "com.google.Chrome"]),
            ("macair", 6, 12, 0, "阅读与资料整理", "浏览 Google Tasks API 文档和几个桌面客户端仓库，记录接口限制。", ["com.google.Chrome", "md.obsidian"]),
            ("macpro", 18, 24, -1, "Plaud 归档布局迁移", "迁移旧 transcript.md 布局，修正音频相对链接并补测试。", ["com.todesktop.230313mzl4w4u92", "com.apple.Terminal", "com.google.Chrome"]),
            ("macpro", 12, 18, -1, "personal-records 部署", "迁移 Health 与账单数据到独立 SQLite，核对审计报告。", ["com.todesktop.230313mzl4w4u92", "com.apple.Terminal", "com.google.Chrome"]),
        ]
        let segmentTitles = ["整理模块规格与布局", "核对设计稿截图并修正排版", "查阅接口文档与限制", "提交并推送改动"]
        var summaries: [SkySummary] = []
        for (i, r) in rows.enumerated() {
            summaries.append(SkySummary(id: "s\(i)", device: r.0, span: .sixHours, start: at(r.1, r.3), title: r.4, summary: r.5, apps: r.6))
            for k in 0..<4 {
                summaries.append(SkySummary(id: "s\(i)-\(k)", device: r.0, span: .tenMinutes, start: at(r.1 + Double(k) * 0.5 + 0.17, r.3),
                                            title: segmentTitles[k], summary: "", apps: Array(r.6.prefix(max(1, r.6.count - k % 2)))))
            }
        }
        return windows(summaries)
    }
}
