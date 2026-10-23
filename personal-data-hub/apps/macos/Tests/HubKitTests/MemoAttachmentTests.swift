import Foundation
import Testing
@testable import HubKit

private func api(_ hub: ScriptedHub) -> HubAPI {
    HubAPI(transport: hub, credential: HubCredential(baseURL: URL(string: "http://hub.test")!, token: "t"))
}

@Test func attachmentsUploadAsOneMultipartFileAndLinkOnCreate() async throws {
    let hub = ScriptedHub { r in
        switch (r.httpMethod ?? "GET", r.url!.path) {
        case ("POST", "/api/v1/memos/attachments"):
            let type = r.value(forHTTPHeaderField: "Content-Type") ?? ""
            let boundary = type.components(separatedBy: "boundary=").last ?? "-"
            let body = String(decoding: r.httpBody ?? Data(), as: UTF8.self)
            let ok = type.hasPrefix("multipart/form-data") && body.hasPrefix("--\(boundary)\r\n")
                && body.contains(#"name="file"; filename="白板'1'.png""#) && body.contains("Content-Type: image/png\r\n\r\nPNGBYTES\r\n")
                && body.hasSuffix("--\(boundary)--\r\n")
            return ok ? (201, #"{"name": "attachments/xyz", "filename": "白板.png", "type": "image/png", "size": 8}"#) : (400, "{}")
        case ("POST", "/api/v1/memos"): return (201, #"{"id": "memos/new"}"#)
        case ("DELETE", "/api/v1/memos/attachments/xyz"): return (204, "")
        default: return (404, "{}")
        }
    }
    let up = try await api(hub).uploadMemoAttachment(Data("PNGBYTES".utf8), filename: "白板\"1\".png", type: "image/png")
    #expect(up.name == "attachments/xyz" && up.size == 8)
    _ = try await api(hub).createMemo(content: "看图", attachments: [up.name])
    #expect(hub.requests.last?.body?["attachments"] as? [String] == ["attachments/xyz"])
    _ = try await api(hub).createMemo(content: "无附件")
    #expect(hub.requests.last?.body?["attachments"] == nil)
    try await api(hub).deleteMemoAttachment(name: up.name)
    #expect(hub.requests.last?.path == "/api/v1/memos/attachments/xyz")
}

@Test func oversizedUploadsShowHubsLimit() async {
    let hub = ScriptedHub { _ in (413, #"{"detail": "文件超过 32 MB"}"#) }
    await #expect(throws: HubError.rejected("文件超过 32 MB", field: nil)) {
        _ = try await api(hub).uploadMemoAttachment(Data(), filename: "a.mov", type: "video/quicktime")
    }
    let bare = ScriptedHub { _ in (413, "") }
    await #expect(throws: HubError.http(413)) {
        _ = try await api(bare).uploadMemoAttachment(Data(), filename: "a.mov", type: "video/quicktime")
    }
}
