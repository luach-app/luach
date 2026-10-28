import Foundation
import SwiftUI

/// Settings › Household › Models: the owner's list of the AI models members may choose from
/// (`/api/models/manage`), its shapes, its calls and the rules behind the screen, kept apart
/// from the views so each can be tested on its own.
extension HouseholdArea {
    typealias ModelHealth = YouKit.ModelMenu.Health

    // MARK: Shapes

    /// What the catalogue said of a model when it was added. Prices are USD per million tokens.
    struct ModelMeta: Decodable, Equatable {
        var contextLength: Int?
        var tools: Bool?
        var priceIn: Double?
        var priceOut: Double?

        init(contextLength: Int? = nil, tools: Bool? = nil, priceIn: Double? = nil, priceOut: Double? = nil) {
            self.contextLength = contextLength
            self.tools = tools
            self.priceIn = priceIn
            self.priceOut = priceOut
        }

        private enum Keys: String, CodingKey { case contextLength, tools, priceIn, priceOut }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            contextLength = try? c.decodeIfPresent(Int.self, forKey: .contextLength)
            tools = try? c.decodeIfPresent(Bool.self, forKey: .tools)
            priceIn = try? c.decodeIfPresent(Double.self, forKey: .priceIn)
            priceOut = try? c.decodeIfPresent(Double.self, forKey: .priceOut)
        }
    }

    /// How a model did in "Try it": the score is advice, the owner decides.
    enum Verdict: String {
        /// Every case passed.
        case good
        /// At least 80% passed.
        case fair
        /// Below that: members may get wrong answers.
        case low
    }

    /// A model's last finished run.
    struct TrialScore: Decodable, Equatable {
        let passed: Int
        let total: Int
        let verdict: String?
        let at: String?

        /// The server's verdict; one it did not give (a run with no cases) is none.
        var grade: Verdict? { verdict.flatMap(Verdict.init(rawValue:)) }
    }

    /// One model on the owner's list.
    struct ManagedModel: Decodable, Identifiable, Equatable {
        let id: String
        let name: String
        let about: String
        let local: Bool
        /// Who answers it, in words: the owner's, or worked out from the id; "" at home.
        let provider: String
        /// The owner's own words for the provider ("" when luach works it out).
        let providerSet: String
        let enabled: Bool
        let position: Int
        let meta: ModelMeta
        let failures: Int
        let lastOkAt: String?
        let health: ModelHealth
        let isDefault: Bool
        let trial: TrialScore?

        init(id: String, name: String, about: String = "", local: Bool = false, provider: String = "",
             providerSet: String = "", enabled: Bool = true, position: Int = 0, meta: ModelMeta = .init(),
             failures: Int = 0, lastOkAt: String? = nil, health: ModelHealth = .ok, isDefault: Bool = false,
             trial: TrialScore? = nil) {
            self.id = id
            self.name = name
            self.about = about
            self.local = local
            self.provider = provider
            self.providerSet = providerSet
            self.enabled = enabled
            self.position = position
            self.meta = meta
            self.failures = failures
            self.lastOkAt = lastOkAt
            self.health = health
            self.isDefault = isDefault
            self.trial = trial
        }

        private enum Keys: String, CodingKey {
            case id, name, about, local, provider, providerSet, enabled, position, meta, failures, lastOkAt
            case health, isDefault, trial
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            id = try c.decode(String.self, forKey: .id)
            let named = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
            name = named.isEmpty ? id : named
            about = (try? c.decodeIfPresent(String.self, forKey: .about)) ?? ""
            local = (try? c.decodeIfPresent(Bool.self, forKey: .local)) ?? false
            provider = (try? c.decodeIfPresent(String.self, forKey: .provider)) ?? ""
            providerSet = (try? c.decodeIfPresent(String.self, forKey: .providerSet)) ?? ""
            enabled = (try? c.decodeIfPresent(Bool.self, forKey: .enabled)) ?? false
            position = (try? c.decodeIfPresent(Int.self, forKey: .position)) ?? 0
            meta = (try? c.decodeIfPresent(ModelMeta.self, forKey: .meta)) ?? .init()
            failures = (try? c.decodeIfPresent(Int.self, forKey: .failures)) ?? 0
            lastOkAt = try? c.decodeIfPresent(String.self, forKey: .lastOkAt)
            health = (try? c.decodeIfPresent(ModelHealth.self, forKey: .health)) ?? .ok
            isDefault = (try? c.decodeIfPresent(Bool.self, forKey: .isDefault)) ?? false
            trial = try? c.decodeIfPresent(TrialScore.self, forKey: .trial)
        }

        var answering: Bool { health.answering }
    }

    /// One of the trial's cases, as it went.
    struct TrialCase: Decodable, Equatable, Identifiable {
        let name: String
        let about: String
        let ok: Bool
        let problems: [String]
        let tools: [[String]]
        var id: String { name }

        private enum Keys: String, CodingKey { case name = "case", about, ok, problems, tools }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
            about = (try? c.decodeIfPresent(String.self, forKey: .about)) ?? ""
            ok = (try? c.decodeIfPresent(Bool.self, forKey: .ok)) ?? false
            problems = (try? c.decodeIfPresent([String].self, forKey: .problems)) ?? []
            tools = (try? c.decodeIfPresent([[String]].self, forKey: .tools)) ?? []
        }
    }

    /// A "Try it" run: running, or how it ended.
    struct Trial: Decodable, Equatable, Identifiable {
        let id: Int
        let model: String
        let status: String
        let requestedBy: String?
        let startedAt: String?
        let finishedAt: String?
        let done: Int
        let passed: Int
        let total: Int
        let verdict: String?
        let cases: [TrialCase]
        let error: String?

        private enum Keys: String, CodingKey {
            case id, model, status, requestedBy, startedAt, finishedAt, done, passed, total, verdict, cases, error
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            id = try c.decode(Int.self, forKey: .id)
            model = (try? c.decodeIfPresent(String.self, forKey: .model)) ?? ""
            status = (try? c.decodeIfPresent(String.self, forKey: .status)) ?? ""
            requestedBy = try? c.decodeIfPresent(String.self, forKey: .requestedBy)
            startedAt = try? c.decodeIfPresent(String.self, forKey: .startedAt)
            finishedAt = try? c.decodeIfPresent(String.self, forKey: .finishedAt)
            done = (try? c.decodeIfPresent(Int.self, forKey: .done)) ?? 0
            passed = (try? c.decodeIfPresent(Int.self, forKey: .passed)) ?? 0
            total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? 0
            verdict = try? c.decodeIfPresent(String.self, forKey: .verdict)
            cases = (try? c.decodeIfPresent([TrialCase].self, forKey: .cases)) ?? []
            error = try? c.decodeIfPresent(String.self, forKey: .error)
        }

        var running: Bool { status == "running" }
        var grade: Verdict? { verdict.flatMap(Verdict.init(rawValue:)) }
    }

    /// Where "Add a model" searches.
    struct CatalogueSource: Decodable, Equatable {
        let configured: Bool
        let source: String
    }

    /// `GET /api/models/manage`, and the answer to every change.
    struct ModelSnapshot: Decodable {
        var `default`: String
        var configured: Bool
        var models: [ManagedModel]
        var trial: Trial?
        var trialsLeftToday: Int
        var catalogue: CatalogueSource?

        private enum Keys: String, CodingKey { case `default`, configured, models, trial, trialsLeftToday, catalogue }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            `default` = (try? c.decodeIfPresent(String.self, forKey: .default)) ?? ""
            configured = (try? c.decodeIfPresent(Bool.self, forKey: .configured)) ?? false
            models = try c.decode([ManagedModel].self, forKey: .models)
            trial = try? c.decodeIfPresent(Trial.self, forKey: .trial)
            trialsLeftToday = (try? c.decodeIfPresent(Int.self, forKey: .trialsLeftToday)) ?? 0
            catalogue = try? c.decodeIfPresent(CatalogueSource.self, forKey: .catalogue)
        }
    }

    /// `POST /api/models/manage`: the list, the model added, and whether its trial started.
    struct ModelAdded: Decodable {
        let snapshot: ModelSnapshot
        let added: String
        let trialStarted: Bool
        /// Why no trial started (the day's trials used up, one already running), else "".
        let note: String

        private enum Keys: String, CodingKey { case added, trialStarted, note }

        init(from decoder: Decoder) throws {
            snapshot = try ModelSnapshot(from: decoder)
            let c = try decoder.container(keyedBy: Keys.self)
            added = (try? c.decodeIfPresent(String.self, forKey: .added)) ?? ""
            trialStarted = (try? c.decodeIfPresent(Bool.self, forKey: .trialStarted)) ?? false
            note = (try? c.decodeIfPresent(String.self, forKey: .note)) ?? ""
        }
    }

    /// `GET`/`POST /api/models/manage/trial`.
    struct TrialReply: Decodable {
        let trial: Trial?
        let trialsLeftToday: Int?
    }

    /// `POST /api/models/manage/trial/cancel`.
    struct TrialCancelled: Decodable {
        let cancelled: Bool
        let trial: Trial?
    }

    /// `POST /api/models/manage/check`: whether it answered, and the list brought up to date.
    struct CheckReply: Decodable {
        let ok: Bool
        let reason: String?
        let health: ModelHealth?
        let models: [ManagedModel]?
    }

    /// A model the catalogue lists. An alias is a moving name that always follows the newest version.
    struct CatalogueEntry: Decodable, Identifiable, Hashable {
        let id: String
        let name: String
        let contextLength: Int?
        let tools: Bool?
        let priceIn: Double?
        let priceOut: Double?
        let alias: Bool
        let provider: String
        let onMenu: Bool
        let recommended: Bool
        /// On a pinned version: the alias that would follow it ("" when there is none).
        let aliasOfIt: String

        private enum Keys: String, CodingKey {
            case id, name, contextLength, tools, priceIn, priceOut, alias, provider, onMenu, recommended, aliasOfIt
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            id = try c.decode(String.self, forKey: .id)
            let named = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
            name = named.isEmpty ? id : named
            contextLength = try? c.decodeIfPresent(Int.self, forKey: .contextLength)
            tools = try? c.decodeIfPresent(Bool.self, forKey: .tools)
            priceIn = try? c.decodeIfPresent(Double.self, forKey: .priceIn)
            priceOut = try? c.decodeIfPresent(Double.self, forKey: .priceOut)
            alias = (try? c.decodeIfPresent(Bool.self, forKey: .alias)) ?? false
            provider = (try? c.decodeIfPresent(String.self, forKey: .provider)) ?? ""
            onMenu = (try? c.decodeIfPresent(Bool.self, forKey: .onMenu)) ?? false
            recommended = (try? c.decodeIfPresent(Bool.self, forKey: .recommended)) ?? alias
            aliasOfIt = (try? c.decodeIfPresent(String.self, forKey: .aliasOfIt)) ?? ""
        }
    }

    /// `GET /api/models/catalogue`: a search, or why there is none.
    struct Catalogue: Decodable {
        let configured: Bool
        let source: String
        let models: [CatalogueEntry]
        let error: String

        private enum Keys: String, CodingKey { case configured, source, models, error }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            configured = (try? c.decodeIfPresent(Bool.self, forKey: .configured)) ?? false
            source = (try? c.decodeIfPresent(String.self, forKey: .source)) ?? ""
            models = (try? c.decodeIfPresent([CatalogueEntry].self, forKey: .models)) ?? []
            error = (try? c.decodeIfPresent(String.self, forKey: .error)) ?? ""
        }
    }

    /// What the owner adds: the id, and their own words. `try` false adds it without a trial.
    struct NewModel: Encodable, Equatable {
        var id: String
        var name: String?
        var about: String?
        var local: Bool?
        var provider: String?
        var `try`: Bool?
    }

    /// A change to one model: only the fields set are sent.
    struct ModelChange: Encodable, Equatable {
        var id: String
        var name: String?
        var about: String?
        var provider: String?
        var enabled: Bool?
        var local: Bool?

        var isEmpty: Bool { name == nil && about == nil && provider == nil && enabled == nil && local == nil }
    }
}

// MARK: The calls

extension HouseholdArea.Client {
    private struct ModelID: Encodable { let id: String }

    func manageModels() async throws -> HouseholdArea.ModelSnapshot {
        try await api.get("/api/models/manage")
    }

    /// Adds a model, off the members' menu, and starts its trial unless `new.try` is false.
    func addModel(_ new: HouseholdArea.NewModel) async throws -> HouseholdArea.ModelAdded {
        try await api.post("/api/models/manage", new)
    }

    func changeModel(_ change: HouseholdArea.ModelChange) async throws -> HouseholdArea.ModelSnapshot {
        try await api.patch("/api/models/manage", change)
    }

    func removeModel(_ id: String) async throws -> HouseholdArea.ModelSnapshot {
        try await api.post("/api/models/manage/remove", ModelID(id: id))
    }

    /// Every id on the list, in the new order.
    func reorderModels(_ ids: [String]) async throws -> HouseholdArea.ModelSnapshot {
        struct Body: Encodable { let ids: [String] }
        return try await api.put("/api/models/manage/order", Body(ids: ids))
    }

    func makeDefault(_ id: String) async throws -> HouseholdArea.ModelSnapshot {
        try await api.put("/api/models/manage/default", ModelID(id: id))
    }

    func trial() async throws -> HouseholdArea.TrialReply {
        try await api.get("/api/models/manage/trial")
    }

    /// 409 with the server's sentence when one is running or the day's trials are used up.
    func startTrial(_ id: String) async throws -> HouseholdArea.TrialReply {
        try await api.post("/api/models/manage/trial", ModelID(id: id))
    }

    func cancelTrial() async throws -> HouseholdArea.TrialCancelled {
        try await api.post("/api/models/manage/trial/cancel")
    }

    /// One tiny request to the model: clears or sets "not answering".
    func checkModel(_ id: String) async throws -> HouseholdArea.CheckReply {
        try await api.post("/api/models/manage/check", ModelID(id: id))
    }

    /// The catalogue's models matching every word of `query`; the whole list when it is empty.
    func catalogue(_ query: String) async throws -> HouseholdArea.Catalogue {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        return try await api.get("/api/models/catalogue", query: q.isEmpty ? [:] : ["q": String(q.prefix(100))])
    }
}

// MARK: Rules

extension HouseholdArea {
    /// The list in the owner's order (the server's, by position; ties keep the server's order).
    static func ordered(_ models: [ManagedModel]) -> [ManagedModel] {
        models.enumerated().sorted { a, b in
            a.element.position != b.element.position ? a.element.position < b.element.position : a.offset < b.offset
        }.map(\.element)
    }

    /// The ids after a drag in the list.
    static func moved(_ ids: [String], from source: IndexSet, to destination: Int) -> [String] {
        var next = ids
        next.move(fromOffsets: source, toOffset: destination)
        return next
    }

    /// Who answers a model, for its row: "At home", the provider, or "A cloud provider".
    static func whereItRuns(_ model: ManagedModel) -> String {
        if model.local { return String(localized: "At home") }
        return model.provider.isEmpty ? String(localized: "A cloud provider") : model.provider
    }

    /// "11 of 12" with its tint: green when all passed, orange when most, red below 80%.
    static func scoreText(_ passed: Int, _ total: Int) -> String {
        String(localized: "\(passed) of \(total) passed")
    }

    static func tint(_ verdict: Verdict?) -> Color {
        switch verdict {
        case .good: .green
        case .fair: .orange
        case .low: .red
        case nil: .secondary
        }
    }

    /// "128K tokens", "1M tokens"; nil when the catalogue does not say.
    static func contextText(_ tokens: Int?) -> String? {
        guard let tokens, tokens > 0 else { return nil }
        let n: String
        if tokens >= 1_000_000 {
            n = (Double(tokens) / 1_000_000).formatted(.number.precision(.fractionLength(0...1))) + "M"
        } else if tokens >= 1_000 {
            n = (Double(tokens) / 1_000).formatted(.number.precision(.fractionLength(0))) + "K"
        } else {
            n = "\(tokens)"
        }
        return String(localized: "\(n) tokens of context")
    }

    /// "$0.30 in, $1.20 out per million tokens", "No charge", or nil when the catalogue does not say.
    static func priceText(_ priceIn: Double?, _ priceOut: Double?) -> String? {
        guard let priceIn, let priceOut else { return nil }
        if priceIn == 0 && priceOut == 0 { return String(localized: "No charge") }
        let style = FloatingPointFormatStyle<Double>.Currency(code: "USD").precision(.fractionLength(2...4))
        return String(localized: "\(priceIn.formatted(style)) in, \(priceOut.formatted(style)) out per million tokens")
    }

    static func toolsText(_ tools: Bool?) -> String? {
        guard let tools else { return nil }
        return tools ? String(localized: "Can use tools") : String(localized: "Cannot use tools")
    }

    /// The run's progress, 0…1; nil before the server knows how many cases there are.
    static func progress(_ trial: Trial) -> Double? {
        guard trial.total > 0 else { return nil }
        return min(1, Double(trial.done) / Double(trial.total))
    }

    /// The model's name on the list, or its id once it is gone from it.
    static func modelName(_ id: String, in models: [ManagedModel]) -> String {
        models.first { $0.id == id }?.name ?? id
    }

    /// The edit form's change against the model as saved: nil when nothing changed.
    static func change(of model: ManagedModel, name: String, about: String, local: Bool, provider: String) -> ModelChange? {
        var c = ModelChange(id: model.id)
        let n = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let a = about.trimmingCharacters(in: .whitespacesAndNewlines)
        let p = provider.trimmingCharacters(in: .whitespacesAndNewlines)
        if n != model.name { c.name = n }
        if a != model.about { c.about = a }
        if local != model.local { c.local = local }
        if !local && p != model.providerSet { c.provider = p }
        return c.isEmpty ? nil : c
    }
}

// MARK: The screen's state

/// What Settings › Household › Models shows and does; the views only lay it out. Every write
/// answers with the whole list, which replaces what was shown.
@Observable
final class HouseholdModelsModel {
    typealias H = HouseholdArea

    private(set) var snapshot: H.ModelSnapshot?
    private(set) var loadError: String?
    /// The server's sentence after a change it refused.
    var error: String?
    /// What the last action said that is not an error ("No trial started: …", "It answered.").
    var notice: String?
    private(set) var working = false
    /// The model whose "Check" is on its way.
    private(set) var checking: String?
    /// The answer to the last "Check", per model: nil while none was asked.
    private(set) var checked: [String: H.CheckReply] = [:]
    /// The trial the screen has followed since it opened (so a finished one is shown, an old one not).
    private(set) var followed: Int?
    /// How often a running trial is asked about.
    var pollEvery: Duration = .seconds(2)
    private var generation = 0

    private let client: H.Client

    init(api: API) {
        client = H.Client(api: api)
    }

    var models: [H.ManagedModel] { H.ordered(snapshot?.models ?? []) }
    var trial: H.Trial? { snapshot?.trial }
    var trialsLeft: Int { snapshot?.trialsLeftToday ?? 0 }
    var running: H.Trial? { trial?.running == true ? trial : nil }
    /// The running trial's id: the screen follows it while there is one.
    var runningID: Int? { running?.id }

    /// The latest trial when it is worth a section: running, or one this screen saw run.
    var shownTrial: H.Trial? {
        guard let trial else { return nil }
        return trial.running || trial.id == followed ? trial : nil
    }

    func model(_ id: String) -> H.ManagedModel? { snapshot?.models.first { $0.id == id } }

    /// "Try it" for `id`: not while another runs, nor with none left today.
    func canTry(_ id: String) -> Bool { running == nil && trialsLeft > 0 && model(id) != nil }

    func load() async {
        do {
            adopt(try await client.manageModels())
            loadError = nil
        } catch is CancellationError {
        } catch {
            loadError = error.localizedDescription
        }
    }

    private func adopt(_ next: H.ModelSnapshot) {
        snapshot = next
        if let t = next.trial, t.running { followed = t.id }
    }

    /// Runs a change; the answer is the whole list. False when it was refused (`error` says why).
    @discardableResult
    private func change(_ call: () async throws -> H.ModelSnapshot) async -> Bool {
        working = true
        defer { working = false }
        error = nil
        notice = nil
        do {
            adopt(try await call())
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    @discardableResult
    func setEnabled(_ id: String, _ on: Bool) async -> Bool {
        await change { try await client.changeModel(.init(id: id, enabled: on)) }
    }

    @discardableResult
    func save(_ change: H.ModelChange) async -> Bool {
        await self.change { try await client.changeModel(change) }
    }

    @discardableResult
    func makeDefault(_ id: String) async -> Bool {
        await change { try await client.makeDefault(id) }
    }

    @discardableResult
    func remove(_ id: String) async -> Bool {
        await change { try await client.removeModel(id) }
    }

    /// A drag: shown at once in the new order, put back if the server refuses it.
    func move(from source: IndexSet, to destination: Int) async {
        guard var snap = snapshot else { return }
        let before = snap
        let ids = H.moved(models.map(\.id), from: source, to: destination)
        guard ids != models.map(\.id) else { return }
        snap.models = ids.enumerated().compactMap { n, id in
            snap.models.first { $0.id == id }.map { reposition($0, n) }
        }
        snapshot = snap
        let saved = await change { try await client.reorderModels(ids) }
        if !saved { snapshot = before }
    }

    private func reposition(_ m: H.ManagedModel, _ position: Int) -> H.ManagedModel {
        H.ManagedModel(id: m.id, name: m.name, about: m.about, local: m.local, provider: m.provider,
                       providerSet: m.providerSet, enabled: m.enabled, position: position, meta: m.meta,
                       failures: m.failures, lastOkAt: m.lastOkAt, health: m.health, isDefault: m.isDefault,
                       trial: m.trial)
    }

    /// Adds a model (off the menu) and, unless `tryIt` is off, starts its trial. True when added.
    @discardableResult
    func add(_ new: H.NewModel) async -> Bool {
        working = true
        defer { working = false }
        error = nil
        notice = nil
        do {
            let reply = try await client.addModel(new)
            adopt(reply.snapshot)
            if !reply.trialStarted && !reply.note.isEmpty {
                notice = String(localized: "Added, without a trial: \(reply.note)")
            }
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func startTrial(_ id: String) async {
        working = true
        defer { working = false }
        error = nil
        notice = nil
        do {
            let reply = try await client.startTrial(id)
            take(reply)
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func take(_ reply: H.TrialReply) {
        guard var snap = snapshot else { return }
        snap.trial = reply.trial
        if let left = reply.trialsLeftToday { snap.trialsLeftToday = left }
        adopt(snap)
    }

    func cancelTrial() async {
        working = true
        defer { working = false }
        error = nil
        do {
            let reply = try await client.cancelTrial()
            if var snap = snapshot {
                snap.trial = reply.trial
                snapshot = snap
            }
            // Another copy of luach may be running it: the next look says how it ended.
            if !reply.cancelled { await poll() }
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// One look at the trial; when it has ended, the list again, for the model's new score.
    func poll() async {
        do {
            let reply = try await client.trial()
            let wasRunning = trial?.running == true
            take(reply)
            if wasRunning && reply.trial?.running != true {
                await load()
            }
        } catch is CancellationError {
        } catch {
            // A look that failed is tried again on the next tick; the run goes on regardless.
        }
    }

    /// Asks about the running trial every `pollEvery` until it ends or the screen goes. The latest
    /// caller does the asking, so two views on the same model never both poll.
    func followTrial() async {
        generation += 1
        let mine = generation
        while running != nil && generation == mine && !Task.isCancelled {
            try? await Task.sleep(for: pollEvery)
            guard !Task.isCancelled, generation == mine else { return }
            await poll()
        }
    }

    func check(_ id: String) async {
        checking = id
        defer { checking = nil }
        error = nil
        notice = nil
        do {
            let reply = try await client.checkModel(id)
            checked[id] = reply
            if let models = reply.models, var snap = snapshot {
                snap.models = models
                snapshot = snap
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
