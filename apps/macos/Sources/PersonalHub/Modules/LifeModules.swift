import HubKit
import SwiftUI

// MARK: - 健康

struct HealthModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let h = state.snapshot.health
        let stepPct = Double(h.steps) / Double(h.stepGoal) * 100
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top) {
                    Hero(value: Double(h.steps), unit: "步")
                    Spacer()
                    Ring(value: stepPct, color: Tone.olive.color, size: 46, width: 6)
                }
                Text("睡眠 \(sleepText(h.sleepMinutes)) · 静息心率 \(h.restingHR)").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
                Spacer(minLength: 6)
                Bars(values: h.steps14, height: 32, color: Tone.olive.color)
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 22) {
                    ZStack {
                        Ring(value: stepPct, color: Tone.olive.color, size: 118, width: 11)
                        Ring(value: Double(h.kcal) / Double(h.kcalGoal) * 100, color: Tone.clay.color, size: 88, width: 11)
                        Ring(value: Double(h.exercise) / Double(h.exerciseGoal) * 100, color: Tone.sky.color, size: 58, width: 11)
                    }
                    VStack(alignment: .leading, spacing: 10) {
                        Hero(value: Double(h.steps), unit: "/ \(Fmt.number(Double(h.stepGoal))) 步")
                        VStack(alignment: .leading, spacing: 5) {
                            Legend(items: [("步数 \(Int(stepPct))%", Tone.olive.color)])
                            Legend(items: [("活动 \(h.kcal) / \(h.kcalGoal) kcal", Tone.clay.color)])
                            Legend(items: [("锻炼 \(h.exercise) / \(h.exerciseGoal) 分钟", Tone.sky.color)])
                        }
                    }
                }
                HStack {
                    Stat(label: "睡眠", value: sleepText(h.sleepMinutes))
                    Stat(label: "静息心率", value: "\(h.restingHR)", unit: "bpm")
                    Stat(label: "血氧", value: "\(h.spo2)", unit: "%")
                }
                .padding(.top, 18)
                SectionTitle("近 14 天步数")
                Bars(values: h.steps14, height: 72, color: Tone.olive.color, labels: Bars.days14)
                HStack(alignment: .top, spacing: 24) {
                    VStack(alignment: .leading, spacing: 0) {
                        SectionTitle("昨晚睡眠 · 23:48 – 07:00")
                        SleepBar(stages: h.sleepStages)
                        Legend(items: h.sleepStages.map { ("\($0.name) \($0.minutes / 60)h\($0.minutes % 60)m", $0.tone.color) }).padding(.top, 8)
                    }
                    VStack(alignment: .leading, spacing: 0) {
                        SectionTitle("静息心率 · 14 天")
                        AreaLine(values: h.restingHR14, height: 52, color: Tone.rose.color)
                    }
                }
            }
        }
    }

    private func sleepText(_ m: Int) -> String { "\(m / 60)h\(m % 60)m" }
}

struct SleepBar: View {
    var stages: [(name: String, minutes: Int, tone: Tone)]
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let total = CGFloat(stages.reduce(0) { $0 + $1.minutes })
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

    var body: some View {
        let b = state.snapshot.bills
        let pct = b.month / b.budget * 100
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Hero(value: b.today, decimals: 2, prefix: "¥")
                Text("今日支出 · \(b.items.count) 笔").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
                Spacer(minLength: 6)
                HStack {
                    Text("本月 ¥\(Fmt.number(b.month))").foregroundStyle(Palette.ink2)
                    Spacer()
                    Text("预算 \(Int(pct))%").foregroundStyle(Palette.ink3)
                }
                .font(Typo.sans(11.5)).padding(.bottom, 6)
                Track(value: pct, color: Tone.kraft.color)
                Text("剩 ¥\(Fmt.number(b.budget - b.month)) · 还有 \(b.daysLeft) 天").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.top, 6)
            }
        } else {
            let catTotal = b.categories.reduce(0) { $0 + $1.amount }
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 24) {
                    VStack(alignment: .leading, spacing: 0) {
                        Hero(value: b.today, decimals: 2, prefix: "¥", unit: "今日")
                        VStack(spacing: 0) {
                            ForEach(b.items.indices, id: \.self) { i in
                                let it = b.items[i]
                                Row(title: it.title, sub: "\(it.category) · \(it.time)", trailing: "−" + Fmt.number(it.amount, 2))
                            }
                        }
                        .padding(.top, 12)
                    }
                    .frame(maxWidth: .infinity)
                    VStack(alignment: .leading, spacing: 0) {
                        SectionTitle("近 14 天").padding(.top, -18)
                        Bars(values: b.d14, height: 70, color: Tone.kraft.color, highlight: [6, 13], labels: Bars.days14)
                        SectionTitle("本月 · ¥\(Fmt.number(b.month)) / \(Fmt.number(b.budget))")
                        StackBar(parts: b.categories.map { ($0.amount, $0.tone.color) })
                        Legend(items: b.categories.map { ("\($0.name) \(Int(($0.amount / catTotal * 100).rounded()))%", $0.tone.color) }).padding(.top, 8)
                    }
                    .frame(maxWidth: .infinity)
                }
                SectionTitle("资产")
                HStack(alignment: .bottom, spacing: 24) {
                    VStack(alignment: .leading, spacing: 4) {
                        Label11("净资产")
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            CountUp(value: b.netWorth, prefix: "¥").font(Typo.serif(30))
                            Text("近 6 月 +14%").font(Typo.sans(12)).foregroundStyle(Tone.olive.color)
                        }
                    }
                    AreaLine(values: b.netWorth6, height: 40, color: Tone.olive.color).frame(maxWidth: 260)
                }
                HStack(spacing: 8) {
                    ForEach(b.accounts.indices, id: \.self) { i in
                        VStack(alignment: .leading, spacing: 3) {
                            Label11(b.accounts[i].name)
                            Text(b.accounts[i].value).font(Typo.serif(15)).monospacedDigit().lineLimit(1).minimumScaleFactor(0.8)
                        }
                        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
                    }
                }
                .padding(.top, 12)
            }
        }
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
                Text(sub).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
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
            let total = parts.reduce(0) { $0 + $1.0 }
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

    var body: some View {
        let c = state.snapshot.crm, cycle = state.snapshot.cycle
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Hero(value: Double(c.today.count), unit: "人 · 今日交流")
                HStack(spacing: -6) { ForEach(c.today) { PersonBadge(initial: $0.initial, tone: $0.tone) } }.padding(.top, 12)
                Spacer(minLength: 6)
                Chip(text: "2 段录音 · 1:46:52", tone: .rose, systemImage: "play.fill")
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                SectionTitle("今日 · \(c.today.count) 人").padding(.top, -18)
                ForEach(Array(c.today.enumerated()), id: \.1.id) { i, p in
                    HStack(alignment: .top, spacing: 12) {
                        PersonBadge(initial: p.initial, tone: p.tone, size: 32)
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(spacing: 8) {
                                Text(p.who).font(Typo.sans(13, .semibold))
                                Text("\(p.relation) · \(p.channel)").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                                Spacer()
                                Text(p.time).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
                            }
                            Text(p.summary).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
                            if let rec = p.recording, let dur = p.duration {
                                Recording(title: rec, duration: dur, seed: Int64(i + 2))
                            }
                        }
                    }
                    .padding(.vertical, 10)
                    .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                    .rise(i)
                }
                SectionTitle("第 \(cycle.index) 阶段")
                HStack(alignment: .bottom, spacing: 28) {
                    stageStat(c.stagePeople, "联系过的人")
                    stageStat(c.stageInteractions, "次交流")
                    stageStat(c.stageRecordings, "段录音")
                    Spacer()
                    VStack(alignment: .trailing, spacing: 6) {
                        Label11("久未联系")
                        Flow(spacing: 6) { ForEach(c.stale.indices, id: \.self) { Chip(text: "\(c.stale[$0].name) · \(c.stale[$0].days) 天") } }
                    }
                }
            }
        }
    }

    private func stageStat(_ v: Int, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            CountUp(value: Double(v)).font(Typo.serif(30))
            Label11(label)
        }
    }
}

struct Recording: View {
    var title: String
    var duration: String
    var seed: Int64
    @ViewState private var playing = false

    var body: some View {
        HStack(spacing: 10) {
            Button { playing.toggle() } label: {
                Image(systemName: playing ? "pause.fill" : "play.fill").font(.system(size: 10)).foregroundStyle(.white)
                    .frame(width: 26, height: 26).background(Circle().fill(Tone.rose.color))
            }
            .buttonStyle(.plain)
            Waveform(bars: 38, seed: seed, color: Tone.rose.color).frame(height: 22)
            Text("\(title) · \(duration) · 转录稿").font(Typo.sans(11)).foregroundStyle(Palette.ink2).lineLimit(1).fixedSize()
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 10).fill(Tone.rose.tint))
        .padding(.top, 4)
    }
}

// MARK: - 媒体

struct MediaModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let m = state.snapshot.media
        if size == .compact {
            let p = m.continueWatching[0]
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .top, spacing: 12) {
                    PosterView(poster: p, showTitle: false).frame(width: 62, height: 88)
                    VStack(alignment: .leading, spacing: 4) {
                        Label11("继续观看")
                        Text(p.title).font(Typo.serif(17))
                        Text("\(p.sub) · 已看 \(Int(p.progress))%").font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                    }
                }
                Spacer(minLength: 6)
                HStack {
                    Text("下载中 2 · ↓ 12.4 MB/s").font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                    Spacer()
                    Chip(text: "最近添加 3")
                }
            }
        } else {
            ViewThatFits(in: .horizontal) {
                detail(columns: 6, wide: true).frame(minWidth: 820)
                detail(columns: 3, wide: false)
            }
        }
    }

    private func detail(columns: Int, wide: Bool) -> some View {
        let m = state.snapshot.media
        return VStack(alignment: .leading, spacing: 0) {
            SectionTitle("继续观看 · Emby").padding(.top, -18)
            HStack(spacing: 12) {
                ForEach(Array(m.continueWatching.prefix(columns).enumerated()), id: \.1.id) { i, p in
                    PosterView(poster: p).aspectRatio(2 / 3, contentMode: .fit).frame(maxWidth: .infinity).rise(i)
                }
            }
            let latest = VStack(alignment: .leading, spacing: 0) {
                SectionTitle("最近添加")
                ForEach(m.latest.indices, id: \.self) { Row(title: m.latest[$0].title, sub: m.latest[$0].sub, trailing: "Emby") }
            }
            let music = VStack(alignment: .leading, spacing: 0) {
                SectionTitle("最近播放 · Navidrome")
                HStack(spacing: 8) {
                    ForEach(m.albums.indices, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 8)
                            .fill(LinearGradient(colors: m.albums[i].map(Color.init(hex:)), startPoint: .topLeading, endPoint: .bottomTrailing))
                            .aspectRatio(1, contentMode: .fit)
                    }
                }
                Text("《Random Access Memories》· 今天 09:12").font(Typo.sans(12)).foregroundStyle(Palette.ink2).padding(.top, 6)
            }
            let downloads = VStack(alignment: .leading, spacing: 0) {
                SectionTitle("下载 · MoviePilot")
                ForEach(m.downloads.indices, id: \.self) { i in
                    VStack(spacing: 5) {
                        HStack {
                            Text(m.downloads[i].title)
                            Spacer()
                            Text("\(Int(m.downloads[i].progress))%").foregroundStyle(Palette.ink3)
                        }
                        .font(Typo.sans(12))
                        Track(value: m.downloads[i].progress, color: Tone.plum.color, delay: Double(i) * 100)
                    }
                    .padding(.vertical, 6)
                }
                Text("↓ 12.4 MB/s · 做种 186 · 分享率 3.2").font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.top, 2)
            }
            if wide {
                HStack(alignment: .top, spacing: 28) { latest; music; downloads }
            } else {
                HStack(alignment: .top, spacing: 28) { latest; downloads }
                music
            }
            HStack(spacing: 6) {
                ForEach(["Emby", "Navidrome", "MoviePilot", "qBittorrent", "PT 站点"], id: \.self) { Chip(text: "\($0) ↗") }
            }
            .padding(.top, 16)
        }
    }
}

struct PosterView: View {
    var poster: Poster
    var showTitle = true

    var body: some View {
        RoundedRectangle(cornerRadius: 12)
            .fill(LinearGradient(colors: poster.gradient.map(Color.init(hex:)), startPoint: .top, endPoint: .bottom))
            .overlay {
                if showTitle {
                    Text(String(poster.title.prefix(1))).font(Typo.serif(44)).foregroundStyle(.white.opacity(0.18))
                }
            }
            .overlay(alignment: .bottomLeading) {
                VStack(alignment: .leading, spacing: 6) {
                    if showTitle {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(poster.title).font(Typo.sans(12, .semibold)).lineLimit(1)
                            Text(poster.sub).font(Typo.sans(10.5)).opacity(0.8)
                        }
                        .foregroundStyle(.white)
                        .padding(.horizontal, 10)
                    }
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Rectangle().fill(.white.opacity(0.25))
                            Rectangle().fill(Tone.clay.color).frame(width: geo.size.width * poster.progress / 100)
                        }
                    }
                    .frame(height: 3)
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .shadow(color: .black.opacity(0.12), radius: 6, y: 3)
    }
}
