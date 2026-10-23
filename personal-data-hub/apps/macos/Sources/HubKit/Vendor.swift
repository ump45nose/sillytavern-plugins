import Foundation

/// Brand colour, name and mark of an agent, model vendor or limits provider.
/// Colours, labels and the model rules follow Token Monitor's `vendorPresentation.js` (MIT, © 2026 Javis).
public struct Vendor: Equatable, Sendable {
    public var id: String
    public var label: String
    /// `#RRGGBB`; nil means the neutral fallback.
    public var hex: String?
    /// Artwork stem in `VendorMarks`, when it is not the id.
    public var icon: String? = nil

    public var mark: String { icon ?? id }

    public static func tool(_ raw: String) -> Vendor {
        let key = raw.lowercased().trimmingCharacters(in: .whitespaces)
        let id = aliases[key] ?? key
        return table[id] ?? Vendor(id: id, label: raw.prefix(1).uppercased() + raw.dropFirst(), hex: nil)
    }

    /// The vendor a model name belongs to, or nil for an unknown model.
    public static func model(_ name: String) -> Vendor? {
        let n = name.lowercased()
        func has(_ pattern: String) -> Bool { n.range(of: pattern, options: .regularExpression) != nil }
        let id: String? = if has("^(cursor-)?auto$") { "cursor" }
            else if has("claude|anthropic|sonnet|opus|haiku") { "claude" }
            else if has("gpt|openai|codex|^o[134](-|$)|o[134]-(mini|pro|preview)|chatgpt") { "openai" }
            else if has("gemini|gemma|google") { "gemini" }
            else if has("grok|xai") { "xai" }
            else if has("deepseek") { "deepseek" }
            else if has("nemotron|nvidia") { "nvidia" }
            else if has("llama|meta|muse-spark(-|$)") { "meta" }
            else if has("mistral|mixtral|codestral") { "mistral" }
            else if has("qwen|qwq|qvq|qmodel") { "qwen" }
            else if has("kimi|moonshot|k2d6-agent|k3-agent|(^|[^a-z0-9])k[23]([^a-z0-9]|$)") { "kimi" }
            else if has("chatglm|\\bglm-|\\bzai\\b|z\\.ai|zhipu") { "zai" }
            else if has("cohere|command-r") { "cohere" }
            else if has("mimo|xiaomi") { "xiaomi" }
            else if has("minimax|\\babab") { "minimax" }
            else if has("doubao|\\bseed(-|$)") { "doubao" }
            else if has("stepfun|step-") { "stepfun" }
            else if has("hy\\d|hunyuan") { "hunyuan" }
            else if has("^swe[-_]|devin|cognition") { "devin" }
            else { nil }
        return id.flatMap { table[$0] }
    }

    /// Stable fallback for unknown names, so a model keeps its colour between renders.
    public static func fallbackIndex(_ name: String, count: Int) -> Int {
        var hash: Int32 = 0
        for u in name.lowercased().unicodeScalars { hash = hash &* 31 &+ Int32(truncatingIfNeeded: u.value) }
        return Int(hash.magnitude) % max(count, 1)
    }

    static let aliases = ["claude-code": "claude", "claudecode": "claude", "gemini-cli": "gemini", "github-copilot": "copilot",
                          "grok-build": "grok", "qoder": "qodercn", "deepseek-harness": "dsh"]

    static let table: [String: Vendor] = Dictionary(uniqueKeysWithValues: [
        Vendor(id: "claude", label: "Claude Code", hex: "#CC7C5E"),
        Vendor(id: "claude-desktop", label: "Claude Desktop", hex: "#E3A587", icon: "claude"),
        Vendor(id: "codex", label: "Codex", hex: "#49A3B0"),
        Vendor(id: "openai", label: "OpenAI", hex: "#49A3B0", icon: "codex"),
        Vendor(id: "opencode", label: "OpenCode", hex: "#000000"),
        Vendor(id: "hermes", label: "Hermes Agent", hex: "#D4AF37", icon: "hermes-agent"),
        Vendor(id: "openclaw", label: "OpenClaw", hex: "#FF4D4D"),
        Vendor(id: "cursor", label: "Cursor", hex: "#000000"),
        Vendor(id: "antigravity", label: "Antigravity", hex: "#4285F4"),
        Vendor(id: "cline", label: "Cline", hex: "#9D4EDD"),
        Vendor(id: "amp", label: "Amp", hex: "#F34E3F"),
        Vendor(id: "droid", label: "Factory Droid", hex: "#000000"),
        Vendor(id: "factory", label: "Factory", hex: "#000000", icon: "droid"),
        Vendor(id: "kimi", label: "Kimi", hex: "#16191E"),
        Vendor(id: "qwen", label: "Qwen", hex: "#615CED"),
        Vendor(id: "grok", label: "Grok Build", hex: "#000000"),
        Vendor(id: "copilot", label: "GitHub Copilot", hex: "#000000"),
        Vendor(id: "pi", label: "Pi", hex: "#000000"),
        Vendor(id: "omp", label: "Oh My Pi", hex: "#ED4ABF"),
        Vendor(id: "zed", label: "Zed", hex: "#4173E7"),
        Vendor(id: "kilo", label: "Kilo", hex: "#D8C83A"),
        Vendor(id: "commandcode", label: "Command Code", hex: "#8C4EDD"),
        Vendor(id: "mimo", label: "Xiaomi MiMo", hex: "#000000", icon: "xiaomi"),
        Vendor(id: "muse", label: "Muse Code", hex: "#0866FF", icon: "meta"),
        Vendor(id: "zcode", label: "ZCode", hex: "#000000", icon: "zai"),
        Vendor(id: "kiro", label: "Kiro", hex: "#9046FF"),
        Vendor(id: "codebuddy", label: "CodeBuddy", hex: "#6C4DFF"),
        Vendor(id: "workbuddy", label: "WorkBuddy", hex: "#0DC8A5"),
        Vendor(id: "catpaw", label: "CatPaw", hex: "#00C47C"),
        Vendor(id: "qodercn", label: "Qoder CN", hex: "#2ADB5C"),
        Vendor(id: "reasonix", label: "Reasonix", hex: "#4D6BFE"),
        Vendor(id: "dsh", label: "DeepSeek Harness", hex: "#4D6BFE"),
        Vendor(id: "cherrystudio", label: "Cherry Studio", hex: "#EA5E5D"),
        Vendor(id: "lmstudio", label: "LM Studio", hex: "#6C5CE7"),
        Vendor(id: "devin", label: "Devin", hex: "#000000"),
        Vendor(id: "mcode", label: "MiniMax Code", hex: "#F23F5D", icon: "minimax"),
        Vendor(id: "openrouter", label: "OpenRouter", hex: "#6566F1"),
        Vendor(id: "gemini", label: "Gemini", hex: "#4285F4"),
        Vendor(id: "deepseek", label: "DeepSeek", hex: "#4D6BFE"),
        Vendor(id: "xai", label: "xAI", hex: "#000000", icon: "grok"),
        Vendor(id: "meta", label: "Meta", hex: "#1D65C1"),
        Vendor(id: "mistral", label: "Mistral", hex: "#FA520F"),
        Vendor(id: "moonshot", label: "Moonshot", hex: "#16191E"),
        Vendor(id: "zai", label: "GLM", hex: "#000000"),
        Vendor(id: "cohere", label: "Cohere", hex: "#39594D"),
        Vendor(id: "xiaomi", label: "Xiaomi", hex: "#000000"),
        Vendor(id: "minimax", label: "MiniMax", hex: "#F23F5D"),
        Vendor(id: "doubao", label: "Doubao", hex: "#1E37FC"),
        Vendor(id: "hunyuan", label: "Hunyuan", hex: "#0053E0"),
        Vendor(id: "stepfun", label: "StepFun", hex: "#000000"),
        Vendor(id: "nvidia", label: "NVIDIA", hex: "#74B71B"),
        Vendor(id: "ollama", label: "Ollama", hex: "#888888"),
    ].map { ($0.id, $0) })
}
