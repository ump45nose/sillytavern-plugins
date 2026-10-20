import AppKit
import SwiftUI

/// Geometry of the "dial" mark in the 536×536 box used by `docs/design/v1/logo-mark.svg`.
enum LogoGeometry {
    static let box: CGFloat = 536
    static let center = CGPoint(x: 268, y: 268)
    static let radius: CGFloat = 228
    static let colors = ["#D97757", "#D4A27F", "#7D8F5E", "#6A9BCC", "#9C7BA0"]
    /// Arc endpoints from the SVG (absolute 1024 canvas, offset by 244).
    static let arcs: [(CGPoint, CGPoint)] = [
        (CGPoint(x: 563.29, y: 289.84), CGPoint(x: 739.69, y: 523.93)),
        (CGPoint(x: 711.41, y: 622.54), CGPoint(x: 539.79, y: 738.30)),
        (CGPoint(x: 437.77, y: 727.58), CGPoint(x: 312.59, y: 622.54)),
        (CGPoint(x: 284.31, y: 523.93), CGPoint(x: 308.85, y: 408.49)),
        (CGPoint(x: 374.79, y: 329.91), CGPoint(x: 460.71, y: 289.84)),
    ].map { (CGPoint(x: $0.0.x - 244, y: $0.0.y - 244), CGPoint(x: $0.1.x - 244, y: $0.1.y - 244)) }

    static func angle(_ p: CGPoint) -> Angle { .radians(atan2(p.y - center.y, p.x - center.x)) }

    /// Arc path in a y-down box of side `side`; angles increase clockwise on screen.
    static func arcPath(_ i: Int, side: CGFloat) -> Path {
        let s = side / box
        var p = Path()
        p.addArc(center: CGPoint(x: center.x * s, y: center.y * s), radius: radius * s,
                 startAngle: angle(arcs[i].0), endAngle: angle(arcs[i].1), clockwise: false)
        return p
    }
}

struct LogoMark: View {
    var mono = false
    var animated = false
    var ink: Color = Palette.ink
    @ViewState private var shown: CGFloat = 1
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geo in
            let side = min(geo.size.width, geo.size.height), s = side / LogoGeometry.box
            ZStack(alignment: .topLeading) {
                ForEach(0..<5, id: \.self) { i in
                    LogoGeometry.arcPath(i, side: side)
                        .trim(from: 0, to: shown)
                        .stroke(mono ? Color.primary : Color(hex: LogoGeometry.colors[i]),
                                style: StrokeStyle(lineWidth: (mono ? 72 : 64) * s, lineCap: .round))
                        .animation(animated ? Motion.grow.delay(Double(i) * 0.09) : nil, value: shown)
                }
                Circle().fill(mono ? Color.primary : ink)
                    .frame(width: (mono ? 208 : 200) * s, height: (mono ? 208 : 200) * s)
                    .scaleEffect(shown)
                    .position(x: 268 * s, y: 268 * s)
                    .animation(animated ? Motion.spring : nil, value: shown)
                Circle().fill(mono ? Color.primary : ink)
                    .frame(width: (mono ? 56 : 48) * s, height: (mono ? 56 : 48) * s)
                    .opacity(shown)
                    .position(x: 268 * s, y: 40 * s)
                    .animation(animated ? .easeOut(duration: 0.3).delay(0.55) : nil, value: shown)
            }
            .frame(width: side, height: side)
        }
        .aspectRatio(1, contentMode: .fit)
        .onAppear {
            guard animated, !reduceMotion else { return }
            shown = 0
            DispatchQueue.main.async { shown = 1 }
        }
    }
}

enum LogoImage {
    /// Monochrome template image for the menu bar.
    static func template(size: CGFloat = 16) -> NSImage {
        let image = NSImage(size: NSSize(width: size, height: size), flipped: true) { rect in
            draw(in: rect, mono: true)
            return true
        }
        image.isTemplate = true
        return image
    }

    static func draw(in rect: CGRect, mono: Bool) {
        guard let ctx = NSGraphicsContext.current?.cgContext else { return }
        let side = min(rect.width, rect.height), s = side / LogoGeometry.box
        ctx.saveGState()
        ctx.translateBy(x: rect.minX, y: rect.minY)
        ctx.setLineCap(.round)
        ctx.setLineWidth((mono ? 72 : 64) * s)
        for i in 0..<5 {
            ctx.addPath(LogoGeometry.arcPath(i, side: side).cgPath)
            ctx.setStrokeColor(mono ? NSColor.black.cgColor : NSColor(Color(hex: LogoGeometry.colors[i])).cgColor)
            ctx.strokePath()
        }
        ctx.setFillColor(mono ? NSColor.black.cgColor : NSColor(Palette.ink).cgColor)
        let core = (mono ? 104 : 100) * s, dot = (mono ? 28 : 24) * s
        ctx.fillEllipse(in: CGRect(x: 268 * s - core, y: 268 * s - core, width: core * 2, height: core * 2))
        ctx.fillEllipse(in: CGRect(x: 268 * s - dot, y: 40 * s - dot, width: dot * 2, height: dot * 2))
        ctx.restoreGState()
    }

    /// Writes a transparent-background `.iconset` for `iconutil`; the mark keeps the system icon grid inset.
    static func writeIconset(to folder: URL) throws {
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        for base in [16, 32, 128, 256, 512] {
            for scale in [1, 2] {
                let px = base * scale
                guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
                                                 samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
                      let context = NSGraphicsContext(bitmapImageRep: rep) else { continue }
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.current = context
                let size = CGFloat(px)
                context.cgContext.translateBy(x: 0, y: size)
                context.cgContext.scaleBy(x: 1, y: -1)
                let inset = size * 0.1
                draw(in: CGRect(x: inset, y: inset, width: size - inset * 2, height: size - inset * 2), mono: false)
                NSGraphicsContext.restoreGraphicsState()
                let name = scale == 1 ? "icon_\(base)x\(base).png" : "icon_\(base)x\(base)@2x.png"
                try rep.representation(using: .png, properties: [:])?.write(to: folder.appendingPathComponent(name))
            }
        }
    }
}
