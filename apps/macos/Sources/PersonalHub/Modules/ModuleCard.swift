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
    private var fixedHeight: CGFloat? { info.bare ? nil : item.effectiveHeight.map { CGFloat($0.points) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if info.bare {
                ModuleBody(id: item.module, size: item.size)
            } else if fixedHeight != nil {
                header.padding(.bottom, 14)
                HubScroll {
                    ModuleBody(id: item.module, size: item.size).frame(maxWidth: .infinity, alignment: .topLeading)
                }
                .frame(maxHeight: .infinity)
            } else {
                header.padding(.bottom, 14)
                ModuleBody(id: item.module, size: item.size)
                    .frame(maxWidth: .infinity, maxHeight: compact ? .infinity : nil, alignment: .topLeading)
            }
        }
        .padding(info.bare ? EdgeInsets(top: 6, leading: 2, bottom: 8, trailing: 2) : EdgeInsets(top: 16, leading: 18, bottom: 18, trailing: 18))
        .frame(height: compact && !info.autoHeight ? Metrics.compactHeight : fixedHeight)
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
            if !compact && !state.editing { Text(info.meta).font(Typo.sans(11)).foregroundStyle(Palette.ink3).lineLimit(1) }
            if !state.editing, let stamp = state.stamp(item.module) { Text(stamp).font(Typo.sans(11)).foregroundStyle(Palette.ink4).monospacedDigit() }
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
                if !compact {
                    let span = item.effectiveSpan
                    HStack(spacing: 2) {
                        toolButton("arrow.right.and.line.vertical.and.arrow.left") { state.editPage { $0.resize(at: index, by: -1) } }
                            .disabled(span <= Page.spanRange.lowerBound).help("变窄")
                        Text("\(span)/12").font(Typo.sans(10.5)).foregroundStyle(Palette.ink3).monospacedDigit().frame(width: 34)
                        toolButton("arrow.left.and.line.vertical.and.arrow.right") { state.editPage { $0.resize(at: index, by: 1) } }
                            .disabled(span >= Page.spanRange.upperBound).help("变宽")
                    }
                    if !info.bare {
                        segments([("自", nil), ("中", .medium), ("高", .tall)] as [(String, ModuleHeight?)], item.height) { h in
                            state.editPage { $0.setHeight(h, at: index) }
                        }
                        .help("卡片高度：自动 / 中 / 高，超出部分在卡片内滚动")
                    }
                }
            }
            segments([("简", .compact), ("详", .detail)] as [(String, ModuleSize)], item.size) { size in
                state.editPage { $0.setSize(size, at: index) }
            }
        }
        .opacity(hovering || state.editing ? 1 : 0)
        .animation(Motion.fast, value: hovering)
    }

    private func segments<V: Equatable>(_ options: [(String, V)], _ current: V, _ pick: @escaping (V) -> Void) -> some View {
        HStack(spacing: 0) {
            ForEach(options.indices, id: \.self) { i in
                let (label, value) = options[i]
                let on = value == current
                Button { if !on { pick(value) } } label: {
                    Text(label).font(Typo.sans(11, on ? .semibold : .regular))
                        .foregroundStyle(on ? Palette.ink : Palette.ink3)
                        .frame(width: 24, height: 20)
                        .background(RoundedRectangle(cornerRadius: 6).fill(on ? Palette.card : .clear).shadow(color: .black.opacity(on ? 0.06 : 0), radius: 1, y: 1))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(2)
        .background(RoundedRectangle(cornerRadius: 8).fill(Palette.sunk))
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

/// 12-column grid: items wrap greedily and keep their own height, so a tall neighbour no longer
/// stretches a short card; the row advances by its tallest item.
struct ModuleGrid: Layout {
    var gap: CGFloat = Grid.gap

    struct Span: LayoutValueKey {
        static let defaultValue = 3
    }

    struct Measured {
        var width: CGFloat = -1
        var rows: [[Int]] = []
        var heights: [CGFloat] = []
    }

    func makeCache(subviews: Subviews) -> Measured { Measured() }

    func updateCache(_ cache: inout Measured, subviews: Subviews) { cache = Measured() }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Measured) -> CGSize {
        let width = proposal.width ?? 1000
        measure(width, subviews, &cache)
        let total = cache.rows.reduce(0) { $0 + rowHeight($1, cache) } + gap * CGFloat(max(0, cache.rows.count - 1))
        return CGSize(width: width, height: total)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Measured) {
        measure(bounds.width, subviews, &cache)
        var y = bounds.minY
        for row in cache.rows {
            var x = bounds.minX
            for i in row {
                let w = Grid.width(span: subviews[i][Span.self], total: bounds.width)
                subviews[i].place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(width: w, height: cache.heights[i]))
                x += w + gap
            }
            y += rowHeight(row, cache) + gap
        }
    }

    private func rowHeight(_ row: [Int], _ cache: Measured) -> CGFloat { row.map { cache.heights[$0] }.max() ?? 0 }

    private func measure(_ width: CGFloat, _ subviews: Subviews, _ cache: inout Measured) {
        guard cache.width != width || cache.heights.count != subviews.count else { return }
        cache.width = width
        cache.rows = Grid.rows(spans: subviews.map { $0[Span.self] })
        cache.heights = subviews.map { s in
            s.sizeThatFits(ProposedViewSize(width: Grid.width(span: s[Span.self], total: width), height: nil)).height
        }
    }
}
