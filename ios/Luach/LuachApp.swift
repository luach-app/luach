import BackgroundTasks
import SwiftUI

@main
struct LuachApp: App {
    @State private var session = AppSession()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(session)
                .task { await session.restore() }
        }
        // Leaving the app asks iOS to wake it now and then, for the Approvals count on the
        // icon and the reminders; iOS decides when, if at all.
        .onChange(of: scenePhase) { _, phase in
            if phase == .background, session.member != nil { BackgroundRefresh.schedule() }
        }
        .backgroundTask(.appRefresh(BackgroundRefresh.identifier)) {
            await BackgroundRefresh.run(session)
        }
    }
}

/// The app's one background task: a short refresh of what is waiting and of the reminders.
enum BackgroundRefresh {
    /// Also in Info.plist (`BGTaskSchedulerPermittedIdentifiers`).
    static let identifier = "luach.refresh"

    static func schedule(after seconds: TimeInterval = 30 * 60) {
        let request = BGAppRefreshTaskRequest(identifier: identifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: seconds)
        try? BGTaskScheduler.shared.submit(request)
    }

    @MainActor
    static func run(_ session: AppSession) async {
        await session.backgroundRefresh()
        if session.member != nil { schedule() }
    }
}

struct RootView: View {
    @Environment(AppSession.self) private var session

    var body: some View {
        switch session.phase {
        case .starting:
            if session.hasServer {
                ProgressView {
                    Text("Reaching \(ServerAddress.display(session.server))…")
                }
            } else {
                ProgressView()
            }
        case .signedOut:
            LoginView()
        case .unreachable(let message):
            // Not a dead end: a phone pointed at the wrong address, or one that should be signed
            // out of a luach that is gone, gets out from here.
            ContentUnavailableView {
                Label("luach is out of reach", systemImage: "wifi.exclamationmark")
            } description: {
                Text(message)
            } actions: {
                Button("Try again") { Task { await session.restore() } }
                    .prominentAccent()
                Button("Use another address") { Task { await session.useAnotherAddress() } }
                    .buttonStyle(.bordered)
                Button("Sign out", role: .destructive) { Task { await session.signOutHere() } }
            }
        case .signedIn:
            MainTabs()
        }
    }
}

struct MainTabs: View {
    @Environment(AppSession.self) private var session
    @Environment(\.scenePhase) private var scenePhase
    // `-tab ask` at launch opens on that tab (simulator checks; see AppSession).
    @State private var tab = UserDefaults.standard.string(forKey: "tab") ?? "agenda"

    var body: some View {
        #if DEBUG
        // `-screen booking` opens one screen on its own (simulator checks).
        if let name = UserDefaults.standard.string(forKey: "screen"), let screen = Screen(rawValue: name) {
            NavigationStack { screen.view.navigationTitle(screen.title) }
        } else {
            tabs
        }
        #else
        tabs
        #endif
    }

    // The web app's order: Agenda, Board, then what needs a yes; Ask last.
    // Settings, members and the rest are behind the account button on every tab.
    private var tabs: some View {
        TabView(selection: $tab) {
            Tab("Agenda", systemImage: "calendar", value: "agenda") {
                AgendaView()
            }
            Tab("Board", systemImage: "square.grid.2x2", value: "board") {
                BoardView()
            }
            Tab("Approvals", systemImage: "hand.raised", value: "approvals") {
                PendingView()
            }
            .badge(session.pending.items.count)
            Tab("Ask", systemImage: "sparkles", value: "ask") {
                AskView()
            }
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            await session.pending.refresh()
            await session.refreshReminders()
        }
        // After any change to the calendar made here: the reminders follow, once the changes
        // settle (a new change restarts the wait).
        .task(id: AgendaData.shared.version) {
            try? await Task.sleep(for: .seconds(2))
            guard !Task.isCancelled, scenePhase == .active else { return }
            await session.refreshReminders()
        }
        .onChange(of: session.pending.items.count) { _, count in
            Task { await session.reminders.badge(count) }
        }
    }
}
