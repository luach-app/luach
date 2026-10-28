import SwiftUI

/// Settings › You › Profile: display name, time zone, the language luach answers
/// in, and the model that answers. Saves only what changed (PATCH /api/auth/me).
struct ProfileView: View {
    @Environment(AppSession.self) private var session
    @State private var model: YouProfileModel
    @State private var pickZone = false
    /// A model outside the house, waiting for the person's yes before it is chosen.
    @State private var askingFor: YouKit.ModelMenu.Choice?

    init(model: YouProfileModel = YouProfileModel()) {
        _model = State(initialValue: model)
    }

    var body: some View {
        Form {
            if let me = model.me {
                Section("Display name") {
                    TextField("Display name", text: $model.displayName)
                        .textContentType(.name)
                        .submitLabel(.done)
                        .accessibilityIdentifier("profile.displayName")
                }
                Section {
                    NavigationLink {
                        YouTimeZonePicker(selection: $model.timezone)
                    } label: {
                        LabeledContent("Time zone", value: model.timezone)
                    }
                    .accessibilityIdentifier("profile.timezone")
                    Picker("Language luach answers in", selection: $model.language) {
                        ForEach(YouKit.languages, id: \.value) { l in
                            Text(l.label).tag(l.value)
                        }
                    }
                    .accessibilityIdentifier("profile.language")
                } footer: {
                    Text("Dates are written this way too.")
                }
                if model.models.count > 1 {
                    Section {
                        ForEach(model.models) { choice in
                            Button {
                                // A model outside the house sends what is asked to its provider:
                                // chosen only after a clear yes, remembered per model.
                                if model.needsConsent(choice) {
                                    askingFor = choice
                                } else {
                                    model.model = choice.id
                                }
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(model.label(choice))
                                            .foregroundStyle(choice.answering ? .primary : .secondary)
                                        if !choice.about.isEmpty {
                                            Text(choice.about)
                                                .font(.footnote)
                                                .foregroundStyle(.secondary)
                                        }
                                        if !choice.answering {
                                            YouModelHealthNote(health: choice.health)
                                        }
                                    }
                                    Spacer()
                                    if choice.id == model.shownModel(me) {
                                        Image(systemName: "checkmark").foregroundStyle(Color.accentColor)
                                    }
                                }
                            }
                            .tint(.primary)
                            // A model that is not answering cannot be picked; the reason says why.
                            .disabled(!model.canPick(choice))
                            .accessibilityIdentifier("model.\(choice.id)")
                            .accessibilityAddTraits(choice.id == model.shownModel(me) ? .isSelected : [])
                        }
                    } header: {
                        Text("Model that answers you")
                    }
                }
                if model.error != nil || model.showsSaved {
                    Section {
                        YouError(message: model.error)
                        if model.showsSaved { YouDone("Saved.") }
                    }
                }
            } else if let loadError = model.loadError {
                YouError(message: loadError)
            }
        }
        .overlay { if model.me == nil && model.loadError == nil { ProgressView() } }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if model.busy {
                    ProgressView()
                } else {
                    Button("Save") { Task { await model.save(session) } }
                        .disabled(!model.dirty)
                        .accessibilityIdentifier("profile.save")
                }
            }
        }
        .onChange(of: [model.displayName, model.timezone, model.language, model.model]) { model.edited() }
        .navigationDestination(isPresented: $pickZone) { YouTimeZonePicker(selection: $model.timezone) }
        .alert(
            Text("Send your questions to \(askingFor?.name ?? "")?"),
            isPresented: Binding(get: { askingFor != nil }, set: { if !$0 { askingFor = nil } }),
            presenting: askingFor
        ) { choice in
            Button("Use \(choice.name)") {
                YouAIConsent.give(choice.id)
                model.model = choice.id
            }
            Button("Keep the household's model", role: .cancel) {}
        } message: { choice in
            if choice.provider.isEmpty {
                Text("\(choice.name) runs outside the house. What you ask luach, and the calendar, task and email details it looks up to answer, are sent to its provider to be answered. You can change this here at any time.")
            } else {
                Text("\(choice.name) runs outside the house, at \(choice.provider). What you ask luach, and the calendar, task and email details it looks up to answer, are sent there to be answered. You can change this here at any time.")
            }
        }
        .task {
            // Once: `.task` runs again on coming back from the zone list, and loading then
            // put the saved zone back over the one just picked.
            guard model.me == nil else { return }
            await model.load(session)
            #if DEBUG
            // `-youPush timezone` opens the time zone list (simulator checks).
            if YouDebug.value("youPush") == "timezone" { pickZone = true }
            #endif
        }
    }
}

/// What Profile shows and saves; the view only lays it out.
@Observable
final class YouProfileModel {
    private(set) var me: YouKit.Me?
    private(set) var loadError: String?
    var displayName = ""
    var timezone = ""
    var language = "auto"
    /// "" until the member picks one; the saved pick shows until then.
    var model = ""
    private(set) var models: [YouKit.ModelMenu.Choice] = []
    private(set) var defaultModel = ""
    private(set) var busy = false
    private(set) var error: String?
    private(set) var saved = false

    func savedModel(_ me: YouKit.Me) -> String { me.model.isEmpty ? defaultModel : me.model }
    func shownModel(_ me: YouKit.Me) -> String { model.isEmpty ? savedModel(me) : model }
    func savedZone(_ me: YouKit.Me) -> String { me.member.timezone ?? "UTC" }
    func savedLanguage(_ me: YouKit.Me) -> String { me.member.language ?? "auto" }

    /// A model's row title: the household's default says so.
    func label(_ choice: YouKit.ModelMenu.Choice) -> String {
        choice.id == defaultModel ? String(localized: "\(choice.name) (default)") : choice.name
    }

    /// Whether picking `choice` first asks the member: anything but the household's default that
    /// does not run at home, until they have said yes to it on this phone. A server too old to say
    /// where a model runs gets the question.
    func needsConsent(_ choice: YouKit.ModelMenu.Choice) -> Bool {
        choice.id != defaultModel && !choice.local && !YouAIConsent.given(choice.id)
    }

    /// A model that is not answering is shown, and cannot be picked.
    func canPick(_ choice: YouKit.ModelMenu.Choice) -> Bool { choice.answering }

    var dirty: Bool {
        guard let me else { return false }
        let modelChanged = !model.isEmpty && model != savedModel(me)
        return displayName != (me.member.displayName ?? "") || timezone != savedZone(me)
            || language != savedLanguage(me) || modelChanged
    }

    /// "Saved." stays until the member changes something again.
    var showsSaved: Bool { saved && !dirty }

    /// A field was edited: a change since the save hides "Saved.". (Taking the server's
    /// answer after a save edits fields too — the model pick goes back to "" — and must not.)
    func edited() {
        if dirty { saved = false }
    }

    private func adopt(_ me: YouKit.Me) {
        self.me = me
        displayName = me.member.displayName ?? ""
        timezone = savedZone(me)
        language = savedLanguage(me)
        model = ""
    }

    func load(_ session: AppSession) async {
        // No menu is not an error a person needs: the choice simply hides.
        if let menu: YouKit.ModelMenu = try? await session.api.get("/api/models") {
            models = menu.catalogue ?? []
            defaultModel = menu.default ?? ""
        }
        do {
            adopt(try await session.api.get("/api/auth/me"))
            loadError = nil
        } catch is CancellationError {
            return
        } catch {
            loadError = error.localizedDescription
        }
    }

    struct Patch: Encodable {
        var displayName: String?
        var timezone: String?
        var language: String?
        var model: String?
    }

    /// Only what changed; picking the household's default saves "" (follow the default).
    func patch(_ me: YouKit.Me) -> Patch {
        var body = Patch()
        if displayName != (me.member.displayName ?? "") {
            body.displayName = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if timezone != savedZone(me) { body.timezone = timezone }
        if language != savedLanguage(me) { body.language = language }
        if !model.isEmpty && model != savedModel(me) { body.model = model == defaultModel ? "" : model }
        return body
    }

    func save(_ session: AppSession) async {
        guard let me else { return }
        saved = false
        error = nil
        let body = patch(me)
        busy = true
        defer { busy = false }
        do {
            let reply: YouKit.Me = try await session.api.patch("/api/auth/me", body)
            session.setMember(reply.member)
            adopt(reply)
            saved = true
        } catch {
            self.error = error.localizedDescription
        }
    }
}

/// Every time zone the phone knows, searchable; the current one ticked.
struct YouTimeZonePicker: View {
    @Binding var selection: String
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""

    private var zones: [String] { Self.zones(matching: query, selection: selection) }

    /// Every zone the phone knows (the selection too, should it not), filtered by what was
    /// typed: "new york" finds America/New_York.
    static func zones(matching query: String, selection: String) -> [String] {
        var all = TimeZone.knownTimeZoneIdentifiers
        if !selection.isEmpty && !all.contains(selection) { all.insert(selection, at: 0) }
        guard !query.isEmpty else { return all }
        let q = query.replacingOccurrences(of: " ", with: "_")
        return all.filter { $0.localizedCaseInsensitiveContains(q) }
    }

    var body: some View {
        List(zones, id: \.self) { zone in
            Button {
                selection = zone
                dismiss()
            } label: {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(zone.replacingOccurrences(of: "_", with: " ")).foregroundStyle(.primary)
                        if let tz = TimeZone(identifier: zone),
                           let name = tz.localizedName(for: .generic, locale: .current) {
                            Text(name).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    if zone == selection {
                        Image(systemName: "checkmark").foregroundStyle(Color.accentColor)
                    }
                }
            }
            .tint(.primary)
            .accessibilityIdentifier("zone.\(zone)")
        }
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search time zones")
        .navigationTitle("Time zone")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// "Not answering since 26 Oct, 10:07", and the reason, under a model that is not answering.
struct YouModelHealthNote: View {
    let health: YouKit.ModelMenu.Health

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Label {
                if let since = health.since, YouKit.date(since) != nil {
                    Text("Not answering since \(YouKit.timestamp(since, zone: nil))")
                } else {
                    Text("Not answering")
                }
            } icon: {
                Image(systemName: "exclamationmark.triangle.fill")
            }
            .font(.footnote.weight(.medium))
            .foregroundStyle(.orange)
            if !health.reason.isEmpty {
                Text(health.reason).font(.footnote).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// A person's yes to a model that runs outside the house, kept on this phone, one per model.
enum YouAIConsent {
    private static func key(_ id: String) -> String { "luach.ai.consent.\(id)" }
    static func given(_ id: String) -> Bool { UserDefaults.standard.bool(forKey: key(id)) }
    static func give(_ id: String) { UserDefaults.standard.set(true, forKey: key(id)) }
    static func withdraw(_ id: String) { UserDefaults.standard.removeObject(forKey: key(id)) }
}
