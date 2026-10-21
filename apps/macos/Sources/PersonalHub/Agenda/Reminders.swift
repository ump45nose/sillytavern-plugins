import Foundation
import HubKit
import UserNotifications

/// Local reminders: ten minutes before timed events, and 09:00 on the day a task is due.
@MainActor
final class Reminders: NSObject, UNUserNotificationCenterDelegate {
    static let shared = Reminders()
    private static let prefix = "hub.agenda."
    private static let eventLead: TimeInterval = 10 * 60
    private var lastSignature = ""

    /// Bare executables (swift run) have no bundle and would crash UNUserNotificationCenter.
    private var available: Bool { Bundle.main.bundleURL.pathExtension == "app" }

    func requestAuthorization() {
        guard available else { return }
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func clear() {
        guard available else { return }
        lastSignature = ""
        Task { await removeOurs(UNUserNotificationCenter.current()) }
    }

    func schedule(_ v: AgendaView, now: Date, calendar: Calendar = .hub) {
        guard available else { return }
        var requests: [(String, String, String, Date)] = []
        for e in v.upcomingEvents where e.start.timeIntervalSince(now) > Self.eventLead && e.start.timeIntervalSince(now) < 2 * 86_400 {
            let body = [Agenda.clock(e.start, calendar: calendar) + " – " + Agenda.clock(e.end, calendar: calendar), e.location]
                .compactMap { $0 }.joined(separator: " · ")
            requests.append(("event.\(e.id).\(Int(e.start.timeIntervalSince1970))", "\(e.title) · 10 分钟后", body, e.start.addingTimeInterval(-Self.eventLead)))
        }
        let byDay = Dictionary(grouping: (v.today + v.upcoming).filter { !$0.completed && $0.due != nil }) { $0.due! }
        for (day, tasks) in byDay {
            guard let fire = calendar.date(bySettingHour: 9, minute: 0, second: 0, of: day), fire > now else { continue }
            let title = tasks.count == 1 ? "今天到期：\(tasks[0].title)" : "今天有 \(tasks.count) 项任务到期"
            let body = tasks.prefix(4).map(\.title).joined(separator: "、")
            requests.append(("tasks.\(GoogleDate.dayString(day, calendar: calendar))", title, body, fire))
        }
        requests.sort { $0.3 < $1.3 }
        requests = Array(requests.prefix(48))
        let signature = requests.map { "\($0.0)|\($0.1)|\($0.2)" }.joined(separator: "\n")
        guard signature != lastSignature else { return }
        lastSignature = signature

        let center = UNUserNotificationCenter.current()
        let items = requests.map { id, title, body, fire -> UNNotificationRequest in
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            let parts = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: fire)
            return UNNotificationRequest(identifier: Self.prefix + id, content: content,
                                         trigger: UNCalendarNotificationTrigger(dateMatching: parts, repeats: false))
        }
        Task {
            await removeOurs(center)
            for item in items { try? await center.add(item) }
        }
    }

    // MARK: Attention

    private static let seenKey = "attentionNotified"

    /// Notifies once per hub attention id while its condition lasts. The first sync only records
    /// what is already active, so connecting does not replay every open item.
    func announce(_ items: [AttentionData.Item]) {
        guard available else { return }
        let defaults = UserDefaults.standard
        let current = Set(items.map(\.id))
        guard let stored = defaults.stringArray(forKey: Self.seenKey) else {
            defaults.set(Array(current), forKey: Self.seenKey)
            return
        }
        let fresh = items.filter { !stored.contains($0.id) }
        // Forget cleared conditions so a recurrence notifies again.
        defaults.set(Array(current), forKey: Self.seenKey)
        guard !fresh.isEmpty else { return }
        let center = UNUserNotificationCenter.current()
        let shown = fresh.prefix(3)
        for item in shown {
            let content = UNMutableNotificationContent()
            content.title = item.title
            if let s = item.subtitle, HubJSON.parseDate(s) == nil { content.body = s }
            content.sound = item.severity == "warn" ? .default : nil
            Task { try? await center.add(UNNotificationRequest(identifier: "hub.attention." + item.id, content: content, trigger: nil)) }
        }
        if fresh.count > shown.count {
            let content = UNMutableNotificationContent()
            content.title = "另有 \(fresh.count - shown.count) 件事需要注意"
            Task { try? await center.add(UNNotificationRequest(identifier: "hub.attention.more", content: content, trigger: nil)) }
        }
    }

    func forgetAttention() { UserDefaults.standard.removeObject(forKey: Self.seenKey) }

    private func removeOurs(_ center: UNUserNotificationCenter) async {
        let ids = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(Self.prefix) }
        center.removePendingNotificationRequests(withIdentifiers: ids)
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound])
    }
}
