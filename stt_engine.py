"""macOS용 STT 엔진 — sounddevice로 마이크를 받고, 에너지 VAD로 발화 구간을
끊어서 Groq Whisper에 보낸다.

Windows판은 RealtimeSTT(faster-whisper)를 썼지만 여기서는 인식을 전부 API로
넘기므로 torch / multiprocessing / 모델 로딩이 없다. 대신 발화 구간을 직접
잘라야 해서 VAD가 이 파일의 핵심이다.

상태 전이:
  IDLE ─[음성 감지]→ SPEAKING ─[침묵]→ PROCESSING ─[인식 완료]→ IDLE
"""

import os
import queue
import subprocess
import sys
import threading
import time
from enum import Enum

import numpy as np
import sounddevice as sd

import config
import groq_client

SAMPLE_RATE = 16000
BLOCK_MS    = 30
BLOCK_SIZE  = SAMPLE_RATE * BLOCK_MS // 1000   # 480 샘플

# ── VAD 튜닝값 ───────────────────────────────────────────────────────────────
ONSET_BLOCKS   = 3      # 연속 3블록(90ms) 음성이면 발화 시작으로 본다
PREROLL_BLOCKS = 10     # 발화 시작 300ms 앞부터 포함 (첫 음절 잘림 방지)
NOISE_FACTOR   = 3.0    # 잡음 바닥의 3배를 넘으면 음성
NOISE_FLOOR_MIN = 1e-4  # 완전 무음 환경에서 문턱이 0으로 붙는 것 방지

# 잡음 바닥은 "빠르게 내려가고 아주 천천히 올라가는" 비대칭 추적으로 잡는다.
#
# 두 가지 함정을 동시에 피해야 한다.
#  (1) 음성이 아닌 블록으로만 갱신하면(예전 방식) 시스템 오디오처럼 시작이 완전한
#      무음(0)일 때 바닥이 최솟값에 붙고 → 문턱이 너무 낮아 모든 블록이 음성이 되고
#      → 바닥이 영영 갱신되지 않아 발화가 안 끊긴다.
#  (2) 최근 구간의 백분위로 잡으면 말이 이어질 때 창이 음성으로 가득 차 바닥이
#      음성 레벨까지 올라가고 → 진짜 말소리가 침묵으로 오분류된다.
#
# 매 블록 갱신하되 상승만 극단적으로 느리게 하면 둘 다 피할 수 있다.
NOISE_DOWN = 0.30      # 지금이 더 조용하면 빠르게 따라 내려간다
NOISE_UP   = 0.0003    # 올라갈 때는 아주 느리게 (시상수 약 100초)

# 발화를 끊는 조건 — Groq 무료 한도(분당 20회)를 넘지 않도록 짧은 말은 뭉친다
SHORT_SILENCE = 0.8     # 이만큼 조용하면 끊는다 (단, 아래 MIN_CHUNK 이상 모였을 때)
LONG_SILENCE  = 2.0     # 이만큼 조용하면 짧게 모였어도 끊는다
MIN_CHUNK     = 6.0     # 최소 이만큼 말이 모여야 SHORT_SILENCE로 끊는다
MAX_CHUNK     = 12.0    # 계속 말하면 이 길이에서 강제로 끊는다 (인식 지연 상한)
MIN_UTTERANCE = 0.4     # 이보다 짧으면 잡음으로 보고 버린다

# 앱 소리에 마이크를 섞을 때, 마이크가 이만큼(블록) 넘게 밀리면 오래된 것을 버린다.
# 두 소스는 서로 다른 시계로 들어오므로 조금씩 어긋나는데, 그냥 두면 지연이 계속
# 쌓여 나중에는 몇 초 전 목소리가 섞인다.
MIC_LAG_BLOCKS = 10     # 300ms


class STTState(Enum):
    IDLE       = "idle"        # 실행 중, 음성 대기
    SPEAKING   = "speaking"    # 발화 녹음 중
    PROCESSING = "processing"  # Groq에 인식 요청 중


DEFAULT_DEVICE_LABEL = "시스템 기본값"

# 앱 소리를 잡을 때 쓰는 접두사. 접두사가 없으면 마이크 이름으로 본다.
APP_PREFIX     = "app:"
SYSTEM_SOURCE  = APP_PREFIX + "SYSTEM"


def helper_path():
    """audio_capture 헬퍼 경로. .app 안에서는 번들에 포함된 것을 쓴다."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "audio_capture")
    if os.path.exists(path) and not os.access(path, os.X_OK):
        try:
            os.chmod(path, 0o755)      # 번들에 들어가며 실행 권한이 빠질 수 있다
        except OSError:
            pass
    return path


def app_sources():
    """소리를 잡을 수 있는 실행 중인 앱 [(bundleID, 표시이름)]. 실패하면 빈 목록.

    Windows에서는 시스템 전체 소리만 잡는다. 앱별로 고르려면 Windows 10 2004의
    프로세스 루프백 API가 필요한데 파이썬 바인딩이 없어 C 헬퍼를 따로 짜야 한다.
    """
    if config.WINDOWS:
        return []
    path = helper_path()
    if not os.path.exists(path):
        return []
    try:
        r = subprocess.run([path, "--list"], capture_output=True, text=True, timeout=5)
    except Exception:
        return []
    out = []
    for line in r.stdout.splitlines():
        bid, _, name = line.partition("\t")
        if bid and name:
            out.append((bid, name))
    return out


def input_devices():
    """입력 가능한 장치 이름 목록. 설정 드롭다운에서 쓴다."""
    names = []
    for d in sd.query_devices():
        if d["max_input_channels"] > 0 and d["name"] not in names:
            names.append(d["name"])
    return names


def _resolve_device(name):
    """장치 이름 → 인덱스. 인덱스는 장치를 꽂고 뺄 때마다 바뀌므로 이름으로 저장한다."""
    if not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and d["name"] == name:
            return i
    return None      # 사라진 장치 — 기본값으로 넘어간다


class STTEngine:
    def __init__(self, language="ko", device="", include_mic=False, mic_device="",
                 on_confirmed=None, on_state_change=None, on_error=None,
                 on_notice=None):
        self.language = language
        self.device = device        # 장치 이름 (빈 값이면 시스템 기본값)
        # 앱 소리를 잡을 때 내 목소리도 함께 받을지. 마이크 입력일 때는 의미가 없다.
        self.include_mic = include_mic
        self.mic_device = mic_device    # 섞을 마이크 이름. 빈 값이면 시스템 기본값

        self._on_confirmed    = on_confirmed    or (lambda t: None)
        self._on_state_change = on_state_change or (lambda s: None)
        self._on_error        = on_error        or (lambda m: None)
        self._on_notice       = on_notice       or (lambda m: None)

        self.state    = STTState.IDLE
        self._running = False

        self._stream     = None
        self._blocks     = queue.Queue()   # 오디오 소스 → VAD 스레드
        self._pending    = queue.Queue()   # VAD 스레드 → 전송 스레드
        self._app_q      = None            # 앱 소리 → 믹서 (마이크를 섞을 때만)
        self._mic_blocks = queue.Queue()   # 마이크 → 믹서 (마이크를 섞을 때만)
        self._mixing     = False           # 지금 두 소스를 섞는 중인지
        self._inflight   = 0               # 인식 대기 중인 요청 수
        self._in_speech  = False           # VAD가 발화를 모으는 중인지
        self._last_text  = ""
        self._proc       = None            # 앱 소리 캡처 헬퍼 프로세스
        self._lock       = threading.Lock()

    # ── Public ──────────────────────────────────────────────────────────────

    @property
    def running(self):
        return self._running

    def start(self):
        with self._lock:
            if self._running:
                return
            self._running = True

        self._last_text = ""
        # 큐를 비워서 재사용하지 않고 매번 새로 만든다. 예전에는 비워 썼는데,
        # stop() 직후 곧바로 start()가 불리면(장치 변경 등) 옛 스레드가 종료신호를
        # 집기 전에 그 신호가 지워져 스레드가 안 죽고 계속 쌓였다. 큐를 새로 만들면
        # 옛 스레드는 자기 큐에 남은 종료신호를 받아 스스로 끝난다.
        blocks  = queue.Queue()
        pending = queue.Queue()
        self._blocks, self._pending = blocks, pending
        self._mic_blocks = queue.Queue()
        self._inflight = 0
        self._in_speech = False
        self._mixing = False
        self._app_q = None

        if self.device.startswith(APP_PREFIX):
            # 마이크를 섞을 때는 앱 소리를 VAD가 아니라 믹서로 먼저 보낸다
            app_q = queue.Queue() if self.include_mic else blocks
            if not self._start_app_capture(self.device[len(APP_PREFIX):], app_q):
                return
            if self.include_mic:
                self._app_q = app_q
                self._mixing = True
                if not self._open_mic(_resolve_device(self.mic_device)):
                    # 마이크가 안 열려도 앱 소리만으로 계속 간다.
                    # 믹서는 마이크 큐가 비어 있으면 앱 소리를 그대로 흘려보낸다.
                    self._on_notice("마이크를 열 수 없어 앱 소리만 받습니다")
                threading.Thread(target=self._mix_loop, args=(app_q, blocks),
                                 daemon=True).start()
            self._start_workers(blocks, pending)
            self._set_state(STTState.IDLE)
            return

        idx = _resolve_device(self.device)
        if self.device and idx is None:
            self._on_error(f"'{self.device}' 장치를 찾을 수 없어 기본 장치를 씁니다")
        if not self._open_mic(idx):
            self._running = False
            self._set_state(STTState.IDLE)
            return

        self._start_workers(blocks, pending)
        self._set_state(STTState.IDLE)

    def _start_workers(self, blocks, pending):
        """VAD와 전송 스레드를 띄운다. 큐를 인자로 넘겨야 세션이 섞이지 않는다."""
        threading.Thread(target=self._vad_loop, args=(blocks, pending),
                         daemon=True).start()
        threading.Thread(target=self._send_loop, args=(pending,),
                         daemon=True).start()

    def _open_mic(self, idx):
        """마이크 스트림을 연다. 성공 여부를 반환."""
        try:
            # BlackHole 같은 가상 장치는 스테레오라 모노로 합쳐야 한다
            info = sd.query_devices(sd.default.device[0] if idx is None else idx)
            channels = min(2, max(1, int(info["max_input_channels"])))
            self._stream = sd.InputStream(
                device=idx,
                samplerate=SAMPLE_RATE,
                channels=channels,
                dtype="float32",
                blocksize=BLOCK_SIZE,
                callback=self._audio_callback,
            )
            self._stream.start()
            return True
        except Exception as e:
            self._stream = None
            self._on_error(f"입력 장치를 열 수 없습니다: {e}")
            return False

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

        # 스레드 깨우기 — 각자 자기 큐의 종료신호를 받아 끝낸다
        for q in (self._app_q, self._blocks, self._pending):
            if q is not None:
                q.put(None)
        self._app_q = None
        self._mixing = False
        self._set_state(STTState.IDLE)

    def shutdown(self):
        self.stop()

    # ── 앱 소리 캡처 (ScreenCaptureKit 헬퍼) ──────────────────────────────────

    def _start_app_capture(self, bundle_id, target):
        """헬퍼를 띄우고 stdout에서 PCM을 읽어 target 큐에 넣는다. 성공 여부 반환.

        target은 마이크를 섞을 때는 믹서 큐, 아니면 VAD 큐다.
        """
        if config.WINDOWS:
            return self._start_loopback(target)

        path = helper_path()
        if not os.path.exists(path):
            self._running = False
            self._on_error("audio_capture 헬퍼를 찾을 수 없습니다")
            self._set_state(STTState.IDLE)
            return False
        try:
            self._proc = subprocess.Popen(
                [path, "--capture", bundle_id],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except Exception as e:
            self._running = False
            self._on_error(f"소리 캡처를 시작할 수 없습니다: {e}")
            self._set_state(STTState.IDLE)
            return False

        threading.Thread(target=self._pipe_reader, args=(self._proc, target), daemon=True).start()
        threading.Thread(target=self._pipe_errors, args=(self._proc,), daemon=True).start()
        return True

    def _start_loopback(self, target):
        """Windows: 스피커로 나가는 소리를 그대로 되받는다(WASAPI 루프백).

        sounddevice(PortAudio)는 루프백 플래그를 노출하지 않아 soundcard를 쓴다.
        기본 스피커를 입력 장치처럼 열고, 맥 헬퍼와 같은 모양(모노 float32 블록)으로
        큐에 넣는다. 그래서 이 아래 VAD·전송 경로는 두 플랫폼이 같은 코드다.
        """
        try:
            import soundcard
        except ImportError:
            self._running = False
            self._on_error("soundcard 모듈이 없어 시스템 소리를 잡을 수 없습니다")
            self._set_state(STTState.IDLE)
            return False
        try:
            speaker = soundcard.default_speaker()
            mic = soundcard.get_microphone(str(speaker.name), include_loopback=True)
        except Exception as e:
            self._running = False
            self._on_error(f"시스템 소리 장치를 열 수 없습니다: {e}")
            self._set_state(STTState.IDLE)
            return False

        def loop():
            try:
                with mic.recorder(samplerate=SAMPLE_RATE, channels=1,
                                  blocksize=BLOCK_SIZE) as rec:
                    while self._running:
                        data = rec.record(numframes=BLOCK_SIZE)
                        # soundcard는 (프레임, 채널) 2차원으로 준다
                        target.put(np.asarray(data, dtype=np.float32).reshape(-1))
            except Exception as e:
                self._on_error(f"시스템 소리 캡처가 끊겼습니다: {e}")
            finally:
                target.put(None)

        threading.Thread(target=loop, daemon=True).start()
        return True

    def _pipe_reader(self, proc, target):
        """16bit LE 모노 PCM을 블록 단위로 읽어 float32로 바꾼다."""
        nbytes = BLOCK_SIZE * 2
        while self._running and proc.poll() is None:
            buf = proc.stdout.read(nbytes)
            if not buf:
                break
            if len(buf) < nbytes:
                buf += b"\x00" * (nbytes - len(buf))
            target.put(
                np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0)
        target.put(None)            # 다음 단계(믹서 또는 VAD) 깨우기

    def _pipe_errors(self, proc):
        """헬퍼가 stderr로 뱉는 오류(주로 권한 문제)를 UI로 올린다."""
        for raw in proc.stderr:
            msg = raw.decode("utf-8", "replace").strip()
            if msg.startswith("ERROR: "):
                msg = msg[7:]
            if msg:
                self._on_error(msg)

    # ── 오디오 콜백 (실시간 스레드 — 절대 블로킹 금지) ─────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        if not self._running:
            return
        # 스테레오면 평균내 모노로 (한쪽 채널만 쓰면 반대쪽 소리를 놓친다)
        block = (indata.mean(axis=1) if indata.shape[1] > 1
                 else indata[:, 0].copy())
        # 앱 소리와 섞는 중이면 믹서가 가져가도록 따로 쌓는다
        (self._mic_blocks if self._mixing else self._blocks).put(block)

    # ── 믹서: 앱 소리 + 내 목소리 ────────────────────────────────────────────

    def _mix_loop(self, app_q, out_q):
        """앱 소리를 시계 삼아 마이크를 얹는다.

        두 소스는 각자의 속도로 들어오므로, 앱 블록 하나마다 마이크 블록을 하나만
        꺼내 더한다. 마이크가 아직 안 왔으면 그 블록은 앱 소리만 내보낸다. 둘을
        같은 큐에 그냥 밀어넣으면 VAD가 두 소리를 번갈아 집어 시간축이 깨진다.
        """
        while self._running:
            block = app_q.get()
            if block is None:
                break
            # 마이크가 밀렸으면 오래된 것부터 버려 지연이 쌓이지 않게 한다
            while self._mic_blocks.qsize() > MIC_LAG_BLOCKS:
                try:
                    self._mic_blocks.get_nowait()
                except queue.Empty:
                    break
            try:
                mic = self._mic_blocks.get_nowait()
            except queue.Empty:
                mic = None
            if mic is not None and len(mic) == len(block):
                # 그냥 더하면 둘 다 클 때 넘치므로 잘라낸다
                block = np.clip(block + mic, -1.0, 1.0)
            out_q.put(block)
        out_q.put(None)             # VAD 루프 깨우기

    # ── VAD: 블록을 모아 발화 단위로 자른다 ───────────────────────────────────

    def _vad_loop(self, block_q, pending_q):
        noise_floor  = None
        preroll      = []          # 발화 직전 블록 (링버퍼)
        speech_run   = 0           # 연속 음성 블록 수
        utterance    = []          # 현재 모으는 중인 발화
        speech_secs  = 0.0         # utterance에 담긴 실제 음성 길이
        silence_secs = 0.0
        block_secs   = BLOCK_MS / 1000.0

        while self._running:
            block = block_q.get()
            if block is None:
                break

            rms = float(np.sqrt(np.mean(block ** 2)))

            # 분류 결과와 무관하게 매 블록 갱신한다. 내려갈 때는 빠르게, 올라갈
            # 때는 아주 느리게 — 말소리가 바닥을 끌어올리지 못하게 한다.
            if noise_floor is None:
                noise_floor = max(rms, NOISE_FLOOR_MIN)
            elif rms < noise_floor:
                noise_floor = (1 - NOISE_DOWN) * noise_floor + NOISE_DOWN * rms
            else:
                noise_floor = (1 - NOISE_UP) * noise_floor + NOISE_UP * rms
            noise_floor = max(noise_floor, NOISE_FLOOR_MIN)

            threshold = max(noise_floor * NOISE_FACTOR, NOISE_FLOOR_MIN)
            is_speech = rms > threshold

            if utterance:
                # 이미 발화를 모으는 중
                utterance.append(block)
                if is_speech:
                    speech_secs += block_secs
                    silence_secs = 0.0
                else:
                    silence_secs += block_secs

                total_secs = len(utterance) * block_secs
                cut = (
                    (silence_secs >= SHORT_SILENCE and speech_secs >= MIN_CHUNK)
                    or silence_secs >= LONG_SILENCE
                    or total_secs >= MAX_CHUNK
                )
                if cut:
                    # _flush가 PROCESSING을 세운 뒤에 내려야 그 틈에 전송 스레드가
                    # IDLE을 덮어쓰지 않는다
                    self._flush(utterance, speech_secs, pending_q)
                    self._in_speech = False
                    utterance, speech_secs, silence_secs, speech_run = [], 0.0, 0.0, 0
            else:
                # 발화 시작을 기다리는 중
                preroll.append(block)
                if len(preroll) > PREROLL_BLOCKS:
                    preroll.pop(0)

                speech_run = speech_run + 1 if is_speech else 0
                if speech_run >= ONSET_BLOCKS:
                    utterance = list(preroll)
                    speech_secs = speech_run * block_secs
                    silence_secs = 0.0
                    preroll = []
                    self._in_speech = True
                    self._set_state(STTState.SPEAKING)

        # 정지 시 남은 발화도 보낸다
        if utterance:
            self._flush(utterance, speech_secs, pending_q)
        self._in_speech = False

    def _flush(self, blocks, speech_secs, pending_q):
        if speech_secs < MIN_UTTERANCE:
            self._set_state(STTState.IDLE)
            return
        audio = np.concatenate(blocks)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        self._inflight += 1
        pending_q.put(pcm)
        self._set_state(STTState.PROCESSING)

    # ── 전송: Groq Whisper 호출 ───────────────────────────────────────────────

    def _send_loop(self, pending_q):
        while True:
            pcm = pending_q.get()
            if pcm is None:
                if not self._running:
                    break
                continue

            try:
                wav = groq_client.pcm_to_wav(pcm, SAMPLE_RATE)
                text = groq_client.transcribe(
                    wav, language=self.language, prompt=self._last_text,
                    fallback_callback=lambda old, new: self._on_notice(
                        f"{old} 한도 초과 → {new}로 전환"),
                )
                if text:
                    self._last_text = text
                    self._on_confirmed(text)
            except groq_client.GroqError as e:
                self._on_error(str(e))
            except Exception as e:
                self._on_error(f"인식 실패: {e}")
            finally:
                self._inflight = max(0, self._inflight - 1)
                # 이미 다음 발화가 시작됐으면 SPEAKING을 덮어쓰지 않는다
                if self._inflight == 0 and not self._in_speech:
                    self._set_state(STTState.IDLE)

    # ── 상태 ─────────────────────────────────────────────────────────────────

    def _set_state(self, state):
        if state == self.state:
            return
        self.state = state
        self._on_state_change(state)
