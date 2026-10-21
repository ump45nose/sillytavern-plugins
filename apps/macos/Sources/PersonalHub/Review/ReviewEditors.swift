import AppKit
import HubKit
import SwiftUI

/// Daily review: the frozen template as fields; one action checks with personal-review and archives.
struct DailyEditor: View {
    var session: ReviewSession
    @Environment(AppState.self) private var state
    @ViewState private var form: ReviewForm
    @ViewState private var serverIssue: ReviewForm.Issue?
    @ViewState private var busy = false
    @ViewState private var done: String?

    init(session: ReviewSession) {
        self.session = session
        let template = session.material?.template ?? ReviewSample.dailyTemplate(session.label)
        var form = ReviewForm(template: template)
        if let saved = AppState.shared.review.drafts.forms[session.id], saved.header == form.header { form.values = saved.values }
        _form = ViewState(initialValue: form)
    }

    private var auto: Set<String> { Set(session.rules?.autoFields ?? ["健康", "财务"]) }
    private var issues: [ReviewForm.Issue] { form.issues(rules: session.rules) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SessionHeader(session: session, action: SessionAction(
                title: busy ? "归档中…" : "确认归档", enabled: !busy && issues.isEmpty,
                note: issues.isEmpty ? "健康和财务确认时自动填入" : "还有 \(issues.count) 项待填写或修正", run: commit))
                .padding(.bottom, 16)
            HStack(alignment: .top, spacing: 20) {
                MaterialPanel(session: session).frame(maxWidth: .infinity)
                Group {
                    switch session.status {
                    case .finalized: FinalView(session: session, done: done)
                    case .expired: ExpiredNote(session: session)
                    case .open: fields
                    }
                }
                .frame(width: 460)
            }
        }
        .padding(.horizontal, 28).padding(.top, 30).padding(.bottom, 20)
        .onChange(of: form) { _, f in state.review.setForm(f, for: session.id) }
    }

    private var fields: some View {
        VStack(alignment: .leading, spacing: 0) {
            HubScroll {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(form.labels, id: \.self) { label in field(label) }
                }
                .padding(.bottom, 12)
            }
            .scrollIndicators(.never)
            if let serverIssue, serverIssue.field == nil {
                Text(serverIssue.message).font(Typo.sans(12)).foregroundStyle(Tone.rose.color).padding(.bottom, 8)
            }
            HStack {
                Text(form.isEmpty ? "填写会自动存为本机草稿" : "草稿已存在本机").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
                Spacer()
                Text("填好后 ⌘↩ 确认归档").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }
            .padding(.top, 10)
            .overlay(alignment: .top) { Rectangle().fill(Palette.line2).frame(height: 1) }
        }
    }

    @ViewBuilder private func field(_ label: String) -> some View {
        let binding = Binding(get: { form[label] }, set: { form[label] = $0; if serverIssue?.field == label { serverIssue = nil } })
        let issue = serverIssue?.field == label ? serverIssue : issues.first { $0.field == label && !form[label].isEmpty }
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(label).font(Typo.sans(12.5, .semibold))
                if let hint = Self.hints[label] { Text(hint).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
                Spacer()
                if label == ReviewForm.summaryLabel, let max = session.rules?.summaryMaxChars {
                    let n = ReviewForm.length(form[label])
                    Text("\(n) / \(max)").font(Typo.sans(11)).monospacedDigit().foregroundStyle(n > max ? Tone.rose.color : Palette.ink3)
                }
            }
            if auto.contains(label) {
                Text("确认时由 personal-review 按当天数据填入").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
            } else {
                TextField(Self.placeholders[label] ?? "", text: binding, axis: .vertical)
                    .textFieldStyle(.plain).font(Typo.sans(13)).lineLimit(1...4)
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Palette.card))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(issue == nil ? Palette.line : Tone.rose.color.opacity(0.6)))
                if label == "情绪", let words = session.rules?.emotionWords, !words.isEmpty {
                    Flow(spacing: 5) {
                        ForEach(words, id: \.self) { w in
                            let on = form[label].contains(w)
                            Button { toggle(w, in: label) } label: { Chip(text: w, tone: on ? .clay : nil) }.buttonStyle(.plain)
                        }
                    }
                }
            }
            if let issue { Text(issue.message).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color) }
        }
    }

    private func toggle(_ word: String, in label: String) {
        var words = form[label].split(separator: "、").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        if let i = words.firstIndex(of: word) { words.remove(at: i) } else { words.append(word) }
        form[label] = words.joined(separator: "、")
    }

    /// The preview call is personal-review's validation; finalize runs only when it passes.
    private func commit() {
        busy = true
        serverIssue = nil
        let content = form.content(auto: auto)
        Task {
            defer { busy = false }
            do {
                _ = try await state.review.preview(session, content: content)
            } catch {
                serverIssue = .init(field: ReviewDesk.field(error), message: ReviewDesk.message(error))
                return
            }
            do {
                let already = try await state.review.finalize(session, content: content)
                done = already ? "这篇日报之前已在 Telegram 确认，没有重复写入" : "已归档到 Memos"
            } catch {
                serverIssue = .init(field: nil, message: ReviewDesk.message(error))
            }
        }
    }

    static let hints: [String: String] = [
        ReviewForm.summaryLabel: "一句话，不是事项清单",
        "情绪": "选一个或自己写",
        "未解": "最多两项",
        "明天唯一重点": "只写一件",
        "瞬间": "一个能重现的画面",
    ]

    static let placeholders: [String: String] = [
        ReviewForm.summaryLabel: "今天最值得记住的是…",
        "留痕": "今天留下了什么（可留空）",
        "未解": "还没想清楚的事；多项用 [ ] 分开",
        "明天唯一重点": "明天只做好一件事",
        "瞬间": "看到、听到、站在…某个具体画面",
    ]
}

/// Weekly review: the multi-line template is edited as live-styled Markdown and archived in one step.
struct WeeklyEditor: View {
    var session: ReviewSession
    @Environment(AppState.self) private var state
    @ViewState private var text: String
    @ViewState private var error: String?
    @ViewState private var busy = false
    @ViewState private var done: String?

    private var template: String { session.material?.template ?? ReviewSample.weeklyTemplate(session.label) }

    init(session: ReviewSession) {
        self.session = session
        let template = session.material?.template ?? ReviewSample.weeklyTemplate(session.label)
        _text = ViewState(initialValue: AppState.shared.review.drafts.texts[session.id] ?? template)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SessionHeader(session: session, action: SessionAction(
                title: busy ? "归档中…" : "确认归档", enabled: !busy && text != template,
                note: text == template ? "先在模板上填写" : nil, run: commit))
                .padding(.bottom, 16)
            HStack(alignment: .top, spacing: 20) {
                MaterialPanel(session: session).frame(maxWidth: .infinity)
                Group {
                    if session.status == .finalized {
                        FinalView(session: session, done: done)
                    } else if session.status == .expired {
                        ExpiredNote(session: session)
                    } else {
                        editor
                    }
                }
                .frame(width: 520)
            }
        }
        .padding(.horizontal, 28).padding(.top, 30).padding(.bottom, 20)
        .onChange(of: text) { _, t in state.review.setText(t, for: session.id, template: template) }
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label11("正文 · Markdown 边写边排版，按模板逐项填写")
            MarkdownEditor(text: $text)
                .frame(minHeight: 260)
                .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: Metrics.innerRadius).strokeBorder(Palette.line))
            if let goals = state.review.goals?.goals, !goals.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    Label11("阶段进度和下周行动用 [目标ID] 指明目标，点一下复制")
                    Flow(spacing: 5) {
                        ForEach(goals) { g in
                            Button {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString("[\(g.id)]", forType: .string)
                            } label: { Chip(text: "\(g.domain) · \(g.goal)", tone: StageTone.of(g.domain), systemImage: "doc.on.doc") }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            if let error { Text(error).font(Typo.sans(12)).foregroundStyle(Tone.rose.color) }
            Text(text == template ? "从模板开始写，填写会自动存为本机草稿" : "草稿已存在本机").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
        }
    }

    /// The preview call is personal-review's validation; finalize runs only when it passes.
    private func commit() {
        busy = true
        error = nil
        let content = text
        Task {
            defer { busy = false }
            do {
                _ = try await state.review.preview(session, content: content)
                let already = try await state.review.finalize(session, content: content)
                done = already ? "这篇周报之前已在 Telegram 确认，没有重复写入" : "已归档到 Memos"
            } catch { self.error = ReviewDesk.message(error) }
        }
    }
}

private struct FinalView: View {
    var session: ReviewSession
    var done: String?
    @Environment(AppState.self) private var state

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let done { DoneBanner(text: done) }
            Label11("已归档的终稿")
            MarkdownEditor(text: .constant(session.finalContent ?? "终稿在 Memos 里"), editable: false)
                .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
            if let memo = session.memoName, let url = URL(string: state.memosURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/" + memo) {
                Button("在 Memos 中打开") { NSWorkspace.shared.open(url) }.buttonStyle(.hubSecondary)
            }
        }
    }
}

private struct ExpiredNote: View {
    var session: ReviewSession

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("这次\(session.kind.title)没有在有效期内确认").font(Typo.sans(14, .medium))
            Text("过期的会话不能再归档，personal-review 会保留当时的材料。左边可以回看。").font(Typo.sans(12.5)).foregroundStyle(Palette.ink3).lineSpacing(3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
    }
}
