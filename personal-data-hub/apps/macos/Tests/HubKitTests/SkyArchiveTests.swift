import Foundation
import Testing
@testable import HubKit

@Suite struct SkyArchiveTests {
    private let utc = ISO8601DateFormatter()

    @Test func parsesFileNames() throws {
        let (start, span, id) = try #require(SkyArchive.parseName("2026-10-13T03-40-00-hNeq-10min-memory-summary.md"))
        #expect(start == utc.date(from: "2026-10-13T03:40:00Z"))
        #expect(span == .tenMinutes)
        #expect(id == "2026-10-13T03-40-00-hNeq-10min-memory-summary")
        #expect(SkyArchive.parseName("2026-10-13T00-00-00-Ab12-6h-memory-summary.md")?.1 == .sixHours)
        #expect(SkyArchive.parseName("README.md") == nil)
        #expect(SkyArchive.parseName("2026-10-13T00-00-00-Ab12-1d-memory-summary.md") == nil)
    }

    @Test func parsesFrontMatter() throws {
        let text = """
        ---
        title: "Fix Telegram proxy: switch selector"
        description: Located the timeout and verified getMe.
        applications: ["com.apple.Terminal", 'ru.keepcoder.Telegram']
        suggestion: none
        ---

        Body text that is not shown.
        """
        let s = try #require(SkyArchive.parse(text, id: "x", device: "macpro", span: .sixHours, start: Date(timeIntervalSince1970: 0)))
        #expect(s.title == "Fix Telegram proxy: switch selector")
        #expect(s.summary == "Located the timeout and verified getMe.")
        #expect(s.apps == ["com.apple.Terminal", "ru.keepcoder.Telegram"])
        #expect(s.end == Date(timeIntervalSince1970: 6 * 3600))
        #expect(SkyArchive.parse("no front matter", id: "y", device: "d", span: .tenMinutes, start: Date()) == nil)
    }

    @Test func groupsSegmentsIntoWindowsAndKeepsAnOpenOne() throws {
        let base = try #require(utc.date(from: "2026-10-19T00:00:00Z"))
        func seg(_ minutes: Double, _ apps: [String], device: String = "macpro") -> SkySummary {
            SkySummary(id: "\(device)-\(minutes)", device: device, span: .tenMinutes, start: base.addingTimeInterval(minutes * 60),
                       title: "seg \(Int(minutes))", summary: "", apps: apps)
        }
        let summaries = [
            SkySummary(id: "w", device: "macpro", span: .sixHours, start: base, title: "Morning", summary: "s", apps: ["a"]),
            seg(10, ["a", "b"]), seg(20, ["a"]), seg(30, ["a", "c"]), seg(40, ["b"]),
            seg(400, ["c"]), seg(410, ["c", "a"]),
            seg(15, ["z"], device: "macair"),
        ]
        let windows = SkyArchive.windows(summaries)
        let closed = try #require(windows.first { $0.id == "w" })
        #expect(closed.segments.count == 4)
        #expect(closed.apps.first?.bundle == "a")
        #expect(closed.apps.first?.share == 0.75)
        #expect(!closed.inProgress)

        let open = try #require(windows.first { $0.id == "macpro/open" })
        #expect(open.inProgress)
        #expect(open.segments.map(\.title) == ["seg 400", "seg 410"])
        #expect(open.title == "seg 410")
        #expect(open.apps.first?.bundle == "c")
        #expect(windows.first?.id == "macpro/open", "newest first")
        #expect(windows.contains { $0.device == "macair" && $0.inProgress }, "a device with only segments still shows up")
    }

    @Test func loadsOnlyTheMostRecentDaysFromDisk() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("sky-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: root) }
        func write(_ device: String, _ name: String, _ title: String) throws {
            let dir = root.appendingPathComponent("\(device)/objects/\(UUID().uuidString.prefix(8))")
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            try "---\ntitle: \(title)\ndescription: d\napplications: []\n---\n".write(to: dir.appendingPathComponent(name), atomically: true, encoding: .utf8)
        }
        try write("macpro", "2026-10-15T02-00-00-aaaa-6h-memory-summary.md", "old")
        try write("macpro", "2026-10-18T02-00-00-bbbb-6h-memory-summary.md", "day before")
        try write("macair", "2026-10-19T02-00-00-cccc-6h-memory-summary.md", "latest")
        try write("macair", "2026-10-19T02-00-00-cccc-6h-notes.md", "ignored")
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let windows = SkyArchive.load(root: root, live: nil, calendar: calendar)
        #expect(windows.map(\.title) == ["latest", "day before"])
        #expect(SkyArchive.load(root: root.appendingPathComponent("missing"), live: nil).isEmpty)

        let files = SkyArchive.index(root: root, live: nil)
        #expect(files.count == 3)
        let days = SkyArchive.days(files, calendar: calendar)
        #expect(days.count == 3)
        #expect(SkyArchive.load(files, day: days[2], calendar: calendar).map(\.title) == ["old"], "older days load on demand")
    }

    @Test func liveSummariesFillInTodayForThisMac() throws {
        let base = FileManager.default.temporaryDirectory.appendingPathComponent("sky-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: base) }
        let root = base.appendingPathComponent("archive"), live = base.appendingPathComponent("live")
        let archived = root.appendingPathComponent("macair/objects/x")
        try FileManager.default.createDirectory(at: archived, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: live, withIntermediateDirectories: true)
        func summary(_ title: String) -> String { "---\ntitle: \(title)\ndescription: a: b\napplications: []\n---\n" }
        try summary("yesterday").write(to: archived.appendingPathComponent("2026-10-19T02-00-00-aaaa-6h-memory-summary.md"), atomically: true, encoding: .utf8)
        try summary("yesterday").write(to: live.appendingPathComponent("2026-10-19T02-00-00-aaaa-6h-memory-summary.md"), atomically: true, encoding: .utf8)
        try summary("this morning").write(to: live.appendingPathComponent("2026-10-21T01-00-00-bbbb-10min-memory-summary.md"), atomically: true, encoding: .utf8)
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let windows = SkyArchive.load(root: root, live: live, liveDevice: "macair", calendar: calendar)
        #expect(windows.map(\.title) == ["this morning", "yesterday"])
        #expect(windows.first?.inProgress == true)
        #expect(windows.last?.segments.isEmpty == true, "the copy in both places counts once")
    }

    @Test func sampleHasTodayAndYesterday() {
        let now = Date()
        let windows = SkyArchive.sample(now: now)
        #expect(windows.contains { Calendar.hub.isDate($0.start, inSameDayAs: now) })
        #expect(windows.allSatisfy { !$0.segments.isEmpty })
    }
}
