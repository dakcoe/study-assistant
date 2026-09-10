"""Study AI — 받아적기·번역 노트와 Groq LLM 채팅.

창은 둘이다. NotesWindow가 본체(받아적기)이고 StudyAssistant가 채팅 창이다.
Tk의 루트는 StudyAssistant라 앱 상태(큐, STT, 설정 창)를 그쪽이 들고 있다.

플랫폼에 따라 갈리는 곳은 config.WINDOWS 로 나눈다 — 최전면 앱 감지, 클립보드,
아이콘 폰트 등록, 단축키, 링크 열기.
"""

import logging
import math
import os
import queue
import re
import ctypes
import ctypes.util
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import unicodedata
from tkinter import filedialog, messagebox
from datetime import datetime

logging.getLogger("root").setLevel(logging.CRITICAL)

import customtkinter as ctk

import config
import groq_client
import stt_engine
from stt_engine import STTEngine, STTState

FONT_UI   = "Apple SD Gothic Neo"
FONT_MONO = "Menlo"

# ── 디자인 토큰 ──────────────────────────────────────────────────────────────
# 값이 늘어나면 위계가 흐려진다. 한때 글자 크기가 11~20까지 10종, 간격이 9종,
# 모서리 반경이 5종이었는데 어느 것이 어느 위계인지 규칙이 없었다(같은 줄에서
# Save note는 13pt, 바로 옆 상태 라벨은 14pt였다). 새 값이 필요하면 눈대중으로
# 적지 말고 여기에 먼저 넣는다.
FS_CAPTION = 12     # 라벨, 캡션, 보조 설명
FS_BODY    = 14     # 본문, 버튼, 입력
FS_TITLE   = 17     # 창 제목, h2
FS_DISPLAY = 20     # 도움말 표제, h1
FS_CODE    = 12     # 고정폭 (코드, 표)

SP_HAIR    = 1      # 한 덩어리로 읽혀야 하는 것 사이 (한도 막대 두 줄)
SP_TIGHT   = 4      # 붙어 있는 것 사이
SP_SNUG    = 8      # 라벨과 컨트롤 사이
SP_ITEM    = 16     # 항목 사이, 창 바깥 여백
SP_SECTION = 24     # 구역 사이

R_CONTROL  = 8      # 누르는 것 (버튼, 드롭다운, 입력)
R_PANEL    = 16     # 담는 것 (프레임, 텍스트박스)

# ── 테마 팔레트 ──────────────────────────────────────────────────────────────
THEMES = {
    "light": {
        "ctk_mode":        "light",
        "ctk_theme":       "green",
        "app_bg":          "#f2f4f7",
        "panel_bg":        "#ffffff",
        "input_bg":        "#f8fafc",
        "text_primary":    "#333333",
        "text_muted":      "#565f6d",
        # accent는 버튼 채우기 전용이다. 그 위에는 흰 글씨가 올라가므로 이대로 맞다.
        # 밝은 배경 위 텍스트로 쓰면 대비가 무너진다(흰 배경 대비 2.54). 그래서
        # trans_text / status_* 는 accent와 같은 초록 계열이되 따로 진하게 잡았다.
        # 다크·네온은 배경이 어두워 같은 문제가 없다.
        "accent":          "#10b981",
        "accent_hover":    "#059669",
        "btn_sec_bg":      "#e2e8f0",
        "btn_sec_hover":   "#cbd5e1",
        "btn_sec_text":    "#333333",
        "seg_selected":    "#10b981",
        "seg_hover":       "#059669",
        "code_bg":         "#f1f5f9",
        "code_text":       "#0f766e",
        "user_label":      "#065f46",
        "ai_label":        "#0b7a75",
        "error_text":      "#dc2626",
        "trans_text":      "#047857",
        # 녹음 버튼은 채운 원이고 그 위에 흰 아이콘이 올라간다
        "mic_rec_fill":    "#dc2626",
        "status_idle":     "#565f6d",
        "status_listen":   "#047857",
        "status_process":  "#8a5a00",
        "clip_bg":         "#fef08a",
        "clip_text":       "#854d0e",
    },
    "dark": {
        "ctk_mode":        "dark",
        "ctk_theme":       "blue",
        "app_bg":          "#242424",
        "panel_bg":        "#2b2b2b",
        "input_bg":        "#1e1e1e",
        "text_primary":    "#d4d4d4",
        "text_muted":      "#a1a1aa",
        "accent":          "#1f538d",
        "accent_hover":    "#14375e",
        "btn_sec_bg":      "#3b3b3b",
        "btn_sec_hover":   "#4a4a4a",
        "btn_sec_text":    "#d4d4d4",
        "seg_selected":    "#1f538d",
        "seg_hover":       "#14375e",
        "code_bg":         "#1a1a1a",
        "code_text":       "#6ee7b7",
        "user_label":      "#60a5fa",
        "ai_label":        "#6ee7b7",
        "error_text":      "#f87171",
        "trans_text":      "#6ee7b7",
        "mic_rec_fill":    "#b91c1c",
        "status_idle":     "#a1a1aa",
        "status_listen":   "#6ee7b7",
        "status_process":  "#fbbf24",
        "clip_bg":         "#3b3b3b",
        "clip_text":       "#d4d4d4",
    },
    "neon": {
        "ctk_mode":        "dark",
        "ctk_theme":       "blue",
        "app_bg":          "#0b0f19",
        "panel_bg":        "#151b2b",
        "input_bg":        "#0f1423",
        "text_primary":    "#e2e8f0",
        "text_muted":      "#a5b4fc",
        "accent":          "#8b5cf6",
        "accent_hover":    "#7c3aed",
        "btn_sec_bg":      "#3730a3",
        "btn_sec_hover":   "#4338ca",
        "btn_sec_text":    "#e0e7ff",
        "seg_selected":    "#8b5cf6",
        "seg_hover":       "#7c3aed",
        "code_bg":         "#1e293b",
        "code_text":       "#a78bfa",
        "user_label":      "#a5b4fc",
        "ai_label":        "#f472b6",
        "error_text":      "#f87171",
        "trans_text":      "#f472b6",
        "mic_rec_fill":    "#e11d48",
        "status_idle":     "#a5b4fc",
        "status_listen":   "#a5b4fc",
        "status_process":  "#f472b6",
        "clip_bg":         "#1e293b",
        "clip_text":       "#a5b4fc",
    },
}

_theme_name = config.get("theme") if config.get("theme") in THEMES else "light"
ctk.set_appearance_mode(THEMES[_theme_name]["ctk_mode"])
ctk.set_default_color_theme(THEMES[_theme_name]["ctk_theme"])

# 반경은 위젯마다 인자로 넘기지 않고 CTk 기본값을 한 번 갈아끼운다. 인자를 주지
# 않은 위젯(버튼·드롭다운·세그먼트의 기본 6)까지 한꺼번에 맞춰진다.
for _w in ("CTkButton", "CTkOptionMenu", "CTkSegmentedButton",
           "CTkEntry", "CTkSwitch", "CTkProgressBar"):
    ctk.ThemeManager.theme[_w]["corner_radius"] = R_CONTROL
for _w in ("CTkFrame", "CTkTextbox", "CTkScrollableFrame"):
    ctk.ThemeManager.theme[_w]["corner_radius"] = R_PANEL

# 터미널/에디터에서 복사한 코드는 자동 캡처하지 않는다
EXCLUDED_APPS = {
    "terminal", "iterm2", "warp", "ghostty", "alacritty", "kitty", "hyper",
    "code", "cursor", "pycharm", "python", "python3",
}

_FRONT_APP_SCRIPT = (
    'tell application "System Events" to get name of '
    'first application process whose frontmost is true'
)


def _log_error(msg):
    """.app으로 실행하면 stderr가 어디에도 안 보이므로 파일에 남긴다."""
    try:
        with open(os.path.join(config.APP_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{msg}\n")
    except Exception:
        pass


def _get_foreground_app():
    """최전면 앱 이름(소문자). 권한이 없거나 실패하면 빈 문자열."""
    if config.WINDOWS:
        # 창 제목이 아니라 실행 파일 이름을 본다. 제목은 문서 이름이 섞여 들쭉날쭉하다.
        try:
            import ctypes
            from ctypes import wintypes
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(user32.GetForegroundWindow(),
                                            ctypes.byref(pid))
            PROCESS_QUERY_LIMITED = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(len(buf))
                if not kernel32.QueryFullProcessImageNameW(h, 0, buf,
                                                           ctypes.byref(size)):
                    return ""
                return os.path.splitext(os.path.basename(buf.value))[0].lower()
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            return ""
    try:
        r = subprocess.run(
            ["osascript", "-e", _FRONT_APP_SCRIPT],
            capture_output=True, text=True, timeout=2,
        )
        return r.stdout.strip().lower()
    except Exception:
        return ""


def _clipboard_text(widget=None):
    """클립보드 글자. 못 읽으면 빈 문자열.

    Windows에는 pbpaste가 없어 Tk로 읽는다. Tk의 clipboard_get은 클립보드가
    비었거나 그림일 때 예외를 던지므로 감싼다.
    """
    if config.WINDOWS:
        try:
            return widget.clipboard_get() if widget is not None else ""
        except Exception:
            return ""
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
        return r.stdout
    except Exception:
        return ""


# ── 마크다운 렌더러 ──────────────────────────────────────────────────────────

# ── 표 ───────────────────────────────────────────────────────────────────────
# tkinter Text에는 표 위젯이 없어서 고정폭 글꼴로 칸을 맞춰 그린다. 다만 셀에 긴
# 설명이 들어가면 정렬해도 자동 줄바꿈에 깨지므로, 폭이 넘치면 행 단위 블록으로
# 바꿔 그린다.
MAX_TABLE_COLS = 64          # 이 표시폭을 넘으면 블록 형태로 전환

_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def _is_table_row(line):
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _split_row(line):
    s = line.strip().strip("|")
    return [_cell_text(c) for c in s.split("|")]


def _cell_text(cell):
    cell = re.sub(r"<br\s*/?>", " ", cell, flags=re.I)
    cell = cell.replace("**", "").replace("`", "").replace("•", "·")
    return " ".join(cell.split())


def _dwidth(s):
    """한글·한자는 고정폭 글꼴에서 두 칸을 차지한다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s, width):
    return s + " " * max(0, width - _dwidth(s))


def _render_table(widget, rows):
    header, body = rows[0], rows[1:]
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    header, body = rows[0], rows[1:]

    widths = [max(_dwidth(r[i]) for r in rows) for i in range(ncol)]
    total = sum(widths) + 3 * (ncol - 1)

    if total <= MAX_TABLE_COLS:
        line = "  ".join(_pad(header[i], widths[i]) for i in range(ncol))
        widget.insert("end", line.rstrip() + "\n", "table_head")
        widget.insert("end", "─" * min(total, MAX_TABLE_COLS) + "\n", "table")
        for r in body:
            line = "  ".join(_pad(r[i], widths[i]) for i in range(ncol))
            widget.insert("end", line.rstrip() + "\n", "table")
        widget.insert("end", "\n")
        return

    # 너무 넓다 — 행마다 블록으로
    for r in body:
        widget.insert("end", r[0] + "\n", "table_head")
        for i in range(1, ncol):
            if r[i]:
                widget.insert("end", f"   {header[i]}: ", "table_head")
                widget.insert("end", r[i] + "\n", "bullet")
        widget.insert("end", "\n")


# Tk는 이미지 객체의 참조가 사라지면 그림을 지운다. 위젯에 달아 붙들어 둔다.
def _insert_image(widget, name, width):
    path = _asset(os.path.join("assets", name))
    if not os.path.exists(path):
        return
    try:
        from PIL import Image, ImageTk
        im = Image.open(path)
        # Retina에서 흐려지지 않게 2배로 그린 뒤 Tk에 논리 크기를 알려준다.
        scale = 2
        im = im.resize((width * scale, round(im.height * width * scale / im.width)),
                       Image.LANCZOS)
        photo = ImageTk.PhotoImage(im)
        photo = photo._PhotoImage__photo.subsample(scale)
    except Exception:
        return
    keep = getattr(widget, "_kept_images", None)
    if keep is None:
        keep = widget._kept_images = []
    keep.append(photo)
    # 번호 목록 아래 오므로 그 들여쓰기에 맞춘다. 왼쪽에 딱 붙으면 단이 어긋난다.
    start = widget.index("end-1c")
    widget.image_create("end", image=photo, padx=SP_SNUG, pady=SP_TIGHT)
    widget.insert("end", "\n")
    widget.tag_add("figure", start, "end-1c")
    widget.tag_config("figure", lmargin1=SP_SECTION, lmargin2=SP_SECTION)


def render_markdown(widget, text):
    if hasattr(widget, "_textbox"):
        widget = widget._textbox
    in_code = False
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if not in_code and _is_table_row(line):
            block = []
            while i < len(lines) and _is_table_row(lines[i]):
                if not _TABLE_SEP_RE.match(lines[i]):     # |---|---| 구분선은 버린다
                    block.append(_split_row(lines[i]))
                i += 1
            if len(block) >= 2:
                _render_table(widget, block)
                continue
            for r in block:                               # 표가 아니면 원래대로
                _inline(widget, " | ".join(r) + "\n")
            continue

        i += 1
        if line.startswith("```"):
            in_code = not in_code
            # 코드 블록 배경이 spacing1/spacing3까지 칠해져서 앞뒤 문단에 붙어
            # 보인다. 위아래로 빈 줄을 하나씩 넣어 띄운다.
            widget.insert("end", "\n")
            continue
        # 빈 줄은 버린다. 문단 사이 간격은 spacing1/spacing3이 이미 만든다.
        # 빈 줄까지 넣으면 한 줄 높이가 더 붙어 간격이 두 배로 벌어진다.
        if not in_code and not line.strip():
            continue
        if in_code:
            # 코드 블록은 줄 전체가 하나의 값이다. 경로에 공백이 있어도
            # (~/Library/Application Support/…) 통째로 잡으려면 여기서 봐야 한다.
            if line.strip().startswith(("~/", "/")):
                widget.insert("end", line, ("code_block", "link"))
                widget.insert("end", "\n", ("code_block",))
            else:
                _insert_linked(widget, line + "\n", ("code_block",))
            continue
        if line.startswith("!["):
            # ![설명](파일.png){폭}  — 폭은 화면에 그릴 논리 픽셀
            m = re.match(r"!\[[^\]]*\]\(([^)]+)\)(?:\{(\d+)\})?", line)
            if m:
                _insert_image(widget, m.group(1), int(m.group(2) or 320))
            continue
        if line.startswith("### "):
            widget.insert("end", line[4:] + "\n", "h3")
        elif line.startswith("## "):
            widget.insert("end", line[3:] + "\n", "h2")
        elif line.startswith("# "):
            widget.insert("end", line[2:] + "\n", "h1")
        elif re.match(r"^[-*] ", line):
            _inline(widget, "• " + line[2:] + "\n", "bullet")
        elif re.match(r"^ {2,4}[-*] ", line):
            _inline(widget, "  ◦ " + line.lstrip(" -*") + "\n", "bullet")
        elif re.match(r"^\d+\. ", line):
            _inline(widget, line + "\n", "bullet")
        else:
            _inline(widget, line + "\n")


# 눌러서 열 수 있는 것 — 주소와 ~ 로 시작하는 경로.
# 링크마다 태그를 따로 만들면 채팅이 조각마다 다시 그려질 때 태그가 끝없이
# 쌓인다. 태그는 "link" 하나만 쓰고, 누른 자리의 글자를 읽어 대상을 정한다.
_LINK_RE = re.compile(
    r"""(https?://[^\s`"'<>]+
       | (?:[\w-]+\.)+(?:com|net|org|io|ai|dev|app|kr)(?:/[^\s`"'<>]*)?
       | ~/[^\s`"'<>]+)""", re.VERBOSE)


def _open_target(text):
    """주소는 브라우저로, 경로는 Finder로 연다. 그 외에는 아무것도 안 한다."""
    text = text.strip().rstrip(".,)]}")
    if text.startswith("~") or text.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", text):
        path = os.path.expanduser(text)
        if os.path.exists(path):
            _open_with_os(path)
        return
    # 스킴이 붙어 있으면 http(s)만 연다. javascript:, file: 같은 건 "://"가
    # 없어서 그냥 두면 앞에 https를 붙여 열어버린다.
    scheme = re.match(r"([a-zA-Z][a-zA-Z0-9+.\-]*):", text)
    if scheme and scheme.group(1).lower() not in ("http", "https"):
        return
    url = text if text.startswith("http") else "https://" + text
    _open_with_os(url)


def _open_with_os(target):
    """탐색기·브라우저에 넘긴다."""
    if config.WINDOWS:
        try:
            os.startfile(target)            # 주소도 경로도 같은 함수로 열린다
        except OSError:
            pass
        return
    subprocess.run(["open", target], check=False)


def _on_link_click(event):
    widget = event.widget
    rng = widget.tag_prevrange("link", widget.index(f"@{event.x},{event.y}") + "+1c")
    if rng:
        _open_target(widget.get(*rng))


def _config_link_tag(ttb, t):
    """링크 모양과 동작. 위젯마다 한 번만 걸면 된다."""
    ttb.tag_config("link", foreground=t["ai_label"], underline=True)
    ttb.tag_bind("link", "<Button-1>", _on_link_click)
    ttb.tag_bind("link", "<Enter>", lambda e: e.widget.configure(cursor="pointinghand"))
    ttb.tag_bind("link", "<Leave>", lambda e: e.widget.configure(cursor=""))


def _inline(widget, text, base=None):
    for p in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if p.startswith("**") and p.endswith("**") and len(p) > 4:
            tags = ("bold", base) if base else ("bold",)
            widget.insert("end", p[2:-2], tags)
        elif p.startswith("`") and p.endswith("`") and len(p) > 2:
            _insert_linked(widget, p[1:-1], ("code",))
        else:
            _insert_linked(widget, p, (base,) if base else ())


def _insert_linked(widget, text, tags):
    """주소·경로만 link 태그를 얹어 넣는다."""
    pos = 0
    for m in _LINK_RE.finditer(text):
        if m.start() > pos:
            widget.insert("end", text[pos:m.start()], tags)
        widget.insert("end", m.group(0), tags + ("link",))
        pos = m.end()
    if pos < len(text):
        widget.insert("end", text[pos:], tags)


def _clean_trans(text):
    return re.sub(r'^(?:교정|번역)\s*:\s*', '', text.strip())


# 번역이 엉뚱한 언어로 나오는 일이 있다 — 한국어로 시켰는데 "本课程"처럼 중국어
# 낱말이 섞이거나, 갑자기 러시아어가 튀어나오기도 한다. 지시문에 규칙을 늘 붙이면
# 매 호출 토큰이 늘지만 효과는 확인되지 않았다(38줄 돌려도 재현 안 됨). 그래서
# 나왔을 때만 다시 부른다 — 깨끗하면 추가 비용이 0이다.
#
# 목표 언어에 맞는 문자만 허용한다. 로마자와 숫자·기호는 어느 언어에서나
# 정상이다(LMS, TCP 같은 약어). 여기 없는 문자 체계는 전부 잘못 나온 것으로 본다.
_SCRIPTS = {
    "hangul":     ((0xAC00, 0xD7A3), (0x1100, 0x11FF), (0x3130, 0x318F)),
    "kana":       ((0x3040, 0x30FF), (0x31F0, 0x31FF)),
    "han":        ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF)),
    "cyrillic":   ((0x0400, 0x04FF),),
    "greek":      ((0x0370, 0x03FF),),
    "arabic":     ((0x0600, 0x06FF),),
    "hebrew":     ((0x0590, 0x05FF),),
    "thai":       ((0x0E00, 0x0E7F),),
    "devanagari": ((0x0900, 0x097F),),
}
# 일본어는 한자를 정상으로 쓴다. 한국어는 한글만 쓴다. 영어는 로마자뿐이다.
_ALLOWED = {"ko": {"hangul"}, "ja": {"kana", "han"}, "en": set()}


def _script_of(ch):
    code = ord(ch)
    for name, ranges in _SCRIPTS.items():
        if any(lo <= code <= hi for lo, hi in ranges):
            return name
    return None                     # 로마자·숫자·기호 — 어느 언어에서나 정상


def off_script(text, lang, source=""):
    """목표 언어에 없는 문자만 골라 돌려준다. 없으면 빈 문자열.

    원문에 있던 글자는 빼고 본다. 영어 강의에 일본어 인용이 섞여 있으면
    번역에도 그대로 남는 게 맞지, 다시 부를 일이 아니다.
    """
    allowed = _ALLOWED.get(lang)
    if allowed is None:
        return ""                   # 모르는 언어는 검사하지 않는다
    seen = set(source)
    bad = []
    for ch in text:
        if ch in seen:
            continue
        script = _script_of(ch)
        if script and script not in allowed:    # None이면 로마자·숫자·기호
            bad.append(ch)
    return "".join(dict.fromkeys(bad))


def off_script_runs(text, lang, source=""):
    """잘못 나온 문자만 이어붙은 조각으로 끊어 돌려준다. 중복은 뺀다."""
    bad = set(off_script(text, lang, source))
    runs, cur = [], []
    for ch in text:
        if ch in bad:
            cur.append(ch)
        elif cur:
            runs.append("".join(cur)); cur = []
    if cur:
        runs.append("".join(cur))
    return list(dict.fromkeys(runs))


# 문장 전체를 다시 번역하면 잘 된 부분까지 새로 뽑느라 토큰이 그만큼 더 든다.
# 섞여 나온 조각만 옮겨 제자리에 끼워 넣는 편이 싸고, 나머지 번역이 보존된다.
# (dev-news 프로젝트에서 쓰던 방식이다.)
FIX_PROMPT = """다음 {name} 문장에 다른 언어 문자가 잘못 섞였다. 나열된 조각만 {name}로 옮겨라.
한자는 한국 한자음 독음으로 옮겨라 (超越=초월, 金融=금융). 독음이 어색하면 뜻으로 옮겨라.
형식은 한 줄에 하나, `원문=번역`. 다른 말은 쓰지 마라.

문장: {context}

조각:
{words}"""


def strict_language(lang):
    """다시 부를 때 붙이는 한 줄."""
    name = config.LANG_NAMES.get(lang, lang)
    return (f" Output ONLY {name}. Do not use any other language or writing "
            f"system, not even for technical terms.")


def prune_autosave(keep_days=None, now=None):
    """오래된 자동 저장 파일을 지운다. 지운 개수를 돌려준다.

    되찾으려고 남기는 파일이라 한 달이면 충분하다. 지우는 장치가 없으면
    강의를 받아적을수록 계속 쌓인다.

    지우는 범위를 좁게 잡는다 — autosave 폴더 바로 아래의 .txt만 본다.
    하위 폴더로 내려가지 않고, 손으로 저장한 메모(사용자가 고른 위치)는
    건드리지 않는다.
    """
    days = config.AUTOSAVE_KEEP_DAYS if keep_days is None else keep_days
    if not days:
        return 0
    folder = os.path.join(config.NOTES_DIR, "autosave")
    cutoff = (now or time.time()) - days * 86400
    removed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        path = os.path.join(folder, name)
        if not name.endswith(".txt") or not os.path.isfile(path):
            continue
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass            # 못 지워도 앱은 계속 떠야 한다
    return removed


def _lang_name(code):
    """프롬프트에 넣을 언어 이름.

    응답 언어는 셋뿐이라 영어 이름이 있다. 원문 언어는 Whisper가 받는 100개라
    이름을 다 두지 않고 ISO 코드를 그대로 넘긴다 — 모델이 알아듣는다.
    """
    return config.LANG_NAMES.get(code, code)


def _est_tokens(text):
    """토큰 수 어림. 언제 묶어 보낼지 정하는 기준일 뿐이라 정확할 필요는 없다.

    비율은 qwen3.6-27b 토크나이저로 직접 재서 맞췄다. 짧은 받아적기 조각
    기준으로 영어는 5글자에 1토큰, 가나·한자는 글자당 0.57토큰꼴이다.
    (gpt-oss와의 차이는 1.6%라 모델별로 나누지 않는다.)
    처음엔 영어 4글자/토큰으로 잡았다가 23% 과다로 나와 고쳤다.
    """
    cjk = sum(1 for ch in text if "\u3040" <= ch <= "\u9fff")
    return max(1, (cjk * 4) // 7 + (len(text) - cjk) // 5)


# 한글 입력 상태에서 Cmd+C는 keysym이 'ㅊ'로 들어와 <Command-c> 바인딩이 걸리지
# 않는다. 그래서 글자가 아니라 키의 물리적 위치(가상 키코드)로 판별한다.
# macOS: Tk가 keycode를 (가상키코드 << 24 | 문자코드)로 준다.
# Windows: keycode가 곧 Virtual-Key Code다 (A=65 …).
if config.WINDOWS:
    MOD_KEY = "Control"
    MOD_NAME = "Ctrl"
    VKEY_A, VKEY_Z, VKEY_X, VKEY_C, VKEY_V = 65, 90, 88, 67, 86

    def _vkey(event):
        return event.keycode
else:
    MOD_KEY = "Command"
    MOD_NAME = "Cmd"
    VKEY_A, VKEY_Z, VKEY_X, VKEY_C, VKEY_V = 0, 6, 7, 8, 9

    def _vkey(event):
        return (event.keycode >> 24) & 0xFF


def _editable(widget):
    """편집 가능한 내부 Text 위젯이면 반환, 아니면 None."""
    if widget is None:
        return None
    tb = getattr(widget, "_textbox", widget)
    if not isinstance(tb, tk.Text):
        return None
    return tb if str(tb.cget("state")) != "disabled" else None


def _paste_into(widget):
    tb = _editable(widget)
    if tb is None:
        return "break"
    try:
        text = tb.clipboard_get()
    except tk.TclError:
        return "break"
    try:
        tb.delete("sel.first", "sel.last")
    except tk.TclError:
        pass
    tb.insert("insert", text)
    return "break"


def _cut_from(widget, copy_targets):
    tb = _editable(widget)
    if tb is None:
        return "break"
    result = _copy_from(copy_targets)
    try:
        tb.delete("sel.first", "sel.last")
    except tk.TclError:
        pass
    return result or "break"


def _copy_from(widgets):
    """선택 영역이 있는 텍스트박스에서 클립보드로 복사한다.

    읽기 전용 영역(state=disabled)은 키보드 포커스를 못 받기 때문에 위젯에
    직접 Cmd+C를 걸면 절대 발동하지 않는다. 그래서 창 단위로 받아서 여기서
    어느 위젯이 선택 영역을 갖고 있는지 찾는다.
    """
    for w in widgets:
        tb = getattr(w, "_textbox", w)
        try:
            text = tb.get("sel.first", "sel.last")
        except tk.TclError:
            continue
        if text:
            tb.clipboard_clear()
            tb.clipboard_append(text)
            return "break"
    return None


def _select_all(widgets):
    """포커스가 있는 텍스트박스를 전부 선택한다. 없으면 첫 번째 것.

    Tk on macOS의 기본 Cmd+A는 '줄 맨 앞으로'라 전체 선택이 안 된다.
    읽기 전용 영역은 포커스를 못 받으므로 창 단위로 받아 여기서 고른다.
    """
    focused = None
    for w in widgets:
        tb = getattr(w, "_textbox", w)
        if tb is tb.focus_get():
            focused = tb
            break
    tb = focused or getattr(widgets[0], "_textbox", widgets[0])
    tb.tag_add("sel", "1.0", "end-1c")
    tb.mark_set("insert", "1.0")
    return "break"


def _enable_drag_scroll(box, step_ms=40):
    """드래그로 선택하다 위젯 밖으로 나가면 따라 스크롤한다.

    Tk에 <B1-Leave> 자동 스크롤이 있지만 CTkTextbox 안에서는 돌지 않는다.
    (Text가 CTkFrame에 싸여 있어 포인터가 프레임 안에 머문다.)

    드래그 중에는 위젯 밖으로 나가도 이동 이벤트가 계속 오므로 마지막 좌표를
    들고 있다가 그걸로 방향을 정한다. 손을 멈춰도 그 좌표로 계속 굴러간다.
    """
    tb = getattr(box, "_textbox", box)
    drag = {"job": None, "x": 0, "y": 0}

    def stop():
        if drag["job"] is not None:
            tb.after_cancel(drag["job"])
            drag["job"] = None

    def scan():
        drag["job"] = None
        if not tb.winfo_exists():
            return
        height = tb.winfo_height()
        y = drag["y"]
        if y < 0:
            tb.yview_scroll(-1, "units")
        elif y > height:
            tb.yview_scroll(1, "units")
        else:
            return                      # 다시 안으로 들어왔으면 멈춘다
        tb.tk.call("tk::TextSelectTo", tb._w, drag["x"],
                   max(0, min(y, height - 1)))
        drag["job"] = tb.after(step_ms, scan)

    def on_motion(event):
        drag["x"], drag["y"] = event.x, event.y
        if not (0 <= event.y <= tb.winfo_height()):
            if drag["job"] is None:
                drag["job"] = tb.after(step_ms, scan)
        else:
            stop()

    tb.bind("<B1-Motion>", on_motion, add="+")
    tb.bind("<ButtonRelease-1>", lambda e: stop(), add="+")
    tb.bind("<Destroy>", lambda e: stop(), add="+")


def _undo(widgets, redo=False):
    """포커스가 있는 편집 가능한 칸에서 되돌리기 / 다시하기.

    Tk의 되돌리기 스택에는 프로그램이 넣은 글자도 함께 쌓인다. 받아적기가
    들어오는 중에 누르면 그 줄이 지워질 수 있다 — 다시 누르면(Cmd+Shift+Z)
    되살아난다.
    """
    boxes = [tb for tb in (_editable(w) for w in widgets) if tb is not None]
    if not boxes:
        return None
    # 읽기 전용 칸에 포커스가 있을 수 있다. 그럴 땐 첫 편집 가능한 칸으로.
    target = next((tb for tb in boxes if tb is tb.focus_get()), boxes[0])
    try:
        target.edit_redo() if redo else target.edit_undo()
    except tk.TclError:
        pass                    # 더 되돌릴 게 없을 뿐이다
    return "break"


# ── 마이크 버튼 ──────────────────────────────────────────────────────────────

class MicButton(ctk.CTkCanvas):
    """녹음 버튼 — 채운 원.

    이 창의 주 동작인데 예전에는 선으로만 그린 아이콘이라 옆의 Clear/Save와
    무게가 같았다. 원을 채워 손이 먼저 가는 자리로 세운다.

    좌표는 지름 44 기준으로 잡고 size 비율로 늘린다. 예전에는 38 기준 숫자가
    박혀 있어 크기를 바꾸면 아이콘이 가운데를 벗어났다.
    """

    BASE = 44.0

    def __init__(self, master, size=44, command=None,
                 bg_color="#ffffff", fill="#1f538d", glyph="#ffffff", **kwargs):
        super().__init__(master, width=size, height=size, bg=bg_color,
                         highlightthickness=0, cursor="hand2", **kwargs)
        self.size = size
        self.command = command
        self.bg_color = bg_color
        self.fill = fill
        self.glyph = glyph
        self.bind("<Button-1>", self._on_click)
        self.draw()

    def draw(self, fill=None, glyph=None):
        fill = fill or self.fill
        glyph = glyph or self.glyph
        k = self.size / self.BASE          # 44 기준 좌표를 실제 크기로
        self.delete("all")
        self.config(bg=self.bg_color)

        self.create_oval(0, 0, self.size, self.size, fill=fill, outline="")
        # 몸통 — 위아래 반원 + 사이 사각형 (Tk에는 둥근 사각형이 없다)
        self.create_oval(16.5 * k, 11 * k, 27.5 * k, 22 * k, fill=glyph, outline="")
        self.create_oval(16.5 * k, 15 * k, 27.5 * k, 26 * k, fill=glyph, outline="")
        self.create_rectangle(16.5 * k, 16.5 * k, 27.5 * k, 20.5 * k,
                              fill=glyph, outline="")
        # 감싸는 아치
        self.create_arc(13 * k, 13.5 * k, 31 * k, 31.5 * k, start=0, extent=-180,
                        style="arc", outline=glyph, width=max(2, round(2.2 * k)))
        # 짧은 대 — 받침선은 뺐다. 이 크기에서는 선이 하나 더 있으면 지저분하다
        self.create_line(22 * k, 31.5 * k, 22 * k, 35 * k,
                         fill=glyph, width=max(2, round(2.2 * k)), capstyle="round")

    def set_colors(self, bg_color, fill, glyph="#ffffff"):
        self.bg_color, self.fill, self.glyph = bg_color, fill, glyph
        self.draw()

    def _on_click(self, event):
        if self.command:
            self.command()


# ── 아이콘 폰트 ──────────────────────────────────────────────────────────────

ICON_FONT = "Material Icons"          # 번들에 넣은 TTF의 패밀리 이름
ICON_GEAR = "\ue8b8"                  # settings 글리프

def _asset(name):
    """번들 안 파일의 경로. PyInstaller로 묶으면 임시 폴더로 풀린다."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def _load_icon_font():
    """번들에 넣은 아이콘 폰트를 이 프로세스에만 등록한다.

    17px짜리 톱니를 캔버스에 직접 그려서는 쓸 만한 게 안 나왔다. 이빨 옆면이
    중심을 향하기 때문에 이빨마다 화면에서의 방향이 달라 제각각으로 보인다.
    PNG로 넣어도 Tk가 이미지를 논리 픽셀로 그려 Retina에서 흐려진다.
    글자는 CoreText가 실제 해상도로 그리므로 이 두 문제가 다 없다.

    customtkinter의 FontManager는 macOS를 지원하지 않는다(코드가 return False).
    그래서 CoreText에 직접 등록한다. 범위를 '프로세스'로 두면 시스템에 설치하지
    않으므로, 앱을 받은 사람 컴퓨터에 폰트가 없어도 보이고 흔적도 안 남는다.

    실패하면 False를 돌려주고, 호출 쪽이 캔버스로 그리는 GearButton으로 떨어진다.
    등록이 안 된 채 글자로 그리면 두부(?)만 뜬다.
    """
    path = _asset(os.path.join("assets", "MaterialIcons-Regular.ttf"))
    if not os.path.exists(path):
        return False
    if config.WINDOWS:
        # gdi32에 프로세스 범위로 등록한다(FR_PRIVATE=0x10). 맥과 마찬가지로
        # 시스템에 설치되지 않으므로 앱을 지워도 흔적이 남지 않는다.
        try:
            added = ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
            return bool(added)
        except Exception:
            _log_error(traceback.format_exc())
            return False
    try:
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        ct = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreText"))
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                                 ctypes.c_uint32]
        cf.CFURLCreateWithFileSystemPath.restype = ctypes.c_void_p
        cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                                     ctypes.c_int, ctypes.c_bool]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                        ctypes.c_void_p]
        text = cf.CFStringCreateWithCString(None, path.encode(), 0x08000100)  # UTF-8
        url = cf.CFURLCreateWithFileSystemPath(None, text, 0, False)          # POSIX
        return bool(ct.CTFontManagerRegisterFontsForURL(url, 1, None))        # 1=프로세스
    except Exception:
        _log_error(traceback.format_exc())
        return False


# 위젯이 폰트를 묻기 전에 한 번만 등록한다
ICON_FONT_OK = _load_icon_font()


# ── 설정(톱니) 버튼 ──────────────────────────────────────────────────────────

class GearButton(ctk.CTkCanvas):
    """톱니를 캔버스에 직접 그리는 설정 버튼.

    글자(⚙)로 넣으면 크기와 세로 위치를 폰트가 정해버린다. 같은 pt에서 한글보다
    30% 작게 그려지고, 버튼 중앙이 아니라 baseline 기준으로 앉아 위로 치우친다.

    PNG로 구워 CTkImage로 넣어도 봤는데, CTkImage는 Tk 확대율에 맞춰 매번
    리샘플링한다. macOS에서 Tk는 논리 픽셀로 보고하므로 원본을 한 번 줄여
    그리고 그걸 Retina가 다시 확대해, 어떤 크기로 구워도 흐려졌다.

    남은 제약은 픽셀 수뿐이다. 지름이 19px일 때는 이빨·골·링이 저마다 2px라
    어느 값을 잡아도 한쪽이 무너졌다(골이 좁아 이웃 이빨이 붙거나, 이빨이
    얇아 뭉개지거나). 버튼을 34px로 키워 지름 24px를 확보하니 셋 다 2.5px를
    넘어 제대로 그려진다. 크기를 다시 줄일 일이 있으면 그 값들부터 확인해라.
    """

    TEETH = 8
    # 버튼 짧은 변에 대한 비율. 40×28 버튼 기준 지름 17.4 · 이빨 2.7 · 링 2.5.
    # 이빨 높이가 톱니로 보이느냐를 가른다. 2.1px일 때는 혹이 얕아 원에 가까웠다.
    R_OUT, R_IN, HOLE = 0.310, 0.215, 0.125
    # 한 이빨 주기를 넷으로 나눈 지점: 윗변 → 옆면 경사 → 골 → 옆면 경사.
    FRACS = (0.08, 0.42, 0.58, 0.92)

    def __init__(self, master, width=40, height=28, command=None,
                 bg="#e2e8f0", hover="#cbd5e1", fg="#333333", panel="#ffffff"):
        super().__init__(master, width=width, height=height, bg=panel,
                         highlightthickness=0, cursor="hand2")
        self._w_, self._h_ = width, height
        self.size = min(width, height)      # 반지름은 짧은 변 기준
        self.command = command
        self.set_colors(bg, hover, fg, panel)
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self.bind("<Enter>", lambda e: self._draw(True))
        self.bind("<Leave>", lambda e: self._draw(False))

    def set_colors(self, bg, hover, fg, panel=None):
        self._bg, self._hover, self._fg = bg, hover, fg
        if panel:
            self._panel = panel
            self.config(bg=panel)
        self._draw(False)

    def _rounded(self, fill, r=R_CONTROL):
        w, h, d = self._w_, self._h_, 2 * r
        self.create_arc(0, 0, d, d, start=90, extent=90, fill=fill, outline=fill)
        self.create_arc(w - d, 0, w, d, start=0, extent=90, fill=fill, outline=fill)
        self.create_arc(0, h - d, d, h, start=180, extent=90, fill=fill, outline=fill)
        self.create_arc(w - d, h - d, w, h, start=270, extent=90, fill=fill, outline=fill)
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline=fill)
        self.create_rectangle(0, r, w, h - r, fill=fill, outline=fill)

    def _draw(self, hovering=False):
        bg = self._hover if hovering else self._bg
        self.delete("all")
        self._rounded(bg)

        cx, cy = self._w_ / 2, self._h_ / 2      # 정중앙 — 폰트와 무관
        r_out, r_in = self.R_OUT * self.size, self.R_IN * self.size
        hole = self.HOLE * self.size
        step = 2 * math.pi / self.TEETH
        # 이빨 중심이 FRACS[0]과 [1]의 중간에 오므로 그만큼 빼서 12시에 맞춘다.
        # 안 맞추면 이빨이 축에서 어긋난 채 앉아 톱니 전체가 기울어 보인다.
        phase = -math.pi / 2 - (self.FRACS[0] + self.FRACS[1]) / 2 * step
        pts = []
        for i in range(self.TEETH):
            base = i * step + phase
            for frac, r in zip(self.FRACS, (r_out, r_out, r_in, r_in)):
                a = base + frac * step
                pts += [cx + r * math.cos(a), cy + r * math.sin(a)]
        self.create_polygon(pts, fill=self._fg, outline=self._fg)
        self.create_oval(cx - hole, cy - hole, cx + hole, cy + hole,
                         fill=bg, outline=bg)


# ── 도움말 ───────────────────────────────────────────────────────────────────

# 한 덩어리로 이어 붙이면 620px 창에서 계속 굴려야 해서 원하는 대목을 못 찾는다.
# 탭으로 나눠 각 탭이 한 화면에 들어가게 한다. (이름, 마크다운) 순서가 탭 순서다.
HELP_SECTIONS = [
    ("시작하기", """학습을 돕는 AI 설명·메모 앱입니다. 주요 기능은 두 가지입니다.

**1. 노트** — 강의나 회의를 마이크로 받아 적습니다. 유튜브·줌처럼 컴퓨터 안에서 나는 소리도 텍스트로 기록해 저장합니다. 앱을 켜면 이 창이 먼저 뜹니다.

**2. LLM** — 연결되어 있는 LLM에게 텍스트 복사만으로 빠르게 질문하여, 공부에 도움이 되는 설명을 받습니다. 노트 아래 **채팅 보이기** 로 엽니다.

## 사용 방법

Groq라는 AI 모델 무료 사용 사이트에서 'API 키'를 받아와야 합니다. 10초면 됩니다.

1. 아래 주소를 눌러 로그인합니다
2. 오른쪽 위 **Create API Key** 를 누릅니다

![Create API Key 버튼](help_key_button.png){200}

3. 이름은 아무거나, 만료는 그대로 두고 **Submit**

![키 만들기 창](help_key_dialog.png){300}

4. 생성된 키를 복사해 ⚙ 설정의 API 키 칸에 붙여넣고 확인을 누릅니다

```
https://console.groq.com/keys
```
"""),

    ("노트", """앱을 켜면 바로 뜨는 본체 창입니다. 음성을 텍스트로 받아 적습니다.

창 위쪽에 **Always on Top** 스위치와 **?** · **⚙** 버튼이 있습니다.

## 소리 입력

무엇을 받아 적을지 고릅니다.

- **🎤 마이크** — 교수님 목소리처럼 실제로 들리는 소리
- **🔊 앱 이름** — 그 앱에서 나는 소리만. 온라인 강의나 통화
- **🔊 시스템 전체 소리** — 컴퓨터에서 나는 모든 소리

앱 소리를 처음 고르면 화면 기록 권한을 요청합니다. 이름과 달리 화면은 촬영하지 않고 소리만 가져옵니다.

## 받아적기

말이 끝나고 잠시 침묵이 감지되면, 해당 음성이 왼쪽에 텍스트로 받아 적힙니다.
원문과 번역 모두 바로 직접 수정할 수 있습니다.

## 번역

- **번역 조건** — AI 호출 횟수 절약을 위해, 인식 언어와 응답 언어가 다를 때만 번역합니다
  - 인식 English + 응답 한국어 → 번역
  - 인식 한국어 + 응답 한국어 → 번역 안 함
- **다른 언어** — **+** 를 누를 경우, 인식하고자 하는 더욱 다양한 언어를 고를 수 있습니다. 선택할 경우 그 자리에 남아 다음부터 바로 선택할 수 있습니다
- **자동 번역** — off일 경우, 번역 요청을 보내지 않습니다

## 그 밖의 버튼

- **채팅 보이기 / 숨기기** — AI 채팅 창을 올리거나 내립니다
- **Save note** — 누를 때마다 Finder 창에서 폴더와 파일명을 지정해 저장합니다
- **Clear** — 화면의 받아적기와 번역을 지웁니다. 누르면 한 번 확인을 묻습니다
- **창 버튼** — 노란 최소화는 녹음을 유지합니다. 빨간 닫기는 이 창이 본체이므로 **앱이 종료**되며, 녹음 중이면 한 번 확인을 묻습니다
"""),

    ("비용", """**요금은 전혀 발생하지 않습니다.** 카드도 등록하지 않고, 한도를 넘어도 청구되지 않습니다. 그때는 요청이 잠시 거부될 뿐입니다.

## Groq과 API 키

이 앱은 AI를 직접 돌리지 않고, **Groq**이라는 회사의 AI에 인터넷으로 물어봅니다. 받아 적기·번역·채팅이 모두 그렇습니다.

**API 키**는 그 회사에 "이 요청은 내 것"이라고 알려주는 긴 문자열입니다. 아이디·비밀번호 대신 프로그램이 쓰는 출입증이라고 보면 됩니다.

Groq은 이 출입증에 무료 사용량을 걸어 둡니다. 그래서 키를 한 번 받아 설정에 넣어두면, 그 한도 안에서 계속 무료로 쓸 수 있습니다.

## 음성 메모

한 번 받아 적을 때마다 1회를 씁니다. 말이 끝나고 침묵이 감지된 구간 하나가 1회입니다.

- 하루 2,000회 · 분당 20회
- 하루 8시간 · 시간당 2시간

한 구간이 평균 7초 정도라, **요청 수가 먼저 바닥납니다.** 2,000회를 다 써도 녹음 길이로는 4시간쯤입니다.

## LLM 대화 · 번역

- 하루 1,000회 · 분당 30회
- 하루 20만 토큰 · 분당 8,000토큰

토큰은 글자 수를 세는 단위입니다. 한글은 한 글자가 대략 1.5토큰입니다.

번역은 여러 줄을 모아 한 번에 보내기 때문에, 강의 한 시간을 받아 적어도 하루치의 4분의 1 정도만 씁니다.

## 알아두면 좋은 것

- 한도는 **모델마다 따로**입니다. 채팅 모델과 번역 모델을 다르게 두면 한도를 나눠 씁니다
- 음성과 대화도 별개입니다. 채팅이 막혀도 받아 적기는 계속됩니다
- 막히면 **다른 모델로 자동 전환**되고, 잠시 뒤 원래 모델로 돌아옵니다
- 자정에 초기화되는 것이 아니라 시간에 비례해 조금씩 회복됩니다. **24시간 동안 쓰지 않으면 모든 한도가 완전히 초기화됩니다**
- 남은 양은 ⚙ 설정의 **한도** 탭에서 확인합니다
"""),

    ("추가 기능", """**Always on Top** — on일 경우, 항상 다른 창 위에 표시(가려지지 않음). 투명도는 설정에서 조절 가능. 두 창 어느 쪽에서 켜도 같이 적용됨

**채팅 창** — 노트의 **채팅 보이기** 로 연다. 이 창의 빨간 닫기는 앱을 끄지 않고 창만 내린다

**Auto Send** — 채팅 창 위쪽 스위치. on일 경우, 복사 즉시 AI에게 전송. 터미널·편집기에서 복사한 것은 제외

**자동 저장** — 받아 적은 줄을 아래 폴더에 즉시 기록. 앱이 꺼져도 복구 가능. 30일 지난 파일은 앱 실행 시 삭제

```
~/Library/Application Support/StudyAI/notes/autosave/
```

**단축키** — {MOD}+A 전체 선택 · {MOD}+C 복사 · {MOD}+Z 되돌리기 · {MOD}+Shift+Z 다시 실행. 주소·경로는 클릭하면 열림
"""),

    ("그 외", """## 데이터가 어디로 가는가

**받아 적은 음성과 질문은 인터넷 너머 Groq으로 전송됩니다.** 기밀 회의나 개인정보처럼 밖으로 나가면 안 되는 소리·글에는 쓰지 않는 편이 안전합니다.

Groq이 밝힌 기준은 이렇습니다.

- 입력과 출력을 **모델 학습에 쓰지 않습니다** (서비스 약관 4.2)
- 요청 데이터를 **기본적으로 저장하지 않습니다.** 오류 점검과 남용 감시 목적으로 최대 30일 임시 기록될 수 있습니다
- Groq 콘솔의 Data Controls에서 **Zero Data Retention**을 켜면 그 임시 기록도 남지 않습니다. 무료 사용자도 켤 수 있습니다

## API 키 보관

API 키는 이 컴퓨터의 아래 파일에 저장됩니다. 다른 곳으로 보내지 않습니다.

```
~/Library/Application Support/StudyAI/settings.json
```

암호화하지 않으므로, 이 파일을 남에게 보내거나 화면에 띄울 때는 키가 함께 노출됩니다. 키가 새면 Groq 콘솔에서 폐기하고 새로 발급하면 됩니다.
"""),
]

# 통째로 복사하거나 훑을 때를 위해 이어 붙인 것도 남긴다
# 본문에 {MOD} 같은 자리를 두고 플랫폼에 맞는 말로 채운다 (Cmd / Ctrl)
HELP_SECTIONS = [(name, body.replace("{MOD}", MOD_NAME))
                 for name, body in HELP_SECTIONS]

HELP_TEXT = "# Study AI\n\n" + "\n".join(
    f"## {name}\n{body}" for name, body in HELP_SECTIONS)


class HelpDialog(ctk.CTkToplevel):
    """탭으로 나눈 도움말.

    예전에는 다섯 절을 한 덩어리로 이어 붙여서, "한도가 얼마더라"를 찾으려면
    창을 계속 굴려야 했다. 탭마다 한 화면에 들어가게 나눴다.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self._t = t = THEMES[parent._theme_name]
        self.title("도움말")
        self.geometry("560x620")
        self.minsize(460, 420)
        self.configure(fg_color=t["app_bg"])
        self.attributes("-topmost", True)

        self._tabs = ctk.CTkSegmentedButton(
            self, values=[name for name, _ in HELP_SECTIONS],
            font=(FONT_UI, FS_CAPTION), command=self._show,
            selected_color=t["seg_selected"], selected_hover_color=t["seg_hover"])
        self._tabs.pack(anchor="w", padx=SP_ITEM, pady=(SP_ITEM, SP_SNUG))

        self._box = ctk.CTkTextbox(
            self, corner_radius=R_PANEL, fg_color=t["panel_bg"],
            text_color=t["text_primary"], font=(FONT_UI, FS_BODY),
            wrap="word", border_width=0)
        self._box.pack(fill="both", expand=True, padx=SP_ITEM)
        # 본문에는 태그가 안 붙어서 줄간격이 0이었다. 위젯 쪽에 줘야 먹는다.
        _enable_drag_scroll(self._box)
        self._box._textbox.configure(spacing1=SP_TIGHT, spacing2=SP_TIGHT,
                                     spacing3=SP_SNUG, padx=SP_SNUG, pady=SP_SNUG)
        NotesWindow._config_trans_tags(self._box._textbox, t)
        self._box._textbox.tag_config("h2", font=(FONT_UI, FS_TITLE, "bold"),
                                      spacing1=SP_ITEM, spacing3=SP_TIGHT)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=SP_ITEM, pady=SP_ITEM)
        ctk.CTkButton(bar, text="닫기", width=80, fg_color=t["accent"],
                      hover_color=t["accent_hover"], text_color="white",
                      font=(FONT_UI, FS_BODY), command=self.destroy).pack(side="right")

        self.bind(f"<{MOD_KEY}-KeyPress>", self._on_cmd_key)
        self.bind("<Escape>", lambda e: self.destroy())
        self._tabs.set(HELP_SECTIONS[0][0])
        self._show(HELP_SECTIONS[0][0])

    def _on_cmd_key(self, event):
        k = _vkey(event)
        if k == VKEY_A:
            return _select_all([self._box])
        if k == VKEY_C:
            return _copy_from([self._box])
        return None

    def _show(self, name):
        body = next((b for n, b in HELP_SECTIONS if n == name), "")
        self._box.configure(state="normal")
        self._box.delete("1.0", "end")
        render_markdown(self._box, body)
        self._box.configure(state="disabled")
        self._box.yview_moveto(0)


# ── 설정 다이얼로그 ───────────────────────────────────────────────────────────

class SettingsDialog(ctk.CTkToplevel):

    KEY_GUIDE = ("console.groq.com/keys 에서 무료로 발급합니다.\n"
                 "카드 등록은 필요 없고, 키는 이 컴퓨터에만 저장됩니다.")

    def __init__(self, parent):
        super().__init__(parent)
        self._parent = parent
        t = THEMES[parent._theme_name]

        self.title("설정")
        self.configure(fg_color=t["panel_bg"])
        self.attributes("-topmost", True)
        # 높이를 재려고 페이지를 붙였다 떼는 동안 빈 창이 먼저 화면에 잡힌다.
        # 다 만든 뒤에 보여준다.
        self.withdraw()

        # 한 장에 다 쌓으면 750px을 넘어 화면에서 잘리기 시작한다. 성격이
        # 다른 둘로 나눈다 — 바꾸는 값(기본)과 지켜보는 값(한도).
        self._tabs = ctk.CTkSegmentedButton(
            self, values=["기본", "한도"], font=(FONT_UI, FS_CAPTION),
            command=self._show_tab, selected_color=t["seg_selected"],
            selected_hover_color=t["seg_hover"])
        self._tabs.pack(anchor="w", padx=SP_SECTION, pady=(SP_SECTION, SP_ITEM))

        # 두 페이지를 같은 칸에 겹쳐 두고 올렸다 내렸다 한다. 떼었다 붙이면
        # 그 사이에 창이 비어서 깜빡인다.
        holder = ctk.CTkFrame(self, fg_color="transparent")
        holder.pack(fill="both", expand=True)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)

        self._pages = {}
        for name in ("기본", "한도"):
            frame = ctk.CTkFrame(holder, fg_color="transparent")
            frame.grid(row=0, column=0, sticky="nsew")
            self._pages[name] = frame
        page = self._pages["기본"]

        def row(pady=(0, SP_SNUG), parent=None):
            f = ctk.CTkFrame(parent or page, fg_color="transparent")
            f.pack(fill="x", padx=SP_SECTION, pady=pady)
            return f

        def label(parent_frame, text):
            return ctk.CTkLabel(parent_frame, text=text, font=(FONT_UI, FS_BODY),
                                text_color=t["text_muted"], width=70,
                                anchor="w").pack(side="left")

        # API 키
        r = row((SP_SECTION, SP_TIGHT))
        label(r, "API 키")
        self._key_entry = ctk.CTkEntry(
            r, show="•", font=(FONT_UI, FS_CAPTION),
            fg_color=t["input_bg"], text_color=t["text_primary"],
            placeholder_text="gsk_...",
        )
        self._key_entry.insert(0, config.get("groq_api_key"))
        self._key_entry.pack(side="left", fill="x", expand=True, padx=(0, SP_SNUG))

        ctk.CTkButton(
            r, text="확인", width=50, font=(FONT_UI, FS_CAPTION),
            fg_color=t["accent"], hover_color=t["accent_hover"],
            command=self._check_key,
        ).pack(side="left")

        # 안내와 확인 결과가 같은 자리를 쓴다. 따로 두면 평소에 빈 줄이 남는다.
        r = row((0, SP_ITEM))
        ctk.CTkLabel(r, text="", width=70).pack(side="left")
        self._key_status = ctk.CTkLabel(
            r, anchor="w", justify="left", font=(FONT_UI, FS_CAPTION),
            text=self.KEY_GUIDE, text_color=t["text_muted"])
        self._key_status.pack(side="left", fill="x", expand=True)
        self._key_note_job = None

        # 채팅 모델
        r = row()
        label(r, "채팅 모델")
        self._chat_model = ctk.CTkOptionMenu(
            r, values=groq_client.chat_models(), font=(FONT_UI, FS_CAPTION),
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            button_color=t["accent"], button_hover_color=t["accent_hover"],
            command=lambda v: config.set("chat_model", v.split(" (")[0]),
        )
        self._set_model(self._chat_model, config.get("chat_model"),
                        groq_client.chat_models())
        self._chat_model.pack(side="left", fill="x", expand=True)

        # 번역 모델 — 채팅과 따로 고른다
        r = row()
        label(r, "번역 모델")
        self._trans_model = ctk.CTkOptionMenu(
            r, values=groq_client.chat_models(), font=(FONT_UI, FS_CAPTION),
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            button_color=t["accent"], button_hover_color=t["accent_hover"],
            command=lambda v: config.set("translate_model", v.split(" (")[0]),
        )
        self._set_model(self._trans_model, config.get("translate_model"),
                        groq_client.chat_models())
        self._trans_model.pack(side="left", fill="x", expand=True)

        # Whisper 모델
        r = row()
        label(r, "음성 인식")
        self._whisper_model = ctk.CTkOptionMenu(
            r, values=groq_client.whisper_models(), font=(FONT_UI, FS_CAPTION),
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            button_color=t["accent"], button_hover_color=t["accent_hover"],
            command=lambda v: config.set("whisper_model", v.split(" (")[0]),
        )
        self._set_model(self._whisper_model, config.get("whisper_model"),
                        groq_client.whisper_models())
        self._whisper_model.pack(side="left", fill="x", expand=True)

        # 소리 입력은 Notes 창에서 바로 고른다 (녹음하면서 바꾸는 일이 잦아서)

        # 응답 언어
        r = row()
        label(r, "응답 언어")
        self._lang_seg = ctk.CTkSegmentedButton(
            r, values=["한국어", "English", "日本語"],
            font=(FONT_UI, FS_CAPTION),
            selected_color=t["accent"], selected_hover_color=t["accent_hover"],
            command=self._on_lang,
        )
        self._lang_seg.set({"ko": "한국어", "en": "English", "ja": "日本語"}
                           .get(config.get("language"), "한국어"))
        self._lang_seg.pack(side="left")

        # 테마
        r = row()
        label(r, "테마")
        self._theme_seg = ctk.CTkSegmentedButton(
            r, values=["Light", "Dark", "Neon"], font=(FONT_UI, FS_CAPTION),
            selected_color=t["accent"], selected_hover_color=t["accent_hover"],
            command=self._on_theme,
        )
        self._theme_seg.set({"light": "Light", "dark": "Dark", "neon": "Neon"}
                            .get(parent._theme_name, "Light"))
        self._theme_seg.pack(side="left")

        # 투명도
        r = row((0, SP_SECTION))
        label(r, "투명도")
        self._opacity_lbl = ctk.CTkLabel(
            r, text=f"{int(parent._blur_opacity * 100)}%", font=(FONT_UI, FS_CAPTION),
            text_color=t["text_primary"], width=42, anchor="e",
        )
        self._opacity_lbl.pack(side="right")
        self._slider = ctk.CTkSlider(
            r, from_=10, to=100, number_of_steps=18, command=self._on_opacity,
            button_color=t["accent"], button_hover_color=t["accent_hover"],
            progress_color=t["accent"],
        )
        self._slider.set(parent._blur_opacity * 100)
        self._slider.pack(side="left", fill="x", expand=True, padx=(0, SP_SNUG))

        # 남은 한도 — 여기부터는 '한도' 탭에 담는다
        page = self._pages["한도"]
        r = row((0, SP_TIGHT))
        label(r, "남은 한도")
        self._limit_btn = ctk.CTkButton(
            r, text="새로고침", width=70, font=(FONT_UI, FS_CAPTION),
            fg_color=t["btn_sec_bg"], hover_color=t["btn_sec_hover"],
            text_color=t["btn_sec_text"], command=self._refresh_limits)
        self._limit_btn.pack(side="right")

        self._limit_box = row((0, SP_ITEM))
        self._render_limits()

        # 같은 칸에 겹쳐 있으므로 요구 높이가 이미 두 탭 중 큰 쪽이다.
        # 높이를 손으로 적으면 항목을 추가할 때마다 아래가 잘린다.
        self.update_idletasks()
        limit = self.winfo_screenheight() - SP_SECTION * 4
        self.geometry(f"440x{min(self.winfo_reqheight(), limit)}")
        self.resizable(False, True)     # 화면이 작으면 사용자가 늘릴 수 있게

        self._tabs.set("기본")
        self._show_tab("기본")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.focus()

    def _show_tab(self, name):
        self._pages[name].tkraise()

    # ── 남은 한도 ────────────────────────────────────────────────────────────

    @staticmethod
    def _set_model(menu, chosen, available):
        """드롭다운을 저장된 값으로 맞춘다.

        Groq가 모델을 내리면 저장된 이름이 목록에 없다. 그대로 두면 사용자는
        그 모델을 쓰는 줄 알지만 실제로는 대체 모델로 조용히 넘어간다.
        목록에 남겨 두되 사라졌다고 적는다.
        """
        if chosen in available:
            menu.set(chosen)
            return
        label = f"{chosen} (없어짐)"
        menu.configure(values=list(available) + [label])
        menu.set(label)

    # 한도가 무엇에 걸리는지 안 적어두면 숫자만 보고는 알 수 없다.
    # (제목, 모델 목록, 헤더에 안 오는 한도의 종류)
    LIMIT_GROUPS = (
        ("채팅·번역", groq_client.chat_models, "tokens"),
        ("음성 인식", groq_client.whisper_models, "audio"),
    )

    @staticmethod
    def _limit_rows(models=None):
        """모델별 (이름, 남은 비율, 문구, 막힘) — 값만 만들고 그리지는 않는다."""
        snap = groq_client.limits_snapshot()
        rows = []
        for model in (groq_client.chat_models() + groq_client.whisper_models()
                      if models is None else models):
            name = model.split("/")[-1][:20]
            info = snap.get(model)
            if info is None:
                # 아직 안 써서 헤더를 못 받았다. 실측 한도를 그대로 보여준다
                full = config.DEFAULT_LIMITS[
                    "whisper" if model in groq_client.whisper_models() else "chat"]
                rows.append((name, 1.0, f"{full}/{full}", False))
                continue
            if info.get("blocked"):
                rows.append((name, 0.0, "막힘", True))
                continue
            left, total = info.get("requests", (0, 0))
            text = f"{int(left)}/{int(total)}" if total else "-"
            if info.get("audio"):
                text += f" · {int(info['audio'][0])}초"
            rows.append((name, (left / total) if total else 0.0, text, False))
        return rows

    def _render_limits(self, note=None):
        """게이지 + 숫자로 다시 그린다. 색만으로는 구분이 안 되므로 숫자를 함께 둔다."""
        for w in self._limit_box.winfo_children():
            w.destroy()
        t = THEMES[self._parent._theme_name]

        if note:
            ctk.CTkLabel(self._limit_box, text=note, font=(FONT_UI, FS_CAPTION),
                         text_color=t["text_muted"], anchor="w").pack(fill="x")
            return

        for title, models, kind in self.LIMIT_GROUPS:
            head = ctk.CTkFrame(self._limit_box, fg_color="transparent")
            head.pack(fill="x", pady=(SP_SNUG, 0))
            ctk.CTkLabel(head, text=title, font=(FONT_UI, FS_CAPTION, "bold"),
                         text_color=t["text_primary"], anchor="w").pack(side="left")

            def model_row(name, metrics):
                """모델 한 줄. metrics는 [(지표 이름, 남은 비율, 값, 막힘)]."""
                r = ctk.CTkFrame(self._limit_box, fg_color="transparent")
                r.pack(fill="x", pady=SP_TIGHT)
                ctk.CTkLabel(r, text=name, font=(FONT_UI, FS_CAPTION),
                             text_color=t["text_muted"], width=116,
                             height=FS_CAPTION, anchor="w").pack(side="left")
                stack = ctk.CTkFrame(r, fg_color="transparent")
                stack.pack(side="left", fill="x", expand=True)

                for tag, ratio, text, blocked in metrics:
                    color = (t["error_text"] if blocked or ratio < 0.1 else
                             t["status_process"] if ratio < 0.3 else t["status_listen"])
                    m = ctk.CTkFrame(stack, fg_color="transparent",
                                     height=FS_CAPTION + SP_TIGHT)
                    m.pack(fill="x", pady=SP_HAIR)
                    m.pack_propagate(False)     # 라벨 높이가 행을 벌리지 않게
                    # 지표 이름을 막대 앞에 둔다. 세로로 줄맞춰 서서 훑기 쉽고,
                    # 막대 끝까지 가지 않아도 무엇의 값인지 안다.
                    ctk.CTkLabel(m, text=tag, font=(FONT_UI, FS_CAPTION),
                                 text_color=t["text_muted"], width=38,
                                 height=FS_CAPTION, anchor="w").pack(side="left")
                    ctk.CTkLabel(m, text=text, font=(FONT_MONO, FS_CODE),
                                 text_color=color, width=52,
                                 height=FS_CAPTION, anchor="e").pack(side="right")
                    bar = ctk.CTkProgressBar(m, height=SP_SNUG - 1,
                                             progress_color=color, fg_color=t["input_bg"])
                    bar.set(ratio)
                    bar.pack(side="left", fill="x", expand=True, padx=SP_SNUG)

            for model in models():
                name, ratio, text, blocked = self._limit_rows([model])[0]
                # 모델마다 항상 두 줄이다. 쓴 적 있을 때만 붙이면 줄 수가
                # 들쭉날쭉해서 빠진 자리가 오류처럼 보인다. 안 쓴 모델은
                # '가득'이라는 뜻이니 그대로 보여주는 편이 읽기 쉽다.
                cap = config.DAILY_CAPS[kind]
                left = max(0.0, cap - groq_client.usage_level(model, kind))
                shown = f"{left/1000:,.0f}K" if kind == "tokens" else f"{left/3600:.1f}h"
                model_row(name, [
                    ("요청", ratio, text.split(" · ")[0].split("/")[0], blocked),
                    ("토큰" if kind == "tokens" else "오디오", left / cap, shown, False),
                ])

        snap = groq_client.limits_snapshot()
        newest = max((i.get("at", 0) for i in snap.values()), default=0)
        # 토큰·오디오는 앱이 센 값이다. Groq가 헤더로 안 주기 때문인데, 이 키를
        # 이 앱만 쓰는 한 정확하다 — 화면에 굳이 단서를 달지 않는다.
        foot = "새로고침할 때마다 요청이 1회씩 차감됩니다."
        if newest:
            foot = datetime.fromtimestamp(newest).strftime("확인 %H:%M · ") + foot
        ctk.CTkLabel(self._limit_box, text=foot, font=(FONT_UI, FS_CAPTION),
                     text_color=t["text_muted"], anchor="w", justify="left").pack(
                         fill="x", pady=(SP_SNUG, 0))
        # 남은 양은 추론 응답 헤더로만 온다. Groq에 조회 전용 창구가 없어서
        # 새로고침도 결국 요청을 한 번씩 보낸다. 평소엔 누를 필요가 없다는 걸
        # 알려주지 않으면 확인하려고 한도를 깎게 된다.
    def _refresh_limits(self):
        self._limit_btn.configure(state="disabled", text="확인 중")
        self._render_limits(note="확인 중...")

        def work():
            try:
                groq_client.probe_limits()
                note = None
            except Exception as e:
                note = f"확인 실패: {e}"
            self.after(0, lambda: (
                self._render_limits(note),
                self._limit_btn.configure(state="normal", text="새로고침")))

        threading.Thread(target=work, daemon=True).start()

    def _key_note(self, text=None, color=None):
        """키 칸 아래 한 줄. 아무것도 안 주면 안내로 되돌린다."""
        if self._key_note_job:
            self.after_cancel(self._key_note_job)
            self._key_note_job = None
        t = THEMES[self._parent._theme_name]
        self._key_status.configure(text=text or self.KEY_GUIDE,
                                   text_color=color or t["text_muted"])

    def _check_key(self):
        key = self._key_entry.get().strip()
        self._key_note("확인 중...")

        def work():
            ok, msg = groq_client.check_key(key)

            def show():
                t = THEMES[self._parent._theme_name]
                self._key_note(("✓ " if ok else "✗ ") + msg,
                               t["status_listen"] if ok else t["error_text"])
                # 결과를 잠깐 보여준 뒤 안내로 되돌린다. 그대로 두면 다음에 열
                # 때까지 안내가 안 보인다.
                self._key_note_job = self.after(5000, self._key_note)
                if ok:
                    config.set("groq_api_key", key)
                    self._parent.clear_key_warning()
            self.after(0, show)

        threading.Thread(target=work, daemon=True).start()

    def _on_lang(self, name):
        code = {"한국어": "ko", "English": "en", "日本語": "ja"}.get(name, "ko")
        config.set("language", code)
        self._parent.reset_system_prompt()

    def _on_theme(self, name):
        self._parent._apply_theme(name.lower())

    def _on_opacity(self, value):
        self._opacity_lbl.configure(text=f"{int(value)}%")
        self._parent._apply_opacity(value / 100)

    def _on_close(self):
        # 확인 버튼을 안 눌렀어도 입력해 둔 키는 저장한다
        key = self._key_entry.get().strip()
        if key != config.get("groq_api_key"):
            config.set("groq_api_key", key)
        if key:
            self._parent.clear_key_warning()
        self.destroy()


# ── 음성 메모 창 ──────────────────────────────────────────────────────────────

class NotesWindow(ctk.CTkToplevel):
    def __init__(self, parent, stt):
        super().__init__(parent)
        self._stt = stt
        self._t = THEMES[parent._theme_name]
        self._trans_history = []
        self._trans_queue = []
        self._trans_running = False
        self._auto_path = None      # 이번 받아적기의 자동 저장 파일 (첫 줄에서 만든다)
        self._trans_buf = []        # 아직 안 보낸 줄들 — 모아서 한 번에 번역한다
        self._flush_job = None

        t = self._t
        self.title("Voice Notes")
        self.geometry("820x560")
        self.minsize(500, 300)
        self.configure(fg_color=t["app_bg"])
        # 빨간 X는 녹음을 멈추고 숨긴다. 노란 최소화는 그대로 녹음을 이어간다
        # (창을 치워두고 강의를 계속 받아 적는 용도).
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure((0, 1), weight=1)

        # 상단 — 이 창이 앱의 본체다. 설정과 도움말이 여기 있다.
        self.top_frame = ctk.CTkFrame(self, height=44, corner_radius=R_PANEL,
                                      fg_color=t["panel_bg"], bg_color=t["app_bg"])
        self.top_frame.grid(row=0, column=0, columnspan=2, sticky="ew",
                            padx=SP_ITEM, pady=(SP_ITEM, SP_SNUG))

        ctk.CTkLabel(self.top_frame, text="Voice Notes",
                     font=(FONT_UI, FS_BODY, "bold"),
                     text_color=t["text_primary"]).pack(side="left",
                                                        padx=SP_ITEM, pady=SP_SNUG)

        # 채팅 창이 내려가 있으면 그쪽 스위치에 손댈 수 없다. 같은 변수를 물려
        # 여기서도 켜고 끈다 — 두 창이 늘 같은 상태를 보인다.
        self.aot_switch = ctk.CTkSwitch(
            self.top_frame, text="Always on Top", variable=parent._aot_var,
            command=parent._toggle_aot, text_color=t["text_primary"],
            progress_color=t["accent"], font=(FONT_UI, FS_BODY))
        self.aot_switch.pack(side="left", padx=SP_ITEM, pady=SP_SNUG)

        if ICON_FONT_OK:
            self.settings_btn = ctk.CTkButton(
                self.top_frame, text=ICON_GEAR, font=(ICON_FONT, 18),
                width=40, height=28, command=self._open_settings,
                fg_color=t["btn_sec_bg"], hover_color=t["btn_sec_hover"],
                text_color=t["btn_sec_text"])
        else:
            self.settings_btn = GearButton(
                self.top_frame, width=40, height=28, command=self._open_settings,
                bg=t["btn_sec_bg"], hover=t["btn_sec_hover"],
                fg=t["btn_sec_text"], panel=t["panel_bg"])
        self.settings_btn.pack(side="right", padx=(0, SP_ITEM), pady=SP_SNUG)

        # side="right"는 먼저 pack한 것이 더 오른쪽에 온다 — ?는 톱니 왼쪽
        self.help_btn = ctk.CTkButton(
            self.top_frame, text="?", width=32, height=28,
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            hover_color=t["btn_sec_hover"],
            font=(FONT_UI, FS_TITLE, "bold"), command=self._open_help)
        self.help_btn.pack(side="right", padx=(0, SP_TIGHT), pady=SP_SNUG)

        # 왼쪽: 원문
        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.grid(row=1, column=0, sticky="nsew", padx=(SP_ITEM, SP_TIGHT), pady=(0, SP_ITEM))

        # 라벨과 스위치는 글상자 아래에 둔다. 위에 두면 상단 바와 겹쳐 보이고,
        # 받아적힌 글이 창 맨 위에서 시작하지 못한다.
        self._orig_header = ctk.CTkLabel(self.left_frame, text="원문",
            font=(FONT_UI, FS_CAPTION, "bold"), text_color=t["text_muted"])
        self._orig_header.pack(side="bottom", anchor="w", padx=SP_TIGHT)

        self.original_text = ctk.CTkTextbox(self.left_frame, corner_radius=R_PANEL,
            fg_color=t["panel_bg"], text_color=t["text_primary"],
            font=(FONT_UI, FS_BODY), wrap="word", undo=True)
        self.original_text.pack(fill="both", expand=True, pady=(0, SP_TIGHT))
        _enable_drag_scroll(self.original_text)

        # 오른쪽: 번역
        self.right_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.right_frame.grid(row=1, column=1, sticky="nsew", padx=(SP_TIGHT, SP_ITEM), pady=(0, SP_ITEM))

        # 원문 쪽 라벨과 같은 줄에 서도록 번역칸 아래에 둔다. 무엇을 켜고 끄는
        # 스위치인지는 번역칸에 붙어 있는 것으로 충분히 드러난다.
        head = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        head.pack(side="bottom", fill="x", padx=SP_TIGHT)

        self._trans_header = ctk.CTkLabel(head, text="번역",
            font=(FONT_UI, FS_CAPTION, "bold"), text_color=t["text_muted"])
        self._trans_header.pack(side="left")

        self._auto_trans_var = ctk.BooleanVar(value=config.get("translate_auto"))
        # 켜고 끄기는 앱 전체에서 스위치 하나로 통일한다. 예전엔 여기만 체크박스라
        # 크기·색·모양이 메인 창과 달랐고, 모서리 반경 탓에 라디오처럼 보였다.
        self.auto_trans_chk = ctk.CTkSwitch(
            head, text="자동 번역", variable=self._auto_trans_var,
            command=self._on_auto_trans, font=(FONT_UI, FS_BODY),
            text_color=t["text_primary"], progress_color=t["accent"],
        )
        self.auto_trans_chk.pack(side="right")

        self.translated_text = ctk.CTkTextbox(self.right_frame, corner_radius=R_PANEL,
            fg_color=t["panel_bg"], text_color=t["trans_text"],
            font=(FONT_UI, FS_BODY), wrap="word", undo=True)
        self.translated_text.pack(fill="both", expand=True, pady=(0, SP_TIGHT))
        _enable_drag_scroll(self.translated_text)
        self._config_trans_tags(self.translated_text._textbox, t)

        # 두 칸 모두 편집할 수 있다. 받아적기가 틀렸을 때 그 자리에서 고치는
        # 편이 자연스럽고, 스트리밍은 trans_start 표식 뒤쪽만 지우고 다시 쓰므로
        # 그 위에 손댄 내용은 건드리지 않는다.
        # 어느 칸에 포커스가 있든 복사·잘라내기가 먹도록 창 단위로 받는다.
        self.bind(f"<{MOD_KEY}-KeyPress>", self._on_cmd_key)

        # 소리 입력 + 인식 언어
        self.lang_frame = ctk.CTkFrame(self, height=40, fg_color="transparent")
        self.lang_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=SP_ITEM, pady=(0, SP_TIGHT))

        self._src_label = ctk.CTkLabel(self.lang_frame, text="소리 입력",
            font=(FONT_UI, FS_CAPTION), text_color=t["text_muted"])
        self._src_label.pack(side="left", padx=(SP_TIGHT, SP_SNUG))

        self._source_labels = {}
        self.source_menu = ctk.CTkOptionMenu(
            self.lang_frame, values=["…"], width=190, font=(FONT_UI, FS_CAPTION),
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            button_color=t["accent"], button_hover_color=t["accent_hover"],
            command=self._on_source,
        )
        self.source_menu.pack(side="left", padx=(0, SP_SNUG))

        # 앱 소리를 받을 때 내 목소리를 얹을지. 마이크를 고른 상태면 꺼둔다.
        self._mic_mix_var = ctk.BooleanVar(value=config.get("include_mic"))
        self.mic_mix_chk = ctk.CTkSwitch(
            self.lang_frame, text="내 목소리도 함께", variable=self._mic_mix_var,
            command=self._on_mic_mix, font=(FONT_UI, FS_BODY),
            text_color=t["text_primary"], progress_color=t["accent"],
        )
        self.mic_mix_chk.pack(side="left", padx=(0, SP_ITEM))

        self._lang_label = ctk.CTkLabel(self.lang_frame, text="인식 언어",
            font=(FONT_UI, FS_CAPTION), text_color=t["text_muted"])
        self._lang_label.pack(side="left", padx=(SP_TIGHT, SP_SNUG))

        self.lang_seg_btn = ctk.CTkSegmentedButton(
            self.lang_frame,
            values=[config.STT_LANGUAGES[c] for c in config.STT_QUICK],
            command=self._change_lang, font=(FONT_UI, FS_CAPTION),
            selected_color=t["seg_selected"], selected_hover_color=t["seg_hover"],
        )

        self.lang_seg_btn.pack(side="left")

        # 세그먼트에는 셋만 두고 나머지 언어는 여기서 고른다. 고르기 전에는 "+"만
        # 보이다가, 고르면 그 언어 이름을 단 드롭다운이 된다.
        self._extra_names = [config.STT_LANGUAGES[c]
                             for c in sorted(config.STT_LANGUAGES,
                                             key=lambda c: config.STT_LANGUAGES[c])
                             if c not in config.STT_QUICK]
        self.lang_extra = ctk.CTkOptionMenu(
            self.lang_frame, values=self._extra_names, width=34,
            font=(FONT_UI, FS_CAPTION), fg_color=t["btn_sec_bg"],
            text_color=t["btn_sec_text"], button_color=t["accent"],
            button_hover_color=t["accent_hover"], command=self._on_extra_lang,
        )
        self.lang_extra.pack(side="left", padx=(SP_SNUG, 0))

        self._sync_lang_ui()

        # 목록을 채우면서 마이크 섞기를 보일지 정한다. _sync_mic_mix가 이 줄의
        # 위젯들을 기준으로 자리를 잡으므로 언어 줄을 다 만든 뒤에 부른다.
        self.refresh_sources()

        # 하단
        self.bottom_frame = ctk.CTkFrame(self, height=50, fg_color="transparent")
        self.bottom_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=SP_ITEM, pady=(0, SP_ITEM))

        self.mic_btn = MicButton(self.bottom_frame, bg_color=t["app_bg"],
                                 fill=t["accent"], command=self._toggle)
        self.mic_btn.pack(side="left", padx=(0, SP_SNUG))

        self.status_lbl = ctk.CTkLabel(self.bottom_frame, text="● 정지",
            text_color=t["status_idle"], font=(FONT_UI, FS_BODY))
        self.status_lbl.pack(side="left", padx=SP_TIGHT)

        # 받아적기만 쓸 때 채팅 창이 계속 뒤에 깔린다. 손으로 최소화하던 걸
        # 버튼 하나로 만든다. 이 창을 닫으면 채팅 창은 저절로 돌아온다.
        self.chat_btn = ctk.CTkButton(
            self.bottom_frame, text="채팅 숨기기", width=96,
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            hover_color=t["btn_sec_hover"], font=(FONT_UI, FS_BODY),
            command=self._toggle_chat)
        self.chat_btn.pack(side="left", padx=SP_ITEM)

        self.save_btn = ctk.CTkButton(
            self.bottom_frame, text="Save note", width=100,
            fg_color=t["accent"], hover_color=t["accent_hover"],
            text_color="white", font=(FONT_UI, FS_BODY, "bold"), command=self._save_note)
        self.save_btn.pack(side="right", padx=SP_TIGHT)

        self.clear_btn = ctk.CTkButton(
            self.bottom_frame, text="Clear", width=80,
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            hover_color=t["btn_sec_hover"], font=(FONT_UI, FS_BODY), command=self._clear)
        self.clear_btn.pack(side="right", padx=SP_TIGHT)

    def _on_cmd_key(self, event):
        targets = [self.original_text, self.translated_text]
        k = _vkey(event)
        if k == VKEY_A:
            return _select_all(targets)
        if k == VKEY_Z:
            return _undo(targets, redo=bool(event.state & 0x1))   # Shift면 다시하기
        if k == VKEY_C:
            return _copy_from(targets)
        if k == VKEY_V:
            return _paste_into(self.focus_get())
        if k == VKEY_X:
            return _cut_from(self.focus_get(), targets)
        return None

    @staticmethod
    def _config_trans_tags(ttb, t):
        ttb.tag_config("bold", font=(FONT_UI, FS_BODY, "bold"))
        ttb.tag_config("code", font=(FONT_MONO, FS_CODE),
                       background=t["code_bg"], foreground=t["code_text"])
        ttb.tag_config("code_block", font=(FONT_MONO, FS_CODE),
                       background=t["code_bg"], foreground=t["code_text"],
                       lmargin1=SP_SNUG, lmargin2=SP_SNUG, spacing1=SP_TIGHT, spacing3=SP_TIGHT)
        ttb.tag_config("h1", font=(FONT_UI, FS_TITLE, "bold"), spacing1=SP_SNUG, spacing3=SP_TIGHT)
        ttb.tag_config("h2", font=(FONT_UI, FS_TITLE, "bold"), spacing1=SP_SNUG, spacing3=SP_TIGHT)
        ttb.tag_config("h3", font=(FONT_UI, FS_BODY, "bold"), spacing1=SP_TIGHT)
        ttb.tag_config("bullet", lmargin1=SP_ITEM, lmargin2=SP_SECTION)
        ttb.tag_config("table", font=(FONT_MONO, FS_CODE), foreground=t["text_primary"])
        ttb.tag_config("table_head", font=(FONT_MONO, FS_CODE, "bold"),
                       foreground=t["trans_text"])
        _config_link_tag(ttb, t)

    def apply_theme(self, t):
        self._t = t
        self.configure(fg_color=t["app_bg"])
        self._orig_header.configure(text_color=t["text_muted"])
        self.original_text.configure(fg_color=t["panel_bg"], text_color=t["text_primary"])
        self._trans_header.configure(text_color=t["text_muted"])
        self.translated_text.configure(fg_color=t["panel_bg"], text_color=t["trans_text"])
        self._config_trans_tags(self.translated_text._textbox, t)
        self._lang_label.configure(text_color=t["text_muted"])
        self._src_label.configure(text_color=t["text_muted"])
        self.auto_trans_chk.configure(text_color=t["text_primary"],
                                      progress_color=t["accent"])
        self.mic_mix_chk.configure(text_color=t["text_primary"],
                                   progress_color=t["accent"])
        self.source_menu.configure(fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
                                   button_color=t["accent"],
                                   button_hover_color=t["accent_hover"])
        self.lang_extra.configure(fg_color=t["btn_sec_bg"], button_color=t["accent"],
                                  button_hover_color=t["accent_hover"])
        self.lang_seg_btn.configure(selected_color=t["seg_selected"],
                                    selected_hover_color=t["seg_hover"])
        self.save_btn.configure(fg_color=t["accent"], hover_color=t["accent_hover"])
        self.clear_btn.configure(fg_color=t["btn_sec_bg"], hover_color=t["btn_sec_hover"],
                                 text_color=t["btn_sec_text"])
        self.chat_btn.configure(fg_color=t["btn_sec_bg"], hover_color=t["btn_sec_hover"],
                                text_color=t["btn_sec_text"])
        self.mic_btn.set_colors(t["app_bg"], t["accent"])
        self.update_state(self._stt.state)

    def update_state(self, state):
        t = self._t
        if not self._stt.running:
            self.status_lbl.configure(text="● 정지", text_color=t["status_idle"])
            self.mic_btn.draw(fill=t["accent"])
            return
        if state == STTState.SPEAKING:
            self.status_lbl.configure(text="● 녹음중", text_color=t["status_listen"])
        elif state == STTState.PROCESSING:
            self.status_lbl.configure(text="● 인식 중...", text_color=t["status_process"])
        else:
            self.status_lbl.configure(text="● 청취 중", text_color=t["status_listen"])
        self.mic_btn.draw(fill=t["mic_rec_fill"])

    def show_error(self, msg):
        self.status_lbl.configure(text=f"⚠ {msg[:60]}", text_color=self._t["error_text"])
        self.after(5000, lambda: self.update_state(self._stt.state))

    def show_notice(self, msg):
        """오류는 아니지만 알아야 할 일 (모델 자동 전환 등)."""
        self.status_lbl.configure(text=f"↻ {msg[:60]}",
                                  text_color=self._t["status_process"])
        self.after(6000, lambda: self.update_state(self._stt.state))

    @staticmethod
    def _at_bottom(tb):
        return tb.yview()[1] >= 0.98

    @staticmethod
    def _sanitize_stt(text):
        """Whisper가 같은 구절을 반복 생성하는 환각을 잘라낸다 (KMP 주기 검출)."""
        words = text.split()
        n = len(words)
        if n < 4:
            return text.strip()
        norm = [re.sub(r'[^\w]', '', w).lower() for w in words]
        f = [0] * n
        k = 0
        for i in range(1, n):
            while k > 0 and norm[k] != norm[i]:
                k = f[k - 1]
            if norm[k] == norm[i]:
                k += 1
            f[i] = k
        period = n - f[n - 1]
        if period < n and n % period == 0 and (n // period) >= 3:
            return ' '.join(words[:period]).rstrip(',').strip()
        return text.strip()

    def _autosave(self, line):
        """받아적은 줄을 그때그때 파일로 흘려 둔다.

        저장 버튼을 누르기 전까지 받아적기는 화면 위젯에만 있어서, 앱이 죽거나
        크래시하면 통째로 사라진다. 여기 남겨두면 최소한 되찾을 수 있다.
        """
        try:
            if self._auto_path is None:
                d = os.path.join(config.NOTES_DIR, "autosave")
                os.makedirs(d, exist_ok=True)
                base = os.path.join(d, datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
                # 같은 초에 두 번 시작하면(지우기 직후) 이전 세션에 덧붙게 된다
                path, n = base + ".txt", 2
                while os.path.exists(path):
                    path, n = f"{base}_{n}.txt", n + 1
                self._auto_path = path
            with open(self._auto_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())     # 강제 종료돼도 마지막 줄이 남도록
        except OSError:
            pass        # 자동 저장이 실패해도 받아적기는 계속돼야 한다

    def show_confirmed(self, text):
        text = self._sanitize_stt(text)
        if not text:
            return
        tb = self.original_text._textbox
        at_bot = self._at_bottom(tb)
        tb.insert("end", text + "\n")
        if at_bot:
            tb.see("end")
        self._autosave(text)

        # 세그먼트가 아니라 엔진에 설정된 코드를 본다. + 로 고른 언어도 잡힌다.
        lang = self._stt.language
        if self._auto_trans_var.get() and lang != config.get("language"):
            self._buffer_translation(text)

    # ── 번역 ─────────────────────────────────────────────────────────────────

    def _buffer_translation(self, text):
        """번역할 줄을 모은다. 기준만큼 쌓이면 묶어서 한 번에 보낸다."""
        self._trans_buf.append(text)
        if self._flush_job:
            self.after_cancel(self._flush_job)
            self._flush_job = None
        if sum(_est_tokens(t) for t in self._trans_buf) >= config.TRANSLATE_BATCH_TOKENS:
            self._flush_translation()
        else:
            # 말이 끊겨 기준에 못 미쳐도 마지막 줄들이 갇히지 않게
            self._flush_job = self.after(config.TRANSLATE_FLUSH_MS,
                                         self._flush_translation)

    def _flush_translation(self):
        """모아둔 줄을 한 덩어리로 번역 대기줄에 넣는다."""
        self._flush_job = None
        if not self._trans_buf:
            return
        self._trans_queue.append("\n".join(self._trans_buf))
        self._trans_buf = []
        if not self._trans_running:
            self._next_translation()

    def _next_translation(self):
        if not self._trans_queue:
            self._trans_running = False
            return
        self._trans_running = True
        text = self._trans_queue.pop(0)
        threading.Thread(target=self._translate_thread, args=(text,), daemon=True).start()

    def _fix_script(self, clean, lang, text, messages, ask):
        """번역에 섞여 나온 다른 언어 문자를 고친다. 못 고치면 받은 그대로 둔다.

        두 단계다. 먼저 섞인 조각만 옮겨 제자리에 끼워 넣고(싸다), 그래도 남으면
        문장 전체를 규칙을 붙여 다시 번역한다(비싸다). 둘 다 실패하면 원래 것을
        쓴다 — 조금 지저분해도 비어 있는 것보다 낫다.
        """
        runs = off_script_runs(clean, lang, text)
        # 지시문을 목표 언어로 쓴다. "Korean로 옮겨라"보다 자연스럽다.
        name = {"ko": "한국어", "en": "English", "ja": "日本語"}.get(
            lang, config.LANG_NAMES.get(lang, lang))
        try:
            reply = ask([{"role": "user", "content": FIX_PROMPT.format(
                name=name, context=clean[:400], words="\n".join(runs))}], 256)
        except Exception:
            reply = ""
        table = {}
        for line in reply.splitlines():
            src, _, dst = line.partition("=")
            src, dst = src.strip(), dst.strip()
            if src in runs and dst and not off_script(dst, lang):
                table[src] = dst
        if len(table) == len(runs):
            fixed = clean
            for src, dst in table.items():
                fixed = fixed.replace(src, dst)
            if not off_script(fixed, lang, text):
                return fixed

        # 조각 교정이 안 되면 문장을 통째로 다시 번역한다
        strict = list(messages)
        strict[0] = {"role": "system",
                     "content": strict[0]["content"] + strict_language(lang)}
        try:
            again = ask(strict, 512)
        except Exception:
            again = ""
        if again and not off_script(again, lang, text):
            return again
        return clean

    def _translate_thread(self, text):
        # 지시문을 영어로 쓴다. 예전에는 한국어로 쓰고 "영어→한국어" 견본 문답을
        # 두 쌍 박아 뒀는데, 응답 언어를 일본어로 두면 그 견본이 지시를 이겨서
        # 한국어를 뱉었다(실측). 견본을 빼니 다섯 언어쌍이 전부 맞고 호출당
        # 32토큰이 덜 든다. 직전 번역 이력은 언어쌍이 늘 맞으므로 그대로 둔다.
        src = _lang_name(self._stt.language)
        tgt = _lang_name(config.get("language"))

        messages = [
            {"role": "system", "content":
                f"You are a translator from {src} to {tgt}. The input is "
                f"speech-to-text output and may be noisy; guess and translate "
                f"anyway. Output ONLY the translation in {tgt}, nothing else. "
                f"If the input has several lines, translate each line into "
                f"exactly one line and keep the number of lines."},
        ]
        for s, tr in self._trans_history[-config.TRANSLATE_HISTORY:]:
            messages.append({"role": "user",      "content": f"입력: {s}\n번역:"})
            messages.append({"role": "assistant", "content": tr})
        messages.append({"role": "user", "content": f"입력: {text}\n번역:"})

        buf = []

        def record_start():
            tb = self.translated_text._textbox
            tb.mark_set("trans_start", "end-1c")
            tb.mark_gravity("trans_start", "left")

        self.after(0, lambda: self._trans_header.configure(text_color=self._t["status_listen"]))
        self.after(0, record_start)

        def on_chunk(chunk):
            buf.append(chunk)
            self.after(0, lambda c=chunk: self._append_trans(c))

        def ask(msgs, limit):
            got = []
            groq_client.stream_chat(msgs, model=config.get("translate_model"),
                                    chunk_callback=got.append, temperature=0.1,
                                    max_tokens=limit, no_think=True)
            return _clean_trans("".join(got))

        def on_done():
            clean = _clean_trans("".join(buf))
            lang = config.get("language")
            if clean and off_script(clean, lang, text):
                clean = self._fix_script(clean, lang, text, messages, ask)
            # 오염된 번역을 이력에 남기면 다음 묶음이 그걸 예시 삼아 따라간다.
            if clean and not off_script(clean, lang, text):
                self._trans_history.append((text, clean))
            self.after(0, lambda: self._finish_translation(clean))

        try:
            groq_client.stream_chat(messages, model=config.get("translate_model"),
                                    chunk_callback=on_chunk,
                                    done_callback=on_done,
                                    # 분당 버킷은 실제 사용량만 깎지만, 한도가
                                    # 바닥일 때의 사전 검사에는 max_tokens가
                                    # 들어간다(에러의 "Requested"가 프롬프트 +
                                    # max_tokens였다). 12줄 묶어도 출력이 150토큰
                                    # 정도라 512면 충분하고, 크게 잡을수록 바닥에서
                                    # 더 일찍 거부당한다.
                                    temperature=0.1, max_tokens=512,
                                    no_think=True)
        except Exception as e:
            # 조용히 비워두면 "번역이 안 된다"만 보이고 이유를 알 수 없다.
            # 아무것도 못 받았을 때만 실패 사유를 대신 띄운다.
            # 실패 문구까지 자동 저장에 들어가면 나중에 메모를 읽을 때 걸리적거린다.
            # 화면에만 남겨 왜 비었는지 알 수 있게 한다.
            got = "".join(buf)
            msg = got or f"[번역 실패: {e}]"
            self.after(0, lambda m=msg, ok=bool(got):
                       self._finish_translation(m, save=ok))

    def _append_trans(self, text):
        tb = self.translated_text._textbox
        at_bot = self._at_bottom(tb)
        tb.insert("end", text)
        if at_bot:
            tb.see("end")

    def _finish_translation(self, clean, save=True):
        tb = self.translated_text._textbox
        at_bot = self._at_bottom(tb)
        try:
            tb.delete("trans_start", "end-1c")
            tb.mark_unset("trans_start")
        except tk.TclError:
            pass
        if clean:
            render_markdown(self.translated_text, clean + "\n")
            if save:
                self._autosave("    " + clean)  # 번역은 들여써서 원문과 구분
        if at_bot:
            tb.see("end")
        self._trans_header.configure(text_color=self._t["text_muted"])
        self._next_translation()

    # ── 조작 ─────────────────────────────────────────────────────────────────

    def refresh_sources(self):
        """마이크와 실행 중인 앱을 다시 훑어 목록을 갱신한다.

        노트창을 열 때마다 부르므로, 나중에 켠 앱도 바로 고를 수 있다.
        """
        self._source_labels = {stt_engine.DEFAULT_DEVICE_LABEL: ""}
        labels = [stt_engine.DEFAULT_DEVICE_LABEL]
        for name in stt_engine.input_devices():
            lbl = f"🎤 {name}"
            labels.append(lbl)
            self._source_labels[lbl] = name
        labels.append("🔊 시스템 전체 소리")
        self._source_labels["🔊 시스템 전체 소리"] = stt_engine.SYSTEM_SOURCE
        for bid, app_name in stt_engine.app_sources():
            lbl = f"🔊 {app_name}"
            labels.append(lbl)
            self._source_labels[lbl] = stt_engine.APP_PREFIX + bid

        saved = config.get("input_device")
        current = next((l for l, v in self._source_labels.items() if v == saved), None)
        if current is None:      # 저장된 앱이 지금 안 떠 있는 경우 — 선택을 잃지 않게 남겨둔다
            current = f"🔊 {saved[len(stt_engine.APP_PREFIX):]} (실행 안 됨)" \
                      if saved.startswith(stt_engine.APP_PREFIX) else stt_engine.DEFAULT_DEVICE_LABEL
            if saved:
                labels.append(current)
                self._source_labels[current] = saved

        self.source_menu.configure(values=labels)
        self.source_menu.set(current)
        self._sync_mic_mix()

    def _sync_mic_mix(self):
        """마이크 섞기는 앱 소리를 잡을 때만 의미가 있으므로 그때만 보여준다.

        pack()은 다시 부르면 맨 뒤에 붙으므로, 원래 자리를 지키려면 다음
        위젯 앞에 넣어야 한다.
        """
        is_app = config.get("input_device").startswith(stt_engine.APP_PREFIX)
        if is_app:
            if not self.mic_mix_chk.winfo_manager():
                self.mic_mix_chk.pack(side="left", padx=(0, SP_ITEM),
                                      before=self._lang_label)
        else:
            self.mic_mix_chk.pack_forget()

    def _on_source(self, label_text):
        value = self._source_labels.get(label_text, "")
        config.set("input_device", value)
        self.master.set_input_device(value)
        self._sync_mic_mix()

    def _open_settings(self):
        self.master._open_settings()

    def _open_help(self):
        self.master._open_help()

    def _toggle_chat(self):
        self.master.set_chat_hidden(not config.get("chat_hidden"))
        self.sync_chat_btn()

    def sync_chat_btn(self):
        self.chat_btn.configure(
            text="채팅 보이기" if config.get("chat_hidden") else "채팅 숨기기")

    def _on_auto_trans(self):
        config.set("translate_auto", self._auto_trans_var.get())
        if self._auto_trans_var.get():
            return
        # 끄는 순간 모아둔 줄까지 같이 버린다. 남겨두면 30초 뒤 타이머가
        # 껐는데도 번역을 한 번 더 보낸다.
        if self._flush_job:
            self.after_cancel(self._flush_job)
            self._flush_job = None
        self._trans_buf = []

    def _on_mic_mix(self):
        config.set("include_mic", self._mic_mix_var.get())
        self.master.set_include_mic(self._mic_mix_var.get())

    def _change_lang(self, name):
        self._stt.language = next(
            (c for c in config.STT_QUICK if config.STT_LANGUAGES[c] == name), "en")
        self._sync_lang_ui()

    def _on_extra_lang(self, name):
        code = next((c for c, n in config.STT_LANGUAGES.items() if n == name), "en")
        config.set("extra_lang", code)
        self._stt.language = code
        self._sync_lang_ui()

    def _sync_lang_ui(self):
        """지금 인식 언어에 맞춰 세그먼트와 + 드롭다운을 맞춘다.

        고르는 곳이 둘이라 어느 쪽이 켜져 있는지 보이지 않으면 헷갈린다.
        쓰이는 쪽만 선택 상태로 두고, 반대쪽은 흐리게 둔다. + 에서 고른 언어는
        이름을 계속 달고 있어서 다시 고를 때 목록을 헤맬 필요가 없다.
        """
        code = self._stt.language
        t = self._t
        quick = code in config.STT_QUICK
        self.lang_seg_btn.set(config.STT_LANGUAGES[code] if quick else "")

        extra = config.get("extra_lang")
        if extra and extra in config.STT_LANGUAGES:
            self.lang_extra.configure(width=110, text_color=(
                t["btn_sec_text"] if not quick else t["text_muted"]))
            self.lang_extra.set(config.STT_LANGUAGES[extra])
        else:
            self.lang_extra.configure(width=34, text_color=t["btn_sec_text"])
            self.lang_extra.set("+")

    def _on_close(self):
        """빨간 X — 이 창이 본체이므로 앱을 끝낸다.

        녹음 중이면 한 번 묻는다. 자동 저장이 있어 받아적은 내용은 남지만,
        모르고 닫으면 강의가 그 자리에서 끊긴다.
        """
        if self._stt.running:
            if not messagebox.askyesno(
                    "받아적는 중", "받아적기를 멈추고 종료할까요?",
                    detail="받아적은 내용은 자동 저장되어 있습니다.",
                    icon="warning", default="no", parent=self):
                return
            self._stt.stop()
        self._flush_translation()       # 모아둔 줄을 남기지 않는다
        config.set("notes_open", True)  # 다음에 켜면 다시 이 창부터
        self.master.quit_app()

    def hide(self):
        """앱은 살려두고 이 창만 내린다. 채팅 창에서 다시 열 수 있다."""
        if self._stt.running:
            self._stt.stop()
        self._flush_translation()
        self.update_state(self._stt.state)
        self.master.set_chat_hidden(False)
        self.sync_chat_btn()
        config.set("notes_open", False)
        self.withdraw()

    def _toggle(self):
        if self._stt.running:
            self._stt.stop()
            self._flush_translation()
        else:
            self._stt.start()
        self.update_state(self._stt.state)

    def _save_note(self):
        self._flush_translation()   # 모아둔 줄이 번역 없이 저장되지 않도록
        original = self.original_text.get("1.0", "end-1c").strip()
        if not original:
            return
        translation = self.translated_text.get("1.0", "end-1c").strip()

        initialdir = config.get("notes_last_dir") or config.NOTES_DIR
        os.makedirs(initialdir, exist_ok=True)
        # -topmost가 켜져 있으면 저장 패널이 창 뒤로 숨는다. 메모 창만이 아니라
        # 본체 창도 함께 떠 있으므로 앱의 모든 창을 잠깐 내렸다 되돌린다.
        root = self.master if isinstance(self.master, tk.Misc) else self
        wins = [w for w in (root, *root.winfo_children())
                if isinstance(w, (tk.Tk, tk.Toplevel))]
        saved = [(w, w.attributes("-topmost")) for w in wins]
        for w, _ in saved:
            w.attributes("-topmost", False)
        try:
            path = filedialog.asksaveasfilename(
                parent=self,
                title="메모 저장",
                initialdir=initialdir,
                initialfile=datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".txt",
                defaultextension=".txt",
                filetypes=[("텍스트 파일", "*.txt"), ("모든 파일", "*.*")])
        finally:
            for w, top in saved:
                if w.winfo_exists():
                    w.attributes("-topmost", top)
        if not path:            # 취소
            return

        with open(path, "w", encoding="utf-8") as f:
            f.write(original)
            if translation:
                f.write("\n\n--- 번역 ---\n")
                f.write(translation)
        config.set("notes_last_dir", os.path.dirname(path))
        self.status_lbl.configure(text=f"저장됨: {os.path.basename(path)}",
                                  text_color=self._t["status_listen"])
        self.after(3000, lambda: self.update_state(self._stt.state))

    def _clear(self):
        # 받아적는 도중에 잘못 누르면 통째로 날아간다. 내용이 있으면 한 번 묻는다.
        if (self.original_text.get("1.0", "end-1c").strip()
                or self.translated_text.get("1.0", "end-1c").strip()):
            if not messagebox.askyesno(
                    "노트 초기화", "노트를 초기화하시겠습니까?",
                    detail="화면의 받아적기와 번역이 모두 지워집니다. "
                           "자동 저장된 파일은 남습니다.",
                    icon="warning", default="no", parent=self):
                return
        self._auto_path = None      # 지운 뒤 받아적기는 새 자동 저장 파일로
        if self._flush_job:
            self.after_cancel(self._flush_job)
            self._flush_job = None
        self._trans_buf = []
        self.original_text.delete("1.0", "end")
        self.translated_text.delete("1.0", "end")


# ── 메인 어시스턴트 앱 ────────────────────────────────────────────────────────

class StudyAssistant(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._q = queue.Queue()
        self._theme_name = _theme_name
        self._blur_opacity = float(config.get("opacity"))

        self._history = [{"role": "system", "content": config.system_prompt()}]
        self._streaming = False
        self._stream_buf = []

        self._clip_last = ""
        self._clip_pending = None
        self._clip_busy = False

        self._stt = None
        self._notepad = None
        self._blur_job = None
        self._settings_dialog = None
        self._help_dialog = None

        self._build_ui()
        self._start_clipboard()
        self._poll_q()

        if not config.get("groq_api_key"):
            self.after(300, self._prompt_for_key)

    # ── UI 구성 ───────────────────────────────────────────────────────────────

    def _build_ui(self):
        t = THEMES[self._theme_name]
        self.title("Study AI")
        self.geometry("520x720")
        self.minsize(400, 600)
        self.configure(fg_color=t["app_bg"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 상단
        self.top_frame = ctk.CTkFrame(self, height=50, corner_radius=R_PANEL,
            fg_color=t["panel_bg"], bg_color=t["app_bg"])
        self.top_frame.grid(row=0, column=0, sticky="ew", padx=SP_ITEM, pady=SP_SNUG)

        self._aot_var = tk.BooleanVar(value=True)
        self.attributes("-topmost", True)
        self.bind("<FocusOut>", self._on_blur)
        self.bind("<FocusIn>", self._on_focus)

        self.aot_switch = ctk.CTkSwitch(
            self.top_frame, text="Always on Top", variable=self._aot_var,
            command=self._toggle_aot, text_color=t["text_primary"],
            progress_color=t["accent"], font=(FONT_UI, FS_BODY))
        self.aot_switch.pack(side="left", padx=SP_ITEM, pady=SP_SNUG)

        self._clip_auto_var = tk.BooleanVar(value=bool(config.get("clip_auto")))
        self.clip_auto_switch = ctk.CTkSwitch(
            self.top_frame, text="Auto Send", variable=self._clip_auto_var,
            command=self._toggle_clip_auto, text_color=t["text_primary"],
            progress_color=t["accent"], font=(FONT_UI, FS_BODY))
        self.clip_auto_switch.pack(side="left", padx=(0, SP_SNUG), pady=SP_SNUG)

        self.notes_btn = ctk.CTkButton(
            self.top_frame, text="Notes", width=80,
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            hover_color=t["btn_sec_hover"], font=(FONT_UI, FS_BODY), command=self._open_notepad)
        self.notes_btn.pack(side="right", padx=(0, SP_ITEM), pady=SP_SNUG)

        if ICON_FONT_OK:
            self.settings_btn = ctk.CTkButton(
                self.top_frame, text=ICON_GEAR, font=(ICON_FONT, 18),
                width=40, height=28, command=self._open_settings,
                fg_color=t["btn_sec_bg"], hover_color=t["btn_sec_hover"],
                text_color=t["btn_sec_text"])
        else:      # 폰트를 못 읽으면 두부 대신 직접 그린 톱니로
            self.settings_btn = GearButton(
                self.top_frame, width=40, height=28, command=self._open_settings,
                bg=t["btn_sec_bg"], hover=t["btn_sec_hover"],
                fg=t["btn_sec_text"], panel=t["panel_bg"])
        self.settings_btn.pack(side="right", padx=(0, SP_TIGHT), pady=SP_SNUG)

        # side="right"는 먼저 pack한 것이 더 오른쪽에 온다 — ?는 톱니 왼쪽에 놓인다
        self.help_btn = ctk.CTkButton(
            self.top_frame, text="?", width=32, height=28,
            fg_color=t["btn_sec_bg"], text_color=t["btn_sec_text"],
            hover_color=t["btn_sec_hover"],
            font=(FONT_UI, FS_TITLE, "bold"), command=self._open_help)
        self.help_btn.pack(side="right", padx=(0, SP_TIGHT), pady=SP_SNUG)

        # 클립보드 바
        self._clip_bar = ctk.CTkFrame(self, fg_color=t["clip_bg"],
            bg_color=t["app_bg"], corner_radius=R_PANEL)
        self._clip_lbl = ctk.CTkLabel(self._clip_bar, text="", text_color=t["clip_text"],
            font=(FONT_UI, FS_CAPTION), anchor="w", justify="left")
        cb = ctk.CTkFrame(self._clip_bar, fg_color="transparent")
        cb.pack(side="right", padx=SP_SNUG)
        self._clip_send_btn = ctk.CTkButton(
            cb, text="Send", fg_color=t["accent"], hover_color=t["accent_hover"],
            text_color="white", width=50, height=26, font=(FONT_UI, FS_CAPTION, "bold"),
            command=self._send_clipboard)
        self._clip_send_btn.pack(side="left", padx=SP_TIGHT)
        self._clip_dismiss_btn = ctk.CTkButton(
            cb, text="X", fg_color="transparent", text_color=t["clip_text"],
            hover_color=t["clip_bg"], width=25, height=26,
            font=(FONT_UI, FS_CAPTION), command=self._dismiss_clipboard)
        self._clip_dismiss_btn.pack(side="left")
        self._clip_lbl.pack(side="left", padx=SP_SNUG, pady=SP_TIGHT, fill="x", expand=True)

        # 채팅 영역
        self.chat_frame = ctk.CTkTextbox(
            self, corner_radius=R_PANEL, fg_color=t["panel_bg"], bg_color=t["app_bg"],
            text_color=t["text_primary"], font=(FONT_UI, FS_BODY), wrap="word", border_width=0)
        self.chat_frame.grid(row=2, column=0, sticky="nsew", padx=SP_ITEM, pady=SP_TIGHT)
        self.chat_frame.configure(state="disabled")
        self._config_chat_tags(self.chat_frame._textbox, t)
        _enable_drag_scroll(self.chat_frame)

        # 입력 영역
        self.input_frame = ctk.CTkFrame(self, height=70, corner_radius=R_PANEL,
            fg_color=t["panel_bg"], bg_color=t["app_bg"])
        self.input_frame.grid(row=3, column=0, sticky="ew", padx=SP_ITEM, pady=SP_ITEM)
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.input_box = ctk.CTkTextbox(
            self.input_frame, height=50, corner_radius=R_PANEL,
            fg_color=t["input_bg"], text_color=t["text_primary"],
            border_width=0, font=(FONT_UI, FS_BODY), undo=True)
        self.input_box.grid(row=0, column=0, sticky="ew", padx=SP_SNUG, pady=SP_SNUG)
        self.input_box.bind("<Return>", self._on_return)

        self.send_btn = ctk.CTkButton(
            self.input_frame, text="Send", width=70, height=50, corner_radius=R_PANEL,
            fg_color=t["accent"], hover_color=t["accent_hover"],
            font=(FONT_UI, FS_BODY, "bold"), command=self._send)
        self.send_btn.grid(row=0, column=1, padx=(0, SP_SNUG), pady=SP_SNUG)

        # 읽기 전용 영역은 포커스를 못 받으므로 창 단위로 받는다
        self.bind(f"<{MOD_KEY}-KeyPress>", self._on_cmd_key)

    def _on_cmd_key(self, event):
        targets = [self.chat_frame, self.input_box]
        k = _vkey(event)
        if k == VKEY_A:
            return _select_all(targets)
        if k == VKEY_Z:
            return _undo(targets, redo=bool(event.state & 0x1))   # Shift면 다시하기
        if k == VKEY_C:
            return _copy_from(targets)
        if k == VKEY_V:
            return _paste_into(self.focus_get())
        if k == VKEY_X:
            return _cut_from(self.focus_get(), targets)
        return None

    @staticmethod
    def _config_chat_tags(ctb, t):
        ctb.tag_config("user_label", foreground=t["user_label"],
            font=(FONT_UI, FS_BODY, "bold"), spacing1=SP_SNUG, spacing3=SP_TIGHT)
        ctb.tag_config("ai_label", foreground=t["ai_label"],
            font=(FONT_UI, FS_BODY, "bold"), spacing1=SP_SNUG, spacing3=SP_TIGHT)
        ctb.tag_config("assistant", foreground=t["text_primary"])
        ctb.tag_config("bold", font=(FONT_UI, FS_BODY, "bold"))
        ctb.tag_config("h1", font=(FONT_UI, FS_DISPLAY, "bold"), spacing1=SP_SNUG, spacing3=SP_TIGHT)
        ctb.tag_config("h2", font=(FONT_UI, FS_TITLE, "bold"), spacing1=SP_SNUG, spacing3=SP_TIGHT)
        ctb.tag_config("h3", font=(FONT_UI, FS_BODY, "bold"), spacing1=SP_SNUG)
        ctb.tag_config("code", font=(FONT_MONO, FS_CODE),
            background=t["code_bg"], foreground=t["code_text"])
        ctb.tag_config("code_block", font=(FONT_MONO, FS_CODE),
            background=t["code_bg"], foreground=t["code_text"],
            lmargin1=SP_ITEM, lmargin2=SP_ITEM, spacing1=SP_TIGHT, spacing3=SP_TIGHT)
        ctb.tag_config("bullet", lmargin1=SP_ITEM, lmargin2=SP_SECTION)
        ctb.tag_config("error", foreground=t["error_text"])
        ctb.tag_config("table", font=(FONT_MONO, FS_CODE), foreground=t["text_primary"])
        ctb.tag_config("table_head", font=(FONT_MONO, FS_CODE, "bold"),
                       foreground=t["ai_label"])
        _config_link_tag(ctb, t)

    def _on_close(self):
        """채팅 창의 빨간 X.

        본체는 Notes다. 노트가 떠 있으면 이 창만 내리고, 노트가 없으면
        더 볼 창이 없으니 앱을 끝낸다.
        """
        if self._notepad is not None and self._notepad.winfo_viewable():
            self.set_chat_hidden(True)
            self._notepad.sync_chat_btn()
            return
        self.quit_app()

    def quit_app(self):
        """앱을 끝낸다. Notes의 X가 부르는 자리이기도 하다.

        _on_close를 그대로 부르면 안 된다 — 그쪽은 노트가 떠 있으면 채팅만
        내리고 돌아오므로, Notes에서 부르면 아무것도 안 닫힌다.
        """
        if self._stt:
            self._stt.shutdown()
        self.destroy()

    # ── 설정 ──────────────────────────────────────────────────────────────────

    def _prompt_for_key(self):
        self._system_msg(
            "Groq API 키가 설정되어 있지 않습니다.\n"
            "⚙ 버튼을 눌러 키를 입력하세요. https://console.groq.com/keys 에서 무료로 발급받을 수 있습니다.",
            mark="keywarn")
        self._open_settings()

    def _open_settings(self):
        if self._settings_dialog and self._settings_dialog.winfo_exists():
            self._settings_dialog.focus()
            return
        self._settings_dialog = SettingsDialog(self)

    def _open_help(self):
        if self._help_dialog and self._help_dialog.winfo_exists():
            self._help_dialog.lift()
            self._help_dialog.focus()
            return
        self._help_dialog = HelpDialog(self)

    def reset_system_prompt(self):
        self._history[0] = {"role": "system", "content": config.system_prompt()}

    def _apply_theme(self, name):
        if name not in THEMES:
            return
        self._theme_name = name
        t = THEMES[name]
        config.set("theme", name)
        ctk.set_appearance_mode(t["ctk_mode"])

        self.configure(fg_color=t["app_bg"])
        self.top_frame.configure(fg_color=t["panel_bg"], bg_color=t["app_bg"])
        self.aot_switch.configure(text_color=t["text_primary"])
        self.clip_auto_switch.configure(text_color=t["text_primary"])
        if ICON_FONT_OK:
            self.settings_btn.configure(fg_color=t["btn_sec_bg"],
                                        hover_color=t["btn_sec_hover"],
                                        text_color=t["btn_sec_text"])
        else:
            self.settings_btn.set_colors(t["btn_sec_bg"], t["btn_sec_hover"],
                                         t["btn_sec_text"], t["panel_bg"])
        self.help_btn.configure(fg_color=t["btn_sec_bg"],
            hover_color=t["btn_sec_hover"], text_color=t["btn_sec_text"])
        self.notes_btn.configure(fg_color=t["btn_sec_bg"],
            hover_color=t["btn_sec_hover"], text_color=t["btn_sec_text"])

        self._clip_bar.configure(fg_color=t["clip_bg"], bg_color=t["app_bg"])
        self._clip_lbl.configure(text_color=t["clip_text"])
        self._clip_send_btn.configure(fg_color=t["accent"], hover_color=t["accent_hover"])
        self._clip_dismiss_btn.configure(text_color=t["clip_text"], hover_color=t["clip_bg"])

        self.chat_frame.configure(fg_color=t["panel_bg"], bg_color=t["app_bg"],
                                  text_color=t["text_primary"])
        self._config_chat_tags(self.chat_frame._textbox, t)

        self.input_frame.configure(fg_color=t["panel_bg"], bg_color=t["app_bg"])
        self.input_box.configure(fg_color=t["input_bg"], text_color=t["text_primary"])
        self.send_btn.configure(hover_color=t["accent_hover"])
        self._set_streaming(self._streaming)   # 응답 대기 중이면 그 표시를 유지

        if self._notepad and self._notepad.winfo_exists():
            self._notepad.apply_theme(t)

    def _apply_opacity(self, value):
        self._blur_opacity = value
        config.set("opacity", round(value, 2))

    # ── 채팅 ──────────────────────────────────────────────────────────────────

    def _chat_at_bottom(self):
        return self.chat_frame._textbox.yview()[1] >= 0.98

    def _on_return(self, event):
        if not (event.state & 0x1):   # Shift+Enter는 줄바꿈
            self._send()
            return "break"

    def _system_msg(self, text, mark=None):
        """mark를 주면 나중에 _clear_marked()로 이 메시지만 지울 수 있다.

        범위를 태그로 잡으면 위젯 끝에 걸쳐서 이후 삽입되는 텍스트까지 태그를
        물려받아 같이 지워진다. 그래서 마크로 잡는다.
        """
        self.chat_frame.configure(state="normal")
        ctb = self.chat_frame._textbox
        start = ctb.index("end-1c")
        ctb.insert("end", f"\n{text}\n", "error")
        if mark:
            ctb.mark_set(f"{mark}_start", start)
            ctb.mark_gravity(f"{mark}_start", "left")
            ctb.mark_set(f"{mark}_end", ctb.index("end-1c"))
            ctb.mark_gravity(f"{mark}_end", "left")
        self.chat_frame.configure(state="disabled")
        self.chat_frame.see("end")

    def _clear_marked(self, mark):
        ctb = self.chat_frame._textbox
        try:
            start, end = f"{mark}_start", f"{mark}_end"
            ctb.index(start), ctb.index(end)      # 없으면 TclError
            self.chat_frame.configure(state="normal")
            ctb.delete(start, end)
            ctb.mark_unset(start, end)
            self.chat_frame.configure(state="disabled")
        except tk.TclError:
            pass

    def clear_key_warning(self):
        """키가 저장되면 시작 시 띄운 안내 문구를 지운다."""
        self._clear_marked("keywarn")

    def _set_streaming(self, on):
        """응답 대기 중임을 눈에 보이게 한다.

        gpt-oss 같은 추론 모델은 답변 전 reasoning 구간이 길어 화면에 아무것도
        안 나온다. 그 동안 입력을 조용히 무시하면 고장난 것과 구분이 안 된다.
        """
        self._streaming = on
        t = THEMES[self._theme_name]
        self.send_btn.configure(
            text="대기 중" if on else "Send",
            state="disabled" if on else "normal",
            fg_color=t["btn_sec_bg"] if on else t["accent"],
        )

    def _send(self):
        text = self.input_box.get("1.0", "end-1c").strip()
        if not text or self._streaming:
            return
        self.input_box.delete("1.0", "end")
        self._add_user_bubble(text)
        self._history.append({"role": "user", "content": text})
        threading.Thread(target=self._ai_call, daemon=True).start()

    def _add_user_bubble(self, text):
        self.chat_frame.configure(state="normal")
        ctb = self.chat_frame._textbox
        ctb.insert("end", "\nYou\n", "user_label")
        ctb.insert("end", text + "\n", "assistant")
        self.chat_frame.configure(state="disabled")
        self.chat_frame.see("end")

    def _ai_call(self):
        self._q.put(lambda: self._set_streaming(True))
        self._streaming = True
        self._stream_buf = []

        def begin():
            self.chat_frame.configure(state="normal")
            ctb = self.chat_frame._textbox
            ctb.insert("end", "\nAI\n", "ai_label")
            ctb.mark_set("ai_resp_start", "end-1c")
            ctb.mark_gravity("ai_resp_start", "left")
            ctb.insert("end", "…", "assistant")
            self.chat_frame.configure(state="disabled")
            self.chat_frame.see("end")
        self._q.put(begin)

        def redraw(full):
            at_bottom = self._chat_at_bottom()
            self.chat_frame.configure(state="normal")
            ctb = self.chat_frame._textbox
            try:
                ctb.delete("ai_resp_start", "end-1c")
            except tk.TclError:
                pass
            render_markdown(self.chat_frame, full)
            self.chat_frame.configure(state="disabled")
            if at_bottom:
                self.chat_frame.see("end")

        def on_chunk(chunk):
            self._stream_buf.append(chunk)
            self._q.put(lambda: redraw("".join(self._stream_buf)))

        def on_done():
            full = "".join(self._stream_buf)
            if full:
                self._history.append({"role": "assistant", "content": full})

            def finish():
                redraw(full + "\n")
                try:
                    self.chat_frame._textbox.mark_unset("ai_resp_start")
                except tk.TclError:
                    pass
            self._q.put(finish)

        def on_fallback(old, new):
            self._q.put(lambda: self._system_msg(f"[{old} 한도 초과 → {new}로 전환]"))

        try:
            groq_client.stream_chat(self._history, chunk_callback=on_chunk,
                                    done_callback=on_done,
                                    fallback_callback=on_fallback)
        except Exception as e:
            _log_error(traceback.format_exc())

            def show_err(msg=str(e)):
                self.chat_frame.configure(state="normal")
                self.chat_frame._textbox.insert("end", f"\n[오류: {msg}]\n", "error")
                self.chat_frame.configure(state="disabled")
                self.chat_frame.see("end")
            self._q.put(show_err)
        finally:
            # finish()/show_err()가 터져도 잠기지 않도록 마지막에 반드시 해제
            self._q.put(lambda: self._set_streaming(False))

    # ── 창 옵션 ───────────────────────────────────────────────────────────────

    def _toggle_clip_auto(self):
        config.set("clip_auto", self._clip_auto_var.get())

    def _toggle_aot(self):
        val = self._aot_var.get()
        self.attributes("-topmost", val)
        if self._notepad:
            self._notepad.attributes("-topmost", val)
        if val:
            self.bind("<FocusOut>", self._on_blur)
            self.bind("<FocusIn>", self._on_focus)
            if self._notepad:
                self._notepad.bind("<FocusOut>", self._on_blur)
                self._notepad.bind("<FocusIn>", self._on_focus)
        else:
            if self._blur_job:
                self.after_cancel(self._blur_job)
                self._blur_job = None
            self.unbind("<FocusOut>")
            self.unbind("<FocusIn>")
            self._set_alpha(1.0)
            if self._notepad:
                self._notepad.unbind("<FocusOut>")
                self._notepad.unbind("<FocusIn>")

    def _set_alpha(self, alpha):
        self.attributes("-alpha", alpha)
        if self._notepad and self._notepad.winfo_exists():
            self._notepad.attributes("-alpha", alpha)

    def _on_blur(self, *_):
        if self._blur_job:
            self.after_cancel(self._blur_job)
        self._blur_job = self.after(150, self._check_and_blur)

    def _check_and_blur(self):
        self._blur_job = None
        if self.focus_displayof() is not None:
            return
        self._set_alpha(self._blur_opacity)

    def _on_focus(self, *_):
        if self._blur_job:
            self.after_cancel(self._blur_job)
            self._blur_job = None
        self._set_alpha(1.0)

    # ── 클립보드 ──────────────────────────────────────────────────────────────

    def _start_clipboard(self):
        def tick():
            if not self._clip_busy:
                self._clip_busy = True
                threading.Thread(target=self._check_clip, daemon=True).start()
            self.after(500, tick)
        self.after(500, tick)

    def _check_clip(self):
        try:
            content = _clipboard_text(self)
            if not content or content == self._clip_last:
                return
            if _get_foreground_app() in EXCLUDED_APPS:
                return
            self._clip_last = content
            if self._clip_auto_var.get():
                self._q.put(lambda c=content: self._auto_send_clip(c))
            else:
                self._q.put(lambda c=content: self._show_clip(c))
        except Exception:
            pass
        finally:
            self._clip_busy = False

    def _show_clip(self, content):
        self._clip_pending = content
        preview = content[:80] + ("…" if len(content) > 80 else "")
        self._clip_lbl.configure(text=f"[clip]  {preview}")
        self._clip_bar.grid(row=1, column=0, sticky="ew", padx=SP_ITEM, pady=SP_TIGHT)

    def _auto_send_clip(self, content):
        self._clip_pending = content
        self._send_clipboard()

    def _send_clipboard(self):
        if self._clip_pending:
            text = f"[복사한 내용]\n{self._clip_pending}"
            self._dismiss_clipboard()
            self.input_box.delete("1.0", "end")
            self.input_box.insert("1.0", text)
            self._send()

    def _dismiss_clipboard(self):
        self._clip_pending = None
        self._clip_bar.grid_forget()

    # ── STT ───────────────────────────────────────────────────────────────────

    def _get_stt(self):
        if self._stt is None:
            self._stt = STTEngine(
                language=config.get("language"),
                device=config.get("input_device"),
                include_mic=config.get("include_mic"),
                mic_device=config.get("mic_device"),
                on_confirmed=self._stt_confirmed,
                on_state_change=self._stt_state,
                on_error=self._stt_error,
                on_notice=self._stt_notice,
            )
        return self._stt

    def set_input_device(self, name):
        """설정에서 장치를 바꿨을 때. 녹음 중이면 새 장치로 다시 연다."""
        if self._stt is None:
            return
        self._restart_stt(device=name)

    def set_include_mic(self, value):
        """'내 목소리도 함께'를 켜고 끌 때. 녹음 중이면 새 설정으로 다시 연다."""
        if self._stt is None:
            return
        self._restart_stt(include_mic=value)

    def _restart_stt(self, **attrs):
        was_running = self._stt.running
        if was_running:
            self._stt.stop()
        for k, v in attrs.items():
            setattr(self._stt, k, v)
        if was_running:
            self._stt.start()
        if self._notepad and self._notepad.winfo_exists():
            self._notepad.update_state(self._stt.state)

    def set_chat_hidden(self, hidden):
        """채팅 창을 내리거나 되돌린다.

        withdraw가 아니라 iconify를 쓴다. withdraw는 Dock에서도 사라져서
        Notes까지 닫으면 되살릴 방법이 없다.
        """
        if hidden:
            self.iconify()
        else:
            self.deiconify()
            self.lift()
        config.set("chat_hidden", hidden)

    def _open_notepad(self):
        if self._notepad is None:
            self._notepad = NotesWindow(self, self._get_stt())
            self._notepad.attributes("-topmost", self._aot_var.get())
            if self._aot_var.get():
                self._notepad.bind("<FocusOut>", self._on_blur)
                self._notepad.bind("<FocusIn>", self._on_focus)
        self._notepad.refresh_sources()   # 그새 켠 앱도 목록에 잡히도록
        self._notepad.deiconify()
        self._notepad.lift()
        self._notepad.focus()
        self._notepad.sync_chat_btn()
        config.set("notes_open", True)

    def _stt_confirmed(self, text):
        self._q.put(lambda t=text: self._notepad and self._notepad.show_confirmed(t))

    def _stt_state(self, state):
        self._q.put(lambda s=state: self._notepad and self._notepad.update_state(s))

    def _stt_error(self, msg):
        self._q.put(lambda m=msg: self._notepad and self._notepad.show_error(m))

    def _stt_notice(self, msg):
        """한도 초과로 모델이 바뀐 것 같은, 오류는 아니지만 알아야 할 일."""
        self._q.put(lambda m=msg: self._notepad and self._notepad.show_notice(m))

    # ── Queue 폴러 ────────────────────────────────────────────────────────────

    def _poll_q(self):
        """큐에 쌓인 UI 콜백을 드레인한다.

        콜백 하나가 예외를 던져도 절대 여기서 빠져나가면 안 된다. 예외가 밖으로
        나가면 아래 after() 재등록이 실행되지 않아 폴러가 영구히 죽고, 그러면
        _streaming이 True로 굳어 입력이 영영 막힌다.
        """
        while True:
            try:
                cb = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                cb()
            except Exception:
                _log_error(traceback.format_exc())
                try:                          # 잠김 방지
                    self._set_streaming(False)
                except Exception:
                    self._streaming = False
        self.after(80, self._poll_q)

    def _restore_last_layout(self):
        """Notes를 띄운다. 이 창이 본체이므로 기본은 여는 쪽이다.

        채팅 창을 내리는 건 Notes가 실제로 뜬 뒤에만 한다. 순서가 바뀌면
        아무 창도 없이 시작할 수 있다.
        """
        if not config.get("notes_open"):
            return
        self._open_notepad()
        if config.get("chat_hidden") and self._notepad.winfo_exists():
            self.set_chat_hidden(True)
            self._notepad.sync_chat_btn()

    def run(self):
        # 손으로 적어둔 모델 목록을 실제 목록과 맞춰 본다. 네트워크를 타므로
        # 창을 띄우는 것과 겹치지 않게 별도 스레드에서 돌린다.
        threading.Thread(target=groq_client.refresh_available, daemon=True).start()
        prune_autosave()        # 오래된 자동 저장 정리 (폴더 훑기라 금방 끝난다)
        # 창이 다 만들어진 뒤에 복원한다
        self.after(200, self._restore_last_layout)
        self.mainloop()


if __name__ == "__main__":
    StudyAssistant().run()
