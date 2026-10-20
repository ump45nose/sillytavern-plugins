import Foundation

public enum ModuleID: String, Codable, CaseIterable, Sendable {
    case brief, agenda, goals, attention, health, bills, crm, media, token, git, net, subs, sky, memos

    /// Default column span on the 12-column grid.
    public func defaultSpan(_ size: ModuleSize) -> Int {
        switch (self, size) {
        case (.brief, _): 12
        case (.attention, .compact): 12
        case (.attention, .detail): 5
        case (.agenda, .detail): 7
        case (.goals, .detail): 5
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

public struct LayoutItem: Codable, Hashable, Sendable, Identifiable {
    public var module: ModuleID
    public var size: ModuleSize
    /// Overrides the default span; only applies to the detail size.
    public var span: Int?

    public init(_ module: ModuleID, _ size: ModuleSize, span: Int? = nil) {
        self.module = module
        self.size = size
        self.span = span
    }

    public var id: ModuleID { module }

    public var effectiveSpan: Int {
        let s = size == .detail ? (span ?? module.defaultSpan(.detail)) : module.defaultSpan(.compact)
        return min(max(s, 1), Grid.columns)
    }
}

public enum PageKind: String, Codable, Sendable {
    case grid, sky, memos
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

    public init(version: Int = LayoutDocument.currentVersion, pages: [Page]) {
        self.version = version
        self.pages = pages
    }

    public func page(_ id: String) -> Page? { pages.first { $0.id == id } }

    public mutating func update(_ id: String, _ change: (inout Page) -> Void) {
        guard let i = pages.firstIndex(where: { $0.id == id }) else { return }
        change(&pages[i])
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
