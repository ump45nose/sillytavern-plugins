import AVFoundation
import HubKit
import SwiftUI

// MARK: - 录音

struct PlaudModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state
    @ViewState private var list: PlaudList?
    @ViewState private var source: HubModel.PlaudSource = .hub
    @ViewState private var error: String?
    @ViewState private var selected: String?
    @ViewState private var loadingMore = false

    var body: some View {
        Group {
            if let list {
                if list.days.isEmpty {
                    empty(source == .crm ? "今天还没有录音。hub 提供录音列表后可以回看更早的。" : "还没有录音")
                } else if size == .compact {
                    compact(list)
                } else {
                    detail(list)
                }
            } else if let error {
                empty(error)
            } else {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: state.hub.data.fetchedAt) { await load() }
    }

    private func load() async {
        do {
            let page = try await state.hub.plaudRecordings()
            list = page.list
            source = page.source
            error = nil
            if selected == nil || !page.list.days.contains(where: { $0.recordings.contains { $0.id == selected } }) {
                selected = page.list.days.first?.recordings.first?.id
            }
        } catch {
            if list == nil { self.error = error.localizedDescription }
        }
    }

    private func loadMore() {
        guard let before = list?.nextBefore, !loadingMore else { return }
        loadingMore = true
        Task {
            if let page = try? await state.hub.plaudRecordings(before: before) {
                list?.days += page.list.days
                list?.nextBefore = page.list.nextBefore
            }
            loadingMore = false
        }
    }

    private func empty(_ text: String) -> some View {
        Text(text).font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).lineSpacing(3)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    // MARK: Compact

    private func compact(_ list: PlaudList) -> some View {
        let day = list.days[0], latest = day.recordings[0]
        let todayKey = ReviewText.dayKey(state.agenda.now)
        let todays = list.days.first { $0.date == todayKey }?.recordings ?? []
        let length = todays.compactMap(\.durationSeconds).reduce(0, +)
        return VStack(alignment: .leading, spacing: 0) {
            Label11(PlaudText.when(latest, day: day.date, now: state.agenda.now) + (day.people.map { $0.isEmpty ? "" : " · " + $0.joined(separator: "、") } ?? ""))
                .lineLimit(1)
            Text(latest.title ?? "未命名录音").font(Typo.sans(14, .semibold)).lineLimit(2).padding(.top, 5)
            ForEach(Array((day.recordings.dropFirst().prefix(2))), id: \.id) { r in
                HStack(spacing: 8) {
                    Text(r.startAt.map(HubFormat.clock) ?? "").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit()
                    Text(r.title ?? "未命名录音").font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(1)
                }
                .padding(.top, 6)
            }
            Spacer(minLength: 6)
            Chip(text: todays.isEmpty ? "今天还没有录音" : "今天 \(todays.count) 段 · \(HubFormat.duration(length) ?? "")", tone: .rose, systemImage: "waveform")
        }
    }

    // MARK: Detail

    private func detail(_ list: PlaudList) -> some View {
        HStack(spacing: 0) {
            HubScroll {
                LazyVStack(alignment: .leading, spacing: 2) {
                    ForEach(list.days) { day in
                        Text(PlaudText.dayTitle(day.date, now: state.agenda.now)).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                            .padding(.horizontal, 10).padding(.top, day.id == list.days.first?.id ? 2 : 14).padding(.bottom, 4)
                        ForEach(day.recordings) { r in row(r, day: day) }
                    }
                    if list.nextBefore != nil {
                        Button(action: loadMore) {
                            Text(loadingMore ? "读取中…" : "加载更早").font(Typo.sans(12)).foregroundStyle(Tone.clay.color)
                        }
                        .buttonStyle(.plain).padding(.horizontal, 10).padding(.vertical, 10)
                        .onAppear(perform: loadMore)
                    }
                    if source == .crm {
                        Text("hub 还没提供录音列表，暂只显示今天交流里的录音").font(Typo.sans(11)).foregroundStyle(Palette.ink4)
                            .lineSpacing(2).padding(10)
                    }
                }
                .padding(.trailing, 10)
            }
            .frame(width: 228)
            Rectangle().fill(Palette.line2).frame(width: 1).padding(.trailing, 22)
            if let id = selected, let (r, day) = find(id, in: list) {
                TranscriptPane(recording: r, day: day, people: source == .sample ? PlaudSample.people(r.id) : day.people ?? [])
                    .id(r.id)
            } else {
                Spacer()
            }
        }
    }

    private func find(_ id: String, in list: PlaudList) -> (PlaudList.Recording, PlaudList.Day)? {
        for day in list.days { if let r = day.recordings.first(where: { $0.id == id }) { return (r, day) } }
        return nil
    }

    private func row(_ r: PlaudList.Recording, day: PlaudList.Day) -> some View {
        let on = r.id == selected
        return Button { withAnimation(Motion.fast) { selected = r.id } } label: {
            VStack(alignment: .leading, spacing: 3) {
                Text([r.startAt.map(HubFormat.clock), r.durationSeconds.map(PlaudText.minutes)].compactMap { $0 }.joined(separator: " · "))
                    .font(Typo.sans(11)).foregroundStyle(on ? Tone.rose.color : Palette.ink3).monospacedDigit()
                Text(r.title ?? "未命名录音").font(Typo.sans(13, on ? .semibold : .medium)).foregroundStyle(Palette.ink).lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 9).fill(on ? Tone.rose.tint : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

enum PlaudText {
    static func minutes(_ seconds: Double) -> String {
        seconds < 60 ? "\(Int(seconds)) 秒" : "\(Int((seconds / 60).rounded())) 分钟"
    }

    static func dayTitle(_ key: String, now: Date) -> String {
        let cal = Calendar.hub
        guard let date = date(key) else { return key }
        let md = "\(cal.component(.month, from: date)) 月 \(cal.component(.day, from: date)) 日"
        if cal.isDate(date, inSameDayAs: now) { return "今天 · " + md }
        if let y = cal.date(byAdding: .day, value: -1, to: now), cal.isDate(date, inSameDayAs: y) { return "昨天 · " + md }
        return md + " " + HubFormat.weekday(date)
    }

    static func when(_ r: PlaudList.Recording, day: String, now: Date) -> String {
        let head = [dayTitle(day, now: now).components(separatedBy: " · ").first, r.startAt.map(HubFormat.clock)].compactMap { $0 }.joined(separator: " ")
        return [head, r.durationSeconds.map(minutes)].compactMap { $0 }.joined(separator: " · ")
    }

    /// `YYYY-MM-DD` in the hub calendar.
    static func date(_ key: String) -> Date? {
        let p = key.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return nil }
        return Calendar.hub.date(from: DateComponents(year: p[0], month: p[1], day: p[2]))
    }

    /// `01:15` or `1:02:03` to seconds.
    static func seconds(_ stamp: String) -> Double? {
        let parts = stamp.split(separator: ":").compactMap { Double($0) }
        guard parts.count >= 2 else { return nil }
        return parts.reduce(0) { $0 * 60 + $1 }
    }

    static func clock(_ seconds: Double) -> String {
        let s = Int(max(0, seconds.isFinite ? seconds : 0))
        return s >= 3600 ? String(format: "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60) : String(format: "%02d:%02d", s / 60, s % 60)
    }
}

// MARK: - Transcript pane

private struct TranscriptPane: View {
    var recording: PlaudList.Recording
    var day: PlaudList.Day
    var people: [String]
    @Environment(AppState.self) private var state
    @ViewState private var audio = AudioController()
    @ViewState private var blocks: [TranscriptBlock]?
    @ViewState private var failed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Label11(header).lineLimit(1)
            Text(recording.title ?? "未命名录音").font(Typo.serif(22)).lineLimit(1).padding(.top, 4)
            AudioBar(audio: audio, duration: recording.durationSeconds, available: state.hub.mode == .hub)
                .padding(.top, 12).padding(.bottom, 6)
            if let blocks {
                if blocks.isEmpty {
                    note("这段录音还没有转录稿")
                } else {
                    HubScroll {
                        TranscriptView(blocks: blocks) { audio.seek(to: $0) }
                            .padding(.top, 8).padding(.bottom, 4).padding(.trailing, 12)
                    }
                }
            } else if failed {
                note("转录稿读取失败")
            } else {
                ProgressView().controlSize(.small).padding(.top, 20)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .task {
            if let player = state.hub.player(recording: recording.id) { audio.attach(player) }
            if let text = await state.hub.transcript(recording: recording.id) {
                blocks = Transcript.parse(text)
            } else {
                failed = true
            }
        }
        .onDisappear { audio.stop() }
    }

    private var header: String {
        var range = recording.startAt.map(HubFormat.clock)
        if let start = recording.startAt, let d = recording.durationSeconds {
            range = HubFormat.clock(start) + " – " + HubFormat.clock(start.addingTimeInterval(d))
        }
        let head = PlaudText.dayTitle(day.date, now: state.agenda.now).components(separatedBy: " · ").first
        return [[head, range].compactMap { $0 }.joined(separator: " "), people.isEmpty ? nil : people.joined(separator: "、")]
            .compactMap { $0 }.joined(separator: " · ")
    }

    private func note(_ text: String) -> some View {
        Text(text).font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).padding(.top, 14)
    }
}

/// Speaker turns get a coloured name column; the recorder's owner (「我」) is always clay.
struct TranscriptView: View {
    var blocks: [TranscriptBlock]
    var seek: (Double) -> Void = { _ in }

    private static let palette: [Tone] = [.steel, .plum, .olive, .sky, .ochre, .sage, .kraft]

    var body: some View {
        let others = Transcript.speakers(blocks).filter { !Transcript.isSelf($0) }
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { i, block in
                switch block {
                case .heading(let level, let text):
                    Text(text).font(level <= 2 ? Typo.serif(17) : Typo.sans(13.5, .semibold))
                        .padding(.top, i == 0 ? 0 : 18).padding(.bottom, 8)
                case .turn(let speaker, let time, let text):
                    let continued = i > 0 && { if case .turn(let prev, _, _) = blocks[i - 1] { return prev == speaker } else { return false } }()
                    turn(speaker, time, text, tone: Self.tone(speaker, others), continued: continued)
                case .quote(let text):
                    HStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 1.5).fill(Tone.rose.color.opacity(0.6)).frame(width: 3)
                        inline(text).font(Typo.sans(13)).foregroundStyle(Palette.ink2).lineSpacing(4)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.vertical, 8)
                case .bullet(let text):
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(Tone.rose.color)
                        inline(text).lineSpacing(4)
                    }
                    .font(Typo.sans(13)).padding(.vertical, 2)
                case .paragraph(let text):
                    inline(text).font(Typo.sans(13)).lineSpacing(4).padding(.vertical, 4)
                case .rule:
                    Rectangle().fill(Palette.line2).frame(height: 1).padding(.vertical, 10)
                }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    static func tone(_ speaker: String, _ others: [String]) -> Tone {
        if Transcript.isSelf(speaker) { return .clay }
        return palette[(others.firstIndex(of: speaker) ?? 0) % palette.count]
    }

    static func display(_ speaker: String) -> String {
        if speaker.hasPrefix("Speaker ") { return "说话人 " + speaker.dropFirst(8) }
        return speaker
    }

    private func turn(_ speaker: String, _ time: String?, _ text: String, tone: Tone, continued: Bool) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                if !continued {
                    Text(Self.display(speaker)).font(Typo.sans(12, .semibold)).foregroundStyle(tone.color).lineLimit(1)
                }
                if let time {
                    Button { PlaudText.seconds(time).map(seek) } label: {
                        Text(time).font(Typo.sans(10.5)).foregroundStyle(Palette.ink4).monospacedDigit()
                    }
                    .buttonStyle(.plain)
                    .help("从这里播放")
                }
            }
            .frame(width: 64, alignment: .leading)
            inline(text).font(Typo.sans(13)).lineSpacing(4).frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.top, continued ? 4 : 10)
    }

    private func inline(_ text: String) -> Text {
        Text((try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text))
    }
}

// MARK: - Audio

@MainActor @Observable
final class AudioController {
    private(set) var player: AVPlayer?
    private(set) var playing = false
    var time: Double = 0
    var loadedDuration: Double?
    var rate: Float = 1
    @ObservationIgnored private var observer: Any?
    @ObservationIgnored private var ended: NSObjectProtocol?

    func attach(_ player: AVPlayer) {
        self.player = player
        observer = player.addPeriodicTimeObserver(forInterval: CMTime(seconds: 0.25, preferredTimescale: 600), queue: .main) { [weak self] t in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.time = t.seconds
                if let d = player.currentItem?.duration.seconds, d.isFinite, d > 0 { self.loadedDuration = d }
            }
        }
        ended = NotificationCenter.default.addObserver(forName: AVPlayerItem.didPlayToEndTimeNotification, object: player.currentItem, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.playing = false
                self?.player?.seek(to: .zero)
            }
        }
    }

    func toggle() {
        guard let player else { return }
        if playing { player.pause() } else { player.playImmediately(atRate: rate) }
        playing.toggle()
    }

    func seek(to seconds: Double) {
        guard let player else { return }
        time = seconds
        player.seek(to: CMTime(seconds: seconds, preferredTimescale: 600), toleranceBefore: .zero, toleranceAfter: .zero)
        if !playing { toggle() }
    }

    func cycleRate() {
        rate = rate == 1 ? 1.5 : rate == 1.5 ? 2 : 1
        if playing { player?.rate = rate }
    }

    func stop() {
        player?.pause()
        playing = false
        if let observer { player?.removeTimeObserver(observer) }
        if let ended { NotificationCenter.default.removeObserver(ended) }
        observer = nil
        ended = nil
    }
}

private struct AudioBar: View {
    var audio: AudioController
    var duration: Double?
    var available: Bool
    @ViewState private var dragging: Double?

    var body: some View {
        let total = audio.loadedDuration ?? duration ?? 0
        let shown = dragging ?? audio.time
        let enabled = available && audio.player != nil
        HStack(spacing: 10) {
            Button { audio.toggle() } label: {
                Image(systemName: audio.playing ? "pause.fill" : "play.fill").font(.system(size: 10)).foregroundStyle(.white)
                    .frame(width: 26, height: 26).background(Circle().fill(Tone.rose.color.opacity(enabled ? 1 : 0.45)))
            }
            .buttonStyle(.plain).disabled(!enabled)
            GeometryReader { geo in
                let p = total > 0 ? min(1, shown / total) : 0
                ZStack(alignment: .leading) {
                    Capsule().fill(Tone.rose.color.opacity(0.18))
                    Capsule().fill(Tone.rose.color).frame(width: geo.size.width * p)
                }
                .frame(height: 4)
                .frame(maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0)
                    .onChanged { v in if enabled, total > 0 { dragging = max(0, min(1, v.location.x / geo.size.width)) * total } }
                    .onEnded { _ in if let d = dragging { audio.seek(to: d) }; dragging = nil })
            }
            .frame(height: 20)
            Text("\(PlaudText.clock(shown)) / \(PlaudText.clock(total))").font(Typo.sans(11)).foregroundStyle(Tone.rose.color).monospacedDigit().fixedSize()
            Button { audio.cycleRate() } label: {
                Text(audio.rate == 1 ? "1×" : audio.rate == 1.5 ? "1.5×" : "2×").font(Typo.sans(11, .medium)).foregroundStyle(Tone.rose.color)
                    .padding(.horizontal, 8).padding(.vertical, 2)
                    .background(Capsule().fill(Palette.card.opacity(0.7)))
            }
            .buttonStyle(.plain).disabled(!enabled)
            if !available {
                Text("示例模式不能播放").font(Typo.sans(11)).foregroundStyle(Palette.ink3).fixedSize()
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(RoundedRectangle(cornerRadius: 10).fill(Tone.rose.tint))
    }
}
