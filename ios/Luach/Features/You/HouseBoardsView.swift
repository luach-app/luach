import SwiftUI

/// Members › House boards (owner): tablets on the wall showing everyone's day.
/// The screen shows a code at /board; typing it here pairs it. The web's Boards.
struct YouHouseBoardsView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouBoardsModel

    init(model: YouBoardsModel = YouBoardsModel()) {
        _model = State(initialValue: model)
    }

    private var boardURL: String {
        session.server.appending(path: "board").absoluteString
    }

    var body: some View {
        List {
            Section {
                Text("A tablet on the wall showing everyone’s day. Open \(Text(boardURL).font(.subheadline.monospaced())) on it and type the code it shows.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if let loadError = model.loadError {
                // Said out loud: an empty list would read as "no boards", and someone
                // would pair the kitchen screen a second time.
                Section { YouError(message: loadError) }
            }
            if let actError = model.actError {
                Section { YouError(message: actError) }
            }
            ForEach(model.boards ?? []) { board in
                boardSection(board)
            }
            Section {
                TextField("K7P3QX", text: $model.code)
                    .textInputAutocapitalization(.characters)
                    .autocorrectionDisabled()
                    .font(.body.monospaced())
                    .onChange(of: model.code) { model.upperCode() }
                    .accessibilityIdentifier("boards.code")
                LabeledContent("Call it") {
                    TextField("Call it", text: $model.name).multilineTextAlignment(.trailing)
                }
                Button {
                    Task { await model.pair(session) }
                } label: {
                    HStack {
                        Text("Pair")
                        if model.pairing {
                            Spacer()
                            ProgressView()
                        }
                    }
                }
                .disabled(!model.canPair)
                .accessibilityIdentifier("boards.pair")
                YouError(message: model.pairError)
            } header: {
                Text("Code on the screen")
            }
        }
        .overlay { if model.boards == nil && model.loadError == nil { ProgressView() } }
        .navigationTitle("House boards")
        .confirmationDialog(
            "Remove \(model.confirmRemove?.name ?? "")?",
            isPresented: Binding(get: { model.confirmRemove != nil }, set: { if !$0 { model.confirmRemove = nil } }),
            titleVisibility: .visible,
            presenting: model.confirmRemove
        ) { board in
            Button("Remove", role: .destructive) { Task { await model.remove(board.id, session) } }
            Button("Keep", role: .cancel) { model.confirmRemove = nil }
        } message: { _ in
            Text("The screen on the wall goes back to showing a code, to be typed here again.")
        }
        .refreshable { await model.load(session) }
        .task { await model.load(session) }
    }

    private func boardSection(_ board: YouKit.HouseBoard) -> some View {
        Section {
            LabeledContent("Last seen", value: board.lastSeen == nil
                ? String(localized: "not seen yet") : YouKit.relative(board.lastSeen))
            Toggle("Anyone at it can add, change and remove — not only tick", isOn: Binding(
                get: { board.canEdit != false },
                set: { on in Task { await model.change(board.id, .init(canEdit: on), session) } }
            ))
            Picker("Language", selection: Binding(
                get: { board.language ?? "auto" },
                set: { lang in Task { await model.change(board.id, .init(language: lang), session) } }
            )) {
                ForEach(YouKit.languages, id: \.value) { l in
                    Text(l.label).tag(l.value)
                }
            }
            if model.saved == board.id {
                YouDone("Saved.")
            }
            Button("Remove", role: .destructive) { model.ask(board) }
        } header: {
            Text(board.name)
        } footer: {
            Text("Automatic follows the screen’s own language. In Hebrew the board reads right to left.")
        }
        .disabled(model.busy)
    }
}

/// The paired boards, pairing and their settings; the view only lays it out.
@Observable
final class YouBoardsModel {
    private(set) var boards: [YouKit.HouseBoard]?
    private(set) var loadError: String?
    var code = ""
    var name = String(localized: "Kitchen")
    private(set) var pairing = false
    private(set) var pairError: String?
    private(set) var busy = false
    private(set) var actError: String?
    /// The board whose change last went through, to say so beside it.
    private(set) var saved: Int?
    var confirmRemove: YouKit.HouseBoard?

    var canPair: Bool { !pairing && !code.trimmingCharacters(in: .whitespaces).isEmpty }

    /// Codes are shown in capitals; typing them in small letters still works.
    func upperCode() {
        if code != code.uppercased() { code = code.uppercased() }
    }

    func ask(_ board: YouKit.HouseBoard) {
        actError = nil
        confirmRemove = board
    }

    func load(_ session: AppSession) async {
        do {
            let list: YouKit.BoardList = try await session.api.get("/api/boards")
            boards = list.boards
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription.isEmpty
                ? String(localized: "Could not load the boards.") : error.localizedDescription
        }
    }

    /// Only the fields given are sent.
    struct Change: Encodable {
        var canEdit: Bool?
        var language: String?
    }

    func change(_ id: Int, _ body: Change, _ session: AppSession) async {
        saved = nil
        actError = nil
        busy = true
        defer { busy = false }
        do {
            let list: YouKit.BoardList = try await session.api.patch("/api/boards/\(id)", body)
            boards = list.boards
            saved = id
        } catch {
            actError = error.localizedDescription
        }
    }

    struct Claim: Encodable {
        let code: String
        let name: String
    }

    func pair(_ session: AppSession) async {
        pairError = nil
        pairing = true
        defer { pairing = false }
        do {
            let _: API.Ignored = try await session.api.post(
                "/api/boards",
                Claim(code: code.trimmingCharacters(in: .whitespaces), name: name.trimmingCharacters(in: .whitespaces))
            )
            code = ""
            await load(session)
        } catch {
            pairError = error.localizedDescription
        }
    }

    func remove(_ id: Int, _ session: AppSession) async {
        confirmRemove = nil
        saved = nil
        actError = nil
        busy = true
        defer { busy = false }
        do {
            let _: API.Ignored = try await session.api.delete("/api/boards/\(id)")
            await load(session)
        } catch {
            actError = error.localizedDescription
        }
    }
}
