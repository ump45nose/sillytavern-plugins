import Foundation
import Testing
@testable import HubKit

@Test func rowsWrapWhenColumnsRunOut() {
    #expect(Grid.rows(spans: [12, 7, 5, 12, 3, 3, 3, 3, 3]) == [[0], [1, 2], [3], [4, 5, 6, 7], [8]])
    #expect(Grid.rows(spans: [6, 6, 6]) == [[0, 1], [2]])
    #expect(Grid.rows(spans: [20, 0]) == [[0], [1]])
    #expect(Grid.rows(spans: []) == [])
}

@Test func columnWidthsIncludeGaps() {
    let total = 12.0 * 60 + 11 * Grid.gap
    #expect(Grid.width(span: 12, total: total) == total)
    #expect(Grid.width(span: 3, total: total) == 3 * 60 + 2 * Grid.gap)
}

@Test func spanOverrideOnlyAppliesToDetail() {
    #expect(LayoutItem(.git, .detail, span: 12).effectiveSpan == 12)
    #expect(LayoutItem(.git, .compact, span: 12).effectiveSpan == 3)
    #expect(LayoutItem(.agenda, .detail).effectiveSpan == 6)
    #expect(LayoutItem(.attention, .compact).effectiveSpan == 12)
}

@Test func defaultHomeMatchesDesign() {
    let home = LayoutDocument.default.page("home")!
    let rows = Grid.rows(spans: home.items.map(\.effectiveSpan))
    #expect(rows.map(\.count) == [1, 2, 1, 4, 4])
    #expect(home.unusedModules == [.media, .subs, .plaud])
}

@Test func pageEditing() {
    var page = LayoutDocument.default.page("usage")!
    page.setSize(.compact, at: 0)
    #expect(page.items[0].size == .compact)
    page.move(at: 0, by: 1)
    #expect(page.items.map(\.module) == [.git, .token, .net, .subs])
    page.move(at: 0, by: -1)
    #expect(page.items.map(\.module) == [.git, .token, .net, .subs])
    page.remove(at: 3)
    page.add(.subs)
    page.add(.subs)
    #expect(page.items.map(\.module) == [.git, .token, .net, .subs])
    #expect(page.items[3].size == .compact)
}

@Test func customPagesCanBeAddedRenamedMovedAndRemoved() throws {
    var doc = LayoutDocument.default
    let added = doc.addPage(title: "  阅读  ")
    let id = try #require(added)
    #expect(doc.pages.last?.id == id && doc.pages.last?.title == "阅读" && doc.pages.last?.items == [])

    doc.renamePage(id, title: "", subtitle: "  书和播客  ")
    #expect(doc.page(id)?.title == "阅读" && doc.page(id)?.subtitle == "书和播客")
    doc.renamePage(id, title: "一个远远超过十二个字的页面名称啊", subtitle: "")
    #expect(doc.page(id)?.title.count == LayoutDocument.maxTitle && doc.page(id)?.subtitle == "")

    doc.movePage(id, to: 0)
    #expect(doc.pages.first?.id == id)
    doc.movePage(id, by: -1)
    #expect(doc.pages.first?.id == id)
    doc.movePage(id, by: 1)
    #expect(doc.pages.map(\.id).prefix(2) == ["home", id])

    let removedHome = doc.removePage("home")
    let removedCustom = doc.removePage(id)
    #expect(!removedHome, "built-in pages stay")
    #expect(removedCustom)
    #expect(doc == .default)
}

@Test func pageLimitMatchesTheCommandDigits() {
    var doc = LayoutDocument.default
    while doc.addPage() != nil {}
    #expect(doc.pages.count == LayoutDocument.maxPages)
    #expect(Set(doc.pages.map(\.id)).count == doc.pages.count)
}

@Test func resettingAPageKeepsItsNameAndPlace() {
    var doc = LayoutDocument.default
    doc.renamePage("usage", title: "开销", subtitle: "")
    doc.movePage("usage", to: 0)
    doc.update("usage") { $0.remove(at: 0) }
    doc.resetPage("usage")
    #expect(doc.pages[0].title == "开销" && doc.pages[0].items == LayoutDocument.default.page("usage")!.items)
    let id = doc.addPage()!
    doc.update(id) { $0.add(.token) }
    doc.resetPage(id)
    #expect(doc.page(id)?.items == [])
}

@Test func storeRoundTripsAndSetsCorruptFilesAside() throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: dir) }
    let store = LayoutStore(url: dir.appendingPathComponent("layout.json"))
    #expect(store.load() == .default)

    var doc = LayoutDocument.default
    doc.update("home") { $0.remove(at: 0) }
    try store.save(doc)
    #expect(store.load() == doc)

    try Data("{broken".utf8).write(to: store.url)
    #expect(store.load() == .default)
    let names = try FileManager.default.contentsOfDirectory(atPath: dir.path)
    #expect(names.contains { $0.contains("unreadable") })
}

@Test func detailCardsResizeWithinTheGrid() {
    var page = LayoutDocument.default.page("home")!
    let goals = page.items.firstIndex { $0.module == .goals }!
    page.resize(at: goals, by: 2)
    #expect(page.items[goals].span == 8)
    page.resize(at: goals, by: 10)
    #expect(page.items[goals].effectiveSpan == 12)
    page.resize(at: goals, by: -20)
    #expect(page.items[goals].effectiveSpan == 4)
    page.resize(at: goals, by: 2)
    #expect(page.items[goals].span == nil, "back at the default span the override is dropped")
    let health = page.items.firstIndex { $0.module == .health }!
    page.resize(at: health, by: 3)
    #expect(page.items[health].span == nil, "compact cards keep their fixed span")
}

@Test func olderLayoutsGainNewBuiltinPagesInPlace() throws {
    var old = LayoutDocument.default
    old.pages.removeAll { $0.id == "review" }
    let added = old.addPage(title: "阅读")
    let custom = try #require(added)
    let migrated = old.withBuiltins()
    #expect(migrated.pages.map(\.id) == ["home", "life", "usage", "sky", "memos", "review", custom])
    #expect(migrated.withBuiltins() == migrated)

    var full = LayoutDocument.default
    full.pages.removeAll { $0.id == "review" }
    while full.addPage() != nil {}
    #expect(full.withBuiltins() == full, "a full document is left alone")
}

@Test func unknownKindsMakeTheDocumentUnreadable() throws {
    // A newer client's page or module must not be silently rewritten, so the whole document is left alone.
    let page = #"{"version":1,"pages":[{"id":"x","title":"X","subtitle":"","kind":"timeline","items":[]}]}"#
    #expect(throws: DecodingError.self) { try JSONDecoder().decode(LayoutDocument.self, from: Data(page.utf8)) }
    let height = #"{"version":1,"pages":[{"id":"x","title":"X","subtitle":"","kind":"grid","items":[{"module":"plaud","size":"detail","height":"tall"}]}]}"#
    let doc = try JSONDecoder().decode(LayoutDocument.self, from: Data(height.utf8))
    #expect(doc.pages[0].items[0].height == .tall)
}

@Test func onlyDetailCardsTakeAFixedHeight() {
    var page = LayoutDocument.default.page("home")!
    let goals = page.items.firstIndex { $0.module == .goals }!
    page.setHeight(.medium, at: goals)
    #expect(page.items[goals].effectiveHeight == .medium)
    page.setSize(.compact, at: goals)
    #expect(page.items[goals].effectiveHeight == nil)
    let health = page.items.firstIndex { $0.module == .health }!
    page.setHeight(.tall, at: health)
    #expect(page.items[health].height == nil)
}
