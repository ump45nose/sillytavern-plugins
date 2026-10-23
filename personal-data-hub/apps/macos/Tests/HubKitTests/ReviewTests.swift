import Foundation
import Testing
@testable import HubKit

/// Answers each request from a closure, recording the JSON bodies it was sent.
final class ScriptedHub: HTTPTransport, @unchecked Sendable {
    private let lock = NSLock()
    private let reply: @Sendable (URLRequest) -> (Int, String)
    private(set) var requests: [(method: String, path: String, body: [String: Any]?, ifMatch: String?)] = []

    init(_ reply: @escaping @Sendable (URLRequest) -> (Int, String)) { self.reply = reply }

    func send(_ request: URLRequest) async throws -> (Data, HTTPURLResponse) {
        let body = request.httpBody.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        lock.lock()
        requests.append((request.httpMethod ?? "GET", request.url!.path, body, request.value(forHTTPHeaderField: "If-Match")))
        lock.unlock()
        let (code, text) = reply(request)
        return (Data(text.utf8), HTTPURLResponse(url: request.url!, statusCode: code, httpVersion: nil, headerFields: nil)!)
    }
}

private func api(_ hub: ScriptedHub) -> HubAPI {
    HubAPI(transport: hub, credential: HubCredential(baseURL: URL(string: "http://hub.test")!, token: "t"))
}

private let goalsJSON = #"""
{"modules": {"goals": {"module": "goals", "status": "partial", "updated_at": "2026-10-21T10:30:00.123456+08:00", "sources": [{"id": "review", "status": "ok", "updated_at": null}],
  "data": {
    "mainline": {"domain": "总主线", "direction": "把注意力放在长期的事上", "purpose": null, "meaning": null, "status": "推进中", "recent_change": null, "memo_name": "memos/1", "updated_at": null},
    "cycle": {"id": "2026-S4A94", "index": 1, "status": "active", "starts_at": "2026-09-14T16:38:02.972119+08:00", "ends_at": "2026-10-26T16:38:02.972119+08:00", "day": 38, "total": 42, "preclose_at": "2026-10-25T16:38:02.972119+08:00"},
    "goals": [{"id": "2026-S4A94-1a2b3c", "domain": "事业", "status": "active", "goal": "上线 v1", "progress": "接入中", "deadline": "2026-10-26", "success_criteria": "每天在用", "stop_signal": "两周不动", "memo_name": "memos/2", "latest_comment": null}],
    "reviews": {"daily": {"id": "daily:2026-10-20", "label": "2026-10-20", "status": "open", "prepared_at": "2026-10-20T21:20:11+08:00", "expires_at": "2026-10-22T00:30:00+08:00", "memo_name": null},
                "weekly": {"id": "weekly:2026-W42", "label": "2026-W42", "status": "something-new", "prepared_at": null, "expires_at": null, "memo_name": null},
                "next_daily_at": "2026-10-21T21:30:00+08:00", "next_weekly_at": null},
    "close": {"status": "awaiting_close", "cycle_id": "2026-S4A94", "template": "#阶段总结 2026-S4A94\n\n这个 loop 成了没成："}
  }}}}
"""#

@Test func goalsModuleDecodesFromTheBatch() async throws {
    let hub = ScriptedHub { _ in (200, goalsJSON) }
    let data = try await api(hub).modules()
    let goals = try #require(data.goals)
    #expect(goals.status == .partial)
    #expect(data.status(.goals) == .partial)
    let d = try #require(goals.data)
    #expect(d.mainline?.direction == "把注意力放在长期的事上")
    #expect(d.mainline?.recentChange == nil)
    #expect(d.cycle?.day == 38 && d.cycle?.total == 42)
    #expect(d.goals?.first?.successCriteria == "每天在用")
    #expect(d.reviews?.daily?.status == .open)
    #expect(d.reviews?.weekly?.status == .expired, "unknown states must not be offered for confirmation")
    #expect(d.close?.status == .awaitingClose)
}

@Test func sessionDetailAndRuleRejections() async throws {
    let detail = #"""
    {"id": "daily:2026-10-20", "kind": "daily", "label": "2026-10-20", "status": "open", "prepared_at": null, "expires_at": "2026-10-22T00:30:00+08:00", "memo_name": null,
     "material": {"sections": [{"title": "Skysight", "blocks": ["- a"]}], "template": "#日报 2026-10-20\n一句话总结今天：\n\n情绪："},
     "delivered": null, "final_content": null,
     "rules": {"fields": ["情绪"], "auto_fields": ["健康", "财务"], "summary_max_chars": 45, "summary_max_list_separators": 1, "max_unresolved": 2, "moment_min_chars": 6, "emotion_words": ["平静"]}}
    """#
    let hub = ScriptedHub { r in
        switch r.url!.lastPathComponent {
        case "preview": (422, #"{"error": {"code": "bad_request", "message": "一句话总结不能超过 45 个字符", "field": "一句话总结今天"}}"#)
        case "finalize": (409, #"{"error": {"code": "expired", "message": "日报会话已经过期"}}"#)
        default: (200, detail)
        }
    }
    let s = try await api(hub).reviewSession(id: "daily:2026-10-20")
    #expect(s.material?.sections.first?.blocks == ["- a"])
    #expect(s.rules?.autoFields == ["健康", "财务"])
    #expect(s.delivered == nil)
    #expect(hub.requests.first?.path == "/api/v1/review/sessions/daily:2026-10-20")

    await #expect(throws: HubError.rejected("一句话总结不能超过 45 个字符", field: "一句话总结今天")) {
        _ = try await api(hub).previewReview(id: s.id, content: "x")
    }
    await #expect(throws: HubError.expired) { _ = try await api(hub).finalizeReview(id: s.id, content: "x") }
    #expect(hub.requests[1].body?["content"] as? String == "x")
}

@Test func finalizeReportsAnEarlierConfirmation() async throws {
    let hub = ScriptedHub { _ in (200, #"{"status": "finalized", "memo_name": "memos/9", "already": true}"#) }
    let done = try await api(hub).finalizeReview(id: "daily:2026-10-20", content: "#日报 2026-10-20")
    #expect(done.already == true && done.memoName == "memos/9")
}

@Test func stageWritesSendRawGoalIDsAndDryRun() async throws {
    let hub = ScriptedHub { _ in (200, ##"{"status": "dry-run", "content": "#阶段总结 2026-S4A94\n\n成了"}"##) }
    let result = try await api(hub).closeCycle(id: "2026-S4A94", text: "成了", outcomes: ["2026-S4A94-1a2b3c": "成功"], dryRun: true)
    #expect(result.isDryRun)
    let body = try #require(hub.requests.last?.body)
    #expect((body["outcomes"] as? [String: String]) == ["2026-S4A94-1a2b3c": "成功"])
    #expect(body["dry_run"] as? Bool == true)
    #expect(hub.requests.last?.path == "/api/v1/stage/cycles/2026-S4A94/close")

    _ = try await api(hub).addGoal(cycle: "2026-S5", GoalDraft(domain: "身体", goal: "g", progress: "p", deadline: "2026-12-07", successCriteria: "s", stopSignal: "x"), dryRun: false)
    let goal = try #require(hub.requests.last?.body)
    #expect(goal["success_criteria"] as? String == "s" && goal["stop_signal"] as? String == "x" && goal["dry_run"] as? Bool == false)
}

@Test func newCycleDryRunSurfacesTheConflictMessage() async throws {
    let hub = ScriptedHub { _ in (409, #"{"error": {"code": "conflict", "message": "已有进行中的周期", "field": null}}"#) }
    await #expect(throws: HubError.rejected("已有进行中的周期", field: nil)) { _ = try await api(hub).createCycle(dryRun: true) }
    #expect(hub.requests.last?.body?["dry_run"] as? Bool == true)
    #expect(hub.requests.last?.path == "/api/v1/stage/cycles")
}

@Test func formKeepsTheTemplateAndFillsFields() {
    let template = ReviewSample.dailyTemplate("2026-10-21")
    var form = ReviewForm(template: template)
    #expect(form.header == "#日报 2026-10-21")
    #expect(form.labels == ["一句话总结今天", "情绪", "健康", "财务", "留痕", "未解", "明天唯一重点", "瞬间"])
    #expect(form.content() == template)

    form["一句话总结今天"] = "把复盘入口\n定下来了"
    form["健康"] = "should not be sent"
    form["瞬间"] = "  抬头看到窗外的云  "
    let text = form.content(auto: ["健康", "财务"])
    #expect(text.hasPrefix("#日报 2026-10-21\n一句话总结今天：把复盘入口 定下来了\n\n情绪：\n健康：\n财务："))
    #expect(text.hasSuffix("瞬间：抬头看到窗外的云"))
}

@Test func formChecksMirrorPersonalReview() {
    var form = ReviewForm(template: ReviewSample.dailyTemplate("2026-10-21"))
    let rules = ReviewSample.rules
    #expect(form.issues(rules: rules).map(\.field) == ["一句话总结今天"])

    form["一句话总结今天"] = String(repeating: "长", count: 46)
    #expect(form.issues(rules: rules).map(\.message) == ["一句话总结不能超过 45 个字符"])

    form["一句话总结今天"] = "写代码；开会；跑步"
    form["未解"] = "[a] [b] [c]"
    form["瞬间"] = "看云"
    #expect(form.issues(rules: rules).map(\.field) == ["一句话总结今天", "未解", "瞬间"])

    #expect(ReviewForm.unresolved("") == 0)
    #expect(ReviewForm.unresolved("还没想清楚") == 1)
    #expect(ReviewForm.unresolved("[a] [b]") == 2)
    #expect(ReviewForm.length("é😀") == 2)
}

@Test func reviewSamplesRoundTripThroughTheCache() throws {
    let now = HubJSON.parseDate("2026-10-21T17:58:00+08:00")!
    let data = HubSample.data(now: now)
    let back = try HubJSON.decoder.decode(HubData.self, from: HubJSON.encoder.encode(data))
    #expect(back.goals == data.goals)
    #expect(back.goals?.data?.reviews?.daily?.label == "2026-10-20")
    let session = ReviewSample.session(id: "daily:2026-10-20", now: now)
    #expect(session.status == .open)
    #expect(try HubJSON.decoder.decode(ReviewSession.self, from: HubJSON.encoder.encode(session)) == session)
    #expect(ReviewSample.preview(ReviewForm(template: session.material!.template).content()) == "#日报 2026-10-20\n一句话总结今天：\n\n健康：步数 6842，睡眠 7 小时 12 分\n财务：今日支出 ¥128.50")
}
