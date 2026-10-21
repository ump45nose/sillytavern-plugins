import AppKit
import HubKit
import SwiftUI

/// The review window: this cycle's mainline and goals, plus daily and weekly sessions to confirm.
struct ReviewView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let desk = state.review
        HStack(spacing: 0) {
            ReviewSidebar().frame(width: Metrics.sidebarWidth).background(Palette.side)
            Rectangle().fill(Palette.line).frame(width: 1)
            Group {
                switch desk.selection {
                case .stage: StageView()
                case .session(let id): SessionDetail(id: id)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(minWidth: 1040, minHeight: 680)
        .background(Palette.bg)
        .preferredColorScheme(.light)
        .tint(Tone.clay.color)
        .task { await desk.reload() }
    }
}

private struct ReviewSidebar: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let desk = state.review
        VStack(alignment: .leading, spacing: 0) {
            // The window's title bar overlays this strip; the header stays below the traffic lights.
            VStack(alignment: .leading, spacing: 4) {
                Text("复盘").font(Typo.serif(24))
                if let direction = desk.goals?.mainline?.direction {
                    Text(direction).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(2).help(direction)
                }
            }
            .padding(.horizontal, 20).padding(.top, 46).padding(.bottom, 10)
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    row(.stage, title: "本阶段", detail: desk.goals?.cycle.map { "第 \($0.day ?? 0) / \($0.total ?? 42) 天" },
                        chip: ReviewText.closeChip(desk.goals?.close?.status))
                    ForEach(ReviewKind.allCases, id: \.self) { kind in
                        SectionTitle(kind.title).padding(.horizontal, 10)
                        let items = desk.lists[kind] ?? []
                        ForEach(items) { s in
                            row(.session(s.id), title: ReviewText.title(s), detail: nil, chip: ReviewText.chip(s.status))
                        }
                        if items.isEmpty {
                            Text(desk.listError ?? "还没有\(kind.title)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.horizontal, 10)
                        }
                    }
                }
                .padding(.horizontal, 10).padding(.bottom, 20)
            }
            .scrollIndicators(.never)
        }
    }

    private func row(_ target: ReviewDesk.Selection, title: String, detail: String?, chip: (String, Tone)?) -> some View {
        let on = state.review.selection == target
        return Button { state.review.selection = target } label: {
            HStack(spacing: 8) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(Typo.sans(13, on ? .semibold : .regular)).foregroundStyle(Palette.ink).lineLimit(1)
                    if let detail { Text(detail).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
                }
                Spacer(minLength: 4)
                if let chip { Chip(text: chip.0, tone: chip.1) }
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 9).fill(on ? Palette.card : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

private struct SessionDetail: View {
    var id: String
    @Environment(AppState.self) private var state

    var body: some View {
        let desk = state.review
        Group {
            if let s = desk.sessions[id] {
                if s.kind == .daily { DailyEditor(session: s) } else { WeeklyEditor(session: s) }
            } else if let error = desk.loadErrors[id] {
                VStack(spacing: 10) {
                    Text(error).font(Typo.sans(13)).foregroundStyle(Palette.ink2)
                    Button("重试") { Task { await desk.load(id, force: true) } }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .id(id)
        .task(id: id) { await desk.load(id) }
    }
}

// MARK: - Shared pieces

enum ReviewText {
    static func title(_ s: ReviewSummary) -> String { title(kind: s.resolvedKind, label: s.label) }

    static func title(kind: ReviewKind, label: String) -> String {
        if kind == .weekly, let week = label.split(separator: "W").last.flatMap({ Int($0) }) { return "第 \(week) 周" }
        guard let date = HubFormat.day(label) else { return label }
        let c = Calendar.hub, now = HubFormat.current()
        let md = "\(c.component(.month, from: date)) 月 \(c.component(.day, from: date)) 日"
        if c.isDate(date, inSameDayAs: now) { return "今天 · " + md }
        if let y = c.date(byAdding: .day, value: -1, to: now), c.isDate(date, inSameDayAs: y) { return "昨天 · " + md }
        return md + " " + ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][c.component(.weekday, from: date) - 1]
    }

    static func chip(_ s: ReviewSummary.State) -> (String, Tone)? {
        switch s {
        case .open: ("待确认", .clay)
        case .finalized: ("已归档", .olive)
        case .expired: ("已过期", .ink)
        }
    }

    static func closeChip(_ s: GoalsData.Close.State?) -> (String, Tone)? {
        switch s {
        case .preclose: ("待结案", .clay)
        case .awaitingClose: ("已冻结", .rose)
        case .closed: ("已结案", .olive)
        default: nil
        }
    }

    /// "还有 4 天" / "还有 30 小时" / "还有 40 分钟" until the session closes.
    static func remaining(_ until: Date?, short: Bool = false, now: Date = HubFormat.current()) -> String? {
        guard let until else { return nil }
        let s = until.timeIntervalSince(now)
        guard s > 0 else { return "已过期" }
        let span = s < 3600 ? "\(max(1, Int(s / 60))) 分钟" : s < 48 * 3600 ? "\(Int(s / 3600)) 小时" : "\(Int(s / 86400)) 天"
        return short ? "剩 " + span : "还有 \(span)过期"
    }

    static func dayKey(_ date: Date) -> String {
        let c = Calendar.hub.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    static func md(_ date: Date) -> String {
        let c = Calendar.hub
        return "\(c.component(.month, from: date))/\(c.component(.day, from: date))"
    }

    static func markdown(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(s)
    }
}

struct Card<Content: View>: View {
    var padding: CGFloat = 18
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: Metrics.innerRadius).strokeBorder(Palette.line2))
    }
}

/// Left column of a session: what 灵珺 sent to Telegram, or the frozen material behind it.
struct MaterialPanel: View {
    var session: ReviewSession
    @ViewState private var raw = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Label11(raw || session.delivered == nil ? "当天材料" : "灵珺发来的")
                Spacer()
                if session.delivered != nil {
                    Segmented(options: [(false, "灵珺"), (true, "材料")], selection: $raw)
                }
            }
            .padding(.bottom, 10)
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let delivered = session.delivered, !raw {
                        Text(ReviewText.markdown(delivered.text)).font(Typo.sans(13)).lineSpacing(4).textSelection(.enabled)
                    } else if let sections = session.material?.sections, !sections.isEmpty {
                        ForEach(sections.indices, id: \.self) { i in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(sections[i].title).font(Typo.sans(12, .semibold)).foregroundStyle(Palette.ink2)
                                ForEach(sections[i].blocks.indices, id: \.self) { j in
                                    Text(ReviewText.markdown(sections[i].blocks[j])).font(Typo.sans(12.5)).lineSpacing(3).textSelection(.enabled)
                                }
                            }
                        }
                    } else {
                        Text("这次没有冻结材料").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, 12)
            }
            .scrollIndicators(.never)
        }
    }
}

/// The step that moves an open session forward, shown in the header so it never scrolls away.
struct SessionAction {
    var title: String
    var enabled: Bool
    var note: String?
    var run: () -> Void
}

struct SessionHeader: View {
    var session: ReviewSession
    var action: SessionAction? = nil

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Text(ReviewText.title(kind: session.kind, label: session.label) + " · " + session.kind.title).font(Typo.serif(26))
            if let chip = ReviewText.chip(session.status) { Chip(text: chip.0, tone: chip.1) }
            Spacer()
            if session.status == .open, let left = ReviewText.remaining(session.expiresAt) {
                Text(left).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }
            if let action, session.status == .open {
                if let note = action.note { Text(note).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1) }
                Button(action: action.run) {
                    HStack(spacing: 6) {
                        Text(action.title)
                        Text("⌘↩").font(Typo.sans(11)).opacity(0.6)
                    }
                }
                .buttonStyle(.hubPrimary)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!action.enabled)
            }
        }
    }
}

/// Final text before writing: the exact content personal-review will store.
struct PreviewSheet: View {
    var title: String
    var content: String
    var confirm: String
    var busy: Bool
    var error: String?
    var back: () -> Void
    var commit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label11(title)
            ScrollView {
                Text(content).font(Typo.sans(13.5)).lineSpacing(5).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }
            .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
            if let error { Text(error).font(Typo.sans(12)).foregroundStyle(Tone.rose.color) }
            HStack {
                Text("确认后写入 Memos，Telegram 会收到已归档的通知").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                Spacer()
                Button("返回修改", action: back).buttonStyle(.hubSecondary).disabled(busy)
                Button(busy ? "写入中…" : confirm, action: commit).buttonStyle(.hubPrimary).keyboardShortcut(.defaultAction).disabled(busy)
            }
        }
    }
}

struct DoneBanner: View {
    var text: String
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "checkmark.circle.fill").foregroundStyle(Tone.olive.color)
            Text(text).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2)
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 9).fill(Tone.olive.tint))
    }
}
