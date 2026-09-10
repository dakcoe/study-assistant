"""설정 저장/로드 — settings.json 하나에 전부 들어간다.

API 키를 앱 안에서 입력받아야 하므로 Windows판처럼 모듈 상수로 굳히지 않고
런타임에 바뀔 수 있는 dict로 들고 있는다.
"""

import json
import os
import sys

WINDOWS = sys.platform == "win32"

if getattr(sys, "frozen", False):
    # 묶인 앱 안은 읽기 전용이므로 설정과 메모는 사용자 폴더에 둔다
    if WINDOWS:
        APP_DIR = os.path.join(os.environ.get("APPDATA") or
                               os.path.expanduser("~"), "StudyAI")
    else:
        APP_DIR = os.path.expanduser("~/Library/Application Support/StudyAI")
    os.makedirs(APP_DIR, exist_ok=True)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 자동 저장은 지우는 장치가 없으면 계속 쌓인다. 되찾으려고 두는 것이라
# 한 달이면 충분하다. 0으로 두면 안 지운다.
AUTOSAVE_KEEP_DAYS = 30

SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
NOTES_DIR     = os.path.join(APP_DIR, "notes")

DEFAULTS = {
    "groq_api_key":  "",
    # gpt-oss로 고른 이유: llama-3.3-70b는 한국어 생성 중에 한자를 섞어 뱉는 버릇이
    # 있었는데(예: "출력한文字와") gpt-oss에서는 재현되지 않는다. 게다가 입력이 4배
    # 싸고(1M당 $0.15 vs $0.59) 무료 일일 토큰 한도가 두 배(200K vs 100K)다.
    # 채팅·번역 모델을 따로 고른다. 한도가 모델마다 따로라 나눠 쓰면 오래 간다.
    # 기본값은 둘 다 qwen3.6 — 번역 한 줄에 15토큰으로 가장 싸고 용어도 정확하다
    # ("경사 하강법"; qwen3.8은 "그라디언트 디센트"로 음차한다).
    "chat_model":     "qwen/qwen3.6-27b",
    "translate_model": "qwen/qwen3.6-27b",
    "extra_lang":     "",       # + 에서 고른 인식 언어 (코드)
    "whisper_model": "whisper-large-v3",
    "language":      "ko",       # AI 응답 언어
    "input_device":  "",         # 마이크/가상장치 이름. 빈 값이면 시스템 기본값
    # 앱 소리를 잡을 때 내 목소리도 함께 받을지. 마이크를 고른 상태면 의미가 없다.
    "include_mic":   False,
    "mic_device":    "",         # 함께 받을 마이크 이름. 빈 값이면 시스템 기본값
    "theme":         "light",
    "opacity":       0.4,
    "clip_auto":     False,
    "translate_auto": True,     # 받아적은 줄을 자동으로 번역할지
    # 받아적기를 주로 쓰는 사람은 채팅 창이 계속 뒤에 깔려 방해가 된다.
    # 마지막에 어떤 상태였는지 기억했다가 다음 실행 때 그대로 띄운다.
    # Notes가 본체다. 처음 켜면 받아적기 창부터 뜨고 채팅은 내려가 있는다.
    "notes_open":     True,     # Notes 창이 열린 채로 끝냈는지
    "chat_hidden":    True,     # 채팅 창을 내려둔 채로 끝냈는지
    "notes_last_dir": "",       # 메모를 마지막으로 저장한 폴더
}

# 2026-08 기준 Groq 무료 목록. llama-3.x는 제공이 끊겨 빼고, 한도가 따로 잡히는
# 모델만 남긴다 — 120b가 일일 토큰을 다 쓰면 20b, qwen 순으로 넘어간다.
# (groq/compound-mini는 내부에서 120b로 라우팅되어 대체가 안 된다)
CHAT_MODELS = [
    "qwen/qwen3.6-27b",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# 메타데이터로는 채팅 모델과 구분되지 않지만 대화에 쓸 물건이 아닌 것들.
# safeguard는 안전성 분류기다 — tools도 지원하고 문맥도 커서 규칙에 걸린다.
EXCLUDE_MODELS = ("openai/gpt-oss-safeguard-20b",)

# thinking(추론 과정) 끄기 — 모델군마다 받는 값이 다르다. 실측:
#   gpt-oss  : low / medium / high   ("none"은 400)
#   qwen3.x  : none / default        ("low"는 400)
# 값은 (파라미터, 무조건 끌지) 쌍이다.
#   무조건 끔 = 켜두면 <think> 사고과정이 응답 본문에 그대로 섞여 나오는 모델.
#   그 외 = 요청할 때만 끈다. 번역은 출력이 20토큰뿐이라 추론이 비용을 지배해서
#   끄면 6배 아끼지만(gpt-oss-20b 188→29), 채팅은 출력이 500토큰이라 효과가 없다
#   (실측 726→782로 오히려 늘었다). 그래서 번역에서만 켠다.
NO_THINK = {
    "openai/gpt-oss-120b": ({"reasoning_effort": "low"},  False),
    "openai/gpt-oss-20b":  ({"reasoning_effort": "low"},  False),
    "qwen/qwen3.8-27b":    ({"reasoning_effort": "none"}, False),
    "qwen/qwen3.6-27b":    ({"reasoning_effort": "none"}, True),
}

# 번역을 줄마다 보내면 프롬프트(약 245토큰)가 매번 새로 붙는다. 입력 문장이
# 두 글자든 한 문장이든 비용이 거의 같다는 뜻이다. 그래서 짧은 줄을 모았다가
# 이 정도 쌓이면 한 번에 보낸다. 5줄 묶었을 때 실측 63% 절감.
# 값을 올릴수록 아끼지만 번역이 화면에 늦게 뜬다.
# 실측(6줄 묶음, 이력 1묶음): 1줄씩 보내면 줄당 270토큰, 4줄 132, 6줄 111,
# 12줄 98. 6줄 근처에서 곡선이 눕는다. 더 키워봐야 몇 %를 더 얻자고 번역이
# 화면에 40초씩 늦게 뜬다. 40토큰 ≈ 5~6줄 ≈ 말하는 속도로 13초.
TRANSLATE_BATCH_TOKENS = 40
# 말이 끊겨 기준에 못 미쳐도 이 시간이 지나면 모인 만큼 보낸다.
# 짧게 잡으면(6초로 뒀었다) 대화처럼 사이가 뜨는 말에서는 타이머가 매번 먼저
# 터져 한두 조각씩만 나가고 묶는 의미가 사라진다. 정지·저장·창 닫기에서도
# 흘려보내므로 이건 화면 표시가 너무 늦어지지 않게 하는 뒷받침일 뿐이다.
# 기준을 넘겨 보내고 나면 타이머는 풀리고, 다음 조각부터 다시 잰다.
TRANSLATE_FLUSH_MS = 30000

# 직전 번역을 몇 묶음이나 실어 보낼지. 이력은 고유명사를 붙들어 두는 값을 한다.
# 실측(6줄 묶음): 3묶음이면 줄당 104토큰, 1묶음 67, 없으면 46.
# 다만 이력을 아예 빼면 Adam이 "아담"으로 음차되기 시작한다. 1묶음이 접점이다.
TRANSLATE_HISTORY = 1

# 아직 한 번도 안 써서 헤더를 못 받은 모델에 보여줄 기본 한도(실측값).
# 실제 요청이 한 번 오가면 응답 헤더 값으로 덮인다. 재보려고 요청을 쓰는 건
# 아껴야 할 자원을 재려고 그 자원을 쓰는 꼴이라 하지 않는다.
# 헤더로 안 오는 한도. 문서값이고, 초과해야만 알 수 있어서 앱이 직접 센다.
# https://console.groq.com/docs/rate-limits (2026-08-31, 무료 티어, 모델당)
DAILY_CAPS = {"tokens": 200_000, "audio": 28_800}     # 하루 토큰 / 하루 오디오 초

DEFAULT_LIMITS = {"chat": 1000, "whisper": 2000}     # 일일 요청 수

WHISPER_MODELS = [
    "whisper-large-v3",
    "whisper-large-v3-turbo",
]

LANG_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese"}

# Whisper가 받아 적을 수 있는 언어. 목록은 API가 직접 알려준다 — 없는 코드를
# 보내면 400 응답 본문에 전부 실려 온다:
#   curl ... -F "model=whisper-large-v3" -F "language=zz"
#   → "Language must be one of: [hr eu sn ...]"
# 매번 물어보면 아껴야 할 음성 요청을 하나 쓰므로 받아 적어 둔다.
# 모델이 바뀌어 목록이 달라지면 위 명령으로 다시 뽑는다. (2026-08-31 기준 99개)
STT_LANGUAGES = {
    "af": "아프리칸스어", "am": "암하라어", "ar": "아랍어", "as": "아삼어",
    "az": "아제르바이잔어", "ba": "바시키르어", "be": "벨라루스어", "bg": "불가리아어",
    "bn": "벵골어", "bo": "티베트어", "br": "브르타뉴어", "bs": "보스니아어",
    "ca": "카탈루냐어", "cs": "체코어", "cy": "웨일스어", "da": "덴마크어",
    "de": "독일어", "el": "그리스어", "en": "English", "es": "스페인어",
    "et": "에스토니아어", "eu": "바스크어", "fa": "페르시아어", "fi": "핀란드어",
    "fo": "페로어", "fr": "프랑스어", "gl": "갈리시아어", "gu": "구자라트어",
    "ha": "하우사어", "haw": "하와이어", "he": "히브리어", "hi": "힌디어",
    "hr": "크로아티아어", "ht": "아이티 크레올어", "hu": "헝가리어", "hy": "아르메니아어",
    "id": "인도네시아어", "is": "아이슬란드어", "it": "이탈리아어", "ja": "日本語",
    "jv": "자바어", "ka": "조지아어", "kk": "카자흐어", "km": "크메르어",
    "kn": "칸나다어", "ko": "한국어", "la": "라틴어", "lb": "룩셈부르크어",
    "ln": "링갈라어", "lo": "라오어", "lt": "리투아니아어", "lv": "라트비아어",
    "mg": "말라가시어", "mi": "마오리어", "mk": "마케도니아어", "ml": "말라얄람어",
    "mn": "몽골어", "mr": "마라티어", "ms": "말레이어", "mt": "몰타어",
    "my": "버마어", "ne": "네팔어", "nl": "네덜란드어", "nn": "노르웨이어(뉘노르스크)",
    "no": "노르웨이어", "oc": "오크어", "pa": "펀자브어", "pl": "폴란드어",
    "ps": "파슈토어", "pt": "포르투갈어", "ro": "루마니아어", "ru": "러시아어",
    "sa": "산스크리트어", "sd": "신디어", "si": "싱할라어", "sk": "슬로바키아어",
    "sl": "슬로베니아어", "sn": "쇼나어", "so": "소말리어", "sq": "알바니아어",
    "sr": "세르비아어", "su": "순다어", "sv": "스웨덴어", "sw": "스와힐리어",
    "ta": "타밀어", "te": "텔루구어", "tg": "타지크어", "th": "태국어",
    "tk": "투르크멘어", "tl": "타갈로그어", "tr": "튀르키예어", "tt": "타타르어",
    "uk": "우크라이나어", "ur": "우르두어", "uz": "우즈베크어", "vi": "베트남어",
    "yi": "이디시어", "yo": "요루바어", "yue": "광둥어", "zh": "중국어",
}

# 세그먼트 버튼에 늘 떠 있는 셋. 나머지는 + 드롭다운에서 고른다.
STT_QUICK = ("ko", "en", "ja")

_settings = dict(DEFAULTS)


def load():
    global _settings
    try:
        with open(SETTINGS_FILE, encoding="utf-8-sig") as f:
            _settings = {**DEFAULTS, **json.load(f)}
    except (FileNotFoundError, json.JSONDecodeError):
        _settings = dict(DEFAULTS)
    return _settings


def save():
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(_settings, f, indent=2, ensure_ascii=False)


def get(key):
    return _settings.get(key, DEFAULTS.get(key))


def set(key, value):
    _settings[key] = value
    save()


def system_prompt():
    lang = LANG_NAMES.get(get("language"), "Korean")
    return (
        f"You are a helpful study assistant. Always respond in {lang}. "
        "The user will often paste or dictate content they are studying — such as lecture notes, articles, or subtitles. "
        "Your job is to: (1) summarize the key points clearly and concisely, "
        "(2) explain any difficult or unfamiliar concepts in simple terms, "
        "(3) organize the information so it is easy to understand at a glance. "
        "If the content is in a foreign language, translate it first, then explain. "
        "Keep responses focused and avoid unnecessary filler."
    )


load()
