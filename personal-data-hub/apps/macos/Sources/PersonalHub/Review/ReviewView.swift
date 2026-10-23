import AppKit
import HubKit
import SwiftUI

/// The review page: header with what's due, the mainline (foldable, so it stays in view while writing),
/// then sessions on the left and the selected session or the stage on the right.
struct ReviewView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let desk = state.review
        VStack(alignment: .leading, spacing: 0) {
            ReviewHeader().padding(.horizontal, 28).padding(.top, 4)
            if desk.selection != .stage, desk.goals != nil {
                MainlinePanel().padding(.horizontal, 28).padding(.top, 14)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
            HStack(alignment: .top, spacing: 0) {
                ReviewRail().frame(width: 208).padding(.leading, 28).padding(.top, 18).padding(.bottom, 24)
                Group {
                    switch desk.selection {
                    case .stage: StageView()
                    case .session(let id): SessionDetail(id: id)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
        .animation(Motion.spring, value: desk.selection)
        .background(Palette.bg)
        .preferredColorScheme(.light)
        .tint(Tone.clay.color)
        .task { await desk.reload() }
    }
}

private struct ReviewHeader: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let page = state.layout.page("review"), d = state.review.goals
        HStack(alignment: .bottom, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                Text(page?.title ?? "复盘").font(Typo.serif(34)).tracking(-0.6)
                Text(page?.subtitle.isEmpty == false ? page!.subtitle : "日报、周报与本阶段").font(Typo.sans(13)).foregroundStyle(Palette.ink2)
            }
            Spacer()
            if let d {
                pill(GoalsModule.dailyTile(d.reviews), d.reviews?.daily.map { .session($0.id) } ?? .latest(.daily))
                pill(GoalsModule.weeklyTile(d.reviews), d.reviews?.weekly.map { .session($0.id) } ?? .latest(.weekly))
                pill(GoalsModule.closeTile(d), .stage)
            }
        }
    }

    private func pill(_ t: (title: String, sub: String, hot: Bool), _ target: ReviewTarget) -> some View {
        Button { state.review.open(target) } label: {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    if t.hot { Dot(color: Tone.clay.color, pulse: true) }
                    Text(t.title).font(Typo.sans(12, .semibold)).foregroundStyle(t.hot ? Palette.clayDeep : Palette.ink)
                }
                Text(t.sub).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .frame(minWidth: 128, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 11).fill(t.hot ? Tone.clay.tint : Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 11).strokeBorder(t.hot ? Tone.clay.color.opacity(0.25) : Palette.line))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The home page's mainline and goals, kept above the editors; folds to one line.
private struct MainlinePanel: View {
    @Environment(AppState.self) private var state
    @AppStorage("reviewMainlineOpen") private var open = true

    var body: some View {
        let d = state.review.goals, c = state.cycle, goals = d?.goals ?? []
        VStack(alignment: .leading, spacing: 0) {
            Button { withAnimation(Motion.spring) { open.toggle() } } label: {
                HStack(spacing: 10) {
                    Text(d?.mainline?.domain ?? "总主线").font(Typo.sans(11, .medium)).foregroundStyle(Tone.clay.color)
                        .padding(.horizontal, 8).frame(height: 20).background(Capsule().fill(Tone.clay.tint))
                    if !open {
                        Mainline(text: d?.mainline?.direction ?? "—", size: 15).lineLimit(1)
                        if let c { Text("\(c.name) · 第 \(c.day) / \(c.total) 天").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).fixedSize() }
                        HStack(spacing: 4) {
                            ForEach(goals) { g in Circle().fill(StageTone.of(g.domain).color).frame(width: 6, height: 6).help("\(g.domain) · \(g.goal)") }
                        }
                    } else {
                        Text("写周报时对照主线和阶段目标").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                    }
                    Spacer(minLength: 8)
                    Text(open ? "收起" : "展开").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                    Image(systemName: "chevron.down").font(.system(size: 10, weight: .semibold)).foregroundStyle(Palette.ink3)
                        .rotationEffect(.degrees(open ? 180 : 0))
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if open {
                HStack(alignment: .top, spacing: 28) {
                    VStack(alignment: .leading, spacing: 0) {
                        Mainline(text: d?.mainline?.direction ?? "—", size: 21)
                        if let now = d?.mainline?.status, !now.isEmpty {
                            Text("现在 · " + now).font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
                        }
                        if let c {
                            CycleTicks(cycle: c, height: 12, spacing: 2).padding(.top, 14)
                            HStack {
                                Text("\(c.start) 开始")
                                Spacer()
                                Text("\(c.name) · 第 \(c.day) 天").fontWeight(.semibold).foregroundStyle(Palette.clayDeep)
                                Spacer()
                                Text("\(c.end) 结案")
                            }
                            .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.top, 5)
                        }
                    }
                    .frame(minWidth: 300, maxWidth: 420, alignment: .leading)
                    VStack(alignment: .leading, spacing: 0) {
                        Label11("阶段目标 · \(goals.count) / \(Stage.maxGoals)").padding(.bottom, 4)
                        ForEach(goals) { g in
                            HStack(alignment: .firstTextBaseline, spacing: 10) {
                                Text(g.domain).font(Typo.sans(11, .medium)).foregroundStyle(StageTone.of(g.domain).color)
                                    .frame(width: 40, height: 20).background(Capsule().fill(StageTone.of(g.domain).tint))
                                Text(g.goal).font(Typo.sans(12.5)).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading).help(g.goal)
                                Text(g.progress ?? "").font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(1)
                                    .frame(maxWidth: 200, alignment: .trailing).help(g.progress ?? "")
                            }
                            .padding(.vertical, 5)
                            .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                        }
                        if goals.isEmpty { Text("这个阶段还没有目标").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 6) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.top, 12)
                .transition(.opacity)
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }
}

/// Stage first, then daily and weekly sessions with their state and time left.
private struct ReviewRail: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let desk = state.review
        VStack(alignment: .leading, spacing: 0) {
            HubScroll {
                VStack(alignment: .leading, spacing: 2) {
                    stageRow
                    ForEach(ReviewKind.allCases, id: \.self) { kind in
                        let items = desk.lists[kind] ?? []
                        HStack {
                            Text(kind.title).font(Typo.sans(11, .semibold)).foregroundStyle(Palette.ink3).tracking(0.5)
                            Spacer()
                            let open = items.filter { $0.status == .open }.count
                            if open > 0 { Text("\(open) 篇待确认").font(Typo.sans(10.5)).foregroundStyle(Tone.clay.color) }
                        }
                        .padding(.horizontal, 10).padding(.top, 14).padding(.bottom, 4)
                        ForEach(items) { s in sessionRow(s) }
                        if items.isEmpty {
                            Text(desk.listError ?? "还没有\(kind.title)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.horizontal, 10)
                        }
                    }
                }
                .padding(8)
            }
            .scrollIndicators(.never)
        }
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }

    private var stageRow: some View {
        let desk = state.review, on = desk.selection == .stage
        return Button { desk.selection = .stage } label: {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(state.cycle?.name ?? "本阶段").font(Typo.sans(13, on ? .semibold : .medium)).foregroundStyle(Palette.ink)
                    Spacer()
                    if let chip = ReviewText.closeChip(desk.goals?.close?.status) { Chip(text: chip.0, tone: chip.1) }
                    else if let c = state.cycle { Text("剩 \(c.remaining) 天").font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
                }
                if let c = state.cycle { CycleTicks(cycle: c, height: 5, spacing: 1) }
                Text("主线、目标与结案").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 10).fill(on ? Palette.sunk : .clear))
            .overlay(alignment: .leading) { if on { Capsule().fill(Tone.clay.color).frame(width: 3, height: 22).offset(x: -5) } }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func sessionRow(_ s: ReviewSummary) -> some View {
        let on = state.review.selection == .session(s.id)
        let tone: Tone = switch s.status { case .open: .clay; case .finalized: .olive; case .expired: .ink }
        let sub: String = switch s.status {
        case .open: "待确认 · " + (ReviewText.remaining(s.expiresAt, short: true) ?? "")
        case .finalized: "已归档"
        case .expired: "已过期"
        }
        return Button { state.review.selection = .session(s.id) } label: {
            HStack(spacing: 9) {
                Circle().fill(s.status == .expired ? Palette.ink4 : tone.color).frame(width: 6, height: 6)
                VStack(alignment: .leading, spacing: 1) {
                    Text(ReviewText.title(s)).font(Typo.sans(12.5, on ? .semibold : .regular)).foregroundStyle(Palette.ink).lineLimit(1)
                    Text(sub).font(Typo.sans(10.5)).foregroundStyle(s.status == .open ? Tone.clay.color : Palette.ink3)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(RoundedRectangle(cornerRadius: 9).fill(on ? Palette.sunk : .clear))
            .overlay(alignment: .leading) { if on { Capsule().fill(Tone.clay.color).frame(width: 3, height: 18).offset(x: -5) } }
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
                    Segmented(options: [(false, "灵珺"), (true, "材料")], selection: $raw).fixedSize()
                }
            }
            .padding(.bottom, 10)
            HubScroll {
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
                .lineLimit(1).fixedSize()
            if let chip = ReviewText.chip(session.status) { Chip(text: chip.0, tone: chip.1).fixedSize() }
            Spacer(minLength: 8)
            // Notes give way before the title or the action button do.
            let left = session.status == .open ? ReviewText.remaining(session.expiresAt) : nil
            let note = session.status == .open ? action?.note : nil
            ViewThatFits(in: .horizontal) {
                notes([left, note])
                notes([note])
                Color.clear.frame(width: 0, height: 0)
            }
            if let action, session.status == .open {
                Button(action: action.run) {
                    HStack(spacing: 6) {
                        Text(action.title)
                        Text("⌘↩").font(Typo.sans(11)).opacity(0.6)
                    }
                }
                .buttonStyle(.hubPrimary)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!action.enabled)
                .fixedSize()
            }
        }
    }

    private func notes(_ texts: [String?]) -> some View {
        HStack(spacing: 10) {
            ForEach(texts.compactMap { $0 }, id: \.self) { Text($0).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1) }
        }
        .fixedSize()
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
            MarkdownEditor(text: .constant(content), editable: false)
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
