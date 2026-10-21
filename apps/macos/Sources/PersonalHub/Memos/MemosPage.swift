import AppKit
import HubKit
import SwiftUI

/// Native Memos: compose, filter by tag or text, edit in place, archive.
struct MemosPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let store = state.memos
        HStack(alignment: .top, spacing: 20) {
            HubScroll {
                MemosSidebar().padding(.bottom, 8)
            }
            .frame(width: 292)
            MemosTimeline()
        }
        .task(id: state.hub.mode) { await store.reload() }
    }
}

enum MemoVisibility {
    static let all = ["PRIVATE", "PROTECTED", "PUBLIC"]

    static func label(_ v: String?) -> String {
        switch v {
        case "PUBLIC": "公开"
        case "PROTECTED": "登录可见"
        default: "私密"
        }
    }

    static func symbol(_ v: String?) -> String {
        switch v {
        case "PUBLIC": "globe"
        case "PROTECTED": "person.2"
        default: "lock"
        }
    }
}

// MARK: - Sidebar

private struct MemosSidebar: View {
    @Environment(AppState.self) private var state
    @ViewState private var draft = ""
    @ViewState private var visibility = "PRIVATE"
    @ViewState private var busy = false
    @ViewState private var error: String?

    var body: some View {
        let store = state.memos
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                MarkdownEditor(text: $draft, size: 13, inset: NSSize(width: 12, height: 10))
                    .frame(height: 132)
                    .overlay(alignment: .topLeading) {
                        if draft.isEmpty {
                            Text("现在的想法是…").font(Typo.sans(13)).foregroundStyle(Palette.ink4)
                                .padding(.leading, 17).padding(.top, 10).allowsHitTesting(false)
                        }
                    }
                    .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
                HStack(spacing: 8) {
                    VisibilityMenu(value: $visibility)
                    Spacer()
                    Button(action: post) {
                        HStack(spacing: 6) {
                            Text(busy ? "发布中…" : "发布")
                            Text("⌘↩").font(Typo.sans(11)).opacity(0.6)
                        }
                    }
                    .buttonStyle(.hubPrimary)
                    .keyboardShortcut(.return, modifiers: .command)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || busy)
                }
                if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color) }
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))

            SectionTitle("标签")
            Flow(spacing: 6) {
                tagChip(nil, "全部")
                ForEach(store.tags.prefix(24), id: \.name) { t in tagChip(t.name, "#\(t.name)" + (t.count.map { " · \($0)" } ?? "")) }
            }

            SectionTitle("近 12 周")
            MemoActivity(dates: store.items.compactMap(\.createdAt), now: state.agenda.now)
            Text(store.next == nil ? "按全部 \(store.items.count) 条统计" : "按已加载的 \(store.items.count) 条统计")
                .font(Typo.sans(11)).foregroundStyle(Palette.ink4).padding(.top, 6)

            Button { if let u = URL(string: state.memosURL) { NSWorkspace.shared.open(u) } } label: {
                Text("在浏览器中打开 Memos ↗").font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            }
            .buttonStyle(.plain).padding(.top, 18)
        }
    }

    private func tagChip(_ tag: String?, _ label: String) -> some View {
        let on = state.memos.tag == tag
        return Button { Task { await state.memos.select(tag: tag) } } label: {
            Text(label).font(Typo.sans(11.5, on ? .semibold : .regular)).lineLimit(1)
                .foregroundStyle(on ? Color.white : Palette.ink2)
                .padding(.horizontal, 10).padding(.vertical, 3.5)
                .background(Capsule().fill(on ? Palette.ink : Palette.sunk))
                .overlay(Capsule().strokeBorder(on ? .clear : Palette.line2))
                .fixedSize()
        }
        .buttonStyle(.plain)
    }

    private func post() {
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty, !busy else { return }
        busy = true
        error = nil
        Task {
            do {
                try await state.memos.create(content, visibility: visibility)
                draft = ""
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}

private struct VisibilityMenu: View {
    @Binding var value: String

    var body: some View {
        Menu {
            ForEach(MemoVisibility.all, id: \.self) { v in
                Button { value = v } label: { Label(MemoVisibility.label(v), systemImage: MemoVisibility.symbol(v)) }
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: MemoVisibility.symbol(value)).font(.system(size: 10, weight: .semibold))
                Text(MemoVisibility.label(value))
                Image(systemName: "chevron.down").font(.system(size: 8, weight: .bold)).opacity(0.6)
            }
            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink2)
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(Capsule().fill(Palette.sunk))
            .overlay(Capsule().strokeBorder(Palette.line2))
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
    }
}

/// Twelve weeks of memo counts, Monday-first columns ending this week.
private struct MemoActivity: View {
    var dates: [Date]
    var now: Date

    var body: some View {
        var cal = Calendar.hub
        cal.firstWeekday = 2
        let thisWeek = cal.dateInterval(of: .weekOfYear, for: now)!.start
        let start = cal.date(byAdding: .day, value: -77, to: thisWeek)!
        var counts: [Int: Int] = [:]
        for d in dates {
            let n = cal.dateComponents([.day], from: start, to: cal.startOfDay(for: d)).day ?? -1
            if (0..<84).contains(n) { counts[n, default: 0] += 1 }
        }
        let today = cal.dateComponents([.day], from: start, to: cal.startOfDay(for: now)).day ?? 83
        return HStack(spacing: 3) {
            ForEach(0..<12, id: \.self) { w in
                VStack(spacing: 3) {
                    ForEach(0..<7, id: \.self) { d in
                        let n = w * 7 + d, c = counts[n] ?? 0
                        RoundedRectangle(cornerRadius: 3)
                            .fill(n > today ? Color.clear : Palette.heat[min(c == 0 ? 0 : c + 1, 5)])
                            .overlay(RoundedRectangle(cornerRadius: 3).strokeBorder(n > today ? Palette.line2 : .clear))
                            .frame(width: 17, height: 17)
                            .help("\(HubFormat.md(cal.date(byAdding: .day, value: n, to: start)!)) · \(c) 条")
                    }
                }
            }
        }
    }
}

// MARK: - Timeline

private struct MemosTimeline: View {
    @Environment(AppState.self) private var state
    @ViewState private var query = ""

    var body: some View {
        let store = state.memos
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").font(.system(size: 11.5)).foregroundStyle(Palette.ink3)
                TextField("搜索 Memo…", text: $query).textFieldStyle(.plain).font(Typo.sans(13))
                    .onSubmit { search() }
                if !query.isEmpty {
                    Button { query = ""; search() } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Palette.ink4) }.buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12).frame(height: 36)
            .background(RoundedRectangle(cornerRadius: 10).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.line))
            .task(id: query) {
                try? await Task.sleep(for: .milliseconds(350))
                if !Task.isCancelled, query != store.query { search() }
            }

            if let note = note(store) {
                Text(note).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }

            if store.items.isEmpty && (store.phase == .idle || store.phase == .loading) {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, minHeight: 200)
            } else {
                if store.items.isEmpty {
                    Text(store.tag != nil || !store.query.isEmpty ? "没有符合条件的 Memo" : "还没有 Memo")
                        .font(Typo.sans(13)).foregroundStyle(Palette.ink3).frame(maxWidth: .infinity, minHeight: 200)
                } else {
                    HubScroll {
                        LazyVStack(alignment: .leading, spacing: 10) {
                            ForEach(store.items) { MemoCard(memo: $0) }
                            if store.next != nil {
                                ProgressView().controlSize(.small).frame(maxWidth: .infinity).padding(.vertical, 12)
                                    .onAppear { Task { await store.loadMore() } }
                            }
                        }
                        .padding(.bottom, 12).padding(.trailing, 10)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func search() {
        state.memos.query = query
        Task { await state.memos.reload() }
    }

    private func note(_ store: MemosStore) -> String? {
        var parts: [String] = []
        if let tag = store.tag { parts.append("#\(tag)") }
        if !store.query.isEmpty { parts.append("「\(store.query)」") }
        let filter = parts.isEmpty ? nil : "筛选 " + parts.joined(separator: " ") + " · \(store.items.count) 条"
        let source: String? = switch store.source {
        case .recent: "hub 还没提供分页接口，暂只显示最近 \(state.hub.data.memos?.data?.recent?.count ?? 0) 条"
        case .sample: "示例数据，不会写入 Memos"
        case .hub: nil
        }
        var failure: String?
        if case .failed(let m) = store.phase { failure = m }
        let out = [filter, source, failure].compactMap { $0 }
        return out.isEmpty ? nil : out.joined(separator: " · ")
    }
}

private struct MemoCard: View {
    var memo: MemosData.Memo
    @Environment(AppState.self) private var state
    @ViewState private var editing = false
    @ViewState private var draft = ""
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var confirmArchive = false
    @ViewState private var expanded = false
    @ViewState private var tall = false

    private static let collapsed: CGFloat = 280

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if editing {
                MarkdownEditor(text: $draft, size: 13, inset: NSSize(width: 12, height: 10))
                    .frame(height: min(420, max(140, CGFloat(draft.components(separatedBy: "\n").count) * 22 + 40)))
                    .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
                HStack(spacing: 8) {
                    if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).lineLimit(2) }
                    Spacer()
                    Button("取消") { editing = false; error = nil }.buttonStyle(.hubSecondary).keyboardShortcut(.cancelAction)
                    Button(busy ? "保存中…" : "保存") { save() }.buttonStyle(.hubPrimary)
                        .keyboardShortcut(.return, modifiers: .command)
                        .disabled(busy || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            } else {
                MemoMarkdown(content: memo.content)
                    .frame(maxHeight: expanded ? nil : Self.collapsed, alignment: .top)
                    .clipped()
                    .overlay(alignment: .bottom) {
                        if tall && !expanded {
                            LinearGradient(colors: [Palette.card.opacity(0), Palette.card], startPoint: .top, endPoint: .bottom).frame(height: 48)
                        }
                    }
                    .background(
                        MemoMarkdown(content: memo.content).fixedSize(horizontal: false, vertical: true).hidden()
                            .onGeometryChange(for: Bool.self) { $0.size.height > Self.collapsed + 20 } action: { tall = $0 }
                    )
                if tall {
                    Button(expanded ? "收起" : "展开全文") { withAnimation(Motion.spring) { expanded.toggle() } }
                        .buttonStyle(.plain).font(Typo.sans(12)).foregroundStyle(Tone.clay.color)
                }
                if let a = memo.attachments, !a.isEmpty {
                    Chip(text: "\(a.count) 个附件", systemImage: "paperclip")
                }
                if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color) }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(editing ? Tone.clay.color.opacity(0.5) : Palette.line))
        .confirmationDialog("归档这条 Memo？", isPresented: $confirmArchive) {
            Button("归档", role: .destructive) { archive() }
        } message: {
            Text("归档后从时间线移除，可以在 Memos 的归档里恢复。")
        }
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text(MemoCard.when(memo.createdAt, now: state.agenda.now)).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit()
            if let u = memo.updatedAt, let c = memo.createdAt, u.timeIntervalSince(c) > 60 {
                Text("已编辑").font(Typo.sans(11)).foregroundStyle(Palette.ink4)
            }
            HStack(spacing: 4) {
                Image(systemName: MemoVisibility.symbol(memo.visibility)).font(.system(size: 9, weight: .semibold))
                Text(MemoVisibility.label(memo.visibility))
            }
            .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
            .padding(.horizontal, 7).padding(.vertical, 1.5)
            .background(Capsule().fill(Palette.sunk))
            if memo.pinned == true {
                Image(systemName: "pin.fill").font(.system(size: 10)).foregroundStyle(Tone.clay.color).help("已置顶")
            }
            Spacer()
            if !editing { menu }
        }
    }

    private var menu: some View {
        Menu {
            Button { draft = memo.content; error = nil; editing = true } label: { Label("编辑", systemImage: "pencil") }
            Button { change(pinned: !(memo.pinned ?? false)) } label: {
                Label(memo.pinned == true ? "取消置顶" : "置顶", systemImage: memo.pinned == true ? "pin.slash" : "pin")
            }
            Menu("可见范围") {
                ForEach(MemoVisibility.all, id: \.self) { v in
                    Button { change(visibility: v) } label: {
                        Label(MemoVisibility.label(v), systemImage: v == (memo.visibility ?? "PRIVATE") ? "checkmark" : MemoVisibility.symbol(v))
                    }
                }
            }
            Button { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(memo.content, forType: .string) } label: {
                Label("拷贝正文", systemImage: "doc.on.doc")
            }
            if let url = link {
                Button { NSWorkspace.shared.open(url) } label: { Label("在 Memos 中打开", systemImage: "arrow.up.right.square") }
            }
            Divider()
            Button(role: .destructive) { confirmArchive = true } label: { Label("归档", systemImage: "archivebox") }
        } label: {
            Image(systemName: "ellipsis").font(.system(size: 12, weight: .semibold)).foregroundStyle(Palette.ink3)
                .frame(width: 26, height: 20).contentShape(Rectangle())
        }
        .menuStyle(.button).buttonStyle(.plain).menuIndicator(.hidden).fixedSize()
    }

    private var link: URL? {
        if let u = memo.url.flatMap(URL.init(string:)) { return u }
        let base = state.memosURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return URL(string: base + "/" + (memo.id.hasPrefix("memos/") ? memo.id : "memos/" + memo.id))
    }

    static func when(_ date: Date?, now: Date) -> String {
        guard let date else { return "" }
        let cal = Calendar.hub
        if cal.isDate(date, inSameDayAs: now) { return "今天 " + HubFormat.clock(date) }
        if let y = cal.date(byAdding: .day, value: -1, to: now), cal.isDate(date, inSameDayAs: y) { return "昨天 " + HubFormat.clock(date) }
        let sameYear = cal.isDate(date, equalTo: now, toGranularity: .year)
        return (sameYear ? HubFormat.md(date) : HubFormat.ymd(date)) + " " + HubFormat.clock(date)
    }

    private func save() {
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !content.isEmpty else { return }
        if content == memo.content { editing = false; return }
        run { try await state.memos.update(memo, content: content) } done: { editing = false }
    }

    private func change(pinned: Bool? = nil, visibility: String? = nil) {
        run { try await state.memos.update(memo, visibility: visibility, pinned: pinned) }
    }

    private func archive() {
        run { try await state.memos.archive(memo) }
    }

    private func run(_ work: @escaping () async throws -> Void, done: @escaping () -> Void = {}) {
        busy = true
        error = nil
        Task {
            do {
                try await work()
                done()
            } catch {
                self.error = error.localizedDescription
            }
            busy = false
        }
    }
}

// MARK: - Rendering

/// Read-only Markdown for a memo: headings, lists, checkboxes, quotes, code blocks; `#tags` tinted.
struct MemoMarkdown: View {
    var content: String

    enum Block: Equatable {
        case heading(Int, String), bullet(String), check(Bool, String), quote(String), code(String), paragraph(String), rule
    }

    var body: some View {
        let blocks = Self.blocks(content)
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { i, b in
                switch b {
                case .heading(let level, let text):
                    Text(Self.inline(text)).font(level == 1 ? Typo.serif(19) : level == 2 ? Typo.serif(16.5) : Typo.sans(13.5, .semibold))
                        .padding(.top, i == 0 ? 0 : 6)
                case .bullet(let text):
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("•").foregroundStyle(Tone.clay.color)
                        Text(Self.inline(text)).lineSpacing(4)
                    }
                    .font(Typo.sans(13))
                case .check(let done, let text):
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: done ? "checkmark.square.fill" : "square").font(.system(size: 12))
                            .foregroundStyle(done ? Tone.olive.color : Palette.ink3)
                        Text(Self.inline(text)).strikethrough(done, color: Palette.ink4).foregroundStyle(done ? Palette.ink3 : Palette.ink).lineSpacing(4)
                    }
                    .font(Typo.sans(13))
                case .quote(let text):
                    HStack(spacing: 10) {
                        RoundedRectangle(cornerRadius: 1.5).fill(Tone.clay.color.opacity(0.55)).frame(width: 3)
                        Text(Self.inline(text)).font(Typo.sans(13)).foregroundStyle(Palette.ink2).lineSpacing(4)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                case .code(let text):
                    Text(text).font(.system(size: 12, design: .monospaced)).foregroundStyle(Palette.ink)
                        .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
                case .paragraph(let text):
                    Text(Self.inline(text)).font(Typo.sans(13)).lineSpacing(5)
                case .rule:
                    Rectangle().fill(Palette.line2).frame(height: 1).padding(.vertical, 4)
                }
            }
        }
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private static let checks: [(String, Bool)] = [("- [ ] ", false), ("- [x] ", true), ("- [X] ", true), ("* [ ] ", false), ("* [x] ", true)]

    static func blocks(_ content: String) -> [Block] {
        var out: [Block] = [], paragraph: [String] = [], code: [String]?
        func flush() {
            if !paragraph.isEmpty { out.append(.paragraph(paragraph.joined(separator: "\n"))); paragraph = [] }
        }
        for raw in content.components(separatedBy: .newlines) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.hasPrefix("```") {
                if let c = code { out.append(.code(c.joined(separator: "\n"))); code = nil } else { flush(); code = [] }
                continue
            }
            if code != nil { code!.append(raw); continue }
            if line.isEmpty { flush(); continue }
            let hashes = line.prefix { $0 == "#" }.count
            if (1...6).contains(hashes), line.dropFirst(hashes).first == " " {
                flush(); out.append(.heading(hashes, line.dropFirst(hashes + 1).trimmingCharacters(in: .whitespaces))); continue
            }
            if line.count >= 3, line.allSatisfy({ $0 == "-" || $0 == "*" || $0 == "_" }) { flush(); out.append(.rule); continue }
            if let (marker, done) = checks.first(where: { line.hasPrefix($0.0) }) {
                flush(); out.append(.check(done, String(line.dropFirst(marker.count)))); continue
            }
            if line.hasPrefix("- ") || line.hasPrefix("* ") || line.hasPrefix("+ ") { flush(); out.append(.bullet(String(line.dropFirst(2)))); continue }
            if let r = line.range(of: #"^\d{1,3}[.)]\s+"#, options: .regularExpression) { flush(); out.append(.bullet(String(line[r.upperBound...]))); continue }
            if line.hasPrefix(">") {
                flush()
                let text = line.drop { $0 == ">" }.trimmingCharacters(in: .whitespaces)
                if case .quote(let prev)? = out.last { out[out.count - 1] = .quote(prev + "\n" + text) } else { out.append(.quote(text)) }
                continue
            }
            paragraph.append(line)
        }
        if let code { out.append(.code(code.joined(separator: "\n"))) }
        flush()
        return out
    }

    static func inline(_ text: String) -> AttributedString {
        var a = (try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
        let plain = String(a.characters)
        let re = try! NSRegularExpression(pattern: #"(?<![\w/])#[^\s#]+"#)
        for m in re.matches(in: plain, range: NSRange(plain.startIndex..., in: plain)) {
            guard let r = Range(m.range, in: plain) else { continue }
            let lo = a.characters.index(a.startIndex, offsetBy: plain.distance(from: plain.startIndex, to: r.lowerBound))
            let hi = a.characters.index(lo, offsetBy: plain.distance(from: r.lowerBound, to: r.upperBound))
            a[lo..<hi].foregroundColor = Tone.sky.color
        }
        for run in a.runs where run.link != nil { a[run.range].foregroundColor = Tone.sky.color }
        return a
    }
}
