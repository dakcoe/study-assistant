"""Groq API 클라이언트 — 채팅 스트리밍 + 음성 인식.

Groq는 OpenAI 호환 엔드포인트를 쓴다.
  채팅: POST /openai/v1/chat/completions  (SSE 스트리밍)
  STT : POST /openai/v1/audio/transcriptions  (multipart)
"""

import io
import json
import os
import time
import wave

import requests

import config
from config import NO_THINK

BASE_URL = "https://api.groq.com/openai/v1"

# ── 모델 자동 전환 ────────────────────────────────────────────────────────────
# 한도는 모델마다 따로 잡힌다(실측: gpt-oss 1,000회 / llama-3.1-8b 14,400회).
# 그래서 429를 맞으면 다른 모델로 넘어가면 바로 이어서 쓸 수 있다.
# 막힌 모델은 잠시 건너뛰고, 시간이 지나면 원래 선호 모델로 저절로 돌아온다.
_cooldown = {}          # 모델 → 이 시각까지는 쓰지 않는다
COOLDOWN_MIN = 30
COOLDOWN_MAX = 600

# Groq가 모델을 갈아치우면 손으로 적어둔 CHAT_MODELS가 죽은 이름을 붙잡는다.
# (실제로 llama-3.x가 사라져 대체 모델이 전부 404가 됐고, 한도에 걸린 번역이
#  넘어갈 데가 없어 통째로 멈췄다.) 시작할 때 한 번 실제 목록과 맞춰 본다.
_available = None       # 확인된 모델 이름들. None이면 아직 확인 못 함
_catalog = None         # {"chat": [...], "whisper": [...]} — /models에서 분류한 것

MIN_CHAT_CTX = 8192     # 강의 노트를 붙여넣는 앱이라 문맥이 이보다 작으면 못 쓴다


def _classify(entry):
    """모델 하나를 chat / whisper / None(안 씀)으로 가른다.

    메타데이터만으로 여기까지는 갈린다:
      whisper : out=['transcription']         ctx 448
      chat    : out=['text'] + tools 지원 + 문맥이 큼
      제외    : out=['speech'](TTS), ctx 512짜리 분류기
    다만 '이 모델이 한국어를 잘 하는가', 'reasoning_effort를 뭘 받는가',
    'thinking이 답변에 새는가'는 메타데이터에 없다. 그건 NO_THINK 표에 손으로 적는다.
    """
    if entry["id"] in config.EXCLUDE_MODELS:
        return None
    out = entry.get("output_modalities") or []
    if "transcription" in out:
        return "whisper"
    if "text" not in out:
        return None                                  # TTS 등
    feats = entry.get("supported_features") or []
    if "tools" not in feats:
        return None                                  # 분류기·가드 모델
    if (entry.get("context_window") or 0) < MIN_CHAT_CTX:
        return None
    return "chat"


def _ordered(found, preferred):
    """손으로 정한 우선순위를 앞에 두고, 새로 생긴 모델을 뒤에 붙인다."""
    return ([m for m in preferred if m in found]
            + sorted(m for m in found if m not in preferred))


def chat_models():
    """지금 쓸 수 있는 채팅 모델. 확인 전이면 손으로 적은 목록."""
    return _catalog["chat"] if _catalog else list(config.CHAT_MODELS)


def whisper_models():
    return _catalog["whisper"] if _catalog else list(config.WHISPER_MODELS)


def refresh_available():
    """계정이 실제로 쓸 수 있는 모델을 확인하고 종류별로 갈라 둔다.

    네트워크가 없거나 응답이 이상하면 확인 전 상태로 남겨, 손으로 적은
    목록을 그대로 쓰게 한다 — 못 고르는 것보다 낫다.
    """
    global _available, _catalog
    try:
        resp = requests.get(f"{BASE_URL}/models",
                            headers={"Authorization": f"Bearer {_api_key()}"},
                            timeout=10)
        if resp.status_code != 200:
            return
        entries = [m for m in resp.json().get("data", []) if m.get("active", True)]
    except (requests.RequestException, ValueError, KeyError, GroqError):
        return

    names = {m["id"] for m in entries}
    if not names:
        return
    _available = names
    chat = {m["id"] for m in entries if _classify(m) == "chat"}
    whisper = {m["id"] for m in entries if _classify(m) == "whisper"}
    if chat and whisper:            # 둘 중 하나라도 비면 분류가 틀린 것이니 안 쓴다
        _catalog = {"chat": _ordered(chat, config.CHAT_MODELS),
                    "whisper": _ordered(whisper, config.WHISPER_MODELS)}


def _mark_limited(model, retry_after):
    wait = COOLDOWN_MIN
    try:
        wait = float(retry_after)
    except (TypeError, ValueError):
        pass
    _cooldown[model] = time.time() + min(max(wait, COOLDOWN_MIN), COOLDOWN_MAX)


def _model_chain(preferred):
    """선호 모델을 앞에 두고, 쿨다운이 안 걸린 나머지를 뒤에 붙인다."""
    ordered = [preferred] + [m for m in chat_models() if m != preferred]
    if _available:
        # 사라진 모델은 뺀다. 전부 빠지면 목록이 낡은 것이므로 선호 모델로 시도한다
        ordered = [m for m in ordered if m in _available] or ordered[:1]
    now = time.time()
    usable = [m for m in ordered if _cooldown.get(m, 0) <= now]
    return usable or ordered[:1]     # 전부 막혔으면 선호 모델로 한 번은 시도


# ── 남은 한도 ────────────────────────────────────────────────────────────────
# Groq는 응답 헤더에 남은 양을 실어 준다. 앱이 어차피 보내는 요청에서 주워
# 두면 따로 물어볼 필요가 없다. 일일 토큰(TPD)은 헤더에 없고 초과했을 때
# 에러 메시지에만 나오므로, 막혔다는 사실만 따로 기록한다.
_limits = {}            # 모델 → {"requests": (남은, 한도), "audio": (남은, 한도),
                        #        "at": 시각, "blocked": 사유 or None}


def _note_limits(model, headers, blocked=None, probe=False):
    """헤더에 실린 남은 양을 적어 둔다.

    probe=True는 남은 양을 보려고 일부러 보낸 요청이다. 헤더 값에는 그 요청이
    이미 반영돼 있어서, 그대로 보여주면 확인할 때마다 숫자가 1씩 줄어든다.
    확인 행위 자체가 결과를 바꾸지 않도록 그 1개만 되돌려 적는다.

    누적으로 되돌리지는 않는다. 그러려면 셈을 언제 지울지 정해야 하는데
    그 기준이 없다 — 새로고침을 여러 번 누르면 실제로 그만큼 줄어드는 게 맞다.
    """
    def pair(name):
        try:
            return (float(headers[f"x-ratelimit-remaining-{name}"]),
                    float(headers[f"x-ratelimit-limit-{name}"]))
        except (KeyError, TypeError, ValueError):
            return None

    info = _limits.setdefault(model, {})
    for key, name in (("requests", "requests"), ("audio", "audio-seconds")):
        got = pair(name)
        if got:
            left, total = got
            if probe and key == "requests":
                left = min(left + 1, total)
            info[key] = (left, total)
    info["at"] = time.time()
    info["blocked"] = blocked


def limits_snapshot():
    """설정 창에 보여줄 사본. 스레드 사이로 넘기므로 얕게 복사해 준다."""
    return {m: dict(v) for m, v in _limits.items()}


def probe_limits():
    """각 모델에 최소 크기 요청을 보내 남은 한도를 새로 받아온다.

    채팅은 프롬프트 3토큰 + 출력 1토큰, 음성은 1초짜리 무음을 보낸다. 둘 다
    요청을 하나씩 쓰지만, 그만큼을 되돌려 적으므로 화면 숫자는 줄지 않는다.
    """
    key = _api_key()
    head = {"Authorization": f"Bearer {key}"}

    for model in chat_models():
        body = {"model": model, "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1}
        params, _always = NO_THINK.get(model, (None, False))
        if params:
            body.update(params)
        try:
            r = requests.post(f"{BASE_URL}/chat/completions", headers=head,
                              json=body, timeout=20)
            _note_limits(model, r.headers, probe=True,
                         blocked=_explain(r) if r.status_code != 200 else None)
        except requests.RequestException:
            pass

    silence = pcm_to_wav(b"\x00" * 32000)      # 1초
    for model in whisper_models():
        try:
            r = requests.post(f"{BASE_URL}/audio/transcriptions", headers=head,
                              files={"file": ("probe.wav", silence, "audio/wav")},
                              data={"model": model, "response_format": "json"},
                              timeout=30)
            _note_limits(model, r.headers, probe=True,
                         blocked=_explain(r) if r.status_code != 200 else None)
        except requests.RequestException:
            pass



# ── 앱이 직접 세는 사용량 ────────────────────────────────────────────────────
# 하루 토큰(TPD)과 하루 오디오(ASD)는 응답 헤더에 안 온다. 초과했을 때 에러로만
# 알 수 있어서, 보낸 만큼을 여기서 쌓는다. 값은 추정이 아니라 Groq가 응답에
# 실어 준 것이다 — 채팅은 마지막 스트림 청크의 usage, 음성은 verbose_json의
# duration.
#
# 한도는 자정에 초기화되지 않고 계속 조금씩 차오른다. 상한이 하루 20만이면
# 초당 2.31씩, 시간당 8,333씩 돌아온다. 그래서 저장하는 것은 지금 차 있는 양과
# 그 값을 적은 시각 둘뿐이다 — 쓸 때 더하고, 볼 때 그동안 흐른 시간만큼 뺀다.
USAGE_FILE = os.path.join(config.APP_DIR, "usage.json")
WINDOW = 24 * 3600      # 상한만큼 회복되는 데 걸리는 시간
_usage = {}             # "모델|종류" → [차 있는 양, 그때 시각]
_usage_saved_at = 0.0


def _rate(kind):
    """초당 회복량. 쓴 양에 비례하지 않고 일정하다."""
    return config.DAILY_CAPS[kind] / WINDOW


def _usage_load():
    """저장된 사용량을 읽는다. 옛 형식이면 수위 하나로 접어서 옮긴다."""
    global _usage
    try:
        with open(USAGE_FILE, encoding="utf-8") as f:
            _usage = json.load(f)
    except (OSError, ValueError):
        _usage = {}
        return

    now = time.time()
    for key, rows in list(_usage.items()):
        if not (rows and isinstance(rows[0], list)):
            continue                        # 이미 새 형식 [수위, 시각]
        # 옛 형식: 호출마다 [시각, 양] 한 줄. 되짚어 지금 수위를 구한다.
        kind = key.split("|")[-1]
        if kind not in config.DAILY_CAPS:
            del _usage[key]
            continue
        rate = _rate(kind)
        level, last = 0.0, None
        for ts, amount in sorted(r for r in rows if now - r[0] < WINDOW):
            if last is not None:
                level = max(0.0, level - rate * (ts - last))
            level += amount
            last = ts
        _usage[key] = [max(0.0, level - rate * (now - last)) if last else 0.0, now]


def _usage_save(force=False):
    global _usage_saved_at
    now = time.time()
    if not force and now - _usage_saved_at < 5:
        return                      # 조각마다 쓰면 강의 한 번에 수백 번이다
    _usage_saved_at = now
    try:
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump(_usage, f)
    except OSError:
        pass                        # 못 써도 앱은 계속 돈다


def note_usage(model, kind, amount):
    """쓴 양을 수위에 더한다. kind는 "tokens" 또는 "audio"(초)."""
    if not amount:
        return
    key = f"{model}|{kind}"
    now = time.time()
    level, at = _usage.get(key, [0.0, now])
    _usage[key] = [max(0.0, level - _rate(kind) * (now - at)) + float(amount), now]
    _usage_save()


def usage_level(model, kind, now=None):
    """지금 차 있는 양. 마지막 기록 이후 회복된 만큼을 뺀다.

    0 아래로는 내려가지 않는다 — 안 쓰고 둔다고 한도가 늘지는 않는다.
    """
    row = _usage.get(f"{model}|{kind}")
    if not row:
        return 0.0
    now = time.time() if now is None else now
    level, at = row
    return max(0.0, level - _rate(kind) * (now - at))


_usage_load()


class GroqError(Exception):
    pass


def _api_key():
    key = config.get("groq_api_key").strip()
    if not key:
        raise GroqError("Groq API 키가 없습니다. ⚙ 설정에서 키를 입력하세요.")
    return key


def _explain(resp):
    """HTTP 에러를 사람이 읽을 수 있는 메시지로."""
    if resp.status_code == 401:
        return "API 키가 올바르지 않습니다. ⚙ 설정에서 다시 확인하세요."
    if resp.status_code == 429:
        return "Groq 무료 한도(분당/일일)를 초과했습니다. 잠시 후 다시 시도하세요."
    try:
        msg = resp.json().get("error", {}).get("message", "")
    except Exception:
        msg = resp.text[:200]
    return f"Groq 오류 {resp.status_code}: {msg}"


# ── 채팅 ─────────────────────────────────────────────────────────────────────

def stream_chat(messages, model=None, chunk_callback=None, done_callback=None,
                temperature=None, max_tokens=None, fallback_callback=None,
                no_think=False):
    """채팅 응답을 스트리밍한다. 한도(429)에 걸리면 다른 모델로 자동 전환한다.

    messages: 시스템 프롬프트를 포함한 전체 대화 이력
    model: 선호 모델. 지정해도 한도에 걸리면 나머지 모델로 넘어간다
    no_think: 추론 과정을 끈다. 번역처럼 생각할 게 없는 작업의 토큰을 크게 아낀다
    chunk_callback(str): 토큰이 올 때마다 호출
    done_callback(): 스트림이 끝나면 호출 (에러로 끝나도 호출)
    fallback_callback(막힌모델, 대체모델): 모델을 바꿔 재시도할 때 호출
    """
    # model은 "이것만"이 아니라 "이걸 먼저"다 — 한도에 걸리면 나머지로 이어간다
    chain = _model_chain(model or config.get("chat_model"))
    last_error = None

    for i, current in enumerate(chain):
        try:
            return _stream_one(current, messages, chunk_callback, done_callback,
                               temperature, max_tokens, no_think)
        except (RateLimited, Unavailable) as e:
            if isinstance(e, RateLimited):
                _mark_limited(current, e.retry_after)
                last_error = GroqError(
                    f"'{current}' 한도를 초과했고 대체할 모델도 없습니다. "
                    f"잠시 후 다시 시도하세요.")
            else:
                # 용량 문제는 곧 풀린다. 잠깐만 피했다가 원래 모델로 돌아간다.
                _mark_limited(current, 60)
                last_error = GroqError(str(e))
            if i + 1 < len(chain):
                if fallback_callback:
                    fallback_callback(current, chain[i + 1])
                continue
            break

    if done_callback:
        done_callback()
    raise last_error or GroqError("요청에 실패했습니다")


OPEN, CLOSE = "<think>", "</think>"


def _strip_think(chunk, state):
    """스트리밍 조각에서 <think>…</think> 안쪽을 걷어낸다.

    태그가 두 조각에 걸쳐 오므로(예: "앞 <thi" / "nk>속마음") 꼬리 몇 글자를
    붙들어 뒀다가 다음 조각에 이어 붙인다. 안 그러면 잘린 태그가 그대로 샌다.

    state는 (블록 안인가, 붙들어 둔 꼬리). 스트림이 끝나면 flush_think로 비운다.
    """
    thinking, tail = state
    buf, out = tail + chunk, []
    while buf:
        if thinking:
            end = buf.find(CLOSE)
            if end < 0:
                keep = len(CLOSE) - 1
                return "".join(out), (True, buf[-keep:] if len(buf) > keep else buf)
            buf, thinking = buf[end + len(CLOSE):], False
        else:
            start = buf.find(OPEN)
            if start < 0:
                keep = len(OPEN) - 1        # 여는 태그가 잘렸을 수 있는 만큼만 남긴다
                out.append(buf[:-keep] if len(buf) > keep else "")
                return "".join(out), (False, buf[-keep:] if len(buf) > keep else buf)
            out.append(buf[:start])
            buf, thinking = buf[start + len(OPEN):], True
    return "".join(out), (thinking, "")


def flush_think(state):
    """스트림이 끝났을 때 붙들고 있던 꼬리를 돌려준다."""
    thinking, tail = state
    return "" if thinking else tail


class Unavailable(Exception):
    """모델이 잠깐 응답을 못 한다(5xx·용량 초과). 한도와 달리 내 잘못이 아니므로
    바로 다음 모델로 넘긴다. qwen3.6이 "over capacity" 503을 낸 적이 있다."""


class RateLimited(Exception):
    def __init__(self, retry_after=None):
        super().__init__("rate limited")
        self.retry_after = retry_after


def _stream_one(model, messages, chunk_callback, done_callback,
                temperature, max_tokens, no_think=False):
    body = {"model": model, "messages": messages, "stream": True}
    # 모델이 모르는 값을 주면 400이므로 표에 있는 모델에만 붙인다
    params, always = NO_THINK.get(model, (None, False))
    if params and (no_think or always):
        body.update(params)
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    think = (False, "")     # (<think> 안인가, 붙들어 둔 꼬리)
    try:
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {_api_key()}"},
            json=body,
            stream=True,
            timeout=120,
        )
        _note_limits(model, resp.headers,
                     blocked=_explain(resp) if resp.status_code != 200 else None)
        if resp.status_code == 429:
            # 스트림이 시작되기 전이므로 다른 모델로 안전하게 재시도할 수 있다
            raise RateLimited(resp.headers.get("retry-after"))
        if resp.status_code >= 500:
            # 503 "over capacity" 같은 것. 내 한도와 무관하니 다음 모델로 넘긴다.
            raise Unavailable(_explain(resp))
        if resp.status_code != 200:
            raise GroqError(_explain(resp))

        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8", "replace")
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            used = (data.get("usage")
                    or data.get("x_groq", {}).get("usage") or {}).get("total_tokens")
            if used:
                note_usage(model, "tokens", used)
            choices = data.get("choices") or [{}]
            delta = choices[0].get("delta", {})
            content = delta.get("content")
            if not content:
                continue
            # 모르는 모델이 사고 과정을 본문에 흘리는 일이 있다(qwen3.6이 그랬다).
            # NO_THINK 표에 없는 새 모델에도 통하도록 여기서 걷어낸다.
            content, think = _strip_think(content, think)
            if content and chunk_callback:
                chunk_callback(content)

        rest = flush_think(think)
        if rest and chunk_callback:
            chunk_callback(rest)
        if done_callback:
            done_callback()
    except RateLimited:
        # 아직 아무것도 못 받았으니 다른 모델로 재시도한다.
        # 여기서 done_callback을 부르면 UI가 응답이 끝난 줄 알고 종료해 버린다.
        raise
    except requests.RequestException as e:
        if done_callback:
            done_callback()
        raise GroqError(f"네트워크 오류: {e}")
    except Exception:
        if done_callback:
            done_callback()
        raise


# ── 음성 인식 ────────────────────────────────────────────────────────────────

def pcm_to_wav(pcm_bytes, sample_rate=16000):
    """16-bit mono PCM → WAV 바이트."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


def transcribe(wav_bytes, language=None, model=None, prompt=None,
               fallback_callback=None):
    """WAV 바이트를 Groq Whisper로 인식해 텍스트를 반환한다.

    한도(429)에 걸리면 다른 Whisper 모델로 자동 전환한다. 수업 중에 인식이
    멈추면 그 구간을 통째로 잃기 때문에, 품질이 조금 낮아도 이어가는 편이 낫다.
    """
    preferred = model or config.get("whisper_model")
    if model:
        chain = [model]
    else:
        ordered = [preferred] + [m for m in whisper_models() if m != preferred]
        now = time.time()
        chain = [m for m in ordered if _cooldown.get(m, 0) <= now] or ordered[:1]

    last = None
    for i, current in enumerate(chain):
        try:
            return _transcribe_one(wav_bytes, current, language, prompt)
        except RateLimited as e:
            _mark_limited(current, e.retry_after)
            last = GroqError(
                f"'{current}' 음성 인식 한도를 초과했고 대체할 모델도 없습니다.")
            if i + 1 < len(chain):
                if fallback_callback:
                    fallback_callback(current, chain[i + 1])
                continue
            break
    raise last or GroqError("음성 인식에 실패했습니다")


def _transcribe_one(wav_bytes, model, language, prompt):
    # verbose_json이어야 duration이 온다. 우리가 만든 WAV 길이로 어림잡는 대신
    # Groq가 센 값을 그대로 쓴다.
    data = {"model": model, "response_format": "verbose_json", "temperature": "0"}
    if language:
        data["language"] = language
    if prompt:
        # 직전 문맥을 주면 고유명사/용어 인식률이 올라간다
        data["prompt"] = prompt[-400:]

    try:
        resp = requests.post(
            f"{BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {_api_key()}"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data=data,
            timeout=60,
        )
    except requests.RequestException as e:
        raise GroqError(f"네트워크 오류: {e}")

    _note_limits(model, resp.headers,
                 blocked=_explain(resp) if resp.status_code != 200 else None)
    if resp.status_code == 429:
        raise RateLimited(resp.headers.get("retry-after"))
    if resp.status_code != 200:
        raise GroqError(_explain(resp))

    body = resp.json()
    note_usage(model, "audio", body.get("duration") or 0)
    return body.get("text", "").strip()


def check_key(key):
    """설정 창에서 키를 검증한다. (ok: bool, 메시지: str)"""
    key = key.strip()
    if not key:
        return False, "키가 비어 있습니다."
    try:
        resp = requests.get(
            f"{BASE_URL}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
    except requests.RequestException as e:
        return False, f"네트워크 오류: {e}"
    if resp.status_code == 200:
        return True, "키 확인됨"
    return False, _explain(resp)
