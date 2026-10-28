import SwiftUI
import Testing
import UIKit
@testable import Luach

/// A You screen shown for real in a window of the test host, answered by a StubServer: its
/// `.task` loads, its body lays out, and the test moves it between states through its model
/// or by pressing what is on screen (buttons, a row's swipe actions, a dialog's choices).
/// It reaches what dev cannot show or must not do — boards, passkeys, invitations, errors,
/// removing an address — without touching dev.
@MainActor
final class YouHost {
    let window: UIWindow

    /// SwiftUI builds its accessibility tree only for an assistive client; this turns one on
    /// for the test host (as Agenda's host does), so pressing works whatever ran before.
    private static let automation: Void = {
        guard let lib = dlopen("/usr/lib/libAccessibility.dylib", RTLD_NOW),
              let set = dlsym(lib, "_AXSSetAutomationEnabled") else { return }
        typealias Set = @convention(c) (Int32) -> Void
        unsafeBitCast(set, to: Set.self)(1)
    }()

    init(_ view: some View, session: AppSession) {
        _ = Self.automation
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        window = scene.map { UIWindow(windowScene: $0) } ?? UIWindow()
        // Tall, so a list lays out every row at once.
        window.frame = CGRect(x: 0, y: 0, width: 402, height: 2400)
        window.rootViewController = UIHostingController(rootView: NavigationStack { view }.environment(session))
        window.isHidden = false
    }

    /// Takes the window away; a dialog still up goes with it.
    func close() {
        window.rootViewController?.dismiss(animated: false)
        window.isHidden = true
        window.rootViewController = nil
    }

    /// Lets the screen load and lay out again.
    func settle(_ time: Duration = .milliseconds(400)) async {
        try? await Task.sleep(for: time)
        window.layoutIfNeeded()
        try? await Task.sleep(for: .milliseconds(50))
    }

    /// Every accessibility element on screen, and in what is presented over it.
    var elements: [NSObject] {
        var found: [NSObject] = []
        func walk(_ node: NSObject, depth: Int) {
            guard depth < 60 else { return }
            if node.isAccessibilityElement { found.append(node) }
            let children: [Any]
            if let list = node.accessibilityElements, !list.isEmpty {
                children = list
            } else if let view = node as? UIView {
                children = view.subviews
            } else {
                let n = node.accessibilityElementCount()
                children = n == NSNotFound || n <= 0 ? [] : (0..<n).compactMap { node.accessibilityElement(at: $0) }
            }
            for child in children { if let child = child as? NSObject { walk(child, depth: depth + 1) } }
        }
        var controller = window.rootViewController
        while let c = controller {
            walk(c.view, depth: 0)
            controller = c.presentedViewController
        }
        return found
    }

    var labels: [String] { elements.compactMap(\.accessibilityLabel) }

    func shows(_ text: String) -> Bool {
        labels.contains { $0 == text || $0.contains(text) }
    }

    /// Waits until something labelled `label` is on screen (a dialog animates in).
    func waitFor(_ label: String, seconds: Double = 5) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if shows(label) { return true }
            await settle(.milliseconds(150))
        }
        return shows(label)
    }

    /// Presses the element labelled exactly `label` (the last one: a dialog's, over the screen).
    @discardableResult
    func press(_ label: String) async -> Bool {
        _ = await waitFor(label, seconds: 3)
        guard let target = elements.last(where: { $0.accessibilityLabel == label }) else { return false }
        let pressed = target.accessibilityActivate()
        await settle()
        return pressed
    }

    /// The dialog up over the screen, if any (SwiftUI's confirmationDialog is an alert controller).
    var dialog: UIAlertController? {
        var controller = window.rootViewController
        while let c = controller {
            if let alert = c as? UIAlertController { return alert }
            controller = c.presentedViewController
        }
        return nil
    }

    /// Chooses `title` in the dialog up. An action sheet draws no Cancel button on a phone and
    /// its buttons do not activate in-process, so the action's own handler is run, as a tap does.
    @discardableResult
    func choose(_ title: String) async -> Bool {
        let end = Date().addingTimeInterval(3)
        while dialog == nil && Date() < end { await settle(.milliseconds(150)) }
        guard let alert = dialog, let action = alert.actions.first(where: { $0.title == title }),
              let block = action.value(forKey: "handler") else { return false }
        typealias Handler = @convention(block) (UIAlertAction) -> Void
        let handler = unsafeBitCast(block as AnyObject, to: Handler.self)
        alert.dismiss(animated: false)
        handler(action)
        await settle()
        return true
    }

    /// Runs the swipe action named `action` of the row whose label contains `row`.
    @discardableResult
    func swipe(_ action: String, on row: String) async -> Bool {
        let rows = elements.filter { ($0.accessibilityLabel ?? "").contains(row) }
        for element in rows {
            if let custom = element.accessibilityCustomActions?.first(where: { $0.name == action }) {
                let done: Bool
                if let handler = custom.actionHandler {
                    done = handler(custom)
                } else if let target = custom.target as? NSObject {
                    done = target.perform(custom.selector, with: custom) != nil
                } else {
                    done = false
                }
                await settle()
                return done
            }
        }
        return false
    }
}
