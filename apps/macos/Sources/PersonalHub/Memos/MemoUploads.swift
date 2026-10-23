import AppKit
import HubKit
import Observation
import SwiftUI
import UniformTypeIdentifiers

/// Files picked, pasted or dropped into the composer. Each uploads right away and is linked when the memo is sent;
/// removing one before sending deletes it from Memos.
@MainActor @Observable
final class MemoUploads {
    struct Item: Identifiable {
        enum Phase: Equatable { case uploading, done(String), failed(String) }
        let id = UUID()
        var filename: String
        var type: String
        var size: Int
        var preview: NSImage?
        var phase: Phase = .uploading
    }

    private(set) var items: [Item] = []

    /// Read into memory before sending, so very large files are refused up front; hub enforces Memos' own limit.
    static let limit = 64 << 20

    var uploading: Bool { items.contains { $0.phase == .uploading } }
    var names: [String] { items.compactMap { if case let .done(name) = $0.phase { name } else { nil } } }

    init(_ items: [Item] = []) { self.items = items }

    /// Files first; a bare image (a screenshot, a copied picture) only when there is no text to paste instead.
    func take(_ pb: NSPasteboard, store: MemosStore) -> Bool {
        let urls = (pb.readObjects(forClasses: [NSURL.self], options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? [])
            .filter { !$0.hasDirectoryPath }
        if !urls.isEmpty {
            add(urls, store: store)
            return true
        }
        guard pb.string(forType: .string) == nil, let type = pb.availableType(from: [.png, .tiff]), let data = pb.data(forType: type),
              let png = type == .png ? data : NSBitmapImageRep(data: data)?.representation(using: .png, properties: [:]) else { return false }
        let stamp = Date().formatted(.dateTime.year().month(.twoDigits).day(.twoDigits).hour(.twoDigits(amPM: .omitted)).minute(.twoDigits).second(.twoDigits))
        start(Item(filename: "截图 \(stamp).png", type: "image/png", size: png.count, preview: NSImage(data: png)), bytes: { png }, store: store)
        return true
    }

    func pick(store: MemosStore) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false
        panel.message = "选择要附加到 Memo 的文件"
        panel.begin { [weak self] response in
            guard response == .OK else { return }
            MainActor.assumeIsolated { self?.add(panel.urls, store: store) }
        }
    }

    func add(_ urls: [URL], store: MemosStore) {
        for url in urls {
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            let type = UTType(filenameExtension: url.pathExtension)?.preferredMIMEType ?? "application/octet-stream"
            var item = Item(filename: url.lastPathComponent, type: type, size: size,
                            preview: type.hasPrefix("image/") ? NSImage(byReferencing: url) : nil)
            guard size <= Self.limit else {
                item.phase = .failed("超过 \(Self.limit >> 20) MB，没有上传")
                items.append(item)
                continue
            }
            start(item, bytes: { try? Data(contentsOf: url) }, store: store)
        }
    }

    func remove(_ item: Item, store: MemosStore) {
        items.removeAll { $0.id == item.id }
        if case let .done(name) = item.phase { Task { await store.discard(attachment: name) } }
    }

    /// After the memo is sent; the uploads now belong to it.
    func clear() { items = [] }

    private func start(_ item: Item, bytes: @escaping @Sendable () -> Data?, store: MemosStore) {
        items.append(item)
        let id = item.id
        Task {
            guard let data = await Task.detached(priority: .userInitiated, operation: bytes).value else {
                set(id, .failed("读不了这个文件"))
                return
            }
            do {
                let uploaded = try await store.upload(data, filename: item.filename, type: item.type)
                if items.contains(where: { $0.id == id }) {
                    set(id, .done(uploaded.name))
                } else {
                    await store.discard(attachment: uploaded.name)
                }
            } catch {
                set(id, .failed(error.localizedDescription))
            }
        }
    }

    private func set(_ id: UUID, _ phase: Item.Phase) {
        if let i = items.firstIndex(where: { $0.id == id }) { items[i].phase = phase }
    }
}

/// A file waiting in the composer: thumbnail or document glyph, name, size or upload state, remove button.
struct MemoUploadCard: View {
    var item: MemoUploads.Item
    var onRemove: () -> Void

    var body: some View {
        HStack(spacing: 9) {
            ZStack {
                RoundedRectangle(cornerRadius: 7).fill(Palette.sunk)
                if let preview = item.preview {
                    Image(nsImage: preview).resizable().scaledToFill()
                } else {
                    Image(systemName: "doc").font(.system(size: 13)).foregroundStyle(Palette.ink3)
                }
            }
            .frame(width: 34, height: 34)
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay { if item.phase == .uploading { RoundedRectangle(cornerRadius: 7).fill(Palette.card.opacity(0.55)) } }
            VStack(alignment: .leading, spacing: 2) {
                Text(item.filename).font(Typo.sans(12)).foregroundStyle(Palette.ink).lineLimit(1).truncationMode(.middle)
                Text(caption).font(Typo.sans(10.5)).foregroundStyle(failed ? Tone.rose.color : Palette.ink3).lineLimit(1)
            }
            .frame(maxWidth: 170, alignment: .leading)
            Button(action: onRemove) {
                Image(systemName: "xmark").font(.system(size: 9, weight: .bold)).foregroundStyle(Palette.ink3)
                    .frame(width: 18, height: 18).contentShape(Rectangle())
            }
            .buttonStyle(.plain).help("移除")
        }
        .padding(.leading, 6).padding(.trailing, 6).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.card))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(failed ? Tone.rose.color.opacity(0.4) : Palette.line))
    }

    private var failed: Bool { if case .failed = item.phase { true } else { false } }

    private var caption: String {
        let size = ByteCountFormatter.string(fromByteCount: Int64(item.size), countStyle: .file)
        return switch item.phase {
        case .uploading: "上传中… · \(size)"
        case .done: size
        case .failed(let message): message
        }
    }
}
