import AppKit
import HubKit
import SwiftUI

/// Renders module content only when hub has data for it; otherwise an honest empty state.
struct HubGate<T: Codable & Sendable & Equatable, Content: View>: View {
    var envelope: HubEnvelope<T>?
    /// Shown when hub has not wired this source up yet.
    var unconfigured = "尚未接入"
    @ViewBuilder var content: (T) -> Content

    var body: some View {
        if let data = envelope?.data, envelope?.status.hasData ?? false {
            content(data)
        } else {
            switch envelope?.status {
            case .unconfigured: ModuleEmpty(symbol: "puzzlepiece.extension", text: unconfigured)
            case .error: ModuleEmpty(symbol: "exclamationmark.triangle", text: "来源暂时取不到数据")
            default: ModuleEmpty(symbol: "arrow.triangle.2.circlepath", text: "正在获取…")
            }
        }
    }
}

struct ModuleEmpty: View {
    var symbol: String
    var text: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: symbol).font(.system(size: 18, weight: .light)).foregroundStyle(Palette.ink4)
            Text(text).font(Typo.sans(12)).foregroundStyle(Palette.ink3).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 90, maxHeight: .infinity)
    }
}

/// Small header badge when a module's data is old, partial or failing.
struct HubBadge: View {
    var status: HubStatus

    var body: some View {
        switch status {
        case .stale: badge("缓存", .ochre)
        case .partial: badge("部分", .ochre)
        case .error: badge("故障", .rose)
        default: EmptyView()
        }
    }

    private func badge(_ text: String, _ tone: Tone) -> some View {
        Text(text).font(Typo.sans(10, .semibold)).foregroundStyle(tone.color)
            .padding(.horizontal, 6).padding(.vertical, 1.5)
            .background(Capsule().fill(tone.tint))
            .lineLimit(1).fixedSize()
    }
}

enum HubFormat {
    static let calendar = Calendar.hub
    /// Overridden by offscreen QA renders so relative times match the pinned moment.
    nonisolated(unsafe) static var current: () -> Date = { Date() }

    /// Header stamp: 17:56, 昨天 21:30 or 10/18.
    static func stamp(_ date: Date?, now: Date = HubFormat.current()) -> String? {
        guard let date else { return nil }
        if calendar.isDate(date, inSameDayAs: now) { return clock(date) }
        if let y = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: y) { return "昨天 " + clock(date) }
        return "\(calendar.component(.month, from: date))/\(calendar.component(.day, from: date))"
    }

    static func md(_ date: Date) -> String { "\(calendar.component(.month, from: date))/\(calendar.component(.day, from: date))" }

    static func ymd(_ date: Date) -> String { "\(calendar.component(.year, from: date))/" + md(date) }

    static func weekday(_ date: Date) -> String { "周" + ["日", "一", "二", "三", "四", "五", "六"][calendar.component(.weekday, from: date) - 1] }

    static func clock(_ date: Date) -> String {
        String(format: "%02d:%02d", calendar.component(.hour, from: date), calendar.component(.minute, from: date))
    }

    static func ago(_ date: Date?, now: Date = HubFormat.current()) -> String {
        guard let date else { return "" }
        let s = now.timeIntervalSince(date)
        if s < 60 { return "刚刚" }
        if s < 3600 { return "\(Int(s / 60)) 分钟前" }
        if calendar.isDate(date, inSameDayAs: now) { return "\(Int(s / 3600)) 小时前" }
        return (stamp(date, now: now) ?? "")
    }

    static func days(since date: Date?, now: Date = HubFormat.current()) -> Int? {
        guard let date else { return nil }
        return calendar.dateComponents([.day], from: calendar.startOfDay(for: date), to: calendar.startOfDay(for: now)).day
    }

    static func gb(_ bytes: Double?, _ decimals: Int = 1) -> String {
        guard let bytes else { return "—" }
        return String(format: "%.\(decimals)f", bytes / 1_073_741_824)
    }

    static func speed(_ bps: Double?) -> String? {
        guard let bps, bps > 0 else { return nil }
        return bps >= 1_048_576 ? String(format: "%.1f MB/s", bps / 1_048_576) : String(format: "%.0f KB/s", bps / 1024)
    }

    static func duration(_ seconds: Double?) -> String? {
        guard let seconds else { return nil }
        let s = Int(seconds.rounded()), h = s / 3600, m = s % 3600 / 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s % 60) : String(format: "%d:%02d", m, s % 60)
    }

    static func minutes(_ m: Double?) -> String {
        guard let m else { return "—" }
        let v = Int(m.rounded())
        return "\(v / 60)h\(v % 60)m"
    }

    static func int(_ v: Double?) -> String { v.map { Fmt.number($0.rounded()) } ?? "—" }

    /// A stable tone per person, so the same contact keeps its colour.
    static func tone(for key: String) -> Tone {
        let palette: [Tone] = [.sky, .steel, .kraft, .sage, .plum, .olive, .ochre, .rose]
        return palette[Int(seed(key)) % palette.count]
    }

    /// Stable across launches, unlike `hashValue`.
    static func seed(_ key: String) -> Int64 {
        Int64(key.unicodeScalars.reduce(0) { ($0 &* 31 &+ Int($1.value)) & 0xFFFF })
    }

    static func initial(_ name: String) -> String { String(name.first.map(String.init) ?? "·") }

    static func day(_ s: String?) -> Date? {
        guard let s else { return nil }
        let p = s.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return nil }
        return calendar.date(from: DateComponents(year: p[0], month: p[1], day: p[2]))
    }
}

/// Display names and icons for the bundle identifiers in computer history.
@MainActor
enum AppCatalog {
    private static var cache: [String: (name: String, icon: NSImage?)] = [:]

    static func info(_ bundle: String) -> (name: String, icon: NSImage?) {
        if let hit = cache[bundle] { return hit }
        var result: (String, NSImage?) = (fallbackName(bundle), nil)
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) {
            let name = FileManager.default.displayName(atPath: url.path).replacingOccurrences(of: ".app", with: "")
            result = (name, NSWorkspace.shared.icon(forFile: url.path))
        }
        cache[bundle] = result
        return result
    }

    private static func fallbackName(_ bundle: String) -> String {
        let known = ["com.todesktop.230313mzl4w4u92": "Cursor", "com.openai.codex": "Codex", "ru.keepcoder.Telegram": "Telegram", "md.obsidian": "Obsidian"]
        if let k = known[bundle] { return k }
        return bundle.split(separator: ".").last.map(String.init) ?? bundle
    }

    static func color(_ bundle: String) -> Color {
        HubFormat.tone(for: bundle).color
    }
}

struct AppIcons: View {
    var bundles: [String]
    var size: CGFloat = 14

    var body: some View {
        HStack(spacing: 4) {
            ForEach(bundles.prefix(8), id: \.self) { b in
                let info = AppCatalog.info(b)
                Group {
                    if let icon = info.icon {
                        Image(nsImage: icon).resizable().interpolation(.high)
                    } else {
                        RoundedRectangle(cornerRadius: 3).fill(AppCatalog.color(b))
                    }
                }
                .frame(width: size, height: size)
                .help(info.name)
            }
        }
    }
}

/// Poster or album cover loaded through hub-api; falls back to a tinted tile with the initial.
struct CoverImage: View {
    var ref: String?
    var title: String
    var tone: Tone = .plum
    @Environment(AppState.self) private var state

    var body: some View {
        let _ = state.hub.imageGeneration
        ZStack {
            if let image = state.hub.image(ref) {
                Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
            } else {
                LinearGradient(colors: [tone.tint, tone.color.opacity(0.75)], startPoint: .top, endPoint: .bottom)
                Text(String(title.prefix(1))).font(Typo.serif(30)).foregroundStyle(.white.opacity(0.5))
            }
        }
        .clipped()
    }
}
