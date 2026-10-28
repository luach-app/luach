import SwiftUI

/// Settings › Security › Audit trail (owner): the tamper-evident log of what
/// luach did, newest first, and whether the hash chain that seals it verifies.
struct AuditView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouAuditModel

    init(model: YouAuditModel = YouAuditModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            if let error = model.error {
                Section { YouError(message: error) }
            }
            if let trail = model.trail {
                Section {
                    LabeledContent("Chain") {
                        if trail.verified {
                            YouBadge("verified ✓", tint: .green)
                        } else {
                            YouBadge("broken ✗", tint: .red)
                        }
                    }
                } footer: {
                    Text("\(trail.total) entries · showing the last \(trail.entries.count)")
                }
                Section {
                    ForEach(trail.entries) { entry in
                        NavigationLink {
                            YouAuditEntryDetail(entry: entry, zone: session.member?.timezone)
                        } label: {
                            entryRow(entry)
                        }
                        .accessibilityIdentifier("audit.\(entry.seq)")
                    }
                    if model.hasOlder {
                        Button("Show older") { Task { await model.showOlder(session) } }
                    }
                }
            }
        }
        .overlay { if model.trail == nil && model.error == nil { ProgressView() } }
        .refreshable { await model.load(session) }
        .task { await model.load(session) }
    }

    private func entryRow(_ entry: YouAuditTrail.Entry) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text(entry.eventType).font(.subheadline.weight(.medium))
                Spacer()
                Text("#\(entry.seq) · \(YouKit.timestamp(entry.ts, zone: session.member?.timezone))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Text(entry.compact.isEmpty ? "—" : entry.compact)
                .font(.caption.monospaced())
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }
}

/// The audit screen's trail and how much of it to show; the view only lays it out.
@Observable
final class YouAuditModel {
    /// The server's most; "Show older" adds 50 at a time up to it.
    static let most = 200

    private(set) var trail: YouAuditTrail?
    private(set) var error: String?
    private(set) var limit = 50

    var hasOlder: Bool {
        guard let trail else { return false }
        return trail.entries.count < trail.total && limit < Self.most
    }

    func load(_ session: AppSession) async {
        do {
            trail = try await YouAuditTrail.fetch(session.api, limit: limit)
            error = nil
        } catch is CancellationError {
            return
        } catch {
            self.error = error.localizedDescription
        }
    }

    func showOlder(_ session: AppSession) async {
        limit = min(limit + 50, Self.most)
        await load(session)
    }
}

/// `GET /api/control/audit`, read with JSONSerialization so a payload's keys stay
/// as luach wrote them (the API's decoder would turn `by_who` into `byWho`).
struct YouAuditTrail {
    struct Entry: Identifiable {
        let seq: Int
        let ts: String
        let eventType: String
        let hash: String
        /// Key and value, each value as JSON unless it is a plain string.
        let fields: [(key: String, value: String)]
        var id: Int { seq }

        /// The web's compactPayload: the first four non-empty fields, each value cut at 48.
        var compact: String {
            fields.filter { !$0.value.isEmpty && $0.value != "null" }.prefix(4).map { f in
                let v = f.value.count > 48 ? "\(f.value.prefix(48))…" : f.value
                return "\(f.key)=\(v)"
            }.joined(separator: "  ")
        }
    }

    let entries: [Entry]
    let total: Int
    let verified: Bool
    let head: String

    static func fetch(_ api: API, limit: Int) async throws -> YouAuditTrail {
        let req = try api.request("GET", "/api/control/audit", query: ["limit": String(limit)])
        // The shared session carries the same cookie store the API uses.
        let (data, response) = try await URLSession.shared.data(for: req)
        try api.check(response, data, path: "/api/control/audit")
        return try parse(data)
    }

    /// The server's answer, newest first, each payload's keys as luach wrote them.
    static func parse(_ data: Data) throws -> YouAuditTrail {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw APIError(status: 0, message: String(localized: "The audit trail could not be read."))
        }
        let rows = (root["entries"] as? [[String: Any]]) ?? []
        let entries = rows.map { row in
            let payload = (row["payload"] as? [String: Any]) ?? [:]
            return Entry(
                seq: (row["seq"] as? Int) ?? 0,
                ts: (row["ts"] as? String) ?? "",
                eventType: (row["event_type"] as? String) ?? "",
                hash: (row["hash"] as? String) ?? "",
                fields: payload.keys.sorted().map { ($0, text(payload[$0])) }
            )
        }
        return YouAuditTrail(
            // Newest first: on a phone the last thing that happened is the one looked for.
            entries: entries.sorted { $0.seq > $1.seq },
            total: (root["total"] as? Int) ?? entries.count,
            verified: (root["chain_verified"] as? Bool) ?? false,
            head: (root["head"] as? String) ?? ""
        )
    }

    /// A payload value as the web shows it: a string as is, anything else as JSON.
    static func text(_ value: Any?) -> String {
        switch value {
        case nil, is NSNull: return ""
        case let s as String: return s
        default:
            guard let value,
                  let data = try? JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed, .sortedKeys, .withoutEscapingSlashes])
            else { return "\(value ?? "")" }
            return String(decoding: data, as: UTF8.self)
        }
    }
}

/// One entry in full: every payload field and the hash that chains it.
struct YouAuditEntryDetail: View {
    let entry: YouAuditTrail.Entry
    let zone: String?

    var body: some View {
        List {
            Section {
                LabeledContent("Event", value: entry.eventType)
                LabeledContent("Number", value: "#\(entry.seq)")
                LabeledContent("When", value: YouKit.timestamp(entry.ts, zone: zone))
            }
            Section("Payload") {
                if entry.fields.isEmpty {
                    Text("—").foregroundStyle(.secondary)
                }
                ForEach(entry.fields, id: \.key) { field in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(field.key).font(.caption).foregroundStyle(.secondary)
                        Text(field.value.isEmpty ? "—" : field.value)
                            .font(.callout.monospaced())
                            .textSelection(.enabled)
                    }
                }
            }
            Section("Hash") {
                Text(entry.hash)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
            }
        }
        .navigationTitle(entry.eventType)
        .navigationBarTitleDisplayMode(.inline)
    }
}
