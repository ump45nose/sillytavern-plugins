import Foundation
import Testing
@testable import HubKit

private let fixedNow = GoogleDate.rfc3339("2026-10-20T09:00:00Z")!

private func makeSync(_ server: FakeGoogle, file: URL? = nil) async -> AgendaSync {
    var cal = Calendar.hub
    cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    let sync = AgendaSync(file: file, calendar: cal, now: { fixedNow })
    await sync.connect(api: GoogleAPI(transport: server, calendar: cal) { _ in "token" }, account: "me@example.com")
    return sync
}

private func seeded() -> FakeGoogle {
    let g = FakeGoogle()
    g.addList("work", "工作")
    g.addList("life", "生活")
    g.addTask("work", "t1", "提交 Q4 迁移方案", due: "2026-10-19")
    g.addTask("work", "t2", "整理文档", due: "2026-10-20")
    g.addTask("work", "t2a", "补截图", parent: "t2")
    g.addTask("life", "t3", "给妈妈打电话")
    g.addEvent("e1", "周会", start: "2026-10-20T02:00:00Z", end: "2026-10-20T03:00:00Z")
    g.addEvent("e2", "羽毛球", start: "2026-10-20T11:00:00Z", end: "2026-10-20T12:30:00Z")
    return g
}

@Test func initialPullFillsCache() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(await sync.status == .idle)
    #expect(s.lists.map(\.title) == ["工作", "生活"])
    #expect(Set(s.tasks.map(\.id)) == ["t1", "t2", "t2a", "t3"])
    #expect(s.tasks.first { $0.id == "t2a" }?.parent == "t2")
    #expect(s.tasks.first { $0.id == "t1" }?.due == "2026-10-19")
    #expect(s.events.map(\.title).sorted() == ["周会", "羽毛球"])
    #expect(s.calendarSyncTokens["me@example.com"] != nil)
    #expect(s.lastSync == fixedNow)
}

private let holiday = "zh.china#holiday@group.v.calendar.google.com"

@Test func subscribedCalendarsAreReadOnly() async {
    let g = seeded()
    g.locked { g.calendars.append(["id": holiday, "summary": "节假日", "selected": true, "accessRole": "reader"]) }
    g.addEvent("h1", "重阳节", start: "2026-10-21T00:00:00Z", end: "2026-10-21T01:00:00Z", cal: holiday)
    let sync = await makeSync(g)
    await sync.syncNow()
    #expect(await sync.status == .idle)
    let v = Agenda.build(await sync.snapshot, now: fixedNow)
    let h = v.upcomingEvents.first { $0.id == "h1" }
    #expect(h?.calendarTitle == "节假日")
    #expect(h?.editable == false)
    #expect(v.upcomingEvents.first { $0.id == "e2" }?.editable == true)
}

@Test func olderOwnedOnlyGrantSkipsOtherCalendars() async {
    let g = seeded()
    g.locked {
        g.calendars.append(["id": holiday, "summary": "节假日", "selected": true, "accessRole": "reader"])
        g.ownedOnlyScope = true
    }
    let sync = await makeSync(g)
    await sync.syncNow()
    #expect(await sync.status == .idle)
    let s = await sync.snapshot
    #expect(s.calendars.map(\.id) == ["me@example.com"])
    #expect(s.events.count == 2)
    let before = g.locked { g.log.count }
    await sync.syncNow()
    #expect(!g.locked { g.log[before...] }.contains { $0.contains("holiday") })
}

@Test func eventsCanBeEditedDeletedAndMoved() async {
    let g = seeded()
    g.locked { g.calendars.append(["id": "team", "summary": "团队", "selected": true, "accessRole": "writer"]) }
    let sync = await makeSync(g)
    await sync.syncNow()
    let start = GoogleDate.rfc3339("2026-10-20T03:00:00Z")!
    await sync.perform(.updateEvent(id: "e1", calendarID: "me@example.com",
                                    draft: EventDraft(title: "周会（改）", start: start, end: start.addingTimeInterval(1800), location: "3F")))
    await sync.perform(.moveEvent(id: "e1", calendarID: "me@example.com", to: "team"))
    await sync.perform(.deleteEvent(id: "e2", calendarID: "me@example.com"))
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.pending.isEmpty && s.failures.isEmpty)
    let moved = g.event("e1", cal: "team")
    #expect(moved?["summary"] as? String == "周会（改）")
    #expect((moved?["start"] as? [String: Any])?["dateTime"] as? String == "2026-10-20T03:00:00Z")
    #expect(moved?["location"] as? String == "3F")
    #expect(g.event("e1")?["status"] as? String == "cancelled")
    #expect(g.event("e2")?["status"] as? String == "cancelled")
    #expect(s.events.map(\.id) == ["e1"])
    #expect(s.events.first?.calendarID == "team")
}

@Test func switchingToAllDayClearsTheTime() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    var cal = Calendar.hub
    cal.timeZone = TimeZone(identifier: "Asia/Shanghai")!
    let day = cal.date(from: DateComponents(year: 2026, month: 10, day: 22))!
    await sync.perform(.updateEvent(id: "e2", calendarID: "me@example.com",
                                    draft: EventDraft(title: "羽毛球", start: day, end: cal.date(byAdding: .day, value: 1, to: day)!, allDay: true)))
    await sync.syncNow()
    let start = g.event("e2")?["start"] as? [String: Any]
    #expect(start?["date"] as? String == "2026-10-22")
    #expect(start?["dateTime"] == nil)
    let e = await sync.snapshot.events.first { $0.id == "e2" }
    #expect(e?.allDay == true)
}

@Test func offlineEventEditsCollapseOrUploadInOrder() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked { g.offline = true }
    let start = GoogleDate.rfc3339("2026-10-22T02:00:00Z")!
    let gone = AgendaStore.localID(), kept = AgendaStore.localID()
    await sync.perform(.createEvent(id: gone, calendarID: "me@example.com", draft: EventDraft(title: "临时", start: start, end: start.addingTimeInterval(600))))
    await sync.perform(.updateEvent(id: gone, calendarID: "me@example.com", draft: EventDraft(title: "临时2", start: start, end: start.addingTimeInterval(600))))
    await sync.perform(.deleteEvent(id: gone, calendarID: "me@example.com"))
    #expect(await sync.snapshot.pending.isEmpty)
    await sync.perform(.createEvent(id: kept, calendarID: "me@example.com", draft: EventDraft(title: "评审", start: start, end: start.addingTimeInterval(3600))))
    await sync.perform(.updateEvent(id: kept, calendarID: "me@example.com",
                                    draft: EventDraft(title: "评审（改）", start: start, end: start.addingTimeInterval(3600), notes: "带电脑")))
    await sync.syncNow()
    #expect(await sync.snapshot.events.contains { $0.title == "评审（改）" })
    g.locked { g.offline = false }
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.pending.isEmpty && s.failures.isEmpty)
    let server = g.locked { g.events["me@example.com"]!.filter { $0["status"] as? String != "cancelled" } }
    #expect(server.count == 3)
    #expect(server.contains { $0["summary"] as? String == "评审（改）" && $0["description"] as? String == "带电脑" })
    #expect(!s.events.contains { AgendaStore.isLocal($0.id) })
}

@Test func deletingAnEventAlreadyDeletedElsewhereSucceeds() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.cancelEvent("e1")
    await sync.perform(.deleteEvent(id: "e1", calendarID: "me@example.com"))
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.pending.isEmpty && s.failures.isEmpty)
    #expect(!s.events.contains { $0.id == "e1" })
}

@Test func invitationsFromOthersAreReadOnly() async {
    let g = seeded()
    g.addEvent("inv", "客户会议", start: "2026-10-20T06:00:00Z", end: "2026-10-20T07:00:00Z", organizer: "boss@example.com")
    g.addEvent("rec", "站会", start: "2026-10-20T01:00:00Z", end: "2026-10-20T01:15:00Z", recurring: true)
    let sync = await makeSync(g)
    await sync.syncNow()
    let v = Agenda.build(await sync.snapshot, now: fixedNow)
    #expect(v.events.first { $0.id == "inv" }?.editable == false)
    #expect(v.events.first { $0.id == "rec" }?.editable == true)
    #expect(v.events.first { $0.id == "rec" }?.recurring == true)
}

@Test func offlineChangesUploadInOrderWhenBackOnline() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked { g.offline = true }

    let temp = AgendaStore.localID()
    await sync.perform(.createTask(id: temp, listID: "work", title: "新任务", notes: nil, due: "2026-10-21", parent: nil))
    await sync.perform(.updateTask(id: temp, listID: "work", patch: TaskPatch(title: "新任务（改）")))
    await sync.perform(.updateTask(id: "t1", listID: "work", patch: TaskPatch(completed: true)))
    await sync.perform(.deleteTask(id: "t3", listID: "life"))
    await sync.syncNow()

    #expect(await sync.status == .offline)
    var s = await sync.snapshot
    #expect(s.pending.count == 4)
    #expect(s.tasks.contains { $0.id == temp && $0.title == "新任务（改）" })
    #expect(s.tasks.first { $0.id == "t1" }?.completed == true)
    #expect(!s.tasks.contains { $0.id == "t3" })

    g.locked { g.offline = false }
    await sync.syncNow()
    s = await sync.snapshot
    #expect(await sync.status == .idle)
    #expect(s.pending.isEmpty)
    #expect(s.failures.isEmpty)
    let created = g.task("work", titled: "新任务（改）")
    #expect(created?["due"] as? String == "2026-10-21T00:00:00.000Z")
    #expect(g.task("work", titled: "提交 Q4 迁移方案")?["status"] as? String == "completed")
    #expect(g.task("life", titled: "给妈妈打电话")?["deleted"] as? Bool == true)
    #expect(!s.tasks.contains { AgendaStore.isLocal($0.id) })
    #expect(s.tasks.contains { $0.id == created?["id"] as? String })
}

@Test func creatingThenDeletingOfflineSendsNothing() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked { g.offline = true }
    let temp = AgendaStore.localID()
    await sync.perform(.createTask(id: temp, listID: "work", title: "临时", notes: nil, due: nil, parent: nil))
    await sync.perform(.updateTask(id: temp, listID: "work", patch: TaskPatch(completed: true)))
    await sync.perform(.deleteTask(id: temp, listID: "work"))
    #expect(await sync.snapshot.pending.isEmpty)
    await sync.syncNow()
    let before = g.locked { g.log.count }
    g.locked { g.offline = false }
    await sync.syncNow()
    #expect(!g.locked { g.log[before...] }.contains { $0.hasPrefix("POST") || $0.hasPrefix("PATCH") || $0.hasPrefix("DELETE") })
}

@Test func taskInNewListUsesTheServerListID() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked { g.offline = true }
    let list = AgendaStore.localID(), task = AgendaStore.localID(), sub = AgendaStore.localID()
    await sync.perform(.createList(id: list, title: "旅行"))
    await sync.perform(.createTask(id: task, listID: list, title: "订机票", notes: "早班", due: nil, parent: nil))
    await sync.perform(.createTask(id: sub, listID: list, title: "比价", notes: nil, due: nil, parent: task))
    g.locked { g.offline = false }
    await sync.syncNow()

    let s = await sync.snapshot
    let serverList = g.locked { g.lists.first { $0["title"] as? String == "旅行" }?["id"] as? String }
    #expect(serverList != nil)
    let parent = g.task(serverList!, titled: "订机票")
    #expect(parent?["notes"] as? String == "早班")
    #expect(g.task(serverList!, titled: "比价")?["parent"] as? String == parent?["id"] as? String)
    #expect(s.lists.contains { $0.id == serverList })
    #expect(s.pending.isEmpty && s.failures.isEmpty)
}

@Test func incrementalPullAppliesRemoteEditsAndDeletes() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked {
        g.tasks["work"]![0]["title"] = "提交 Q4 迁移方案 v2"
        g.tasks["work"]![0]["updated"] = "2026-10-20T10:00:00Z"
        g.tasks["life"]![0]["deleted"] = true
        g.tasks["life"]![0]["updated"] = "2026-10-20T10:00:01Z"
    }
    g.addTask("life", "t4", "续费域名", updated: "2026-10-20T10:00:02Z")
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.tasks.first { $0.id == "t1" }?.title == "提交 Q4 迁移方案 v2")
    #expect(!s.tasks.contains { $0.id == "t3" })
    #expect(s.tasks.contains { $0.id == "t4" })
    #expect(s.tasks.contains { $0.id == "t2" })
    #expect(g.log.contains { $0.contains("/lists/work/tasks?") && $0.contains("updatedMin=2026-10-20T08:55:00Z") })
}

@Test func calendarUsesSyncTokenAndRecoversFromExpiry() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.cancelEvent("e1")
    g.addEvent("e3", "迁移方案评审", start: "2026-10-20T06:00:00Z", end: "2026-10-20T07:30:00Z")
    await sync.syncNow()
    var s = await sync.snapshot
    #expect(s.events.map(\.title).sorted() == ["羽毛球", "迁移方案评审"])
    #expect(g.log.contains { $0.contains("/events?") && $0.contains("syncToken=") })

    g.locked { g.expiredTokens = true }
    g.addEvent("e4", "晚饭", start: "2026-10-20T12:00:00Z", end: "2026-10-20T13:00:00Z")
    await sync.syncNow()
    s = await sync.snapshot
    #expect(await sync.status == .idle)
    #expect(s.events.map(\.title).sorted() == ["晚饭", "羽毛球", "迁移方案评审"])
}

@Test func permanentFailureIsReportedAndQueueContinues() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked { g.failNext["PATCH /tasks/v1/lists/work/tasks/t1"] = 400 }
    await sync.perform(.updateTask(id: "t1", listID: "work", patch: TaskPatch(title: "坏请求")))
    await sync.perform(.updateTask(id: "t2", listID: "work", patch: TaskPatch(completed: true)))
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.pending.isEmpty)
    #expect(s.failures.count == 1)
    #expect(s.failures[0].summary.contains("400"))
    #expect(g.task("work", titled: "整理文档")?["status"] as? String == "completed")
    // The server copy wins after a rejected edit.
    #expect(s.tasks.first { $0.id == "t1" }?.title == "提交 Q4 迁移方案")
}

@Test func deletingSomethingAlreadyGoneSucceedsQuietly() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    g.locked { g.tasks["life"]![0]["deleted"] = true }
    await sync.perform(.deleteTask(id: "t3", listID: "life"))
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.pending.isEmpty && s.failures.isEmpty)
}

@Test func moveToAnotherListAndTimeBlock() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    await sync.perform(.moveTask(id: "t3", listID: "life", toList: "work", parent: nil))
    let start = GoogleDate.rfc3339("2026-10-21T07:00:00Z")!
    await sync.perform(.createEvent(id: AgendaStore.localID(), calendarID: "me@example.com",
                                    draft: EventDraft(title: "对齐方案", start: start, end: start.addingTimeInterval(3600))))
    await sync.syncNow()
    let s = await sync.snapshot
    #expect(s.tasks.first { $0.id == "t3" }?.listID == "work")
    #expect(g.task("work", titled: "给妈妈打电话") != nil)
    #expect(s.events.contains { $0.title == "对齐方案" && !AgendaStore.isLocal($0.id) })
}

@Test func cacheAndQueueSurviveRestart() async throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: dir) }
    let file = dir.appendingPathComponent("agenda.json")
    let g = seeded()
    let first = await makeSync(g, file: file)
    await first.syncNow()
    g.locked { g.offline = true }
    await first.perform(.updateTask(id: "t1", listID: "work", patch: TaskPatch(due: .some(nil))))
    await first.syncNow()

    let second = await makeSync(g, file: file)
    let s = await second.snapshot
    #expect(s.tasks.count == 4)
    #expect(s.pending.count == 1)
    #expect(s.pending[0].change == .updateTask(id: "t1", listID: "work", patch: TaskPatch(due: .some(nil))))
    #expect(s.tasks.first { $0.id == "t1" }?.due == nil)
    let attrs = try FileManager.default.attributesOfItem(atPath: file.path)
    #expect((attrs[.posixPermissions] as? Int) == 0o600)

    g.locked { g.offline = false }
    await second.syncNow()
    #expect(g.task("work", titled: "提交 Q4 迁移方案")?["due"] == nil)
}

@Test func switchingAccountsDropsTheOldCache() async {
    let g = seeded()
    let sync = await makeSync(g)
    await sync.syncNow()
    await sync.connect(api: nil, account: "other@example.com")
    let s = await sync.snapshot
    #expect(s.tasks.isEmpty && s.lists.isEmpty && s.account == "other@example.com")
}

@Test func patchEncodingKeepsClearDistinctFromUnchanged() throws {
    let patches = [TaskPatch(title: "a"), TaskPatch(due: .some(nil)), TaskPatch(notes: .some("n"), due: .some("2026-10-21")), TaskPatch(completed: false)]
    for p in patches {
        let decoded = try JSONDecoder().decode(TaskPatch.self, from: JSONEncoder().encode(p))
        #expect(decoded == p)
    }
    #expect(TaskPatch(due: .some(nil)).body["due"] is NSNull)
    #expect(TaskPatch(title: "a").body["due"] == nil)
}

@Test func expiredAccessTokenIsRefreshedOnce() async throws {
    final class Counter: @unchecked Sendable { var forced = 0 }
    let counter = Counter()
    let g = seeded()
    g.locked { g.failNext["GET /tasks/v1/users/@me/lists"] = 401 }
    let api = GoogleAPI(transport: g) { force in
        if force { counter.forced += 1 }
        return "token"
    }
    let lists = try await api.taskLists()
    #expect(lists.count == 2)
    #expect(counter.forced == 1)
}
