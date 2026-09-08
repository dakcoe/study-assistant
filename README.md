# Study Assistant (macOS)

수업용 AI 공부 도우미. 클립보드 자동 캡처 + Groq LLM 채팅 + Groq Whisper 음성 메모.

Windows판에서 **디자인 시스템과 UI 요소만 가져오고**, 플랫폼에 의존하는 코드는 전부 macOS용으로 새로 썼습니다.

## 실행

**평소에는 `/Applications/Study AI.app`을 실행하세요.** (Spotlight에서 "Study AI")

터미널에서 `python main.py`로 띄우면 **마이크가 동작하지 않습니다.** macOS는 권한 주체를 파이썬이 아니라 그걸 실행한 부모 앱(터미널/에디터)으로 보는데, 그 앱에 마이크 권한이 없으면 요청 팝업이 뜨지 않고 PortAudio가 에러 없이 무음(전부 0)만 돌려줍니다. `.app`으로 묶어야 앱이 자기 이름으로 권한을 받습니다.

코드를 고치며 개발할 때는 터미널 실행도 됩니다 (마이크만 안 됨):

```
.venv/bin/python main.py
```

venv를 새로 만들려면:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

처음 실행하면 API 키 입력을 요구합니다. [console.groq.com/keys](https://console.groq.com/keys)에서 무료로 발급받아 **⚙ 설정 → API 키**에 붙여넣고 **확인**을 누르세요.

## .app 빌드

```
./build.sh          # 코드가 바뀐 것만 다시 빌드 → /Applications 까지 설치
./build.sh --swift  # Swift 헬퍼까지 강제로 다시 컴파일
```

`build.sh`가 하는 일: Swift 헬퍼 컴파일(필요할 때만) → PyInstaller → 서명 → `/Applications` 설치.

**직접 PyInstaller만 돌리면 안 된다.** 두 가지가 빠진다.

- **`/Applications` 설치.** `dist/`와 `/Applications`에 같은 번들 ID를 가진 사본이 둘 있으면, `open dist/...`을 해도 macOS LaunchServices가 `/Applications` 쪽을 대신 띄운다. 새로 빌드했는데 옛날 앱이 실행되는 함정에 빠진다.
- **헬퍼 서명.** `audio_capture`를 앱과 같은 신원(`com.superbleo.studyai`)으로 서명해야 macOS가 둘을 한 프로그램으로 본다. 서명이 따로 놀면 화면 기록 권한을 매번 다시 묻는다.

**Swift 헬퍼를 다시 컴파일하면 서명 해시가 바뀌어 권한을 다시 물어본다.** 그래서 `build.sh`는 `.swift`가 바뀌지 않았으면 건너뛴다. 근본 원인은 ad-hoc 서명(개발자 인증서 없음)이라 TCC가 권한을 안정적으로 기억하지 못하는 것이다. 완전히 없애려면 Apple Developer Program(연 $99)의 Developer ID 인증서가 필요하다.

`StudyAI.spec`의 `info_plist`에 있는 **`NSMicrophoneUsageDescription`이 빠지면 macOS가 마이크 권한 요청 자체를 띄우지 않는다.** 최전면 앱 감지에 쓰는 `NSAppleEventsUsageDescription`도 마찬가지다.

Dock 아이콘이 이전 것으로 남아 있으면 `killall Dock`으로 캐시를 갱신한다.

## 설정 파일 위치

| 실행 방식 | settings.json / notes |
|---|---|
| `.app` | `~/Library/Application Support/StudyAI/` |
| `python main.py` | 프로젝트 폴더 |

`.app`은 번들 안이 읽기 전용이라 `config.py`가 `sys.frozen`을 보고 경로를 나눕니다. 두 방식이 서로 다른 설정을 쓰므로, 키를 한쪽에만 넣었다면 다른 쪽에서는 다시 입력해야 합니다.

## 요구 사항

- Python 3.11+ (Tk 8.6 필요 — Tk 9.0에서는 customtkinter가 깨집니다)
- Groq API 키
- 네트워크 연결 (채팅·음성 인식 모두 API 호출)

로컬 모델을 안 쓰므로 ollama, torch, RealtimeSTT, faster-whisper가 전부 필요 없습니다.

## 비용

무료 플랜 범위 안에서는 **0원**이고, 한도를 넘으면 과금이 아니라 요청이 거부됩니다.

| | Whisper | gpt-oss-120b (기본) | llama-3.3-70b |
|---|---|---|---|
| 분당 요청 | 20회 | 30회 | 30회 |
| 하루 요청 | 2,000회 | 1,000회 | 1,000회 |
| 분당 토큰 | 오디오 2시간 | 8,000 | 12,000 |
| 하루 토큰 | 오디오 8시간 | **200,000** | 100,000 |

STT는 수업용으로 넉넉합니다(하루 8시간 분량). 채팅은 **하루 토큰이 먼저 닳습니다** — 긴 강의 노트를 통째로 붙여넣으면 한 번에 2~3천 토큰씩 나갑니다.

기본 모델을 `gpt-oss-120b`로 둔 이유: `llama-3.3-70b`는 한국어 생성 중 한자를 섞어 뱉는 버릇이 있었는데(예: "출력한**文字**와") gpt-oss에서는 재현되지 않습니다. 입력 단가가 4배 싸고($0.15 vs $0.59 per 1M) 하루 토큰 한도도 두 배입니다. 다만 gpt-oss는 추론 모델이라 답변 전 reasoning 토큰을 생성하고 **그것도 출력 토큰으로 차감**되므로, 하루 한도가 체감상 정확히 두 배는 아닙니다. 분당 토큰이 8K로 더 낮은 것도 유의 — 긴 노트를 연달아 붙여넣으면 429가 날 수 있습니다.

## 기능

**채팅** — 입력창에 쓰거나, 클립보드에서 자동으로 받아 요약·설명. 마크다운 렌더링(헤더/불릿/코드블록/굵게), 스트리밍 출력, 대화 맥락 유지.

**클립보드 캡처** — 500ms마다 `pbpaste` 폴링. 새로 복사하면 상단에 미리보기 바가 뜨고 Send로 전송. `Auto Send`를 켜면 복사 즉시 전송. 터미널·에디터에서 복사한 건 무시합니다(`EXCLUDED_APPS`).

**소리 입력** — Notes 창 하단에서 마이크와 앱 소리를 골라 녹음한다. `🔊`가 붙은 항목은 그 앱의 소리만 잡는다(ScreenCaptureKit). 가상 오디오 장치를 깔거나 출력 장치를 바꿀 필요가 없어서, 소리는 평소대로 들리고 볼륨 키도 그대로 살아 있다. 목록은 Notes를 열 때마다 갱신되므로 나중에 켠 앱도 바로 잡힌다.

**내 목소리도 함께** — `🔊` 항목을 고르면 옆에 체크박스가 켜진다. 앱 소리에 마이크를 얹어 한 줄기로 받아적는다. 화상회의나 통화처럼 상대 목소리(앱 소리)와 내 목소리(마이크)가 서로 다른 경로로 오는 상황을 위한 것이다. 마이크를 직접 고른 상태에서는 섞을 것이 없으므로 꺼진다.

> 스피커로 들으면서 켜면 상대 목소리가 마이크로도 한 번 더 들어와 겹친다. **이어폰을 쓰는 편이 낫다.**

**음성 메모 (Notes)** — 마이크 버튼으로 녹음 시작. 왼쪽에 원문, 오른쪽에 번역이 실시간으로 쌓입니다. 인식 언어(한국어/English/日本語)는 녹음 중에도 바꿀 수 있고, 응답 언어와 다르면 자동 번역됩니다. `Save note`로 `notes/`에 타임스탬프 파일로 저장.

**창 버튼** — Notes 창의 🟡 최소화는 녹음을 유지하고(창을 치워두고 계속 받아 적는 용도), 🔴 닫기는 녹음을 멈춘다. 안 보이는 채로 계속 캡처해 API 한도를 축내지 않도록.

**투명도** — 창에서 포커스가 빠지면 설정한 투명도로 흐려지고, 다시 클릭하면 불투명해집니다. `Always on Top`을 끄면 이 동작도 꺼집니다.

**테마** — Light / Dark / Neon 3종. 설정에서 즉시 전환되고 열려 있는 노트 창에도 같이 적용됩니다.

## Windows판에서 바뀐 것

| 항목 | Windows | macOS |
|---|---|---|
| LLM | ollama (로컬) | Groq API |
| STT | RealtimeSTT + faster-whisper (로컬) | Groq Whisper API |
| 최전면 앱 감지 | `ctypes.windll.user32` | `osascript` + System Events |
| 클립보드 | `pyperclip` | `pbpaste` |
| UI 폰트 | Malgun Gothic | Apple SD Gothic Neo |
| 고정폭 폰트 | Courier New | Menlo |
| 콘솔 숨기기 | `CREATE_NO_WINDOW` | 불필요 (제거) |
| 설치 마법사 | `wizard.py` | 제거 — 설정 창으로 대체 |

**로컬 Whisper를 안 쓰는 이유**: RealtimeSTT가 쓰는 CTranslate2는 Apple Silicon GPU(Metal)를 지원하지 않아 Mac에서는 CPU로만 돕니다. M1에서 `large-v3`는 약 1배속이라 실시간 인식이 밀리고, 본 모델과 실시간 모델이 별도 프로세스에 중복 로드돼 메모리도 부담입니다. API로 넘기면 가장 큰 `large-v3`를 그대로 쓸 수 있습니다.

## 파일 구조

```
study-assistant(mac)/
├── main.py           # customtkinter UI (StudyAssistant / NotesWindow / SettingsDialog / MicButton)
├── stt_engine.py     # 마이크 캡처 + 에너지 VAD + Groq Whisper 호출
├── groq_client.py    # Groq API (채팅 스트리밍 + 음성 인식 + 키 검증)
├── config.py         # settings.json 로드/저장
├── test_studyai.py   # 테스트 (.venv/bin/python test_studyai.py)
├── audio_capture.swift  # ScreenCaptureKit 앱 소리 캡처 헬퍼 (Swift)
├── audio_capture        # 위를 컴파일한 바이너리 (arm64)
├── audio_capture_x86    # 같은 것의 인텔용
│
├── build.sh          # arm64 빌드 + 서명 + /Applications 설치
├── build-intel.sh    # 인텔용 빌드 → make_dmg.sh --intel 까지
├── make_dmg.sh       # 배포용 dmg (안내문 포함). --build / --intel
├── StudyAI.spec      # PyInstaller 빌드 설정 (권한 설명 키 포함)
├── requirements.txt
│
├── assets/           # 번들에 통째로 들어간다
│   ├── AppIcon.icns
│   ├── MaterialIcons-Regular.ttf   # 톱니 아이콘용, 프로세스 범위로 등록
│   └── help_key_*.png              # 도움말의 API 키 발급 안내 그림
├── tools/
│   ├── grabwin.py    # 창만 찍는 스크린샷 도구 (UI 확인용)
│   └── icon/         # 아이콘 원본 그림 + make_icon.py
└── dist/
    ├── Study AI 1.0.0.dmg          # Apple Silicon
    ├── Study AI 1.0.0 (Intel).dmg  # 인텔
    ├── 설치 안내.txt
    └── 보관/                        # 지난 버전
```

개발 중 소스로 실행하면 `settings.json`·`usage.json`·`notes/`가 이 폴더에 생긴다
(`.app`으로 실행할 때는 `~/Library/Application Support/StudyAI/`).
**그 `settings.json`에는 API 키가 들어가므로 폴더째 남에게 보내지 않는다.**

## 구조 메모

**VAD가 이 앱의 핵심** (`stt_engine.py`). 로컬 모델을 안 쓰니 발화 구간을 직접 잘라야 합니다. 30ms 블록마다 RMS를 재고, 잡음 바닥의 3배를 문턱으로 씁니다. 발화 시작 300ms 앞(`PREROLL_BLOCKS`)까지 포함해야 첫 음절이 안 잘립니다.

**잡음 바닥은 "빠르게 내려가고 아주 천천히 올라가는" 비대칭 추적입니다.** 두 함정을 동시에 피해야 합니다.

- *음성이 아닌 블록으로만 갱신하면* — 시스템 오디오처럼 시작이 완전한 무음(정확히 0)일 때 바닥이 최솟값에 붙고 → 문턱이 너무 낮아 모든 블록이 음성으로 분류되고 → 바닥이 영영 갱신되지 않습니다. 침묵이 한 번도 감지되지 않아 **영상을 멈출 때까지 발화가 안 끊깁니다.**
- *최근 구간의 백분위로 잡으면* — 말이 이어질 때 창이 음성으로 가득 차 바닥이 음성 레벨까지 올라가고 → 진짜 말소리가 침묵으로 오분류됩니다.

매 블록 갱신하되 상승만 극단적으로 느리게(`NOISE_UP`) 하면 둘 다 피할 수 있습니다.

**짧은 말은 일부러 뭉칩니다.** 문장마다 API를 때리면 분당 20회 한도에 걸립니다. `0.8초 침묵 + 6초 이상 모임` 또는 `2초 침묵` 또는 `12초 경과`일 때만 끊습니다. 실측으로 쉬지 않는 60초 강의도 분당 4~6회에 그칩니다. `MAX_CHUNK`가 곧 인식 지연의 상한입니다.

**상태 갱신 순서 주의.** `_flush()`가 PROCESSING을 세운 **뒤에** `_in_speech`를 내려야 합니다. 순서가 바뀌면 그 틈에 전송 스레드가 IDLE을 덮어써서 상태 표시가 깜빡입니다.

**재시작 시 큐를 비웁니다.** `stop()`이 넣는 종료 신호(`None`)를 이전 스레드가 못 먹고 나가는 경우가 있어서, `start()`에서 큐를 비우지 않으면 새 스레드가 묵은 `None`을 집어 즉시 죽습니다.

**Whisper 환각 차단.** 침묵 구간에서 같은 구절을 반복 생성하는 문제가 있어 `_sanitize_stt()`가 KMP 실패함수로 반복 주기를 찾아 잘라냅니다. (Windows판에서 그대로 가져옴)

**두 소리를 섞을 때는 믹서 단계를 둡니다.** 앱 소리와 마이크를 같은 큐에 그냥 밀어넣으면 VAD가 두 소리를 번갈아 집어 시간축이 깨집니다. 그래서 앱 소리를 시계로 삼고, 앱 블록 하나마다 마이크 블록을 하나씩 꺼내 더한 뒤 VAD로 넘깁니다. 두 소스는 각자의 클럭으로 들어와 조금씩 어긋나므로, 마이크가 300ms 넘게 밀리면 오래된 것부터 버려 지연이 쌓이지 않게 합니다.

**앱 소리는 별도 프로세스로 잡습니다.** macOS는 시스템 출력을 입력 장치로 노출하지 않습니다. BlackHole 같은 가상 오디오 장치를 깔고 다중 출력 기기를 만드는 방법도 있지만, 사용자가 출력 장치를 갈아끼워야 하고 그러면 **볼륨 키가 안 먹습니다.** 그래서 ScreenCaptureKit을 쓰는 Swift 헬퍼(`audio_capture`)를 띄우고 16kHz 모노 PCM을 파이프로 받습니다. 출력 장치를 건드리지 않으므로 소리는 평소대로 들리고 에어팟을 쓰든 상관없습니다. 헬퍼는 부모가 죽으면 파이프가 끊겨 같이 종료되므로 고아로 남지 않습니다.

**UI 스레드 안전성.** 백그라운드 스레드(STT, 클립보드, AI 응답)는 전부 `queue.Queue`에 콜백을 넣고, 메인 스레드가 80ms마다 드레인합니다.

**Cmd+C는 창 단위로 받습니다.** 채팅·메모 영역은 `state="disabled"`라 **키보드 포커스를 아예 받지 못합니다** (`focus_set()`을 해도 `focus_get()`이 `None`). 그래서 그 위젯에 Cmd+C를 직접 걸면 영원히 발동하지 않습니다 — 마우스 선택은 되는데 복사만 안 되는 증상이 납니다. 창에 걸고 `_copy_from()`이 선택 영역을 가진 위젯을 찾습니다.

**단축키는 keysym이 아니라 keycode로 판별합니다.** 한글 입력 상태에서 Cmd+C는 Tk에 `<Command-ㅊ>`로 들어와서 `<Command-c>` 바인딩이 걸리지 않습니다 (Cmd+V→`ㅍ`, Cmd+X→`ㅌ`도 동일). Tk는 macOS에서 keycode를 `(가상키코드 << 24 | 문자코드)`로 주는데, 한/영을 바꿔도 **문자 부분만 바뀌고 상위 가상 키코드는 그대로**입니다. 그래서 `_vkey()`가 `keycode >> 24`로 물리 키를 판별합니다 (C=8, V=9, X=7).

**시작 안내 문구는 마크로 지웁니다.** 태그로 범위를 잡으면 위젯 끝에 걸쳐서 이후 삽입되는 텍스트까지 태그를 물려받아 같이 지워집니다.

## 알려진 제약

- **실시간 임시 텍스트가 없습니다.** Groq 음성 인식은 요청/응답 방식이라 말하는 도중에 글자가 흘러나오지 않습니다. 말을 멈추면 그 구간이 한 번에 뜹니다(보통 1초 이내). Windows판의 로컬 tiny 모델 실시간 표시와 다른 점입니다.
- **오디오가 Groq 서버로 전송됩니다.** 수업 녹음에 다른 사람 목소리가 섞이는 게 문제라면 로컬 방식을 검토해야 합니다.
- **오프라인에서 동작하지 않습니다.** 강의실 네트워크가 끊기면 채팅과 STT 모두 멈춥니다.
- **`settings.json`에 API 키가 평문으로 저장됩니다.** `.gitignore`에 넣어 뒀지만, 폴더를 압축해 넘기거나 백업할 때 키가 따라갑니다. 키가 새면 [console.groq.com/keys](https://console.groq.com/keys)에서 폐기하세요.
- **앱 소리 캡처에 "화면 기록" 권한이 필요합니다.** 이름과 달리 화면은 찍지 않고 오디오만 씁니다 — ScreenCaptureKit이 그 권한을 요구하는 구조라 우회가 안 됩니다.
- **ad-hoc 서명이라 권한이 잘 안 붙어 있습니다.** Swift 헬퍼를 다시 컴파일하면 권한을 다시 물어봅니다. Developer ID 인증서가 있으면 해결됩니다.
- 최전면 앱 감지에 **자동화(Automation) 권한**이 필요합니다. 첫 실행 시 macOS가 물어봅니다. 거부하면 크래시는 안 나고, 터미널에서 복사한 내용도 캡처될 뿐입니다.

## 서드파티

- `assets/MaterialIcons-Regular.ttf` — Google Material Icons, Apache License 2.0.
  앱 번들에 넣고 실행할 때 이 프로세스에만 등록한다(시스템에 설치하지 않는다).
