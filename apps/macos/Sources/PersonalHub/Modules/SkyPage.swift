import HubKit
import SwiftUI

/// 电脑历史, read as a day's journal: an overview band, the day's windows on the serif-clock timeline,
/// and the picked window as an article. Day and device pickers sit in the page header (`SkyControls`).
struct SkyPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        if state.hub.skyDays.isEmpty {
            ModuleEmpty(symbol: "desktopcomputer", text: "本机还没有电脑历史归档\n~/.codex/skysight-sync/archive")
                .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        } else {
            let pick = SkyPick(state)
            let windows = pick.windows
            let selected = windows.first { $0.id == state.skyWindow } ?? windows.first
            VStack(alignment: .leading, spacing: 20) {
                SkyOverview(pick: pick, selected: selected?.id) { id in withAnimation(Motion.spring) { state.skyWindow = id } }
                HStack(alignment: .top, spacing: 24) {
                    SkyWindowList(windows: windows, loading: pick.all == nil, selected: selected?.id) { id in
                        withAnimation(Motion.spring) { state.skyWindow = id }
                    }
                    .frame(width: 340)
                    if let selected {
                        SkyDetail(window: selected, live: state.hub.skyLive)
                            .id(selected.id)
                            .transition(.opacity.combined(with: .offset(y: 8)))
                    } else {
                        Text(pick.all == nil ? "正在读取…" : "这一天没有记录").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                            .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
                            .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
                    }
                }
                .frame(maxHeight: .infinity)
            }
        }
    }
}

/// The picked day and device, resolved against what the archive has.
struct SkyPick {
    var day: Date
    /// Every device's windows that day; nil while loading.
    var all: [SkyWindowItem]?
    var devices: [String]
    var device: String?

    @MainActor init(_ state: AppState) {
        let hub = state.hub
        day = state.skyDay.flatMap { d in hub.skyDays.first { Calendar.hub.isDate($0, inSameDayAs: d) } } ?? hub.skyDays.first ?? HubFormat.current()
        all = hub.skyWindows(day)
        devices = Array(Set(all?.map(\.device) ?? [])).sorted()
        device = state.skyDevice.flatMap { devices.contains($0) ? $0 : nil }
    }

    /// The shown device's windows, newest first.
    var windows: [SkyWindowItem] {
        (all ?? []).filter { device == nil || $0.device == device }.sorted { $0.start > $1.start }
    }

    var shownDevices: [String] { device.map { [$0] } ?? devices }
}

// MARK: - Header controls

/// Device switch, then 「‹ 日期 ▾ ›」 with a shaded month calendar, then 今天.
struct SkyControls: View {
    @Environment(AppState.self) private var state
    @ViewState private var picking = false

    var body: some View {
        let hub = state.hub, pick = SkyPick(state)
        let index = hub.skyDays.firstIndex { Calendar.hub.isDate($0, inSameDayAs: pick.day) }
        HStack(spacing: 8) {
            if pick.devices.count > 1 {
                Segmented(options: [(String?.none, "全部设备")] + pick.devices.map { (Optional($0), SkyText.device($0)) },
                          selection: Binding(get: { pick.device }, set: { d in withAnimation(Motion.spring) { state.skyDevice = d } }), small: true)
                    .fixedSize()
            }
            HStack(spacing: 0) {
                step("chevron.left", to: index.flatMap { $0 + 1 < hub.skyDays.count ? hub.skyDays[$0 + 1] : nil }, help: "前一天")
                Button { picking = true } label: {
                    HStack(spacing: 5) {
                        Text("\(SkyText.day(pick.day)) · \(HubFormat.weekday(pick.day))").font(Typo.sans(12.5, .semibold))
                        Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold)).foregroundStyle(Palette.ink3)
                    }
                    .padding(.horizontal, 8).frame(height: 28).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .popover(isPresented: $picking, arrowEdge: .bottom) {
                    SkyMonth(selected: pick.day) { d in
                        picking = false
                        go(d)
                    }
                    .environment(state)
                }
                step("chevron.right", to: index.flatMap { $0 > 0 ? hub.skyDays[$0 - 1] : nil }, help: "后一天")
            }
            .padding(.horizontal, 2).frame(height: 32)
            .background(RoundedRectangle(cornerRadius: 9).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Palette.line))
            if let first = hub.skyDays.first, !Calendar.hub.isDate(first, inSameDayAs: pick.day) {
                ToolButton(symbol: "arrow.uturn.backward", title: Calendar.hub.isDateInToday(first) ? "今天" : "最新") { go(first) }
            }
        }
    }

    private func step(_ symbol: String, to day: Date?, help: String) -> some View {
        Button { if let day { go(day) } } label: {
            Image(systemName: symbol).font(.system(size: 11, weight: .semibold))
                .foregroundStyle(day == nil ? Palette.ink4 : Palette.ink2)
                .frame(width: 26, height: 28).contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(day == nil).help(help)
    }

    private func go(_ day: Date) {
        withAnimation(Motion.spring) {
            state.skyDay = day
            state.skyWindow = nil
        }
    }
}

/// Month grid shaded by how many 10-minute segments each day has; days without an archive are disabled.
struct SkyMonth: View {
    var selected: Date
    var pick: (Date) -> Void
    @Environment(AppState.self) private var state
    @ViewState private var month: Date?

    private static let heat = ["#EFEAE0", "#EFE1D3", "#E8C9B5", "#DFA88E", "#CB8466", "#B35A3D"].map { Color(hex: $0) }

    var body: some View {
        let cal = Calendar.hub, hub = state.hub
        let first = cal.date(from: cal.dateComponents([.year, .month], from: month ?? selected))!
        let lead = (cal.component(.weekday, from: first) + 5) % 7
        let count = cal.range(of: .day, in: .month, for: first)!.count
        let days = Set(hub.skyDays.map { cal.startOfDay(for: $0) })
        let peak = max(hub.skyActivity.values.max() ?? 1, 1)
        let earliest = hub.skyDays.last.flatMap { cal.date(from: cal.dateComponents([.year, .month], from: $0)) } ?? first
        let latest = hub.skyDays.first.flatMap { cal.date(from: cal.dateComponents([.year, .month], from: $0)) } ?? first
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(verbatim: "\(cal.component(.year, from: first)) 年 \(cal.component(.month, from: first)) 月").font(Typo.serif(16))
                Spacer()
                ForEach([-1, 1], id: \.self) { dir in
                    let target = cal.date(byAdding: .month, value: dir, to: first)!
                    let ok = dir < 0 ? target >= earliest : target <= latest
                    Button { withAnimation(Motion.fast) { month = target } } label: {
                        Image(systemName: dir < 0 ? "chevron.left" : "chevron.right").font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(ok ? Palette.ink2 : Palette.ink4).frame(width: 22, height: 22).contentShape(Rectangle())
                    }
                    .buttonStyle(.plain).disabled(!ok)
                }
            }
            LazyVGrid(columns: Array(repeating: GridItem(.fixed(32), spacing: 4), count: 7), spacing: 4) {
                ForEach(MonthCalendar.weekdays, id: \.self) { Text($0).font(Typo.sans(10.5)).foregroundStyle(Palette.ink3) }
                ForEach(-lead..<0, id: \.self) { _ in Color.clear.frame(height: 28) }
                ForEach(0..<count, id: \.self) { i in
                    let d = cal.date(byAdding: .day, value: i, to: first)!
                    let has = days.contains(d), on = cal.isDate(d, inSameDayAs: selected)
                    let n = hub.skyActivity[d] ?? 0
                    let level = has ? min(5, Int((Double(n) / Double(peak) * 5).rounded(.up))) : 0
                    Button { pick(d) } label: {
                        Text("\(i + 1)").font(Typo.sans(11.5, on ? .semibold : .regular)).monospacedDigit()
                            .foregroundStyle(on ? Color.white : has ? (level >= 4 ? Color.white : Palette.ink) : Palette.ink4)
                            .frame(width: 32, height: 28)
                            .background(RoundedRectangle(cornerRadius: 7).fill(on ? Palette.ink : has ? Self.heat[level] : .clear))
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain).disabled(!has)
                    .help(has ? "约 \(Fmt.number(Double(n) / 6, 1)) 小时活跃" : "没有归档")
                }
            }
            HStack(spacing: 4) {
                Text("少").font(Typo.sans(10)).foregroundStyle(Palette.ink3)
                ForEach(1..<6, id: \.self) { RoundedRectangle(cornerRadius: 2).fill(Self.heat[$0]).frame(width: 10, height: 10) }
                Text("多").font(Typo.sans(10)).foregroundStyle(Palette.ink3)
            }
        }
        .padding(14)
        .background(Palette.card)
    }
}

// MARK: - Overview

/// Active time, the day's app mix and a 24-hour ribbon per device; the picked window is outlined.
private struct SkyOverview: View {
    var pick: SkyPick
    var selected: String?
    var choose: (String) -> Void
    @Environment(AppState.self) private var state

    private let label: CGFloat = 92, row: CGFloat = 16

    var body: some View {
        let windows = pick.windows
        let segments = windows.flatMap(\.segments)
        let active = Double(Set(segments.map(\.id)).count) / 6
        let mix = Self.mix(segments)
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .bottom, spacing: 22) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(Fmt.number(active, 1)).font(Typo.serif(30)).tracking(-0.5).monospacedDigit()
                        Text("小时活跃").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    }
                    Text(caption(windows: windows.count, segments: segments.count, active: active))
                        .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(1)
                }
                .fixedSize()
                Rectangle().fill(Palette.line2).frame(width: 1, height: 40)
                VStack(alignment: .leading, spacing: 7) {
                    Label11("应用占比")
                    GeometryReader { g in
                        HStack(spacing: 2) {
                            ForEach(mix, id: \.bundle) { m in
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(m.bundle.isEmpty ? Palette.line : AppCatalog.color(m.bundle))
                                    .frame(width: max(3, (g.size.width - CGFloat(mix.count - 1) * 2) * m.share))
                            }
                        }
                    }
                    .frame(height: 8)
                    HStack(spacing: 12) {
                        ForEach(mix.filter { !$0.bundle.isEmpty }, id: \.bundle) { m in
                            HStack(spacing: 5) {
                                AppIcons(bundles: [m.bundle], size: 12)
                                Text(AppCatalog.info(m.bundle).name).font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(1)
                                Text("\(Int((m.share * 100).rounded()))%").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit()
                            }
                            .fixedSize()
                        }
                    }
                }
                .frame(maxWidth: 520, alignment: .leading)
                Spacer(minLength: 0)
            }
            ribbon
        }
        .padding(.horizontal, 22).padding(.top, 18).padding(.bottom, 14)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }

    private func caption(windows: Int, segments: Int, active: Double) -> String {
        let cal = Calendar.hub, hub = state.hub
        let week = (1...7).compactMap { cal.date(byAdding: .day, value: -$0, to: cal.startOfDay(for: pick.day)) }
            .compactMap { hub.skyActivity[$0] }
        var parts = ["\(windows) 个窗口", "\(segments) 个片段"]
        if pick.device == nil, week.count >= 3 {
            let avg = Double(week.reduce(0, +)) / Double(week.count) / 6, diff = active - avg
            if abs(diff) >= 0.1 { parts.append("比前 7 天均值\(diff > 0 ? "多" : "少") \(Fmt.number(abs(diff), 1)) 小时") }
        }
        return parts.joined(separator: " · ")
    }

    /// Lead app per segment as a share of the day: the top four, then everything else as one grey part.
    static func mix(_ segments: [SkySummary]) -> [(bundle: String, share: Double)] {
        guard !segments.isEmpty else { return [] }
        let counts = Dictionary(grouping: segments.map(SkyDetail.lead), by: { $0 }).mapValues(\.count)
            .filter { !$0.key.isEmpty }.sorted { $0.value > $1.value }
        let total = Double(segments.count)
        let top = counts.prefix(4).map { (bundle: $0.key, share: Double($0.value) / total) }
        let rest = 1 - top.reduce(0) { $0 + $1.share }
        return top + (rest > 0.005 ? [(bundle: "", share: rest)] : [])
    }

    private var ribbon: some View {
        let devices = pick.shownDevices.isEmpty ? [""] : pick.shownDevices
        let start = Calendar.hub.startOfDay(for: pick.day)
        let windows = pick.windows
        return VStack(alignment: .leading, spacing: 4) {
            GeometryReader { geo in
                let width = geo.size.width - label
                let x = { (d: Date) -> CGFloat in label + CGFloat(min(max(d.timeIntervalSince(start) / 86_400, 0), 1)) * width }
                ZStack(alignment: .topLeading) {
                    ForEach(Array(devices.enumerated()), id: \.1) { i, device in
                        let y = CGFloat(i) * (row + 8)
                        Text(SkyText.device(device)).font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(1)
                            .frame(width: label - 10, height: row, alignment: .leading).offset(y: y)
                        RoundedRectangle(cornerRadius: 5).fill(Palette.sunk)
                            .frame(width: width, height: row).offset(x: label, y: y)
                            .contentShape(Rectangle())
                            .onTapGesture { p in
                                let at = start.addingTimeInterval(Double(p.x / width) * 86_400)
                                if let w = windows.first(where: { $0.device == device && $0.start <= at && at < max($0.end, $0.start.addingTimeInterval(600)) }) {
                                    choose(w.id)
                                }
                            }
                        ForEach(windows.filter { $0.device == device }) { w in
                            ForEach(w.segments) { s in
                                RoundedRectangle(cornerRadius: 1.5)
                                    .fill(AppCatalog.color(SkyDetail.lead(s)).opacity(w.id == selected ? 0.95 : 0.6))
                                    .frame(width: max(width / 144 - 0.5, 2), height: row - 6)
                                    .offset(x: x(s.start), y: y + 3)
                                    .allowsHitTesting(false)
                            }
                        }
                    }
                    if let w = windows.first(where: { $0.id == selected }) {
                        let x0 = x(w.start), x1 = x(w.inProgress ? max(w.end, w.start.addingTimeInterval(600)) : w.end)
                        RoundedRectangle(cornerRadius: 7).strokeBorder(Palette.ink, lineWidth: 1.5)
                            .frame(width: max(x1 - x0 + 6, 12), height: CGFloat(devices.count) * (row + 8) + 4)
                            .offset(x: x0 - 3, y: -6)
                            .allowsHitTesting(false)
                            .animation(Motion.spring, value: selected)
                    }
                }
            }
            .frame(height: CGFloat(devices.count) * (row + 8) - 4)
            HStack(spacing: 0) {
                ForEach(Array(stride(from: 0, through: 24, by: 3)), id: \.self) { h in
                    Text("\(h)").font(Typo.sans(10)).foregroundStyle(Palette.ink4).monospacedDigit()
                    if h < 24 { Spacer(minLength: 0) }
                }
            }
            .padding(.leading, label)
            .padding(.top, 4)
        }
    }
}

// MARK: - Window list

/// The day's windows on the serif-clock timeline, newest first; each shows its app mix, trimmed to fit.
private struct SkyWindowList: View {
    var windows: [SkyWindowItem]
    var loading: Bool
    var selected: String?
    var pick: (String) -> Void

    var body: some View {
        if loading {
            ProgressView().controlSize(.small).frame(maxWidth: .infinity).padding(.top, 40)
        } else {
            HubScroll {
                VStack(alignment: .leading, spacing: 0) {
                    Text("\(windows.count) 个窗口").font(Typo.sans(11)).foregroundStyle(Palette.ink3).tracking(0.5)
                        .padding(.leading, 74).padding(.bottom, 14)
                    ForEach(Array(windows.enumerated()), id: \.1.id) { i, w in
                        let on = w.id == selected, live = SkyText.live(w)
                        TimelineEntry(time: HubFormat.clock(w.start), first: i == 0, last: i == windows.count - 1,
                                      dot: on ? Palette.ink : live ? Tone.steel.color : Palette.ink4.opacity(0.75),
                                      timeColor: on ? Palette.ink : Palette.ink3, timeWidth: 50, ring: Palette.bg, gap: 10) {
                            SkyListItem(window: w, selected: on)
                                .contentShape(Rectangle())
                                .onTapGesture { pick(w.id) }
                        }
                        .rise(min(i, 10))
                    }
                }
                .padding(.top, 2).padding(.bottom, 12).padding(.trailing, 4)
            }
            .scrollIndicators(.never)
        }
    }
}

private struct SkyListItem: View {
    var window: SkyWindowItem
    var selected: Bool

    var body: some View {
        let quiet = window.segments.isEmpty && window.title.isEmpty
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text("\(SkyText.span(window)) · \(SkyText.device(window.device))").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                    .monospacedDigit().lineLimit(1)
                Spacer(minLength: 0)
                if let badge = SkyText.badge(window) { Chip(text: badge, tone: SkyText.live(window) ? .steel : nil) }
            }
            Text(quiet ? "没有前台活动" : window.title).font(Typo.sans(13.5, quiet ? .regular : .semibold))
                .foregroundStyle(quiet ? Palette.ink3 : Palette.ink).lineLimit(2).fixedSize(horizontal: false, vertical: true)
            if !window.apps.isEmpty { SkyAppMix(apps: window.apps) }
        }
        .padding(.horizontal, 12).padding(.top, 9).padding(.bottom, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(selected ? Palette.card : Color.clear))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(selected ? Palette.line : Color.clear))
        .shadow(color: Color(hex: "#3C280A").opacity(selected ? 0.05 : 0), radius: 2, y: 1)
        .padding(.top, -9)
    }
}

/// A window's apps as one proportional bar, then as many name + share labels as fit; the rest count as +N.
private struct SkyAppMix: View {
    var apps: [(bundle: String, share: Double)]

    var body: some View {
        let total = max(apps.reduce(0) { $0 + $1.share }, 0.0001)
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { g in
                HStack(spacing: 1.5) {
                    ForEach(apps.prefix(6), id: \.bundle) { a in
                        RoundedRectangle(cornerRadius: 2).fill(AppCatalog.color(a.bundle))
                            .frame(width: max(2, (g.size.width - 8) * a.share / total))
                    }
                }
            }
            .frame(height: 4)
            ViewThatFits(in: .horizontal) {
                ForEach((1...min(apps.count, 4)).reversed(), id: \.self) { n in labels(n) }
            }
        }
    }

    private func labels(_ n: Int) -> some View {
        HStack(spacing: 10) {
            ForEach(apps.prefix(n), id: \.bundle) { a in
                HStack(spacing: 4) {
                    AppIcons(bundles: [a.bundle], size: 12)
                    Text(AppCatalog.info(a.bundle).name).lineLimit(1)
                    Text("\(Int((a.share * 100).rounded()))%").foregroundStyle(Palette.ink4).monospacedDigit()
                }
                .fixedSize()
            }
            if apps.count > n { Text("+\(apps.count - n)").foregroundStyle(Palette.ink4).fixedSize() }
        }
        .font(Typo.sans(11)).foregroundStyle(Palette.ink2)
    }
}

// MARK: - Detail

private struct SkyDetail: View {
    var window: SkyWindowItem
    var live: Bool
    @ViewState private var allSegments = false

    private static let preview = 6

    var body: some View {
        HubScroll {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 8) {
                    Text([SkyText.span(window), SkyText.device(window.device), "\(window.segments.count) 个片段", live ? nil : "示例"]
                        .compactMap { $0 }.joined(separator: " · "))
                        .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    if let badge = SkyText.badge(window) { Chip(text: badge, tone: SkyText.live(window) ? .steel : nil) }
                }
                Text(window.title).font(Typo.serif(28)).padding(.top, 8).fixedSize(horizontal: false, vertical: true)
                Text(window.summary).font(Typo.serif(16)).foregroundStyle(Palette.ink2).lineSpacing(8).padding(.top, 12)
                    .frame(maxWidth: 680, alignment: .leading)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                if !window.apps.isEmpty { apps }
                segments
            }
            .padding(.horizontal, 30).padding(.top, 26).padding(.bottom, 20)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .scrollIndicators(.never)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }

    private var apps: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("应用分布 · 出现在多少片段里").padding(.top, 8)
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 28), GridItem(.flexible(), spacing: 28)], alignment: .leading, spacing: 10) {
                ForEach(Array(window.apps.prefix(8).enumerated()), id: \.1.bundle) { i, app in
                    HStack(spacing: 10) {
                        AppIcons(bundles: [app.bundle], size: 16)
                        Text(AppCatalog.info(app.bundle).name).font(Typo.sans(12.5)).lineLimit(1).frame(width: 96, alignment: .leading)
                        Track(value: app.share * 100, color: AppCatalog.color(app.bundle), height: 5, delay: Double(i) * 60)
                        Text("\(Int((app.share * 100).rounded()))%").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit()
                            .frame(width: 36, alignment: .trailing)
                    }
                }
            }
        }
    }

    private var segments: some View {
        let all = Array(window.segments.reversed())
        let shown = allSegments ? all : Array(all.prefix(Self.preview))
        return VStack(alignment: .leading, spacing: 0) {
            SectionTitle("10 分钟片段").padding(.top, 10)
            if all.isEmpty {
                Text("这个窗口没有片段记录").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
            ForEach(Array(shown.enumerated()), id: \.1.id) { i, s in
                TimelineEntry(time: HubFormat.clock(s.start), first: i == 0, last: i == shown.count - 1 && all.count == shown.count,
                              timeWidth: 46, gap: 18) {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(s.title).font(Typo.sans(13, .medium)).foregroundStyle(Palette.ink).fixedSize(horizontal: false, vertical: true)
                            AppIcons(bundles: s.apps.filter { $0 != "com.apple.finder" }, size: 11)
                        }
                        if !s.summary.isEmpty {
                            Text(s.summary).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).lineSpacing(3).lineLimit(3)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            if all.count > Self.preview {
                Button { withAnimation(Motion.spring) { allSegments.toggle() } } label: {
                    Text(allSegments ? "收起" : "显示其余 \(all.count - Self.preview) 个片段")
                        .font(Typo.sans(12)).foregroundStyle(Tone.steel.color)
                }
                .buttonStyle(.plain)
                .padding(.leading, 70).padding(.top, 6)
            }
        }
    }

    /// The segment's main app, skipping the always-present system ones.
    static func lead(_ s: SkySummary) -> String {
        s.apps.first { !["com.apple.finder", "com.apple.dock", "com.apple.loginwindow", "com.apple.WindowManager"].contains($0) } ?? s.apps.first ?? ""
    }
}
