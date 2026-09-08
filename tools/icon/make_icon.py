"""앱 아이콘(AppIcon.icns) 생성기.

    .venv/bin/python tools/icon/make_icon.py      # icon_source.png 를 변환
    .venv/bin/python make_icon.py 어떤그림.png    # 지정한 그림을 변환
    .venv/bin/python make_icon.py --draw         # 코드로 그린 기본 아이콘 사용

원본 그림이 있으면 그걸 쓰고, 없으면 마이크 도형을 직접 그린다.
"""

import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw

S       = 1024                      # icns 최대 크기
ACCENT  = (16, 185, 129, 255)       # #10b981
WHITE   = (255, 255, 255, 255)
PAD     = int(S * 0.09)
RADIUS  = int(S * 0.225)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(HERE, "icon_source.png")


def draw_icon():
    """원본 그림이 없을 때 쓰는 기본 아이콘 — 초록 바탕에 흰 마이크."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((PAD, PAD, S - PAD, S - PAD), radius=RADIUS, fill=ACCENT)

    cx = S // 2
    cap_w, cap_h, cap_top = int(S * 0.20), int(S * 0.34), int(S * 0.27)
    d.rounded_rectangle((cx - cap_w // 2, cap_top, cx + cap_w // 2, cap_top + cap_h),
                        radius=cap_w // 2, fill=WHITE)
    arc_w = int(S * 0.33)
    arc_top = cap_top + int(cap_h * 0.42)
    arc_bot = arc_top + int(S * 0.30)
    d.arc((cx - arc_w // 2, arc_top, cx + arc_w // 2, arc_bot),
          start=0, end=180, fill=WHITE, width=int(S * 0.045))
    stand_top = arc_bot - int(S * 0.02)
    stand_bot = stand_top + int(S * 0.10)
    d.line((cx, stand_top, cx, stand_bot), fill=WHITE, width=int(S * 0.045))
    foot_w = int(S * 0.17)
    d.line((cx - foot_w // 2, stand_bot, cx + foot_w // 2, stand_bot),
           fill=WHITE, width=int(S * 0.045))
    return img


def load_source(path):
    img = Image.open(path).convert("RGBA")
    if img.size != (S, S):
        # 정사각형이 아니면 긴 쪽에 맞춰 가운데 정렬
        side = max(img.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
        img = canvas.resize((S, S), Image.LANCZOS)
    return img


def build_icns(img):
    iconset = os.path.join(HERE, "AppIcon.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        img.resize((size, size), Image.LANCZOS).save(
            os.path.join(iconset, f"icon_{size}x{size}.png"))
        img.resize((size * 2, size * 2), Image.LANCZOS).save(
            os.path.join(iconset, f"icon_{size}x{size}@2x.png"))
    # 빌드(StudyAI.spec)가 읽는 자리로 바로 내보낸다
    out = os.path.join(HERE, "..", "..", "assets", "AppIcon.icns")
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", out], check=True)
    shutil.rmtree(iconset, ignore_errors=True)
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--draw"]
    if "--draw" in sys.argv:
        icon, src = draw_icon(), "(코드로 그림)"
    else:
        src = args[0] if args else DEFAULT_SOURCE
        if not os.path.exists(src):
            sys.exit(f"원본 그림이 없습니다: {src}\n"
                     f"--draw 를 주면 기본 아이콘을 그립니다.")
        icon, src = load_source(src), src

    icon.save(os.path.join(HERE, "AppIcon.png"))     # 미리보기용
    path = build_icns(icon)
    print(f"원본: {src}")
    print(f"생성: {path}  ({os.path.getsize(path):,} bytes)")
