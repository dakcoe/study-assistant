"""앱 아이콘 생성기 — macOS 규격(스퀘어클)으로 깎아 icns/ico를 만든다.

    .venv/bin/python tools/icon/make_icon.py

macOS는 iOS와 달리 앱 아이콘을 자동으로 깎아 주지 않는다. 정사각형 그림을
그대로 넣으면 독에서 혼자 각져 보인다(실제로 그런 말을 들었다). 그래서
애플 규격대로 직접 만든다.

  캔버스 1024 × 1024, 바깥은 투명
  본체   824 × 824 가운데 정렬  (캔버스의 80.5%)
  모서리 연속 곡선(초타원) — 단순 둥근 사각형보다 애플 것에 가깝다

원본 그림(icon_source.png)에서 잉크 부분만 잘라내 본체 안에 다시 앉힌다.
원본 여백이 얼마든 결과가 같은 비율로 나온다.
"""

import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SOURCE = os.path.join(HERE, "icon_source.png")

S      = 1024                  # 캔버스
BODY   = 824                   # 본체 (애플 규격)
INK    = 0.62                  # 본체 대비 그림이 차지할 비율
N      = 5.0                   # 초타원 지수. 4~5가 애플 모서리에 가깝다
SS     = 4                     # 마스크를 4배로 그려 줄여서 계단을 없앤다


def squircle(size):
    """연속 곡선 모서리 마스크. |x|^n + |y|^n = 1 안쪽을 채운다."""
    big = size * SS
    mask = Image.new("L", (big, big), 0)
    px = mask.load()
    half = big / 2
    for y in range(big):
        ny = abs((y + 0.5 - half) / half)
        if ny > 1:
            continue
        # x^n = 1 - y^n  →  경계 x
        limit = (1 - ny ** N) ** (1 / N)
        x0 = int(half - limit * half)
        x1 = int(half + limit * half)
        for x in range(x0, x1):
            px[x, y] = 255
    return mask.resize((size, size), Image.LANCZOS)


def ink_of(img):
    """그림에서 배경(흰색)을 뺀 알맹이만 잘라낸다."""
    rgb = img.convert("RGB")
    bg = rgb.getpixel((1, 1))
    diff = Image.new("L", img.size, 0)
    d = diff.load()
    src = rgb.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = src[x, y]
            if abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) > 24:
                d[x, y] = 255
    box = diff.getbbox()
    return img.crop(box) if box else img


def build():
    src = Image.open(SOURCE).convert("RGBA")
    ink = ink_of(src)

    # 본체 — 흰 타일에 스퀘어클 모양으로 구멍을 낸다
    body = Image.new("RGBA", (BODY, BODY), (255, 255, 255, 255))
    body.putalpha(squircle(BODY))

    # 그림을 본체 안에 앉힌다. 가로세로 중 긴 쪽을 기준으로 맞춘다.
    target = int(BODY * INK)
    w, h = ink.size
    scale = target / max(w, h)
    ink = ink.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    body.alpha_composite(ink, ((BODY - ink.width) // 2, (BODY - ink.height) // 2))

    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    off = (S - BODY) // 2
    # 옅은 그림자 — 밝은 배경에서 타일 경계가 보이게 한다
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 60), (off, off + 10), squircle(BODY))
    icon.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    icon.alpha_composite(body, (off, off))
    return icon


def main():
    icon = build()
    icon.save(os.path.join(HERE, "AppIcon.png"))            # 미리보기

    # ── macOS .icns ─────────────────────────────────────────────────────────
    iconset = os.path.join(HERE, "AppIcon.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = size * scale
            name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
            icon.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
    out = os.path.join(ROOT, "assets", "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
    shutil.rmtree(iconset, ignore_errors=True)

    # ── Windows .ico ────────────────────────────────────────────────────────
    icon.save(os.path.join(ROOT, "assets", "AppIcon.ico"),
              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    print("만듦: assets/AppIcon.icns · assets/AppIcon.ico · tools/icon/AppIcon.png")


if __name__ == "__main__":
    sys.exit(main())
