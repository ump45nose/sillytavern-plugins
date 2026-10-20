import HubKit
import SwiftUI

struct NavEntry: Identifiable {
    var id: String
    var title: String
    var symbol: String
    var shortcut: String

    static let all = [
        NavEntry(id: "home", title: "主页", symbol: "house", shortcut: "⌘1"),
        NavEntry(id: "life", title: "生活", symbol: "heart", shortcut: "⌘2"),
        NavEntry(id: "usage", title: "用量", symbol: "chart.bar", shortcut: "⌘3"),
        NavEntry(id: "sky", title: "电脑历史", symbol: "desktopcomputer", shortcut: "⌘4"),
        NavEntry(id: "memos", title: "Memos", symbol: "note.text", shortcut: "⌘5"),
    ]
}

struct MainView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        HStack(spacing: 0) {
            Sidebar()
                .frame(width: Metrics.sidebarWidth)
                .background(Palette.side)
                .overlay(alignment: .trailing) { Rectangle().fill(Palette.line).frame(width: 1) }
            VStack(spacing: 0) {
                Toolbar()
                PageView()
                    .id(state.currentPage)
                    .transition(.opacity)
            }
            .background(Palette.bg)
        }
        .frame(minWidth: 1100, minHeight: 720)
        .ignoresSafeArea()
        .preferredColorScheme(.light)
    }
}

private struct Sidebar: View {
    @Environment(AppState.self) private var state
    @Namespace private var ns

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                LogoMark(animated: true).frame(width: 28, height: 28)
                VStack(alignment: .leading, spacing: 0) {
                    Text("Personal Hub").font(Typo.serif(16, .medium))
                    Text("个人信息中心").font(Typo.sans(10.5)).foregroundStyle(Palette.ink3)
                }
            }
            .padding(.leading, 18).padding(.top, 46).padding(.bottom, 22)

            VStack(spacing: 2) {
                ForEach(NavEntry.all) { e in
                    let on = state.currentPage == e.id
                    Button { state.go(e.id) } label: {
                        HStack(spacing: 10) {
                            Image(systemName: e.symbol).font(.system(size: 13)).frame(width: 18)
                                .foregroundStyle(on ? Tone.clay.color : Palette.ink2)
                            Text(e.title).font(Typo.sans(13, on ? .semibold : .regular))
                            Spacer()
                            Kbd(e.shortcut)
                        }
                        .foregroundStyle(on ? Palette.ink : Palette.ink2)
                        .padding(.horizontal, 10).frame(height: 34)
                        .background {
                            if on {
                                RoundedRectangle(cornerRadius: 10).fill(Palette.card)
                                    .shadow(color: .black.opacity(0.06), radius: 2, y: 1)
                                    .matchedGeometryEffect(id: "nav", in: ns)
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 10)
            .animation(Motion.spring, value: state.currentPage)

            Text("自定义").font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.leading, 22).padding(.top, 22).padding(.bottom, 8)
            HStack(spacing: 10) {
                Image(systemName: "plus").font(.system(size: 12)).frame(width: 18)
                Text("新建页面").font(Typo.sans(13))
            }
            .foregroundStyle(Palette.ink3)
            .padding(.horizontal, 10).frame(maxWidth: .infinity, minHeight: 34, alignment: .leading)
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
            .padding(.horizontal, 10)
            .help("自定义页面将在后续版本支持")

            Spacer()
            SourceHealth().padding(.horizontal, 12)
            HStack(spacing: 10) {
                Text("玮").font(Typo.sans(13, .semibold)).foregroundStyle(.white)
                    .frame(width: 30, height: 30).background(Circle().fill(Tone.clay.color))
                VStack(alignment: .leading, spacing: 0) {
                    Text("玮康").font(Typo.sans(13, .semibold))
                    Text("\(Host.current().localizedName ?? "Mac") · 设置 ⌘,").font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 16)
            .contentShape(Rectangle())
            .onTapGesture { state.openSettings() }
        }
    }
}

private struct SourceHealth: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Dot(color: Tone.olive.color)
                Text("示例数据 · 10 个来源").font(Typo.sans(12))
                Spacer()
                Text("17:58").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            }
            HStack(spacing: 3) {
                ForEach(0..<10, id: \.self) { i in
                    Capsule().fill(i == 4 ? Tone.ochre.color : Tone.olive.color.opacity(0.6)).frame(height: 4)
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Palette.line))
    }
}

private struct Toolbar: View {
    @Environment(AppState.self) private var state

    var body: some View {
        HStack(spacing: 10) {
            (Text("Personal Hub / ").foregroundColor(Palette.ink3) + Text(state.page.title).fontWeight(.semibold).foregroundColor(Palette.ink))
                .font(Typo.sans(12))
            Spacer()
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").font(.system(size: 12))
                Text("搜索任务、交流、Memo…").font(Typo.sans(12.5))
                Spacer()
                Kbd("⌘K")
            }
            .foregroundStyle(Palette.ink3)
            .padding(.horizontal, 12).frame(width: 300, height: 30)
            .background(RoundedRectangle(cornerRadius: 9).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Palette.line))
            ToolButton(symbol: "arrow.triangle.2.circlepath", title: state.lastSync, spinning: state.syncing) { state.sync() }
            if state.page.kind == .grid {
                ToolButton(symbol: "square.grid.2x2", title: state.editing ? "完成" : "编辑布局", prominent: state.editing) {
                    withAnimation(Motion.spring) { state.editing.toggle() }
                }
            }
        }
        .padding(.leading, 28).padding(.trailing, 24)
        .frame(height: 56)
        .padding(.top, 8)
    }
}

struct ToolButton: View {
    var symbol: String
    var title: String
    var spinning = false
    var prominent = false
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: symbol).font(.system(size: 12, weight: .medium))
                    .rotationEffect(.degrees(spinning ? 360 : 0))
                    .animation(spinning ? .linear(duration: 0.8).repeatForever(autoreverses: false) : .default, value: spinning)
                Text(title).font(Typo.sans(12.5, prominent ? .semibold : .regular)).monospacedDigit()
            }
            .foregroundStyle(prominent ? Color.white : Palette.ink2)
            .padding(.horizontal, 12).frame(height: 30)
            .background(RoundedRectangle(cornerRadius: 9).fill(prominent ? Palette.ink : Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(prominent ? Color.clear : Palette.line))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct PageView: View {
    @Environment(AppState.self) private var state
    @ViewState private var pulse: ModuleID?

    var body: some View {
        let page = state.page
        switch page.kind {
        case .sky:
            VStack(alignment: .leading, spacing: 18) { PageHeader(page: page); SkyPage() }
                .padding(.horizontal, 28).padding(.bottom, 24)
        case .memos:
            VStack(alignment: .leading, spacing: 18) { PageHeader(page: page); MemosPage() }
                .padding(.horizontal, 28).padding(.bottom, 24)
        case .grid:
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        if page.id != "home" { PageHeader(page: page) }
                        ModuleGrid {
                            ForEach(Array(page.items.enumerated()), id: \.1.module) { i, item in
                                ModuleCard(item: item, index: i, count: page.items.count, highlighted: pulse == item.module)
                                    .layoutValue(key: ModuleGrid.Span.self, value: item.effectiveSpan)
                                    .id(item.module)
                                    .rise(i)
                                    .transition(.scale(scale: 0.96).combined(with: .opacity))
                            }
                        }
                        if state.editing { AddModuleTile(page: page).transition(.opacity.combined(with: .offset(y: 8))) }
                    }
                    .padding(.horizontal, 28).padding(.top, 4).padding(.bottom, 32)
                }
                .scrollIndicators(.never)
                .onChange(of: state.focusedModule) { _, m in
                    guard let m else { return }
                    withAnimation(.easeInOut(duration: 0.4)) { proxy.scrollTo(m, anchor: .center) }
                    pulse = m
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) {
                        pulse = nil
                        state.focusedModule = nil
                    }
                }
            }
        }
    }
}

private struct PageHeader: View {
    var page: Page

    var body: some View {
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 4) {
                Text(page.title).font(Typo.serif(34)).tracking(-0.6)
                Text(page.subtitle).font(Typo.sans(13)).foregroundStyle(Palette.ink2)
            }
            Spacer()
            Text(page.kind == .grid ? "\(page.items.count) 个模块 · 更新于 17:58" : "更新于 17:58").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
        }
    }
}

private struct AddModuleTile: View {
    var page: Page
    @Environment(AppState.self) private var state

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("添加模块").font(Typo.sans(13, .semibold))
                Text("每个模块都有简略版和详细版，可放在任意页面").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Spacer()
                Button("恢复默认布局") { state.resetLayout() }.buttonStyle(.plain).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
            if page.unusedModules.isEmpty {
                Text("所有模块都已在此页").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            } else {
                HStack(spacing: 8) {
                    ForEach(page.unusedModules, id: \.self) { m in
                        Button { state.editPage { $0.add(m) } } label: {
                            HStack(spacing: 6) {
                                Image(systemName: m.info.symbol).font(.system(size: 11)).foregroundStyle(m.info.tone.color)
                                Text(m.info.title)
                            }
                            .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .background(Capsule().fill(Palette.card))
                            .overlay(Capsule().strokeBorder(Palette.line))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1.5, dash: [6, 4])))
    }
}
