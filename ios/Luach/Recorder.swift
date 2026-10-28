import AVFoundation
import Observation

/// What a voice note is recorded with: AVAudioRecorder on a phone, a stand-in in the tests
/// (the simulator has no microphone to speak into).
protocol AudioRecording: AnyObject {
    var currentTime: TimeInterval { get }
    func record() -> Bool
    func stop()
}

extension AVAudioRecorder: AudioRecording {}

/// Records a voice note as AAC in an MP4 container, which `/api/transcribe`
/// takes as `audio/mp4`.
@Observable
final class Recorder {
    static let contentType = "audio/mp4"

    private(set) var recording = false
    private var recorder: AudioRecording?
    let file: URL
    private let permission: () async -> Bool
    private let make: (URL, [String: Any]) throws -> AudioRecording

    struct Denied: LocalizedError {
        var errorDescription: String? {
            String(localized: "luach cannot hear you: allow the microphone in Settings.")
        }
    }

    init(
        file: URL = FileManager.default.temporaryDirectory.appending(path: "luach-voice.m4a"),
        permission: @escaping () async -> Bool = { await AVAudioApplication.requestRecordPermission() },
        make: @escaping (URL, [String: Any]) throws -> AudioRecording = Recorder.system
    ) {
        self.file = file
        self.permission = permission
        self.make = make
    }

    /// The phone's own recorder: AVAudioRecorder, writing AAC to `url`.
    nonisolated static func system(_ url: URL, _ settings: [String: Any]) throws -> AudioRecording {
        try AVAudioRecorder(url: url, settings: settings)
    }

    func start() async throws {
        guard await permission() else { throw Denied() }
        let audio = AVAudioSession.sharedInstance()
        try audio.setCategory(.record, mode: .spokenAudio)
        try audio.setActive(true)
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 16_000,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.medium.rawValue,
        ]
        let recorder = try make(file, settings)
        guard recorder.record() else { throw CocoaError(.fileWriteUnknown) }
        self.recorder = recorder
        recording = true
    }

    /// Stops and hands back the recording, or nil when there is nothing worth sending.
    func stop() -> Data? {
        guard let recorder else { return nil }
        let seconds = recorder.currentTime
        recorder.stop()
        self.recorder = nil
        recording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        guard seconds > 0.3 else { return nil }
        return try? Data(contentsOf: file)
    }
}
