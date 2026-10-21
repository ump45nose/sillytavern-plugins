import Foundation

public enum ModuleID: String, Codable, CaseIterable, Sendable {
    case brief, agenda, goals, attention, health, bills, crm, media, token, git, net, subs, sky, memos

    /// Default column span on the 12-column grid.
    public func defaultSpan(_ size: ModuleSize) -> Int {
        switch (self, size) {
        case (.brief, _): 12
        case (.attention, .compact): 12
        case (.attention, .detail): 5
        case (.agenda, .detail): 6
        case (.goals, .detail): 6
        case (.media, .detail), (.token, .detail): 12
        case (_, .compact): 3
        case (_, .detail): 6
        }
    }
}

public enum ModuleSize: String, Codable, Sendable {
    case compact, detail

    public var toggled: ModuleSize { self == .compact ? .detail : .compact }
}

/// Fixed heights for detail cards; content beyond them scrolls inside the card. nil is automatic.
public enum ModuleHeight: String, Codable, CaseIterable, Sendable {
    case medium, tall

    public var points: Double { self == .medium ? 360 : 560 }
}

public struct LayoutItem: Codable, Hashable, Sendable, Identifiable {
    public var module: ModuleID
    public var size: ModuleSize
    /// Overrides the default span; only applies to the detail size.
    public var span: Int?
    /// Only applies to the detail size.
    public var height: ModuleHeight?

    public init(_ module: ModuleID, _ size: ModuleSize, span: Int? = nil, height: ModuleHeight? = nil) {
        self.module = module
        self.size = size
        self.span = span
        self.height = height
    }

    public var effectiveHeight: ModuleHeight? { size == .detail ? height : nil }

    public var id: ModuleID { module }

    public var effectiveSpan: Int {
        let s = size == .detail ? (span ?? module.defaultSpan(.detail)) : module.defaultSpan(.compact)
        return min(max(s, 1), Grid.columns)
    }
}

public enum PageKind: String, Codable, Sendable {
    case grid, sky, memos, review

    /// A kind from a newer client reads as a plain grid instead of failing the whole document.
    public init(from decoder: Decoder) throws {
        self = PageKind(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .grid
    }
}

public struct Page: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var title: String
    public var subtitle: String
    public var kind: PageKind
    public var items: [LayoutItem]

    public init(id: String, title: String, subtitle: String = "", kind: PageKind = .grid, items: [LayoutItem] = []) {
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.kind = kind
        self.items = items
    }

    public var unusedModules: [ModuleID] {
        ModuleID.allCases.filter { m in !items.contains { $0.module == m } }
    }

    public mutating func setSize(_ size: ModuleSize, at index: Int) {
        guard items.indices.contains(index) else { return }
        items[index].size = size
    }

    /// Detail cards can be resized from a third of the grid up to full width.
    public static let spanRange = 4...Grid.columns

    public mutating func resize(at index: Int, by offset: Int) {
        guard items.indices.contains(index), items[index].size == .detail else { return }
        let next = min(max(items[index].effectiveSpan + offset, Self.spanRange.lowerBound), Self.spanRange.upperBound)
        items[index].span = next == items[index].module.defaultSpan(.detail) ? nil : next
    }

    public mutating func setHeight(_ height: ModuleHeight?, at index: Int) {
        guard items.indices.contains(index), items[index].size == .detail else { return }
        items[index].height = height
    }

    public mutating func move(at index: Int, by offset: Int) {
        let target = index + offset
        guard items.indices.contains(index), items.indices.contains(target) else { return }
        items.swapAt(index, target)
    }

    public mutating func remove(at index: Int) {
        guard items.indices.contains(index) else { return }
        items.remove(at: index)
    }

    public mutating func add(_ module: ModuleID, size: ModuleSize = .compact) {
        guard !items.contains(where: { $0.module == module }) else { return }
        items.append(LayoutItem(module, size))
    }
}

public struct LayoutDocument: Codable, Equatable, Sendable {
    public static let currentVersion = 1

    public var version: Int
    public var pages: [Page]
    /// Menu bar panel pages (Mac only); nil means the default tray.
    public var tray: [TrayPage]?

    public init(version: Int = LayoutDocument.currentVersion, pages: [Page], tray: [TrayPage]? = nil) {
        self.version = version
        self.pages = pages
        self.tray = tray
    }

    public func page(_ id: String) -> Page? { pages.first { $0.id == id } }

    public mutating func update(_ id: String, _ change: (inout Page) -> Void) {
        guard let i = pages.firstIndex(where: { $0.id == id }) else { return }
        change(&pages[i])
    }

    // MARK: Pages

    /// ⌘1–⌘9 address pages by position.
    public static let maxPages = 9
    public static let maxTitle = 12
    public static let maxSubtitle = 40

    /// Built-in pages can be renamed and reordered but not removed; custom pages are plain grids.
    public static func isBuiltin(_ id: String) -> Bool { LayoutDocument.default.page(id) != nil }

    public var canAddPage: Bool { pages.count < Self.maxPages }

    /// Appends an empty grid page and returns its id, or nil when the page limit is reached.
    @discardableResult
    public mutating func addPage(title: String = "新页面", id: String? = nil) -> String? {
        guard canAddPage else { return nil }
        var identifier = id ?? "page-" + UUID().uuidString.prefix(8).lowercased()
        while page(identifier) != nil { identifier += "x" }
        pages.append(Page(id: identifier, title: Self.clean(title, Self.maxTitle) ?? "新页面"))
        return identifier
    }

    /// An empty title keeps the current one; an empty subtitle clears it.
    public mutating func renamePage(_ id: String, title: String, subtitle: String) {
        update(id) { page in
            if let t = Self.clean(title, Self.maxTitle) { page.title = t }
            page.subtitle = Self.clean(subtitle, Self.maxSubtitle) ?? ""
        }
    }

    public mutating func movePage(_ id: String, to index: Int) {
        guard let from = pages.firstIndex(where: { $0.id == id }) else { return }
        let page = pages.remove(at: from)
        pages.insert(page, at: min(max(index, 0), pages.count))
    }

    public mutating func movePage(_ id: String, by offset: Int) {
        guard let from = pages.firstIndex(where: { $0.id == id }), pages.indices.contains(from + offset) else { return }
        pages.swapAt(from, from + offset)
    }

    @discardableResult
    public mutating func removePage(_ id: String) -> Bool {
        guard !Self.isBuiltin(id), let i = pages.firstIndex(where: { $0.id == id }) else { return false }
        pages.remove(at: i)
        return true
    }

    /// Built-in pages introduced after this document was written, inserted at their default position.
    public func withBuiltins() -> LayoutDocument {
        var doc = self
        for (i, page) in LayoutDocument.default.pages.enumerated() where doc.page(page.id) == nil && doc.canAddPage {
            doc.pages.insert(page, at: min(i, doc.pages.count))
        }
        return doc
    }

    /// Restores a built-in page's modules (keeping its name and position); custom pages are emptied.
    public mutating func resetPage(_ id: String) {
        let items = LayoutDocument.default.page(id)?.items ?? []
        update(id) { $0.items = items }
    }

    private static func clean(_ text: String, _ limit: Int) -> String? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "\n", with: " ")
        return t.isEmpty ? nil : String(t.prefix(limit))
    }

    public static let `default` = LayoutDocument(pages: [
        Page(id: "home", title: "主页", items: [
            LayoutItem(.brief, .detail), LayoutItem(.agenda, .detail), LayoutItem(.goals, .detail),
            LayoutItem(.attention, .compact), LayoutItem(.health, .compact), LayoutItem(.bills, .compact),
            LayoutItem(.crm, .compact), LayoutItem(.token, .compact), LayoutItem(.net, .compact),
            LayoutItem(.git, .compact), LayoutItem(.sky, .compact), LayoutItem(.memos, .compact),
        ]),
        Page(id: "life", title: "生活", subtitle: "健康、账单、交流与媒体", items: [
            LayoutItem(.health, .detail), LayoutItem(.bills, .detail), LayoutItem(.crm, .detail),
            LayoutItem(.media, .detail, span: 6),
        ]),
        Page(id: "usage", title: "用量", subtitle: "Token、GitHub、网络与订阅", items: [
            LayoutItem(.token, .detail), LayoutItem(.git, .detail, span: 12),
            LayoutItem(.net, .detail), LayoutItem(.subs, .detail),
        ]),
        Page(id: "sky", title: "电脑历史", subtitle: "MacPro 与 MacAir 的 6 小时窗口摘要", kind: .sky),
        Page(id: "memos", title: "Memos", subtitle: "直接嵌入 Memos · ⌃⌥M 随时记录", kind: .memos),
        Page(id: "review", title: "复盘", subtitle: "日报、周报与本阶段", kind: .review),
    ])
}

public enum Grid {
    public static let columns = 12
    public static let gap: Double = 16

    /// Greedy row packing: an item that does not fit the remaining columns starts a new row.
    public static func rows(spans: [Int], columns: Int = Grid.columns) -> [[Int]] {
        var rows: [[Int]] = []
        var current: [Int] = []
        var used = 0
        for (i, raw) in spans.enumerated() {
            let span = min(max(raw, 1), columns)
            if used + span > columns, !current.isEmpty {
                rows.append(current)
                current = []
                used = 0
            }
            current.append(i)
            used += span
        }
        if !current.isEmpty { rows.append(current) }
        return rows
    }

    public static func width(span: Int, total: Double, columns: Int = Grid.columns) -> Double {
        let col = (total - gap * Double(columns - 1)) / Double(columns)
        return col * Double(span) + gap * Double(span - 1)
    }
}
