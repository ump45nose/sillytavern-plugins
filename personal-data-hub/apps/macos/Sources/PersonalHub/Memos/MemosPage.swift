import AppKit
import HubKit
import SwiftUI

/// Native Memos: compose, filter by tag or text, edit in place, archive.
struct MemosPage: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let store = state.memos
        HStack(alignment: .top, spacing: 24) {
            HubScroll {
                MemosSidebar().padding(.bottom, 8)
            }
            .scrollIndicators(.never)
            .frame(width: 284)
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

    @ViewState private var allTags = false

    var body: some View {
        let store = state.memos
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(alignment: .firstTextBaseline) {
                    Text("记下此刻").font(Typo.serif(18))
                    Spacer()
                    Text("随时 " + HotKeyCenter.shared.display(.quickMemo)).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
                }
                MarkdownEditor(text: $draft, size: 13, inset: NSSize(width: 12, height: 10))
                    .frame(height: 120)
                    .overlay(alignment: .topLeading) {
                        if draft.isEmpty {
                            Text("现在的想法是…  可用 #标签").font(Typo.sans(13)).foregroundStyle(Palette.ink4)
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
            .padding(16)
            .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))

            MemoActivity(dates: store.items.compactMap(\.createdAt), now: state.agenda.now, partial: store.next != nil)
                .padding(16)
                .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(Palette.line))

            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Label11("标签")
                    Spacer()
                    if store.tag != nil {
                        Button("清除筛选") { Task { await store.select(tag: nil) } }.buttonStyle(.plain)
                            .font(Typo.sans(11)).foregroundStyle(Tone.clay.color)
                    }
                }
                .padding(.bottom, 4)
                let tags = Array(store.tags.prefix(allTags ? 60 : 8))
                ForEach(tags, id: \.name) { t in tagRow(t.name, count: t.count) }
                if store.tags.count > 8 {
                    Button(allTags ? "收起" : "全部 \(store.tags.count) 个标签") { withAnimation(Motion.spring) { allTags.toggle() } }
                        .buttonStyle(.plain).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).padding(.top, 4).padding(.leading, 8)
                }
                if store.tags.isEmpty { Text("还没有标签").font(Typo.sans(12)).foregroundStyle(Palette.ink3) }
            }
            .padding(.horizontal, 8)

            Button { if let u = URL(string: state.memosURL) { NSWorkspace.shared.open(u) } } label: {
                Text("在浏览器中打开 Memos ↗").font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            }
            .buttonStyle(.plain).padding(.leading, 16)
        }
    }

    private func tagRow(_ tag: String, count: Int?) -> some View {
        let on = state.memos.tag == tag
        return Button { Task { await state.memos.select(tag: on ? nil : tag) } } label: {
            HStack(spacing: 6) {
                Text("#").font(Typo.sans(12.5, .semibold)).foregroundStyle(on ? Tone.clay.color : Palette.ink4)
                Text(tag).font(Typo.sans(12.5, on ? .semibold : .regular)).foregroundStyle(on ? Palette.ink : Palette.ink2).lineLimit(1)
                Spacer(minLength: 4)
                if let count { Text("\(count)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit() }
            }
            .padding(.horizontal, 8).frame(height: 28)
            .background(RoundedRectangle(cornerRadius: 8).fill(on ? Palette.card : .clear))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(on ? Palette.line : .clear))
            .contentShape(Rectangle())
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

/// This week, the last 30 days and the current streak, over twelve weeks of counts (Monday-first columns).
private struct MemoActivity: View {
    var dates: [Date]
    var now: Date
    var partial: Bool

    var body: some View {
        let cal = Calendar.hub
        let today = cal.startOfDay(for: now)
        let thisWeek = cal.dateInterval(of: .weekOfYear, for: now)!.start
        let start = cal.date(byAdding: .day, value: -77, to: thisWeek)!
        let days = Dictionary(grouping: dates) { cal.startOfDay(for: $0) }.mapValues(\.count)
        let week = dates.filter { $0 >= thisWeek }.count
        let month = dates.filter { $0 >= cal.date(byAdding: .day, value: -29, to: today)! }.count
        let streak = Self.streak(days, today: today, calendar: cal)
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 0) {
                stat("\(week)", "本周")
                stat("\(month)", "近 30 天")
                stat("\(streak)", "连续天数")
            }
            GeometryReader { g in
                let side = (g.size.width - 11 * 3) / 12
                HStack(spacing: 3) {
                    ForEach(0..<12, id: \.self) { w in
                        VStack(spacing: 3) {
                            ForEach(0..<7, id: \.self) { d in
                                let day = cal.date(byAdding: .day, value: w * 7 + d, to: start)!
                                let c = days[day] ?? 0
                                RoundedRectangle(cornerRadius: 3.5)
                                    .fill(day > today ? Color.clear : Palette.heat[min(c, 5)])
                                    .overlay(RoundedRectangle(cornerRadius: 3.5).strokeBorder(cal.isDate(day, inSameDayAs: today) ? Palette.ink3 : .clear))
                                    .frame(width: side, height: side)
                                    .help("\(HubFormat.md(day)) · \(c) 条")
                            }
                        }
                    }
                }
            }
            .aspectRatio(12 / 7, contentMode: .fit)
            HStack(spacing: 4) {
                Text(partial ? "按已加载的 \(dates.count) 条" : "近 12 周 · 共 \(dates.count) 条").font(Typo.sans(10.5)).foregroundStyle(Palette.ink4)
                Spacer()
                Text("少").font(Typo.sans(10)).foregroundStyle(Palette.ink4)
                ForEach(0..<5, id: \.self) { RoundedRectangle(cornerRadius: 2).fill(Palette.heat[$0 + ($0 > 0 ? 1 : 0)]).frame(width: 9, height: 9) }
                Text("多").font(Typo.sans(10)).foregroundStyle(Palette.ink4)
            }
        }
    }

    private func stat(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(value).font(Typo.serif(24)).monospacedDigit()
            Text(label).font(Typo.sans(11)).foregroundStyle(Palette.ink3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Days in a row with at least one memo, ending today (or yesterday, before today's first memo).
    static func streak(_ days: [Date: Int], today: Date, calendar: Calendar) -> Int {
        var day = days[today] == nil ? calendar.date(byAdding: .day, value: -1, to: today)! : today, n = 0
        while days[day] != nil { n += 1; day = calendar.date(byAdding: .day, value: -1, to: day)! }
        return n
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
                    let filtered = store.tag != nil || !store.query.isEmpty
                    let pinned = filtered ? [] : store.items.filter { $0.pinned == true }
                    let rest = store.items.filter { filtered || $0.pinned != true }
                    HubScroll {
                        LazyVStack(alignment: .leading, spacing: 8, pinnedViews: [.sectionHeaders]) {
                            if !pinned.isEmpty {
                                Section { ForEach(pinned) { MemoCard(memo: $0, dated: true) } } header: { dayHeader("置顶", nil, pinned.count) }
                            }
                            ForEach(Self.days(rest), id: \.0) { day, memos in
                                let (title, caption) = Self.dayTitle(day, now: state.agenda.now)
                                Section { ForEach(memos) { MemoCard(memo: $0) } } header: { dayHeader(title, caption, memos.count) }
                            }
                            if store.next != nil {
                                ProgressView().controlSize(.small).frame(maxWidth: .infinity).padding(.vertical, 12)
                                    .onAppear { Task { await store.loadMore() } }
                            }
                        }
                        .padding(.bottom, 12).padding(.trailing, 10)
                    }
                    .scrollIndicators(.never)
                }
            }
        }
        .frame(maxWidth: 880, maxHeight: .infinity, alignment: .topLeading)
    }

    private func dayHeader(_ title: String, _ caption: String?, _ count: Int) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(title).font(Typo.serif(17))
            if let caption { Text(caption).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3) }
            Text("\(count) 条").font(Typo.sans(11.5)).foregroundStyle(Palette.ink4)
            Rectangle().fill(Palette.line).frame(height: 1).alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] }
        }
        .padding(.leading, 56).padding(.top, 14).padding(.bottom, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.bg)
    }

    /// Newest day first; memos without a date go last.
    static func days(_ memos: [MemosData.Memo]) -> [(Date, [MemosData.Memo])] {
        let cal = Calendar.hub
        var order: [Date] = [], groups: [Date: [MemosData.Memo]] = [:]
        for m in memos {
            let day = m.createdAt.map { cal.startOfDay(for: $0) } ?? .distantPast
            if groups[day] == nil { order.append(day) }
            groups[day, default: []].append(m)
        }
        return order.sorted(by: >).map { ($0, groups[$0]!) }
    }

    /// "今天" over "10 月 21 日 周三"; older days lead with the date and keep the weekday as the caption.
    static func dayTitle(_ day: Date, now: Date) -> (String, String?) {
        if day == .distantPast { return ("没有日期", nil) }
        let rel = Agenda.relativeDay(day, now: now)
        if rel == "今天" || rel == "昨天" { return (rel, Agenda.longDay(day)) }
        let c = Calendar.hub.dateComponents([.year, .month, .day], from: day)
        let sameYear = Calendar.hub.isDate(day, equalTo: now, toGranularity: .year)
        return ((sameYear ? "" : "\(c.year!) 年 ") + "\(c.month!) 月 \(c.day!) 日", Agenda.weekdayName(day))
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
    /// Pinned memos sit outside their day, so they show the date too.
    var dated = false
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
        HStack(alignment: .top, spacing: 14) {
            Text(dated ? MemoCard.when(memo.createdAt, now: state.agenda.now) : memo.createdAt.map(HubFormat.clock) ?? "")
                .font(Typo.sans(11.5)).foregroundStyle(Palette.ink3).monospacedDigit()
                .frame(width: 42, alignment: .trailing).lineLimit(2).multilineTextAlignment(.trailing)
                .padding(.top, 17)
            card
        }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 10) {
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
                footer
                if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color) }
            }
        }
        .padding(.horizontal, 18).padding(.vertical, 14)
        .padding(.trailing, editing ? 0 : 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(editing ? Tone.clay.color.opacity(0.5) : Palette.line2))
        .overlay(alignment: .leading) {
            if memo.pinned == true { Capsule().fill(Tone.clay.color).frame(width: 3).padding(.vertical, 14) }
        }
        .overlay(alignment: .topTrailing) { if !editing { menu.padding(.top, 10).padding(.trailing, 8) } }
        .shadow(color: .black.opacity(0.025), radius: 3, y: 1)
        .confirmationDialog("归档这条 Memo？", isPresented: $confirmArchive) {
            Button("归档", role: .destructive) { archive() }
        } message: {
            Text("归档后从时间线移除，可以在 Memos 的归档里恢复。")
        }
    }

    /// Only what differs from the default: shared visibility, edits, attachments.
    @ViewBuilder private var footer: some View {
        let shared = (memo.visibility ?? "PRIVATE") != "PRIVATE"
        let edited = memo.updatedAt.flatMap { u in memo.createdAt.map { u.timeIntervalSince($0) > 60 } } ?? false
        let files = memo.attachments?.count ?? 0
        if shared || edited || files > 0 {
            HStack(spacing: 10) {
                if shared {
                    Label(MemoVisibility.label(memo.visibility), systemImage: MemoVisibility.symbol(memo.visibility))
                }
                if files > 0 { Label("\(files) 个附件", systemImage: "paperclip") }
                if edited { Text("已编辑") }
            }
            .labelStyle(TightLabel())
            .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
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

private struct TightLabel: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 4) { configuration.icon.font(.system(size: 9.5, weight: .semibold)); configuration.title }
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
