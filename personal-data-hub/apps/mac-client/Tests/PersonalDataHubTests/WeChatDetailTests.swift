import XCTest
import Foundation
@testable import PersonalDataHub

final class WeChatDetailTests: XCTestCase {
    private func detail(content: String?, channel: String = "wechat") throws -> RecordDetail {
        var raw: [String: Any] = ["channel": channel, "summary": "旧摘要"]
        if let content { raw["message"] = ["record": ["content": content]] }
        let object: [String: Any] = [
            "id": "synthetic", "source": "crm", "kind": "interactions",
            "raw": raw, "normalized": ["content": "列表预览"], "assets": []
        ]
        return try RecordDetail(data: JSONSerialization.data(withJSONObject: object))
    }

    func testSourceBodyPreservesWhitespaceAndLongMarkdownLikeText() throws {
        let original = " \n---\ntitle: 原文\n---\n# *原文*\t\u{0000}" + String(repeating: "字", count: 60000) + "\n "
        let record = try detail(content: original)
        XCTAssertEqual(record.wechatContent, original)
        let exported = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(record.rawJSON.utf8)) as? [String: Any])
        let raw = try XCTUnwrap(exported["raw"] as? [String: Any])
        let message = try XCTUnwrap(raw["message"] as? [String: Any])
        let source = try XCTUnwrap(message["record"] as? [String: Any])
        XCTAssertEqual(source["content"] as? String, original)
    }

    func testEmptySourceBodyDoesNotBecomeSummary() throws {
        XCTAssertEqual(try detail(content: "").wechatContent, "")
    }

    func testLegacyAndOtherChannelsKeepExistingFields() throws {
        let legacy = try detail(content: nil)
        XCTAssertNil(legacy.wechatContent)
        XCTAssertEqual(legacy.fields.first { $0.id == "summary" }?.value, "旧摘要")
        XCTAssertNil(try detail(content: "正文", channel: "email").wechatContent)
    }
}
