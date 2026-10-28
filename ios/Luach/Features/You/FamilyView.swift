import SwiftUI

/// Members › Family (owner): who events and tasks are for. A person here is not
/// an account — the children need none — though one who signs in is linked by
/// the address they share. The web's FamilyEditor.
struct YouFamilyView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouFamilyModel
    @State private var open: YouKit.Person?

    init(model: YouFamilyModel = YouFamilyModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        List {
            Section {
                Text("Who events and tasks are for. Each person has their own colour, in luach and in Google Calendar.")
                Text("In Google Calendar an event becomes someone’s when you give it their colour, start its title with their name (“\(model.family?.exampleName ?? String(localized: "someone")): football”), or invite just them.")
            }
            .font(.subheadline)
            .foregroundStyle(.secondary)

            if let loadError = model.loadError {
                Section { YouError(message: loadError) }
            }
            if let family = model.family {
                Section {
                    ForEach(family.people) { person in
                        // A destination link, as Members' own: a value link here would be put
                        // below Family on the stack (SwiftUI orders value-presented screens
                        // before view-presented ones), so Family showed again over the person.
                        NavigationLink {
                            YouPersonEditor(person: person, colors: family.colors) { await model.load(session) }
                        } label: {
                            HStack(spacing: 12) {
                                Circle().fill(Color(youHex: person.hex)).frame(width: 16, height: 16)
                                Text(person.name)
                                Spacer()
                                if person.isKid { YouBadge("child") }
                                if person.userId != nil { YouBadge("signs in") }
                            }
                        }
                        .accessibilityIdentifier("person.\(person.key)")
                    }
                }
            }

            Section {
                TextField("Name", text: $model.name)
                    .textContentType(.name)
                    .submitLabel(.done)
                    .accessibilityIdentifier("family.name")
                Toggle("A child", isOn: $model.kid)
                    .accessibilityIdentifier("family.kid")
                Button {
                    Task { await model.add(session) }
                } label: {
                    HStack {
                        Text("Add")
                        if model.adding {
                            Spacer()
                            ProgressView()
                        }
                    }
                }
                .disabled(!model.canAdd)
                .accessibilityIdentifier("family.add")
                YouError(message: model.addError)
            } header: {
                Text("Add someone")
            }
        }
        .overlay { if model.family == nil && model.loadError == nil { ProgressView() } }
        .navigationTitle("Family")
        .refreshable { await model.load(session) }
        .task {
            await model.load(session)
            #if DEBUG
            // `-youPerson <key>` opens that person (simulator checks).
            if let key = YouDebug.value("youPerson"), let p = model.family?.people.first(where: { $0.key == key }) {
                open = p
            }
            #endif
        }
        .navigationDestination(item: $open) { person in
            YouPersonEditor(person: person, colors: model.family?.colors ?? []) { await model.load(session) }
        }
    }
}

/// The family list and adding someone; the view only lays it out.
@Observable
final class YouFamilyModel {
    private(set) var family: YouKit.Family?
    private(set) var loadError: String?
    var name = ""
    var kid = false
    private(set) var adding = false
    private(set) var addError: String?

    var canAdd: Bool { !adding && !name.trimmingCharacters(in: .whitespaces).isEmpty }

    func load(_ session: AppSession) async {
        do {
            family = try await session.api.get("/api/family")
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription
        }
    }

    struct NewPerson: Encodable {
        let name: String
        let kind: String
    }

    /// Adds who was typed, then lists the family again; the person made is returned.
    @discardableResult
    func add(_ session: AppSession) async -> YouKit.Person? {
        addError = nil
        adding = true
        defer { adding = false }
        do {
            let made: YouKit.Person = try await session.api.post(
                "/api/family", NewPerson(name: name.trimmingCharacters(in: .whitespacesAndNewlines), kind: kid ? "kid" : "adult")
            )
            name = ""
            kid = false
            await load(session)
            return made
        } catch {
            addError = error.localizedDescription
            return nil
        }
    }
}

/// One person: colour, address, child or not, and removing them. Each change
/// saves on its own, as on the web.
struct YouPersonEditor: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var model: YouPersonModel
    let colors: [YouKit.FamilyColor]

    init(person: YouKit.Person, colors: [YouKit.FamilyColor], onChange: @escaping () async -> Void) {
        self.init(model: YouPersonModel(person: person, onChange: onChange), colors: colors)
    }

    init(model: YouPersonModel, colors: [YouKit.FamilyColor]) {
        _model = State(initialValue: model)
        self.colors = colors
    }

    var body: some View {
        let person = model.person
        Form {
            Section("Colour") {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 6), spacing: 12) {
                    ForEach(colors) { c in
                        Button {
                            Task { await model.save(.init(color: c.id), session) }
                        } label: {
                            Circle()
                                .fill(Color(youHex: c.hex))
                                .frame(width: 36, height: 36)
                                .overlay {
                                    if c.id == person.color {
                                        Image(systemName: "checkmark").font(.footnote.bold()).foregroundStyle(Color.ink(on: c.hex))
                                    }
                                }
                                .overlay { Circle().strokeBorder(.primary, lineWidth: c.id == person.color ? 2 : 0).padding(-3) }
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(c.name)
                        .accessibilityIdentifier("colour.\(c.id)")
                        .accessibilityAddTraits(c.id == person.color ? .isSelected : [])
                    }
                }
                .padding(.vertical, 6)
                .disabled(model.busy)
            }
            Section {
                HStack {
                    TextField("Email", text: $model.email)
                        .keyboardType(.emailAddress)
                        .textContentType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .accessibilityIdentifier("person.email")
                    Button("Save") { Task { await model.saveEmail(session) } }
                        .buttonStyle(.borderless)
                        .disabled(!model.emailChanged)
                        .accessibilityIdentifier("person.saveEmail")
                }
            } header: {
                Text("Email")
            } footer: {
                Text("Invited to the events they lead. Optional.")
            }
            Section {
                Toggle("A child", isOn: Binding(
                    get: { model.person.isKid },
                    set: { on in Task { await model.save(.init(kind: on ? "kid" : "adult"), session) } }
                ))
                .disabled(model.busy)
                .accessibilityIdentifier("person.kid")
            }
            if let error = model.error {
                Section { YouError(message: error) }
            }
            Section {
                Button("Remove \(person.name)", role: .destructive) { model.askRemove() }
                    .disabled(model.busy)
                    .accessibilityIdentifier("person.remove")
            }
        }
        .navigationTitle(person.name)
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog("Remove \(person.name)?", isPresented: $model.confirmRemove, titleVisibility: .visible) {
            Button("Remove \(person.name)", role: .destructive) {
                Task { if await model.remove(session) { dismiss() } }
            }
            Button("Keep", role: .cancel) {}
        }
    }
}

/// One person's changes, each saved on its own; the view only lays it out.
@Observable
final class YouPersonModel {
    private(set) var person: YouKit.Person
    var email: String
    private(set) var busy = false
    private(set) var error: String?
    var confirmRemove = false
    let onChange: () async -> Void

    init(person: YouKit.Person, onChange: @escaping () async -> Void = {}) {
        self.person = person
        email = person.email
        self.onChange = onChange
    }

    var emailChanged: Bool { !busy && email.trimmingCharacters(in: .whitespaces) != person.email }

    /// Only the fields given are sent.
    struct Fields: Encodable {
        var color: String?
        var email: String?
        var kind: String?
    }

    func askRemove() {
        error = nil
        confirmRemove = true
    }

    func saveEmail(_ session: AppSession) async {
        await save(Fields(email: email.trimmingCharacters(in: .whitespaces)), session)
    }

    func save(_ fields: Fields, _ session: AppSession) async {
        error = nil
        busy = true
        defer { busy = false }
        do {
            person = try await session.api.patch("/api/family/\(person.key)", fields)
            email = person.email
            await onChange()
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// True when they are gone (the editor then closes).
    func remove(_ session: AppSession) async -> Bool {
        error = nil
        busy = true
        defer { busy = false }
        do {
            let _: API.Ignored = try await session.api.delete("/api/family/\(person.key)")
            await onChange()
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }
}
