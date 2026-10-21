import HubKit
import SwiftUI

// MARK: - Motion helpers

/// Fires once on appear; respects Reduce Motion by jumping straight to the end state.
struct AppearProgress: ViewModifier {
    var delay: Double = 0
    var animation: Animation = Motion.grow
    @Binding var progress: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.onAppear {
            if reduceMotion { progress = 1; return }
            withAnimation(animation.delay(delay)) { progress = 1 }
        }
    }
}

struct Rise: ViewModifier {
    var index: Int
    @ViewState private var shown: CGFloat = 0

    func body(content: Content) -> some View {
        content
            .opacity(shown)
            .offset(y: (1 - shown) * 12)
            .modifier(AppearProgress(delay: Double(index) * Motion.stagger, animation: Motion.rise, progress: $shown))
    }
}

extension View {
    func rise(_ index: Int) -> some View { modifier(Rise(index: index)) }
}

/// Number that counts up from zero the first time it appears.
struct CountUp: View {
    var value: Double
    var decimals = 0
    var prefix = ""
    var suffix = ""
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        CountingText(value: value * shown, decimals: decimals, prefix: prefix, suffix: suffix)
            .modifier(AppearProgress(animation: .timingCurve(0.25, 1, 0.5, 1, duration: 1.1), progress: $shown))
    }
}

private struct CountingText: View, Animatable {
    var value: Double
    var decimals: Int
    var prefix: String
    var suffix: String
    var animatableData: Double {
        get { value }
        set { value = newValue }
    }

    var body: some View { Text(prefix + Fmt.number(value, decimals) + suffix).monospacedDigit() }
}

enum Fmt {
    static func number(_ v: Double, _ decimals: Int = 0) -> String {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = decimals
        f.maximumFractionDigits = decimals
        return f.string(from: NSNumber(value: v)) ?? "\(v)"
    }
}

// MARK: - Text styles

struct Hero: View {
    var value: Double
    var decimals = 0
    var prefix = ""
    var unit: String? = nil
    var size: CGFloat = 38

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            CountUp(value: value, decimals: decimals, prefix: prefix)
                .font(Typo.serif(size))
                .tracking(-0.5)
                .foregroundStyle(Palette.ink)
            if let unit { Text(unit).font(Typo.sans(12)).foregroundStyle(Palette.ink3) }
        }
    }
}

struct Label11: View {
    var text: String
    init(_ text: String) { self.text = text }
    var body: some View { Text(text).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
}

struct SectionTitle: View {
    var title: String
    init(_ title: String) { self.title = title }
    var body: some View {
        HStack(spacing: 8) {
            Text(title).font(Typo.sans(11)).foregroundStyle(Palette.ink3).tracking(0.5).fixedSize()
            Rectangle().fill(Palette.line2).frame(height: 1)
        }
        .padding(.top, 18).padding(.bottom, 8)
    }
}

struct Stat: View {
    var label: String
    var value: String
    var unit: String? = nil
    var color: Color = Palette.ink

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Label11(label)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(value).font(Typo.serif(19)).foregroundStyle(color).monospacedDigit().lineLimit(1)
                if let unit { Text(unit).font(Typo.sans(11)).foregroundStyle(Palette.ink3) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

// MARK: - Chips & small controls

struct Chip: View {
    var text: String
    var tone: Tone? = nil
    var systemImage: String? = nil

    var body: some View {
        HStack(spacing: 5) {
            if let systemImage { Image(systemName: systemImage).font(.system(size: 10, weight: .semibold)) }
            Text(text).lineLimit(1)
        }
        .font(Typo.sans(11.5, tone == nil ? .regular : .medium))
        .foregroundStyle(tone?.color ?? Palette.ink2)
        .padding(.horizontal, 10).padding(.vertical, 3.5)
        .background(Capsule().fill(tone?.tint ?? Palette.sunk))
        .overlay(Capsule().strokeBorder(tone == nil ? Palette.line2 : .clear))
        .fixedSize()
    }
}

struct Dot: View {
    var color: Color
    var pulse = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Circle().fill(color).frame(width: 7, height: 7)
            .background { if pulse && !reduceMotion { PulseHalo(color: NSColor(color)).frame(width: 7, height: 7) } }
    }
}

/// Endless halo driven by Core Animation; a SwiftUI `repeatForever` would re-run window layout every frame.
private struct PulseHalo: NSViewRepresentable {
    var color: NSColor

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        view.wantsLayer = true
        let halo = CALayer()
        halo.backgroundColor = color.withAlphaComponent(0.45).cgColor
        halo.frame = CGRect(x: 0, y: 0, width: 7, height: 7)
        halo.cornerRadius = 3.5
        let scale = CABasicAnimation(keyPath: "transform.scale")
        scale.fromValue = 1
        scale.toValue = 2.6
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = 1
        fade.toValue = 0
        let group = CAAnimationGroup()
        group.animations = [scale, fade]
        group.duration = 2
        group.timingFunction = CAMediaTimingFunction(name: .easeOut)
        group.repeatCount = .infinity
        group.isRemovedOnCompletion = false
        halo.add(group, forKey: "pulse")
        view.layer?.addSublayer(halo)
        view.layer?.masksToBounds = false
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}

struct Kbd: View {
    var text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text).font(Typo.sans(10.5)).foregroundStyle(Palette.ink3)
            .padding(.horizontal, 6).padding(.vertical, 1.5)
            .background(RoundedRectangle(cornerRadius: 5).fill(Palette.card))
            .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(Palette.line))
    }
}

struct MiniInput: View {
    var placeholder: String
    var shortcut: String
    var icon: String? = "plus"
    var height: CGFloat = 34

    var body: some View {
        HStack(spacing: 8) {
            if let icon { Image(systemName: icon).font(.system(size: 11, weight: .semibold)).foregroundStyle(Palette.ink3) }
            Text(placeholder).font(Typo.sans(12)).foregroundStyle(Palette.ink3).lineLimit(1)
            Spacer(minLength: 4)
            Kbd(shortcut)
        }
        .padding(.horizontal, 12).frame(height: height)
        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Palette.line2))
    }
}

struct Segmented<T: Hashable>: View {
    var options: [(T, String)]
    @Binding var selection: T
    var small = false
    @Namespace private var ns

    var body: some View {
        HStack(spacing: 2) {
            ForEach(options, id: \.0) { value, label in
                let on = value == selection
                Button { withAnimation(Motion.spring) { selection = value } } label: {
                    Text(label).font(Typo.sans(small ? 11 : 12.5, on ? .semibold : .regular))
                        .foregroundStyle(on ? Palette.ink : Palette.ink3)
                        .lineLimit(1).fixedSize(horizontal: small, vertical: false)
                        .padding(.horizontal, small ? 8 : 14).padding(.vertical, small ? 2 : 4)
                        .background {
                            if on {
                                RoundedRectangle(cornerRadius: small ? 5 : 7).fill(Palette.card)
                                    .shadow(color: .black.opacity(0.08), radius: 1, y: 1)
                                    .matchedGeometryEffect(id: "seg", in: ns)
                            }
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(small ? 2 : 3)
        .background(RoundedRectangle(cornerRadius: small ? 7 : 10).fill(Palette.sunk))
    }
}

struct Legend: View {
    var items: [(String, Color)]
    var body: some View {
        Flow(spacing: 10) {
            ForEach(items.indices, id: \.self) { i in
                HStack(spacing: 5) {
                    RoundedRectangle(cornerRadius: 2).fill(items[i].1).frame(width: 8, height: 8)
                    Text(items[i].0).font(Typo.sans(11)).foregroundStyle(Palette.ink2).lineLimit(1)
                }
            }
        }
    }
}

// MARK: - Charts

struct Track: View {
    var value: Double
    var color: Color
    var height: CGFloat = 6
    var delay: Double = 0
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color(hex: "#EEE8DC"))
                Capsule().fill(color).frame(width: geo.size.width * min(1, value / 100) * shown)
            }
        }
        .frame(height: height)
        .modifier(AppearProgress(delay: 0.1 + delay / 1000, progress: $shown))
    }
}

struct Ring: View {
    var value: Double
    var color: Color
    var size: CGFloat
    var width: CGFloat
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        ZStack {
            Circle().stroke(Color(hex: "#EEE8DC"), lineWidth: width)
            Circle().trim(from: 0, to: min(1, value / 100) * shown)
                .stroke(color, style: StrokeStyle(lineWidth: width, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
        .padding(width / 2)
        .frame(width: size, height: size)
        .modifier(AppearProgress(delay: 0.15, animation: .timingCurve(0.2, 0.8, 0.2, 1, duration: 1.1), progress: $shown))
    }
}

struct ArcGauge: View {
    var value: Double
    var color: Color
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        ZStack {
            arc.stroke(Color(hex: "#EEE8DC"), style: StrokeStyle(lineWidth: 10, lineCap: .round))
            arc.trim(from: 0, to: value / 100 * shown).stroke(color, style: StrokeStyle(lineWidth: 10, lineCap: .round))
        }
        .frame(width: 132, height: 74)
        .modifier(AppearProgress(delay: 0.15, animation: .timingCurve(0.2, 0.8, 0.2, 1, duration: 1.1), progress: $shown))
    }

    private var arc: Path {
        var p = Path()
        p.addArc(center: CGPoint(x: 66, y: 68), radius: 54, startAngle: .degrees(180), endAngle: .degrees(0), clockwise: false)
        return p
    }
}

struct Bars: View {
    /// nil is an unknown value: drawn as a faint stub rather than as zero.
    var values: [Double?]
    var height: CGFloat = 64
    var color: Color
    var highlight: Set<Int>? = nil
    var labels: [String]? = nil
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        let maxV = max(values.compactMap { $0 }.max() ?? 1, 0.000_001)
        VStack(spacing: 5) {
            HStack(alignment: .bottom, spacing: 0) {
                ForEach(values.indices, id: \.self) { i in
                    let on = highlight.map { $0.contains(i) } ?? (i == values.count - 1)
                    RoundedRectangle(cornerRadius: 1.6)
                        .fill(values[i] == nil ? Palette.line2 : on ? color : Color(hex: "#E7E0D2"))
                        .frame(height: values[i].map { max(1.5, $0 / maxV * height) } ?? 1)
                        .scaleEffect(x: 1, y: shown, anchor: .bottom)
                        .animation(Motion.grow.delay(Double(i) * 0.028), value: shown)
                        .padding(.horizontal, 0)
                        .frame(maxWidth: .infinity)
                        .padding(.horizontal, 2)
                }
            }
            .frame(height: height, alignment: .bottom)
            if let labels {
                HStack(spacing: 0) {
                    ForEach(labels.indices, id: \.self) { i in
                        Text(labels[i]).font(Typo.sans(10)).foregroundStyle(Palette.ink4).frame(maxWidth: .infinity)
                    }
                }
            }
        }
        .modifier(AppearProgress(animation: .linear(duration: 0.01), progress: $shown))
    }

    /// Day-of-month on every other bar, ending with 今 for today. `dates` are `YYYY-MM-DD`.
    static func dayLabels(_ dates: [String]) -> [String] {
        dates.indices.map { i in
            if i == dates.count - 1 { return "今" }
            guard (dates.count - 1 - i) % 2 == 0, let d = Int(dates[i].suffix(2)) else { return "" }
            return "\(d)"
        }
    }
}

struct AreaLine: View {
    var values: [Double]
    var height: CGFloat = 56
    var color: Color
    @ViewState private var shown: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let pts = points(in: geo.size)
            ZStack(alignment: .topLeading) {
                Path { p in
                    p.move(to: CGPoint(x: 0, y: geo.size.height))
                    pts.forEach { p.addLine(to: $0) }
                    p.addLine(to: CGPoint(x: geo.size.width, y: geo.size.height))
                    p.closeSubpath()
                }
                .fill(LinearGradient(colors: [color.opacity(0.22), color.opacity(0)], startPoint: .top, endPoint: .bottom))
                .opacity(shown)
                Path { p in p.addLines(pts) }
                    .trim(from: 0, to: shown)
                    .stroke(color, style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
                if let last = pts.last {
                    Circle().fill(color).frame(width: 8, height: 8)
                        .overlay(Circle().stroke(Palette.card, lineWidth: 3).padding(-1.5))
                        .position(last).opacity(shown)
                }
            }
        }
        .frame(height: height)
        .modifier(AppearProgress(delay: 0.15, animation: .timingCurve(0.2, 0.8, 0.2, 1, duration: 1.1), progress: $shown))
    }

    private func points(in size: CGSize) -> [CGPoint] {
        guard values.count > 1, let lo = values.min(), let hi = values.max() else { return [] }
        let pad: CGFloat = 5, range = (hi - lo) == 0 ? 1 : hi - lo
        return values.enumerated().map { i, v in
            CGPoint(x: CGFloat(i) / CGFloat(values.count - 1) * size.width,
                    y: size.height - pad - CGFloat((v - lo) / range) * (size.height - pad * 2))
        }
    }
}

/// GitHub-style contribution grid with fixed cell size.
struct ContributionGrid: View {
    var weeks: Int
    var seed: Int64 = 7
    var cell: CGFloat = 11
    var gap: CGFloat = 3

    var body: some View {
        let levels = Self.levels(weeks: weeks, seed: seed)
        HStack(spacing: gap) {
            ForEach(0..<weeks, id: \.self) { w in
                VStack(spacing: gap) {
                    ForEach(0..<7, id: \.self) { d in
                        let i = w * 7 + d
                        RoundedRectangle(cornerRadius: 2)
                            .fill(i == weeks * 7 - 1 ? Palette.gitHeat[4] : Palette.gitHeat[levels[i]])
                            .frame(width: cell, height: cell)
                    }
                }
            }
        }
        .fixedSize()
    }

    static func levels(weeks: Int, seed: Int64) -> [Int] {
        var s = seed
        return (0..<weeks * 7).map { _ in
            s = (s * 16807) % 2147483647
            let v = Double(s) / 2147483647
            return v < 0.32 ? 0 : v < 0.58 ? 1 : v < 0.8 ? 2 : v < 0.93 ? 3 : 4
        }
    }
}

struct PersonBadge: View {
    var initial: String
    var tone: Tone
    var size: CGFloat = 30

    var body: some View {
        Text(initial).font(Typo.sans(size * 0.42, .semibold)).foregroundStyle(tone.color)
            .frame(width: size, height: size)
            .background(Circle().fill(tone.tint))
            .overlay(Circle().stroke(Palette.card, lineWidth: 2))
    }
}

struct Waveform: View {
    var bars = 38
    var seed: Int64 = 3
    var color: Color

    var body: some View {
        var s = seed
        let heights: [CGFloat] = (0..<bars).map { i in
            s = (s * 16807) % 2147483647
            return 0.2 + abs(sin(Double(i) * 0.5)) * 0.5 + Double(s) / 2147483647 * 0.3
        }
        return GeometryReader { geo in
            HStack(alignment: .center, spacing: 2) {
                ForEach(heights.indices, id: \.self) { i in
                    Capsule().fill(color.opacity(0.75)).frame(width: 2, height: geo.size.height * heights[i])
                }
            }
            .frame(maxHeight: .infinity)
        }
    }
}
