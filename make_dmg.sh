#!/bin/bash
# 배포용 DMG 생성.
#
#   ./make_dmg.sh          현재 /Applications 에 설치된 빌드(Apple Silicon)로 DMG
#   ./make_dmg.sh --build  먼저 build.sh 로 새로 빌드한 뒤 DMG
#   ./make_dmg.sh --intel  dist-x86 의 인텔 빌드로 DMG (build-intel.sh가 부른다)
#
# 주의: ad-hoc 서명이라 받는 사람 쪽에서 Gatekeeper에 막힌다. 그래서 DMG 안에
# 안내문(읽어주세요.txt)을 같이 넣는다. 이 경고를 없애려면 Apple Developer
# Program의 Developer ID 인증서로 서명하고 공증(notarization)을 받아야 한다.

set -e
cd "$(dirname "$0")"

NAME="Study AI"
VERSION="1.0.0"
STAGE="$(mktemp -d)"
mkdir -p dist

if [ "$1" = "--intel" ]; then
    SRC="dist-x86/$NAME.app"
    OUT="dist/$NAME $VERSION (Intel).dmg"
    NEED="- 인텔 맥 전용입니다. Apple Silicon(M1 이상) 맥에서는 다른 파일을 쓰세요."
else
    [ "$1" = "--build" ] && ./build.sh
    SRC="/Applications/$NAME.app"
    OUT="dist/$NAME $VERSION.dmg"
    NEED="- Apple Silicon(M1 이상) 맥 전용입니다. 인텔 맥에서는 다른 파일을 쓰세요."
fi

if [ ! -d "$SRC" ]; then
    echo "빌드가 없습니다: $SRC"
    [ "$1" = "--intel" ] && echo "먼저 ./build-intel.sh 를 실행하세요." \
                         || echo "먼저 ./build.sh 를 실행하거나 --build 를 붙이세요."
    exit 1
fi

echo "▶ 스테이징"
cp -R "$SRC" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

cat > "$STAGE/읽어주세요.txt" <<TXT
Study AI 설치 방법
==================

■ 1단계 — 반드시 Applications 폴더로 옮기세요

   왼쪽의 "Study AI" 를 오른쪽 Applications 폴더로 끌어다 놓으세요.

   이 창(디스크 이미지) 안에서 바로 실행하면 안 됩니다. 읽기 전용이라
   보안 승인이 저장되지 않아서, 열 때마다 매번 차단 경고가 나옵니다.


■ 2단계 — 터미널에서 아래 한 줄을 실행하세요 (한 번만)

   xattr -cr "/Applications/Study AI.app"

   인터넷에서 받은 파일에 붙는 격리 표식을 지우는 명령입니다. 이걸 실행하면
   그 뒤로는 경고 없이 그냥 열립니다.

   터미널은 Spotlight(Command+스페이스)에서 "터미널"로 찾을 수 있습니다.
   위 줄을 복사해 붙여넣고 엔터를 누르면 됩니다.

   ※ 이 과정이 필요한 이유: Apple 개발자 인증서로 서명하지 않은 앱이라
     macOS가 출처를 확인할 수 없다고 판단합니다. 앱 자체의 문제는 아닙니다.

   2단계를 건너뛰면 "확인되지 않은 개발자" 또는 "손상되었기 때문에 열 수
   없습니다" 경고가 계속 나옵니다. 그때는 우클릭 → 열기 → 다시 열기, 또는
   시스템 설정 → 개인정보 보호 및 보안 → 아래쪽 "확인 없이 열기" 를
   눌러야 하는데, 매번 반복해야 하므로 2단계를 하시는 편이 훨씬 낫습니다.


■ 3단계 — Groq API 키 넣기 (무료, 10초)

   실행하면 API 키를 입력하라고 합니다. 카드 등록이 필요 없습니다.

   1) https://console.groq.com/keys  접속해서 로그인
   2) 오른쪽 위 [+ Create API Key] 누르기
   3) 이름은 아무거나, 만료(Expiration)는 그대로 두고 [Submit]
   4) 만들어진 키를 복사
   5) 앱의 톱니 버튼 -> API 키 칸에 붙여넣고 [확인]

   한도를 넘어도 요금이 청구되지 않고 잠시 요청이 거부될 뿐입니다.


■ 권한

   음성을 받아 적을 때 마이크 권한을, 앱 소리(유튜브·강의 영상 등)를 받아
   적을 때 화면 기록 권한을 물어봅니다. 화면 기록이라는 이름과 달리 화면은
   저장하지 않고 소리만 가져옵니다.


■ 요구 사항

   $NEED
   - macOS 13 이상 (앱별 소리 받아 적기는 macOS 15 이상)
   - 인터넷 연결 (AI 채팅과 음성 인식이 모두 서버를 거칩니다)


자세한 사용법은 앱 안의 ? 버튼을 누르면 나옵니다.
TXT

# 따로 보낼 일이 있으니 같은 안내문을 dist에도 둔다 (내용이 어긋나지 않게)
cp "$STAGE/읽어주세요.txt" "dist/설치 안내.txt"

echo "▶ DMG 생성"
rm -f "$OUT"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO \
               -imagekey zlib-level=9 "$OUT" >/dev/null
rm -rf "$STAGE"

echo
echo "완료: $OUT  ($(du -h "$OUT" | cut -f1))"
