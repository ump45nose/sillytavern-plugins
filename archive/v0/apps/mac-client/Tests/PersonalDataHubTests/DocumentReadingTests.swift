import XCTest
import Foundation
@testable import PersonalDataHub

private final class ReadingURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, Data))!
    static var delay: ((URLRequest) -> Double)?
    private var pending: DispatchWorkItem?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, data) = try Self.handler(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!
            let work = DispatchWorkItem { [weak self] in
                guard let self else { return }
                self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                self.client?.urlProtocol(self, didLoad: data)
                self.client?.urlProtocolDidFinishLoading(self)
            }
            pending = work
            DispatchQueue.global().asyncAfter(deadline: .now() + (Self.delay?(request) ?? 0), execute: work)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() { pending?.cancel() }
}

@MainActor
final class DocumentReadingTests: XCTestCase {
    private let id = "synthetic-document"

    private func api() -> HubAPI {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ReadingURLProtocol.self]
        return HubAPI(Connection(endpoint: "https://synthetic.invalid"),
                      session: URLSession(configuration: config), tokenProvider: { "synthetic" })
    }

    private func json(_ value: Any) -> Data { try! JSONSerialization.data(withJSONObject: value) }
    private func fixture(_ key: String) throws -> Data {
        let root = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("docs/client-requirements/m1-api-fixtures.json"))) as! [String: Any]
        return try JSONSerialization.data(withJSONObject: root[key]!)
    }
    private func document(state: String = "ready", revision: Int = 1, summary: String? = "old summary") -> [String: Any] {
        ["id": id, "type": "document", "variant": "note", "schema_version": 1, "revision": revision,
         "source": "memos", "account": "synthetic", "scope_key": "scope", "occurred_at": NSNull(),
         "business_date": NSNull(), "timezone": "Asia/Shanghai", "title": "标题", "preview": "preview",
         "summary": summary.map { $0 as Any } ?? NSNull(), "warnings": [], "coverage": ["body": "complete"],
         "processing": ["state": state, "published_at": NSNull()], "content": "/blocks", "evidence": "/evidence",
         "match": NSNull(), "metadata": ["format": "markdown", "empty": false], "assets": []]
    }
    private func blocks(_ values: [(Int, String)], revision: Int = 1, next: Int? = nil) -> [String: Any] {
        ["id": id, "revision": revision, "blocks": values.map { ["key": "body:\($0.0)", "ordinal": $0.0,
            "type": "markdown", "text": $0.1, "refs": [], "metadata": ["continuation": true]] },
         "next_after": next.map { $0 as Any } ?? NSNull()]
    }
    private func response(_ value: Any, _ status: Int = 200) -> (Int, Data) { (status, json(value)) }

    func testSyntheticFixtureDecodesAndPreservesContract() throws {
        let page = try JSONDecoder().decode(DocumentPage.self, from: fixture("list"))
        XCTAssertEqual(page.schema_version, 1)
        let item = try XCTUnwrap(page.items.first)
        XCTAssertEqual(item.variant, "daily_review"); XCTAssertTrue(item.supported); XCTAssertTrue(item.ready)
        let detail = try JSONDecoder().decode(DocumentContent.self, from: fixture("detail"))
        XCTAssertEqual(detail.metadata?.body_chars, 36); XCTAssertEqual(detail.assets?.count, 1)
        let evidence = try JSONDecoder().decode(DocumentEvidence.self, from: fixture("evidence"))
        XCTAssertEqual(evidence.revision, 1); XCTAssertTrue(evidence.inputs[0].current_matches)
        _ = try JSONDecoder().decode(DocumentPage.self, from: fixture("search"))
        _ = try JSONDecoder().decode(DocumentBlocks.self, from: fixture("blocks"))
        _ = try JSONDecoder().decode(ProcessingStatus.self, from: fixture("processing_status"))
    }

    func testBlocksJoinWithoutSeparatorsAndReachTailBeyondFifty() async throws {
        let values = (0..<56).map { ($0, $0 == 0 ? "# 标题\n\n👩🏽‍💻e\u{301}\n**" : $0 == 54 ? "边界中" : $0 == 55 ? "文尾部**\n末尾" : "x") }
        ReadingURLProtocol.handler = { request in
            if request.url!.path.hasSuffix("/blocks") {
                let after = Int(URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!.first { $0.name == "after" }!.value!)!
                XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer synthetic")
                let start = after + 1; let end = min(start + 8, 55)
                return self.response(self.blocks(Array(values[start...end]), next: end == 55 ? nil : end))
            }
            return self.response(self.document())
        }
        var value = document(); value["match"] = ["ordinal": 54, "excerpt": "边界中文尾部"]
        let reader = DocumentReader(); let item = try JSONDecoder().decode(DocumentContent.self, from: json(value))
        await reader.open(DocumentSelection(item: item, query: "中文尾部"), api: api())
        XCTAssertEqual(reader.body, values.map(\.1).joined())
        XCTAssertTrue(reader.matchResolved); XCTAssertTrue(reader.complete)
        XCTAssertEqual(reader.blocks.count, 56)
        let offset = try XCTUnwrap(reader.matchOffset)
        XCTAssertEqual(offset, values.prefix(54).map(\.1).joined().unicodeScalars.count + 2)
        XCTAssertTrue(DocumentMarkdown.paragraphs(reader.body).contains { $0.sourceOffsets?.contains(offset) == true && $0.plain.contains("中文尾部") })
    }

    func testNextAfterIsUsedIndependentlyOfPageLength() async throws {
        var requested: [String] = []
        ReadingURLProtocol.handler = { request in
            if request.url!.path.hasSuffix("/blocks") {
                let q = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
                requested.append(q.first { $0.name == "after" }!.value!)
                return requested.count == 1 ? self.response(self.blocks([(0, "a")], next: 0)) : self.response(self.blocks([(1, "b")]))
            }
            return self.response(self.document())
        }
        let reader = DocumentReader(); let item = try JSONDecoder().decode(DocumentContent.self, from: json(document()))
        await reader.open(DocumentSelection(item: item, query: ""), api: api()); await reader.loadNext()
        XCTAssertEqual(requested, ["-1", "0"]); XCTAssertEqual(reader.body, "ab"); XCTAssertTrue(reader.complete)
    }

    func testListCursorAndDeduplicationAndQueryReset() async throws {
        var queries: [[String: String]] = []
        ReadingURLProtocol.handler = { request in
            let qs = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
            queries.append(Dictionary(uniqueKeysWithValues: qs.map { ($0.name, $0.value ?? "") }))
            let item = self.document(); return self.response(["schema_version": 1, "items": [item], "next_cursor": "opaque"])
        }
        let model = DocumentListModel(); await model.load(api: api(), filter: DocumentFilter(query: "一"))
        await model.load(api: api(), filter: DocumentFilter(query: "一"), reset: false)
        await model.load(api: api(), filter: DocumentFilter(query: "二"))
        XCTAssertEqual(model.items.count, 1); XCTAssertEqual(queries[1]["cursor"], "opaque")
        XCTAssertNil(queries[2]["cursor"]); XCTAssertEqual(queries[2]["query"], "二")
    }

    func testStaleAndUnknownSchemaDoNotReadBody() throws {
        for state in ["pending", "running", "stale", "failed"] {
            var value = document(state: state); let decoded = try JSONDecoder().decode(DocumentContent.self, from: json(value))
            XCTAssertFalse(decoded.readable, state)
            value["schema_version"] = 99
            XCTAssertFalse(try JSONDecoder().decode(DocumentContent.self, from: json(value)).supported)
        }
        let zero = document(revision: 0); XCTAssertFalse(try JSONDecoder().decode(DocumentContent.self, from: json(zero)).readable)
        var missing = document(); missing.removeValue(forKey: "metadata")
        XCTAssertFalse(try JSONDecoder().decode(DocumentContent.self, from: json(missing)).readable)
        missing["metadata"] = ["format": "html"]
        XCTAssertFalse(try JSONDecoder().decode(DocumentContent.self, from: json(missing)).readable)
    }

    func testChangedAndRemovedClearDerivedStateButNetworkFailureDoesNotClaimRemoval() async throws {
        var mode = "ok"
        ReadingURLProtocol.handler = { request in
            if mode == "network" { throw URLError(.notConnectedToInternet) }
            if mode == "removed" { return self.response(["detail": "content_removed"], 404) }
            if mode == "changed" { return self.response(["detail": "content_changed"], 409) }
            if request.url!.path.hasSuffix("/blocks") { return self.response(self.blocks([(0, "正文")], next: 0)) }
            return self.response(self.document())
        }
        let reader = DocumentReader(); let item = try JSONDecoder().decode(DocumentContent.self, from: json(document()))
        await reader.open(DocumentSelection(item: item, query: ""), api: api()); XCTAssertEqual(reader.body, "正文")
        mode = "network"; await reader.verifyCurrent()
        XCTAssertFalse(reader.removed); XCTAssertEqual(reader.body, "正文"); XCTAssertNotNil(reader.verificationError)
        mode = "changed"; await reader.loadNext(); XCTAssertTrue(reader.body.isEmpty); XCTAssertFalse(reader.removed)
        mode = "removed"; await reader.reload(); XCTAssertTrue(reader.removed); XCTAssertTrue(reader.body.isEmpty)
        mode = "network"; await reader.reload(); XCTAssertFalse(reader.removed)
    }

    func testEvidenceRevisionMismatchAndMarkdownHighlight() async throws {
        ReadingURLProtocol.handler = { request in
            if request.url!.path.hasSuffix("/evidence") { return self.response(["id": self.id, "revision": 2, "inputs": []]) }
            if request.url!.path.hasSuffix("/blocks") { return self.response(self.blocks([(0, "正文")])) }
            return self.response(self.document())
        }
        let reader = DocumentReader(); let item = try JSONDecoder().decode(DocumentContent.self, from: json(document()))
        await reader.open(DocumentSelection(item: item, query: ""), api: api()); await reader.loadEvidence()
        XCTAssertNil(reader.evidence); XCTAssertEqual(reader.body, "正文")
        let paragraphs = DocumentMarkdown.paragraphs("# 标题\n\n- 项目\n\n> 引用\n\n[链接](https://example.invalid)")
        XCTAssertEqual(paragraphs.first?.heading, 1); XCTAssertEqual(paragraphs[1].marker, "•"); XCTAssertTrue(paragraphs[2].quoted)
        XCTAssertTrue(paragraphs.last!.text.runs.contains { $0.link?.absoluteString == "https://example.invalid" })
        let highlighted = highlightedText("中文命中", query: "命中")
        XCTAssertTrue(highlighted.runs.contains { $0.backgroundColor != nil })
    }

    private func query(_ request: URLRequest) -> [String: String] {
        Dictionary(uniqueKeysWithValues: (URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems ?? []).map { ($0.name, $0.value ?? "") })
    }
    func testRapidObjectAndQuerySwitchIgnoreDelayedResponses() async throws {
        let started = expectation(description: "old detail requested")
        ReadingURLProtocol.delay = { $0.url!.path.hasSuffix("/old") ? 0.15 : 0 }
        defer { ReadingURLProtocol.delay = nil }
        ReadingURLProtocol.handler = { request in
            if request.url!.path.hasSuffix("/old") { started.fulfill() }
            var value = request.url!.path.hasSuffix("/blocks") ? self.blocks([(0, "新正文")]) : self.document()
            value["id"] = request.url!.path.hasSuffix("/old") ? "old" : "new"
            return self.response(value)
        }
        var old = document(); old["id"] = "old"
        var new = document(); new["id"] = "new"
        let oldItem = try JSONDecoder().decode(DocumentContent.self, from: json(old))
        let newItem = try JSONDecoder().decode(DocumentContent.self, from: json(new))
        let reader = DocumentReader()
        let oldRequest = Task { await reader.open(DocumentSelection(item: oldItem, query: ""), api: api()) }
        await fulfillment(of: [started], timeout: 2)
        await reader.open(DocumentSelection(item: newItem, query: ""), api: api()); await oldRequest.value
        XCTAssertEqual(reader.header?.id, "new"); XCTAssertEqual(reader.body, "新正文")

        let queryStarted = expectation(description: "old query requested")
        ReadingURLProtocol.delay = { self.query($0)["query"] == "old" ? 0.15 : 0 }
        ReadingURLProtocol.handler = { request in
            let isOld = self.query(request)["query"] == "old"
            if isOld { queryStarted.fulfill() }
            var value = self.document(); value["id"] = isOld ? "old" : "new"
            return self.response(["schema_version": 1, "items": [value], "next_cursor": isOld ? "old-cursor" as Any : NSNull()])
        }
        let list = DocumentListModel()
        let oldQuery = Task { await list.load(api: api(), filter: DocumentFilter(query: "old")) }
        await fulfillment(of: [queryStarted], timeout: 2)
        await list.load(api: api(), filter: DocumentFilter(query: "new")); await oldQuery.value
        XCTAssertEqual(list.items.map(\.id), ["new"]); XCTAssertNil(list.cursor)
    }
    func testVersionConflictReplacesSummaryAssetsAndEvidenceThenLiveStaleClearsBody() async throws {
        var revision = 1; var state = "ready"
        ReadingURLProtocol.handler = { request in
            if request.url!.path.hasSuffix("/blocks") {
                if self.query(request)["revision"] != String(revision) { return self.response(["detail": "content_changed"], 409) }
                return self.response(self.blocks([(0, "正文\(revision)")], revision: revision, next: revision == 1 ? 0 : nil))
            }
            if request.url!.path.hasSuffix("/evidence") { return self.response(["id": self.id, "revision": revision, "inputs": []]) }
            var value = self.document(state: state, revision: revision, summary: "摘要\(revision)")
            value["assets"] = revision == 1 ? [["id": "old-asset", "name": "old.txt", "size": 1, "media_type": "text/plain"]] : []
            return self.response(value)
        }
        let reader = DocumentReader(); let item = try JSONDecoder().decode(DocumentContent.self, from: json(document()))
        await reader.open(DocumentSelection(item: item, query: ""), api: api()); await reader.loadEvidence()
        XCTAssertNotNil(reader.evidence); XCTAssertEqual(reader.header?.assets?.count, 1)
        revision = 2; await reader.loadNext()
        XCTAssertEqual(reader.body, "正文2"); XCTAssertEqual(reader.header?.summary, "摘要2")
        XCTAssertEqual(reader.header?.assets?.count, 0); XCTAssertNil(reader.evidence)
        state = "stale"; await reader.verifyCurrent()
        XCTAssertTrue(reader.body.isEmpty); XCTAssertNil(reader.evidence); XCTAssertNil(reader.nextAfter)
        XCTAssertFalse(reader.complete)
    }
    func testSearchOrdinalTargetsLaterOccurrenceAndEmptyBodyIsExplicitlyComplete() async throws {
        var texts = [(0, "命中\n\n"), (1, "深层命中")]
        ReadingURLProtocol.handler = { request in
            request.url!.path.hasSuffix("/blocks") ? self.response(self.blocks(texts)) : self.response(self.document())
        }
        var value = document(); value["match"] = ["ordinal": 1, "excerpt": "深层命中"]
        let reader = DocumentReader(); await reader.open(DocumentSelection(item: try JSONDecoder().decode(DocumentContent.self, from: json(value)), query: "命中"), api: api())
        XCTAssertTrue(reader.matchResolved); XCTAssertEqual(reader.matchOffset, 6)
        texts = []; await reader.reload()
        XCTAssertTrue(reader.complete); XCTAssertEqual(reader.body, "")
    }
}
