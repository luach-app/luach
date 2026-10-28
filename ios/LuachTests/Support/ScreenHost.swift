import SwiftUI
import Testing
import UIKit
@testable import Luach

/// A screen of the app in a window of the test host, answered by a StubServer, read and pressed
/// through accessibility: for the states dev cannot produce (a refusal, a 409, an empty list).
@MainActor
final class ScreenHost {
    let window: UIWindow

    /// SwiftUI builds its accessibility tree only for an assistive client; without this a hosted
    /// test saw the screen or nothing depending on whether a UI test had just run.
    private static let automation: Void = {
        guard let lib = dlopen("/usr/lib/libAccessibility.dylib", RTLD_NOW),
              let set = dlsym(lib, "_AXSSetAutomationEnabled") else { return }
        typealias Set = @convention(c) (Int32) -> Void
        unsafeBitCast(set, to: Set.self)(1)
    }()

    /// `stack`: wrap the view in a NavigationStack (screens pushed from the settings sheet).
    init(_ view: some View, session: AppSession, stack: Bool = true) {
        _ = Self.automation
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        window = scene.map { UIWindow(windowScene: $0) } ?? UIWindow()
        window.frame = CGRect(x: 0, y: 0, width: 402, height: 3000)
        let root = stack ? AnyView(NavigationStack { view }.environment(session)) : AnyView(view.environment(session))
        window.rootViewController = UIHostingController(rootView: root)
        // Key, so a text field can take focus and what is typed reaches the view's state.
        window.makeKeyAndVisible()
    }

    func close() {
        window.rootViewController?.dismiss(animated: false)
        window.isHidden = true
        window.rootViewController = nil
    }

    func settle(_ time: Duration = .milliseconds(300)) async {
        try? await Task.sleep(for: time)
        window.layoutIfNeeded()
        try? await Task.sleep(for: .milliseconds(50))
    }

    /// Waits until the screen shows `text`, and says whether it did.
    func waitFor(_ text: String, seconds: Double = 5) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if shows(text) { return true }
            await settle(.milliseconds(150))
        }
        return shows(text)
    }

    /// Every accessibility element on screen, and in whatever is presented over it.
    var elements: [NSObject] {
        var found: [NSObject] = []
        func walk(_ node: NSObject, depth: Int) {
            guard depth < 60 else { return }
            // A row the list removed can linger as a hidden cell kept for reuse: not on screen.
            if let view = node as? UIView, view.isHidden || view.alpha == 0 { return }
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

    /// Waits until `text` is no longer on screen, and says whether it went.
    func waitGone(_ text: String, seconds: Double = 5) async -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while Date() < end {
            if !shows(text) { return true }
            await settle(.milliseconds(150))
        }
        return !shows(text)
    }

    var labels: [String] { elements.compactMap(\.accessibilityLabel) }

    func shows(_ text: String) -> Bool {
        (labels + elements.compactMap(\.accessibilityValue)).contains { $0 == text || $0.contains(text) }
    }

    /// Presses the element labelled exactly `label` (the last one, the topmost presented).
    @discardableResult
    func press(_ label: String) async -> Bool {
        guard let target = elements.last(where: { $0.accessibilityLabel == label }) else { return false }
        let pressed = target.accessibilityActivate()
        await settle()
        return pressed
    }

    /// The text fields on screen (secure ones too), in the order they are laid out.
    var textFields: [UITextField] {
        var out: [UITextField] = []
        func walk(_ view: UIView) {
            if let field = view as? UITextField { out.append(field) }
            view.subviews.forEach(walk)
        }
        walk(window)
        return out
    }

    /// The text field whose placeholder is `placeholder`.
    func field(_ placeholder: String) -> UITextField? {
        textFields.first { $0.placeholder == placeholder }
    }

    /// Types into the field whose placeholder is `placeholder`, as the keyboard would, after
    /// clearing what was there.
    @discardableResult
    func type(_ text: String, into placeholder: String) async -> Bool {
        guard let field = field(placeholder) else { return false }
        field.becomeFirstResponder()
        if let range = field.textRange(from: field.beginningOfDocument, to: field.endOfDocument) {
            field.replace(range, withText: "")
        }
        field.insertText(text)
        await settle()
        return true
    }

    /// Runs a row's swipe action (SwiftUI offers them as custom actions) on the element whose
    /// label contains `row`.
    @discardableResult
    func action(_ name: String, on row: String) async -> Bool {
        for element in elements where element.accessibilityLabel?.contains(row) == true {
            if let action = element.accessibilityCustomActions?.first(where: { $0.name == name }) {
                let done: Bool
                if let handler = action.actionHandler {
                    done = handler(action)
                } else if let target = action.target as? NSObject {
                    done = target.perform(action.selector, with: action) != nil
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
