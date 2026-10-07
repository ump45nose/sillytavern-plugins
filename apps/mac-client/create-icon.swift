// Regenerate the app icon with native vector drawing: swift create-icon.swift
import AppKit

let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let resources = root.appendingPathComponent("Resources")
let iconset = root.appendingPathComponent("dist/AppIcon.iconset")
let files = FileManager.default
try files.createDirectory(at: resources, withIntermediateDirectories: true)
try files.createDirectory(at: iconset, withIntermediateDirectories: true)
defer { try? files.removeItem(at: iconset) }

func render(_ size: Int) throws -> Data {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
                                 bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                 isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    let context = NSGraphicsContext(bitmapImageRep: bitmap)!
    NSGraphicsContext.saveGraphicsState()
    defer { NSGraphicsContext.restoreGraphicsState() }
    NSGraphicsContext.current = context
    context.cgContext.scaleBy(x: CGFloat(size) / 1024, y: CGFloat(size) / 1024)

    let tile = NSBezierPath(roundedRect: NSRect(x: 96, y: 96, width: 832, height: 832), xRadius: 184, yRadius: 184)
    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.22)
    shadow.shadowBlurRadius = 34
    shadow.shadowOffset = NSSize(width: 0, height: -14)
    shadow.set()
    NSColor(calibratedRed: 0.10, green: 0.26, blue: 0.64, alpha: 1).setFill()
    tile.fill()
    NSGraphicsContext.restoreGraphicsState()
    NSGradient(starting: NSColor(calibratedRed: 0.10, green: 0.27, blue: 0.65, alpha: 1),
               ending: NSColor(calibratedRed: 0.20, green: 0.52, blue: 0.95, alpha: 1))!.draw(in: tile, angle: 90)
    NSColor.white.withAlphaComponent(0.16).setStroke()
    tile.lineWidth = 2
    tile.stroke()

    NSColor.white.withAlphaComponent(0.55).setFill()
    NSBezierPath(roundedRect: NSRect(x: 374, y: 560, width: 302, height: 222), xRadius: 30, yRadius: 30).fill()
    NSColor.white.setFill()
    NSBezierPath(roundedRect: NSRect(x: 348, y: 524, width: 316, height: 232), xRadius: 32, yRadius: 32).fill()
    NSColor(calibratedRed: 0.26, green: 0.51, blue: 0.82, alpha: 0.65).setFill()
    for (y, width) in [(CGFloat(676), CGFloat(186)), (CGFloat(621), CGFloat(132))] {
        NSBezierPath(roundedRect: NSRect(x: 398, y: y, width: width, height: 22), xRadius: 11, yRadius: 11).fill()
    }

    let tray = NSBezierPath()
    tray.move(to: NSPoint(x: 304, y: 540))
    tray.line(to: NSPoint(x: 364, y: 540))
    tray.curve(to: NSPoint(x: 386, y: 528), controlPoint1: NSPoint(x: 374, y: 540), controlPoint2: NSPoint(x: 381, y: 536))
    tray.line(to: NSPoint(x: 422, y: 475))
    tray.curve(to: NSPoint(x: 444, y: 462), controlPoint1: NSPoint(x: 428, y: 466), controlPoint2: NSPoint(x: 433, y: 462))
    tray.line(to: NSPoint(x: 580, y: 462))
    tray.curve(to: NSPoint(x: 602, y: 475), controlPoint1: NSPoint(x: 591, y: 462), controlPoint2: NSPoint(x: 596, y: 466))
    tray.line(to: NSPoint(x: 638, y: 528))
    tray.curve(to: NSPoint(x: 660, y: 540), controlPoint1: NSPoint(x: 643, y: 536), controlPoint2: NSPoint(x: 650, y: 540))
    tray.line(to: NSPoint(x: 720, y: 540))
    tray.curve(to: NSPoint(x: 776, y: 484), controlPoint1: NSPoint(x: 751, y: 540), controlPoint2: NSPoint(x: 776, y: 515))
    tray.line(to: NSPoint(x: 776, y: 330))
    tray.curve(to: NSPoint(x: 720, y: 274), controlPoint1: NSPoint(x: 776, y: 299), controlPoint2: NSPoint(x: 751, y: 274))
    tray.line(to: NSPoint(x: 304, y: 274))
    tray.curve(to: NSPoint(x: 248, y: 330), controlPoint1: NSPoint(x: 273, y: 274), controlPoint2: NSPoint(x: 248, y: 299))
    tray.line(to: NSPoint(x: 248, y: 484))
    tray.curve(to: NSPoint(x: 304, y: 540), controlPoint1: NSPoint(x: 248, y: 515), controlPoint2: NSPoint(x: 273, y: 540))
    tray.close()
    NSColor.white.setFill()
    tray.fill()
    NSColor(calibratedRed: 0.15, green: 0.37, blue: 0.73, alpha: 1).setFill()
    NSBezierPath(roundedRect: NSRect(x: 450, y: 355, width: 124, height: 24), xRadius: 12, yRadius: 12).fill()
    return bitmap.representation(using: .png, properties: [:])!
}

for size in [16, 32, 128, 256, 512] {
    try render(size).write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size * 2).write(to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
try render(1024).write(to: resources.appendingPathComponent("AppIcon.png"))
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", "-o", resources.appendingPathComponent("AppIcon.icns").path, iconset.path]
try process.run()
process.waitUntilExit()
guard process.terminationStatus == 0 else { fatalError("iconutil failed") }
print("AppIcon.png and AppIcon.icns generated")
