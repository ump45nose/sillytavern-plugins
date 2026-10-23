import AppKit
import HubKit
import SwiftUI

/// Native Memos: search, views, activity and tags on the left; a fixed composer over the day-grouped timeline.
struct MemosPage: View {
    @Environment(AppState.self) private var state
    @ViewState private var height: CGFloat = 800

    var body: some View {
        let store = state.memos
        HStack(alignment: .top, spacing: 24) {
            HubScroll {
                MemosSidebar().padding(.bottom, 8)
            }
            .scrollIndicators(.never)
            .frame(width: 284)
            VStack(alignment: .leading, spacing: 16) {
                MemoComposer(maxHeight: max(240, height * 0.5))
                MemosTimeline()
            }
            .frame(maxWidth: 880, maxHeight: .infinity, alignment: .topLeading)
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height = $0 }
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
    @ViewState private var query = ""
    @ViewState private var allTags = false
    @FocusState private var searching: Bool

    private static let filters: [(MemosStore.Filter, String)] = [(.all, "全部"), (.pinned, "置顶"), (.attachments, "有附件"), (.archived, "已归档")]

    var body: some View {
        let store = state.memos
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").font(.system(size: 11.5)).foregroundStyle(Palette.ink3)
                    TextField("搜索 Memo…", text: $query).textFieldStyle(.plain).font(Typo.sans(13))
                        .focused($searching)
                        .onSubmit { search() }
                    if query.isEmpty {
                        Kbd("⌘F")
                    } else {
                        Button { query = ""; search() } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(Palette.ink4) }.buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 12).frame(height: 36)
                .background(RoundedRectangle(cornerRadius: 10).fill(Palette.card))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(searching ? Tone.clay.color.opacity(0.5) : Palette.line))
                .background { Button("") { searching = true }.keyboardShortcut("f", modifiers: .command).hidden() }
                .task(id: query) {
                    try? await Task.sleep(for: .milliseconds(350))
                    if !Task.isCancelled, query != store.query { search() }
                }
                Segmented(options: Self.filters,
                          selection: Binding(get: { store.filter }, set: { f in Task { await store.select(filter: f) } }), small: true)
            }

            MemoActivity(dates: store.activity, now: state.agenda.now, partial: store.activityPartial)
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
        .onAppear { query = store.query }
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

    private func search() {
        state.memos.query = query
        Task { await state.memos.reload() }
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

// MARK: - Composer

/// One line until clicked; then a Markdown editor that grows with its text, with a formatting bar.
/// The draft is kept across launches and survives Esc.
struct MemoComposer: View {
    var maxHeight: CGFloat
    @Environment(AppState.self) private var state
    @AppStorage("memos.draft") private var draft = ""
    @AppStorage("memos.visibility") private var visibility = "PRIVATE"
    @ViewState private var open = false
    @ViewState private var textHeight: CGFloat = 0
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var editor = MarkdownController()
    @ViewState private var uploads: MemoUploads

    init(maxHeight: CGFloat, open: Bool = false, draftKey: String = "memos.draft", uploads: MemoUploads? = nil) {
        self.maxHeight = maxHeight
        _open = ViewState(initialValue: open)
        _draft = AppStorage(wrappedValue: "", draftKey)
        _uploads = ViewState(initialValue: uploads ?? MemoUploads())
    }

    private var canSend: Bool {
        !busy && !uploads.uploading && (!draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !uploads.names.isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if open { expanded } else { collapsed }
        }
        .background(RoundedRectangle(cornerRadius: Metrics.cardRadius).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(open ? Tone.clay.color.opacity(0.45) : Palette.line))
        .shadow(color: Color(hex: "#3C280A").opacity(open ? 0.06 : 0.02), radius: open ? 10 : 2, y: open ? 4 : 1)
        .background { Button("") { expand() }.keyboardShortcut("n", modifiers: .command).hidden() }
        .onDrop(of: [.fileURL], isTargeted: nil) { providers in
            for p in providers {
                _ = p.loadObject(ofClass: URL.self) { url, _ in
                    guard let url else { return }
                    DispatchQueue.main.async {
                        expand()
                        uploads.add([url], store: state.memos)
                    }
                }
            }
            return !providers.isEmpty
        }
    }

    private var collapsed: some View {
        let first = draft.split(separator: "\n").first.map(String.init)?.trimmingCharacters(in: .whitespaces)
        return HStack(spacing: 10) {
            Image(systemName: "square.and.pencil").font(.system(size: 13)).foregroundStyle(Palette.ink3)
            if let first, !first.isEmpty {
                Text("草稿").font(Typo.sans(11, .semibold)).foregroundStyle(Tone.clay.color)
                Text(first).font(Typo.sans(13.5)).foregroundStyle(Palette.ink2).lineLimit(1)
            } else {
                Text("记下此刻…  支持 Markdown，# 加标签").font(Typo.sans(13.5)).foregroundStyle(Palette.ink4)
            }
            Spacer(minLength: 8)
            if !uploads.items.isEmpty {
                Label("\(uploads.items.count)", systemImage: "paperclip").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }
            Kbd("⌘N")
            tool("paperclip", help: "附加文件") { expand(); uploads.pick(store: state.memos) }
            tool("number", help: "加标签") { expand(); DispatchQueue.main.async { editor.insert("#") } }
        }
        .padding(.leading, 16).padding(.trailing, 10).frame(height: 48)
        .contentShape(Rectangle())
        .onTapGesture { expand() }
    }

    private var expanded: some View {
        let height = min(max(textHeight, 160), maxHeight)
        return VStack(alignment: .leading, spacing: 0) {
            MarkdownEditor(text: $draft, size: 14, inset: NSSize(width: 14, height: 14), controller: editor,
                           onHeight: { textHeight = $0 }, onEscape: collapse,
                           onFiles: { [uploads, memos = state.memos] in uploads.take($0, store: memos) })
                .frame(height: height)
                .overlay(alignment: .topLeading) {
                    if draft.isEmpty {
                        Text("现在的想法是…  支持 Markdown，# 加标签").font(Typo.sans(14)).foregroundStyle(Palette.ink4)
                            .padding(.leading, 19).padding(.top, 14).allowsHitTesting(false)
                    }
                }
            if !uploads.items.isEmpty {
                Flow(spacing: 8) {
                    ForEach(uploads.items) { item in
                        MemoUploadCard(item: item) { uploads.remove(item, store: state.memos) }
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 12)
            }
            if let error {
                Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).padding(.horizontal, 16).padding(.bottom, 6)
            }
            Rectangle().fill(Palette.line2).frame(height: 1).padding(.horizontal, 12)
            HStack(spacing: 2) {
                tool("bold", help: "粗体") { editor.wrap("**", "**", placeholder: "粗体") }
                tool("italic", help: "斜体") { editor.wrap("*", "*", placeholder: "斜体") }
                Button { editor.toggleLine("## ") } label: {
                    Text("H").font(Typo.serif(14)).foregroundStyle(Palette.ink2).frame(width: 28, height: 26).contentShape(Rectangle())
                }
                .buttonStyle(.plain).help("标题")
                tool("list.bullet", help: "列表") { editor.toggleLine("- ") }
                tool("checklist", help: "待办") { editor.toggleLine("- [ ] ") }
                tool("chevron.left.forwardslash.chevron.right", help: "代码") { editor.wrap("`", "`", placeholder: "代码") }
                tool("link", help: "链接") { editor.wrap("[", "](https://)", placeholder: "链接文字") }
                tool("number", help: "标签") { editor.insert("#") }
                tool("paperclip", help: "附加文件，也可以拖入或粘贴截图") { uploads.pick(store: state.memos) }
                Spacer(minLength: 8)
                VisibilityMenu(value: $visibility)
                Text(draft.isEmpty ? "Esc 收起" : "Esc 收起 · 草稿已保存").font(Typo.sans(11)).foregroundStyle(Palette.ink4)
                    .padding(.horizontal, 8).lineLimit(1).fixedSize()
                Button(action: post) {
                    HStack(spacing: 6) {
                        Text(busy ? "发送中…" : uploads.uploading ? "等上传…" : "发送")
                        Text("⌘↩").font(Typo.sans(11)).opacity(0.6)
                    }
                }
                .buttonStyle(.hubPrimary)
                .keyboardShortcut(.return, modifiers: .command)
                .disabled(!canSend)
            }
            .padding(.leading, 8).padding(.trailing, 10).padding(.vertical, 8)
        }
        .transition(.opacity)
    }

    private func tool(_ symbol: String, help: String, enabled: Bool = true, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 12, weight: .medium))
                .foregroundStyle(enabled ? Palette.ink2 : Palette.ink4.opacity(0.6))
                .frame(width: 28, height: 26).contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(!enabled).help(help)
    }

    private func expand() {
        withAnimation(Motion.spring) { open = true }
        DispatchQueue.main.async { editor.focus() }
    }

    private func collapse() {
        withAnimation(Motion.spring) { open = false }
        error = nil
    }

    private func post() {
        let content = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard canSend else { return }
        busy = true
        error = nil
        Task {
            do {
                try await state.memos.create(content, visibility: visibility, attachments: uploads.names)
                draft = ""
                uploads.clear()
                collapse()
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

// MARK: - Timeline

private struct MemosTimeline: View {
    @Environment(AppState.self) private var state

    var body: some View {
        let store = state.memos
        VStack(alignment: .leading, spacing: 8) {
            if let note = note(store) {
                Text(note).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3)
            }
            if store.items.isEmpty && (store.phase == .idle || store.phase == .loading) {
                ProgressView().controlSize(.small).frame(maxWidth: .infinity, minHeight: 200)
            } else if store.items.isEmpty {
                Text(empty(store)).font(Typo.sans(13)).foregroundStyle(Palette.ink3).frame(maxWidth: .infinity, minHeight: 200)
            } else {
                let pinned = store.filtered ? [] : store.items.filter { $0.pinned == true }
                let rest = store.items.filter { store.filtered || $0.pinned != true }
                HubScroll {
                    LazyVStack(alignment: .leading, spacing: 0, pinnedViews: [.sectionHeaders]) {
                        if !pinned.isEmpty {
                            Section { entries(pinned, dated: true) } header: { dayHeader("置顶", nil, pinned.count) }
                        }
                        ForEach(Self.days(rest), id: \.0) { day, memos in
                            let (title, caption) = Self.dayTitle(day, now: state.agenda.now)
                            Section { entries(memos, dated: store.filter == .pinned) } header: { dayHeader(title, caption, memos.count) }
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
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func entries(_ memos: [MemosData.Memo], dated: Bool) -> some View {
        ForEach(Array(memos.enumerated()), id: \.1.id) { i, memo in
            TimelineEntry(time: memo.createdAt.map(HubFormat.clock) ?? "", first: i == 0, last: i == memos.count - 1,
                          timeWidth: 46, timeSize: 14, ring: Palette.bg, gap: 12) {
                MemoCard(memo: memo, dated: dated)
            }
        }
    }

    private func dayHeader(_ title: String, _ caption: String?, _ count: Int) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(title).font(Typo.serif(17))
            if let caption { Text(caption).font(Typo.sans(11.5)).foregroundStyle(Palette.ink3) }
            Text("\(count) 条").font(Typo.sans(11.5)).foregroundStyle(Palette.ink4)
            Rectangle().fill(Palette.line2).frame(height: 1).alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] }
        }
        .padding(.top, 12).padding(.bottom, 10)
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

    private func empty(_ store: MemosStore) -> String {
        switch store.filter {
        case .archived: store.archiveUnsupported ? "hub 还不能列出已归档的 Memo，可以先在 Memos 里查看" : "没有已归档的 Memo"
        case .pinned: "没有置顶的 Memo"
        case .attachments: "没有带附件的 Memo"
        case .all: store.filtered ? "没有符合条件的 Memo" : "还没有 Memo"
        }
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
    /// Outside their day (pinned), memos show the date in the footer.
    var dated = false
    @Environment(AppState.self) private var state
    @ViewState private var editing = false
    @ViewState private var draft = ""
    @ViewState private var busy = false
    @ViewState private var error: String?
    @ViewState private var confirmArchive = false
    @ViewState private var expanded = false
    @ViewState private var tall = false
    @ViewState private var editHeight: CGFloat = 0

    private static let collapsed: CGFloat = 280
    private var archived: Bool { memo.state == "ARCHIVED" }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if editing {
                MarkdownEditor(text: $draft, size: 13, inset: NSSize(width: 12, height: 10),
                               onHeight: { editHeight = $0 }, onEscape: { editing = false; error = nil })
                    .frame(height: min(420, max(120, editHeight)))
                    .background(RoundedRectangle(cornerRadius: Metrics.innerRadius).fill(Palette.sunk))
                HStack(spacing: 8) {
                    if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color).lineLimit(2) }
                    Spacer()
                    Button("取消") { editing = false; error = nil }.buttonStyle(.hubSecondary)
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
                if let files = memo.attachments, !files.isEmpty { MemoAttachments(memo: memo, files: files) }
                footer
                if let error { Text(error).font(Typo.sans(11.5)).foregroundStyle(Tone.rose.color) }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .padding(.trailing, editing ? 0 : 18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(editing ? Tone.clay.color.opacity(0.5) : Palette.line2))
        .overlay(alignment: .leading) {
            if memo.pinned == true { Capsule().fill(Tone.clay.color).frame(width: 3).padding(.vertical, 12) }
        }
        .overlay(alignment: .topTrailing) { if !editing { menu.padding(.top, 8).padding(.trailing, 6) } }
        .opacity(archived ? 0.75 : 1)
        .padding(.top, -6)
        .confirmationDialog("归档这条 Memo？", isPresented: $confirmArchive) {
            Button("归档", role: .destructive) { archive() }
        } message: {
            Text("归档后从时间线移除，可以在「已归档」里恢复。")
        }
    }

    /// Only what differs from the default: the date outside its day, shared visibility, edits.
    @ViewBuilder private var footer: some View {
        let shared = (memo.visibility ?? "PRIVATE") != "PRIVATE"
        let edited = memo.updatedAt.flatMap { u in memo.createdAt.map { u.timeIntervalSince($0) > 60 } } ?? false
        if dated || shared || edited || archived {
            HStack(spacing: 10) {
                if dated, let at = memo.createdAt { Text(MemoCard.when(at, now: state.agenda.now)) }
                if archived { Label("已归档", systemImage: "archivebox") }
                if shared {
                    Label(MemoVisibility.label(memo.visibility), systemImage: MemoVisibility.symbol(memo.visibility))
                }
                if edited { Text("已编辑") }
            }
            .labelStyle(TightLabel())
            .font(Typo.sans(11)).foregroundStyle(Palette.ink3)
        }
    }

    private var menu: some View {
        Menu {
            if archived {
                Button { restore() } label: { Label("恢复", systemImage: "arrow.uturn.backward") }
            } else {
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
            }
            Button { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(memo.content, forType: .string) } label: {
                Label("拷贝正文", systemImage: "doc.on.doc")
            }
            if let url = link {
                Button { NSWorkspace.shared.open(url) } label: { Label("在 Memos 中打开", systemImage: "arrow.up.right.square") }
            }
            if !archived {
                Divider()
                Button(role: .destructive) { confirmArchive = true } label: { Label("归档", systemImage: "archivebox") }
            }
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

    private func restore() {
        run { try await state.memos.restore(memo) }
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

/// Images as thumbnails through hub's read proxy; other files, and images hub can't serve, as file chips.
private struct MemoAttachments: View {
    var memo: MemosData.Memo
    var files: [MemosData.Memo.Attachment]
    @Environment(AppState.self) private var state

    var body: some View {
        let store = state.memos
        let images = files.filter { ($0.type ?? "").hasPrefix("image/") && !store.missing.contains(memo.id + "|" + $0.name) }
        let others = files.filter { f in !images.contains { $0.name == f.name } }
        VStack(alignment: .leading, spacing: 8) {
            if !images.isEmpty {
                HStack(spacing: 6) {
                    ForEach(images.prefix(4), id: \.name) { f in
                        ZStack {
                            if let image = store.thumbnail(memo, f) {
                                Image(nsImage: image).resizable().aspectRatio(contentMode: .fill)
                            } else {
                                Palette.sunk
                            }
                        }
                        .frame(width: 88, height: 66)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Palette.line2))
                        .help(f.filename ?? f.name)
                    }
                    if images.count > 4 { Text("+\(images.count - 4)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3) }
                }
            }
            if !others.isEmpty {
                HStack(spacing: 6) {
                    ForEach(others.prefix(3), id: \.name) { f in
                        Label(f.filename ?? f.name, systemImage: (f.type ?? "").hasPrefix("image/") ? "photo" : "doc")
                            .labelStyle(TightLabel())
                            .font(Typo.sans(11.5)).foregroundStyle(Palette.ink2).lineLimit(1)
                            .padding(.horizontal, 8).frame(height: 24)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Palette.sunk))
                    }
                    if others.count > 3 { Text("+\(others.count - 3)").font(Typo.sans(11.5)).foregroundStyle(Palette.ink3) }
                }
            }
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
