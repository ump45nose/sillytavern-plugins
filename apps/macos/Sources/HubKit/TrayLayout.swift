import Foundation

/// Widgets that only exist in the menu bar panel; every other tray item is a module's compact view.
public enum TrayWidget: String, Codable, CaseIterable, Sendable {
    case attention, agenda, tasks, metrics
}

/// A page of the menu bar panel: an ordered list of widget or module ids.
public struct TrayPage: Codable, Hashable, Sendable, Identifiable {
    public var id: String
    public var title: String
    public var items: [String]

    public init(id: String, title: String, items: [String] = []) {
        self.id = id
        self.title = title
        self.items = items
    }

    /// The 380-point panel fits four tabs of up to four characters next to the edit button.
    public static let maxPages = 4
    public static let maxTitle = 4

    public static let defaults = [
        TrayPage(id: "today", title: "今天", items: ["attention", "agenda", "tasks", "metrics"]),
        TrayPage(id: "life", title: "生活", items: ["health", "bills", "crm"]),
        TrayPage(id: "work", title: "工作", items: ["goals", "token", "git"]),
    ]

    /// What can go on a tray page. The panel has richer agenda and attention widgets, and the brief
    /// is a page-wide greeting, so those modules are not offered.
    public static let choices: [String] = TrayWidget.allCases.map(\.rawValue)
        + ModuleID.allCases.filter { ![.brief, .agenda, .attention].contains($0) }.map(\.rawValue)

    public var unused: [String] { Self.choices.filter { !items.contains($0) } }

    public mutating func add(_ item: String) {
        guard Self.choices.contains(item), !items.contains(item) else { return }
        items.append(item)
    }

    public mutating func remove(_ item: String) { items.removeAll { $0 == item } }

    public mutating func move(_ item: String, by offset: Int) {
        guard let i = items.firstIndex(of: item), items.indices.contains(i + offset) else { return }
        items.swapAt(i, i + offset)
    }
}

extension LayoutDocument {
    /// nil in the document means the default tray, so untouched layouts stay byte-identical on hub.
    public var trayPages: [TrayPage] { tray ?? TrayPage.defaults }

    public mutating func editTray(_ change: (inout [TrayPage]) -> Void) {
        var pages = trayPages
        change(&pages)
        tray = pages == TrayPage.defaults ? nil : pages
    }

    public mutating func editTrayPage(_ id: String, _ change: (inout TrayPage) -> Void) {
        editTray { pages in
            guard let i = pages.firstIndex(where: { $0.id == id }) else { return }
            change(&pages[i])
        }
    }

    @discardableResult
    public mutating func addTrayPage(title: String = "新页") -> String? {
        guard trayPages.count < TrayPage.maxPages else { return nil }
        var id = "tray-" + UUID().uuidString.prefix(6).lowercased()
        while trayPages.contains(where: { $0.id == id }) { id += "x" }
        editTray { $0.append(TrayPage(id: id, title: title)) }
        return id
    }

    /// The last remaining page stays.
    public mutating func removeTrayPage(_ id: String) {
        guard trayPages.count > 1 else { return }
        editTray { $0.removeAll { $0.id == id } }
    }

    public mutating func renameTrayPage(_ id: String, title: String) {
        let t = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        editTrayPage(id) { $0.title = String(t.prefix(TrayPage.maxTitle)) }
    }

    public mutating func moveTrayPage(_ id: String, by offset: Int) {
        editTray { pages in
            guard let i = pages.firstIndex(where: { $0.id == id }), pages.indices.contains(i + offset) else { return }
            pages.swapAt(i, i + offset)
        }
    }
}
