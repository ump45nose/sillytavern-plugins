import HubKit
import SwiftUI
import WebKit

// MARK: - 电脑历史

struct SkyModule: View {
    var size: ModuleSize
    @Environment(AppState.self) private var state

    var body: some View {
        let today = state.snapshot.sky.filter { !$0.yesterday }
        if size == .compact {
            let s = today[0]
            VStack(alignment: .leading, spacing: 0) {
                Label11("\(s.start) – \(s.end) · \(s.device)")
                Text(s.title).font(Typo.sans(13.5, .semibold)).padding(.top, 5)
                Text(s.summary).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineSpacing(2).lineLimit(2).padding(.top, 4)
                Spacer(minLength: 6)
                HStack(spacing: 4) {
                    AppDots(colors: s.apps)
                    Text("今日 \(today.count) 个窗口").font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.leading, 6)
                }
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(today.enumerated()), id: \.1.id) { i, s in
                    HStack(alignment: .top, spacing: 14) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(s.start); Text(s.end)
                            Text(s.device).foregroundStyle(Palette.ink4)
                        }
                        .font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 52, alignment: .leading)
                        VStack(alignment: .leading, spacing: 5) {
                            Text(s.title).font(Typo.sans(13, .semibold))
                            Text(s.summary).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).lineSpacing(2).fixedSize(horizontal: false, vertical: true)
                            AppDots(colors: s.apps)
                        }
                    }
                    .padding(.vertical, 10)
                    .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Palette.line2).frame(height: 1) } }
                    .rise(i)
                }
                Button { state.go("sky") } label: { Chip(text: "打开电脑历史 →") }.buttonStyle(.plain).padding(.top, 12)
            }
        }
    }
}

struct AppDots: View {
    var colors: [String]
    var body: some View {
        HStack(spacing: 4) {
            ForEach(colors.indices, id: \.self) { RoundedRectangle(cornerRadius: 3).fill(Color(hex: colors[$0])).frame(width: 12, height: 12) }
        }
    }
}

struct SkyPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let items = state.snapshot.sky
        HStack(alignment: .top, spacing: 16) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(items.enumerated()), id: \.1.id) { i, s in
                        if i == 0 || items[i - 1].yesterday != s.yesterday {
                            Text(s.yesterday ? "昨天 · 10 月 19 日" : "今天 · 10 月 20 日")
                                .font(Typo.sans(11, .semibold)).foregroundStyle(Palette.ink3)
                                .padding(.top, i == 0 ? 0 : 12).padding(.leading, 6)
                        }
                        SkyListItem(window: s, selected: state.skySelection == i)
                            .onTapGesture { withAnimation(Motion.spring) { state.skySelection = i } }
                            .rise(i)
                    }
                }
                .padding(12)
            }
            .frame(width: 340)
            .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))
            SkyDetail(window: items[state.skySelection])
                .id(state.skySelection)
                .transition(.opacity.combined(with: .offset(y: 8)))
        }
    }
}

private struct SkyListItem: View {
    var window: SkyWindow
    var selected: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(window.start) – \(window.end) · \(window.device)").font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit()
            Text(window.title).font(Typo.sans(13, .semibold))
            Text(window.summary).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(2)
            AppDots(colors: window.apps).padding(.top, 2)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(selected ? Tone.steel.tint : Color.clear))
        .contentShape(Rectangle())
    }
}

private struct SkyDetail: View {
    var window: SkyWindow
    private let appNames = ["Cursor", "Chrome", "终端", "Telegram", "Obsidian"]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("\(window.yesterday ? "10 月 19 日" : "10 月 20 日") · \(window.start) – \(window.end) · \(window.device)")
                .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            Text(window.title).font(Typo.serif(30)).padding(.top, 6)
            Text(window.summary).font(Typo.serif(16)).foregroundStyle(Palette.ink2).lineSpacing(6).padding(.top, 12)
                .fixedSize(horizontal: false, vertical: true)
            SectionTitle("应用分布").padding(.top, 10)
            ForEach(window.apps.indices, id: \.self) { i in
                HStack(spacing: 10) {
                    RoundedRectangle(cornerRadius: 3).fill(Color(hex: window.apps[i])).frame(width: 12, height: 12)
                    Text(appNames[i % appNames.count]).font(Typo.sans(12.5)).frame(width: 90, alignment: .leading)
                    Track(value: window.usage[i], color: Color(hex: window.apps[i]), height: 6, delay: Double(i) * 80)
                    Text("\(Int(window.usage[i]))%").font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 40, alignment: .trailing)
                }
                .padding(.vertical, 5)
            }
            SectionTitle("10 分钟片段")
            ForEach(0..<4, id: \.self) { i in
                HStack(alignment: .top, spacing: 12) {
                    Text(String(format: "%@:%d0", String(window.start.prefix(2)), i + 1)).font(Typo.sans(11)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 40, alignment: .leading)
                    Text(["整理模块规格与布局", "核对设计稿截图并修正排版", "查阅接口文档与限制", "提交并推送改动"][i]).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2)
                }
                .padding(.vertical, 6)
            }
            Spacer(minLength: 0)
        }
        .padding(28)
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
        let memos = state.snapshot.memos
        if size == .compact {
            VStack(alignment: .leading, spacing: 0) {
                Button { state.showQuickMemo() } label: { MiniInput(placeholder: "记一条…", shortcut: "⌃⌥M", icon: nil) }.buttonStyle(.plain)
                MemoText(memo: memos[0]).lineLimit(3).padding(.top, 12)
                Spacer(minLength: 4)
                Text(memos[0].time).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            }
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Button { state.showQuickMemo() } label: { MiniInput(placeholder: "现在的想法是…", shortcut: "⌃⌥M", icon: nil, height: 40) }.buttonStyle(.plain)
                Flow(spacing: 6) { ForEach(["#日报", "#周报", "#主线", "#阶段目标", "#想法"], id: \.self) { Chip(text: $0) } }
                    .padding(.vertical, 12)
                ForEach(Array(memos.enumerated()), id: \.1.id) { i, m in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(m.time).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                        MemoText(memo: m)
                    }
                    .padding(.vertical, 10)
                    .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
                    .rise(i)
                }
            }
        }
    }
}

struct MemoText: View {
    var memo: Memo
    var body: some View {
        memo.tags.reduce(Text(memo.text)) { $0 + Text(" ") + Text($1).foregroundColor(Tone.sky.color) }
            .font(Typo.sans(12.5)).foregroundStyle(Palette.ink).lineSpacing(3)
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
