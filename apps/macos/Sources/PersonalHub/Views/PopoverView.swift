import HubKit
import SwiftUI

struct PopoverView: View {
    @Environment(AppState.self) private var state
    @ViewState private var tab = 0

    var body: some View {
        let v = state.agenda.view, attention = state.attention
        VStack(alignment: .leading, spacing: 0) {
            Segmented(options: [(0, "今天"), (1, "即将"), (2, "全部")], selection: $tab)
                .frame(maxWidth: .infinity)
            if !attention.isEmpty {
                HStack(spacing: 8) {
                    ForEach(attention.prefix(2)) { a in
                        Button { state.open(a) } label: { AttentionCard(item: a) }.buttonStyle(.plain)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 12)
            }
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
            HStack(spacing: 8) { minis }
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

    @ViewBuilder private var minis: some View {
        let d = state.hub.data
        mini("步数", d.health?.data?.steps.map { Fmt.number($0) } ?? "—")
        mini("今日支出", d.bills?.data?.todayTotal.map { "¥" + Fmt.number($0, $0 >= 1000 ? 0 : 2) } ?? "—")
        let token = d.token[.day]?.data
        mini("Token", (token?.today?.total ?? token?.total).map { TokenFormat.short($0 / 1_000_000) } ?? "—")
        let net = d.net?.data
        if let p = net?.pools?.first, let used = p.usedBytes, let total = p.totalBytes {
            mini("剩余流量", HubFormat.gb(max(0, total - used), 0) + "G")
        } else {
            mini("今日流量", net?.today.map { HubFormat.gb(($0.downBytes ?? 0) + ($0.upBytes ?? 0)) + "G" } ?? "—")
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
