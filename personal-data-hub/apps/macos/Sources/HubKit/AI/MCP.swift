import Foundation

/// Arguments of one `tools/call`, read through typed accessors.
public struct MCPArguments: @unchecked Sendable {
    public let raw: [String: Any]

    public init(_ raw: [String: Any]) { self.raw = raw }

    public func string(_ key: String) -> String? {
        (raw[key] as? String).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.flatMap { $0.isEmpty ? nil : $0 }
    }

    public func int(_ key: String) -> Int? {
        if let n = raw[key] as? Int { return n }
        if let d = raw[key] as? Double { return Int(d) }
        return (raw[key] as? String).flatMap(Int.init)
    }

    public func bool(_ key: String) -> Bool? {
        if let b = raw[key] as? Bool { return b }
        return (raw[key] as? String).map { $0 == "true" }
    }
}

public struct MCPToolError: Error, Sendable {
    public var message: String
    public init(_ message: String) { self.message = message }
}

public struct MCPTool: @unchecked Sendable {
    public var name: String
    public var description: String
    public var schema: [String: Any]
    public var run: @Sendable (MCPArguments, MCPSession) async throws -> String

    public init(name: String, description: String, properties: [String: [String: Any]] = [:], required: [String] = [],
                run: @escaping @Sendable (MCPArguments, MCPSession) async throws -> String) {
        self.name = name
        self.description = description
        var schema: [String: Any] = ["type": "object", "properties": properties, "additionalProperties": false]
        if !required.isEmpty { schema["required"] = required }
        self.schema = schema
        self.run = run
    }
}

/// What the server learned from `initialize`.
public final class MCPSession: @unchecked Sendable {
    private let lock = NSLock()
    private var _client: String?

    public init() {}

    public var client: String? {
        get { lock.withLock { _client } }
        set { lock.withLock { _client = newValue } }
    }
}

/// JSON-RPC 2.0 over newline-delimited stdio, the subset of MCP a tools-only server needs.
public final class MCPServer: @unchecked Sendable {
    public static let versions = ["2025-06-18", "2025-03-26", "2024-11-05"]

    public let name: String
    public let version: String
    public let instructions: String
    public let tools: [MCPTool]
    public let session = MCPSession()
    /// Called after every tool call with its name and whether it succeeded; never with arguments.
    public var onCall: (@Sendable (String, Bool) -> Void)?

    public init(name: String, version: String, instructions: String, tools: [MCPTool]) {
        self.name = name
        self.version = version
        self.instructions = instructions
        self.tools = tools
    }

    /// One request line in, at most one response line out (notifications get none).
    public func handle(_ line: String) async -> String? {
        guard let data = line.data(using: .utf8), let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return encode(["jsonrpc": "2.0", "id": NSNull(), "error": ["code": -32700, "message": "Parse error"]])
        }
        guard let method = message["method"] as? String else { return nil }
        let id = message["id"]
        let params = message["params"] as? [String: Any] ?? [:]
        guard let id, !(id is NSNull) else { return nil }

        func result(_ r: [String: Any]) -> String? { encode(["jsonrpc": "2.0", "id": id, "result": r]) }
        func failure(_ code: Int, _ text: String) -> String? { encode(["jsonrpc": "2.0", "id": id, "error": ["code": code, "message": text]]) }

        switch method {
        case "initialize":
            let asked = params["protocolVersion"] as? String
            session.client = (params["clientInfo"] as? [String: Any])?["name"] as? String
            return result([
                "protocolVersion": asked.flatMap { Self.versions.contains($0) ? $0 : nil } ?? Self.versions[0],
                "capabilities": ["tools": ["listChanged": false]],
                "serverInfo": ["name": name, "version": version],
                "instructions": instructions,
            ])
        case "ping":
            return result([:])
        case "tools/list":
            return result(["tools": tools.map { ["name": $0.name, "description": $0.description, "inputSchema": $0.schema] }])
        case "tools/call":
            guard let toolName = params["name"] as? String, let tool = tools.first(where: { $0.name == toolName }) else {
                return failure(-32602, "Unknown tool")
            }
            let args = MCPArguments(params["arguments"] as? [String: Any] ?? [:])
            do {
                let text = try await tool.run(args, session)
                onCall?(toolName, true)
                return result(["content": [["type": "text", "text": text]], "isError": false])
            } catch {
                onCall?(toolName, false)
                let text = (error as? MCPToolError)?.message ?? "工具执行失败"
                return result(["content": [["type": "text", "text": text]], "isError": true])
            }
        default:
            return failure(-32601, "Method not found")
        }
    }

    private func encode(_ object: [String: Any]) -> String? {
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.withoutEscapingSlashes]) else { return nil }
        return String(decoding: data, as: UTF8.self)
    }
}

// MARK: - Pending changes

/// A write an agent asked for. Nothing reaches Google, hub or Memos until the user confirms it in the app.
public struct AIPendingChange: Codable, Equatable, Sendable, Identifiable {
    public enum Kind: Codable, Equatable, Sendable {
        case task(title: String, due: String?, time: String?, notes: String?, list: String?)
        case completeTask(id: String, title: String)
        case memo(content: String, visibility: String)
        case event(title: String, start: Date, end: Date, location: String?, notes: String?)
    }

    public var id: String
    public var createdAt: Date
    public var agent: String?
    public var kind: Kind

    public init(id: String = UUID().uuidString.lowercased(), createdAt: Date = Date(), agent: String?, kind: Kind) {
        self.id = id
        self.createdAt = createdAt
        self.agent = agent
        self.kind = kind
    }
}

/// One file per change, so the MCP process and the app never rewrite each other's data.
public struct AIPendingStore: Sendable {
    public static let limit = 20
    public let dir: URL

    public init(dir: URL) { self.dir = dir }

    public func list() -> [AIPendingChange] {
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return files.filter { $0.pathExtension == "json" }
            .compactMap { try? Data(contentsOf: $0) }
            .compactMap { try? Self.decoder.decode(AIPendingChange.self, from: $0) }
            .sorted { $0.createdAt < $1.createdAt }
    }

    public func add(_ change: AIPendingChange) throws {
        guard list().count < Self.limit else { throw MCPToolError("待确认的变更已有 \(Self.limit) 项，请先让用户在 Personal Hub 里处理") }
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent(change.id + ".json")
        try Self.encoder.encode(change).write(to: file, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }

    public func remove(_ id: String) {
        guard id.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "-" }) else { return }
        try? FileManager.default.removeItem(at: dir.appendingPathComponent(id + ".json"))
    }

    static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        e.outputFormatting = [.sortedKeys]
        return e
    }()

    static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()
}

/// Which tools ran and when; arguments and results are never written.
public struct AIAuditLog: Sendable {
    public let file: URL

    public init(file: URL) { self.file = file }

    public func record(tool: String, ok: Bool, client: String?, at date: Date = Date()) {
        let entry: [String: Any] = ["at": ISO8601DateFormatter().string(from: date), "tool": tool, "ok": ok, "client": client ?? NSNull()]
        guard var line = try? JSONSerialization.data(withJSONObject: entry, options: [.sortedKeys]) else { return }
        line.append(0x0A)
        try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let handle = try? FileHandle(forWritingTo: file) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: line)
        } else {
            try? line.write(to: file, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        }
    }
}
