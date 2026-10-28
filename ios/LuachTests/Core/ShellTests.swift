import Foundation
import SwiftUI
import Testing
@testable import Luach

@MainActor
struct ShellTests {
    @Test func stoppingANoteThatNeverStartedSendsNothing() {
        let recorder = Recorder()
        #expect(!recorder.recording)
        #expect(recorder.stop() == nil)
        #expect(Recorder.contentType == "audio/mp4")
    }

    @Test func aRefusedMicrophoneSaysWhereToAllowIt() {
        #expect(Recorder.Denied().errorDescription?.contains("Settings") == true)
    }

    @Test func everyScreenHasANameAndAnIcon() {
        #expect(Screen.allCases.count == 17)
        for screen in Screen.allCases {
            #expect(UIImage(systemName: screen.symbol) != nil, "\(screen) has no icon")
            #expect(Screen(rawValue: screen.id) == screen)
        }
    }
}
