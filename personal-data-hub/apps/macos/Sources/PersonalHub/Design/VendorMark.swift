import AppKit
import HubKit
import SwiftUI

extension Vendor {
    /// Near-black brands use the app's ink so they sit on the warm paper; unknown ids get a stable palette tone.
    var color: Color {
        guard let hex else { return Self.fallback[Vendor.fallbackIndex(id, count: Self.fallback.count)].color }
        return hex == "#000000" || hex == "#16191E" ? Palette.ink : Color(hex: hex)
    }

    static func modelColor(_ name: String) -> Color {
        model(name)?.color ?? fallback[fallbackIndex(name, count: fallback.count)].color
    }

    private static let fallback: [Tone] = [.steel, .plum, .olive, .sky, .ochre, .sage, .kraft]
}

/// The vendor's logo, tinted with its colour when the artwork is single-colour; a dot when there is none.
struct VendorMark: View {
    var vendor: Vendor?
    var color: Color? = nil
    var size: CGFloat = 14

    var body: some View {
        if let vendor, let image = Self.image(vendor.mark) {
            Image(nsImage: image)
                .resizable()
                .renderingMode(VendorMarks.mono.contains(vendor.mark) ? .template : .original)
                .interpolation(.high)
                .aspectRatio(contentMode: .fit)
                .foregroundStyle(color ?? vendor.color)
                .frame(width: size, height: size)
        } else {
            Circle().fill(color ?? vendor?.color ?? Palette.ink4).frame(width: size * 0.5, height: size * 0.5)
                .frame(width: size, height: size)
        }
    }

    @MainActor private static var cache: [String: NSImage] = [:]

    @MainActor static func image(_ mark: String) -> NSImage? {
        if let hit = cache[mark] { return hit }
        guard let svg = VendorMarks.svg[mark], let image = NSImage(data: Data(svg.utf8)) else { return nil }
        image.size = NSSize(width: 48, height: 48)
        image.isTemplate = VendorMarks.mono.contains(mark)
        cache[mark] = image
        return image
    }
}
