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

struct SkyPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let items = state.hub.sky
        if items.isEmpty {
            ModuleEmpty(symbol: "desktopcomputer", text: "本机还没有电脑历史归档\n~/.codex/skysight-sync/archive")
                .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        } else {
            let selection = min(state.skySelection, items.count - 1)
            HStack(alignment: .top, spacing: 16) {
                HubScroll {
                    LazyVStack(alignment: .leading, spacing: 6) {
                        ForEach(Array(items.enumerated()), id: \.1.id) { i, s in
                            if i == 0 || !Calendar.hub.isDate(items[i - 1].start, inSameDayAs: s.start) {
                                Text(SkyText.day(s.start))
                                    .font(Typo.sans(11, .semibold)).foregroundStyle(Palette.ink3)
                                    .padding(.top, i == 0 ? 0 : 12).padding(.leading, 6)
                            }
                            SkyListItem(window: s, selected: selection == i)
                                .onTapGesture { withAnimation(Motion.spring) { state.skySelection = i } }
                                .rise(min(i, 12))
                        }
                    }
                    .padding(12)
                }
                .frame(width: 340)
                .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
                SkyDetail(window: items[selection], live: state.hub.skyLive)
                    .id(items[selection].id)
                    .transition(.opacity.combined(with: .offset(y: 8)))
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
                Text("\(SkyText.span(window)) · \(window.device)").font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
                if let badge = SkyText.badge(window) { Chip(text: badge, tone: SkyText.live(window) ? .steel : nil) }
            }
            Text(window.title).font(Typo.sans(13, .semibold)).lineLimit(2)
            AppIcons(bundles: window.apps.map(\.bundle), size: 13).padding(.top, 2)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(selected ? Tone.steel.tint : Color.clear))
        .contentShape(Rectangle())
    }
}

private struct SkyDetail: View {
    var window: SkyWindowItem
    var live: Bool

    var body: some View {
        HubScroll {
            VStack(alignment: .leading, spacing: 0) {
                Text("\(SkyText.day(window.start)) · \(SkyText.span(window)) · \(SkyText.device(window.device))\(live ? "" : " · 示例")")
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Text(window.title).font(Typo.serif(30)).padding(.top, 6).fixedSize(horizontal: false, vertical: true)
                Text(window.summary).font(Typo.serif(16)).foregroundStyle(Palette.ink2).lineSpacing(6).padding(.top, 12)
                    .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                SectionTitle("应用分布").padding(.top, 10)
                ForEach(Array(window.apps.prefix(8).enumerated()), id: \.1.bundle) { i, app in
                    let info = AppCatalog.info(app.bundle)
                    HStack(spacing: 10) {
                        AppIcons(bundles: [app.bundle], size: 16)
                        Text(info.name).font(Typo.sans(12.5)).lineLimit(1).frame(width: 110, alignment: .leading)
                        Track(value: app.share * 100, color: AppCatalog.color(app.bundle), height: 6, delay: Double(i) * 80)
                        Text("\(Int((app.share * 100).rounded()))%").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 40, alignment: .trailing)
                    }
                    .padding(.vertical, 5)
                }
                SectionTitle("10 分钟片段 · \(window.segments.count)")
                if window.segments.isEmpty {
                    Text("这个窗口没有片段记录").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
                ForEach(window.segments.reversed()) { s in
                    HStack(alignment: .top, spacing: 12) {
                        Text(HubFormat.clock(s.start)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 40, alignment: .leading)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.title).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2)
                            if !s.summary.isEmpty {
                                Text(s.summary).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(3).fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(.vertical, 6)
                }
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
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

struct MemosPage: View {
    @Environment(AppState.self) private var state
    @ViewState private var draft = ""

    var body: some View {
        @Bindable var state = state
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "lock.fill").font(.system(size: 10)).foregroundStyle(Palette.ink3)
                Text(state.memosURL).font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                Spacer()
                Button("在浏览器中打开") { if let u = URL(string: state.memosURL) { NSWorkspace.shared.open(u) } }
                    .buttonStyle(.plain).font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            }
            .padding(.horizontal, 14).frame(height: 38)
            .background(Palette.sunk)
            .overlay(alignment: .bottom) { Rectangle().fill(Palette.line).frame(height: 1) }
            if let url = URL(string: state.memosURL), url.scheme?.hasPrefix("http") == true {
                WebView(url: url)
            } else {
                VStack(spacing: 10) {
                    Text("设置 Memos 地址").font(Typo.serif(20))
                    TextField("http://nas:5230", text: $draft).textFieldStyle(.roundedBorder).frame(width: 320)
                    Button("保存") { state.memosURL = draft }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .background(Palette.card)
        .clipShape(RoundedRectangle(cornerRadius: Metrics.cardRadius))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
    }
}

struct WebView: NSViewRepresentable {
    var url: URL

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: config)
        view.load(URLRequest(url: url))
        return view
    }

    func updateNSView(_ view: WKWebView, context: Context) {
        if view.url?.host() != url.host() { view.load(URLRequest(url: url)) }
    }
}
