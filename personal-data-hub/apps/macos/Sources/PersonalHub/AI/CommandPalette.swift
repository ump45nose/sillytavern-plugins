import AppKit
import HubKit
import SwiftUI

/// ⌘K: jump to pages, tasks, events and memos, or ask the default agent.
struct CommandPalette: View {
    @Environment(AppState.self) private var state
    @ViewState private var query = ""
    @ViewState private var selection = 0
    @FocusState private var focused: Bool

    init(query: String = "") {
        _query = ViewState(initialValue: query)
    }

    static let suggestions = ["今天有哪些要紧的事？", "这周 Token 花了多少美元，主要花在哪？", "最近有哪些交流需要我跟进？"]

    enum Row: Identifiable {
        case ask(String), suggestion(String), page(Page), task(AgendaTask), event(AgendaEvent), memo(MemosData.Memo)

        var id: String {
            switch self {
            case .ask: "ask"
            case let .suggestion(s): "s:" + s
            case let .page(p): "p:" + p.id
            case let .task(t): "t:" + t.id
            case let .event(e): "e:" + e.id
            case let .memo(m): "m:" + m.id
            }
        }
    }

    private var trimmed: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }

    private var showingRun: Bool { state.aiRun.phase != .idle && trimmed == state.aiRun.prompt }

    private var rows: [Row] {
        guard !trimmed.isEmpty else {
            return Self.suggestions.map(Row.suggestion) + state.layout.pages.map(Row.page)
        }
        let q = trimmed.lowercased()
        let pages = state.layout.pages.filter { $0.title.lowercased().contains(q) }.map(Row.page)
        let tasks = state.agenda.search(trimmed).prefix(5).map(Row.task)
        let v = state.agenda.view
        var seen = Set<String>()
        let events = (v.allDay + v.events + v.upcomingEvents)
            .filter { seen.insert($0.id).inserted && $0.title.lowercased().contains(q) }
            .prefix(4).map(Row.event)
        var memoIDs = Set<String>()
        let memos = (state.memos.items + (state.hub.data.memos?.data?.recent ?? []))
            .filter { memoIDs.insert($0.id).inserted && $0.content.lowercased().contains(q) }
            .prefix(4).map(Row.memo)
        return [.ask(trimmed)] + pages + tasks + events + memos
    }

    var body: some View {
        let rows = rows
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "magnifyingglass").font(.system(size: 15, weight: .medium)).foregroundStyle(Palette.ink3)
                TextField("搜索任务、日程、Memo，或问 AI…", text: $query)
                    .textFieldStyle(.plain).font(Typo.sans(16))
                    .focused($focused)
                    .onSubmit { activate(rows.indices.contains(selection) ? rows[selection] : nil) }
                    .onKeyPress(.upArrow) { selection = max(selection - 1, 0); return .handled }
                    .onKeyPress(.downArrow) { selection = min(selection + 1, max(rows.count - 1, 0)); return .handled }
                    .onKeyPress(.escape) { close(); return .handled }
                if state.aiRun.running {
                    ProgressView().controlSize(.small)
                }
                Kbd("esc")
            }
            .padding(.horizontal, 18).frame(height: 56)
            Rectangle().fill(Palette.line2).frame(height: 1)

            if showingRun {
                AIRunPane(retry: { ask(state.aiRun.prompt) })
            } else {
                HubScroll {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(Array(rows.enumerated()), id: \.1.id) { i, row in
                            if i == 0 || header(rows[i - 1]) != header(row), let title = header(row) {
                                Text(title).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                                    .padding(.horizontal, 10).padding(.top, i == 0 ? 2 : 10).padding(.bottom, 4)
                            }
                            Button { activate(row) } label: { label(row, on: i == selection) }
                                .buttonStyle(.plain)
                                .onHover { if $0 { selection = i } }
                        }
                    }
                    .padding(8)
                }
                .frame(maxHeight: 380)
                .fixedSize(horizontal: false, vertical: true)
            }

            Rectangle().fill(Palette.line2).frame(height: 1)
            HStack(spacing: 12) {
                hint("↑↓", "选择")
                hint("↩", trimmed.isEmpty || selection == 0 ? "执行" : "打开")
                hint("⌘↩", "问 AI")
                Spacer()
                Button { state.openSettings() } label: {
                    Text("问 AI 使用 \(state.aiAgent.title)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                }
                .buttonStyle(.plain).help("在 设置 → AI 里更换默认 agent")
            }
            .padding(.horizontal, 16).frame(height: 34)
            .background(Palette.sunk)
            Button("") { if !trimmed.isEmpty { ask(trimmed) } }
                .keyboardShortcut(.return, modifiers: .command).frame(width: 0, height: 0).opacity(0)
        }
        .frame(width: 660)
        .background(RoundedRectangle(cornerRadius: 16).fill(Palette.card))
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Palette.line))
        .shadow(color: .black.opacity(0.16), radius: 30, y: 14)
        .onChange(of: query) { selection = 0 }
        .onAppear {
            if state.aiRun.phase != .idle, query.isEmpty { query = state.aiRun.prompt }
            focused = true
        }
    }

    private func header(_ row: Row) -> String? {
        switch row {
        case .ask: nil
        case .suggestion: "问 AI 试试"
        case .page: "页面"
        case .task: "任务"
        case .event: "日程"
        case .memo: "Memo"
        }
    }

    @ViewBuilder
    private func label(_ row: Row, on: Bool) -> some View {
        HStack(spacing: 10) {
            switch row {
            case let .ask(q):
                icon("sparkles", .clay)
                (Text("问 \(state.aiAgent.title)：").foregroundColor(Palette.ink2) + Text(q).foregroundColor(Palette.ink))
                    .font(Typo.sans(13.5, .medium)).lineLimit(1)
                Spacer(minLength: 8)
                Kbd("↩")
            case let .suggestion(s):
                icon("sparkles", .clay)
                Text(s).font(Typo.sans(13.5)).foregroundStyle(Palette.ink)
                Spacer()
            case let .page(p):
                icon(NavEntry.symbol(p), .ink)
                Text(p.title).font(Typo.sans(13.5)).foregroundStyle(Palette.ink)
                Text(p.subtitle).font(Typo.sans(12)).foregroundStyle(Palette.ink3).lineLimit(1)
                Spacer()
                if let i = state.layout.pages.firstIndex(where: { $0.id == p.id }), let k = NavEntry.shortcut(i) { Kbd(k) }
            case let .task(t):
                icon(t.completed ? "checkmark.circle.fill" : "circle", .olive)
                Text(t.title).font(Typo.sans(13.5)).foregroundStyle(t.completed ? Palette.ink3 : Palette.ink).lineLimit(1)
                Spacer(minLength: 8)
                Text([t.listTitle, t.due.map(HubFormat.md)].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink3).lineLimit(1)
            case let .event(e):
                icon("calendar", .sky)
                Text(e.title).font(Typo.sans(13.5)).foregroundStyle(Palette.ink).lineLimit(1)
                Spacer(minLength: 8)
                Text(HubFormat.md(e.start) + (e.allDay ? " 全天" : " " + Agenda.clock(e.start)))
                    .font(Typo.sans(12)).foregroundStyle(Palette.ink3).monospacedDigit()
            case let .memo(m):
                icon("note.text", .kraft)
                Text(m.content.replacingOccurrences(of: "\n", with: " ")).font(Typo.sans(13.5)).foregroundStyle(Palette.ink).lineLimit(1)
                Spacer(minLength: 8)
                if let d = m.createdAt { Text(HubFormat.md(d)).font(Typo.sans(12)).foregroundStyle(Palette.ink3) }
            }
        }
        .padding(.horizontal, 10).frame(height: 36)
        .background(RoundedRectangle(cornerRadius: 9).fill(on ? Palette.sunk : .clear))
        .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(on ? Palette.line2 : .clear))
        .contentShape(Rectangle())
    }

    private func icon(_ symbol: String, _ tone: Tone) -> some View {
        Image(systemName: symbol).font(.system(size: 12, weight: .medium))
            .foregroundStyle(tone == .ink ? Palette.ink2 : tone.color)
            .frame(width: 24, height: 24)
            .background(RoundedRectangle(cornerRadius: 7).fill(tone == .ink ? Palette.sunk : tone.tint))
    }

    private func hint(_ key: String, _ text: String) -> some View {
        HStack(spacing: 5) {
            Kbd(key)
            Text(text).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
        }
    }

    private func activate(_ row: Row?) {
        guard let row else { return }
        switch row {
        case let .ask(q): ask(q)
        case let .suggestion(s): ask(s)
        case let .page(p): state.go(p.id); close()
        case .task, .event: state.focus(.agenda); close()
        case .memo:
            if state.layout.page("memos") != nil { state.go("memos") }
            close()
        }
    }

    private func ask(_ q: String) {
        query = q
        state.aiRun.start(q, agent: state.aiAgent)
    }

    private func close() {
        withAnimation(Motion.fast) { state.paletteOpen = false }
    }
}

/// The streaming answer, plus whatever the agent proposed during this run.
struct AIRunPane: View {
    @Environment(AppState.self) private var state
    var retry: () -> Void

    var body: some View {
        let run = state.aiRun
        let proposed = state.aiPending.items(since: run.started)
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles").font(.system(size: 12, weight: .semibold)).foregroundStyle(Tone.clay.color)
                Text(run.agent.title).font(Typo.sans(12.5, .semibold))
                status(run)
                Spacer()
                if run.running {
                    Button("停止") { run.stop() }.buttonStyle(.hubSecondary)
                } else {
                    if !run.output.isEmpty {
                        Button("拷贝") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(run.output, forType: .string)
                        }
                        .buttonStyle(.hubSecondary)
                    }
                    Button("再问一次") { retry() }.buttonStyle(.hubSecondary)
                }
            }
            .padding(.horizontal, 18).padding(.top, 12).padding(.bottom, 8)

            HubScroll {
                VStack(alignment: .leading, spacing: 12) {
                    if !run.output.isEmpty {
                        MemoMarkdown(content: run.output).textSelection(.enabled)
                    } else if run.running {
                        Text(run.progress).font(Typo.mono(11.5)).foregroundStyle(Palette.ink3).lineLimit(2)
                    }
                    if case let .failed(message) = run.phase {
                        Text(message).font(Typo.sans(12.5)).foregroundStyle(Palette.clayDeep).textSelection(.enabled)
                    }
                    if !proposed.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("待你确认").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                            ForEach(proposed) { AIPendingRow(change: $0) }
                        }
                        .padding(.top, 4)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 18).padding(.bottom, 16)
            }
            .frame(minHeight: 120, maxHeight: 420)
            .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder
    private func status(_ run: AgentRun) -> some View {
        Group {
            switch run.phase {
            case .running:
                TimelineView(.periodic(from: .now, by: 1)) { t in
                    Text("思考中 · \(Int(t.date.timeIntervalSince(run.started ?? t.date)))s")
                }
            case .done:
                Text("完成" + (run.finished.flatMap { f in run.started.map { " · 用时 \(Int(f.timeIntervalSince($0)))s" } } ?? ""))
            case .failed: Text("未完成")
            case .idle: EmptyView()
            }
        }
        .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit()
    }
}

/// One proposed change with 拒绝 / 确认.
struct AIPendingRow: View {
    @Environment(AppState.self) private var state
    var change: AIPendingChange

    var body: some View {
        let pending = state.aiPending
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: change.symbol).font(.system(size: 12, weight: .medium)).foregroundStyle(Tone.clay.color)
                .frame(width: 26, height: 26)
                .background(RoundedRectangle(cornerRadius: 7).fill(Tone.clay.tint))
            VStack(alignment: .leading, spacing: 2) {
                (Text(change.verb + " · ").foregroundColor(Palette.ink3) + Text(change.headline).foregroundColor(Palette.ink))
                    .font(Typo.sans(13, .medium)).lineLimit(2)
                if let detail = change.detail {
                    Text(detail).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).lineLimit(2)
                }
                if let error = pending.errors[change.id] {
                    Text(error).font(Typo.sans(11.5)).foregroundStyle(Palette.clayDeep)
                }
            }
            Spacer(minLength: 8)
            if pending.busy.contains(change.id) {
                ProgressView().controlSize(.small).frame(height: 30)
            } else {
                Button("拒绝") { pending.reject(change) }.buttonStyle(.hubSecondary)
                Button("确认") { Task { await pending.confirm(change, state: state) } }.buttonStyle(.hubPrimary)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 12).fill(Palette.sunk))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Palette.line2))
    }
}

/// Toolbar popover listing everything agents proposed.
struct AIPendingList: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let items = state.aiPending.items
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("AI 提议的变更").font(Typo.serif(16, .medium))
                Spacer()
                if items.count > 1 {
                    Button("全部确认") { Task { await state.aiPending.confirmAll(state: state) } }.buttonStyle(.hubSecondary)
                }
            }
            if items.isEmpty {
                Text("没有待确认的变更").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3)
            } else {
                HubScroll {
                    VStack(spacing: 6) { ForEach(items) { AIPendingRow(change: $0) } }
                }
                .frame(maxHeight: 360).fixedSize(horizontal: false, vertical: true)
            }
            Text("agent 通过 MCP 只能提议；确认后才写入 Google、hub 或 Memos。").font(Typo.sans(11)).foregroundStyle(Palette.ink3)
        }
        .padding(16)
        .frame(width: 460)
        .background(Palette.card)
    }
}
