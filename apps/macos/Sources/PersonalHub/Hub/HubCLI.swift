import Foundation
import HubKit

/// Terminal entry points for hub-api. Output is limited to statuses, counts and sizes: never
/// tokens, personal content or values.
enum HubCLI {
    /// `--hub-token-stdin [URL]`: reads a device token from stdin, checks it against hub-api and
    /// stores it in the keychain vault next to the Google credential.
    static func storeToken(base: URL) async -> Int32 {
        let input = FileHandle.standardInput.readDataToEndOfFile()
        let token = String(decoding: input, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: "\"'")))
        guard !token.isEmpty, !token.contains(where: \.isWhitespace) else {
            print("FAIL token: nothing usable on stdin")
            return 2
        }
        let credential = HubCredential(baseURL: base, token: token, deviceID: "dev-token")
        do {
            let sources = try await HubAPI(transport: URLSessionTransport(), credential: credential).status()
            print("PASS status: \(sources.count) sources, \(sources.filter { $0.status == .ok }.count) ok")
        } catch let e as HubError {
            print("FAIL status: \(describe(e))")
            return 1
        } catch {
            print("FAIL status: \(type(of: error))")
            return 1
        }
        do {
            try CredentialStore.update { $0.hub = credential }
        } catch {
            print("FAIL keychain: \((error as? CredentialStore.Failure)?.errorDescription ?? "\(type(of: error))")")
            return 1
        }
        DistributedNotificationCenter.default().postNotificationName(HubModel.changed, object: nil, userInfo: nil, deliverImmediately: true)
        print("PASS stored: \(base.absoluteString)")
        return 0
    }

    /// Enum-like fields whose distinct values are safe to show.
    private static let enums: Set<String> = ["state", "status", "currency", "cycle", "category", "payer", "type", "visibility",
                                             "region", "kind", "collector", "provider", "unit", "source", "pinned", "stale", "active"]

    /// `--hub-probe PATH [k=v …]`: the response's shape as key paths with types and counts; values only for `enums`.
    static func probe(_ path: String, query: [String: String]) async -> Int32 {
        guard let credential = try? CredentialStore.load().hub else {
            print("FAIL credentials: hub not connected")
            return 2
        }
        let data: Data
        do {
            data = try await HubAPI(transport: URLSessionTransport(), credential: credential).probe(path, query: query)
        } catch let e as HubError {
            print("FAIL \(path) — \(describe(e))")
            return 1
        } catch {
            print("FAIL \(path) — \(type(of: error))")
            return 1
        }
        guard let json = try? JSONSerialization.jsonObject(with: data) else {
            print("PASS \(path) — \(data.count) bytes, not JSON")
            return 0
        }
        var shape: [String: (types: Set<String>, count: Int, values: [String: Int])] = [:]
        func walk(_ v: Any, _ p: String) {
            func note(_ type: String, value: String? = nil) {
                var e = shape[p] ?? ([], 0, [:])
                e.types.insert(type)
                e.count += 1
                if let value, enums.contains(String(p.split(separator: ".").last ?? "")) { e.values[value, default: 0] += 1 }
                shape[p] = e
            }
            switch v {
            case let d as [String: Any]:
                note("object")
                for (k, x) in d { walk(x, p.isEmpty ? k : p + "." + k) }
            case let a as [Any]:
                note("array[\(a.count)]")
                for x in a { walk(x, p + "[]") }
            case let n as NSNumber:
                note(CFGetTypeID(n) == CFBooleanGetTypeID() ? "bool" : "number", value: n.stringValue)
            case let s as String: note("string", value: s.count <= 32 ? s : nil)
            case is NSNull: note("null")
            default: note("?")
            }
        }
        walk(json, "")
        print("PASS \(path) \(query.isEmpty ? "" : "\(query) ")— \(data.count) bytes")
        for (p, e) in shape.sorted(by: { $0.key < $1.key }) where !p.isEmpty {
            let types = e.types.count > 3 ? "array[…]" : e.types.sorted().joined(separator: "|")
            let values = e.values.isEmpty ? "" : "  " + e.values.sorted { $0.key < $1.key }.map { "\($0.key)×\($0.value)" }.joined(separator: " ")
            print("  \(p): \(types) ×\(e.count)\(values)")
        }
        return 0
    }

    /// `--hub-smoke`: reads every endpoint the app uses with the stored credential.
    static func smoke() async -> Int32 {
        guard let credential = try? CredentialStore.load().hub else {
            print("FAIL credentials: hub not connected")
            return 2
        }
        let transport = URLSessionTransport()
        let api = HubAPI(transport: transport, credential: credential)
        var failures = 0
        func line(_ ok: Bool, _ name: String, _ detail: String) {
            if !ok { failures += 1 }
            print("\(ok ? "PASS" : "FAIL") \(name) — \(detail)")
        }
        func status<T>(_ e: HubEnvelope<T>?) -> String { e.map { $0.status.rawValue } ?? "missing" }

        let d: HubData
        do {
            d = try await api.modules()
        } catch let e as HubError {
            line(false, "modules", describe(e))
            return 1
        } catch {
            line(false, "modules", "\(type(of: error))")
            return 1
        }

        // After the batch: hub-api reports sources it has not read since start as stale.
        do {
            let sources = try await api.status()
            let bad = sources.filter { $0.status != .ok && $0.status != .unconfigured }
            line(true, "status", "\(sources.count) sources · \(sources.filter { $0.status == .ok }.count) ok · \(sources.filter { $0.status == .unconfigured }.count) unconfigured"
                 + (bad.isEmpty ? "" : " · not ok: " + bad.map { "\($0.id)=\($0.status.rawValue)" }.joined(separator: ",")))
        } catch let e as HubError {
            line(false, "status", describe(e))
        } catch { line(false, "status", "\(type(of: error))") }

        do {
            if let remote = try await api.layout() {
                let local = LayoutStore.appSupport().load()
                line(true, "layout", "version \(remote.version) · " + (remote.document.map {
                    "pages \($0.pages.count) · custom \($0.pages.filter { !LayoutDocument.isBuiltin($0.id) }.count)"
                        + " · default \($0 == .default ? "yes" : "no") · same as this Mac \($0 == local ? "yes" : "no")"
                } ?? "unreadable document"))
            } else {
                line(true, "layout", "none stored yet")
            }
        } catch let e as HubError {
            line(false, "layout", describe(e))
        } catch { line(false, "layout", "\(type(of: error))") }
        let h = d.health?.data
        line(d.health?.status.hasData ?? false, "health", "\(status(d.health)) · days \(h?.days?.count ?? 0) · steps \(h?.steps == nil ? "null" : "set") · stages \(h?.sleepStages?.count ?? 0)")
        let b = d.bills?.data
        line(d.bills?.status.hasData ?? false, "bills", "\(status(d.bills)) · today items \(b?.todayItems?.count ?? 0) · days \(b?.days?.count ?? 0) · categories \(b?.monthCategories?.count ?? 0) · assets \(b?.netWorth == nil ? "null" : "set")")
        let c = d.crm?.data
        line(d.crm?.status.hasData ?? false, "crm", "\(status(d.crm)) · today \(c?.today?.count ?? 0) · recordings \(c?.today?.compactMap(\.recording).count ?? 0) · stale \(c?.stale?.count ?? 0)")
        let m = d.media?.data
        line(d.media?.status.hasData ?? false, "media", "\(status(d.media)) · watching \(m?.continueWatching?.count ?? 0) · latest \(m?.latest?.count ?? 0) · albums \(m?.recentAlbums?.count ?? 0) · downloads \(m?.downloads?.count ?? 0) · services \(m?.services?.count ?? 0)")
        let n = d.net?.data
        line(d.net?.status.hasData ?? false, "net", "\(status(d.net)) · hourly \(n?.hourly?.count ?? 0) · pools \(n?.pools.map { "\($0.count)" } ?? "null") · month \(n?.monthBytes == nil ? "null" : "set")")
        let me = d.memos?.data
        line(d.memos?.status.hasData ?? false, "memos", "\(status(d.memos)) · recent \(me?.recent?.count ?? 0) · tags \(me?.tags?.count ?? 0)")
        for (name, s) in [("git", d.git?.status), ("subs", d.subs?.status), ("attention", d.attention?.status)] {
            line(s != nil && s != .error, name, s?.rawValue ?? "missing")
        }

        var ranges = d.token
        for r in [TokenRange.week, .month, .year] {
            do { ranges[r] = try await api.token(range: r) } catch { line(false, "token.\(r.rawValue)", "\((error as? HubError).map(describe) ?? "\(type(of: error))")") }
        }
        let daily = TokenRangeSummary.daily(from: ranges[.year]?.data)
        for r in TokenRange.allCases {
            guard let env = ranges[r] else { continue }
            let summary = env.data.map { TokenRangeSummary($0, now: Date(), daily: daily) }
            line(env.status.hasData, "token.\(r.rawValue)", "\(env.status.rawValue) · total \(env.data?.total == nil ? "null" : "set") · series \(env.data?.buckets?.series.count ?? 0) · tools \(env.data?.tools?.count ?? 0) · heatmap \(summary?.heatmap.map { "\($0.rowLabels.count)x\($0.columns)" } ?? "none")"
                 + (r == .day ? " · limits \(env.data?.limits?.count ?? 0)" : ""))
        }

        if let ref = (m?.continueWatching ?? []).compactMap(\.image).first ?? (m?.recentAlbums ?? []).compactMap(\.image).first {
            do { line(true, "image", "\(try await api.image(ref: ref).count) bytes") } catch { line(false, "image", (error as? HubError).map(describe) ?? "\(type(of: error))") }
        } else {
            print("SKIP image — no cover reference in media")
        }
        let recordings = (c?.today ?? []).compactMap(\.recording)
        if let rec = recordings.first {
            do {
                var request = try api.audioRequest(recording: rec.id)
                request.setValue("bytes=0-1023", forHTTPHeaderField: "Range")
                let (data, response) = try await URLSession.shared.data(for: request)
                let code = (response as? HTTPURLResponse)?.statusCode ?? 0
                line(code == 206 || code == 200, "audio", "HTTP \(code) · \(data.count) bytes · \((response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Type") ?? "?")")
            } catch { line(false, "audio", "\(type(of: error))") }
            if let plaud = recordings.first(where: { $0.id.hasPrefix("plaud:") }) {
                do { line(true, "transcript", "\(try await api.transcript(recording: plaud.id).count) chars") } catch { line(false, "transcript", (error as? HubError).map(describe) ?? "\(type(of: error))") }
            }
        } else {
            print("SKIP audio — no recording today")
        }

        let sky = SkyArchive.load()
        print("INFO sky — \(sky.count) local windows · \(Set(sky.map(\.device)).count) devices · latest \(sky.first.map { HubJSON.format($0.end) } ?? "none")")
        failures += await reviewSmoke(api, goals: d.goals)
        return failures == 0 ? 0 : 1
    }

    /// Reads only, plus a preview of the blank template that personal-review must reject: nothing is written.
    private static func reviewSmoke(_ api: HubAPI, goals: HubEnvelope<GoalsData>?) async -> Int {
        var failures = 0
        func line(_ ok: Bool, _ name: String, _ detail: String) {
            if !ok { failures += 1 }
            print("\(ok ? "PASS" : "FAIL") \(name) — \(detail)")
        }
        func fail(_ error: Error) -> String { (error as? HubError).map(describe) ?? "\(type(of: error))" }
        guard let goals else {
            print("SKIP goals — hub has no goals module yet")
            return 0
        }
        let g = goals.data
        line(goals.status.hasData, "goals", "\(goals.status.rawValue) · mainline \(g?.mainline == nil ? "null" : "set") · cycle \(g?.cycle.map { "day \($0.day ?? 0)/\($0.total ?? 0) \($0.status)" } ?? "null") · goals \(g?.goals?.count ?? 0) · daily \(g?.reviews?.daily?.status.rawValue ?? "null") · weekly \(g?.reviews?.weekly?.status.rawValue ?? "null") · close \(g?.close?.status.rawValue ?? "null")")
        var open: ReviewSummary?
        for kind in ReviewKind.allCases {
            do {
                let items = try await api.reviewSessions(kind: kind)
                let counts = Dictionary(grouping: items, by: \.status).map { "\($0.key.rawValue) \($0.value.count)" }.sorted().joined(separator: " · ")
                line(true, "review.\(kind.rawValue)", "\(items.count) sessions" + (counts.isEmpty ? "" : " · " + counts))
                if open == nil { open = items.first { $0.status == .open } }
            } catch { line(false, "review.\(kind.rawValue)", fail(error)) }
        }
        guard let target = open ?? g?.reviews?.daily else {
            print("SKIP review.detail — no session")
            return failures
        }
        do {
            let s = try await api.reviewSession(id: target.id)
            line(s.material != nil, "review.detail", "\(s.kind.rawValue) \(s.status.rawValue) · sections \(s.material?.sections.count ?? 0) · delivered \(s.delivered == nil ? "null" : "set") · rules \(s.rules?.fields.count ?? 0) fields")
            guard s.status == .open, let template = s.material?.template else {
                print("SKIP review.preview — session not open")
                return failures
            }
            do {
                _ = try await api.previewReview(id: s.id, content: ReviewForm(template: template).content())
                line(false, "review.preview", "blank template accepted")
            } catch HubError.rejected(_, let field) {
                line(true, "review.preview", "blank template rejected · field \(field ?? "none")")
            } catch { line(false, "review.preview", fail(error)) }
        } catch { line(false, "review.detail", fail(error)) }
        return failures
    }

    private static func describe(_ e: HubError) -> String {
        switch e {
        case .unauthorized: "unauthorized"
        case .offline: "offline"
        case .http(let code): "HTTP \(code)"
        case .invalidResponse: "invalid response"
        case .rejected(_, let field): "rejected · field \(field ?? "none")"
        case .expired: "expired"
        }
    }
}
