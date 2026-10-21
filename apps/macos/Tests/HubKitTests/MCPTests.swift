import Foundation
import Testing
@testable import HubKit

private func server() -> MCPServer {
    MCPServer(name: "personal_hub", version: "1", instructions: "hi", tools: [
        MCPTool(name: "echo", description: "", properties: ["text": ["type": "string"]], required: ["text"]) { args, session in
            guard let text = args.string("text") else { throw MCPToolError("缺少 text") }
            return "\(session.client ?? "-"):\(text)"
        },
        MCPTool(name: "boom", description: "") { _, _ in throw CocoaError(.fileNoSuchFile) },
    ])
}

private func object(_ line: String?) throws -> [String: Any] {
    let data = try #require(line?.data(using: .utf8))
    return try #require(try JSONSerialization.jsonObject(with: data) as? [String: Any])
}

@Test func mcpHandshakeListsToolsAndAnswersCalls() async throws {
    let s = server()
    let initialize = try object(await s.handle(#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"codex"}}}"#))
    let result = try #require(initialize["result"] as? [String: Any])
    #expect(result["protocolVersion"] as? String == "2024-11-05")
    #expect((result["serverInfo"] as? [String: Any])?["name"] as? String == "personal_hub")

    #expect(await s.handle(#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#) == nil)

    let list = try object(await s.handle(#"{"jsonrpc":"2.0","id":"a","method":"tools/list"}"#))
    let tools = try #require((list["result"] as? [String: Any])?["tools"] as? [[String: Any]])
    #expect(tools.map { $0["name"] as? String } == ["echo", "boom"])
    #expect((tools[0]["inputSchema"] as? [String: Any])?["required"] as? [String] == ["text"])
    #expect(list["id"] as? String == "a")

    let call = try object(await s.handle(#"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"text":" hi "}}}"#))
    let content = try #require((call["result"] as? [String: Any]))
    #expect(content["isError"] as? Bool == false)
    #expect(((content["content"] as? [[String: Any]])?.first?["text"] as? String) == "codex:hi")
}

@Test func mcpErrorsStayInsideTheProtocol() async throws {
    let s = server()
    var calls: [String] = []
    let lock = NSLock()
    s.onCall = { name, ok in lock.withLock { calls.append("\(name):\(ok)") } }

    let missing = try object(await s.handle(#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"echo","arguments":{}}}"#))
    #expect((missing["result"] as? [String: Any])?["isError"] as? Bool == true)
    let boom = try object(await s.handle(#"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"boom"}}"#))
    let text = ((boom["result"] as? [String: Any])?["content"] as? [[String: Any]])?.first?["text"] as? String
    #expect(text == "工具执行失败")
    #expect(lock.withLock { calls } == ["echo:false", "boom:false"])

    let unknown = try object(await s.handle(#"{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"nope"}}"#))
    #expect((unknown["error"] as? [String: Any])?["code"] as? Int == -32602)
    let method = try object(await s.handle(#"{"jsonrpc":"2.0","id":4,"method":"resources/list"}"#))
    #expect((method["error"] as? [String: Any])?["code"] as? Int == -32601)
    let garbage = try object(await s.handle("not json"))
    #expect((garbage["error"] as? [String: Any])?["code"] as? Int == -32700)
    let newer = try object(await s.handle(#"{"jsonrpc":"2.0","id":5,"method":"initialize","params":{"protocolVersion":"2099-01-01"}}"#))
    #expect((newer["result"] as? [String: Any])?["protocolVersion"] as? String == MCPServer.versions[0])
}

@Test func pendingChangesAreOneFileEachAndCapped() throws {
    let dir = FileManager.default.temporaryDirectory.appendingPathComponent("pending-\(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: dir) }
    let store = AIPendingStore(dir: dir)
    #expect(store.list().isEmpty)

    let first = AIPendingChange(createdAt: Date(timeIntervalSince1970: 100), agent: "codex",
                                kind: .task(title: "写周报", due: "2026-10-22", time: "15:00", notes: nil, list: "工作"))
    let second = AIPendingChange(createdAt: Date(timeIntervalSince1970: 50), agent: nil, kind: .memo(content: "# hi", visibility: "PRIVATE"))
    try store.add(first)
    try store.add(second)
    #expect(store.list().map(\.id) == [second.id, first.id])
    #expect(store.list().last == first)

    store.remove("../" + first.id)
    #expect(store.list().count == 2)
    store.remove(first.id)
    #expect(store.list().map(\.id) == [second.id])

    for i in 0..<(AIPendingStore.limit - 1) {
        try store.add(AIPendingChange(agent: nil, kind: .completeTask(id: "t\(i)", title: "x")))
    }
    #expect(throws: MCPToolError.self) { try store.add(AIPendingChange(agent: nil, kind: .completeTask(id: "over", title: "x"))) }
}

@Test func auditLogAppendsToolNamesOnly() throws {
    let file = FileManager.default.temporaryDirectory.appendingPathComponent("audit-\(UUID().uuidString).jsonl")
    defer { try? FileManager.default.removeItem(at: file) }
    let log = AIAuditLog(file: file)
    log.record(tool: "get_overview", ok: true, client: "codex")
    log.record(tool: "propose_task", ok: false, client: nil)
    let lines = try String(contentsOf: file, encoding: .utf8).split(separator: "\n")
    #expect(lines.count == 2)
    let last = try object(String(lines[1]))
    #expect(last["tool"] as? String == "propose_task")
    #expect(last["ok"] as? Bool == false)
    #expect(Set(last.keys) == ["at", "tool", "ok", "client"])
}
