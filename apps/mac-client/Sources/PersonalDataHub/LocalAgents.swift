import Foundation
import AppKit

struct AgentStatus: Identifiable {
    let id: String
    let name: String
    let loaded: Bool
    let running: Bool
    let exitCode: Int?
    let checkedAt: Date
    var state: String {
        if !loaded { return "未加载" }
        if running { return "后台运行" }
        if let code = exitCode, code != 0 { return "上次同步失败（\(code)）" }
        return "等待下次同步"
    }
}

enum LocalAgents {
    static func installBundled(statusOnly: Bool = false) throws {
        guard let resources = Bundle.main.resourceURL,
              FileManager.default.fileExists(atPath: resources.appendingPathComponent("collection.json").path) else {
            throw CollectionFailure.unavailable
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [resources.appendingPathComponent("install-agents.py").path, "--app", Bundle.main.bundleURL.path] + (statusOnly ? ["--status"] : [])
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        try process.run(); process.waitUntilExit()
        if process.terminationStatus == 2 { throw CollectionFailure.authorizationRequired }
        guard process.terminationStatus == 0 else { throw CollectionFailure.installationFailed }
    }

    static func prepareBundledIfNeeded() throws {
        guard let resources = Bundle.main.resourceURL,
              FileManager.default.fileExists(atPath: resources.appendingPathComponent("collection.json").path) else { throw CollectionFailure.unavailable }
        // The installer checks actual launch arguments as well as its receipt.
        // Repeated checks are idempotent and do not restart healthy jobs.
        try installBundled()
    }

    @MainActor static func openAuthorizationSettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") { NSWorkspace.shared.open(url) }
    }

    static let labels = [
        ("com.yuwk.personal-review-skysight", "电脑活动同步"),
        ("com.personal-crm.wechat", "微信采集"),
        ("com.yuwk.personal-data-hub-network", "本机网络采集")
    ]
    static func configureNetwork(enabled: Bool) throws {
        guard let resources = Bundle.main.resourceURL else { throw CollectionFailure.unavailable }
        let process = Process(); process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [resources.appendingPathComponent("install-agents.py").path, "--app", Bundle.main.bundleURL.path, "--network", enabled ? "enable" : "disable"]
        process.standardOutput = FileHandle.nullDevice; process.standardError = FileHandle.nullDevice
        try process.run(); process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw CollectionFailure.installationFailed }
    }
    static func networkStatus() -> NetworkCollectionStatus? {
        let folder = Connection.directory.appendingPathComponent("Network")
        let value = (try? Data(contentsOf: folder.appendingPathComponent("status.json"))).flatMap { try? JSONDecoder().decode(NetworkCollectionStatus.self, from: $0) }
        guard let data = try? Data(contentsOf: folder.appendingPathComponent("config.json")),
              let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var result = value ?? NetworkCollectionStatus()
        result.enabled = config["enabled"] as? Bool ?? false
        return result
    }
    static func inspect() -> [AgentStatus] {
        labels.map { label, name in
            let (code, output) = run(["print", "gui/\(getuid())/\(label)"])
            let lines = output.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespaces) }
            let state = lines.first(where: { $0.hasPrefix("state = ") })?.replacingOccurrences(of: "state = ", with: "")
            let exitCode = lines.first(where: { $0.hasPrefix("last exit code = ") })
                .flatMap { Int($0.replacingOccurrences(of: "last exit code = ", with: "")) }
            return AgentStatus(id: label, name: name, loaded: code == 0, running: state == "running", exitCode: exitCode, checkedAt: Date())
        }
    }

    static func synchronize() throws {
        // launchd 对同一 label 只运行一个实例；已有进程不使用 -k 重启。
        let (code, _) = run(["kickstart", "gui/\(getuid())/com.yuwk.personal-review-skysight"])
        guard code == 0 else { throw NSError(domain: "PersonalDataHub", code: Int(code), userInfo: [NSLocalizedDescriptionKey: "无法启动同步，请确认采集 Agent 已安装。"] ) }
    }

    static func checkpoint() -> CheckpointStatus? {
        let path = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/PersonalReview/skysight-checkpoint.json")
        guard let data = try? Data(contentsOf: path),
              let value = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return CheckpointStatus(segments: (value["segments"] as? [String: Any])?.count ?? 0,
                                summaries: (value["summaries"] as? [String: Any])?.count ?? 0,
                                invalid: (value["invalid_segments"] as? [String: Any])?.count ?? 0,
                                lastSuccess: value["last_complete_success_at"] as? String,
                                lastAttempt: value["last_attempt_at"] as? String)
    }

    private static func run(_ arguments: [String]) -> (Int32, String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe; process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "")
        } catch { return (-1, "") }
    }
}

struct NetworkCollectionStatus: Decodable {
    var enabled: Bool = false
    var last_sample: String?
    var last_upload: String?
    var pending_records: Int?
    var active_connections: Int?
    var identified_applications: Int?
    var collection_error: String?
    var upload_error: String?
}

struct CheckpointStatus {
    let segments: Int
    let summaries: Int
    let invalid: Int
    let lastSuccess: String?
    let lastAttempt: String?
}
