import AVFoundation
import AppKit
import HubKit
import SwiftUI

// MARK: - 健康

struct HealthModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        HubGate(envelope: state.hub.data.health) { h in
            if size == .compact { compact(h) } else { detail(h) }
        }
    }

    private func pct(_ v: Double?, _ goal: Double?) -> Double? {
        guard let v, let goal, goal > 0 else { return nil }
        return v / goal * 100
    }

    private func days(_ h: HealthData) -> [HealthData.Day] { Array((h.days ?? []).suffix(14)) }

    private func compact(_ h: HealthData) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top) {
                if let steps = h.steps { Hero(value: steps, unit: "步") } else { Hero.empty("步") }
                Spacer()
                ZStack {
                    Ring(value: pct(h.steps, h.stepGoal) ?? 0, color: Tone.olive.color, size: 48, width: 5)
                    Ring(value: pct(h.activeKcal, h.kcalGoal) ?? 0, color: Tone.clay.color, size: 36, width: 5)
                    Ring(value: pct(h.exerciseMinutes, h.exerciseGoal) ?? 0, color: Tone.sky.color, size: 24, width: 5)
                }
                .help("外圈步数 · 中圈活动 · 内圈锻炼")
            }
            Text("睡眠 \(HubFormat.minutes(h.sleepMinutes)) · 心率 \(HubFormat.int(h.restingHr)) · 血氧 \(HubFormat.int(h.spo2))%")
                .font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1).padding(.top, 4)
            Text("活动 \(HubFormat.int(h.activeKcal)) kcal · 锻炼 \(HubFormat.int(h.exerciseMinutes)) 分钟")
                .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1).padding(.top, 2)
            Spacer(minLength: 6)
            Bars(values: days(h).map(\.steps), height: 26, color: Tone.olive.color)
        }
    }

    private func detail(_ h: HealthData) -> some View {
        let d = days(h), stages = sleepStages(h)
        return VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 22) {
                ZStack {
                    Ring(value: pct(h.steps, h.stepGoal) ?? 0, color: Tone.olive.color, size: 118, width: 11)
                    Ring(value: pct(h.activeKcal, h.kcalGoal) ?? 0, color: Tone.clay.color, size: 88, width: 11)
                    Ring(value: pct(h.exerciseMinutes, h.exerciseGoal) ?? 0, color: Tone.sky.color, size: 58, width: 11)
                }
                VStack(alignment: .leading, spacing: 10) {
                    if let steps = h.steps {
                        Hero(value: steps, unit: h.stepGoal.map { "/ \(Fmt.number($0)) 步" } ?? "步")
                    } else {
                        Hero.empty("今天还没有步数")
                    }
                    VStack(alignment: .leading, spacing: 5) {
                        Legend(items: [("步数 \(pct(h.steps, h.stepGoal).map { "\(Int($0))%" } ?? "—")", Tone.olive.color)])
                        Legend(items: [("活动 \(HubFormat.int(h.activeKcal)) / \(HubFormat.int(h.kcalGoal)) kcal", Tone.clay.color)])
                        Legend(items: [("锻炼 \(HubFormat.int(h.exerciseMinutes)) / \(HubFormat.int(h.exerciseGoal)) 分钟", Tone.sky.color)])
                    }
                }
            }
            HStack {
                Stat(label: "睡眠", value: HubFormat.minutes(h.sleepMinutes))
                Stat(label: "静息心率", value: HubFormat.int(h.restingHr), unit: "bpm")
                Stat(label: "血氧", value: HubFormat.int(h.spo2), unit: "%")
            }
            .padding(.top, 18)
            SectionTitle("近 \(d.count) 天步数")
            Bars(values: d.map(\.steps), height: 72, color: Tone.olive.color, labels: Bars.dayLabels(d.map(\.date)))
            HStack(alignment: .top, spacing: 24) {
                VStack(alignment: .leading, spacing: 0) {
                    SectionTitle("昨晚睡眠")
                    if stages.isEmpty {
                        Text("暂无睡眠分期").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    } else {
                        SleepBar(stages: stages)
                        Legend(items: stages.map { ("\($0.name) \(HubFormat.minutes(Double($0.minutes)))", $0.tone.color) }).padding(.top, 8)
                    }
                }
                VStack(alignment: .leading, spacing: 0) {
                    SectionTitle("静息心率 · \(d.count) 天")
                    let hr = d.compactMap(\.restingHr)
                    if hr.count > 1 {
                        AreaLine(values: hr, height: 52, color: Tone.rose.color)
                    } else {
                        Text("暂无").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    }
                }
            }
        }
    }

    private func sleepStages(_ h: HealthData) -> [(name: String, minutes: Int, tone: Tone)] {
        let names: [String: (String, Tone)] = ["deep": ("深睡", .steel), "core": ("核心", .sky), "light": ("浅睡", .sky), "rem": ("REM", .plum), "awake": ("清醒", .ochre)]
        return (h.sleepStages ?? []).compactMap { s in
            guard let m = s.minutes, m > 0 else { return nil }
            let n = names[s.stage.lowercased()] ?? (s.stage, .kraft)
            return (n.0, Int(m.rounded()), n.1)
        }
    }
}

extension Hero {
    /// Placeholder hero for a measurement the source has not reported yet.
    static func empty(_ caption: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text("—").font(Typo.serif(38)).foregroundStyle(Palette.ink3)
            Text(caption).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
        }
    }
}

struct SleepBar: View {
    var stages: [(name: String, minutes: Int, tone: Tone)]
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let total = CGFloat(max(1, stages.reduce(0) { $0 + $1.minutes }))
            HStack(spacing: 2) {
                ForEach(stages.indices, id: \.self) { i in
                    RoundedRectangle(cornerRadius: 3).fill(stages[i].tone.color)
                        .frame(width: max(0, (geo.size.width - CGFloat(stages.count - 1) * 2) * CGFloat(stages[i].minutes) / total))
                        .scaleEffect(x: shown, anchor: .leading)
                        .animation(Motion.grow.delay(Double(i) * 0.09), value: shown)
                }
            }
        }
        .frame(height: 14)
        .modifier(AppearProgress(animation: .linear(duration: 0.01), progress: $shown))
    }
}

// MARK: - 账单

struct BillsModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    static let categoryTones: [Tone] = [.kraft, .clay, .olive, .sky, .plum, .ochre, .steel, .rose]

    var body: some View {
        HubGate(envelope: state.hub.data.bills) { b in
            if size == .compact { compact(b) } else { detail(b) }
        }
    }

    private func budgetPct(_ b: BillsData) -> Double? {
        guard let month = b.monthTotal, let budget = b.monthBudget, budget > 0 else { return nil }
        return month / budget * 100
    }

    private func compact(_ b: BillsData) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if let today = b.todayTotal { Hero(value: today, decimals: 2, prefix: "¥") } else { Hero.empty("今日") }
            Text("今日支出 · \(b.todayItems?.count ?? 0) 笔").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
            Spacer(minLength: 6)
            HStack {
                Text("本月 ¥\(b.monthTotal.map { Fmt.number($0) } ?? "—")").foregroundStyle(Palette.ink2)
                Spacer()
                if let pct = budgetPct(b) { Text("预算 \(Int(pct))%").foregroundStyle(Palette.ink3) }
            }
            .font(Typo.sans(11.5)).padding(.bottom, 6)
            if let pct = budgetPct(b), let month = b.monthTotal, let budget = b.monthBudget {
                Track(value: pct, color: Tone.kraft.color)
                Text("剩 ¥\(Fmt.number(budget - month))\(b.daysLeftInMonth.map { " · 还有 \($0) 天" } ?? "")")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.top, 6)
            } else {
                Text("未设置月预算").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
        }
    }

    private func detail(_ b: BillsData) -> some View {
        let cats = (b.monthCategories ?? []).compactMap { c in c.amount.map { (c.name, $0) } }.filter { $0.1 > 0 }
        let catTotal = max(cats.reduce(0) { $0 + $1.1 }, 0.01)
        let days = Array((b.days ?? []).suffix(14))
        let weekends = Set(days.indices.filter { i in HubFormat.day(days[i].date).map { Calendar.hub.isDateInWeekend($0) } ?? false })
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 24) {
                VStack(alignment: .leading, spacing: 0) {
                    if let today = b.todayTotal { Hero(value: today, decimals: 2, prefix: "¥", unit: "今日") } else { Hero.empty("今日") }
                    VStack(spacing: 0) {
                        ForEach(b.todayItems ?? []) { it in
                            Row(title: it.title ?? "未命名", sub: [it.category, it.time.map(HubFormat.clock)].compactMap { $0 }.joined(separator: " · "),
                                trailing: it.amount.map { "−" + Fmt.number($0, 2) } ?? "—")
                        }
                        if (b.todayItems ?? []).isEmpty {
                            Text("今天还没有记账").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 9)
                        }
                    }
                    .padding(.top, 12)
                }
                .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 0) {
                    SectionTitle("近 \(days.count) 天").padding(.top, -18)
                    Bars(values: days.map(\.total), height: 70, color: Tone.kraft.color, highlight: weekends, labels: Bars.dayLabels(days.map(\.date)))
                    SectionTitle("本月 · ¥\(b.monthTotal.map { Fmt.number($0) } ?? "—")\(b.monthBudget.map { " / \(Fmt.number($0))" } ?? "")")
                    if cats.isEmpty {
                        Text("暂无分类").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    } else {
                        StackBar(parts: cats.indices.map { (cats[$0].1, Self.categoryTones[$0 % Self.categoryTones.count].color) })
                        Legend(items: cats.indices.map { ("\(cats[$0].0) \(Int((cats[$0].1 / catTotal * 100).rounded()))%", Self.categoryTones[$0 % Self.categoryTones.count].color) })
                            .padding(.top, 8)
                    }
                }
                .frame(maxWidth: .infinity)
            }
            if let netWorth = b.netWorth { assets(b, netWorth) }
        }
    }

    @ViewBuilder private func assets(_ b: BillsData, _ netWorth: Double) -> some View {
        let months = (b.netWorthMonths ?? []).compactMap(\.value)
        SectionTitle("资产")
        HStack(alignment: .bottom, spacing: 24) {
            VStack(alignment: .leading, spacing: 4) {
                Label11("净资产")
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    CountUp(value: netWorth, prefix: "¥").font(Typo.serif(30))
                    if let first = months.first, first > 0, months.count > 1 {
                        let change = (netWorth / first - 1) * 100
                        Text("近 \(months.count) 月 \(change >= 0 ? "+" : "")\(Int(change.rounded()))%").font(Typo.sans(12))
                            .foregroundStyle(change >= 0 ? Tone.olive.color : Tone.rose.color)
                    }
                }
            }
            if months.count > 1 { AreaLine(values: months, height: 40, color: Tone.olive.color).frame(maxWidth: 260) }
        }
        HStack(spacing: 8) {
            ForEach(b.accounts ?? [], id: \.name) { a in
                VStack(alignment: .leading, spacing: 3) {
                    Label11(a.name)
                    Text(a.balance.map { "¥" + Fmt.number($0) } ?? "—").font(Typo.serif(15)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.8)
                }
                .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
            }
        }
        .padding(.top, 12)
    }
}

struct Row: View {
    var title: String
    var sub: String
    var trailing: String

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(Typo.sans(13)).lineLimit(1)
                Text(sub).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
            }
            Spacer()
            Text(trailing).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).monospacedDigit()
        }
        .padding(.vertical, 9)
        .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
    }
}

struct StackBar: View {
    var parts: [(Double, Color)]
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let total = max(parts.reduce(0) { $0 + $1.0 }, 0.000_001)
            HStack(spacing: 2) {
                ForEach(parts.indices, id: \.self) { i in
                    Rectangle().fill(parts[i].1)
                        .frame(width: max(0, (geo.size.width - CGFloat(parts.count - 1) * 2) * parts[i].0 / total))
                        .scaleEffect(x: shown, anchor: .leading)
                        .animation(Motion.grow.delay(Double(i) * 0.08), value: shown)
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: 10)
        .modifier(AppearProgress(animation: .linear(duration: 0.01), progress: $shown))
    }
}

// MARK: - 交流

struct CRMModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state
    @ViewState private var showAll = false

    var body: some View {
        HubGate(envelope: state.hub.data.crm) { c in
            if size == .compact { compact(c) } else { detail(c) }
        }
    }

    private func people(_ c: CRMData) -> [CRMData.Interaction] {
        var seen = Set<String>()
        return (c.today ?? []).filter { seen.insert($0.personId ?? $0.name).inserted }
    }

    private func compact(_ c: CRMData) -> some View {
        let today = c.today ?? [], who = people(c), recordings = today.compactMap(\.recording)
        let length = recordings.compactMap(\.durationSeconds).reduce(0, +)
        let latest = today.max { ($0.time ?? .distantPast) < ($1.time ?? .distantPast) }
        return VStack(alignment: .leading, spacing: 0) {
            Hero(value: Double(who.count), unit: "人 · \(today.count) 条交流")
            HStack(spacing: 8) {
                HStack(spacing: -6) {
                    ForEach(who.prefix(5)) { PersonBadge(initial: HubFormat.initial($0.name), tone: HubFormat.tone(for: $0.personId ?? $0.name), size: 26) }
                }
                if !recordings.isEmpty {
                    Chip(text: "\(recordings.count) 段录音\(length > 0 ? " · " + (HubFormat.duration(length) ?? "") : "")", tone: .rose, systemImage: "waveform")
                }
            }
            .padding(.top, 8)
            if let latest {
                VStack(alignment: .leading, spacing: 2) {
                    Text([latest.name, latest.time.map(HubFormat.clock)].compactMap { $0 }.joined(separator: " · "))
                        .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    Text(Self.preview(latest.summary)).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(2)
                }
                .padding(.top, 10)
            } else {
                Text("今天还没有交流记录").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.top, 10)
            }
        }
    }

    /// Markdown attachment links (`[图片](attachment://…)`) become their bare label.
    static func clean(_ text: String) -> String {
        text.replacingOccurrences(of: #"\[([^\]]*)\]\(attachment://[^)]*\)"#, with: "[$1]", options: .regularExpression)
    }

    /// Chat-log summaries arrive as one line per message; the card shows the last real line.
    static func preview(_ summary: String?) -> String {
        let lines = clean(summary ?? "").split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
        let text = lines.last { !$0.isEmpty && !$0.hasSuffix("[图片]") && $0.count > 1 } ?? lines.last ?? ""
        return text.isEmpty ? "没有摘要" : text
    }

    private static let shownRows = 5

    private func detail(_ c: CRMData) -> some View {
        let today = c.today ?? []
        let rows = showAll ? today : Array(today.prefix(Self.shownRows))
        return VStack(alignment: .leading, spacing: 0) {
            SectionTitle("今日 · \(people(c).count) 人 · \(today.count) 条").padding(.top, -18)
            if today.isEmpty {
                Text("今天还没有交流记录").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).padding(.vertical, 10)
            }
            ForEach(Array(rows.enumerated()), id: \.1.id) { i, p in
                HStack(alignment: .top, spacing: 12) {
                    PersonBadge(initial: HubFormat.initial(p.name), tone: HubFormat.tone(for: p.personId ?? p.name), size: 32)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 8) {
                            Text(p.name).font(Typo.sans(13, .semibold))
                            Text([p.relation, p.channel].compactMap { $0 }.joined(separator: " · ")).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                            Spacer()
                            if let t = p.time { Text(HubFormat.clock(t)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit() }
                        }
                        if let s = p.summary, !s.isEmpty { CollapsibleText(text: Self.clean(s)) }
                        if let rec = p.recording { Recording(recording: rec) }
                    }
                }
                .padding(.vertical, 10)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                .rise(i)
            }
            if today.count > Self.shownRows {
                Button { withAnimation(Motion.spring) { showAll.toggle() } } label: {
                    Chip(text: showAll ? "收起" : "展开全部 \(today.count) 条")
                }
                .buttonStyle(.plain).padding(.top, 4)
            }
            if let cycle = c.cycle {
                SectionTitle(cycle.days.map { "近 \($0) 天" } ?? "本阶段")
                HStack(alignment: .bottom, spacing: 28) {
                    stageStat(cycle.people, "联系过的人")
                    stageStat(cycle.interactions, "次交流")
                    stageStat(cycle.recordings, "段录音")
                    Spacer()
                }
                if let stale = c.stale, !stale.isEmpty {
                    Label11("久未联系").padding(.top, 14).padding(.bottom, 6)
                    Flow(spacing: 6) { ForEach(stale.prefix(8), id: \.name) { s in Chip(text: s.days.map { "\(s.name) · \($0) 天" } ?? s.name) } }
                }
            }
        }
    }

    private func stageStat(_ v: Int?, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            if let v { CountUp(value: Double(v)).font(Typo.serif(30)) } else { Text("—").font(Typo.serif(30)).foregroundStyle(Palette.ink3) }
            Label11(label)
        }
    }
}

/// Long text clipped to a few lines, with a toggle when it does not fit.
struct CollapsibleText: View {
    var text: String
    var lines = 3
    @ViewState private var expanded = false

    private var long: Bool { text.count > 120 || text.filter { $0 == "\n" }.count >= lines }

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(text).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).lineSpacing(2)
                .lineLimit(expanded ? nil : lines)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if long {
                Button { withAnimation(Motion.spring) { expanded.toggle() } } label: {
                    Text(expanded ? "收起" : "展开").font(Typo.sans(11, .medium)).foregroundStyle(Palette.ink3)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

/// A recording attached to an interaction: streams through hub-api, transcript for Plaud.
struct Recording: View {
    var recording: CRMData.Recording
    @Environment(AppState.self) private var state
    @ViewState private var player: AVPlayer?
    @ViewState private var playing = false
    @ViewState private var transcript: String?
    @ViewState private var showTranscript = false
    @ViewState private var loadingTranscript = false

    private var hasTranscript: Bool { recording.id.hasPrefix("plaud:") }

    var body: some View {
        HStack(spacing: 10) {
            Button(action: toggle) {
                Image(systemName: playing ? "pause.fill" : "play.fill").font(.system(size: 10)).foregroundStyle(.white)
                    .frame(width: 26, height: 26).background(Circle().fill(Tone.rose.color))
            }
            .buttonStyle(.plain)
            .disabled(state.hub.mode != .hub)
            Waveform(bars: 38, seed: HubFormat.seed(recording.id), color: Tone.rose.color).frame(height: 22)
            Text([recording.title, HubFormat.duration(recording.durationSeconds)].compactMap { $0 }.joined(separator: " · "))
                .font(Typo.sans(11)).foregroundStyle(Palette.ink2).lineLimit(1).fixedSize()
            if hasTranscript {
                Button { openTranscript() } label: {
                    Text(loadingTranscript ? "读取中…" : "转录稿").font(Typo.sans(11, .medium)).foregroundStyle(Tone.rose.color)
                }
                .buttonStyle(.plain)
                .popover(isPresented: $showTranscript, arrowEdge: .bottom) {
                    HubScroll {
                        Text(transcript.map { (try? AttributedString(markdown: $0, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString($0) } ?? "暂无转录稿")
                            .font(Typo.sans(12.5)).lineSpacing(3).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(16)
                    }
                    .frame(width: 420, height: 360)
                }
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 10).fill(Tone.rose.tint))
        .padding(.top, 4)
        .onReceive(NotificationCenter.default.publisher(for: AVPlayerItem.didPlayToEndTimeNotification)) { note in
            guard let item = note.object as? AVPlayerItem, item === player?.currentItem else { return }
            playing = false
            player?.seek(to: .zero)
        }
        .onDisappear { player?.pause(); playing = false }
    }

    private func toggle() {
        if player == nil { player = state.hub.player(recording: recording.id) }
        guard let player else { return }
        if playing { player.pause() } else { player.play() }
        playing.toggle()
    }

    private func openTranscript() {
        if transcript != nil || state.hub.mode != .hub { showTranscript = true; return }
        loadingTranscript = true
        Task {
            transcript = await state.hub.transcript(recording: recording.id)
            loadingTranscript = false
            showTranscript = true
        }
    }
}

// MARK: - 媒体

struct MediaModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state
    @ViewState private var wide = true

    var body: some View {
        HubGate(envelope: state.hub.data.media) { m in
            if size == .compact {
                compact(m)
            } else {
                detail(m, columns: wide ? 6 : 3, wide: wide)
                    .onGeometryChange(for: Bool.self) { $0.size.width >= 820 } action: { wide = $0 }
            }
        }
    }

    private func downloading(_ m: MediaData) -> [MediaData.Download] { (m.downloads ?? []).filter { $0.state == "downloading" } }

    private func compact(_ m: MediaData) -> some View {
        let active = downloading(m), speed = active.compactMap(\.speedBps).reduce(0, +)
        return VStack(alignment: .leading, spacing: 0) {
            if let p = m.continueWatching?.first {
                HStack(alignment: .top, spacing: 12) {
                    PosterView(item: p, showTitle: false).frame(width: 62, height: 88)
                    VStack(alignment: .leading, spacing: 4) {
                        Label11("继续观看")
                        Text(p.title).font(Typo.serif(17)).lineLimit(2)
                        Text([p.subtitle, p.progress.map { "已看 \(Int(($0 * 100).rounded()))%" }].compactMap { $0 }.joined(separator: " · "))
                            .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                    }
                }
            } else {
                Text("没有在看的内容").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
            }
            Spacer(minLength: 6)
            HStack {
                Text(active.isEmpty ? "没有下载任务" : "下载中 \(active.count)\(HubFormat.speed(speed).map { " · ↓ \($0)" } ?? "")")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                Spacer()
                if let n = m.latest?.count, n > 0 { Chip(text: "最近添加 \(n)") }
            }
        }
    }

    private func detail(_ m: MediaData, columns: Int, wide: Bool) -> some View {
        let watching = m.continueWatching ?? [], downloads = m.downloads ?? []
        let speed = downloading(m).compactMap(\.speedBps).reduce(0, +)
        let latest = VStack(alignment: .leading, spacing: 0) {
            SectionTitle("最近添加")
            ForEach((m.latest ?? []).prefix(5)) { it in
                Button { open(it.link) } label: { Row(title: it.title, sub: it.subtitle ?? "", trailing: "Emby").contentShape(Rectangle()) }
                    .buttonStyle(.plain)
            }
            if (m.latest ?? []).isEmpty { empty("暂无") }
        }
        let music = VStack(alignment: .leading, spacing: 0) {
            SectionTitle("最近播放 · Navidrome")
            let albums = Array((m.recentAlbums ?? []).prefix(5))
            HStack(spacing: 8) {
                ForEach(Array(albums.enumerated()), id: \.1.id) { i, a in
                    Button { open(a.link) } label: {
                        CoverImage(ref: a.image, title: a.title, tone: [.plum, .steel, .clay, .olive, .sky][i % 5])
                            .aspectRatio(1, contentMode: .fit)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }
                    .buttonStyle(.plain)
                    .help([a.title, a.artist].compactMap { $0 }.joined(separator: " · "))
                }
            }
            if let a = albums.first {
                Text("《\(a.title)》\(a.artist.map { " · \($0)" } ?? "")").font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1).padding(.top, 6)
            } else {
                empty("暂无")
            }
        }
        let downloadList = VStack(alignment: .leading, spacing: 0) {
            SectionTitle("下载 · qBittorrent")
            ForEach(Array(downloads.prefix(4).enumerated()), id: \.1.id) { i, d in
                let p = min(max(d.progress ?? 0, 0), 1) * 100
                VStack(spacing: 5) {
                    HStack {
                        Text(d.title).lineLimit(1)
                        Spacer()
                        Text(d.state == "downloading" ? "\(Int(p))%" : Self.stateText(d.state, p)).foregroundStyle(Palette.ink3)
                    }
                    .font(Typo.sans(12))
                    Track(value: p, color: d.state == "stalled" ? Tone.ochre.color : Tone.plum.color, delay: Double(i) * 100)
                }
                .padding(.vertical, 6)
            }
            if downloads.isEmpty { empty("没有下载任务") }
            if let s = HubFormat.speed(speed) {
                Text("↓ \(s)").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.top, 2)
            }
        }
        return VStack(alignment: .leading, spacing: 0) {
            SectionTitle("继续观看 · Emby").padding(.top, -18)
            if watching.isEmpty {
                empty("没有在看的内容")
            } else {
                HStack(spacing: 12) {
                    ForEach(Array(watching.prefix(columns).enumerated()), id: \.1.id) { i, p in
                        Button { open(p.link) } label: { PosterView(item: p) }
                            .buttonStyle(.plain)
                            .aspectRatio(2 / 3, contentMode: .fit).frame(maxWidth: .infinity).rise(i)
                    }
                    ForEach(0..<max(0, columns - watching.count), id: \.self) { _ in Color.clear.aspectRatio(2 / 3, contentMode: .fit).frame(maxWidth: .infinity) }
                }
            }
            if wide {
                HStack(alignment: .top, spacing: 28) { latest; music; downloadList }
            } else {
                HStack(alignment: .top, spacing: 28) { latest; downloadList }
                music
            }
            HStack(spacing: 6) {
                ForEach(m.services ?? []) { s in
                    Button { open(s.link) } label: {
                        Chip(text: "\(Self.serviceName(s.id))\(s.link == nil ? "" : " ↗")", tone: s.status == .ok ? nil : .rose)
                    }
                    .buttonStyle(.plain)
                    .disabled(s.link == nil)
                }
            }
            .padding(.top, 16)
        }
    }

    private func empty(_ text: String) -> some View {
        Text(text).font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 8)
    }

    private func open(_ link: String?) {
        guard let link, let url = URL(string: link) else { return }
        NSWorkspace.shared.open(url)
    }

    static func stateText(_ state: String?, _ p: Double) -> String {
        switch state {
        case "paused": "已暂停 \(Int(p))%"
        case "queued": "排队中"
        case "stalled": "停滞 \(Int(p))%"
        case "completed", "seeding": "已完成"
        default: "\(Int(p))%"
        }
    }

    static func serviceName(_ id: String) -> String {
        ["emby": "Emby", "navidrome": "Navidrome", "moviepilot": "MoviePilot", "qbittorrent": "qBittorrent"][id] ?? id
    }
}

struct PosterView: View {
    var item: MediaData.Item
    var showTitle = true

    var body: some View {
        CoverImage(ref: item.image, title: item.title, tone: HubFormat.tone(for: item.title))
            .overlay {
                if showTitle {
                    LinearGradient(colors: [.clear, .black.opacity(0.55)], startPoint: .center, endPoint: .bottom)
                }
            }
            .overlay(alignment: .bottomLeading) {
                VStack(alignment: .leading, spacing: 6) {
                    if showTitle {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(item.title).font(Typo.sans(12, .semibold)).lineLimit(1)
                            if let s = item.subtitle { Text(s).font(Typo.sans(10.5)).opacity(0.8).lineLimit(1) }
                        }
                        .foregroundStyle(.white)
                        .padding(.horizontal, 10)
                    }
                    if let p = item.progress {
                        GeometryReader { geo in
                            ZStack(alignment: .leading) {
                                Rectangle().fill(.white.opacity(0.25))
                                Rectangle().fill(Tone.clay.color).frame(width: geo.size.width * min(max(p, 0), 1))
                            }
                        }
                        .frame(height: 3)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .shadow(color: .black.opacity(0.12), radius: 6, y: 3)
    }
}
