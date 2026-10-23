import Testing
@testable import HubKit

@Test func modelsResolveToTheirVendor() {
    #expect(Vendor.model("claude-opus-5-5 (auto balanced)")?.id == "claude")
    #expect(Vendor.model("gpt-6.1-sol")?.id == "openai")
    #expect(Vendor.model("grok-4.7-high-fast")?.id == "xai")
    #expect(Vendor.model("deepseek-v4-flash")?.id == "deepseek")
    #expect(Vendor.model("Qwen3.8-Flash")?.id == "qwen")
    #expect(Vendor.model("auto")?.id == "cursor")
    #expect(Vendor.model("k3-256k")?.id == "kimi")
    #expect(Vendor.model("mystery-model") == nil)
}

@Test func toolsUseBrandColoursAndNames() {
    #expect(Vendor.tool("claude").hex == "#CC7C5E")
    #expect(Vendor.tool("Claude-Code").id == "claude")
    #expect(Vendor.tool("grok").hex == "#000000")
    #expect(Vendor.tool("dsh").label == "DeepSeek Harness")
    #expect(Vendor.tool("claude-desktop").mark == "claude")
    let unknown = Vendor.tool("newtool")
    #expect(unknown.hex == nil && unknown.label == "Newtool")
    #expect(Vendor.fallbackIndex("x", count: 7) == Vendor.fallbackIndex("X", count: 7))
}
