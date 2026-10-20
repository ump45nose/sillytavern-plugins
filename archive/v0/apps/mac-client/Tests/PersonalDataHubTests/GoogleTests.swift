import XCTest
import Foundation
@testable import PersonalDataHub

final class MockGoogleProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (Int, [String: Any]))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, value) = try Self.handler!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: [:])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: try JSONSerialization.data(withJSONObject: value))
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}
final class GoogleTests: XCTestCase {
    static func body(_ request: URLRequest) throws -> [String: Any] {
        var data = request.httpBody ?? Data()
        if data.isEmpty, let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }
            var bytes = [UInt8](repeating: 0, count: 4096)
            while true { let count = stream.read(&bytes, maxLength: bytes.count); if count <= 0 { break }; data.append(contentsOf: bytes.prefix(count)) }
        }
        return try JSONSerialization.jsonObject(with: data) as! [String: Any]
    }
    func client() -> GoogleClient {
        let cfg = URLSessionConfiguration.ephemeral; cfg.protocolClasses = [MockGoogleProtocol.self]
        return GoogleClient(session: URLSession(configuration: cfg), accessToken: "synthetic")
    }
    func testTaskDateAndConflictAndNoRetry() async throws {
        var count = 0
        MockGoogleProtocol.handler = { request in
            count += 1
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer synthetic")
            let body = try Self.body(request)
            XCTAssertEqual(body["due"] as? String, "2026-10-06T00:00:00.000Z")
            XCTAssertEqual(URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "parent")
            return (200, ["id": "new"])
        }
        let c = client()
        try await c.saveTask(nil, list: "list", title: "task", notes: "notes", due: "2026-10-06", parent: "parent")
        XCTAssertEqual(count, 1)
        let task = GoogleTask(["id":"one","etag":"version1","title":"original"], list: "list")
        count = 0
        MockGoogleProtocol.handler = { request in
            count += 1; XCTAssertEqual(request.value(forHTTPHeaderField: "If-Match"), "version1")
            return (412, [:])
        }
        do { try await c.saveTask(task, list:"list", title:"edited", notes:"", due:""); XCTFail() }
        catch GoogleError.conflict {}
        XCTAssertEqual(count,1)
    }
    func testAllDayCalendarAndCreationID() async throws {
        let c = client()
        MockGoogleProtocol.handler = { request in
            let b = try Self.body(request)
            XCTAssertEqual(b["id"] as? String, "abc123")
            XCTAssertNotNil((b["start"] as? [String: String])?["date"])
            XCTAssertNil((b["start"] as? [String: String])?["dateTime"])
            XCTAssertEqual(b["recurrence"] as? [String], ["RRULE:FREQ=WEEKLY"])
            XCTAssertNil(b["attendees"])
            return (200, ["id":"abc123"])
        }
        try await c.saveEvent(nil, calendar:"primary", title:"personal", notes:"", location:"", start:Date(timeIntervalSince1970:1791244800), end:Date(timeIntervalSince1970:1791331200), allDay:true, zone:"Asia/Shanghai", recurrence:"FREQ=WEEKLY", series:false, creationID:"abc123")
    }
    func testUnauthorizedAndGuestsAreNotEdited() async throws {
        let c = client(); var count = 0
        MockGoogleProtocol.handler = { _ in count += 1; return (401, [:]) }
        do { _ = try await c.snapshot(date: Date(), days:1); XCTFail() } catch GoogleError.unauthorized {}
        XCTAssertEqual(count,1)
        let event = GoogleEvent(["id":"e","attendees":[["email":"synthetic@example.invalid"]]], calendar:"primary")
        do { try await c.deleteEvent(event,series:false); XCTFail() } catch GoogleError.invalid {}
        XCTAssertEqual(count,1)
    }
    func testCalendarConcurrentVersion() async throws {
        let c = client()
        let event = GoogleEvent(["id":"e","etag":"old","start":["date":"2026-10-06"],"end":["date":"2026-10-07"]],calendar:"primary")
        var count = 0
        MockGoogleProtocol.handler = { req in count += 1; XCTAssertEqual(req.httpMethod,"GET"); XCTAssertEqual(req.cachePolicy, .reloadIgnoringLocalCacheData); return (200,["etag":"new"]) }
        do {
            try await c.saveEvent(event,calendar:"primary",title:"updated",notes:"",location:"",start:Date(),end:Date().addingTimeInterval(3600),allDay:false,zone:"Asia/Shanghai",recurrence:"",series:false,creationID:"")
            XCTFail()
        } catch GoogleError.conflict {}
        XCTAssertEqual(count,1)
    }
    func testNextEventDoesNotStopAtMidnight() async throws {
        let c = client(); var count = 0
        MockGoogleProtocol.handler = { request in
            count += 1
            let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
            XCTAssertNil(query.first { $0.name == "timeMax" })
            XCTAssertEqual(query.first { $0.name == "maxResults" }?.value, "1")
            return (200, ["items": [["id": "future", "start": ["date": "2030-01-01"], "end": ["date": "2030-01-02"]]]])
        }
        let next = try await c.nextEvent(calendars: [GoogleCalendar(id:"owned",title:"personal",owned:true,primary:true),GoogleCalendar(id:"shared",title:"shared",owned:false,primary:false)])
        XCTAssertEqual(next?.eventID,"future"); XCTAssertEqual(count,1)
    }
}
