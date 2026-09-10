"""자잘한 자체 점검 — 네트워크 없이 돈다.

    .venv/bin/python test_studyai.py

여기 있는 둘은 조용히 망가지면 알아채기 어려운 것들이다.
자동 저장은 안 되도 화면은 멀쩡해 보이고, 모델 체인은 Groq가 모델을
갈아치운 날에야 터진다(실제로 llama-3.x가 사라져 번역이 통째로 멈췄다).
"""

import os
import tempfile
import types

import config
import groq_client
import main
import stt_engine


def test_loopback_thread_setup():
    """윈도우 루프백을 도는 스레드가 COM을 켜고 장치도 거기서 잡는가.

    COM은 스레드마다 따로 켜야 한다. 안 켜면 recorder를 열 때
    0x800401F0(CO_E_NOTINITIALIZED)로 죽는다. 실제로 그렇게 실패했다.
    COM 객체는 만든 스레드에 매여 있으므로 장치를 UI 스레드에서 잡아
    넘겨도 안 된다. 윈도우가 없어 실행으로는 확인할 수 없어 소스로 본다.
    """
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "stt_engine.py"), encoding="utf-8").read()
    body = src[src.index("def _start_loopback"):src.index("def _pipe_reader")]
    thread_part = body[body.index("def run():"):]
    assert "CoInitializeEx" in thread_part, "스레드에서 COM을 안 켠다"
    assert "CoUninitialize" in thread_part, "짝을 안 맞춘다"

    loop_part = body[body.index("def loop():"):body.index("def run():")]
    assert "default_speaker()" in loop_part, "장치를 스레드 밖에서 잡는다"
    assert "include_loopback=True" in loop_part


def test_resample():
    """윈도우 루프백이 주는 48kHz를 16kHz 블록으로 줄이는가.

    공유 모드 루프백은 장치의 믹스 포맷을 그대로 내준다. 길이를 안 맞추면
    VAD의 블록 길이 가정이 깨지고 발화 구간이 엉뚱하게 잘린다.
    """
    import numpy as np
    # 48kHz에서 30ms = 1440 샘플 → 16kHz 한 블록 480 샘플
    src = np.sin(np.linspace(0, 8 * np.pi, 1440)).astype(np.float32)
    out = stt_engine._resample(src, 480)
    assert len(out) == 480 and out.dtype == np.float32
    assert abs(float(out.max()) - 1.0) < 0.05, out.max()

    same = np.zeros(480, dtype=np.float32)
    assert stt_engine._resample(same, 480) is same, "길이가 같으면 그대로 둔다"

    # 44.1kHz도 같은 길이로 나와야 한다
    assert len(stt_engine._resample(np.zeros(1323, dtype=np.float32), 480)) == 480


def test_autosave():
    """받아적은 줄이 그때그때 파일에 남는가."""
    config.NOTES_DIR = tempfile.mkdtemp()
    w = types.SimpleNamespace(_auto_path=None)

    main.NotesWindow._autosave(w, "첫 줄")
    main.NotesWindow._autosave(w, "    번역문")
    assert os.path.exists(w._auto_path)
    assert open(w._auto_path, encoding="utf-8").read() == "첫 줄\n    번역문\n"

    first = w._auto_path
    w._auto_path = None                     # 지우기 = 새 파일
    main.NotesWindow._autosave(w, "새 세션")
    assert w._auto_path != first

    config.NOTES_DIR = "/dev/null/없는경로"   # 쓰기 실패해도 받아적기는 계속돼야 한다
    w._auto_path = None
    main.NotesWindow._autosave(w, "조용히 실패")


def test_settings_fits():
    """설정 창이 내용을 다 담는가.

    높이를 손으로 적어두면 항목을 하나 추가할 때마다 맨 아래 안내가 잘린다.
    실제로 두 번 잘렸다. 이제 내용에 맞춰 잡으므로 그 값이 맞는지만 본다.
    """
    import customtkinter as ctk

    class Parent(ctk.CTk):
        _theme_name = "dark"
        _blur_opacity = 0.4
        def clear_key_warning(self): pass
        def reset_system_prompt(self): pass
        def _apply_theme(self, name): pass
        def _apply_opacity(self, value): pass

    root = Parent()
    root.withdraw()
    try:
        dlg = main.SettingsDialog(root)
        assert set(dlg._pages) == {"기본", "한도"}, list(dlg._pages)
        have = int(dlg.geometry().split("x")[1].split("+")[0])
        # 탭을 오갈 때 창이 들썩이지 않게 큰 쪽에 맞춰 뒀는지
        for name in dlg._pages:
            dlg._show_tab(name)
            dlg.update_idletasks()
            assert have >= min(dlg.winfo_reqheight(), dlg.winfo_screenheight()), name
        # 나눈 보람이 있어야 한다. 한 장에 다 쌓으면 약 990px이라 화면에서
        # 잘리기 시작한다(실제로 두 번 잘렸다).
        stacked = sum(p.winfo_reqheight() for p in dlg._pages.values())
        assert have < stacked * 0.75, (have, stacked)
    finally:
        root.destroy()


def test_drag_scroll():
    """드래그로 선택하다 아래로 나가면 화면이 따라 내려가는가.

    Tk에 자동 스크롤이 있지만 CTkTextbox 안에서는 안 돈다. 직접 넣은 것이
    빠지면 긴 대화에서 전체 선택이 사실상 불가능해진다.
    창을 하나 띄우므로 화면이 있어야 돈다.
    """
    import time
    import customtkinter as ctk

    def scrolled(enable):
        root = ctk.CTk()
        root.geometry("320x160+3000+3000")          # 화면 밖에 띄운다
        box = ctk.CTkTextbox(root)
        box.pack(fill="both", expand=True)
        box.insert("1.0", "\n".join(f"{i}번째 줄" for i in range(80)))
        box.configure(state="disabled")             # 채팅창과 같은 조건
        if enable:
            main._enable_drag_scroll(box, step_ms=10)
        root.update()
        tb = box._textbox
        height = tb.winfo_height()
        before = tb.yview()[0]
        tb.event_generate("<ButtonPress-1>", x=10, y=10)
        tb.event_generate("<B1-Motion>", x=10, y=height + 30)
        for _ in range(20):
            root.update()
            time.sleep(0.02)
        tb.event_generate("<ButtonRelease-1>", x=10, y=height + 30)
        root.update()
        after = tb.yview()[0]
        root.destroy()
        return after - before

    assert scrolled(False) == 0, "이 검사가 무의미하다 — Tk가 알아서 하고 있다"
    assert scrolled(True) > 0, "드래그해도 화면이 안 내려간다"


def test_shortcut_keys():
    """단축키를 가상 키코드로 잡는가.

    keysym으로 잡으면 한글 입력 상태에서 다른 값이 와서 안 먹는다. 가상 키코드는
    자판 상태와 무관하게 같다. macOS는 keycode 상위 바이트가, Windows는 keycode
    자체가 그 값이다.
    """
    keys = (main.VKEY_A, main.VKEY_Z, main.VKEY_X, main.VKEY_C, main.VKEY_V)
    if config.WINDOWS:
        assert keys == (65, 90, 88, 67, 86), keys      # Virtual-Key Code
        assert main.MOD_KEY == "Control" and main.MOD_NAME == "Ctrl"
        make = lambda vkey: types.SimpleNamespace(keycode=vkey)
    else:
        assert keys == (0, 6, 7, 8, 9), keys           # macOS 가상 키코드
        assert main.MOD_KEY == "Command" and main.MOD_NAME == "Cmd"
        make = lambda vkey: types.SimpleNamespace(keycode=(vkey << 24) | 97)

    for vkey in keys:
        assert main._vkey(make(vkey)) == vkey

    # 창에 거는 바인딩도 같은 수식 키를 써야 한다
    src_main = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "main.py"), encoding="utf-8").read()
    assert src_main.count('f"<{MOD_KEY}-KeyPress>"') == 3, "본체·노트·도움말"

    # 편집 가능한 칸에만 되돌리기가 걸려야 한다
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "main.py"), encoding="utf-8").read()
    assert src.count("undo=True") == 3, "원문·번역·입력칸 세 곳"


def test_unavailable_falls_back():
    """모델이 503(용량 초과)을 내면 다음 모델로 넘어가는가.

    한도(429)만 넘기고 5xx는 그대로 실패시키면, 번역 자리에 오류 문구가 남는다
    (qwen3.6이 "over capacity" 503을 낸 적이 있다).
    """
    import time
    tried, real = [], groq_client._stream_one

    def fake(model, messages, chunk_cb, done_cb, temp, limit, no_think):
        tried.append(model)
        if len(tried) == 1:
            raise groq_client.Unavailable("Groq 오류 503: over capacity")
        if chunk_cb:
            chunk_cb("ok")
        if done_cb:
            done_cb()

    groq_client._stream_one = fake
    swapped = []
    try:
        got = []
        groq_client.stream_chat([{"role": "user", "content": "hi"}],
                                model=config.CHAT_MODELS[0],
                                chunk_callback=got.append,
                                fallback_callback=lambda a, b: swapped.append((a, b)))
        assert "".join(got) == "ok"
        assert len(tried) == 2 and tried[0] != tried[1], tried
        assert swapped and swapped[0][0] == tried[0]
        # 503을 낸 모델은 잠시 쉬게 둔다 — 매 구간마다 다시 찔러 시간을 버리지 않게
        assert groq_client._cooldown.get(tried[0], 0) > time.time()
    finally:
        groq_client._stream_one = real
        groq_client._cooldown.pop(tried[0], None)


def test_off_script():
    """번역이 엉뚱한 문자로 나온 것을 잡아내는가.

    멀쩡한 번역을 잡으면 매번 다시 불러 토큰을 두 배로 쓴다. 로마자 약어와
    숫자·기호는 어느 언어에서나 정상이므로 걸리면 안 된다. 반대로 놓치면
    한자나 러시아어가 그대로 화면에 남는다.
    """
    # 한국어 — 한글과 로마자·숫자·기호는 정상
    assert not main.off_script("이 강의에서는 TCP/IP를 다룹니다", "ko")
    assert not main.off_script("2,000회 · 8시간 — 기호 ⚙ 포함", "ko")
    assert not main.off_script("LMS에서 자료를 받으세요 (chapter 3)", "ko")
    # 한국어 — 한자·가나·키릴은 잘못 나온 것
    assert main.off_script("이 本课程에서는", "ko") == "本课程"
    assert main.off_script("이 강의는 очень 좋습니다", "ko") == "очень"
    assert main.off_script("전송 계층とは", "ko") == "とは"

    # 일본어 — 가나와 한자는 정상, 한글은 아님
    assert not main.off_script("この講義ではTCP/IPを扱います", "ja")
    assert main.off_script("この講義では전송を扱います", "ja") == "전송"

    # 영어 — 로마자만
    assert not main.off_script("This course covers TCP/IP (chapter 3).", "en")
    assert main.off_script("This course covers 전송 계층.", "en") == "전송계층"

    # 원문에 있던 글자는 봐준다 — 인용은 그대로 남는 게 맞다
    assert not main.off_script("일본어로 「ありがとう」라고 합니다", "ko",
                               source="They say ありがとう in Japanese")

    # 모르는 언어는 검사하지 않는다 (100개 인식 언어는 응답 언어가 아니다)
    assert not main.off_script("любой текст", "ru")

    # 다시 부를 때 붙는 지시문에 목표 언어 이름이 들어간다
    assert "Korean" in main.strict_language("ko")
    assert "Japanese" in main.strict_language("ja")


def test_translate_prompt():
    """번역 지시가 응답 언어를 따라가는가.

    예전에는 지시문에 '영어→한국어' 견본 문답이 박혀 있어서, 응답 언어를
    일본어로 두면 그 견본이 지시를 이기고 한국어를 뱉었다(실측). 견본을 뺐다.
    """
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "main.py"), encoding="utf-8").read()
    body = src[src.index("def _translate_thread"):]
    body = body[:body.index("buf = []")]
    assert "모델은 훈련 데이터로부터" not in body, "견본 문답이 다시 들어왔다"
    assert "{tgt}" in body and "{src}" in body

    # 응답 언어 셋은 이름이 있고, 원문 언어는 코드를 그대로 넘긴다
    assert main._lang_name("ko") == "Korean"
    assert main._lang_name("ja") == "Japanese"
    assert main._lang_name("fr") == "fr"


def test_link_detection():
    """도움말의 주소·경로만 눌리는 대상으로 잡히는가.

    모델 이름(qwen/qwen3.6-27b)이나 소수점 숫자까지 링크로 잡히면 본문이
    파랗게 물든다. 잡히면 안 되는 쪽을 같이 확인한다.
    """
    find = main._LINK_RE.findall
    assert find("console.groq.com/keys 에서 가입") == ["console.groq.com/keys"]
    assert find("https://console.groq.com/keys 로") == ["https://console.groq.com/keys"]
    assert find("~/Documents/6학기 에 넣었다")[0].startswith("~/Documents")
    for plain in ("qwen/qwen3.6-27b 모델", "3.6 같은 것", "notes/autosave/ 에도",
                  "보통 문장은 안 잡힌다"):
        assert find(plain) == [], plain


def test_open_target(monkeypatch=None):
    """열어도 되는 것만 여는가. 모델이 뱉은 이상한 스킴을 실행하면 안 된다."""
    # 실제로 여는 자리(_open_with_os)만 가로챈다. 맥은 open, Windows는
    # os.startfile을 쓰므로 그 아래를 잡으면 한쪽에서만 도는 테스트가 된다.
    calls = []
    real = main._open_with_os
    main._open_with_os = calls.append
    try:
        main._open_target("console.groq.com/keys")
        assert calls[-1] == "https://console.groq.com/keys"
        main._open_target("https://example.com/a.")      # 끝 문장부호는 뗀다
        assert calls[-1] == "https://example.com/a"

        before = len(calls)
        main._open_target("file:///etc/passwd")          # http 아닌 스킴은 무시
        main._open_target("javascript:alert(1)")
        main._open_target("~/없는경로/여기없음")            # 없는 경로도 무시
        assert len(calls) == before, calls[before:]

        # 존재하는 경로는 연다. 맥이든 Windows든 같은 자리로 넘어가야 한다.
        folder = tempfile.mkdtemp()
        main._open_target(folder)
        assert calls[-1] == folder, calls[-1]
    finally:
        main._open_with_os = real


def test_model_catalog():
    """/models 응답을 종류별로 가르는가.

    메타데이터로 갈리는 건 여기까지다 — 한국어를 잘 하는지, reasoning_effort를
    뭘 받는지는 안 나온다. 그건 NO_THINK / EXCLUDE_MODELS에 손으로 적는다.
    """
    entries = [
        {"id": "openai/gpt-oss-120b", "output_modalities": ["text"],
         "supported_features": ["tools", "reasoning"], "context_window": 131072},
        {"id": "qwen/qwen3.6-27b", "output_modalities": ["text"],
         "supported_features": ["tools", "reasoning"], "context_window": 131072},
        {"id": "whisper-large-v3", "output_modalities": ["transcription"],
         "context_window": 448},
        # 아래는 전부 걸러져야 한다
        {"id": "canopylabs/orpheus-v1-english", "output_modalities": ["speech"],
         "context_window": 4000},                                   # TTS
        {"id": "meta-llama/llama-prompt-guard-2-22m", "output_modalities": ["text"],
         "supported_features": [], "context_window": 512},          # 분류기
        {"id": "allam-2-7b", "output_modalities": ["text"],
         "supported_features": ["tools"], "context_window": 4096},  # 문맥이 작다
        {"id": "openai/gpt-oss-safeguard-20b", "output_modalities": ["text"],
         "supported_features": ["tools", "reasoning"], "context_window": 131072},
    ]
    kinds = {e["id"]: groq_client._classify(e) for e in entries}
    assert kinds["openai/gpt-oss-120b"] == "chat"
    assert kinds["qwen/qwen3.6-27b"] == "chat"
    assert kinds["whisper-large-v3"] == "whisper"
    for junk in ("canopylabs/orpheus-v1-english", "meta-llama/llama-prompt-guard-2-22m",
                 "allam-2-7b", "openai/gpt-oss-safeguard-20b"):
        assert kinds[junk] is None, junk

    # 손으로 정한 우선순위가 앞이고, 새로 생긴 모델은 뒤에 붙는다
    got = groq_client._ordered({"b", "a", "새모델"}, ["a", "b", "없어진것"])
    assert got == ["a", "b", "새모델"], got

    # 확인 전에는 손으로 적은 목록을 쓴다
    saved = groq_client._catalog
    try:
        groq_client._catalog = None
        assert groq_client.chat_models() == list(config.CHAT_MODELS)
        assert groq_client.whisper_models() == list(config.WHISPER_MODELS)
    finally:
        groq_client._catalog = saved


def test_strip_think():
    """모르는 모델이 사고 과정을 흘려도 화면에 안 나오는가.

    태그가 스트리밍 조각 경계에서 잘리는 경우가 실제로 있다.
    """
    def run(parts):
        state, out = (False, ""), ""
        for part in parts:
            piece, state = groq_client._strip_think(part, state)
            out += piece
        return out + groq_client.flush_think(state)

    assert run(["안녕 <think>속마음</think> 반가워"]) == "안녕  반가워"
    assert run(["앞 <thi", "nk>숨김</think> 뒤"]) == "앞  뒤"      # 태그가 잘린 경우
    assert run(["a<think>x", "y</thi", "nk>b"]) == "ab"
    assert run(["<think>끝까지 안 닫힘"]) == ""
    assert run(["그냥 글"]) == "그냥 글"
    assert run(["짧", "은", "글"]) == "짧은글"


def test_model_chain():
    """사라진 모델을 붙잡지 않는가."""
    live = {"openai/gpt-oss-120b", "qwen/qwen3.6-27b"}
    real = config.CHAT_MODELS               # 다음 검사가 진짜 목록을 봐야 한다
    config.CHAT_MODELS = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile",
                          "qwen/qwen3.6-27b"]
    groq_client._cooldown.clear()
    try:

        groq_client._available = None        # 확인 전 — 적어둔 목록 그대로
        assert "llama-3.3-70b-versatile" in groq_client._model_chain("openai/gpt-oss-120b")

        groq_client._available = live        # 확인 후 — 죽은 것 제거
        assert groq_client._model_chain("openai/gpt-oss-120b") == \
            ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"]

        # 선호 모델이 사라져도 나머지로 이어간다
        assert groq_client._model_chain("llama-3.3-70b-versatile") == \
            ["openai/gpt-oss-120b", "qwen/qwen3.6-27b"]

        # 한도에 걸린 모델은 건너뛴다
        groq_client._mark_limited("openai/gpt-oss-120b", None)
        assert groq_client._model_chain("openai/gpt-oss-120b") == ["qwen/qwen3.6-27b"]
    finally:
        config.CHAT_MODELS = real
        groq_client._available = None
        groq_client._cooldown.clear()


def test_no_think_table():
    """thinking 끄는 값이 모델군마다 다르다 — 섞이면 400이 난다."""
    for model, (params, _always) in config.NO_THINK.items():
        effort = params["reasoning_effort"]
        if model.startswith("openai/gpt-oss"):
            assert effort in ("low", "medium", "high"), (model, effort)
        elif model.startswith("qwen/"):
            assert effort in ("none", "default"), (model, effort)
        assert model in config.CHAT_MODELS, f"{model}이 CHAT_MODELS에 없다"

    # 켜두면 사고과정이 응답에 섞여 나오는 모델은 무조건 꺼져 있어야 한다
    assert config.NO_THINK["qwen/qwen3.6-27b"][1] is True


def test_icon_font():
    """아이콘 폰트가 번들에 들어가고 등록되는가.

    customtkinter의 FontManager는 macOS에서 그냥 False를 돌려준다. 직접
    등록하지 않으면 톱니 자리에 두부(?)만 뜬다. 등록이 실패하면 캔버스로
    그리는 GearButton으로 떨어져야 하고, 그래서 그 클래스는 지우면 안 된다.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    ttf = os.path.join(here, "assets", "MaterialIcons-Regular.ttf")
    assert os.path.exists(ttf), "MaterialIcons-Regular.ttf 가 없다"
    assert os.path.getsize(ttf) > 100_000, os.path.getsize(ttf)

    assert main.ICON_GEAR == "\ue8b8", repr(main.ICON_GEAR)
    assert main.ICON_FONT == "Material Icons"
    assert main.ICON_FONT_OK is True, "폰트 등록 실패 — 두부가 뜬다"
    assert hasattr(main, "GearButton"), "등록 실패 시 쓸 대비책이 사라졌다"

    # 번들에도 들어가야 앱을 받은 사람 화면에서 보인다
    spec = open(os.path.join(here, "StudyAI.spec"), encoding="utf-8").read()
    # assets 폴더째로 들어가고, 그 안에 폰트가 있다
    assert '("assets", "assets")' in spec, "spec의 datas에 assets가 없다"
    icon = "AppIcon.ico" if config.WINDOWS else "AppIcon.icns"
    for name in ("help_key_button.png", "help_key_dialog.png",
                 "MaterialIcons-Regular.ttf", icon):
        assert os.path.exists(os.path.join(here, "assets", name)), name


def test_gear_shape():
    """톱니가 기울지 않고, 이빨·골·링이 픽셀에 잡힐 만큼 굵은가.

    지름 19px일 때는 셋 다 2px여서 어느 값을 잡아도 한쪽이 무너졌다 — 골이
    좁아 이웃 이빨이 붙어 좌우가 넙대대해 보이거나, 이빨이 얇아 뭉개졌다.
    버튼을 34px로 키워 확보한 여유를 다시 까먹지 않도록 여기서 지킨다.
    """
    import math
    G = main.GearButton
    size = 28                                  # 버튼 40×28의 짧은 변
    step = 2 * math.pi / G.TEETH
    r_out, r_in, hole = (G.R_OUT * size, G.R_IN * size, G.HOLE * size)

    # 이빨 하나가 12시에 오고, 나머지는 고르게 벌어져 있다
    mid = (G.FRACS[0] + G.FRACS[1]) / 2 * step
    phase = -math.pi / 2 - mid
    centers = sorted(round(math.degrees(phase + i * step + mid)) % 360
                     for i in range(G.TEETH))
    assert 270 in centers, centers
    assert len({centers[i + 1] - centers[i] for i in range(len(centers) - 1)}) == 1

    top, flank, valley = (G.FRACS[1] - G.FRACS[0],
                          G.FRACS[2] - G.FRACS[1],
                          G.FRACS[3] - G.FRACS[2])
    assert abs(top + valley + 2 * flank - 1.0) < 1e-9, (top, flank, valley)
    assert flank > 0, "옆면이 수직으로 서면 이빨이 ⊓ 모양이 된다"

    # 아래 수치는 실제로 Tk에 띄워 찍어 보고 정한 것이다. 눈으로 확인하지 않고
    # 값만 고치면 또 어긋난다.
    assert r_out - r_in >= 2.5, r_out - r_in           # 이빨 높이 — 얕으면 원이 된다
    assert r_in * valley * step >= 1.5, r_in * valley * step   # 골 폭
    assert r_in - hole >= 2.4, r_in - hole             # 링 두께
    assert 2 * r_out <= size - 8, r_out                # 가장자리 여백
    # 이빨이 반지름의 3분의 1을 넘으면 톱니가 아니라 별표로 보인다
    assert (r_out - r_in) / r_out <= 0.35, (r_out - r_in) / r_out


def test_usage_tracking():
    """헤더에 안 오는 토큰·오디오를 24시간 창으로 세는가.

    Groq는 이 둘을 초과했을 때만 알려준다. 앱이 세지 않으면 바닥날 때까지
    알 수 없다. 버킷이 자정에 초기화되지 않으므로 '오늘'이 아니라 24시간이다.
    """
    import time
    saved, real_save = dict(groq_client._usage), groq_client._usage_save
    groq_client._usage_save = lambda force=False: None    # 파일을 건드리지 않는다
    groq_client._usage.clear()
    try:
        now = time.time()
        groq_client.note_usage("m", "tokens", 1000)
        groq_client.note_usage("m", "tokens", 500)
        groq_client.note_usage("m", "audio", 12.5)
        # 방금 쓴 것은 회복될 시간이 없었으므로 그대로 남아 있다
        assert abs(groq_client.usage_level("m", "tokens") - 1500) < 1
        assert abs(groq_client.usage_level("m", "audio") - 12.5) < 0.1
        assert groq_client.usage_level("없는모델", "tokens") == 0

        # 저장되는 것은 [수위, 시각] 한 쌍뿐이다
        level, at = groq_client._usage["m|tokens"]
        assert abs(level - 1500) < 1 and abs(at - now) < 5

        # 회복은 쓴 양에 비례하지 않고 초당 일정량(상한/24시간)이다.
        # 6시간이면 하루치의 4분의 1인 5만이 돌아온다.
        groq_client._usage["b|tokens"] = [100000, now - 6 * 3600]
        left = groq_client.usage_level("b", "tokens", now)
        assert abs(left - 50000) < 1, left

        # 회복량이 쓴 양보다 크면 0에서 멈춘다 (안 쓴다고 한도가 늘지 않는다)
        groq_client._usage["c|tokens"] = [100, now - 23 * 3600]
        assert groq_client.usage_level("c", "tokens", now) == 0

        # 이어 쓰면 사이에 회복된 만큼만 빠진다
        groq_client._usage["d|tokens"] = [20000, now - 3600]
        groq_client.note_usage("d", "tokens", 20000)
        left = groq_client.usage_level("d", "tokens")
        assert abs(left - (40000 - 200000 / 24)) < 5, left

        # 옛 형식([[시각, 양], ...])을 읽으면 수위 하나로 접는다
        import json, tempfile, os as _os
        old_file = groq_client.USAGE_FILE
        fd, path = tempfile.mkstemp(suffix=".json")
        with _os.fdopen(fd, "w") as f:
            json.dump({"m|tokens": [[now - 3600, 30000], [now, 10000]]}, f)
        groq_client.USAGE_FILE = path
        try:
            groq_client._usage_load()
            level, at = groq_client._usage["m|tokens"]
            # 30000이 1시간 회복(8,333) 뒤 10000이 더해진 값
            assert abs(level - (30000 - 200000 / 24 + 10000)) < 50, level
        finally:
            groq_client.USAGE_FILE = old_file
            _os.unlink(path)
    finally:
        groq_client._usage.clear()
        groq_client._usage.update(saved)
        groq_client._usage_save = real_save

    # 문서에서 옮겨 적은 한도
    assert config.DAILY_CAPS == {"tokens": 200_000, "audio": 28_800}


def test_limit_rows():
    """남은 한도 게이지의 값 — 헤더가 빠져 있어도 깨지지 않는가."""
    rows = main.SettingsDialog._limit_rows

    groq_client._limits.clear()
    blank = {name: (ratio, text) for name, ratio, text, _ in rows()}
    # 한 번도 안 썼으면 실측 한도를 가득 찬 게이지로 보여준다
    assert blank["gpt-oss-120b"] == (1.0, "1000/1000"), blank["gpt-oss-120b"]
    assert blank["whisper-large-v3"] == (1.0, "2000/2000")

    groq_client._limits.update({
        "openai/gpt-oss-120b": {"requests": (250.0, 1000.0), "at": 1788000000, "blocked": None},
        # 음성은 응답에 audio-seconds 헤더가 붙을 때도 안 붙을 때도 있다
        "whisper-large-v3": {"requests": (1691.0, 2000.0), "audio": (7199.0, 7200.0),
                             "at": 1788000000, "blocked": None},
        "qwen/qwen3.8-27b": {"at": 1788000000, "blocked": "한도 초과"},
        "qwen/qwen3.6-27b": {"at": 1788000000, "blocked": None},   # 아무 헤더도 없는 경우
    })
    got = {name: (round(ratio, 3), text, blocked) for name, ratio, text, blocked in rows()}
    assert got["gpt-oss-120b"] == (0.25, "250/1000", False), got["gpt-oss-120b"]
    assert got["whisper-large-v3"] == (0.846, "1691/2000 · 7199초", False)
    assert got["qwen3.8-27b"] == (0.0, "막힘", True)
    assert got["qwen3.6-27b"] == (0.0, "-", False)      # 0으로 나누지 않는다
    assert got["gpt-oss-20b"] == (1.0, "1000/1000", False)   # 기록 없는 모델은 기본값

    assert len(rows()) == len(config.CHAT_MODELS) + len(config.WHISPER_MODELS)
    assert all(0.0 <= r <= 1.0 for _, r, _, _ in rows()), "게이지 비율이 범위를 벗어남"
    groq_client._limits.clear()


def test_design_tokens():
    """토큰 밖의 값이 다시 새어 들어오지 않았는가.

    글자 크기 10종·간격 9종·반경 5종이 규칙 없이 섞여 있던 것을 접은 것이라,
    한 군데라도 숫자를 직접 적기 시작하면 원래대로 돌아간다.
    """
    import re
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "main.py"), encoding="utf-8").read()
    body = src.split("# ── 디자인 토큰", 1)[1].split("\n", 1)[1]
    body = body.split("R_PANEL    = 16", 1)[1]      # 정의부는 건너뛴다

    strays = re.findall(r"\(FONT_(?:UI|MONO), \d+", body)
    strays += re.findall(r"(?:padx|pady|lmargin[12]|spacing[13])=\(?[1-9]\d*", body)
    strays += re.findall(r"corner_radius=\d+", body)
    assert not strays, strays

    assert (main.FS_CAPTION, main.FS_BODY, main.FS_TITLE, main.FS_DISPLAY) == (12, 14, 17, 20)
    assert (main.SP_TIGHT, main.SP_SNUG, main.SP_ITEM, main.SP_SECTION) == (4, 8, 16, 24)
    # 막대 두 줄을 한 덩어리로 묶는 데만 쓴다. 4는 그 자리에 너무 벌어진다.
    assert main.SP_HAIR == 1
    assert (main.R_CONTROL, main.R_PANEL) == (8, 16)


def test_translation_batching():
    """짧은 줄을 모았다가 기준을 넘으면 한 번에 보내는가."""

    class Fake:
        """Tk 없이 after/after_cancel만 흉내낸다."""
        def __init__(self):
            self._trans_buf, self._trans_queue = [], []
            self._trans_running = False
            self._flush_job = None
            self.jobs, self.translated = {}, []
            self._n = 0

        def after(self, ms, fn):
            self._n += 1
            self.jobs[self._n] = fn
            return self._n

        def after_cancel(self, job):
            self.jobs.pop(job, None)

        _buffer_translation = main.NotesWindow._buffer_translation
        _flush_translation = main.NotesWindow._flush_translation
        _next_translation = lambda self: self.translated.append(self._trans_queue.pop(0))

    # 기준에 닿을 때까지 쌓기만 하고, 넘으면 한 덩어리로 나간다.
    # 기준값은 설정에서 바뀔 수 있으므로 줄 수를 고정하지 않는다.
    w = Fake()
    line = "and then we move the weights in the opposite direction"
    sent = []
    while not w.translated:
        assert len(sent) < 50, "기준을 못 넘었다"
        w._buffer_translation(line)
        sent.append(line)
        if not w.translated:
            assert w._flush_job in w.jobs, "아직 안 보냈으면 타이머가 걸려 있어야 한다"

    assert len(sent) > 1, "한 줄 만에 나가면 묶는 의미가 없다"
    assert w.translated[0].splitlines() == sent
    assert w._trans_buf == []
    assert w._flush_job is None, "보냈으면 타이머도 풀려야 한다"

    # 기준을 넘겨 보냈으면 타이머는 처음부터 다시 잰다 —
    # 직전 묶음 때 걸어둔 타이머가 살아 있으면 다음 묶음이 일찍 잘린다
    w._buffer_translation("short one")
    assert w._flush_job is not None, "새 조각이 오면 타이머를 새로 건다"
    assert len(w.jobs) == 1, f"묵은 타이머가 남아 있다: {w.jobs}"

    # 말이 끊겨 기준에 못 미쳐도 타이머가 남은 줄을 흘려보낸다
    w = Fake()
    w._buffer_translation("that's all for today")
    assert w.translated == []
    w.jobs[w._flush_job]()                      # 타이머 발화
    assert w.translated == ["that's all for today"]

    # 빈 버퍼로 흘려보내도 빈 요청을 만들지 않는다
    w._flush_translation()
    assert len(w.translated) == 1

    # 자동 번역을 끄면 모아둔 줄과 걸어둔 타이머를 같이 버린다.
    # 안 버리면 껐는데도 30초 뒤에 번역이 한 번 더 나간다.
    w = Fake()
    w._auto_trans_var = types.SimpleNamespace(get=lambda: False)
    w._on_auto_trans = types.MethodType(main.NotesWindow._on_auto_trans, w)
    w._buffer_translation("모아만 두고")
    assert w._flush_job in w.jobs
    saved, real_save = dict(config._settings), config.save
    config.save = lambda: None
    try:
        w._on_auto_trans()
    finally:
        config._settings, config.save = saved, real_save
    assert w._trans_buf == []
    assert w._flush_job is None
    assert w.jobs == {}, f"타이머가 남아 있다: {w.jobs}"
    assert w.translated == [], "끄면서 번역을 보내면 안 된다"


def test_window_roles():
    """창을 닫았을 때 화면에 아무것도 안 남는 조합이 없는가.

    Notes가 본체다. Notes의 X는 앱을 끝내고, 채팅 창의 X는 창만 내린다.
    예전에는 Notes를 닫으면 숨어 있던 채팅이 돌아왔는데, 이제 Notes가 본체라
    그 자리는 hide()로 따로 뺐다 — 채팅에서 Notes를 잠깐 치울 때 쓴다.
    """
    calls, quit_called = [], []

    class FakeMain:
        def set_chat_hidden(self, hidden):
            calls.append(hidden)
            config._settings["chat_hidden"] = hidden

        def quit_app(self):
            quit_called.append(True)

    class FakeStt:
        running = False
        state = None
        def stop(self):
            pass

    def fresh():
        return types.SimpleNamespace(
            _stt=FakeStt(), master=FakeMain(),
            _trans_buf=[], _trans_queue=[], _trans_running=False, _flush_job=None,
            update_state=lambda s: None, withdraw=lambda: None,
            sync_chat_btn=lambda: None, _flush_translation=lambda: None,
        )

    saved, real_save = dict(config._settings), config.save
    config.save = lambda: None          # 검사가 settings.json을 건드리지 않게
    try:
        # hide() — 앱은 살아 있어야 하므로 채팅이 반드시 돌아온다
        config._settings.update(chat_hidden=True, notes_open=True)
        w = fresh()
        types.MethodType(main.NotesWindow.hide, w)()
        assert calls == [False], calls
        assert config.get("chat_hidden") is False
        assert config.get("notes_open") is False

        # X — 앱을 끝낸다. 다음에 켜면 다시 Notes부터 뜨도록 켜둔 채 남긴다.
        calls.clear()
        config._settings.update(chat_hidden=True, notes_open=False)
        w = fresh()
        types.MethodType(main.NotesWindow._on_close, w)()
        assert quit_called == [True], "Notes의 X가 앱을 끝내지 않았다"
        # _on_close를 부르면 채팅만 내려가고 창이 안 닫힌다 — 그 자리로 새지 않게
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "main.py"), encoding="utf-8").read()
        assert "self.master.quit_app()" in src
        assert "self.master._on_close()" not in src
        assert config.get("notes_open") is True
        assert calls == [], "종료하면서 채팅 창을 되살릴 이유가 없다"
    finally:
        config._settings, config.save = saved, real_save

    # 기본값도 Notes부터 뜨는 쪽이어야 한다
    assert config.DEFAULTS["notes_open"] is True
    assert config.DEFAULTS["chat_hidden"] is True


def test_help_text():
    """도움말이 살아 있고 화면에 있는 것과 어긋나지 않는가.

    한 번 통째로 사라진 적이 있다(다른 영역을 갈아끼우다 같이 지워짐). 참조만
    남아서 임포트는 되고 ? 버튼을 눌러야 터지는 자리라 오래 몰랐다.
    """
    assert isinstance(main.HELP_TEXT, str) and len(main.HELP_TEXT) > 500
    assert len(main.HELP_SECTIONS) >= 3
    for name, body in main.HELP_SECTIONS:
        assert name and body.strip(), name
    for must in ("Always on Top", "Auto Send", "자동 번역", "자동 저장",
                 "30일", "채팅 보이기", "+"):
        assert must in main.HELP_TEXT, must
    # 화면 라벨과 도움말이 따로 놀지 않게
    assert "다른 언어" in main.HELP_TEXT
    assert len(config.STT_LANGUAGES) == 100, len(config.STT_LANGUAGES)


def test_prune_autosave():
    """오래된 자동 저장만 지우는가.

    지우는 코드라 범위가 새면 손으로 저장한 메모까지 날아간다. 남겨야 할 것을
    남기는지, 폴더나 다른 확장자를 건드리지 않는지 함께 확인한다.
    """
    import time
    tmp = tempfile.mkdtemp()
    config.NOTES_DIR = tmp
    auto = os.path.join(tmp, "autosave")
    os.makedirs(auto)
    now = time.time()

    def put(name, age_days, folder=auto):
        path = os.path.join(folder, name)
        open(path, "w").write("x")
        os.utime(path, (now - age_days * 86400,) * 2)
        return path

    old_txt = put("2026-01-01_00-00-00.txt", 40)
    new_txt = put("2026-08-31_00-00-00.txt", 3)
    edge = put("edge.txt", 29)                    # 딱 경계 안쪽은 남는다
    keep_ext = put("메모.md", 40)                  # .txt 아닌 것은 안 건드린다
    os.makedirs(os.path.join(auto, "보관"))
    nested = put("옛날.txt", 40, os.path.join(auto, "보관"))   # 하위 폴더는 안 내려간다

    assert main.prune_autosave(keep_days=30, now=now) == 1
    assert not os.path.exists(old_txt)
    for path in (new_txt, edge, keep_ext, nested):
        assert os.path.exists(path), path
    assert os.path.isdir(os.path.join(auto, "보관"))

    # 0이면 아무것도 안 지운다
    put("2025-01-01_00-00-00.txt", 400)
    assert main.prune_autosave(keep_days=0, now=now) == 0
    # 폴더가 없어도 터지지 않는다
    config.NOTES_DIR = os.path.join(tmp, "없음")
    assert main.prune_autosave(keep_days=30, now=now) == 0


def test_translate_budget():
    """번역 프롬프트를 키우는 값들이 실수로 커지지 않았는지."""
    # 이력은 고유명사 유지용이다. 늘리면 회당 프롬프트가 그만큼 커진다
    # (실측: 1묶음 326토큰 → 3묶음 556토큰).
    assert 1 <= config.TRANSLATE_HISTORY <= 2, config.TRANSLATE_HISTORY
    # 채팅과 번역을 따로 고를 수 있어야 한도를 나눠 쓸 수 있다
    assert config.get("translate_model") in config.CHAT_MODELS
    assert config.get("chat_model") in config.CHAT_MODELS
    # 너무 작으면 프롬프트가 매번 새로 붙고, 너무 크면 번역이 늦게 뜬다
    assert 20 <= config.TRANSLATE_BATCH_TOKENS <= 80, config.TRANSLATE_BATCH_TOKENS
    # 말이 끊겼을 때 남은 줄을 흘려보내는 타이머. 짧으면 묶이기 전에 매번
    # 먼저 터지고(6초일 때 대화에서 한두 조각씩만 나갔다), 길면 침묵 동안
    # 번역이 화면에 안 뜬다.
    assert 15000 <= config.TRANSLATE_FLUSH_MS <= 60000, config.TRANSLATE_FLUSH_MS


def test_est_tokens():
    """어림값이 실제 토크나이저와 크게 벌어지지 않는가.

    아래 '실제'는 qwen3.6-27b에 같은 글을 넣어 prompt_tokens로 잰 값이다.
    20% 넘게 빗나가면 기준 토큰이 뜻하는 바가 달라진다.
    """
    assert main._est_tokens("") == 1                    # 0이면 영영 안 쌓인다
    assert main._est_tokens("um") == 1

    en = ("okay whatever you are based on this all right we have a prerequisite "
          "capitalist tune okay anybody of you who because I believe we have some "
          "international exchange students for this but it is not the case with the "
          "exchange student okay if you have enough mathematical background on calculus")
    ja = ("では今日の講義を始めます。まず勾配降下法について説明します。"
          "コスト関数の微分を各重みについて計算して、その勾配と反対方向に重みを動かします。"
          "学習率がステップの大きさを決めます。大きすぎると発散してしまいます。")
    for text, real in ((en, 50), (ja, 59)):
        got = main._est_tokens(text)
        assert 0.8 <= got / real <= 1.2, (got, real)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
