import Foundation

/// Persists the layout as JSON. A missing or unreadable file falls back to the default layout;
/// an unreadable file is kept aside instead of being overwritten.
public struct LayoutStore: Sendable {
    public let url: URL

    public init(url: URL) {
        self.url = url
    }

    public static func appSupport(_ fileManager: FileManager = .default) -> LayoutStore {
        let base = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return LayoutStore(url: base.appendingPathComponent("PersonalHub/layout.json"))
    }

    public func load() -> LayoutDocument {
        guard let data = try? Data(contentsOf: url) else { return .default }
        if let doc = try? JSONDecoder().decode(LayoutDocument.self, from: data),
           doc.version == LayoutDocument.currentVersion {
            return doc
        }
        let aside = url.deletingPathExtension().appendingPathExtension("unreadable-\(Int(Date().timeIntervalSince1970)).json")
        try? FileManager.default.moveItem(at: url, to: aside)
        return .default
    }

    public func save(_ doc: LayoutDocument) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(doc).write(to: url, options: .atomic)
    }
}
