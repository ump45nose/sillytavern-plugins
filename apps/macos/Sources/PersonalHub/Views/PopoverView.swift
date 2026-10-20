import HubKit
import SwiftUI

struct PopoverView: View {
    @Environment(AppState.self) private var state
    @ViewState private var tab = 0

    var body: some View {
        let d = state.snapshot
        VStack(alignment: .leading, spacing: 0) {
            Segmented(options: [(0, "今天"), (1, "即将"), (2, "全部")], selection: $tab)
                .frame(maxWidth: .infinity)
            HStack(spacing: 8) {
                ForEach(d.attention.prefix(2)) { AttentionCard(item: $0) }
            }
            .fixedSize(horizontal: false, vertical: true)
            .padding(.top, 12)
            SectionTitle("日程").padding(.top, -4)
            EventBlock(event: d.events[2], caption: "19:00 – 20:30 · 1 小时后")
            SectionTitle("任务 · \(state.dueCount) 项到期")
            VStack(spacing: 0) {
                ForEach(tab == 1 ? d.tasks.upcoming : d.tasks.overdue + d.tasks.today) { t in
                    TaskRow(task: t, late: d.tasks.overdue.contains(t), showList: false)
                }
            }
            .animation(Motion.spring, value: tab)
            Button { state.showQuickTask() } label: {
                MiniInput(placeholder: "添加任务，例如「明天下午3点 开会」", shortcut: "⌃⌥Space")
            }
            .buttonStyle(.plain).padding(.top, 10)
            HStack(spacing: 8) {
                mini("步数", Fmt.number(Double(d.health.steps)))
                mini("今日支出", "¥\(Int(d.bills.today))")
                mini("Token", TokenFormat.short(d.token.today))
                mini("剩余流量", "\(Int(d.net.pools[0].remaining))G")
            }
            .padding(.top, 12)
            Rectangle().fill(Palette.line2).frame(height: 1).padding(.top, 12)
            HStack {
                Button { state.openMainWindow(nil) } label: {
                    HStack(spacing: 6) {
                        LogoMark().frame(width: 14, height: 14)
                        Text("打开 Personal Hub")
                    }
                }
                .buttonStyle(.plain)
                Spacer()
                Button { state.openSettings() } label: { Text("设置 ⌘,") }.buttonStyle(.plain)
            }
            .font(Typo.sans(12)).foregroundStyle(Palette.ink2)
            .padding(.top, 10)
        }
        .padding(14)
        .frame(width: 380)
        .background(Palette.card)
        .preferredColorScheme(.light)
    }

    private func mini(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label11(label)
            Text(value).font(Typo.serif(16)).monospacedDigit().lineLimit(1)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10).fill(Palette.sunk))
    }
}
