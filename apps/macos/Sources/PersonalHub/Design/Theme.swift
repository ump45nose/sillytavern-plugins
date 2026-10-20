import AppKit
import HubKit
import SwiftUI

/// The macOS 27 SDK declares `@State` as a macro whose plugin ships only with Xcode;
/// naming the property wrapper directly keeps Command Line Tools builds working.
typealias ViewState<Value> = SwiftUICore.State<Value>

extension Color {
    init(hex: String) {
        var v: UInt64 = 0
        Scanner(string: hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))).scanHexInt64(&v)
        self.init(.sRGB, red: Double((v >> 16) & 0xFF) / 255, green: Double((v >> 8) & 0xFF) / 255, blue: Double(v & 0xFF) / 255)
    }
}

enum Palette {
    static let canvas = Color(hex: "#E7E2D6")
    static let bg = Color(hex: "#F4F1EA")
    static let side = Color(hex: "#ECE8DE")
    static let card = Color(hex: "#FFFDF8")
    static let sunk = Color(hex: "#F6F3EC")
    static let line = Color(hex: "#E6E0D3")
    static let line2 = Color(hex: "#EFEAE0")
    static let ink = Color(hex: "#1F1E1B")
    static let ink2 = Color(hex: "#5E5D59")
    static let ink3 = Color(hex: "#93918A")
    static let ink4 = Color(hex: "#B9B6AD")
    static let clayDeep = Color(hex: "#B95A3B")
    static let heat = ["#EFEAE0", "#F4DDD0", "#EDBBA3", "#E3977A", "#D97757", "#B35A3D"].map(Color.init(hex:))
    static let gitHeat = ["#EEE9DE", "#DCE3CC", "#B9C79E", "#93A872", "#6F8550"].map(Color.init(hex:))
}

extension Tone {
    var color: Color {
        switch self {
        case .clay: Color(hex: "#D97757")
        case .kraft: Color(hex: "#C99A6E")
        case .olive: Color(hex: "#7D8F5E")
        case .sky: Color(hex: "#6A9BCC")
        case .plum: Color(hex: "#9C7BA0")
        case .sage: Color(hex: "#7FA394")
        case .ochre: Color(hex: "#C9A23F")
        case .rose: Color(hex: "#C97B84")
        case .steel: Color(hex: "#5F7A99")
        case .ink: Palette.ink4
        }
    }

    var tint: Color {
        switch self {
        case .clay: Color(hex: "#F7E4DA")
        case .kraft: Color(hex: "#F3E7D9")
        case .olive: Color(hex: "#E7EBDD")
        case .sky: Color(hex: "#E2EBF4")
        case .plum: Color(hex: "#EFE6EF")
        case .sage: Color(hex: "#E3EDE8")
        case .ochre: Color(hex: "#F5ECD3")
        case .rose: Color(hex: "#F5E3E5")
        case .steel: Color(hex: "#E3E9F0")
        case .ink: Palette.sunk
        }
    }
}

enum Typo {
    /// New York with Songti SC for CJK, matching the mockup's serif headings.
    /// New York is loaded from its file because the system-UI instance widens CJK punctuation to 1.5em.
    static func serif(_ size: CGFloat, _ weight: NSFont.Weight = .regular) -> Font {
        let w = weight.rawValue
        let bold = w >= NSFont.Weight.semibold.rawValue
        let instance: String = switch w {
        case ..<NSFont.Weight.medium.rawValue: "Regular"
        case ..<NSFont.Weight.semibold.rawValue: "Medium"
        case ..<NSFont.Weight.bold.rawValue: "Semibold"
        case ..<NSFont.Weight.heavy.rawValue: "Bold"
        default: "Heavy"
        }
        let cjk = CTFontDescriptorCreateWithNameAndSize((bold ? "STSongti-SC-Bold" : "STSongti-SC-Regular") as CFString, size)
        if let latin = newYork[".NewYork-" + instance] {
            let desc = CTFontDescriptorCreateCopyWithAttributes(latin, [kCTFontCascadeListAttribute: [cjk]] as CFDictionary)
            return Font(CTFontCreateWithFontDescriptor(desc, size, nil))
        }
        let base = NSFont.systemFont(ofSize: size, weight: weight)
        let desc = (base.fontDescriptor.withDesign(.serif) ?? base.fontDescriptor).addingAttributes([.cascadeList: [cjk]])
        return Font(NSFont(descriptor: desc, size: size) ?? base)
    }

    private static let newYork: [String: CTFontDescriptor] = {
        let url = URL(fileURLWithPath: "/System/Library/Fonts/NewYork.ttf") as CFURL
        let descs = CTFontManagerCreateFontDescriptorsFromURL(url) as? [CTFontDescriptor] ?? []
        return Dictionary(descs.compactMap { d in
            (CTFontDescriptorCopyAttribute(d, kCTFontNameAttribute) as? String).map { ($0, d) }
        }, uniquingKeysWith: { a, _ in a })
    }()

    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight) }
    static func mono(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font { .system(size: size, weight: weight, design: .monospaced) }
}

enum Metrics {
    static let cardRadius: CGFloat = 18
    static let innerRadius: CGFloat = 12
    static let smallRadius: CGFloat = 8
    static let compactHeight: CGFloat = 192
    static let sidebarWidth: CGFloat = 232
}

enum Motion {
    static let rise = Animation.timingCurve(0.2, 0.8, 0.2, 1, duration: 0.55)
    static let spring = Animation.spring(response: 0.42, dampingFraction: 0.78)
    static let grow = Animation.timingCurve(0.2, 0.8, 0.2, 1, duration: 0.8)
    static let fast = Animation.easeOut(duration: 0.16)
    static let stagger = 0.055
}
