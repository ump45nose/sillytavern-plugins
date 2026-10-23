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

    /// The final value sizes the view so the per-frame text never re-runs the surrounding layout.
    var body: some View {
        Text(prefix + Fmt.number(value, decimals) + suffix).monospacedDigit().hidden()
            .overlay(alignment: .leading) {
                CountingText(value: value * shown, decimals: decimals, prefix: prefix, suffix: suffix).fixedSize()
            }
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
    /// NumberFormatter is thread-safe once configured, and creating one per call showed up in animated numbers.
    nonisolated(unsafe) private static let formatters = (0...4).map(make)

    private static func make(_ decimals: Int) -> NumberFormatter {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = decimals
        f.maximumFractionDigits = decimals
        return f
    }

    static func number(_ v: Double, _ decimals: Int = 0) -> String {
        let f = formatters.indices.contains(decimals) ? formatters[decimals] : make(decimals)
        return f.string(from: NSNumber(value: v)) ?? "\(v)"
    }
}

/// Side by side when the proposed width allows, stacked otherwise. Unlike `ViewThatFits` it decides
/// from the width alone, so it never measures its children's ideal sizes.
struct AdaptiveRow: Layout {
    var threshold: CGFloat
    var spacing: CGFloat = 24
    var stackSpacing: CGFloat = 0

    /// A fixed column width in the side-by-side arrangement; other columns share what is left.
    struct Width: LayoutValueKey {
        static let defaultValue: CGFloat? = nil
    }

    private func widths(_ total: CGFloat, _ subviews: Subviews) -> [CGFloat] {
        let fixed = subviews.compactMap { $0[Width.self] }
        let flexible = subviews.count - fixed.count
        let rest = max(0, total - fixed.reduce(0, +) - spacing * CGFloat(max(0, subviews.count - 1)))
        return subviews.map { $0[Width.self] ?? (flexible > 0 ? rest / CGFloat(flexible) : 0) }
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? threshold
        if width >= threshold {
            let w = widths(width, subviews)
            let h = subviews.indices.map { subviews[$0].sizeThatFits(ProposedViewSize(width: w[$0], height: nil)).height }.max() ?? 0
            return CGSize(width: width, height: h)
        }
        let heights = subviews.map { $0.sizeThatFits(ProposedViewSize(width: width, height: nil)).height }
        return CGSize(width: width, height: heights.reduce(0, +) + stackSpacing * CGFloat(max(0, subviews.count - 1)))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        if bounds.width >= threshold {
            var x = bounds.minX
            for (i, w) in widths(bounds.width, subviews).enumerated() {
                subviews[i].place(at: CGPoint(x: x, y: bounds.minY), proposal: ProposedViewSize(width: w, height: nil))
                x += w + spacing
            }
        } else {
            var y = bounds.minY
            for s in subviews {
                let h = s.sizeThatFits(ProposedViewSize(width: bounds.width, height: nil)).height
                s.place(at: CGPoint(x: bounds.minX, y: y), proposal: ProposedViewSize(width: bounds.width, height: h))
                y += h + stackSpacing
            }
        }
    }
}

extension View {
    func adaptiveWidth(_ width: CGFloat) -> some View { layoutValue(key: AdaptiveRow.Width.self, value: width) }
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

/// One stop on the serif-clock timeline: time on the left, a dot on a hairline, content on the right.
struct TimelineEntry<Content: View>: View {
    var time: String
    var first = false
    var last = false
    var dot: Color = Palette.ink4.opacity(0.75)
    var timeColor: Color = Palette.ink3
    var timeWidth: CGFloat = 48
    var timeSize: CGFloat = 15
    /// Background behind the dot, so the hairline stops short of it.
    var ring: Color = Palette.card
    var gap: CGFloat = 20
    @ViewBuilder var content: Content

    var body: some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.bottom, last ? 0 : gap)
            .padding(.leading, timeWidth + 24)
            .background(alignment: .topLeading) {
                HStack(alignment: .top, spacing: 0) {
                    Text(time).font(Typo.serif(timeSize)).monospacedDigit().foregroundStyle(timeColor).lineLimit(1)
                        .frame(width: timeWidth, alignment: .trailing)
                    ZStack(alignment: .top) {
                        if !(first && last) {
                            Rectangle().fill(Palette.line).frame(width: 1, height: last ? 9 : nil)
                                .frame(maxHeight: .infinity, alignment: .top)
                                .padding(.top, first ? 9 : 0)
                        }
                        Circle().fill(dot).frame(width: 7, height: 7)
                            .background(Circle().fill(ring).frame(width: 13, height: 13))
                            .padding(.top, 6)
                    }
                    .frame(width: 24)
                    .frame(maxHeight: .infinity, alignment: .top)
                }
            }
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

/// Filled ink button for the one action that moves a flow forward; `.secondary` is the quiet companion.
struct HubButton: ButtonStyle {
    var primary = true
    @Environment(\.isEnabled) private var enabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Typo.sans(12.5, primary ? .semibold : .regular))
            .foregroundStyle(primary ? Color.white : Palette.ink)
            .padding(.horizontal, 14).frame(height: 30)
            .background(RoundedRectangle(cornerRadius: 8).fill(primary ? Palette.ink : Palette.sunk))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(primary ? Color.clear : Palette.line))
            .opacity(enabled ? (configuration.isPressed ? 0.8 : 1) : 0.4)
            .contentShape(Rectangle())
    }
}

extension ButtonStyle where Self == HubButton {
    static var hubPrimary: HubButton { HubButton() }
    static var hubSecondary: HubButton { HubButton(primary: false) }
}

/// A thin rounded knob with no slot. The system overlay scroller grows a grey track on hover.
final class HubScroller: NSScroller {
    override class var isCompatibleWithOverlayScrollers: Bool { true }

    override func drawKnobSlot(in slotRect: NSRect, highlight flag: Bool) {}

    override func drawKnob() {
        let knob = rect(for: .knob)
        let vertical = bounds.height >= bounds.width, thickness: CGFloat = 5
        let r = vertical ? NSRect(x: knob.maxX - thickness - 3, y: knob.minY + 3, width: thickness, height: max(knob.height - 6, thickness))
                         : NSRect(x: knob.minX + 3, y: knob.maxY - thickness - 3, width: max(knob.width - 6, thickness), height: thickness)
        NSColor(Palette.ink2).withAlphaComponent(0.32).setFill()
        NSBezierPath(roundedRect: r, xRadius: thickness / 2, yRadius: thickness / 2).fill()
    }

    static func adopt(_ scroll: NSScrollView) {
        scroll.scrollerStyle = .overlay
        if !(scroll.verticalScroller is HubScroller) { scroll.verticalScroller = HubScroller() }
        if !(scroll.horizontalScroller is HubScroller) { scroll.horizontalScroller = HubScroller() }    }
}

/// `ScrollView` whose scrollers are `HubScroller`s.
struct HubScroll<Content: View>: View {
    var axes: Axis.Set = .vertical
    @ViewBuilder var content: Content

    init(_ axes: Axis.Set = .vertical, @ViewBuilder content: () -> Content) {
        self.axes = axes
        self.content = content()
    }

    var body: some View {
        ScrollView(axes) { content.background(ScrollerProbe()) }
    }
}

private struct ScrollerProbe: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView { Probe() }
    func updateNSView(_ nsView: NSView, context: Context) {}

    final class Probe: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            DispatchQueue.main.async { [weak self] in
                if let scroll = self?.enclosingScrollView { HubScroller.adopt(scroll) }
            }
        }
    }
}

/// Warm switch in place of the system's blue one.
struct HubSwitch: ToggleStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 8) {
            configuration.label
            Capsule()
                .fill(configuration.isOn ? Tone.olive.color : Color(hex: "#E2DACB"))
                .frame(width: 34, height: 20)
                .overlay(alignment: configuration.isOn ? .trailing : .leading) {
                    Circle().fill(Palette.card).padding(2.5)
                        .shadow(color: .black.opacity(0.15), radius: 1, y: 1)
                }
                .contentShape(Capsule())
                .onTapGesture { withAnimation(Motion.fast) { configuration.isOn.toggle() } }
                .accessibilityAddTraits(.isButton)
                .accessibilityValue(configuration.isOn ? "开" : "关")
        }
    }
}

extension ToggleStyle where Self == HubSwitch {
    static var hub: HubSwitch { HubSwitch() }
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

/// The user's picked photo, or the first character of their name on clay.
struct UserAvatar: View {
    var size: CGFloat
    @Environment(AppState.self) private var state

    var body: some View {
        Group {
            if let image = state.avatar {
                Image(nsImage: image).resizable().scaledToFill()
            } else {
                Text(String(state.displayName.prefix(1))).font(Typo.sans(size * 0.43, .semibold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(Tone.clay.color)
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .overlay(Circle().strokeBorder(Palette.line))
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
