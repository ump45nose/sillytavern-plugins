import HubKit
import SwiftUI

struct PopoverView: View {
    @Environment(AppState.self) private var state
    @ViewState private var tab = 0

    var body: some View {
        let d = state.snapshot, v = state.agenda.view
        VStack(alignment: .leading, spacing: 0) {
            Segmented(options: [(0, "今天"), (1, "即将"), (2, "全部")], selection: $tab)
                .frame(maxWidth: .infinity)
            HStack(spacing: 8) {
                ForEach(d.attention.prefix(2)) { AttentionCard(item: $0) }
            }
            .fixedSize(horizontal: false, vertical: true)
            .padding(.top, 12)
            SyncNotice().padding(.top, 10)
            SectionTitle("日程").padding(.top, -4)
            events
            SectionTitle(tab == 2 ? "任务 · 全部清单" : "任务 · \(v.dueCount) 项到期")
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(tasks) { TaskRow(task: $0, showList: tab != 0) }
                    if tasks.isEmpty {
                        Text(tab == 1 ? "接下来一周没有到期的任务" : "今天没有到期的任务")
                            .font(Typo.sans(12)).foregroundStyle(Palette.ink3).padding(.vertical, 10)
                    }
                }
                .animation(Motion.spring, value: tasks.map(\.completed))
            }
            .scrollIndicators(.never)
            .frame(maxHeight: 300)
            .fixedSize(horizontal: false, vertical: true)
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

    private var tasks: [AgendaTask] {
        let v = state.agenda.view
        switch tab {
        case 0: return v.overdue + v.today
        case 1: return v.upcoming + v.later
        default: return v.allTasks.sorted { $0.listTitle < $1.listTitle }
        }
    }

    @ViewBuilder private var events: some View {
        let v = state.agenda.view, now = state.agenda.now
        if tab == 0 {
            if let e = v.currentEvent ?? v.nextEvent {
                let when = e.id == v.currentEvent?.id ? "进行中" : Agenda.countdown(to: e.start, now: now)
                EventBlock(event: e, caption: "\(Agenda.clock(e.start)) – \(Agenda.clock(e.end)) · \(when)")
            } else {
                Text("接下来没有日程").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
            }
        } else {
            VStack(spacing: 6) {
                ForEach(v.upcomingEvents.prefix(tab == 1 ? 3 : 5)) { e in
                    EventBlock(event: e, caption: "\(Agenda.relativeDay(e.start, now: now)) \(Agenda.clock(e.start)) – \(Agenda.clock(e.end))")
                }
                if v.upcomingEvents.isEmpty {
                    Text("接下来没有日程").font(Typo.sans(12)).foregroundStyle(Palette.ink3)
                }
            }
        }
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
