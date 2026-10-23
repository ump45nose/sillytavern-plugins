import Foundation
import Testing
@testable import HubKit

@Test func trayDefaultsStayOutOfTheDocument() throws {
    var doc = LayoutDocument.default
    #expect(doc.tray == nil)
    #expect(doc.trayPages.map(\.id) == ["today", "life", "work"])
    doc.editTrayPage("life") { $0.remove("crm") }
    #expect(doc.tray?.first { $0.id == "life" }?.items == ["health", "bills"])
    doc.editTrayPage("life") { $0.add("crm") }
    #expect(doc.tray == nil)

    let json = String(decoding: try JSONEncoder().encode(doc), as: UTF8.self)
    #expect(!json.contains("tray"))
    let old = #"{"version":\#(LayoutDocument.currentVersion),"pages":[]}"#
    #expect(try JSONDecoder().decode(LayoutDocument.self, from: Data(old.utf8)).tray == nil)
}

@Test func trayPageItems() {
    var page = TrayPage(id: "p", title: "测试")
    page.add("tasks")
    page.add("tasks")
    page.add("git")
    page.add("brief")
    page.add("nonsense")
    #expect(page.items == ["tasks", "git"])
    page.move("git", by: -1)
    #expect(page.items == ["git", "tasks"])
    page.move("git", by: -1)
    #expect(page.items == ["git", "tasks"])
    page.remove("git")
    #expect(page.items == ["tasks"])
    #expect(!page.unused.contains("tasks"))
    #expect(page.unused.contains("health"))
    #expect(!TrayPage.choices.contains("brief"))
    #expect(Set(TrayPage.choices).count == TrayPage.choices.count)
}

@Test func trayPagesAddRenameMoveRemove() throws {
    var doc = LayoutDocument.default
    let added = doc.addTrayPage()
    let id = try #require(added)
    #expect(doc.trayPages.count == 4)
    let overflow = doc.addTrayPage()
    #expect(overflow == nil)

    doc.renameTrayPage(id, title: "  学习计划表  ")
    #expect(doc.trayPages.last?.title == "学习计划")
    doc.renameTrayPage(id, title: "   ")
    #expect(doc.trayPages.last?.title == "学习计划")

    doc.moveTrayPage(id, by: -1)
    #expect(doc.trayPages.map(\.id) == ["today", "life", id, "work"])
    doc.moveTrayPage("today", by: -1)
    #expect(doc.trayPages.first?.id == "today")

    doc.removeTrayPage(id)
    #expect(doc.tray == nil)
    for page in doc.trayPages.dropFirst() { doc.removeTrayPage(page.id) }
    doc.removeTrayPage("today")
    #expect(doc.trayPages.map(\.id) == ["today"])
}
