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

sed "s|{NEED}|$NEED|" packaging/읽어주세요-mac.txt > "$STAGE/읽어주세요.txt"

# 따로 보낼 일이 있으니 같은 안내문을 dist에도 둔다 (내용이 어긋나지 않게)
cp "$STAGE/읽어주세요.txt" "dist/설치 안내.txt"

echo "▶ DMG 생성"
rm -f "$OUT"
hdiutil create -volname "$NAME" -srcfolder "$STAGE" -ov -format UDZO \
               -imagekey zlib-level=9 "$OUT" >/dev/null
rm -rf "$STAGE"

echo
echo "완료: $OUT  ($(du -h "$OUT" | cut -f1))"
