import HubKit
import SwiftUI

enum StageTone {
    static func of(_ domain: String) -> Tone {
        switch domain {
        case "身体": .olive
        case "事业": .clay
        case "财务": .kraft
        case "关系": .rose
        case "生活": .sage
        default: .steel
        }
    }

    /// The design's tick strip, from live cycle data.
    static func cycle(_ c: GoalsData.Cycle) -> Cycle {
        let total = c.total ?? 42
        return Cycle(index: c.index ?? 1, day: min(max(c.day ?? 1, 1), total), total: total,
                     start: ReviewText.md(c.startsAt), end: ReviewText.md(c.endsAt))
    }
}

/// Mainline, the current 42-day cycle and its goals; closing a cycle and opening the next.
struct StageView: View {
    @Environment(AppState.self) private var state
    @ViewState private var adding = false

    var body: some View {
        let g = state.review.goals
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                if let m = g?.mainline { mainline(m) }
                if let c = g?.cycle {
                    cycle(c)
                    SectionTitle("阶段目标 · \(g?.goals?.count ?? 0) / \(Stage.maxGoals)")
                    VStack(spacing: 10) {
                        ForEach(g?.goals ?? []) { goal in GoalCard(goal: goal) }
                        if c.status == "active", (g?.goals?.count ?? 0) < Stage.maxGoals {
                            if adding {
                                AddGoalForm(cycle: c)
                            } else {
                                Button("新增目标…") { adding = true }.buttonStyle(.link).font(Typo.sans(12))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                    if let close = g?.close, close.status == .preclose || close.status == .awaitingClose {
                        SectionTitle("阶段结案")
                        CloseForm(cycle: c, goals: g?.goals ?? [], close: close)
                    } else if let at = c.precloseAt {
                        Text("\(ReviewText.md(at)) 起可以结案；结案时为每个目标选择成功、失败或停止，并写下阶段总结。")
                            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.top, 14)
                    }
                } else {
                    NextCycle(goals: g)
                }
                if g == nil {
                    Text(state.hub.mode == .hub ? "hub 还没有提供主线与阶段数据" : "连接 hub 后显示 personal-review 的主线与阶段")
                        .font(Typo.sans(13)).foregroundStyle(Palette.ink3).padding(.top, 40)
                }
            }
            .padding(.horizontal, 28).padding(.top, 30).padding(.bottom, 28)
            .frame(maxWidth: 860, alignment: .leading)
        }
        .scrollIndicators(.never)
    }

    private func mainline(_ m: GoalsData.Mainline) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Label11(m.domain ?? "总主线")
            Mainline(text: m.direction ?? "—", size: 28).padding(.top, 4)
            let facts = [("为什么", m.purpose), ("意味着", m.meaning), ("现在", m.status), ("最近的变化", m.recentChange)]
                .compactMap { k, v in v.flatMap { $0.isEmpty ? nil : (k, $0) } }
            if !facts.isEmpty {
                Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 14, verticalSpacing: 6) {
                    ForEach(facts, id: \.0) { k, v in
                        GridRow {
                            Text(k).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                            Text(v).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2)
                        }
                    }
                }
                .padding(.top, 12)
            }
        }
    }

    private func cycle(_ c: GoalsData.Cycle) -> some View {
        let ticks = StageTone.cycle(c)
        return VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("第 \(ticks.index) 阶段").font(Typo.sans(13, .semibold))
                Text("第 \(ticks.day) / \(ticks.total) 天 · 剩 \(ticks.remaining) 天").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                Spacer()
                if let chip = ReviewText.closeChip(state.review.goals?.close?.status) { Chip(text: chip.0, tone: chip.1) }
            }
            CycleTicks(cycle: ticks, height: 20, spacing: 3).padding(.top, 10)
            HStack {
                Text("\(ticks.start) 开始")
                Spacer()
                Text("\(ticks.end) 结案")
            }
            .font(Typo.sans(11)).foregroundStyle(Palette.ink3).padding(.top, 6)
        }
        .padding(.top, 24)
    }
}

private struct GoalCard: View {
    var goal: GoalsData.Goal
    @Environment(AppState.self) private var state
    @ViewState private var writing = false
    @ViewState private var note = ""
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var confirm = false

    var body: some View {
        Card(padding: 16) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Chip(text: goal.domain, tone: StageTone.of(goal.domain))
                Text(goal.goal).font(Typo.serif(17)).lineLimit(2)
                Spacer(minLength: 8)
                if let d = goal.deadline { Text("截止 \(d)").font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
            }
            if let p = goal.progress, !p.isEmpty {
                Text(p).font(Typo.sans(12.5)).foregroundStyle(Palette.ink2).padding(.top, 8)
            }
            Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 12, verticalSpacing: 4) {
                if let s = goal.successCriteria { row("成功标准", s) }
                if let s = goal.stopSignal { row("中止信号", s) }
            }
            .padding(.top, 8)
            if let c = goal.latestComment {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: "text.bubble").font(.system(size: 10)).foregroundStyle(Palette.ink3)
                    Text(c.text).font(Typo.sans(12)).foregroundStyle(Palette.ink2).lineLimit(3)
                    if let at = c.createdAt { Text(HubFormat.ago(at)).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
                }
                .padding(.top, 8)
            }
            if writing {
                HStack(spacing: 8) {
                    TextField("这次的进度或决定，原样写入目标评论", text: $note, axis: .vertical)
                        .textFieldStyle(.roundedBorder).lineLimit(1...4)
                    Button("取消") { writing = false; note = "" }
                    Button(busy ? "写入中…" : "写入") { confirm = true }
                        .disabled(busy || note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .padding(.top, 10)
            } else if goal.status == "active" {
                Button("记进度") { writing = true }.buttonStyle(.link).font(Typo.sans(12)).padding(.top, 8)
            }
            if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).padding(.top, 6) }
        }
        .alert("写入这条进度？", isPresented: $confirm) {
            Button("写入") { save() }
            Button("取消", role: .cancel) {}
        } message: {
            Text("会作为「\(goal.goal)」目标 Memo 的评论保存，不会改写。")
        }
    }

    private func row(_ k: String, _ v: String) -> some View {
        GridRow {
            Text(k).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            Text(v).font(Typo.sans(12)).foregroundStyle(Palette.ink2)
        }
    }

    private func save() {
        busy = true
        error = nil
        let id = goal.id, text = note
        Task {
            defer { busy = false }
            do {
                _ = try await state.review.stage(false, { try await $0.commentGoal(id: id, text: text, dryRun: false) },
                                                 demo: { StageResult(status: "dry-run", content: text) })
                writing = false
                note = ""
            } catch { self.error = ReviewDesk.message(error) }
        }
    }
}

/// Every goal gets a terminal state, and the summary is the user's own words, stored verbatim.
private struct CloseForm: View {
    var cycle: GoalsData.Cycle
    var goals: [GoalsData.Goal]
    var close: GoalsData.Close
    @Environment(AppState.self) private var state
    @ViewState private var outcomes: [String: String] = [:]
    @ViewState private var text = ""
    @ViewState private var preview: String?
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var done = false

    private var key: String { "stage:close:\(cycle.id)" }
    private var body0: String { Self.body(of: close.template ?? ReviewSample.closeTemplate(cycle.id)) }
    private var ready: Bool { goals.allSatisfy { outcomes[$0.id] != nil } && text.trimmingCharacters(in: .whitespacesAndNewlines) != body0.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        Card {
            if done {
                DoneBanner(text: "第 \(cycle.index ?? 1) 阶段已结案，目标已归档")
            } else if let preview {
                PreviewSheet(title: "阶段总结预览 · 原文写入，不做润色", content: preview + "\n\n" + summaryLine, confirm: "确认结案", busy: busy, error: error,
                             back: { self.preview = nil }, commit: commit)
                    .frame(minHeight: 320)
            } else {
                Text(close.status == .awaitingClose ? "已过结案日，目标已冻结。结案后才能开始下一阶段。" : "\(ReviewText.md(cycle.endsAt)) 结案。为每个目标选一个终态，再写下阶段总结。")
                    .font(Typo.sans(12)).foregroundStyle(close.status == .awaitingClose ? Tone.rose.color : Palette.ink3)
                VStack(spacing: 8) {
                    ForEach(goals) { g in
                        HStack(spacing: 10) {
                            Chip(text: g.domain, tone: StageTone.of(g.domain))
                            Text(g.goal).font(Typo.sans(13)).lineLimit(1)
                            Spacer()
                            Picker("", selection: Binding(get: { outcomes[g.id] ?? "" }, set: { outcomes[g.id] = $0 })) {
                                Text("未选").tag("")
                                ForEach(Stage.outcomes, id: \.self) { Text($0).tag($0) }
                            }
                            .pickerStyle(.segmented).labelsHidden().frame(width: 230)
                        }
                    }
                }
                .padding(.top, 12)
                TextEditor(text: $text)
                    .font(Typo.sans(13)).scrollContentBackground(.hidden).padding(10).frame(minHeight: 170)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
                    .padding(.top, 12)
                if let error { Text(error).font(Typo.sans(12)).foregroundStyle(Tone.rose.color).padding(.top, 8) }
                HStack {
                    Text("每个目标都要选终态；总结按原文保存").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                    Spacer()
                    Button(busy ? "检查中…" : "预览结案") { check() }.disabled(busy || !ready)
                }
                .padding(.top, 10)
            }
        }
        .onAppear { text = state.review.drafts.texts[key] ?? body0 }
        .onChange(of: text) { _, t in state.review.setText(t, for: key, template: body0) }
    }

    private var summaryLine: String {
        goals.map { "\($0.domain)「\($0.goal)」：\(outcomes[$0.id] ?? "")" }.joined(separator: "\n")
    }

    /// `close_cycle` adds the `#阶段总结` header itself.
    static func body(of template: String) -> String {
        var lines = template.components(separatedBy: "\n")
        if lines.first?.hasPrefix("#阶段总结") == true { lines.removeFirst() }
        while lines.first?.trimmingCharacters(in: .whitespaces).isEmpty == true { lines.removeFirst() }
        return lines.joined(separator: "\n")
    }

    private func check() { run(dryRun: true) }
    private func commit() { run(dryRun: false) }

    private func run(dryRun: Bool) {
        busy = true
        error = nil
        let id = cycle.id, summary = text, chosen = outcomes
        Task {
            defer { busy = false }
            do {
                let r = try await state.review.stage(dryRun, { try await $0.closeCycle(id: id, text: summary, outcomes: chosen, dryRun: dryRun) },
                                                     demo: { StageResult(status: "dry-run", content: "#阶段总结 \(id)\n\n" + summary) })
                if dryRun { preview = r.content ?? summary } else {
                    state.review.setText("", for: key, template: body0)
                    done = true
                }
            } catch { self.error = ReviewDesk.message(error) }
        }
    }
}

/// After a close: open the next cycle, then add up to five goals (personal-review validates them).
private struct NextCycle: View {
    var goals: GoalsData?
    @Environment(AppState.self) private var state
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var confirm = false

    var body: some View {
        if goals?.close?.status == .closed || (goals != nil && goals?.cycle == nil) {
            Card {
                Text("上一阶段已经结案").font(Typo.serif(19))
                Text("开始新的 42 天阶段后，再为它设定不超过 5 个目标。").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).padding(.top, 4)
                if let error { Text(error).font(Typo.sans(12)).foregroundStyle(Tone.rose.color).padding(.top, 8) }
                Button(busy ? "创建中…" : "开始新阶段") { confirm = true }.disabled(busy).padding(.top, 12)
            }
            .padding(.top, 24)
            .alert("从今天开始新阶段？", isPresented: $confirm) {
                Button("开始") { start() }
                Button("取消", role: .cancel) {}
            } message: { Text("周期长度由 personal-review 决定（42 天）。") }
        }
    }

    private func start() {
        busy = true
        error = nil
        Task {
            defer { busy = false }
            do {
                _ = try await state.review.stage(false, { try await $0.createCycle() }, demo: { StageResult(status: "dry-run") })
            } catch { self.error = ReviewDesk.message(error) }
        }
    }
}

/// Shown under the goals while the cycle still has room.
struct AddGoalForm: View {
    var cycle: GoalsData.Cycle
    @Environment(AppState.self) private var state
    @ViewState private var draft: GoalDraft
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var added: String?

    init(cycle: GoalsData.Cycle) {
        self.cycle = cycle
        _draft = ViewState(initialValue: GoalDraft(domain: Stage.domains[4], deadline: ReviewText.dayKey(cycle.endsAt)))
    }

    var body: some View {
        Card {
            HStack {
                Text("新增目标").font(Typo.sans(13, .semibold))
                Spacer()
                Picker("", selection: $draft.domain) { ForEach(Stage.domains, id: \.self) { Text($0).tag($0) } }
                    .pickerStyle(.segmented).labelsHidden().frame(width: 280)
            }
            VStack(spacing: 8) {
                input("目标", $draft.goal, "这 42 天要做成什么")
                input("进度", $draft.progress, "现在在哪里")
                input("截止", $draft.deadline, "YYYY-MM-DD")
                input("成功标准", $draft.successCriteria, "怎样算成了，最好能被别人验证")
                input("中止信号", $draft.stopSignal, "出现什么就停下")
            }
            .padding(.top, 12)
            if let error { Text(error).font(Typo.sans(12)).foregroundStyle(Tone.rose.color).padding(.top, 8) }
            if let added { DoneBanner(text: added).padding(.top, 8) }
            HStack {
                Spacer()
                Button(busy ? "写入中…" : "添加并发布到 Memos") { add() }.disabled(busy || !draft.isComplete)
            }
            .padding(.top, 10)
        }
    }

    private func input(_ label: String, _ text: Binding<String>, _ placeholder: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(label).font(Typo.sans(12)).foregroundStyle(Palette.ink2).frame(width: 60, alignment: .leading)
            TextField(placeholder, text: text, axis: .vertical).textFieldStyle(.roundedBorder).lineLimit(1...3)
        }
    }

    private func add() {
        busy = true
        error = nil
        added = nil
        let id = cycle.id, d = draft
        Task {
            defer { busy = false }
            do {
                _ = try await state.review.stage(false, { try await $0.addGoal(cycle: id, d, dryRun: false) }, demo: { StageResult(status: "dry-run") })
                added = "已添加「\(d.goal)」"
                draft = GoalDraft(domain: d.domain, deadline: d.deadline)
            } catch { self.error = ReviewDesk.message(error) }
        }
    }
}
