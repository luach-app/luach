import SwiftUI

/// A task as a tick box in its person's colour. The box ticks; with `onOpen` the
/// words open the task (on the board, ticking should not be the only thing a tap does).
struct TaskRow: View {
    let task: TaskItem
    let hex: String
    let onTick: () -> Void
    var onOpen: (() -> Void)?

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onTick) { box }
                .buttonStyle(.borderless)
                .accessibilityLabel(task.title)
                .accessibilityValue(task.done ? Text("Done") : Text("Not done"))
                .accessibilityAddTraits(.isToggle)
            if let onOpen {
                Button(action: onOpen) { words }
                    .buttonStyle(.borderless)
                    .tint(.primary)
                    .accessibilityLabel(Text("Open \(task.title)"))
                    // The label replaces the words under it: say what they say beyond the title.
                    .accessibilityValue(details)
            } else {
                words
                    .contentShape(Rectangle())
                    .onTapGesture(perform: onTick)
            }
        }
        .sensoryFeedback(.selection, trigger: task.done)
    }

    private var box: some View {
        let color = personColor(hex)
        return RoundedRectangle(cornerRadius: 6)
            .strokeBorder(task.done ? .clear : Color.secondary.opacity(0.6), lineWidth: 2)
            .background(RoundedRectangle(cornerRadius: 6).fill(task.done ? color : .clear))
            .frame(width: 26, height: 26)
            .overlay {
                if task.done {
                    Image(systemName: "checkmark")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color(luachHex: hex) == nil ? Color.accentOn : Color.ink(on: hex))
                }
            }
            .padding(.vertical, 4)
            .contentShape(Rectangle())
    }

    private var words: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(task.title)
                .strikethrough(task.done)
                .foregroundStyle(task.done ? .secondary : .primary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .multilineTextAlignment(.leading)
            if let line = subline {
                line
                    .font(.footnote)
                    .foregroundStyle(task.overdue && !task.chore ? .red : .secondary)
            }
            if let notes = task.notes, !notes.isEmpty {
                Text(notes)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
    }

    /// The day or the days, and the notes, for VoiceOver.
    var details: String {
        var parts: [String] = []
        if task.chore {
            parts.append(Weekday.describe(task.days))
        } else if task.overdue {
            parts.append(String(localized: "late — was due \(ISODay.short(task.due))"))
        } else if !task.due.isEmpty {
            parts.append(String(localized: "due \(ISODay.short(task.due))"))
        }
        if let notes = task.notes, !notes.isEmpty { parts.append(notes) }
        return parts.joined(separator: ", ")
    }

    private var subline: Text? {
        if task.chore {
            return Text("\(Image(systemName: "repeat")) \(Weekday.describe(task.days))")
        }
        if task.overdue { return Text("late — was due \(ISODay.short(task.due))") }
        if !task.due.isEmpty { return Text("due \(ISODay.short(task.due))") }
        return nil
    }
}

/// A person's badge and name, for section headers.
struct PersonHeading: View {
    let name: String
    let hex: String

    var body: some View {
        HStack(spacing: 10) {
            PersonAvatar(name: name, hex: hex, size: 30)
            Text(name)
        }
    }
}
