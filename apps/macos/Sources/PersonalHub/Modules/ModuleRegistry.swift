import HubKit
import SwiftUI

struct ModuleInfo {
    var title: String
    var symbol: String
    var tone: Tone
    var meta: String
    /// Rendered without card chrome (the greeting on the home page).
    var bare = false
    /// The compact size grows with its content instead of the fixed tile height.
    var autoHeight = false
    /// The detail body scrolls its own columns, so the card keeps this height unless a preset overrides it.
    var detailHeight: CGFloat?
}

extension ModuleID {
    var info: ModuleInfo {
        switch self {
        case .brief: ModuleInfo(title: "今日简报", symbol: "sun.max", tone: .clay, meta: "汇总所有模块", bare: true)
        case .agenda: ModuleInfo(title: "日程与任务", symbol: "calendar", tone: .sky, meta: "Google 日历 · Tasks")
        case .goals: ModuleInfo(title: "主线与复盘", symbol: "scope", tone: .clay, meta: "personal-review · Memos")
        case .attention: ModuleInfo(title: "需要注意", symbol: "bell", tone: .ochre, meta: "跨模块提醒", autoHeight: true)
        case .health: ModuleInfo(title: "健康", symbol: "heart", tone: .olive, meta: "personal-records")
        case .bills: ModuleInfo(title: "账单", symbol: "creditcard", tone: .kraft, meta: "personal-records · AutoAccounting")
        case .crm: ModuleInfo(title: "交流", symbol: "person.2", tone: .rose, meta: "personal-crm · 录音附属")
        case .media: ModuleInfo(title: "媒体", symbol: "play.rectangle", tone: .plum, meta: "Emby · Navidrome · qBittorrent")
        case .token: ModuleInfo(title: "Token 用量", symbol: "hexagon", tone: .clay, meta: "Token Monitor")
        case .git: ModuleInfo(title: "GitHub", symbol: "arrow.triangle.branch", tone: .olive, meta: "ump45nose · 通知与 PR")
        case .net: ModuleInfo(title: "网络", symbol: "wifi", tone: .sage, meta: "usage-monitor")
        case .subs: ModuleInfo(title: "订阅", symbol: "repeat", tone: .ochre, meta: "hub 偏好 · 账单识别")
        case .sky: ModuleInfo(title: "电脑历史", symbol: "desktopcomputer", tone: .steel, meta: "skysight-sync")
        case .memos: ModuleInfo(title: "Memos", symbol: "note.text", tone: .sky, meta: "memos · 快速 Memo")
        case .plaud: ModuleInfo(title: "录音", symbol: "waveform", tone: .rose, meta: "Plaud · 转录稿", detailHeight: 560)
        }
    }
}

struct ModuleBody: View {
    var id: ModuleID
    var size: ModuleSize

    var body: some View {
        switch id {
        case .brief: BriefModule(size: size)
        case .agenda: AgendaModule(size: size)
        case .goals: GoalsModule(size: size)
        case .attention: AttentionModule(size: size)
        case .health: HealthModule(size: size)
        case .bills: BillsModule(size: size)
        case .crm: CRMModule(size: size)
        case .media: MediaModule(size: size)
        case .token: TokenModule(size: size)
        case .git: GitModule(size: size)
        case .net: NetModule(size: size)
        case .subs: SubsModule(size: size)
        case .sky: SkyModule(size: size)
        case .memos: MemosModule(size: size)
        case .plaud: PlaudModule(size: size)
        }
    }
}
