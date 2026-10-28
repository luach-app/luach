import SwiftUI

/// Actions the gate held for a person to decide. The household shares one
/// calendar, so everyone sees every hold (the email scan's are its member's alone).
struct PendingView: View {
    @Environment(AppSession.self) private var session
    @State private var scan: MailStatus.Scan?

    /// How often the list is asked again while it is on screen, as the web's Pending page does.
    static var pollInterval: Duration = .seconds(30)

    var body: some View {
        let store = session.pending
        NavigationStack {
            List {
                // The email scan, seen working: a line while this member's is on.
                if let scan {
                    HStack(spacing: 6) {
                        Circle().fill(.green).frame(width: 6, height: 6)
                        Text(ScanLine.text(scan))
                    }
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .listRowBackground(Color.clear)
                }
                if let error = store.error {
                    Text(error).foregroundStyle(.red)
                }
                if let failure = store.failure {
                    Label(failure, systemImage: "exclamationmark.triangle.fill").foregroundStyle(.red)
                }
                ForEach(store.items) { item in
                    PendingRow(item: item)
                }
            }
            .overlay {
                if store.items.isEmpty && store.error == nil {
                    ContentUnavailableView(
                        "Nothing waiting",
                        systemImage: "checkmark.seal",
                        description: Text("When luach is not sure about a change, it waits here for a yes.")
                    )
                }
            }
            .navigationTitle("Approvals")
            // Felt as a hold is decided and leaves the list.
            .sensoryFeedback(trigger: store.items.count) { old, new in
                new < old && store.failure == nil ? .success : nil
            }
            .sensoryFeedback(.error, trigger: store.failure)
            .accountButton()
            .refreshable { await store.refresh() }
            .task {
                // Opening the tab shows what is waiting now, not what was when the app came forward.
                await store.refresh()
                if let st = try? await session.api.mailStatus(), st.connected, st.scan?.enabled == true {
                    scan = st.scan
                }
            }
            // While the tab is on screen, a hold made elsewhere (the email scan, someone else's
            // chat) shows up without pulling. Leaving the tab stops it; in the background the
            // app is suspended, and coming forward refreshes anyway (MainTabs).
            .task {
                while !Task.isCancelled {
                    try? await Task.sleep(for: Self.pollInterval)
                    if Task.isCancelled { break }
                    await store.refresh()
                }
            }
        }
    }
}

struct PendingRow: View {
    @Environment(AppSession.self) private var session
    let item: PendingAction
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(item.summary).font(.body.weight(.medium))
            if !item.reason.isEmpty {
                Text(item.reason.map { Self.describe($0) }.joined(separator: " · "))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            let meta = Self.meta(item, clock: AgendaClock.of(session.member))
            if !meta.isEmpty {
                Text(meta)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("hold.meta")
            }
            if let source = item.source, source.kind == "email" {
                fromEmail(source)
            }
            if let error {
                Text(error).font(.footnote).foregroundStyle(.red)
            }
            HStack {
                Button("Approve") { decide(true) }
                    .prominentAccent()
                Button("Deny", role: .destructive) { decide(false) }
                    .buttonStyle(.bordered)
                if busy { ProgressView().padding(.leading, 4) }
            }
            .disabled(busy)
        }
        .padding(.vertical, 4)
        .sensoryFeedback(.error, trigger: error)
    }

    private func decide(_ approve: Bool) {
        busy = true
        Task {
            defer { busy = false }
            do {
                _ = try await session.pending.decide(item.id, approve: approve)
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    /// The mail a proposal was found in, so it is decided with the mail in view.
    private func fromEmail(_ source: PendingAction.Source) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(source.when.map { String(localized: "From your email · \($0)") } ?? String(localized: "From your email"))
                .font(.caption)
                .foregroundStyle(.secondary)
            Label((source.subject ?? "").isEmpty ? String(localized: "(no subject)") : source.subject!, systemImage: "envelope")
                .font(.footnote.weight(.medium))
                .lineLimit(1)
            if let from = source.from, !from.isEmpty {
                Text(from).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
            }
            if let link = source.gmailLink {
                Link("Open in Gmail", destination: link)
                    .font(.footnote)
                    .accessibilityIdentifier("hold.gmail")
            }
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
    }

    /// Who asked, through which door, and when: "Asked by robin · in a chat · Wed 28 Oct, 14:05".
    static func meta(_ item: PendingAction, clock: AgendaClock) -> String {
        var parts: [String] = []
        if !item.principal.isEmpty { parts.append(String(localized: "Asked by \(item.principal)")) }
        if let door = door(item.door) { parts.append(door) }
        if let at = item.createdAt.flatMap(clock.instant) { parts.append(clock.dateTime(at)) }
        return parts.joined(separator: " · ")
    }

    /// The door a request came through, in words; nil when the server did not say.
    static func door(_ door: String) -> String? {
        switch door {
        case "": nil
        case "web", "app", "chat": String(localized: "in a chat")
        case "email": String(localized: "by email")
        case "email-scan": String(localized: "from the email scan")
        default: String(localized: "via \(door)")
        }
    }

    /// The gate's labels (README, "What makes it governed") in words.
    static func describe(_ label: String) -> String {
        switch label {
        case "ambiguous": String(localized: "the time was a guess")
        case "past": String(localized: "it is in the past")
        case "possible-duplicate": String(localized: "looks like one already there")
        case "mutation-existing": String(localized: "changes something luach did not make")
        case "bulk": String(localized: "more than one event at once")
        case "outside-the-house": String(localized: "sends an invitation outside the household")
        default: label.replacingOccurrences(of: "-", with: " ")
        }
    }
}
