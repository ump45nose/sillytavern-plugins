import Foundation
import Testing
@testable import HubKit

@Test func transcriptTurnsInEveryPlaudFormat() {
    let md = """
    ## 摘要

    **决定**：先迁健康。
    第二行接着上一段。

    - 要点一
    1. 要点二

    [00:12] 【他人】可以先切。
    [00:31] 【我】：那账单一起。
    - [00:44] Speaker 1：交流先别动。
    [1:02:03] Speaker 2: 好。

    **00:01:10 Speaker 3**

    回滚预案我来写。
    周五前发。

    **00:02:00 Speaker 1**
    收到。

    > 决定：本周切换。
    ---
    """
    let blocks = Transcript.parse(md)
    #expect(blocks == [
        .heading(level: 2, text: "摘要"),
        .paragraph("**决定**：先迁健康。\n第二行接着上一段。"),
        .bullet("要点一"), .bullet("要点二"),
        .turn(speaker: "他人", time: "00:12", text: "可以先切。"),
        .turn(speaker: "我", time: "00:31", text: "那账单一起。"),
        .turn(speaker: "Speaker 1", time: "00:44", text: "交流先别动。"),
        .turn(speaker: "Speaker 2", time: "1:02:03", text: "好。"),
        .turn(speaker: "Speaker 3", time: "00:01:10", text: "回滚预案我来写。\n周五前发。"),
        .turn(speaker: "Speaker 1", time: "00:02:00", text: "收到。"),
        .quote("决定：本周切换。"),
        .rule,
    ])
    #expect(Transcript.speakers(blocks) == ["他人", "我", "Speaker 1", "Speaker 2", "Speaker 3"])
    #expect(Transcript.isSelf("我?") && !Transcript.isSelf("他人"))
}

@Test func plaudListDecodesSnakeCase() throws {
    let json = #"{"days":[{"date":"2026-10-21","recordings":[{"id":"plaud:2026-10-21:ab","title":"周会","start_at":"2026-10-21T10:05:00+08:00","duration_seconds":3240}],"has_transcript":true,"people":["李雷"]}],"next_before":"2026-10-21"}"#
    let list = try HubJSON.decoder.decode(PlaudList.self, from: Data(json.utf8))
    #expect(list.nextBefore == "2026-10-21")
    #expect(list.days[0].recordings[0].durationSeconds == 3240 && list.days[0].recordings[0].startAt != nil)
}
