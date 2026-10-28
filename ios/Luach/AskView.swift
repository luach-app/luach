import SwiftUI
import UIKit

struct AskView: View {
    @Environment(AppSession.self) private var session
    @State private var conversation = Conversation()
    @State private var text = ""
    @State private var recorder = Recorder()
    @State private var transcribing = false
    @State private var micError: String?
    /// Whether this luach has a transcriber; without one the mic is not offered.
    @State private var micAvailable = false
    @State private var showingThreads = false
    /// Counts what was sent, for the tap felt as a message goes.
    @State private var sent = 0
    @FocusState private var typing: Bool

    /// Tests hand in a conversation of their own and a recorder with no microphone behind it.
    init(conversation: Conversation = Conversation(), recorder: Recorder = Recorder()) {
        _conversation = State(initialValue: conversation)
        _recorder = State(initialValue: recorder)
    }

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
                        if conversation.items.isEmpty {
                            AskGreeting(name: session.member?.name ?? "") { suggestion, sendNow in
                                text = suggestion
                                if sendNow { send() } else { typing = true }
                            }
                        }
                        ForEach(conversation.items) { item in
                            ItemView(item: item, conversation: conversation)
                        }
                        if let activity = conversation.activity {
                            HStack(spacing: 8) {
                                ProgressView()
                                Text(activity).foregroundStyle(.secondary)
                            }
                            .font(.subheadline)
                        } else if conversation.streaming, case .user = conversation.items.last?.kind {
                            ProgressView()
                        }
                        Color.clear.frame(height: 1).id("end")
                    }
                    .padding()
                }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: conversation.items.count) { proxy.scrollTo("end", anchor: .bottom) }
                .onChange(of: conversation.activity) { proxy.scrollTo("end", anchor: .bottom) }
            }
            .safeAreaInset(edge: .bottom) { composer }
            .navigationTitle("luach")
            .navigationBarTitleDisplayMode(.inline)
            .accountButton()
            .sensoryFeedback(.impact(weight: .light), trigger: sent)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Conversations", systemImage: "list.bullet") { showingThreads = true }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("New", systemImage: "square.and.pencil") {
                        conversation.reset()
                    }
                    .disabled(conversation.items.isEmpty)
                }
            }
            .sheet(isPresented: $showingThreads) {
                ThreadsView(current: conversation.threadID) { id in
                    showingThreads = false
                    Task { await conversation.open(id, api: session.api) }
                } onDeleted: { id in
                    if id == conversation.threadID { conversation.reset() }
                }
            }
            .task {
                struct Status: Decodable { let available: Bool }
                micAvailable = ((try? await session.api.get("/api/transcribe/status")) as Status?)?.available ?? false
                await conversation.restore(api: session.api)
                #if DEBUG
                // `-showThreads YES` opens the conversation list (simulator checks).
                // Only ever opens: by now the person may have opened the list themselves.
                if UserDefaults.standard.bool(forKey: "showThreads") { showingThreads = true }
                // `-ask "what's on this week"` sends one turn at launch (simulator checks).
                if let ask = UserDefaults.standard.string(forKey: "ask"), conversation.items.isEmpty {
                    text = ask
                    send()
                }
                #endif
            }
        }
    }

    private var composer: some View {
        VStack(spacing: 6) {
            if let micError {
                Text(micError).font(.footnote).foregroundStyle(.red)
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField(recorder.recording ? "Listening…" : "Dentist next Tuesday at three", text: $text, axis: .vertical)
                    .onSubmit(send)
                    .lineLimit(1...5)
                    .focused($typing)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(.background.secondary, in: .rect(cornerRadius: 20))
                    .disabled(recorder.recording || transcribing)

                if conversation.streaming {
                    roundButton("stop.fill", label: "Stop") { conversation.stop() }
                } else if micAvailable && text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    micButton
                } else {
                    roundButton("arrow.up", label: "Send", action: send)
                        .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private var micButton: some View {
        Group {
            if transcribing {
                ProgressView().frame(width: 40, height: 40)
            } else {
                roundButton(recorder.recording ? "stop.circle.fill" : "mic.fill",
                            label: recorder.recording ? "Stop listening" : "Speak",
                            tint: recorder.recording ? .red : .accentColor,
                            ink: recorder.recording ? .white : .accentOn,
                            action: toggleMic)
            }
        }
    }

    private func roundButton(
        _ symbol: String, label: LocalizedStringKey, tint: Color = .accentColor, ink: Color = .accentOn,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .bold))
                .frame(width: 40, height: 40)
                .foregroundStyle(ink)
                .background(tint, in: .circle)
        }
        .accessibilityLabel(Text(label))
    }

    private func send() {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return }
        text = ""
        sent += 1
        conversation.send(t, api: session.api) {
            Task { await session.pending.refresh() }
        }
    }

    /// Like the web composer: what was heard lands in the field to read before sending.
    private func toggleMic() {
        micError = nil
        if recorder.recording {
            guard let audio = recorder.stop() else { return }
            transcribing = true
            Task {
                defer { transcribing = false }
                do {
                    let heard = try await session.api.transcribe(audio: audio, contentType: Recorder.contentType)
                    let before = text.trimmingCharacters(in: .whitespaces)
                    text = before.isEmpty ? heard : "\(before) \(heard)"
                } catch {
                    micError = error.localizedDescription
                }
            }
        } else {
            typing = false
            Task {
                do { try await recorder.start() } catch { micError = error.localizedDescription }
            }
        }
    }
}

/// The first thing Ask shows: who it is talking to, and a few things to say with one tap.
/// A question is asked at once; something to add goes in the field for the person to finish.
private struct AskGreeting: View {
    let name: String
    let pick: (String, Bool) -> Void

    /// What each chip says, what it puts in the field (in the person's language, which luach
    /// answers in too), whether it is sent at once, and its symbol.
    private static var suggestions: [(LocalizedStringKey, String, Bool, String)] {
        func start(_ s: String) -> String { s.replacingOccurrences(of: "…", with: " ") }
        return [
            ("What's on this week?", String(localized: "What's on this week?"), true, "calendar"),
            ("Is Saturday free?", String(localized: "Is Saturday free?"), true, "checkmark.circle"),
            ("What does tomorrow look like?", String(localized: "What does tomorrow look like?"), true, "sun.horizon"),
            ("Add…", start(String(localized: "Add…")), false, "plus"),
            ("Move…", start(String(localized: "Move…")), false, "arrow.uturn.right"),
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Hi \(name).").font(.title.bold())
                Text("Say it the way you would to a person: \"dentist next Tuesday at three\" is enough.")
                    .foregroundStyle(.secondary)
            }
            FlowLayout(spacing: 8) {
                ForEach(Array(Self.suggestions.enumerated()), id: \.offset) { _, s in
                    Button { pick(s.1, s.2) } label: {
                        Label(s.0, systemImage: s.3)
                            .font(.subheadline.weight(.medium))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .background(.background.secondary, in: .capsule)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.top, 24)
    }
}

/// Lays its children out in rows, wrapping when a row is full.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        rows(proposal.width ?? .infinity, subviews).last.map { CGSize(width: proposal.width ?? $0.width, height: $0.maxY) } ?? .zero
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX {
                x = bounds.minX; y += rowHeight + spacing; rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }

    private func rows(_ width: CGFloat, _ subviews: Subviews) -> [(width: CGFloat, maxY: CGFloat)] {
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, out: [(CGFloat, CGFloat)] = []
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { x = 0; y += rowHeight + spacing; rowHeight = 0 }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            out.append((x, y + rowHeight))
        }
        return out.map { (width: $0.0, maxY: $0.1) }
    }
}

private struct ItemView: View {
    let item: Conversation.Item
    let conversation: Conversation

    var body: some View {
        switch item.kind {
        case .user(let text):
            HStack {
                Spacer(minLength: 48)
                Text(text)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .foregroundStyle(Color.accentOn)
                    .background(Color.accentColor, in: .rect(cornerRadius: 18))
            }
        case .trace(let steps):
            Trace(steps: steps)
        case .assistant(let text):
            Text(Self.markdown(text))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        case .footer(let model, let text, let stopped):
            AnswerFooter(model: model, text: text, stopped: stopped)
        case .widget(let kind, let data):
            WidgetCard(kind: kind, data: data)
        case .held(let id, let summary, let reason, let labels, let restored):
            HeldCard(
                id: id, summary: summary, reason: reason, labels: labels, restored: restored,
                conversation: conversation)
        case .error(let message):
            Label(message, systemImage: "exclamationmark.triangle")
                .foregroundStyle(.red)
        }
    }

    static func markdown(_ s: String) -> AttributedString {
        (try? AttributedString(markdown: s, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
            ?? AttributedString(s)
    }
}

/// The cards the stream sends after a read tool; the reply text does not repeat them.
private struct WidgetCard: View {
    let kind: String
    let data: WidgetData

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            switch kind {
            case "availability":
                Label(data.free == true ? "Free" : "Something's on",
                      systemImage: data.free == true ? "checkmark.circle" : "calendar.badge.exclamationmark")
                    .font(.headline)
                    .foregroundStyle(data.free == true ? .green : .orange)
                ForEach(data.clashes ?? []) { CompactRow(event: $0) }
            case "event":
                if let event = data.event { CompactRow(event: event) }
            default:
                if let title = data.title {
                    Text(title).font(.headline)
                }
                let events = data.events ?? []
                if events.isEmpty {
                    Text("Nothing on the calendar.").foregroundStyle(.secondary)
                }
                ForEach(events) { CompactRow(event: $0) }
                if data.truncated == true {
                    Text("And more.").font(.footnote).foregroundStyle(.secondary)
                }
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background.secondary, in: .rect(cornerRadius: 16))
    }
}

private struct CompactRow: View {
    let event: CompactEvent

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(event.title).font(.subheadline.weight(.semibold))
            Text(event.when).font(.footnote).foregroundStyle(.secondary)
            if let location = event.location, !location.isEmpty {
                Text(location).font(.footnote).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }
}

/// A write the gate held: approving runs the exact call luach proposed.
private struct HeldCard: View {
    @Environment(AppSession.self) private var session
    let id: String
    let summary: String
    let reason: String
    let labels: [String]
    let restored: Bool
    let conversation: Conversation
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Waiting for a yes", systemImage: "hand.raised.fill")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tint)
            Text(summary).font(.body.weight(.medium))
            if !labels.isEmpty {
                // The same words as under Approvals: "sends an invitation outside the household".
                Text(labels.map { PendingRow.describe($0) }.joined(separator: " · "))
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            if !reason.isEmpty {
                Text(reason).font(.footnote).foregroundStyle(.secondary)
            }
            if let error {
                Text(error).font(.footnote).foregroundStyle(.red)
            }
            switch conversation.decisions[id] {
            case .approved:
                Label("Approved", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            case .denied:
                Label("Denied", systemImage: "xmark.circle.fill").foregroundStyle(.secondary)
            case .failed:
                Label("It did not go through", systemImage: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            case nil where restored && !session.pending.items.contains { $0.id == id }:
                // A card from an earlier visit whose hold is no longer waiting.
                Label("Decided", systemImage: "checkmark.circle").foregroundStyle(.secondary)
            case nil:
                HStack {
                    Button("Approve") { decide(true) }.prominentAccent()
                    Button("Deny", role: .destructive) { decide(false) }.buttonStyle(.bordered)
                    if busy { ProgressView() }
                }
                .disabled(busy)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background.secondary, in: .rect(cornerRadius: 16))
        .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.tint.opacity(0.4)))
        .sensoryFeedback(.success, trigger: conversation.decisions[id])
        .sensoryFeedback(.error, trigger: error)
    }

    private func decide(_ approve: Bool) {
        busy = true
        Task {
            defer { busy = false }
            do {
                let row = try await session.pending.decide(id, approve: approve)
                conversation.decisions[id] = Conversation.Decision(status: row.status)
                // Approved, but refused when it ran: say why rather than "Approved".
                if row.failed, let why = row.failure, !why.isEmpty { self.error = why }
            } catch let e as APIError where e.status == 409 {
                // Someone decided it first (in the web app, or through the service key).
                self.error = String(localized: "Already decided elsewhere.")
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

/// What luach did on the way to its answer, folded to one line once it is done
/// (web WorkTrace): a person who wonders why can open it.
private struct Trace: View {
    let steps: [Conversation.Step]
    @State private var open = false

    var body: some View {
        let running = steps.contains { !$0.done }
        DisclosureGroup(isExpanded: Binding(get: { open || running }, set: { open = $0 })) {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(steps.enumerated()), id: \.offset) { _, step in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: step.failed != nil ? "exclamationmark.circle" : step.done ? "checkmark" : "circle.dotted")
                            .foregroundStyle(step.failed != nil ? .orange : .secondary)
                            .frame(width: 14)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(step.label)
                            if let failed = step.failed {
                                Text(failed).foregroundStyle(.orange)
                            }
                        }
                    }
                }
            }
            .padding(.top, 6)
        } label: {
            Text(steps.count == 1 ? "1 step" : "\(steps.count) steps")
        }
        .font(.footnote)
        .foregroundStyle(.secondary)
    }
}

/// Under a finished answer: which model gave it (a person who picked one should
/// see when the router let another answer), and a way to take the words elsewhere.
private struct AnswerFooter: View {
    let model: String?
    let text: String
    let stopped: Bool
    @State private var copied = false

    var body: some View {
        HStack(spacing: 10) {
            if stopped { Text("stopped") }
            if let model, !model.isEmpty {
                Text(model).font(.caption2.monospaced()).lineLimit(1).truncationMode(.middle)
            }
            if !text.isEmpty {
                Button {
                    UIPasteboard.general.string = text
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(1.6))
                        copied = false
                    }
                } label: {
                    Label(copied ? "copied" : "copy", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(.borderless)
            }
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
