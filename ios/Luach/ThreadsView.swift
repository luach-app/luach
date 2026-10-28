import SwiftUI

extension API {
    func threads(before: String? = nil) async throws -> ThreadPage {
        try await get("/api/threads", query: before.map { ["before": $0] } ?? [:])
    }

    func renameThread(_ id: String, to title: String) async throws -> String {
        struct Body: Encodable { let title: String }
        struct Reply: Decodable { let title: String }
        let reply: Reply = try await patch("/api/threads/\(id)", Body(title: title))
        return reply.title
    }

    func deleteThread(_ id: String) async throws {
        let _: Ignored = try await delete("/api/threads/\(id)")
    }
}

/// Every conversation this member has had with luach, newest first. Nobody else's:
/// a household shares a calendar, not the things each person asks about it.
struct ThreadsView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    let current: String?
    let onOpen: (String) -> Void
    let onDeleted: (String) -> Void

    @State private var rows: [ThreadSummary]?
    @State private var more = false
    @State private var retention = 0
    @State private var error: String?
    /// The conversation being renamed. A sheet with its own field, not an alert's: an alert's
    /// text field did not reliably hand back what was typed before Save read it.
    @State private var renaming: ThreadSummary?

    var body: some View {
        NavigationStack {
            List {
                if let error {
                    Text(error).foregroundStyle(.red)
                }
                if let rows, rows.isEmpty {
                    ContentUnavailableView("Nothing yet", systemImage: "bubble.left.and.bubble.right",
                                           description: Text("Ask luach something."))
                }
                Section {
                    ForEach(rows ?? []) { row in
                        Button { onOpen(row.id) } label: { ThreadRow(row: row, current: row.id == current) }
                            .buttonStyle(.plain)
                            // No full swipe: a long swipe should not delete a conversation on its own.
                            .swipeActions(allowsFullSwipe: false) {
                                Button("Delete", role: .destructive) { Task { await remove(row) } }
                                Button("Rename") {
                                    renaming = row
                                }
                                .tint(.gray)
                            }
                            .contextMenu {
                                Button("Rename", systemImage: "pencil") {
                                    renaming = row
                                }
                                Button("Delete", systemImage: "trash", role: .destructive) { Task { await remove(row) } }
                            }
                    }
                    if more {
                        Button("Show older") { Task { await load(more: true) } }
                    }
                } footer: {
                    if retention > 0, rows?.isEmpty == false {
                        Text("Conversations are kept for \(retention) days. What luach should remember about you for longer, tell it to remember.")
                    }
                }
            }
            .overlay { if rows == nil && error == nil { ProgressView() } }
            .navigationTitle("Conversations")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .refreshable { await load() }
            .task { await load() }
            .sheet(item: $renaming) { row in
                RenameSheet(title: row.title) { name in await rename(row, to: name) }
                    .presentationDetents([.height(220)])
            }
        }
    }

    private func load(more older: Bool = false) async {
        do {
            let page = try await session.api.threads(before: older ? rows?.last?.updatedAt : nil)
            rows = older ? (rows ?? []) + page.threads : page.threads
            more = page.more
            retention = page.retentionDays ?? 0
            error = nil
        } catch is CancellationError {
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func rename(_ row: ThreadSummary, to name: String) async {
        renaming = nil
        let t = name.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty, t != row.title else { return }
        do {
            let saved = try await session.api.renameThread(row.id, to: t)
            rows = rows?.map { $0.id == row.id ? ThreadSummary(id: $0.id, title: saved, door: $0.door, turns: $0.turns, createdAt: $0.createdAt, updatedAt: $0.updatedAt) : $0 }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func remove(_ row: ThreadSummary) async {
        do {
            try await session.api.deleteThread(row.id)
            rows?.removeAll { $0.id == row.id }
            onDeleted(row.id)
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// A conversation's new name: the old one to start from, Save when it says something new.
private struct RenameSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State var title: String
    let save: (String) async -> Void
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            Form {
                TextField("Title", text: $title)
                    .focused($focused)
                    .submitLabel(.done)
                    .onSubmit { Task { await save(title) } }
            }
            .navigationTitle("Rename")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Task { await save(title) } }
                        .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear { focused = true }
        }
    }
}

private struct ThreadRow: View {
    let row: ThreadSummary
    let current: Bool

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(row.title.isEmpty ? String(localized: "Untitled") : row.title)
                    .foregroundStyle(.primary)
                    .lineLimit(1)
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if current {
                Image(systemName: "checkmark").foregroundStyle(.tint)
            }
        }
        .contentShape(Rectangle())
    }

    private var subtitle: String {
        var parts: [String] = []
        if let d = EventTime.parse(row.updatedAt) {
            parts.append(d.formatted(.relative(presentation: .named)))
        }
        if let door = row.door, !door.isEmpty, door != "web", door != "app" {
            parts.append(door)
        }
        return parts.joined(separator: " · ")
    }
}
