import AppKit
import CoreText
import SwiftUI

/// Anthropic's typefaces as installed on this Mac: the variable Sans and Serif inside Claude.app, and Anthropic
/// Serif Text with CJK in the user's fonts. Read in place, for this Mac only; the app never copies or bundles them.
/// Latin comes from the variable fonts (`wght` 300–800, `opsz` 16–48); Chinese cascades to Anthropic Serif Text
/// (serif) or PingFang (sans), and Songti fills the CJK punctuation Anthropic Serif Text lacks.
enum AnthropicFonts {
    enum Family: String { case sans, serif }

    static var available: Bool { latin[.sans] != nil && latin[.serif] != nil }

    /// Anthropic's emphasis is lighter than the system's: semibold maps to 550 rather than 600.
    static func axisWeight(_ weight: CGFloat) -> CGFloat {
        switch weight {
        case ..<(-0.3): 300
        case ..<0.1: 400
        case ..<0.27: 500
        case ..<0.35: 550
        case ..<0.5: 650
        default: 750
        }
    }

    static func weight(_ w: Font.Weight) -> CGFloat {
        let table: [(Font.Weight, NSFont.Weight)] = [(.ultraLight, .ultraLight), (.thin, .thin), (.light, .light), (.medium, .medium),
                                                     (.semibold, .semibold), (.bold, .bold), (.heavy, .heavy), (.black, .black)]
        return (table.first { $0.0 == w }?.1 ?? .regular).rawValue
    }

    static func font(_ family: Family, size: CGFloat, weight: CGFloat) -> NSFont? {
        guard let base = latin[family] else { return nil }
        let wght = axisWeight(weight)
        let key = "\(family.rawValue)|\(size)|\(wght)"
        lock.lock()
        defer { lock.unlock() }
        if let hit = cache[key] { return hit }
        let variation: [NSNumber: NSNumber] = [NSNumber(value: wghtAxis): NSNumber(value: Double(wght)),
                                               NSNumber(value: opszAxis): NSNumber(value: Double(min(max(size, 16), 48)))]
        let attributes: [CFString: Any] = [kCTFontVariationAttribute: variation, kCTFontCascadeListAttribute: cascade(family, wght, size)]
        let font = CTFontCreateWithFontDescriptor(CTFontDescriptorCreateCopyWithAttributes(base, attributes as CFDictionary), size, nil) as NSFont
        cache[key] = font
        return font
    }

    private static let wghtAxis: UInt32 = 0x7767_6874, opszAxis: UInt32 = 0x6F70_737A
    private static let lock = NSLock()
    nonisolated(unsafe) private static var cache: [String: NSFont] = [:]

    private static func cascade(_ family: Family, _ wght: CGFloat, _ size: CGFloat) -> [CTFontDescriptor] {
        func named(_ name: String) -> CTFontDescriptor { CTFontDescriptorCreateWithNameAndSize(name as CFString, size) }
        switch family {
        case .serif:
            let song = named(wght >= 600 ? "STSongti-SC-Bold" : "STSongti-SC-Regular")
            return wght < 600 ? (cjkSerif.map { [$0, song] } ?? [song]) : [song]
        case .sans:
            let pingfang = switch wght {
            case ..<350: "PingFangSC-Light"
            case ..<450: "PingFangSC-Regular"
            case ..<600: "PingFangSC-Medium"
            default: "PingFangSC-Semibold"
            }
            return [named(pingfang)]
        }
    }

    private static let latin: [Family: CTFontDescriptor] = {
        let dir = URL(fileURLWithPath: "/Applications/Claude.app/Contents/Resources/fonts")
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        func load(_ prefix: String) -> CTFontDescriptor? {
            let match = files.filter { $0.lastPathComponent.hasPrefix(prefix) && ["ttf", "otf"].contains($0.pathExtension.lowercased()) }
            guard let url = match.max(by: { $0.lastPathComponent < $1.lastPathComponent }) else { return nil }
            return (CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor])?.first
        }
        var out: [Family: CTFontDescriptor] = [:]
        out[.sans] = load("AnthropicSans-Romans")
        out[.serif] = load("AnthropicSerif-Romans")
        return out
    }()

    /// Installed in ~/Library/Fonts, so it resolves by name; nil (Songti only) when it isn't there.
    private static let cjkSerif: CTFontDescriptor? = {
        let name = "AnthropicSerifText-Light"
        let d = CTFontDescriptorCreateWithNameAndSize(name as CFString, 12)
        return (CTFontCopyPostScriptName(CTFontCreateWithFontDescriptor(d, 12, nil)) as String) == name ? d : nil
    }()
}
