#!/bin/bash
# Study AI 빌드 — .app 생성부터 /Applications 설치까지 한 번에.
#
#   ./build.sh          코드가 바뀐 것만 다시 빌드
#   ./build.sh --swift  Swift 헬퍼까지 강제로 다시 컴파일
#   ./build.sh --force  실행 중인 Study AI를 종료하고 빌드 (기본은 거부)
#
# 헬퍼(audio_capture)를 다시 컴파일하면 서명 해시가 바뀌고, macOS는 이를 처음 보는
# 프로그램으로 판단해 화면 기록 권한을 다시 묻는다. 그래서 .swift가 바뀌지 않았으면
# 건드리지 않는다.

set -e
cd "$(dirname "$0")"

# --force / --swift 는 순서 상관없이 받는다
FORCE=0
SWIFT=0
for a in "$@"; do
    [ "$a" = "--force" ] && FORCE=1
    [ "$a" = "--swift" ] && SWIFT=1
done

APP="dist/Study AI.app"
DEST="/Applications/Study AI.app"
BUNDLE_ID="com.superbleo.studyai"

# ── 1. Swift 헬퍼 (필요할 때만) ────────────────────────────────────────────────
if [ "$SWIFT" = "1" ] || [ ! -f audio_capture ] || [ audio_capture.swift -nt audio_capture ]; then
    echo "▶ Swift 헬퍼 컴파일"
    swiftc -O audio_capture.swift -o audio_capture
    echo "  ⚠ 헬퍼가 새로 빌드됨 — 화면 기록 권한을 다시 물어볼 수 있습니다"
else
    echo "▶ Swift 헬퍼 변경 없음 — 건너뜀 (권한 유지)"
fi

# ── 2. 실행 중인 앱 종료 ──────────────────────────────────────────────────────
# 녹음 중에 죽이면 저장 안 한 받아적기가 통째로 날아간다. 떠 있으면 먼저 물어본다.
if pgrep -f "StudyAI" >/dev/null 2>&1; then
    if [ "$FORCE" = "1" ]; then
        echo "▶ 실행 중인 Study AI 종료 (--force)"
    else
        echo "✋ Study AI가 실행 중입니다. 녹음 중이면 메모부터 저장하세요."
        echo "   종료하고 빌드하려면: ./build.sh --force"
        exit 1
    fi
fi
pkill -f "StudyAI" 2>/dev/null || true
sleep 1

# ── 3. .app 빌드 ─────────────────────────────────────────────────────────────
echo "▶ PyInstaller"
.venv/bin/python -m PyInstaller --noconfirm --clean StudyAI.spec >/dev/null 2>&1

# ── 3-1. 한국어 번들로 표시 ───────────────────────────────────────────────────
# Info.plist의 CFBundleLocalizations만으로는 부족하고, .lproj 폴더가 실제로
# 있어야 macOS가 한국어 앱으로 취급한다. 없으면 저장 패널이 영어로 뜬다.
mkdir -p "$APP/Contents/Resources/ko.lproj"
cat > "$APP/Contents/Resources/ko.lproj/InfoPlist.strings" <<'STRINGS'
"CFBundleName" = "Study AI";
"CFBundleDisplayName" = "Study AI";
STRINGS

# ── 4. 서명 ─────────────────────────────────────────────────────────────────
# 헬퍼를 앱 신원 아래로 묶어야 TCC가 둘을 한 프로그램으로 본다.
echo "▶ 서명"
codesign -f -s - -i "$BUNDLE_ID.audiocapture" "$APP/Contents/Frameworks/audio_capture"
codesign -f -s - -i "$BUNDLE_ID" --deep "$APP" 2>/dev/null

# ── 5. /Applications 설치 ────────────────────────────────────────────────────
# 두 사본이 같은 번들 ID를 가지면 macOS가 어느 쪽을 띄울지 알 수 없다.
# 항상 /Applications 쪽을 최신으로 덮어써서 헷갈릴 여지를 없앤다.
echo "▶ /Applications 설치"
rm -rf "$DEST"
cp -R "$APP" /Applications/
# dist 사본을 남겨두면 Spotlight에 같이 잡혀 "Study AI가 두 개"로 보인다.
# 빌드 중간 산출물일 뿐이므로 설치 후 지운다.
rm -rf "$APP"

echo
echo "완료: $DEST"
codesign -dv "$DEST" 2>&1 | grep -E "Identifier|Signature" | sed 's/^/  /'
codesign -dv "$DEST/Contents/Frameworks/audio_capture" 2>&1 | grep -E "Identifier" | sed 's/^/  헬퍼 /'

