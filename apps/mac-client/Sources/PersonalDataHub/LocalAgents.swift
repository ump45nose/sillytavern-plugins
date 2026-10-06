import Foundation

struct AgentStatus: Identifiable {
    let id: String
    let name: String
    let loaded: Bool
    let running: Bool
    let exitCode: Int?
    let checkedAt: Date
    var state: String {
        if !loaded { return "未加载" }
        if running { return "采集中" }
        if let code = exitCode, code != 0 { return "上次同步失败（\(code)）" }
        return "等待下次同步"
    }
}

enum LocalAgents {
    static let labels = [
        ("com.yuwk.personal-review-skysight", "电脑活动同步"),
        ("com.personal-crm.wechat", "微信采集")
    ]
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

struct CheckpointStatus {
    let segments: Int
    let summaries: Int
    let invalid: Int
    let lastSuccess: String?
    let lastAttempt: String?
}
