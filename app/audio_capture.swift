// ScreenCaptureKit으로 특정 앱(또는 시스템 전체)의 소리를 잡아 stdout으로 흘려보낸다.
//
// BlackHole 같은 가상 오디오 장치를 깔고 다중 출력 기기를 만드는 과정 없이,
// 사용자의 출력 장치를 전혀 건드리지 않고 소리를 가져오기 위한 헬퍼다.
//
//   ./audio_capture --list                 실행 중인 앱 목록 (bundleID\t이름)
//   ./audio_capture --capture <bundleID>   그 앱의 소리만 캡처
//   ./audio_capture --capture SYSTEM       시스템 전체 소리 캡처
//
// 출력: 16kHz · 모노 · 16bit LE raw PCM (헤더 없음)
// 빌드: swiftc -O audio_capture.swift -o audio_capture

import AVFoundation
import AppKit
import Foundation
import ScreenCaptureKit

let SAMPLE_RATE = 16000
let CHANNELS = 1

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write(("ERROR: " + msg + "\n").data(using: .utf8)!)
    exit(1)
}

// ── 앱 목록 ───────────────────────────────────────────────────────────────────
// SCShareableContent는 화면 기록 권한을 요구하므로, 목록만 뽑을 때는 권한이
// 필요 없는 NSWorkspace를 쓴다. 권한은 실제 캡처 시점에만 필요하다.
func listApps() {
    var seen = Set<String>()
    for app in NSWorkspace.shared.runningApplications
    where app.activationPolicy == .regular {
        guard let bid = app.bundleIdentifier, let name = app.localizedName else { continue }
        if seen.insert(bid).inserted {
            print("\(bid)\t\(name)")
        }
    }
}

// ── 캡처 ─────────────────────────────────────────────────────────────────────
final class AudioTap: NSObject, SCStreamOutput, SCStreamDelegate {
    private let out = FileHandle.standardOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .audio, CMSampleBufferDataIsReady(sb) else { return }
        guard let fmtDesc = CMSampleBufferGetFormatDescription(sb),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fmtDesc)?.pointee
        else { return }

        var blockBuffer: CMBlockBuffer?
        var abl = AudioBufferList()
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sb,
            bufferListSizeNeededOut: nil,
            bufferListOut: &abl,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr, let data = abl.mBuffers.mData else { return }

        let frames = Int(abl.mBuffers.mDataByteSize) / MemoryLayout<Float32>.size
        guard frames > 0 else { return }
        let samples = data.bindMemory(to: Float32.self, capacity: frames)

        // Float32 → Int16 LE. 채널이 여러 개면 인터리브를 평균내 모노로 만든다.
        let ch = max(1, Int(asbd.mChannelsPerFrame))
        let interleaved = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) == 0
        let outFrames = interleaved ? frames / ch : frames
        var pcm = [Int16](repeating: 0, count: outFrames)
        for i in 0..<outFrames {
            var v: Float32 = 0
            if interleaved && ch > 1 {
                for c in 0..<ch { v += samples[i * ch + c] }
                v /= Float32(ch)
            } else {
                v = samples[i]
            }
            pcm[i] = Int16(max(-1.0, min(1.0, v)) * 32767)
        }
        pcm.withUnsafeBufferPointer { buf in
            out.write(Data(buffer: buf))
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail("스트림 중단: \(error.localizedDescription)")
    }
}

func capture(target: String) async {
    let content: SCShareableContent
    do {
        content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false)
    } catch {
        // 권한이 없으면 여기서 걸린다
        fail("화면 기록 권한이 필요합니다. 시스템 설정 → 개인정보 보호 및 보안 → 화면 기록에서 허용하세요. (\(error.localizedDescription))")
    }

    guard let display = content.displays.first else { fail("디스플레이를 찾을 수 없습니다") }

    let filter: SCContentFilter
    if target == "SYSTEM" {
        // 시스템 전체 — 자기 자신 소리만 제외
        let me = content.applications.first { $0.bundleIdentifier == Bundle.main.bundleIdentifier }
        filter = SCContentFilter(display: display,
                                 excludingApplications: me.map { [$0] } ?? [],
                                 exceptingWindows: [])
    } else {
        guard let app = content.applications.first(where: { $0.bundleIdentifier == target }) else {
            fail("'\(target)' 앱을 찾을 수 없습니다. 실행 중인지 확인하세요.")
        }
        filter = SCContentFilter(display: display, including: [app], exceptingWindows: [])
    }

    let cfg = SCStreamConfiguration()
    cfg.capturesAudio = true
    cfg.sampleRate = SAMPLE_RATE
    cfg.channelCount = CHANNELS
    cfg.excludesCurrentProcessAudio = true
    // 화면은 쓰지 않지만 SCStream이 비디오를 요구하므로 최소 크기로 낮춰 부담을 줄인다
    cfg.width = 2
    cfg.height = 2
    cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)

    let tap = AudioTap()
    let stream = SCStream(filter: filter, configuration: cfg, delegate: tap)
    do {
        try stream.addStreamOutput(tap, type: .audio,
                                   sampleHandlerQueue: DispatchQueue(label: "audio"))
        try await stream.startCapture()
    } catch {
        fail("캡처를 시작할 수 없습니다: \(error.localizedDescription)")
    }

    // 부모가 파이프를 닫거나 프로세스를 죽일 때까지 계속 흘려보낸다
    while true { try? await Task.sleep(nanoseconds: 1_000_000_000) }
}

// ── 진입점 ───────────────────────────────────────────────────────────────────
let args = CommandLine.arguments
signal(SIGPIPE, SIG_IGN)        // 파이프가 닫히면 write 실패로 조용히 끝난다

if args.count >= 2 && args[1] == "--list" {
    listApps()
    exit(0)
} else if args.count >= 3 && args[1] == "--capture" {
    let sem = DispatchSemaphore(value: 0)
    Task {
        await capture(target: args[2])
        sem.signal()
    }
    sem.wait()
} else {
    print("사용법: audio_capture --list | --capture <bundleID|SYSTEM>")
    exit(2)
}
