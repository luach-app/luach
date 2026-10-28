import SwiftUI

/// One event, to read (web `EventSheet`'s view): when, whose, which calendar, where,
/// the notes, who is invited, how it repeats, and Google Calendar. Edit and Delete
/// unless luach may not change it, and then it says why. The caller wraps it in a
/// `NavigationStack`; Done and Edit sit in that bar.
struct AgendaEventDetail: View {
    let event: AgendaEvent
    let clock: AgendaClock
    var onEdit: () -> Void
    var onChanged: () -> Void
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @State private var confirm = false
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        let data = AgendaData.shared
        let leaders = data.leaders(of: event)
        let cal = data.calendar(event.calendarId)
        List {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(event.displayTitle).font(.title2.bold())
                            .accessibilityIdentifier("event.title")
                        if event.readOnly {
                            Text(readOnlyLine).font(.subheadline).foregroundStyle(.secondary)
                        }
                        Text(clock.range(event)).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 2)
                    if !leaders.isEmpty {
                        HStack(spacing: 6) {
                            ForEach(leaders) { p in
                                Circle().fill(AgendaPalette.color(p.hex) ?? .accentColor).frame(width: 10, height: 10)
                            }
                            Text("For \(AgendaWords.names(leaders.map(\.name)))").font(.subheadline.weight(.medium))
                        }
                    }
                    if let cal, data.enabledCalendars.count > 1 {
                        HStack(spacing: 6) {
                            Circle().fill(AgendaPalette.color(cal.color) ?? .accentColor).frame(width: 10, height: 10)
                            Text(cal.name).font(.subheadline).foregroundStyle(.secondary)
                        }
                    }
                    if !event.location.isEmpty {
                        if let maps = mapsURL {
                            Link(destination: maps) { Label(event.location, systemImage: "mappin.and.ellipse") }
                        } else {
                            Label(event.location, systemImage: "mappin.and.ellipse")
                        }
                    }
                    if !event.attendees.isEmpty {
                        Label(event.attendees.joined(separator: ", "), systemImage: "person.2")
                            .font(.subheadline)
                    }
                    if !event.recurrence.isEmpty {
                        Label(AgendaRepeat.describe(event.recurrence, locale: clock.locale), systemImage: "repeat")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                }
                if !event.description.isEmpty {
                    Section("Notes") {
                        Text(AgendaNotes.attributed(event.description))
                            .font(.subheadline)
                            .textSelection(.enabled)
                    }
                }
                if !event.inviteError.isEmpty {
                    Section {
                        Label(event.inviteError, systemImage: "info.circle").font(.subheadline)
                    }
                }
                if let link = URL(string: event.htmlLink), !event.htmlLink.isEmpty {
                    Section {
                        Link(destination: link) {
                            Label("Open in Google Calendar", systemImage: "arrow.up.right.square")
                        }
                    }
                }
                if let error {
                    Section { Text(error).foregroundStyle(.red) }
                }
                if !event.readOnly {
                    Section {
                        Button(role: .destructive) { confirm = true } label: {
                            HStack {
                                Text("Delete")
                                if busy { Spacer(); ProgressView() }
                            }
                        }
                        .disabled(busy)
                    }
                }
            }
            .navigationTitle("Event")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
                if !event.readOnly {
                    ToolbarItem(placement: .primaryAction) {
                        Button("Edit") { onEdit() }.disabled(busy)
                    }
                }
            }
            .confirmationDialog("Delete this event?", isPresented: $confirm, titleVisibility: .visible) {
                // One occurrence of a repeating event: that one, or every one.
                if event.isOccurrence {
                    Button("This event", role: .destructive) { Task { await remove(scope: .this) } }
                    Button("All events", role: .destructive) { Task { await remove(scope: .series) } }
                } else {
                    Button("Delete for real", role: .destructive) { Task { await remove() } }
                }
                Button("Keep it", role: .cancel) {}
            } message: {
                Text(AgendaWords.deleting(event))
            }
    }

    private var readOnlyLine: String {
        event.organizer.isEmpty
            ? String(localized: "From a calendar luach only reads. It holds the time; what it is stays where it lives.")
            : String(localized: "An invitation from \(event.organizer). Only they can change it — reply to it in Google Calendar.")
    }

    private var mapsURL: URL? {
        var c = URLComponents(string: "https://maps.apple.com/")
        c?.queryItems = [URLQueryItem(name: "q", value: event.location)]
        return c?.url
    }

    private func remove(scope: AgendaScope? = nil) async {
        busy = true
        defer { busy = false }
        do {
            try await session.api.agendaDelete(event.id, calendar: event.calendarId, scope: scope)
            await session.pending.refresh()
            onChanged()
            dismiss()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
