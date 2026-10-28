import SwiftUI

/// Settings › Household › Models (owner only): the AI models members may choose from, in the
/// order they see them. The owner turns each on or off, picks the household's default, adds one
/// from the catalogue, tries it ("Try it": a dozen of luach's own cases) and checks it answers.
struct HouseholdModelsView: View {
    @Environment(AppSession.self) private var session
    @State private var model: HouseholdModelsModel?

    /// `model`: tests hand in their own, pointed at a stub luach.
    init(model: HouseholdModelsModel? = nil) {
        _model = State(initialValue: model)
    }

    var body: some View {
        Group {
            if let model {
                HouseholdModelsList(model: model)
            } else {
                ProgressView()
            }
        }
        .task {
            if model == nil { model = HouseholdModelsModel(api: session.api) }
        }
    }
}

/// Which sheet is up over the list.
enum HouseholdModelsSheet: Identifiable, Hashable {
    case model(String)
    case add
    var id: String {
        switch self {
        case .model(let id): "model:\(id)"
        case .add: "add"
        }
    }
}

struct HouseholdModelsList: View {
    typealias H = HouseholdArea
    @Bindable var model: HouseholdModelsModel
    @State private var opened: HouseholdModelsSheet?
    @State private var removing: H.ManagedModel?

    var body: some View {
        List {
            if let loadError = model.loadError, model.snapshot == nil {
                Section {
                    Text(loadError).foregroundStyle(.red)
                    Button("Try again") { Task { await model.load() } }
                }
            }
            if let snap = model.snapshot {
                if !snap.configured {
                    Section {
                        Label("No model server is set up, so no model can answer yet.", systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                    }
                }
                if let trial = model.shownTrial {
                    Section {
                        HouseholdTrialProgress(model: model, trial: trial)
                    } header: {
                        Text("Try it")
                    }
                }
                Section {
                    if model.models.isEmpty {
                        Text("No models on the list yet.").foregroundStyle(.secondary)
                    }
                    ForEach(model.models) { m in
                        row(m)
                    }
                    .onMove { from, to in Task { await model.move(from: from, to: to) } }
                } header: {
                    Text("Models")
                } footer: {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("Members choose from the models that are on, in this order. Tap a model to change it, try it or check it; Edit changes the order.")
                        if !snap.default.isEmpty && !snap.models.contains(where: { $0.id == snap.default }) {
                            Text("The household's default, \(snap.default), is set in luach's own settings.")
                        }
                    }
                }
                if model.error != nil || model.notice != nil {
                    Section {
                        YouError(message: model.error)
                        if let notice = model.notice { Text(notice).foregroundStyle(.secondary) }
                    }
                }
                Section {
                    Button {
                        model.error = nil
                        opened = .add
                    } label: {
                        Label("Add a model", systemImage: "plus.circle")
                    }
                    .accessibilityIdentifier("models.add")
                } footer: {
                    Text("Trials left today: \(snap.trialsLeftToday)")
                }
            }
        }
        .overlay { if model.snapshot == nil && model.loadError == nil { ProgressView() } }
        .toolbar {
            if model.models.count > 1 {
                ToolbarItem(placement: .primaryAction) { EditButton() }
            }
        }
        .task { await model.load() }
        .task(id: model.runningID) {
            if model.runningID != nil { await model.followTrial() }
        }
        .refreshable { await model.load() }
        .sheet(item: $opened) { sheet in
            switch sheet {
            case .model(let id):
                HouseholdModelDetail(model: model, id: id)
            case .add:
                HouseholdAddModelView(model: model)
            }
        }
        .confirmationDialog(
            Text("Remove \(removing?.name ?? "")?"),
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            titleVisibility: .visible,
            presenting: removing
        ) { m in
            Button("Remove", role: .destructive) { Task { await model.remove(m.id) } }
            Button("Keep", role: .cancel) {}
        } message: { _ in
            Text("Members who chose it go back to the household's default. You can add it again.")
        }
        #if DEBUG
        .task {
            // `-modelsOpen add|<model id>` opens a sheet in the simulator.
            if let open = UserDefaults.standard.string(forKey: "modelsOpen"), opened == nil {
                while model.snapshot == nil && model.loadError == nil { try? await Task.sleep(for: .milliseconds(100)) }
                opened = open == "add" ? .add : .model(open)
            }
        }
        #endif
    }

    private func row(_ m: H.ManagedModel) -> some View {
        Button {
            model.error = nil
            opened = .model(m.id)
        } label: {
            HStack(alignment: .top, spacing: 10) {
                HouseholdModelSummary(m: m)
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
        }
        .tint(.primary)
        .accessibilityIdentifier("models.row.\(m.id)")
        .accessibilityHint(Text("Opens the model's settings"))
        .swipeActions(edge: .trailing) {
            if !m.isDefault {
                Button("Remove", role: .destructive) { removing = m }
            }
        }
        .swipeActions(edge: .leading) {
            if !m.isDefault {
                Button(m.enabled ? "Turn off" : "Turn on") {
                    Task { await model.setEnabled(m.id, !m.enabled) }
                }
                .tint(m.enabled ? .gray : .green)
            }
        }
    }
}

/// A model's name, where it runs and its badges: on or off, the default, not answering, its score.
struct HouseholdModelSummary: View {
    typealias H = HouseholdArea
    let m: H.ManagedModel

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(m.name)
                .font(.body.weight(.medium))
                .foregroundStyle(m.enabled ? .primary : .secondary)
            Text(H.whereItRuns(m)).font(.footnote).foregroundStyle(.secondary)
            HouseholdFlow {
                if m.isDefault {
                    H.Tag(text: "Default", tint: .accentColor)
                }
                if !m.enabled {
                    H.Tag(text: "Off")
                } else if !m.isDefault {
                    H.Tag(text: "On the menu", tint: .green)
                }
                if !m.answering {
                    H.Tag(text: "Not answering", tint: .red)
                }
                if let score = m.trial {
                    HouseholdScoreTag(passed: score.passed, total: score.total, verdict: score.grade)
                }
            }
            if !m.answering {
                YouModelHealthNote(health: m.health)
            }
            if m.trial?.grade == .low {
                HouseholdLowScoreWarning()
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// "Tried: 11 of 12 passed", tinted by the verdict.
struct HouseholdScoreTag: View {
    let passed: Int
    let total: Int
    let verdict: HouseholdArea.Verdict?

    var body: some View {
        Text("Tried: \(HouseholdArea.scoreText(passed, total))")
            .font(.caption)
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .foregroundStyle(HouseholdArea.tint(verdict))
            .background(HouseholdArea.tint(verdict).opacity(0.12), in: Capsule())
    }
}

struct HouseholdLowScoreWarning: View {
    var body: some View {
        Label("Low score: members may get wrong answers.", systemImage: "exclamationmark.triangle.fill")
            .font(.footnote)
            .foregroundStyle(.red)
    }
}

/// Badges side by side, wrapping onto a new line when they do not fit (large text).
struct HouseholdFlow: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0, widest: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width {
                y += line + spacing
                x = 0
                line = 0
            }
            x += size.width + spacing
            line = max(line, size.height)
            widest = max(widest, x - spacing)
        }
        return CGSize(width: min(widest, width), height: subviews.isEmpty ? 0 : y + line)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, line: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                y += line + spacing
                x = bounds.minX
                line = 0
            }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            line = max(line, size.height)
        }
    }
}

/// The trial going on (or the one just finished): which model, how far, and Cancel.
struct HouseholdTrialProgress: View {
    typealias H = HouseholdArea
    @Bindable var model: HouseholdModelsModel
    let trial: H.Trial

    var body: some View {
        let name = H.modelName(trial.model, in: model.models)
        VStack(alignment: .leading, spacing: 6) {
            switch trial.status {
            case "running":
                Text("Trying \(name)…").font(.body.weight(.medium))
                if let progress = H.progress(trial) {
                    ProgressView(value: progress)
                        .accessibilityLabel(Text("Trial progress"))
                        .accessibilityValue(Text("\(trial.done) of \(trial.total) cases"))
                    Text("\(trial.done) of \(trial.total) cases").font(.footnote).foregroundStyle(.secondary)
                } else {
                    ProgressView().accessibilityLabel(Text("Starting the trial"))
                }
            case "done":
                Text("\(name) was tried").font(.body.weight(.medium))
                HouseholdScoreTag(passed: trial.passed, total: trial.total, verdict: trial.grade)
                if trial.grade == .low { HouseholdLowScoreWarning() }
            case "cancelled":
                Text("The trial of \(name) was cancelled.").foregroundStyle(.secondary)
            default:
                Text("The trial of \(name) stopped.").font(.body.weight(.medium))
                if let error = trial.error, !error.isEmpty {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
            }
        }
        .accessibilityElement(children: .combine)
        if trial.running {
            Button("Cancel the trial", role: .destructive) { Task { await model.cancelTrial() } }
                .disabled(model.working)
                .accessibilityIdentifier("models.cancelTrial")
        }
        if !trial.cases.isEmpty {
            DisclosureGroup {
                ForEach(trial.cases) { c in
                    HouseholdTrialCaseRow(c: c)
                }
            } label: {
                Text("What it was asked")
            }
        }
    }
}

struct HouseholdTrialCaseRow: View {
    let c: HouseholdArea.TrialCase

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Label {
                Text(c.about.isEmpty ? c.name : c.about)
            } icon: {
                Image(systemName: c.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(c.ok ? .green : .red)
                    .accessibilityLabel(c.ok ? Text("Passed") : Text("Failed"))
            }
            ForEach(c.problems, id: \.self) { p in
                Text(p).font(.footnote).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

// MARK: One model

/// One model's settings, in a sheet over the list: on the menu, the default, its health and
/// "Check", "Try it" and its score, what the catalogue said of it, its name and words, Remove.
struct HouseholdModelDetail: View {
    typealias H = HouseholdArea
    @Bindable var model: HouseholdModelsModel
    let id: String
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var about = ""
    @State private var local = false
    @State private var provider = ""
    @State private var seeded = false
    @State private var saved = false
    @State private var confirmRemove = false
    @State private var confirmDefault = false

    var body: some View {
        NavigationStack {
            Form {
                if let m = model.model(id) {
                    menuSection(m)
                    healthSection(m)
                    trialSection(m)
                    aboutSection(m)
                    wordsSection(m)
                    if model.error != nil {
                        Section { YouError(message: model.error) }
                    }
                    if !m.isDefault {
                        Section {
                            Button("Remove from the list", role: .destructive) { confirmRemove = true }
                                .disabled(model.working)
                                .accessibilityIdentifier("model.remove")
                        }
                    }
                } else {
                    Text("This model is no longer on the list.").foregroundStyle(.secondary)
                }
            }
            .navigationTitle(model.model(id)?.name ?? id)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .onAppear { seed() }
            .confirmationDialog(
                Text("Remove \(model.model(id)?.name ?? id)?"),
                isPresented: $confirmRemove, titleVisibility: .visible
            ) {
                Button("Remove", role: .destructive) {
                    Task { if await model.remove(id) { dismiss() } }
                }
                Button("Keep", role: .cancel) {}
            } message: {
                Text("Members who chose it go back to the household's default. You can add it again.")
            }
            .confirmationDialog(
                Text("Make \(model.model(id)?.name ?? id) the household's default?"),
                isPresented: $confirmDefault, titleVisibility: .visible
            ) {
                Button("Make default") { Task { await model.makeDefault(id) } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("It will answer everyone who has not chosen a model of their own, without asking them first. It runs outside the house, at \(model.model(id).map(H.whereItRuns) ?? ""): what they ask, and the calendar, task and email details luach looks up to answer, are sent there.")
            }
        }
    }

    private func seed() {
        guard !seeded, let m = model.model(id) else { return }
        seeded = true
        name = m.name
        about = m.about
        local = m.local
        provider = m.providerSet
    }

    private func menuSection(_ m: H.ManagedModel) -> some View {
        Section {
            Toggle("On the members' menu", isOn: Binding(
                get: { m.enabled },
                set: { on in Task { await model.setEnabled(m.id, on) } }
            ))
            .disabled(m.isDefault || model.working)
            .accessibilityIdentifier("model.enabled")
            if m.isDefault {
                Label("The household's default", systemImage: "star.fill")
                    .foregroundStyle(Color.accentColor)
            } else {
                Button("Make default") {
                    if m.local {
                        Task { await model.makeDefault(m.id) }
                    } else {
                        confirmDefault = true
                    }
                }
                .disabled(!m.answering || model.working)
                .accessibilityIdentifier("model.makeDefault")
            }
        } footer: {
            if m.isDefault {
                Text("It answers everyone who has not chosen a model, so it is always on the menu.")
            } else if !m.answering {
                Text("A model that is not answering cannot be the default.")
            } else {
                Text("Members can choose it when it is on. Before their questions go to a model outside the house, each member is asked.")
            }
        }
    }

    private func healthSection(_ m: H.ManagedModel) -> some View {
        Section {
            if m.answering {
                Label("Answering", systemImage: "checkmark.circle").foregroundStyle(.green)
            } else {
                YouModelHealthNote(health: m.health)
            }
            if let last = m.lastOkAt, YouKit.date(last) != nil {
                LabeledContent("Last answered", value: YouKit.relative(last))
            }
            Button {
                Task { await model.check(m.id) }
            } label: {
                HStack {
                    Text("Check")
                    if model.checking == m.id { Spacer(); ProgressView() }
                }
            }
            .disabled(model.checking != nil)
            .accessibilityIdentifier("model.check")
            if let reply = model.checked[m.id] {
                if reply.ok {
                    Label("It answered.", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                } else {
                    Text(reply.reason?.isEmpty == false ? reply.reason! : String(localized: "It did not answer."))
                        .foregroundStyle(.red)
                }
            }
        } header: {
            Text("Health")
        } footer: {
            Text("Check sends it one tiny request. A model that stops answering is shown to members as not answering, and they cannot pick it.")
        }
    }

    private func trialSection(_ m: H.ManagedModel) -> some View {
        Section {
            if let score = m.trial {
                HStack {
                    HouseholdScoreTag(passed: score.passed, total: score.total, verdict: score.grade)
                    if let at = score.at, YouKit.date(at) != nil {
                        Spacer()
                        Text(YouKit.relative(at)).font(.footnote).foregroundStyle(.secondary)
                    }
                }
                if score.grade == .low { HouseholdLowScoreWarning() }
            } else {
                Text("Not tried yet.").foregroundStyle(.secondary)
            }
            if let trial = model.trial, trial.model == m.id, trial.running || trial.id == model.followed {
                HouseholdTrialProgress(model: model, trial: trial)
            }
            Button("Try it") { Task { await model.startTrial(m.id) } }
                .disabled(!model.canTry(m.id) || model.working)
                .accessibilityIdentifier("model.try")
        } header: {
            Text("Try it")
        } footer: {
            VStack(alignment: .leading, spacing: 4) {
                Text("A dozen of luach's own questions, to see whether it can run luach. The score is advice: you decide whether to put it on the menu.")
                if model.running != nil && model.running?.model != m.id {
                    Text("Another trial is running.")
                }
                Text("Trials left today: \(model.trialsLeft)")
            }
        }
    }

    @ViewBuilder
    private func aboutSection(_ m: H.ManagedModel) -> some View {
        let facts = [H.contextText(m.meta.contextLength), H.toolsText(m.meta.tools),
                     H.priceText(m.meta.priceIn, m.meta.priceOut)].compactMap { $0 }
        Section {
            LabeledContent("Model id") {
                Text(m.id).font(.footnote.monospaced()).textSelection(.enabled)
            }
            ForEach(facts, id: \.self) { Text($0) }
        } header: {
            Text("From the catalogue")
        }
    }

    private func wordsSection(_ m: H.ManagedModel) -> some View {
        let change = H.change(of: m, name: name, about: about, local: local, provider: provider)
        let nameEmpty = name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return Section {
            TextField("Name", text: $name)
                .accessibilityIdentifier("model.name")
                .onChange(of: name) { saved = false }
            TextField("What members read about it", text: $about, axis: .vertical)
                .lineLimit(2...5)
                .accessibilityIdentifier("model.about")
                .onChange(of: about) { saved = false }
            Toggle("Runs at home", isOn: $local)
                .accessibilityIdentifier("model.local")
                .onChange(of: local) { saved = false }
            if !local {
                TextField("Provider", text: $provider, prompt: Text(m.provider.isEmpty ? String(localized: "Who answers it") : m.provider))
                    .accessibilityIdentifier("model.provider")
                    .onChange(of: provider) { saved = false }
            }
            Button("Save") {
                guard let change else { return }
                Task { saved = await model.save(change) }
            }
            .disabled(change == nil || nameEmpty || model.working)
            .accessibilityIdentifier("model.save")
            if saved && change == nil {
                YouDone("Saved.")
            }
        } header: {
            Text("Name and description")
        } footer: {
            Text("Turn on “Runs at home” only for a model on the household's own machine: members are not asked before their questions go to it.")
        }
    }
}

// MARK: Adding

/// "Add a model": searches the catalogue (the model server's own list), shows what each costs and
/// can do, recommends the always-current names, and adds the one picked with the owner's words.
struct HouseholdAddModelView: View {
    typealias H = HouseholdArea
    @Bindable var model: HouseholdModelsModel
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var query: String
    @State private var found: H.Catalogue?
    @State private var searchError: String?
    @State private var searching = false
    @State private var draft: HouseholdModelDraft?

    init(model: HouseholdModelsModel, query: String = "") {
        self.model = model
        _query = State(initialValue: query)
    }

    private var typed: String { query.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        NavigationStack {
            List {
                if let found, !found.configured {
                    Section {
                        Text("No catalogue is set up, so there is nothing to search. Type a model's id to add it by its id.")
                            .foregroundStyle(.secondary)
                    }
                }
                if let message = searchError ?? found.flatMap({ $0.error.isEmpty ? nil : $0.error }) {
                    Section { Text(message).foregroundStyle(.red) }
                }
                if !typed.isEmpty && !(found?.models.contains { $0.id == typed } ?? false) {
                    Section {
                        Button {
                            draft = HouseholdModelDraft(id: typed, name: "")
                        } label: {
                            Label("Add “\(typed)” by its id", systemImage: "plus")
                        }
                        .accessibilityIdentifier("catalogue.byId")
                    }
                }
                if let found, !found.models.isEmpty {
                    Section {
                        ForEach(found.models) { entry in
                            Button {
                                draft = HouseholdModelDraft(entry)
                            } label: {
                                HouseholdCatalogueRow(entry: entry)
                            }
                            .tint(.primary)
                            .disabled(entry.onMenu)
                            .accessibilityIdentifier("catalogue.\(entry.id)")
                        }
                    } header: {
                        Text(found.source.isEmpty ? String(localized: "Catalogue") : String(localized: "From \(found.source)"))
                    }
                } else if let found, found.configured, found.error.isEmpty, !searching {
                    Section { Text("Nothing matches.").foregroundStyle(.secondary) }
                }
            }
            .overlay { if found == nil && searchError == nil { ProgressView() } }
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search models")
            .autocorrectionDisabled()
            .textInputAutocapitalization(.never)
            .task(id: query) {
                // A pause after the last key, so each word is not a request.
                if found != nil { try? await Task.sleep(for: .milliseconds(350)) }
                guard !Task.isCancelled else { return }
                await search()
            }
            .navigationTitle("Add a model")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .navigationDestination(item: $draft) { d in
                HouseholdAddModelForm(model: model, draft: d, catalogue: found?.models ?? []) { dismiss() }
            }
        }
    }

    private func search() async {
        searching = true
        defer { searching = false }
        do {
            found = try await H.Client(api: session.api).catalogue(query)
            searchError = nil
        } catch is CancellationError {
        } catch {
            searchError = error.localizedDescription
        }
    }
}

/// A catalogue entry: name, id, context, tools, price, and whether it is the always-current name.
struct HouseholdCatalogueRow: View {
    typealias H = HouseholdArea
    let entry: H.CatalogueEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(alignment: .firstTextBaseline) {
                Text(entry.name).font(.body.weight(.medium))
                if entry.onMenu { H.Tag(text: "On the list") }
            }
            Text(entry.id).font(.caption.monospaced()).foregroundStyle(.secondary)
            if entry.recommended || entry.alias {
                Label("Recommended: always the newest version", systemImage: "arrow.triangle.2.circlepath")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.green)
            }
            let facts = [H.contextText(entry.contextLength), H.toolsText(entry.tools),
                         H.priceText(entry.priceIn, entry.priceOut)].compactMap { $0 }
            if !facts.isEmpty {
                Text(facts.joined(separator: " · ")).font(.caption).foregroundStyle(.secondary)
            }
            if entry.tools == false {
                Text("luach needs a model that can use tools.").font(.caption).foregroundStyle(.orange)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// What "Add" will send, from a catalogue entry or a typed id.
struct HouseholdModelDraft: Identifiable, Hashable {
    var id: String
    var name: String
    var entry: HouseholdArea.CatalogueEntry?

    init(id: String, name: String) {
        self.id = id
        self.name = name
    }

    init(_ entry: HouseholdArea.CatalogueEntry) {
        id = entry.id
        name = entry.name
        self.entry = entry
    }
}

struct HouseholdAddModelForm: View {
    typealias H = HouseholdArea
    @Bindable var model: HouseholdModelsModel
    /// The search it was picked from, to find the always-current name's own entry.
    let catalogue: [H.CatalogueEntry]
    let added: () -> Void
    @State private var draft: HouseholdModelDraft
    @State private var name: String
    @State private var about = ""
    @State private var local = false
    @State private var provider = ""
    @State private var tryIt = true

    init(model: HouseholdModelsModel, draft: HouseholdModelDraft, catalogue: [H.CatalogueEntry] = [],
         added: @escaping () -> Void) {
        self.model = model
        self.catalogue = catalogue
        self.added = added
        _draft = State(initialValue: draft)
        _name = State(initialValue: draft.name)
    }

    /// Switches to the always-current name: its own entry when the search listed it.
    private func useAlias(_ alias: String) {
        if let entry = catalogue.first(where: { $0.id == alias }) {
            draft = HouseholdModelDraft(entry)
            name = entry.name
        } else {
            draft = HouseholdModelDraft(id: alias, name: name)
        }
    }

    /// What Add sends: the owner's words, trimmed; empty ones left for luach to fill in.
    var request: H.NewModel {
        func clean(_ s: String) -> String? {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        return H.NewModel(id: draft.id, name: clean(name), about: clean(about), local: local,
                          provider: local ? nil : clean(provider), try: tryIt)
    }

    var body: some View {
        Form {
            Section {
                LabeledContent("Model id") {
                    Text(draft.id).font(.footnote.monospaced()).textSelection(.enabled)
                }
                if let entry = draft.entry {
                    if entry.recommended || entry.alias {
                        Label("Recommended: always the newest version", systemImage: "arrow.triangle.2.circlepath")
                            .foregroundStyle(.green)
                    }
                    ForEach([H.contextText(entry.contextLength), H.toolsText(entry.tools),
                             H.priceText(entry.priceIn, entry.priceOut)].compactMap { $0 }, id: \.self) { Text($0) }
                    if !entry.aliasOfIt.isEmpty {
                        Button {
                            useAlias(entry.aliasOfIt)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Use \(entry.aliasOfIt) instead")
                                Text("It always points at the newest version of this model, so the menu never goes stale.")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .accessibilityIdentifier("add.useAlias")
                    }
                }
            }
            Section {
                TextField("Name", text: $name, prompt: Text(draft.entry?.name ?? draft.id))
                    .accessibilityIdentifier("add.name")
                TextField("What members read about it", text: $about, axis: .vertical)
                    .lineLimit(2...5)
                    .accessibilityIdentifier("add.about")
                Toggle("Runs at home", isOn: $local)
                    .accessibilityIdentifier("add.local")
                if !local {
                    TextField("Provider", text: $provider,
                              prompt: Text(draft.entry?.provider.isEmpty == false ? draft.entry!.provider : String(localized: "Who answers it")))
                        .accessibilityIdentifier("add.provider")
                }
            } header: {
                Text("Name and description")
            } footer: {
                Text("Turn on “Runs at home” only for a model on the household's own machine: members are not asked before their questions go to it.")
            }
            Section {
                Toggle("Try it once added", isOn: $tryIt)
                    .accessibilityIdentifier("add.try")
            } footer: {
                Text("It is added off the menu: turn it on when you are happy with it. Trials left today: \(model.trialsLeft)")
            }
            if model.error != nil {
                Section { YouError(message: model.error) }
            }
        }
        .navigationTitle(draft.entry?.name ?? draft.id)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                if model.working {
                    ProgressView()
                } else {
                    Button("Add") {
                        Task { if await model.add(request) { added() } }
                    }
                    .accessibilityIdentifier("add.confirm")
                }
            }
        }
    }
}
