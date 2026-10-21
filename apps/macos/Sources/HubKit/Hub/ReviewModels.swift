import Foundation

// personal-review through hub-api (docs/plans/2026-10-21-phase5-nas.md §4).

public enum ReviewKind: String, Codable, Sendable, CaseIterable {
    case daily, weekly

    public var title: String { self == .daily ? "日报" : "周报" }
}

public struct ReviewSummary: Codable, Equatable, Sendable, Identifiable {
    public enum State: String, Codable, Sendable {
        case open, finalized, expired

        /// An unknown state is never offered for confirmation.
        public init(from decoder: Decoder) throws {
            self = State(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .expired
        }
    }
    public var id: String
    public var kind: ReviewKind?
    public var label: String
    public var status: State
    public var preparedAt: Date?
    public var expiresAt: Date?
    public var memoName: String?

    public init(id: String, kind: ReviewKind?, label: String, status: State, preparedAt: Date? = nil, expiresAt: Date? = nil, memoName: String? = nil) {
        self.id = id
        self.kind = kind
        self.label = label
        self.status = status
        self.preparedAt = preparedAt
        self.expiresAt = expiresAt
        self.memoName = memoName
    }

    public var resolvedKind: ReviewKind { kind ?? (id.hasPrefix("weekly:") ? .weekly : .daily) }
}

public struct GoalsData: Codable, Equatable, Sendable {
    public struct Mainline: Codable, Equatable, Sendable {
        public var domain: String?
        public var direction: String?, purpose: String?, meaning: String?, status: String?, recentChange: String?
        public var memoName: String?
        public var updatedAt: Date?
    }
    public struct Cycle: Codable, Equatable, Sendable {
        public var id: String
        public var index: Int?
        public var status: String
        public var startsAt: Date
        public var endsAt: Date
        public var day: Int?, total: Int?
        public var precloseAt: Date?
    }
    public struct Comment: Codable, Equatable, Sendable { public var text: String; public var createdAt: Date? }
    public struct Goal: Codable, Equatable, Sendable, Identifiable {
        public var id: String
        public var domain: String
        public var status: String
        public var goal: String
        public var progress: String?, deadline: String?
        public var successCriteria: String?, stopSignal: String?
        public var memoName: String?
        public var latestComment: Comment?
    }
    public struct Reviews: Codable, Equatable, Sendable {
        public var daily: ReviewSummary?
        public var weekly: ReviewSummary?
        public var nextDailyAt: Date?
        public var nextWeeklyAt: Date?
    }
    public struct Close: Codable, Equatable, Sendable {
        public enum State: String, Codable, Sendable {
            case none, preclose, awaitingClose = "awaiting_close", closed

            public init(from decoder: Decoder) throws {
                self = State(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .none
            }
        }
        public var status: State
        public var cycleId: String?
        public var template: String?

        public init(status: State, cycleId: String?, template: String?) {
            self.status = status
            self.cycleId = cycleId
            self.template = template
        }
    }
    public var mainline: Mainline?
    public var cycle: Cycle?
    public var goals: [Goal]?
    public var reviews: Reviews?
    public var close: Close?
}

public struct ReviewSession: Codable, Equatable, Sendable, Identifiable {
    public struct Section: Codable, Equatable, Sendable { public var title: String; public var blocks: [String] }
    public struct Material: Codable, Equatable, Sendable { public var sections: [Section]; public var template: String }
    public struct Delivered: Codable, Equatable, Sendable { public var text: String; public var deliveredAt: Date? }
    public struct Rules: Codable, Equatable, Sendable {
        public var fields: [String]
        public var autoFields: [String]?
        public var summaryMaxChars: Int?
        public var summaryMaxListSeparators: Int?
        public var maxUnresolved: Int?
        public var momentMinChars: Int?
        public var emotionWords: [String]?
    }
    public var id: String
    public var kind: ReviewKind
    public var label: String
    public var status: ReviewSummary.State
    public var preparedAt: Date?
    public var expiresAt: Date?
    public var memoName: String?
    public var material: Material?
    public var delivered: Delivered?
    public var finalContent: String?
    public var rules: Rules?
}

public struct ReviewPage: Codable, Equatable, Sendable { public var items: [ReviewSummary] }

public struct ReviewPreview: Codable, Equatable, Sendable { public var content: String }

public struct ReviewFinalized: Codable, Equatable, Sendable {
    public var status: String
    public var memoName: String?
    public var already: Bool?
}

/// Shared reply of the stage writes: `dry-run` carries the content that would be written.
public struct StageResult: Codable, Equatable, Sendable {
    public var status: String
    public var content: String?
    public var memoName: String?
    public var commentName: String?
    public var cycleId: String?
    public var goalId: String?

    public init(status: String, content: String? = nil) {
        self.status = status
        self.content = content
    }

    public var isDryRun: Bool { status == "dry-run" }
}

public struct GoalDraft: Codable, Equatable, Sendable {
    public var domain: String
    public var goal: String
    public var progress: String
    public var deadline: String
    public var successCriteria: String
    public var stopSignal: String

    public init(domain: String, goal: String = "", progress: String = "", deadline: String, successCriteria: String = "", stopSignal: String = "") {
        self.domain = domain
        self.goal = goal
        self.progress = progress
        self.deadline = deadline
        self.successCriteria = successCriteria
        self.stopSignal = stopSignal
    }

    public var isComplete: Bool {
        [goal, progress, deadline, successCriteria, stopSignal].allSatisfy { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }
}

public enum Stage {
    /// personal-review's `stages.domains`; it validates them again.
    public static let domains = ["关系", "身体", "财务", "生活", "事业"]
    public static let outcomes = ["成功", "失败", "停止"]
    public static let maxGoals = 5
}
