import HubKit
import SwiftUI

struct ModuleCard: View {
    var item: LayoutItem
    var index: Int
    var count: Int
    var highlighted = false
    @Environment(AppState.self) private var state
    @ViewState private var hovering = false

    private var info: ModuleInfo { item.module.info }
    private var compact: Bool { item.size == .compact }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if info.bare {
                ModuleBody(id: item.module, size: item.size)
            } else {
                header.padding(.bottom, 14)
                ModuleBody(id: item.module, size: item.size)
                    .frame(maxWidth: .infinity, maxHeight: compact ? .infinity : nil, alignment: .topLeading)
            }
        }
        .padding(info.bare ? EdgeInsets(top: 6, leading: 2, bottom: 8, trailing: 2) : EdgeInsets(top: 16, leading: 18, bottom: 18, trailing: 18))
        .frame(height: compact && !info.autoHeight ? Metrics.compactHeight : nil)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background { if !info.bare { cardBackground } }
        .overlay(alignment: .topTrailing) { if info.bare { tools.padding(.top, 2) } }
        .overlay { editOverlay }
        .overlay {
            RoundedRectangle(cornerRadius: Metrics.cardRadius)
                .stroke(Tone.clay.color.opacity(highlighted ? 0.55 : 0), lineWidth: highlighted ? 6 : 0)
                .padding(-3)
                .animation(.easeOut(duration: 0.9), value: highlighted)
        }
        .offset(y: hovering && !state.editing && !info.bare ? -2 : 0)
        .animation(Motion.fast, value: hovering)
        .onHover { hovering = $0 }
        .environment(\.moduleTone, info.tone)
    }

    private var header: some View {
        HStack(spacing: 9) {
            Image(systemName: info.symbol)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(info.tone.color)
                .frame(width: 26, height: 26)
                .background(RoundedRectangle(cornerRadius: 8).fill(info.tone.tint))
            Text(info.title).font(Typo.sans(13, .semibold)).foregroundStyle(Palette.ink).lineLimit(1)
            if !compact { Text(info.meta).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
            if let stamp = state.stamp(item.module) { Text(stamp).font(Typo.sans(11)).foregroundStyle(Palette.ink4).monospacedDigit() }
            if let status = state.hubStatus(item.module) { HubBadge(status: status) }
            Spacer(minLength: 0)
            tools
        }
        .frame(minHeight: 24)
    }

    private var tools: some View {
        HStack(spacing: 6) {
            if state.editing {
                HStack(spacing: 2) {
                    toolButton("chevron.left") { state.editPage { $0.move(at: index, by: -1) } }.disabled(index == 0)
                    toolButton("chevron.right") { state.editPage { $0.move(at: index, by: 1) } }.disabled(index == count - 1)
                }
            }
            HStack(spacing: 0) {
                sizeButton("简", .compact)
                sizeButton("详", .detail)
            }
            .padding(2)
            .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
        }
        .opacity(hovering || state.editing ? 1 : 0)
        .animation(Motion.fast, value: hovering)
    }

    private func sizeButton(_ label: String, _ size: ModuleSize) -> some View {
        let on = item.size == size
        return Button { if !on { state.editPage { $0.setSize(size, at: index) } } } label: {
            Text(label).font(Typo.sans(11, on ? .semibold : .regular))
                .foregroundStyle(on ? Palette.ink : Palette.ink3)
                .frame(width: 24, height: 20)
                .background(RoundedRectangle(cornerRadius: 6).fill(on ? Palette.card : .clear).shadow(color: .black.opacity(on ? 0.06 : 0), radius: 1, y: 1))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func toolButton(_ symbol: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 10, weight: .semibold)).foregroundStyle(Palette.ink2)
                .frame(width: 22, height: 22)
                .background(RoundedRectangle(cornerRadius: 6).fill(Palette.sunk))
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var cardBackground: some View {
        RoundedRectangle(cornerRadius: Metrics.cardRadius)
            .fill(Palette.card)
            .overlay(RoundedRectangle(cornerRadius: Metrics.cardRadius).strokeBorder(hovering ? Color(hex: "#E0D8C8") : Palette.line))
            .shadow(color: Color(red: 0.27, green: 0.18, blue: 0.06).opacity(hovering ? 0.16 : 0.04), radius: hovering ? 16 : 1.5, y: hovering ? 10 : 1)
    }

    @ViewBuilder private var editOverlay: some View {
        if state.editing {
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: Metrics.cardRadius)
                    .strokeBorder(Tone.clay.color.opacity(0.55), style: StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                    .padding(-4)
                Button { state.editPage { $0.remove(at: index) } } label: {
                    Image(systemName: "xmark").font(.system(size: 9, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 20, height: 20).background(Circle().fill(Palette.ink))
                }
                .buttonStyle(.plain)
                .offset(x: -10, y: -10)
            }
            .transition(.opacity)
        }
    }
}

private struct ModuleToneKey: EnvironmentKey {
    static let defaultValue: Tone = .clay
}

extension EnvironmentValues {
    var moduleTone: Tone {
        get { self[ModuleToneKey.self] }
        set { self[ModuleToneKey.self] = newValue }
    }
}

/// 12-column grid: items wrap greedily, each row takes the height of its tallest item.
struct ModuleGrid: Layout {
    var gap: CGFloat = Grid.gap

    struct Span: LayoutValueKey {
        static let defaultValue = 3
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 1000
        let heights = rowHeights(width: width, subviews: subviews)
        return CGSize(width: width, height: heights.reduce(0) { $0 + $1.1 } + gap * CGFloat(max(0, heights.count - 1)))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for (row, height) in rowHeights(width: bounds.width, subviews: subviews) {
            var x = bounds.minX
            for i in row {
                let w = Grid.width(span: subviews[i][Span.self], total: bounds.width)
                subviews[i].place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(width: w, height: height))
                x += w + gap
            }
            y += height + gap
        }
    }

    private func rowHeights(width: CGFloat, subviews: Subviews) -> [([Int], CGFloat)] {
        Grid.rows(spans: subviews.map { $0[Span.self] }).map { row in
            let h = row.map { i in
                subviews[i].sizeThatFits(ProposedViewSize(width: Grid.width(span: subviews[i][Span.self], total: width), height: nil)).height
            }.max() ?? 0
            return (row, h)
        }
    }
}
