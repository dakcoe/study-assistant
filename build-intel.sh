#!/bin/bash
# 인텔(x86_64) 맥용 빌드 — Apple Silicon 맥에서 만든다.
#
#   ./build-intel.sh
#
# arm64 빌드(build.sh)와 완전히 따로 돈다. /Applications 에 설치하지 않고
# dist/Study AI (Intel).dmg 만 만든다. 네 맥에서 쓰는 앱은 건드리지 않는다.
#
# 유니버설 한 개로 못 만드는 이유: numpy 2.x는 universal2 휠을 내지 않는다.
# x86_64용과 arm64용을 따로 내므로, 인텔용은 x86_64 파이썬으로 따로 빌드한다.

set -e
cd "$(dirname "$0")"

VENV=".venv-x86"

# ── 1. x86_64 파이썬 (uv가 관리자 권한 없이 받아온다) ────────────────────────
if [ ! -x "$VENV/bin/python" ]; then
    echo "▶ x86_64 파이썬 준비"
    uv venv --python cpython-3.13-macos-x86_64 "$VENV"
    uv pip install --python "$VENV/bin/python" -r requirements.txt pyinstaller
fi

# ── 2. Swift 헬퍼 x86_64 ────────────────────────────────────────────────────
# ScreenCaptureKit 오디오 탭은 macOS 13부터라 타깃을 13으로 잡는다.
if [ ! -f audio_capture_x86 ] || [ audio_capture.swift -nt audio_capture_x86 ]; then
    echo "▶ Swift 헬퍼 (x86_64)"
    swiftc -O -target x86_64-apple-macos13 audio_capture.swift -o audio_capture_x86
fi

# ── 3. 빌드 ────────────────────────────────────────────────────────────────
# spec은 audio_capture 라는 이름만 보므로, 빌드하는 동안만 x86 것으로 바꿔 둔다.
echo "▶ PyInstaller (x86_64)"
cp audio_capture audio_capture.arm64.bak
cp audio_capture_x86 audio_capture
trap 'cp audio_capture.arm64.bak audio_capture; rm -f audio_capture.arm64.bak' EXIT
"$VENV/bin/python" -m PyInstaller --noconfirm --clean \
    --distpath dist-x86 --workpath build-x86 StudyAI.spec >/dev/null 2>&1

APP="dist-x86/Study AI.app"

# ── 4. 한국어 번들 + 서명 ───────────────────────────────────────────────────
mkdir -p "$APP/Contents/Resources/ko.lproj"
cat > "$APP/Contents/Resources/ko.lproj/InfoPlist.strings" <<'STRINGS'
"CFBundleName" = "Study AI";
"CFBundleDisplayName" = "Study AI";
STRINGS
echo "▶ 서명"
codesign -f -s - -i "com.superbleo.studyai.audiocapture" "$APP/Contents/Frameworks/audio_capture"
codesign -f -s - -i "com.superbleo.studyai" --deep "$APP" 2>/dev/null

# ── 5. arm64가 섞여 들어가지 않았는지 확인 ──────────────────────────────────
# 하나라도 arm64 전용이 섞이면 인텔 맥에서 그 모듈을 부를 때 죽는다.
BAD=0
while read -r f; do
    lipo -archs "$f" 2>/dev/null | grep -q x86_64 || { echo "  ✗ x86_64 없음: $f"; BAD=1; }
done < <(find "$APP" \( -name "*.so" -o -name "*.dylib" -o -perm -u+x -type f \) )
[ "$BAD" = "1" ] && { echo "⛔ arm64 전용 파일이 섞였습니다"; exit 1; }
echo "  전부 x86_64 포함"

# ── 6. dmg (안내문까지 make_dmg.sh가 넣는다) ────────────────────────────────
./make_dmg.sh --intel
