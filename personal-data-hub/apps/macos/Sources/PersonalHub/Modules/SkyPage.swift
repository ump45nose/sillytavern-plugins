import HubKit
import SwiftUI

/// 电脑历史: pick a day from the whole archive, see it as a 24-hour timeline per device, then read a window.
struct SkyPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let hub = state.hub
        if hub.skyDays.isEmpty {
            ModuleEmpty(symbol: "desktopcomputer", text: "本机还没有电脑历史归档\n~/.codex/skysight-sync/archive")
                .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        } else {
            let day = state.skyDay.flatMap { d in hub.skyDays.first { Calendar.hub.isDate($0, inSameDayAs: d) } } ?? hub.skyDays[0]
            let all = hub.skyWindows(day)
            let devices = Array(Set(all?.map(\.device) ?? [])).sorted()
            let device = state.skyDevice.flatMap { devices.contains($0) ? $0 : nil }
            let windows = (all ?? []).filter { device == nil || $0.device == device }
            let selected = windows.first { $0.id == state.skyWindow } ?? windows.first
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    SkyDayStrip(days: hub.skyDays, selected: day)
                    if devices.count > 1 {
                        Segmented(options: [(String?.none, "全部")] + devices.map { (Optional($0), SkyText.device($0)) },
                                  selection: Binding(get: { device }, set: { state.skyDevice = $0 }), small: true)
                            .fixedSize()
                    }
                }
                SkyTimeline(day: day, windows: all ?? [], devices: device.map { [$0] } ?? devices, selected: selected?.id) { id in
                    withAnimation(Motion.spring) { state.skyWindow = id }
                }
                HStack(alignment: .top, spacing: 16) {
                    SkyWindowList(windows: windows, loading: all == nil, selected: selected?.id) { id in
                        withAnimation(Motion.spring) { state.skyWindow = id }
                    }
                    .frame(width: 300)
                    if let selected {
                        SkyDetail(window: selected, live: hub.skyLive)
                            .id(selected.id)
                            .transition(.opacity.combined(with: .offset(y: 8)))
                    } else {
                        SkyCard {
                            Text(all == nil ? "正在读取…" : "这一天没有记录").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
                                .frame(maxWidth: .infinity, maxHeight: .infinity)
                        }
                    }
                }
                .frame(maxHeight: .infinity)
            }
        }
    }
}

private struct SkyCard<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }
}

/// Every archived day, newest on the left; scrolls back to the first sync.
private struct SkyDayStrip: View {
    var days: [Date]
    var selected: Date
    @Environment(AppState.self) private var state

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.horizontal) {
                HStack(spacing: 6) {
                    ForEach(days, id: \.self) { d in
                        let on = Calendar.hub.isDate(d, inSameDayAs: selected)
                        Button { withAnimation(Motion.spring) { state.skyDay = d; state.skyWindow = nil } } label: {
                            VStack(spacing: 1) {
                                Text(Self.top(d)).font(Typo.sans(10.5)).foregroundStyle(on ? Color.white.opacity(0.75) : Palette.ink3)
                                Text(HubFormat.md(d)).font(Typo.sans(13, .semibold)).monospacedDigit()
                                    .foregroundStyle(on ? Color.white : Palette.ink)
                            }
                            .frame(width: 54, height: 42)
                            .background(RoundedRectangle(cornerRadius: 10).fill(on ? Palette.ink : Palette.card))
                            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(on ? Color.clear : Palette.line))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .id(d)
                    }
                }
                .padding(.vertical, 1)
            }
            .scrollIndicators(.never)
            .onAppear { proxy.scrollTo(selected, anchor: .leading) }
        }
    }

    static func top(_ d: Date) -> String {
        let c = Calendar.hub, now = HubFormat.current()
        if c.isDate(d, inSameDayAs: now) { return "今天" }
        if let y = c.date(byAdding: .day, value: -1, to: now), c.isDate(d, inSameDayAs: y) { return "昨天" }
        return HubFormat.weekday(d)
    }
}

/// One row per device across the day: 6-hour windows as blocks, 10-minute segments as ticks in the top app's colour.
private struct SkyTimeline: View {
    var day: Date
    var windows: [SkyWindowItem]
    var devices: [String]
    var selected: String?
    var pick: (String) -> Void

    private let label: CGFloat = 92, row: CGFloat = 30

    var body: some View {
        let start = Calendar.hub.startOfDay(for: day)
        let segments = windows.flatMap(\.segments)
        let active = Double(Set(segments.map(\.id)).count) * 10 / 60
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(SkyText.day(day)).font(Typo.serif(17, .medium))
                Text("\(HubFormat.weekday(day)) · \(windows.count) 个窗口\(active > 0 ? " · 活跃约 \(Fmt.number(active, 1)) 小时" : "")")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Spacer()
            }
            GeometryReader { geo in
                let width = geo.size.width - label
                let x = { (d: Date) -> CGFloat in label + CGFloat(min(max(d.timeIntervalSince(start) / 86_400, 0), 1)) * width }
                ZStack(alignment: .topLeading) {
                    ForEach(Array(stride(from: 0, through: 24, by: 3)), id: \.self) { h in
                        Rectangle().fill(Palette.line2).frame(width: 1, height: CGFloat(devices.count) * (row + 6))
                            .offset(x: label + width * CGFloat(h) / 24)
                        Text("\(h)").font(Typo.sans(10)).foregroundStyle(Palette.ink4).monospacedDigit().fixedSize()
                            .offset(x: label + width * CGFloat(h) / 24 - (h == 24 ? 14 : h == 0 ? 0 : 5), y: CGFloat(devices.count) * (row + 6) + 2)
                    }
                    ForEach(Array(devices.enumerated()), id: \.1) { i, device in
                        let y = CGFloat(i) * (row + 6)
                        Text(SkyText.device(device)).font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(1)
                            .frame(width: label - 10, height: row, alignment: .leading).offset(y: y)
                        ForEach(windows.filter { $0.device == device }) { w in
                            let on = w.id == selected
                            let x0 = x(w.start), x1 = x(min(w.end, w.inProgress ? max(w.end, w.start.addingTimeInterval(600)) : w.end))
                            Button { pick(w.id) } label: {
                                RoundedRectangle(cornerRadius: 7)
                                    .fill(on ? Tone.steel.tint : Palette.sunk)
                                    .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(on ? Tone.steel.color.opacity(0.7) : Palette.line, lineWidth: on ? 1.5 : 1))
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .frame(width: max(x1 - x0 - 2, 6), height: row)
                            .offset(x: x0 + 1, y: y)
                            .help("\(SkyText.span(w)) · \(w.title)")
                            ForEach(w.segments) { s in
                                RoundedRectangle(cornerRadius: 1.5)
                                    .fill(AppCatalog.color(Self.lead(s)).opacity(on ? 0.95 : 0.7))
                                    .frame(width: max(width / 144 - 1, 2), height: row - 14)
                                    .offset(x: x(s.start), y: y + 7)
                                    .allowsHitTesting(false)
                            }
                        }
                    }
                }
            }
            .frame(height: CGFloat(max(devices.count, 1)) * (row + 6) + 14)
        }
        .padding(.horizontal, 18).padding(.vertical, 14)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }

    static func lead(_ s: SkySummary) -> String {
        s.apps.first { !["com.apple.finder", "com.apple.dock", "com.apple.loginwindow", "com.apple.WindowManager"].contains($0) } ?? s.apps.first ?? ""
    }
}

private struct SkyWindowList: View {
    var windows: [SkyWindowItem]
    var loading: Bool
    var selected: String?
    var pick: (String) -> Void

    var body: some View {
        SkyCard {
            if loading {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity).padding(.top, 40)
            } else {
                HubScroll {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(Array(windows.enumerated()), id: \.1.id) { i, w in
                            SkyListItem(window: w, selected: w.id == selected)
                                .onTapGesture { pick(w.id) }
                                .rise(min(i, 10))
                        }
                    }
                    .padding(10)
                }
            }
        }
    }
}

private struct SkyListItem: View {
    var window: SkyWindowItem
    var selected: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(SkyText.span(window)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
                Text(SkyText.device(window.device)).font(Typo.sans(11)).foregroundStyle(Palette.ink4)
                Spacer(minLength: 0)
                if let badge = SkyText.badge(window) { Chip(text: badge, tone: SkyText.live(window) ? .steel : nil) }
            }
            Text(window.title).font(Typo.sans(13, .semibold)).foregroundStyle(Palette.ink).lineLimit(2)
            AppIcons(bundles: window.apps.map(\.bundle), size: 13).padding(.top, 2)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(selected ? Tone.steel.tint : Color.clear))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(selected ? Tone.steel.color.opacity(0.35) : Color.clear))
        .contentShape(Rectangle())
    }
}

private struct SkyDetail: View {
    var window: SkyWindowItem
    var live: Bool

    var body: some View {
        SkyCard {
            HubScroll {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 8) {
                        Text("\(SkyText.span(window)) · \(SkyText.device(window.device))\(live ? "" : " · 示例")")
                            .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                        if let badge = SkyText.badge(window) { Chip(text: badge, tone: SkyText.live(window) ? .steel : nil) }
                    }
                    Text(window.title).font(Typo.serif(28)).padding(.top, 6).fixedSize(horizontal: false, vertical: true)
                    Text(window.summary).font(Typo.serif(15.5)).foregroundStyle(Palette.ink2).lineSpacing(6).padding(.top, 10)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                    AdaptiveRow(threshold: 640, spacing: 28, stackSpacing: 4) {
                        apps
                        segments
                    }
                    .padding(.top, 6)
                }
                .padding(26)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
        }
    }

    private var apps: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("应用分布")
            ForEach(Array(window.apps.prefix(8).enumerated()), id: \.1.bundle) { i, app in
                let info = AppCatalog.info(app.bundle)
                HStack(spacing: 10) {
                    AppIcons(bundles: [app.bundle], size: 16)
                    Text(info.name).font(Typo.sans(12.5)).lineLimit(1).frame(width: 104, alignment: .leading)
                    Track(value: app.share * 100, color: AppCatalog.color(app.bundle), height: 6, delay: Double(i) * 80)
                    Text("\(Int((app.share * 100).rounded()))%").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 38, alignment: .trailing)
                }
                .padding(.vertical, 5)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var segments: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionTitle("10 分钟片段 · \(window.segments.count)")
            if window.segments.isEmpty {
                Text("这个窗口没有片段记录").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
            ForEach(Array(window.segments.reversed().enumerated()), id: \.1.id) { i, s in
                HStack(alignment: .top, spacing: 10) {
                    VStack(spacing: 0) {
                        Circle().fill(AppCatalog.color(SkyTimeline.lead(s))).frame(width: 7, height: 7).padding(.top, 5)
                        if i < window.segments.count - 1 { Rectangle().fill(Palette.line).frame(width: 1).frame(maxHeight: .infinity) }
                    }
                    .frame(width: 8)
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(HubFormat.clock(s.start)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
                            AppIcons(bundles: s.apps.filter { $0 != "com.apple.finder" }, size: 11)
                        }
                        Text(s.title).font(Typo.sans(12.5)).foregroundStyle(Palette.ink)
                        if !s.summary.isEmpty {
                            Text(s.summary).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(3).fixedSize(horizontal: false, vertical: true)
                        }
                    }
                    .padding(.bottom, 10)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
