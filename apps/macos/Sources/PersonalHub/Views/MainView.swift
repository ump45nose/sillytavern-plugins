import HubKit
import SwiftUI

/// Sidebar icon and ⌘-number for a page; the order comes from the layout.
enum NavEntry {
    static func symbol(_ page: Page) -> String {
        switch page.id {
        case "home": "house"
        case "life": "heart"
        case "usage": "chart.bar"
        case "sky": "desktopcomputer"
        case "memos": "note.text"
        case "review": "text.book.closed"
        default: "square.grid.2x2"
        }
    }

    static func shortcut(_ index: Int) -> String? { index < LayoutDocument.maxPages ? "⌘\(index + 1)" : nil }
}

struct MainView: View {
    @Environment(AppState.self) private var state
    var palette = ""

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
        .overlay {
            if state.paletteOpen {
                ZStack(alignment: .top) {
                    Color.black.opacity(0.12).contentShape(Rectangle())
                        .onTapGesture { withAnimation(Motion.fast) { state.paletteOpen = false } }
                    CommandPalette(query: palette).padding(.top, 96)
                        .transition(.opacity.combined(with: .scale(scale: 0.98, anchor: .top)))
                }
                .transition(.opacity)
            }
        }
        .frame(minWidth: 1100, minHeight: 720)
        .ignoresSafeArea()
        .preferredColorScheme(.light)
        .tint(Tone.clay.color)
    }
}

private struct Sidebar: View {
    @Environment(AppState.self) private var state
    @Namespace private var ns
    @ViewState private var renaming: String?
    @ViewState private var confirmDelete: Page?
    @ViewState private var dropTarget: String?

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
                let pages = state.layout.pages
                ForEach(Array(pages.enumerated()), id: \.1.id) { i, page in
                    row(page, index: i, count: pages.count)
                }
            }
            .padding(.horizontal, 10)
            .animation(Motion.spring, value: state.currentPage)
            .animation(Motion.spring, value: state.layout.pages.map(\.id))

            Text("自定义").font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.leading, 22).padding(.top, 22).padding(.bottom, 8)
            Button {
                if let id = state.newPage() { renaming = id }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "plus").font(.system(size: 12)).frame(width: 18)
                    Text("新建页面").font(Typo.sans(13))
                    Spacer()
                }
                .foregroundStyle(Palette.ink3)
                .padding(.horizontal, 10).frame(maxWidth: .infinity, minHeight: 34, alignment: .leading)
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(!state.layout.canAddPage)
            .opacity(state.layout.canAddPage ? 1 : 0.5)
            .padding(.horizontal, 10)
            .help(state.layout.canAddPage ? "新建一个空页面，再从「添加模块」放入模块" : "最多 \(LayoutDocument.maxPages) 个页面")
            Text("拖动或右键调整顺序、重命名").font(Typo.sans(10.5)).foregroundStyle(Palette.ink4).padding(.leading, 22).padding(.top, 6)

            Spacer()
            SourceHealth().padding(.horizontal, 12)
            HStack(spacing: 10) {
                UserAvatar(size: 30)
                VStack(alignment: .leading, spacing: 0) {
                    Text(state.displayName).font(Typo.sans(13, .semibold)).lineLimit(1)
                    Text("\(Host.current().localizedName ?? "Mac") · 设置 ⌘,").font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1)
                }
            }
            .padding(.horizontal, 18).padding(.vertical, 16)
            .contentShape(Rectangle())
            .onTapGesture { state.openSettings() }
        }
        .alert("删除页面「\(confirmDelete?.title ?? "")」？", isPresented: Binding(get: { confirmDelete != nil }, set: { if !$0 { confirmDelete = nil } })) {
            Button("删除", role: .destructive) {
                if let page = confirmDelete { state.deletePage(page.id) }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text("只删除这个页面的布局，模块和数据不受影响。")
        }
    }

    private func row(_ page: Page, index: Int, count: Int) -> some View {
        let on = state.currentPage == page.id
        return Button { state.go(page.id) } label: {
            HStack(spacing: 10) {
                Image(systemName: NavEntry.symbol(page)).font(.system(size: 13)).frame(width: 18)
                    .foregroundStyle(on ? Tone.clay.color : Palette.ink2)
                Text(page.title).font(Typo.sans(13, on ? .semibold : .regular)).lineLimit(1)
                Spacer()
                if let key = NavEntry.shortcut(index) { Kbd(key) }
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
            .overlay {
                if dropTarget == page.id {
                    RoundedRectangle(cornerRadius: 10).strokeBorder(Tone.clay.color.opacity(0.6), lineWidth: 1.5)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .draggable(page.id) {
            Text(page.title).font(Typo.sans(13, .semibold)).padding(.horizontal, 12).padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 9).fill(Palette.card))
        }
        .dropDestination(for: String.self) { ids, _ in
            guard let id = ids.first, id != page.id, state.layout.page(id) != nil else { return false }
            state.movePage(id, to: index)
            return true
        } isTargeted: { over in
            if over { dropTarget = page.id } else if dropTarget == page.id { dropTarget = nil }
        }
        .contextMenu {
            Button("重命名…") { renaming = page.id }
            Button("上移") { state.movePage(page.id, by: -1) }.disabled(index == 0)
            Button("下移") { state.movePage(page.id, by: 1) }.disabled(index == count - 1)
            if !LayoutDocument.isBuiltin(page.id) {
                Divider()
                Button("删除页面…", role: .destructive) { confirmDelete = page }
            }
        }
        .popover(isPresented: Binding(get: { renaming == page.id }, set: { if !$0 { renaming = nil } }), arrowEdge: .trailing) {
            PageNameField(page: page) { title, subtitle in
                if let title { state.renamePage(page.id, title: title, subtitle: subtitle) }
                renaming = nil
            }
        }
    }
}

/// Title and optional subtitle of a page; the subtitle shows under the page heading.
struct PageNameField: View {
    var page: Page
    var done: (String?, String) -> Void
    @ViewState private var title = ""
    @ViewState private var subtitle = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label11("页面名称")
            TextField("名称", text: $title).textFieldStyle(.roundedBorder).focused($focused).frame(width: 240)
                .onSubmit(submit)
            Label11("说明（可选）").padding(.top, 2)
            TextField("显示在页面标题下", text: $subtitle).textFieldStyle(.roundedBorder).frame(width: 240)
                .onSubmit(submit)
            HStack {
                Text("\(title.trimmingCharacters(in: .whitespaces).count) / \(LayoutDocument.maxTitle)")
                    .font(Typo.sans(11)).foregroundStyle(title.count > LayoutDocument.maxTitle ? Tone.rose.color : Palette.ink4)
                Spacer()
                Button("取消") { done(nil, "") }.keyboardShortcut(.cancelAction)
                Button("好", action: submit).keyboardShortcut(.defaultAction)
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(14)
        .onAppear {
            title = page.title
            subtitle = page.subtitle
            DispatchQueue.main.async { focused = true }
        }
    }

    private func submit() {
        let t = title.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        done(t, subtitle)
    }
}

private struct SourceHealth: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let hub = state.hub
        let sources = hub.data.sources.filter { $0.status != .unconfigured }
        let health = hub.sourcesHealthy
        let (tone, title): (Tone, String) = switch hub.status {
        case _ where hub.mode == .demo: (.ochre, "示例数据")
        case .needsSignIn: (.rose, "hub 需要重新登录")
        case .offline: (.ochre, "hub 离线 · 显示缓存")
        case .failed: (.rose, "hub 同步失败")
        default: (health.ok == health.total ? .olive : .ochre, "\(health.ok) / \(health.total) 来源正常")
        }
        Button { state.openSettings() } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Dot(color: tone.color, pulse: hub.status == .syncing)
                    Text(title).font(Typo.sans(12)).lineLimit(1)
                    Spacer()
                    if let at = HubFormat.stamp(hub.data.fetchedAt) { Text(at).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
                }
                if !sources.isEmpty {
                    HStack(spacing: 3) {
                        ForEach(sources) { s in
                            Capsule().fill(s.status == .ok ? Tone.olive.color.opacity(0.6) : s.status == .error ? Tone.rose.color : Tone.ochre.color)
                                .frame(height: 4)
                                .help("\(s.name) · \(Self.label(s.status))")
                        }
                    }
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Palette.line))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    static func label(_ s: HubStatus) -> String {
        switch s {
        case .ok: "正常"
        case .partial: "部分可用"
        case .stale: "数据过旧"
        case .error: "故障"
        case .unconfigured: "未接入"
        }
    }
}

private struct Toolbar: View {
    @Environment(AppState.self) private var state
    @ViewState private var showPending = false

    var body: some View {
        HStack(spacing: 10) {
            (Text("Personal Hub / ").foregroundColor(Palette.ink3) + Text(state.page.title).fontWeight(.semibold).foregroundColor(Palette.ink))
                .font(Typo.sans(12))
            Spacer()
            Button { withAnimation(Motion.fast) { state.paletteOpen = true } } label: {
                HStack(spacing: 8) {
                    Image(systemName: state.aiRun.running ? "sparkles" : "magnifyingglass").font(.system(size: 12))
                        .foregroundStyle(state.aiRun.running ? Tone.clay.color : Palette.ink3)
                    Text(state.aiRun.running ? "\(state.aiRun.agent.title) 正在回答…" : "搜索，或问 AI…").font(Typo.sans(12.5))
                    Spacer()
                    Kbd("⌘K")
                }
                .foregroundStyle(Palette.ink3)
                .padding(.horizontal, 12).frame(width: 300, height: 30)
                .background(RoundedRectangle(cornerRadius: 9).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Palette.line))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if !state.aiPending.items.isEmpty {
                ToolButton(symbol: "sparkles", title: "待确认 \(state.aiPending.items.count)", prominent: true) { showPending.toggle() }
                    .popover(isPresented: $showPending, arrowEdge: .bottom) { AIPendingList().environment(state) }
            }
            ToolButton(symbol: "arrow.triangle.2.circlepath", title: state.lastSync, spinning: state.syncingAny) { state.sync() }
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
        case .review:
            ReviewView()
        case .grid:
            ScrollViewReader { proxy in
                HubScroll {
                    VStack(alignment: .leading, spacing: 18) {
                        if page.id != "home" { PageHeader(page: page) }
                        if page.items.isEmpty, !state.editing { EmptyPage() }
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
    @Environment(AppState.self) private var state
    @ViewState private var renaming = false

    var body: some View {
        let modules: [ModuleID] = switch page.kind {
        case .grid: page.items.map(\.module)
        case .sky: [.sky]
        case .memos: [.memos]
        case .review: [.goals]
        }
        let stamp = HubFormat.stamp(modules.compactMap(state.updatedAt).max())
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(page.title).font(Typo.serif(34)).tracking(-0.6)
                    if state.editing {
                        Button { renaming = true } label: {
                            Image(systemName: "pencil").font(.system(size: 13, weight: .medium)).foregroundStyle(Palette.ink3)
                                .frame(width: 26, height: 26).background(Circle().fill(Palette.card))
                                .overlay(Circle().strokeBorder(Palette.line))
                        }
                        .buttonStyle(.plain)
                        .help("重命名页面")
                        .popover(isPresented: $renaming, arrowEdge: .bottom) {
                            PageNameField(page: page) { title, subtitle in
                                if let title { state.renamePage(page.id, title: title, subtitle: subtitle) }
                                renaming = false
                            }
                        }
                    }
                }
                if !page.subtitle.isEmpty {
                    Text(page.subtitle).font(Typo.sans(13)).foregroundStyle(Palette.ink2)
                }
            }
            Spacer()
            Text(([page.kind == .grid ? "\(page.items.count) 个模块" : nil, stamp.map { "更新于 " + $0 }].compactMap { $0 }).joined(separator: " · "))
                .font(Typo.sans(12)).foregroundStyle(Palette.ink3)
        }
    }
}

private struct EmptyPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "square.dashed").font(.system(size: 28, weight: .light)).foregroundStyle(Palette.ink4)
            Text("这个页面还没有模块").font(Typo.serif(19))
            Text("同一个模块可以同时放在多个页面，简略版和详细版各取所需。").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
            Button { withAnimation(Motion.spring) { state.editing = true } } label: {
                Text("添加模块").font(Typo.sans(12.5, .semibold)).foregroundStyle(.white)
                    .padding(.horizontal, 14).frame(height: 30)
                    .background(RoundedRectangle(cornerRadius: 9).fill(Palette.ink))
            }
            .buttonStyle(.plain).padding(.top, 4)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 56)
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.ink4, style: StrokeStyle(lineWidth: 1.5, dash: [6, 4])))
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
                if LayoutDocument.isBuiltin(page.id) {
                    Button("恢复本页默认") { state.resetPage() }.buttonStyle(.plain).font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
            }
            if page.unusedModules.isEmpty {
                Text("所有模块都已在此页").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            } else {
                Flow(spacing: 8) {
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
