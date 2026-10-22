import HubKit
import SwiftUI
import WebKit

// MARK: - 电脑历史

enum SkyText {
    /// Still being recorded: no 6-hour summary yet and a segment within the last half hour.
    static func live(_ w: SkyWindowItem) -> Bool {
        w.inProgress && HubFormat.current().timeIntervalSince(w.end) < 30 * 60
    }

    static func span(_ w: SkyWindowItem) -> String {
        "\(HubFormat.clock(w.start)) – \(live(w) ? "现在" : HubFormat.clock(w.end))"
    }

    static func badge(_ w: SkyWindowItem) -> String? {
        live(w) ? "进行中" : w.inProgress ? "未汇总" : nil
    }

    static func day(_ date: Date, now: Date = HubFormat.current()) -> String {
        let c = Calendar.hub, md = "\(c.component(.month, from: date)) 月 \(c.component(.day, from: date)) 日"
        if c.isDate(date, inSameDayAs: now) { return "今天 · " + md }
        if let y = c.date(byAdding: .day, value: -1, to: now), c.isDate(date, inSameDayAs: y) { return "昨天 · " + md }
        return md
    }

    static func device(_ id: String) -> String {
        ["macpro": "MacBook Pro", "macair": "MacBook Air"][id] ?? id
    }
}

struct SkyModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let all = state.hub.sky
        let latestDay = all.first.map { Calendar.hub.startOfDay(for: $0.start) }
        let today = all.filter { w in latestDay.map { Calendar.hub.isDate(w.start, inSameDayAs: $0) } ?? false }
        if let s = today.first {
            if size == .compact {
                VStack(alignment: .leading, spacing: 0) {
                    Label11("\(SkyText.span(s)) · \(s.device)")
                    Text(s.title).font(Typo.sans(13.5, .semibold)).lineLimit(1).padding(.top, 5)
                    Text(s.summary).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineSpacing(2).lineLimit(2).padding(.top, 4)
                    Spacer(minLength: 6)
                    HStack(spacing: 4) {
                        AppIcons(bundles: s.apps.map(\.bundle), size: 13)
                        Text("\(Calendar.hub.isDate(s.start, inSameDayAs: HubFormat.current()) ? "今日" : SkyText.day(s.start)) \(today.count) 个窗口")
                            .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.leading, 6)
                    }
                }
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(today.prefix(5).enumerated()), id: \.1.id) { i, s in
                        HStack(alignment: .top, spacing: 14) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(HubFormat.clock(s.start)); Text(SkyText.live(s) ? "现在" : HubFormat.clock(s.end))
                                Text(s.device).foregroundStyle(Palette.ink4)
                            }
                            .font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 52, alignment: .leading)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(s.title).font(Typo.sans(13, .semibold))
                                Text(s.summary).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).lineSpacing(2).lineLimit(4)
                                    .fixedSize(horizontal: false, vertical: true)
                                AppIcons(bundles: s.apps.map(\.bundle))
                            }
                        }
                        .padding(.vertical, 10)
                        .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                        .rise(i)
                    }
                    Button { state.go("sky") } label: { Chip(text: "打开电脑历史 →") }.buttonStyle(.plain).padding(.top, 12)
                }
            }
        } else {
            ModuleEmpty(symbol: "desktopcomputer", text: "本机还没有电脑历史归档")
        }
    }
}

// MARK: - Memos

struct MemosModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        HubGate(envelope: state.hub.data.memos) { d in
            let memos = d.recent ?? []
            if size == .compact {
                VStack(alignment: .leading, spacing: 0) {
                    Button { state.showQuickMemo() } label: { MiniInput(placeholder: "记一条…", shortcut: HotKeyCenter.shared.display(.quickMemo), icon: nil) }.buttonStyle(.plain)
                    if let m = memos.first {
                        MemoText(content: m.content).lineLimit(3).padding(.top, 12)
                        Spacer(minLength: 4)
                        Text(HubFormat.ago(m.createdAt)).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    } else {
                        Spacer()
                    }
                }
            } else {
                VStack(alignment: .leading, spacing: 0) {
                    Button { state.showQuickMemo() } label: { MiniInput(placeholder: "现在的想法是…", shortcut: HotKeyCenter.shared.display(.quickMemo), icon: nil, height: 40) }.buttonStyle(.plain)
                    let tags = (d.tags ?? []).sorted { ($0.count ?? 0) > ($1.count ?? 0) }.prefix(8)
                    if !tags.isEmpty {
                        Flow(spacing: 6) { ForEach(Array(tags), id: \.name) { Chip(text: "#\($0.name)\($0.count.map { " \($0)" } ?? "")") } }
                            .padding(.top, 12)
                    }
                    ForEach(Array(memos.prefix(6).enumerated()), id: \.1.id) { i, m in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(HubFormat.ago(m.createdAt)).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                            MemoText(content: m.content).lineLimit(6)
                        }
                        .padding(.vertical, 10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                        .padding(.top, i == 0 ? 12 : 0)
                        .rise(i)
                    }
                    if memos.isEmpty {
                        Text("还没有 Memo").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.top, 12)
                    }
                }
            }
        }
    }
}

/// Memo content with inline `#tags` tinted.
struct MemoText: View {
    var content: String

    var body: some View {
        Self.styled(content).font(Typo.sans(12.5)).foregroundStyle(Palette.ink).lineSpacing(3)
    }

    static func styled(_ content: String) -> Text {
        var out = Text("")
        var rest = Substring(content)
        while let r = rest.range(of: #"#[^\s#]+"#, options: .regularExpression) {
            out = out + Text(rest[..<r.lowerBound]) + Text(rest[r]).foregroundColor(Tone.sky.color)
            rest = rest[r.upperBound...]
        }
        return out + Text(rest)
    }
}
