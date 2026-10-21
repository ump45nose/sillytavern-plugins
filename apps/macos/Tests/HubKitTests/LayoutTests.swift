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
    #expect(LayoutItem(.agenda, .detail).effectiveSpan == 7)
    #expect(LayoutItem(.attention, .compact).effectiveSpan == 12)
}

@Test func defaultHomeMatchesDesign() {
    let home = LayoutDocument.default.page("home")!
    let rows = Grid.rows(spans: home.items.map(\.effectiveSpan))
    #expect(rows.map(\.count) == [1, 2, 1, 4, 4])
    #expect(home.unusedModules == [.media, .subs])
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
