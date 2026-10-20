import Foundation
import Darwin

private var collectionChild: pid_t = 0

/// Keep collection children under the signed client's permission identity.
enum CollectionRuntime {
    static func directory() throws -> URL {
        guard let resources = Bundle.main.resourceURL,
              let data = try? Data(contentsOf: resources.appendingPathComponent("collection.json")),
              let manifest = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let hash = manifest["archiveSHA256"] as? String,
              hash.count == 64, hash.allSatisfy({ $0.isHexDigit }) else { throw CollectionFailure.unavailable }
        let version = Connection.directory.appendingPathComponent("Agents/versions/" + hash)
        guard FileManager.default.fileExists(atPath: version.appendingPathComponent("python/bin/python3.12").path) else { throw CollectionFailure.unavailable }
        return version
    }

    // Only fixed, packaged entry points are accepted, never arbitrary executables.
    static func run(_ source: String, checkAccess: Bool = false, arguments: [String] = []) throws -> Int32 {
        let version = try directory()
        let process = Process()
        process.currentDirectoryURL = version
        if source == "wechat" {
            process.executableURL = version.appendingPathComponent("python/bin/python3.12")
            process.arguments = ["-I", version.appendingPathComponent("run-wechat.py").path,
                                 checkAccess ? "--access-check" : "--watch"]
        } else if source == "network" {
            process.executableURL = version.appendingPathComponent("python/bin/python3.12")
            process.arguments = ["-I", version.appendingPathComponent("network/collector.py").path,
                                 checkAccess ? "--access-check" : "--watch"]
        } else if source == "activity" {
            process.executableURL = version.appendingPathComponent("bin/node")
            process.arguments = [version.appendingPathComponent(checkAccess ? "check-activity.mjs" : "skysight/sync-skysight.mjs").path] + arguments
        } else { throw CollectionFailure.unavailable }
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        try process.run()
        collectionChild = process.processIdentifier
        signal(SIGTERM) { _ in if collectionChild > 0 { kill(collectionChild, SIGTERM) } }
        signal(SIGINT) { _ in if collectionChild > 0 { kill(collectionChild, SIGINT) } }
        process.waitUntilExit()
        collectionChild = 0
        return process.terminationStatus
    }
}

enum CollectionFailure: LocalizedError {
    case authorizationRequired, unavailable, installationFailed
    var errorDescription: String? {
        switch self {
        case .authorizationRequired: return "请在系统设置中允许 Personal Data Hub 完全磁盘访问。授权后回到客户端即可启用微信和电脑活动采集。"
        case .unavailable: return "应用缺少采集组件，请重新安装完整应用。"
        case .installationFailed: return "采集组件暂时无法启用，原任务和同步进度已保留。"
        }
    }
}
