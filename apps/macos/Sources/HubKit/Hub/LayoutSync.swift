import Foundation

/// hub-api's stored layout (§5.5): the document is kept verbatim for every device.
public struct RemoteLayout: Decodable, Equatable, Sendable {
    public var version: Int
    public var updatedAt: String?
    /// nil when this build cannot read the stored document (an unknown module or a newer format).
    public var document: LayoutDocument?

    public init(version: Int, updatedAt: String? = nil, document: LayoutDocument?) {
        self.version = version
        self.updatedAt = updatedAt
        self.document = document
    }

    private enum CodingKeys: String, CodingKey { case version, updatedAt, document }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = try c.decode(Int.self, forKey: .version)
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
        let doc = try? c.decodeIfPresent(LayoutDocument.self, forKey: .document)
        document = doc?.version == LayoutDocument.currentVersion && doc?.pages.isEmpty == false ? doc : nil
    }
}

public enum LayoutWrite: Equatable, Sendable {
    case saved(Int)
    case conflict(RemoteLayout?)
}

/// Persisted next to the layout: the hub version last read or written, and whether local edits are unsent.
public struct LayoutSyncState: Codable, Equatable, Sendable {
    public var version = 0
    public var dirty = false

    public init(version: Int = 0, dirty: Bool = false) {
        self.version = version
        self.dirty = dirty
    }
}

public enum LayoutSync {
    public struct Outcome: Equatable, Sendable {
        /// A layout from another device to show instead of the local one.
        public var adopt: LayoutDocument?
        public var state: LayoutSyncState
    }

    /// One round. Unsent local edits win (a single person edits one device at a time); otherwise a newer
    /// hub layout is adopted. A stored document this build cannot read is never overwritten.
    public static func run(api: HubAPI, local: LayoutDocument, state: LayoutSyncState) async throws -> Outcome {
        var s = state
        if s.dirty { return try await push(api, local, s, base: s.version) }
        guard let remote = try await api.layout() else { return try await push(api, local, s, base: 0) }
        guard remote.version != s.version, let doc = remote.document else { return Outcome(state: s) }
        // First contact from a Mac whose layout was already customized: keep the Mac's.
        if s.version == 0, local != .default, doc != local { return try await push(api, local, s, base: remote.version) }
        s.version = remote.version
        return Outcome(adopt: doc == local ? nil : doc, state: s)
    }

    private static func push(_ api: HubAPI, _ local: LayoutDocument, _ state: LayoutSyncState, base: Int) async throws -> Outcome {
        var s = state
        s.dirty = true
        var version = base
        for _ in 0..<2 {
            switch try await api.putLayout(local, version: version) {
            case .saved(let v):
                return Outcome(state: LayoutSyncState(version: v, dirty: false))
            case .conflict(let current):
                if let current, current.document == nil { return Outcome(state: s) }
                version = current?.version ?? 0
            }
        }
        return Outcome(state: s)
    }
}
