# 개발 메모

## 실행

```bash
.venv/bin/python main.py
```

터미널에서 띄우면 **마이크가 동작하지 않는다.** macOS는 권한 주체를 파이썬이 아니라
그걸 실행한 부모 앱(터미널)으로 보는데, 그 앱에 마이크 권한이 없으면 요청 팝업이
뜨지 않고 PortAudio가 에러 없이 무음(전부 0)만 돌려준다. `.app`으로 묶어야 앱이
자기 이름으로 권한을 받는다.

```bash
.venv/bin/python test_studyai.py     # 테스트
```

## 빌드

```bash
./build.sh                 # arm64 빌드 + 서명 + /Applications 설치
./make_dmg.sh              # 설치된 앱으로 dmg (--build 로 빌드부터)
./build-intel.sh           # 인텔용 빌드 → dmg 까지
```

Windows와 4종 배포본은 GitHub Actions에서 만든다 (`.github/workflows/release.yml`).
`v1.0.0` 같은 태그를 밀면 Releases에 dmg 2개와 zip 2개가 붙는다.
PyInstaller는 크로스 컴파일이 안 되므로 각 플랫폼 러너에서 빌드한다.
맥 유니버설 앱은 numpy 2.x가 universal2 휠을 내지 않아 만들 수 없다.

## 플랫폼 분기

`config.WINDOWS` 하나로 갈린다. 다섯 군데뿐이다.

| 곳 | macOS | Windows |
|---|---|---|
| 설정 저장 | `~/Library/Application Support/StudyAI` | `%APPDATA%\StudyAI` |
| 시스템 소리 | ScreenCaptureKit 헬퍼(Swift) | WASAPI 루프백 (`soundcard`) |
| 최전면 앱 | `osascript` | `GetForegroundWindow` |
| 아이콘 폰트 | CoreText | gdi32 `AddFontResourceExW` |
| 단축키·클립보드·링크 | Cmd · `pbpaste` · `open` | Ctrl · Tk 클립보드 · `os.startfile` |

앱별 소리 캡처는 macOS만 된다. Windows는 프로세스 루프백 API에 파이썬 바인딩이
없어 C 헬퍼가 필요하다 — 시스템 전체 소리로 대신한다.

## 구조 메모

**VAD가 이 앱의 핵심** (`stt_engine.py`). 로컬 모델을 안 쓰니 발화 구간을 직접
잘라야 한다. 30ms 블록마다 RMS를 재고, 잡음 바닥의 3배를 문턱으로 쓴다. 발화 시작
300ms 앞(`PREROLL_BLOCKS`)까지 포함해야 첫 음절이 안 잘린다.

**잡음 바닥은 "빠르게 내려가고 아주 천천히 올라가는" 비대칭 추적이다.** 두 함정을
동시에 피해야 한다.

- *음성이 아닌 블록으로만 갱신하면* — 시스템 오디오처럼 시작이 완전한 무음(정확히 0)일
  때 바닥이 최솟값에 붙고 → 문턱이 너무 낮아 모든 블록이 음성으로 분류되고 → 바닥이
  영영 갱신되지 않는다. 침묵이 한 번도 감지되지 않아 영상을 멈출 때까지 발화가 안 끊긴다.
- *최근 구간의 백분위로 잡으면* — 말이 이어질 때 창이 음성으로 가득 차 바닥이 음성
  레벨까지 올라가고 → 진짜 말소리가 침묵으로 오분류된다.

매 블록 갱신하되 상승만 극단적으로 느리게(`NOISE_UP`) 하면 둘 다 피할 수 있다.

**짧은 말은 일부러 뭉친다.** 문장마다 API를 때리면 분당 20회 한도에 걸린다.
`0.8초 침묵 + 6초 이상 모임` 또는 `2초 침묵` 또는 `12초 경과`일 때만 끊는다. 실측으로
쉬지 않는 60초 강의도 분당 4~6회에 그친다. `MAX_CHUNK`가 곧 인식 지연의 상한이다.

**번역은 묶어 보낸다.** 받아적힌 줄을 40토큰까지 모으거나 30초가 지나면 한 번에
보낸다. 직전 묶음 하나만 예시로 딸려 보내 문맥을 잇는다. 오염된 번역(다른 언어 문자가
섞인 것)은 이력에 넣지 않는다 — 다음 번역이 그걸 따라 한다.

**한도는 수위 하나로 센다** (`groq_client.usage_level`). 토큰과 오디오 길이는 응답
헤더에 안 와서 앱이 직접 센다. 자정에 초기화되는 게 아니라 초당 일정량(상한/24시간)씩
회복되므로, 쓴 양과 그때 시각만 저장하고 볼 때 흐른 시간만큼 뺀다.

## 파일 구조

```
main.py            UI 전부 (StudyAssistant / NotesWindow / SettingsDialog / HelpDialog)
stt_engine.py      소리 캡처 + VAD + Whisper 호출
groq_client.py     Groq API — 채팅 스트리밍, 음성 인식, 모델 목록, 한도 계산
config.py          settings.json 로드/저장, 상수
test_studyai.py    테스트 (프레임워크 없이 실행)

assets/            번들에 통째로 들어간다 (아이콘, 폰트, 도움말 그림)
packaging/         설치 안내문 — 로컬 스크립트와 CI가 같은 파일을 쓴다
tools/             개발용 (창 스크린샷, 아이콘 생성기)
```

소스로 실행하면 `settings.json`·`usage.json`·`notes/`가 프로젝트 폴더에 생긴다
(`.app`은 `~/Library/Application Support/StudyAI/`). **그 `settings.json`에는 API 키가
평문으로 들어가므로 폴더째 남에게 보내지 않는다.**

## 알려진 제약

- 말하는 도중에 글자가 흘러나오지 않는다. Groq 음성 인식이 요청/응답 방식이라
  말을 멈춰야 그 구간이 한 번에 뜬다(보통 1초 이내).
- 오프라인에서 동작하지 않는다.
- ad-hoc 서명이라 Gatekeeper·SmartScreen 경고가 뜬다. 없애려면 Apple Developer
  Program(연 $99)과 Windows 코드 서명 인증서가 필요하다.
- Swift 헬퍼를 다시 컴파일하면 서명 해시가 바뀌어 macOS가 권한을 다시 묻는다.

## 서드파티

- `assets/MaterialIcons-Regular.ttf` — Google Material Icons, Apache License 2.0.
  번들에 넣고 실행할 때 이 프로세스에만 등록한다(시스템에 설치하지 않는다).
