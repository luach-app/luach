import SwiftUI

/// Settings › Meetings › Busy calendars: feeds luach reads for busy time only. It
/// never writes to them and never shows what the meetings are — only that the
/// hours are taken, so the booking page cannot offer them away.
struct BusyCalendarsView: View {
    @Environment(AppSession.self) private var session
    @State private var sources: [HouseholdArea.BusySource]?
    @State private var loadError: String?
    @State private var name = ""
    @State private var url = ""
    @State private var working = false
    @State private var error: String?
    @State private var removing: HouseholdArea.BusySource?

    var body: some View {
        Form {
            Section {
                if let loadError {
                    Text(loadError).foregroundStyle(.red)
                } else if let sources, sources.isEmpty {
                    Text("No work calendar yet.").foregroundStyle(.secondary)
                }
            } footer: {
                Text("A calendar luach may read but never change, such as the one at your job. It takes the hours, not the meetings: the booking page stops offering times you are already in something, and the agenda shows them as “Busy”.")
            }

            ForEach(sources ?? []) { source in
                Section {
                    sourceRow(source)
                }
            }

            Section {
                LabeledContent("Name") {
                    TextField("Work", text: $name)
                        .multilineTextAlignment(.trailing)
                        .accessibilityIdentifier("busy.name")
                }
                TextField("Feed address (ICS)", text: $url, axis: .vertical)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .lineLimit(1...4)
                    .accessibilityIdentifier("busy.url")
                Button("Add") { Task { await add() } }
                    .disabled(working || url.trimmingCharacters(in: .whitespaces).isEmpty)
            } header: {
                Text("Add a calendar")
            } footer: {
                Text("In Outlook: Settings › Calendar › Shared calendars › Publish a calendar, permission “Can view when I’m busy”, then copy the ICS link. Anyone with that link can read it, so treat it like a password.")
            }

            if let error {
                Section { Text(error).foregroundStyle(.red) }
            }

            if let sources, !sources.isEmpty {
                Section {
                    Button {
                        Task { await act(.refresh) }
                    } label: {
                        HStack {
                            Text("Read them now")
                            if working { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(working)
                }
            }
        }
        .overlay { if sources == nil && loadError == nil { ProgressView() } }
        .task { await load() }
        .refreshable { await load() }
        .confirmationDialog(
            "Remove \(removing?.name ?? "")?",
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            titleVisibility: .visible,
            presenting: removing
        ) { source in
            Button("Remove", role: .destructive) {
                Task { await act(.remove(source.id)) }
            }
            Button("Keep", role: .cancel) {}
        } message: { _ in
            Text("luach stops reading it. You can add it again with its address.")
        }
    }

    private func sourceRow(_ s: HouseholdArea.BusySource) -> some View {
        Group {
            HStack {
                Text(s.name)
                Spacer()
                if let err = s.lastError, !err.isEmpty {
                    HouseholdArea.Tag(text: "could not read", tint: .red)
                } else {
                    HouseholdArea.Tag(text: "\(s.blocks ?? 0) busy")
                }
            }
            Toggle("Block bookings", isOn: Binding(
                get: { s.enabled },
                set: { on in Task { await update(s.id, ["enabled": on]) } }
            ))
            Toggle("Show in the agenda", isOn: Binding(
                get: { s.showInAgenda },
                set: { on in Task { await update(s.id, ["show_in_agenda": on]) } }
            ))
            LabeledContent("Read", value: readAgo(s.lastFetched))
            if let err = s.lastError, !err.isEmpty {
                Text(err).font(.footnote).foregroundStyle(.red)
            }
            Button("Remove", role: .destructive) { removing = s }
        }
        .disabled(working)
    }

    private func readAgo(_ iso: String?) -> String {
        HouseholdArea.readAgo(iso)
    }

    private var client: HouseholdArea.Client { HouseholdArea.Client(api: session.api) }

    private func load() async {
        do {
            sources = try await client.busy()
            loadError = nil
        } catch is CancellationError {
        } catch {
            loadError = error.localizedDescription
        }
    }

    private enum Op {
        case refresh
        case remove(Int)
        case update(Int, [String: Bool])
        case add(name: String, url: String)
    }

    /// Every write answers with the listing that is left.
    private func act(_ op: Op) async {
        working = true
        defer { working = false }
        do {
            switch op {
            case .refresh: sources = try await client.refreshBusy()
            case .remove(let id): sources = try await client.removeBusy(id)
            case .update(let id, let body): sources = try await client.updateBusy(id, body)
            case .add(let name, let url): sources = try await client.addBusy(name: name, url: url)
            }
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func update(_ id: Int, _ body: [String: Bool]) async {
        await act(.update(id, body))
    }

    private func add() async {
        await act(.add(name: name, url: url))
        if error == nil {
            name = ""
            url = ""
        }
    }
}
