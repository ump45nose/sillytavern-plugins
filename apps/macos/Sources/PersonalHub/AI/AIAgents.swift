import AppKit
import Foundation
import HubKit
import Observation

/// A local agent CLI that can answer with the `personal_hub` MCP tools.
enum AIAgent: String, CaseIterable, Identifiable {
    case codex, claude, pi, antigravity

    var id: String { rawValue }

    var title: String {
        switch self {
        case .codex: "Codex"
        case .claude: "Claude Code"
        case .pi: "pi"
        case .antigravity: "Antigravity"
        }
    }

    var command: String {
        switch self {
        case .codex: "codex"
        case .claude: "claude"
        case .pi: "pi"
        case .antigravity: "agy"
        }
    }

    /// Codex and Claude take the server per run; pi and Antigravity only read it from their own config.
    var mountsPerRun: Bool { self == .codex || self == .claude }

    static let searchPaths: [String] = {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return ["/opt/homebrew/bin", "/usr/local/bin", "\(home)/.local/bin", "\(home)/.npm-global/bin", "\(home)/bin", "/usr/bin"]
    }()

    var executable: URL? {
        Self.searchPaths.map { URL(fileURLWithPath: $0).appendingPathComponent(command) }
            .first { FileManager.default.isExecutableFile(atPath: $0.path) }
    }

    /// The registration command for the agent's own sessions; required before 问 AI for pi and Antigravity.
    func registerCommand(server: String) -> String {
        let quoted = "\"\(server)\""
        return switch self {
        case .codex: "codex mcp add \(HubMCP.serverName) -- \(quoted) --mcp"
        case .claude: "claude mcp add --scope user \(HubMCP.serverName) -- \(quoted) --mcp"
        case .pi: "pi mcp add \(HubMCP.serverName) -- \(quoted) --mcp"
        case .antigravity: "agy mcp add \(HubMCP.serverName) -- \(quoted) --mcp"
        }
    }

    func arguments(prompt: String, server: String, configFile: URL) -> [String] {
        let system = AIAgent.system()
        switch self {
        case .codex:
            let key = "mcp_servers.\(HubMCP.serverName)"
            return ["exec", "--skip-git-repo-check", "--ephemeral", "--color", "never", "-s", "read-only",
                    "-c", "approval_policy=\"never\"",
                    "-c", "\(key).command=\(Self.toml(server))",
                    "-c", "\(key).args=[\"--mcp\"]",
                    "-c", "\(key).default_tools_approval_mode=\"approve\"",
                    system + "\n\n用户：" + prompt]
        case .claude:
            return ["-p", "--strict-mcp-config", "--mcp-config", configFile.path,
                    "--allowedTools", "mcp__\(HubMCP.serverName)", "--append-system-prompt", system, prompt]
        case .pi:
            return ["-p", "--no-session", "--tools", "mcp__\(HubMCP.serverName)__*", "--append-system-prompt", system, prompt]
        case .antigravity:
            return ["-p", system + "\n\n用户：" + prompt]
        }
    }

    static func system(now: Date = Date()) -> String {
        """
        你在 Nook 的 ⌘K 面板里回答用户（\(NSFullUserName())）。现在是 \(HubMCP.stamp(now))。
        数据只来自 personal_hub MCP 工具：先调用 get_overview 或相关工具，再回答。不要读写本机文件，也不要执行命令。
        需要新建任务、日程、Memo 或完成任务时调用 propose_* 工具；它们只会生成待确认项，请提醒用户在面板里确认。
        用简洁的中文 Markdown 回答，金额用美元或原币种，不要编造数据。
        """
    }

    private static func toml(_ s: String) -> String {
        "\"" + s.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }
}

enum AIEnvironment {
    static var server: String { Bundle.main.executableURL?.path ?? CommandLine.arguments[0] }

    /// Empty working directory, so an agent never starts inside a repository.
    static let workdir = HubMCP.support.appendingPathComponent("agent-workdir")

    static var mcpJSON: String {
        let object: [String: Any] = ["mcpServers": [HubMCP.serverName: ["command": server, "args": ["--mcp"]]]]
        let data = (try? JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])) ?? Data()
        return String(decoding: data, as: UTF8.self)
    }

    static func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = (AIAgent.searchPaths + [env["PATH"] ?? "/bin"]).joined(separator: ":")
        env["NO_COLOR"] = "1"
        return env
    }
}

/// One 问 AI run: the agent's answer streams into `output`.
@MainActor
@Observable
final class AgentRun {
    enum Phase: Equatable { case idle, running, done, failed(String) }

    private(set) var phase: Phase = .idle
    private(set) var output = ""
    private(set) var progress = ""
    private(set) var prompt = ""
    private(set) var agent: AIAgent = .codex
    private(set) var started: Date?
    private(set) var finished: Date?

    @ObservationIgnored private var process: Process?
    @ObservationIgnored private var stderrTail = ""
    @ObservationIgnored private var timeout: Task<Void, Never>?
    @ObservationIgnored private var generation = 0

    static let limit: TimeInterval = 300

    var running: Bool { phase == .running }

    func start(_ prompt: String, agent: AIAgent) {
        stop()
        generation += 1
        let g = generation
        self.prompt = prompt
        self.agent = agent
        output = ""
        progress = "正在启动 \(agent.title)…"
        stderrTail = ""
        started = Date()
        finished = nil
        guard let exe = agent.executable else {
            phase = .failed("没找到 \(agent.command)，可以在 设置 → AI 里换一个 agent。")
            return
        }
        phase = .running
        do {
            try FileManager.default.createDirectory(at: AIEnvironment.workdir, withIntermediateDirectories: true)
            let config = AIEnvironment.workdir.appendingPathComponent("mcp.json")
            try Data(AIEnvironment.mcpJSON.utf8).write(to: config, options: .atomic)

            let p = Process()
            p.executableURL = exe
            p.arguments = agent.arguments(prompt: prompt, server: AIEnvironment.server, configFile: config)
            p.currentDirectoryURL = AIEnvironment.workdir
            p.environment = AIEnvironment.environment()
            p.standardInput = FileHandle.nullDevice
            let out = Pipe(), err = Pipe()
            p.standardOutput = out
            p.standardError = err
            out.fileHandleForReading.readabilityHandler = { [weak self] h in
                let text = Self.clean(h.availableData)
                guard !text.isEmpty else { return }
                Task { @MainActor in
                    guard let self, self.generation == g else { return }
                    self.output += text
                }
            }
            err.fileHandleForReading.readabilityHandler = { [weak self] h in
                let text = Self.clean(h.availableData)
                guard !text.isEmpty else { return }
                Task { @MainActor in
                    guard let self, self.generation == g else { return }
                    self.stderrTail = String((self.stderrTail + text).suffix(4000))
                    if let line = text.split(whereSeparator: \.isNewline).last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) {
                        self.progress = String(line.trimmingCharacters(in: .whitespaces).prefix(120))
                    }
                }
            }
            p.terminationHandler = { [weak self] proc in
                let status = proc.terminationStatus, reason = proc.terminationReason
                out.fileHandleForReading.readabilityHandler = nil
                err.fileHandleForReading.readabilityHandler = nil
                let rest = Self.clean(out.fileHandleForReading.readDataToEndOfFile())
                Task { @MainActor in
                    guard let self, self.generation == g else { return }
                    self.output += rest
                    self.finish(status: status, signalled: reason == .uncaughtSignal)
                }
            }
            try p.run()
            process = p
            timeout = Task { [weak self] in
                try? await Task.sleep(for: .seconds(Self.limit))
                guard !Task.isCancelled, let self, self.generation == g, self.running else { return }
                self.process?.terminate()
                self.phase = .failed("超过 \(Int(Self.limit / 60)) 分钟没有完成，已停止。")
            }
        } catch {
            phase = .failed("启动 \(agent.title) 失败：\(error.localizedDescription)")
        }
    }

    func stop() {
        timeout?.cancel()
        if let p = process, p.isRunning { p.terminate() }
        process = nil
        if running {
            phase = .failed("已停止。")
            finished = Date()
        }
    }

    func reset() {
        stop()
        generation += 1
        phase = .idle
        output = ""
        progress = ""
    }

    #if DEBUG
    func preview(_ prompt: String, output: String, agent: AIAgent, seconds: TimeInterval) {
        self.prompt = prompt
        self.agent = agent
        self.output = output
        finished = Date()
        started = finished?.addingTimeInterval(-seconds)
        phase = .done
    }
    #endif

    private func finish(status: Int32, signalled: Bool) {
        timeout?.cancel()
        process = nil
        finished = Date()
        guard running else { return }
        output = output.trimmingCharacters(in: .whitespacesAndNewlines)
        if status == 0, !output.isEmpty {
            phase = .done
        } else if signalled {
            phase = .failed("已停止。")
        } else {
            let tail = stderrTail.split(whereSeparator: \.isNewline).suffix(4).joined(separator: "\n")
            phase = .failed(tail.isEmpty ? "\(agent.title) 没有返回内容（退出码 \(status)）。" : tail)
        }
    }

    nonisolated private static func clean(_ data: Data) -> String {
        String(decoding: data, as: UTF8.self)
            .replacingOccurrences(of: "\u{1B}\\[[0-9;?]*[ -/]*[@-~]", with: "", options: .regularExpression)
    }
}

/// Watches the pending-change folder the MCP server writes into, and applies confirmed changes.
@MainActor
@Observable
final class AIPendingModel {
    private(set) var items: [AIPendingChange] = []
    private(set) var busy: Set<String> = []
    private(set) var errors: [String: String] = [:]

    @ObservationIgnored private let store: AIPendingStore
    @ObservationIgnored private var source: DispatchSourceFileSystemObject?

    init(store: AIPendingStore) {
        self.store = store
        try? FileManager.default.createDirectory(at: store.dir, withIntermediateDirectories: true)
        reload()
        watch()
    }

    func reload() {
        let fresh = store.list()
        if fresh != items { items = fresh }
        errors = errors.filter { id, _ in fresh.contains { $0.id == id } }
    }

    func items(since date: Date?) -> [AIPendingChange] {
        guard let date else { return [] }
        return items.filter { $0.createdAt >= date.addingTimeInterval(-1) }
    }

    func reject(_ change: AIPendingChange) {
        store.remove(change.id)
        reload()
    }

    func confirm(_ change: AIPendingChange, state: AppState) async {
        guard !busy.contains(change.id) else { return }
        busy.insert(change.id)
        defer { busy.remove(change.id) }
        errors[change.id] = nil
        do {
            try await apply(change, state: state)
            store.remove(change.id)
            reload()
        } catch HubModel.WriteError.demo {
            errors[change.id] = "示例模式下不能写入，先在设置里连接 hub。"
        } catch let e as AIApplyError {
            errors[change.id] = e.message
        } catch {
            errors[change.id] = "写入失败：\(error.localizedDescription)"
        }
    }

    func confirmAll(state: AppState) async {
        for change in items { await confirm(change, state: state) }
    }

    struct AIApplyError: Error { var message: String }

    private func apply(_ change: AIPendingChange, state: AppState) async throws {
        let agenda = state.agenda
        switch change.kind {
        case let .task(title, due, time, notes, list):
            let day = due.flatMap { GoogleDate.day($0, calendar: .hub) }
            let clock = time.map { "时间 " + $0 }
            let body = [clock, notes].compactMap { $0 }.joined(separator: "\n")
            guard agenda.addTask(title: title, notes: body.isEmpty ? nil : body, due: day, listName: list) else {
                throw AIApplyError(message: "还没有任务列表，先连接 Google。")
            }
        case let .completeTask(id, _):
            guard let task = agenda.view.allTasks.first(where: { $0.id == id }) else { throw AIApplyError(message: "这个任务已经不在了。") }
            if !task.completed { agenda.toggle(task) }
        case let .event(title, start, end, location, notes):
            guard let calendar = agenda.writableCalendar else { throw AIApplyError(message: "没有可写入的日历。") }
            agenda.createEvent(EventDraft(title: title, start: start, end: end, location: location, notes: notes), calendarID: calendar.id)
        case let .memo(content, visibility):
            try await state.memos.create(content, visibility: visibility)
        }
    }

    #if DEBUG
    func seed(_ changes: [AIPendingChange]) {
        for c in changes { try? store.add(c) }
        reload()
    }
    #endif

    private func watch() {
        let fd = open(store.dir.path, O_EVTONLY)
        guard fd >= 0 else { return }
        let s = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.write, .rename, .delete], queue: .main)
        s.setEventHandler { [weak self] in MainActor.assumeIsolated { self?.reload() } }
        s.setCancelHandler { close(fd) }
        s.resume()
        source = s
    }
}

extension AIPendingChange {
    var symbol: String {
        switch kind {
        case .task: "checklist"
        case .completeTask: "checkmark.circle"
        case .event: "calendar.badge.plus"
        case .memo: "note.text.badge.plus"
        }
    }

    var verb: String {
        switch kind {
        case .task: "新建任务"
        case .completeTask: "完成任务"
        case .event: "新建日程"
        case .memo: "发布 Memo"
        }
    }

    var headline: String {
        switch kind {
        case let .task(title, _, _, _, _), let .completeTask(_, title), let .event(title, _, _, _, _): title
        case let .memo(content, _): content.split(whereSeparator: \.isNewline).first.map(String.init) ?? content
        }
    }

    var detail: String? {
        switch kind {
        case let .task(_, due, time, notes, list):
            let day = due.flatMap { GoogleDate.day($0, calendar: .hub) }.map { HubFormat.md($0) + " " + HubFormat.weekday($0) }
            let when = [day, time].compactMap { $0 }.joined(separator: " ")
            return [when.isEmpty ? nil : when, list.map { "#" + $0 }, notes].compactMap { $0 }.joined(separator: " · ").nilIfEmpty
        case .completeTask:
            return nil
        case let .event(_, start, end, location, _):
            let day = HubFormat.md(start) + " " + Agenda.clock(start) + "–" + Agenda.clock(end)
            return [day, location].compactMap { $0 }.joined(separator: " · ")
        case let .memo(content, visibility):
            let rest = content.split(whereSeparator: \.isNewline).dropFirst().joined(separator: " ")
            let scope = ["PRIVATE": "私密", "PROTECTED": "登录可见", "PUBLIC": "公开"][visibility] ?? visibility
            return [scope, rest.isEmpty ? nil : rest].compactMap { $0 }.joined(separator: " · ")
        }
    }
}

private extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
