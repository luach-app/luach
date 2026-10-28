import SwiftUI

/// Settings › You › What luach remembers: the facts the chat keeps about you,
/// read at the start of every conversation. Yours to see, add to and take away.
struct MemoryView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouMemoryModel

    init(model: YouMemoryModel = YouMemoryModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            Section {
                Text("Things you told the chat that hold from now on — “I only book mornings”, “\(model.example) finishes school at 3:30”. It reads them at the start of every conversation. Take away anything that is no longer true, or tell the chat “forget that”.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let off = model.off {
                Section {
                    Label(off, systemImage: "info.circle").foregroundStyle(.secondary)
                }
            } else if let facts = model.facts {
                Section {
                    if facts.isEmpty {
                        Text("Nothing yet.").foregroundStyle(.secondary)
                    }
                    ForEach(facts) { fact in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(fact.fact)
                            if let topic = fact.topic, !topic.isEmpty {
                                Text(topic).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("fact.\(fact.key)")
                        .swipeActions {
                            Button("Forget", role: .destructive) { Task { await model.forget(fact.key, session) } }
                        }
                        .contextMenu {
                            Button("Forget", systemImage: "trash", role: .destructive) { Task { await model.forget(fact.key, session) } }
                        }
                    }
                } footer: {
                    if !facts.isEmpty { Text("Swipe a fact to forget it.") }
                }
                Section("Tell luach something to keep") {
                    TextField("We keep Friday nights clear", text: $model.draft, axis: .vertical)
                        .lineLimit(1...4)
                        .onChange(of: model.draft) { model.clip() }
                        .accessibilityIdentifier("memory.draft")
                    Button("Keep") { Task { await model.add(session) } }
                        .disabled(!model.canKeep)
                        .accessibilityIdentifier("memory.keep")
                }
            }
            if let error = model.error {
                Section { YouError(message: error) }
            }
        }
        .overlay { if model.facts == nil && model.off == nil { ProgressView() } }
        .refreshable { await model.load(session) }
        .task { await model.load(session) }
    }
}

/// What the memory screen shows and changes; the view only lays it out.
@Observable
final class YouMemoryModel {
    static let longest = 500

    private(set) var facts: [YouKit.MemoryFact]?
    /// Why memory is not there at all (503 when the box has none); hides the form.
    private(set) var off: String?
    private(set) var example = String(localized: "someone")
    var draft = ""
    private(set) var busy = false
    private(set) var error: String?

    var canKeep: Bool { !busy && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    /// A fact is at most 500 characters, as on the web.
    func clip() {
        if draft.count > Self.longest { draft = String(draft.prefix(Self.longest)) }
    }

    func load(_ session: AppSession) async {
        // Only for the example name; a family that will not load keeps "someone".
        if let family: YouKit.Family = try? await session.api.get("/api/family") {
            example = family.exampleName
        }
        do {
            let listing: YouKit.MemoryListing = try await session.api.get("/api/memory")
            facts = listing.facts
            off = nil
        } catch is CancellationError {
            return
        } catch {
            off = error.localizedDescription
        }
    }

    private struct FactBody: Encodable { let fact: String }

    func add(_ session: AppSession) async {
        let fact = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !fact.isEmpty else { return }
        busy = true
        error = nil
        defer { busy = false }
        do {
            let listing: YouKit.MemoryListing = try await session.api.post("/api/memory", FactBody(fact: fact))
            facts = listing.facts
            draft = ""
        } catch {
            self.error = error.localizedDescription
        }
    }

    func forget(_ key: String, _ session: AppSession) async {
        busy = true
        error = nil
        defer { busy = false }
        do {
            let listing: YouKit.MemoryListing = try await session.api.delete("/api/memory/\(key)")
            facts = listing.facts
        } catch {
            self.error = error.localizedDescription
        }
    }
}
