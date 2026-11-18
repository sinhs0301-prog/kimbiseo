# 두뇌 — OpenAI 호환 주소(기본: 이 PC 의 llama-server, Gemma 4 E4B Q4_K_M)·GPT·클로드.
#   방식(설정 두뇌.방식): local = 이 PC llama-server(두뇌.주소) / url = 다른 OpenAI 호환 주소 / openai = GPT(열쇠) / claude = 클로드(열쇠)
#                         / claude_cli·codex_cli = 구독 두뇌(같은 PC 의 claude·codex 명령, core/cli_brain.py).
#   열쇠는 core/keystore(사용자 PC 의 DPAPI 파일·환경변수)에서만 읽는다 — 설정·로그·저장소에 쓰지 않음.
#   모드(두뇌.모드): '빠른' = 생각 끔(기본, 첫마디 빠름) / '꼼꼼' = 생각 켬(chat_template_kwargs.enable_thinking).
#   글로 쓴 도구 호출 건지기(두뇌.글로쓴호출_건지기): 작은 모델이 도구 호출 표시 없이 `get_weather{day:...}` ·
#     `get_weather(day=tomorrow, place=서울)` · `calc(32000+14000)` 처럼 글로 쓰면(답 맨 앞이든 한 문장 뒤든)
#     brain/tool_text_rescue.CallSplitter 가 그 부분을 떼어 진짜 도구 호출로 바꾼다. 호출 꼴인데 읽을 수 없으면 버린다
#     (화면·목소리로 함수 글이 나가지 않게). 보통 글은 바로 흘려보내고, 호출의 시작일 수 있는 몇 글자만 잠깐 잡는다.
#   약속만 한 답 다시 묻기(local·url): 도구가 필요한 부탁(켜·열어·검색·적어…)에 도구 없이 '열어 드릴게요'처럼 약속만 하고 끝나면
#     같은 문맥으로 한 번 더 묻되 tool_choice=required(도구를 꼭 부르게) — 사용자 말 하나당 2번까지. 그래도 말뿐이면 그 차례(사용자 말 +
#     약속)는 다음 요청의 대화 기록에서 뺀다(작은 두뇌는 한 번 말만 하면 그 대화 내내 말만 하는 버릇이 생김). 몸동작 부탁(춤…)은 제외.
#     다시 물을 수도 있는 차례(도구가 필요한 부탁)는 첫 답의 글을 끝날 때까지 잡아 두었다가, 다시 물으면 버리고(두 번 말하지 않게)
#     안 물으면 그대로 내보낸다. 도구를 부르면 잡아 둔 글을 먼저 내보낸다.
#   행동 도구(켜기·메모장 쓰기·계산·기억…) 결과 뒤 답(local·url)도 끝까지 잡아 두고 살핀다(fix_after_tool): 앞의 '김비서입니다.'·'안녕하세요.'는 떼고,
#     비었거나·사용자 말을 그대로 따라 했거나·(켜기·쓰기 뒤) 결과에 없는 숫자를 지어냈으면 도구 결과의 짧은 말로 바꾼다.
#   글 거르기: <think> 블록·중국어 낱말(filters.py).
#   캐시(같은 앞부분은 다시 읽지 않게):
#     · 지시문+도구 정의+기억 블록이 맨 앞에 고정(prompt.py), 지금 시각은 사용자 말 끝 꼬리표로 한 번만 붙여 대화에 그대로 둔다.
#     · local/url: cache_prompt + id_slot(대화마다 같은 칸) + timings_per_token. GPT: prompt_cache_key. 클로드: cache_control.
#     · 캐시 오염 가드(local): 응답 첫 조각의 timings.cache_n(캐시로 다시 쓴 토큰 수)이 '이번 요청과 지금까지 보낸 요청들의
#       공통 앞부분 토큰 수'(/apply-template 로 그린 글의 공통 앞부분을 /tokenize)보다 크면, 다른 대화 내용을 이어 쓴 것으로 보고
#       그 응답을 버린 뒤 경고를 남기고 cache_prompt 를 끈 채 다시 묻는다(이 대화는 그 뒤로 캐시 끔). 글은 가드 판정 뒤에야 내보냄.
import asyncio
import collections
import json
import os
import re
import time
import uuid

import httpx
from loguru import logger
from pipecat.frames.frames import FunctionCallFromLLM, LLMContextFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService

from . import config as C
from . import debate
from . import i18n, keystore
from .filters import HanziFilter, ThinkFilter
from .memory import TIME_TAG
from .prompt import now_tag


def _load_rescue():
    import importlib.util
    spec = importlib.util.spec_from_file_location("kimbiseo_tool_text_rescue",
                                                  os.path.join(C.REPO, "brain", "tool_text_rescue.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RESCUE = _load_rescue()
rescue = RESCUE.rescue
DROP_SAY = "잠깐 말이 꼬였어요. 한 번만 다시 말씀해 주세요."
GUARD_SLACK = 16   # 토큰 경계·BOS 차이 허용


class CacheGuard:
    """한 두뇌 서버(llama-server)에 보낸 요청 글(그린 프롬프트 + 받은 답)을 기억해, 캐시 재사용이 맞는지 본다.
    본체 하나가 그 서버를 혼자 쓴다고 본다(다른 프로그램이 같은 서버를 쓰면 가드가 지나치게 조심할 수 있음 — 그때는 캐시를 끔)."""

    def __init__(self, base_url, keep=8):
        root = re.sub(r"/v1/?$", "", base_url.rstrip("/"))
        self.root = root
        self.hist = collections.deque(maxlen=keep)   # 그린 프롬프트 + 그 답 글
        self.ok = True                               # /apply-template·/tokenize 가 없으면 False(가드 못 함)
        self.trips = 0
        self.checks = 0
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))

    async def render(self, params):
        body = {"messages": params.get("messages") or []}
        if params.get("tools"):
            body["tools"] = params["tools"]
        eb = params.get("extra_body") or {}
        if eb.get("chat_template_kwargs"):
            body["chat_template_kwargs"] = eb["chat_template_kwargs"]
        r = await self.http.post(self.root + "/apply-template", json=body)
        r.raise_for_status()
        return r.json()["prompt"]

    async def n_tokens(self, text):
        if not text:
            return 0
        r = await self.http.post(self.root + "/tokenize", json={"content": text})
        r.raise_for_status()
        return len(r.json().get("tokens") or [])

    async def allowed(self, rendered):
        """캐시로 다시 써도 되는 최대 토큰 수.
        ① 지금까지 보낸 요청(+받은 답 글)과의 가장 긴 공통 앞부분.
        ② 이번 요청이 앞 요청 P 를 통째로 이어 쓴 것이면(같은 대화의 다음 차례) 서버 칸에는 P 와 그때 두뇌가 만든 토큰 G 가
           있으므로 |P| + |G| 까지(도구 호출은 답 글이 없어 ①만으로는 모자람 — 시험에서 21토큰 차이로 헛걸림)."""
        best, ext, ext_gen = "", "", 0
        for prompt, full, gen in self.hist:
            p = os.path.commonprefix([full, rendered])
            if len(p) > len(best):
                best = p
            if gen and len(prompt) > len(ext) and rendered.startswith(prompt):
                ext, ext_gen = prompt, gen
        n = await self.n_tokens(best)
        if ext:
            n = max(n, await self.n_tokens(ext) + int(ext_gen))
        return n

    def remember(self, rendered, reply_text="", gen_tokens=0):
        if rendered:
            self.hist.append((rendered, rendered + (reply_text or ""), int(gen_tokens or 0)))


def _plain_assistant(m):
    return (isinstance(m, dict) and m.get("role") == "assistant" and not m.get("tool_calls")
            and isinstance(m.get("content"), str))


def tidy_messages(msgs):
    """두뇌에 보내는 사본만 다듬는다(대화 문맥 자체는 그대로).
    ① 끝에 붙은 비서 글(도구 앞 한마디 '잠깐 날씨 볼게요' 등)은 뺀다 — llama-server 는 끝이 비서 말이면 그 말을 '이어 쓰기'로 받는다.
    ② 이어진 비서 글 두 개(앞 한마디 + 답)는 하나로 합친다 — 차례가 번갈아야 하는 채팅 틀이 있음."""
    out = []
    for m in msgs:
        if out and _plain_assistant(m) and _plain_assistant(out[-1]):
            out[-1] = {**out[-1], "content": (out[-1]["content"].rstrip() + " " + m["content"].lstrip()).strip()}
            continue
        out.append(m)
    while len(out) > 1 and _plain_assistant(out[-1]) and any(isinstance(x, dict) and x.get("role") in ("user", "tool") for x in out):
        out.pop()
    return out


def _timings(chunk):
    ex = getattr(chunk, "model_extra", None) or {}
    t = ex.get("timings") if isinstance(ex, dict) else None
    return t if isinstance(t, dict) and "cache_n" in t else None


class BrainLLM(OpenAILLMService):
    """OpenAI 호환 두뇌 + 글로 쓴 도구 호출 건지기 + 글 거르기 + 캐시 가드."""

    supports_developer_role = False

    def __init__(self, state, cfg, tool_names=(), guard=None, slot=0, cache_key="", **kw):
        super().__init__(**kw)
        self.state = state
        self.cfg = cfg
        b = cfg["두뇌"]
        self.kind = str(b.get("방식") or "local")
        self.mode = str(b.get("모드") or "빠른")
        self.tool_names = list(tool_names)
        self.do_rescue = bool(b.get("글로쓴호출_건지기", True))
        self.guard = guard
        self.slot = int(slot)
        self.cache_key = cache_key or uuid.uuid4().hex[:12]
        self.cache_off = not bool(b.get("캐시", True))
        self.last_timing = None      # 마지막 응답의 {cache_n, prompt_n, ttft_ms}
        self.timing_log = []
        self.cur_user_key = None
        self.rescued = 0
        self.dropped = 0
        self.tool_first = {}         # 도구 → 이름 없이 준 인자 하나를 넣을 칸(registry.register 가 도구 정의에서 채움)
        self._think = ThinkFilter()
        self._hanzi = HanziFilter()
        self._split = None
        self._pushed = False
        self._said = []              # 이번 답에서 내보낸 글(약속만 했는지 보려고)
        self._raw = []               # 같은 글의 원래 모양(도구 이름을 쉬운 말로 바꾸기 전)
        self._dropped = False        # 이번 답에 읽을 수 없는 호출 꼴이 있었나
        self._called = False         # 이번 답에서 진짜 도구 호출이 있었나
        self._force_tool = False     # 다시 물을 때 tool_choice=required
        self._hold = None            # 다시 물을 수도 있는 첫 답: 내보내지 않고 잡아 둔 글(list) / 안 잡으면 None
        self._body_ask = ""          # 이번 사용자 말이 펫 몸동작 부탁이면 그 짧은 답('네, 춰 볼게요!')
        self._retries = {}           # 사용자 말 → 다시 물은 횟수
        self._turn_tools = {}        # 사용자 말 → 그 말에 부른 도구 이름들
        self.retried = 0

    # ---------------- 요청 만들기
    def build_chat_completion_params(self, params_from_context):
        params = super().build_chat_completion_params(params_from_context)
        if isinstance(params.get("messages"), list):
            params["messages"] = tidy_messages(params["messages"])
            if self.kind in ("local", "url"):
                params["messages"] = drop_promise_turns(params["messages"])
        b = self.cfg["두뇌"]
        eb = dict(b.get("추가") or {})
        st = self.state
        if debate.on(st):
            # 말싸움: 지난 기록·도구 결과의 개인 값과 개인 도구를 두뇌에 안 넘긴다(core/debate.py).
            if isinstance(params.get("messages"), list):
                params["messages"] = debate.filter_messages(params["messages"], st)
            if isinstance(params.get("tools"), list):
                kept = debate.filter_tools(params["tools"], self.cfg)
                if kept:
                    params["tools"] = kept
                else:
                    params.pop("tools", None)
                    params.pop("tool_choice", None)
        if params.get("tools") and (getattr(st, "stop_now", False)
                                    or (st.no_tools_key is not None and st.no_tools_key == self.cur_user_key)):
            params["tool_choice"] = "none"   # '그만' 뒤·도구 폭주로 멈춘 그 질문: 도구 없이 답하게(서버에서 강제)
        elif params.get("tools") and self._force_tool:
            params["tool_choice"] = "required"   # 약속만 한 답 다시 묻기: 이번에는 도구를 꼭 부르게
        if self.kind in ("local", "url"):
            ctk = dict(eb.get("chat_template_kwargs") or {})
            ctk["enable_thinking"] = self.mode == "꼼꼼"
            eb["chat_template_kwargs"] = ctk
            eb.setdefault("cache_prompt", not self.cache_off)
            if not self.cache_off:
                eb.setdefault("id_slot", self.slot)
            eb.setdefault("timings_per_token", True)
        elif self.kind == "openai" and not self.cache_off:
            eb.setdefault("prompt_cache_key", "kimbiseo-" + self.cache_key)
        if self._no_cache_once:
            eb["cache_prompt"] = False
            eb.pop("id_slot", None)
        params["extra_body"] = {**(params.get("extra_body") or {}), **eb}
        for k in ("frequency_penalty", "presence_penalty", "seed", "top_p", "max_completion_tokens", "service_tier"):
            if params.get(k) is None or type(params.get(k)).__name__ == "NotGiven":
                params.pop(k, None)
        return params

    _no_cache_once = False

    async def get_chat_completions(self, context):
        if self.kind != "local" or self.guard is None or not self.guard.ok:
            return await super().get_chat_completions(context)
        return self._guarded_stream(context)

    async def _guarded_stream(self, context):
        """첫 timings 조각에서 캐시 재사용이 맞는지 확인한 뒤에야 조각을 내보낸다(어긋나면 버리고 캐시 끄고 다시)."""
        adapter = self.get_llm_adapter()
        for attempt in range(2):
            pfc = await adapter.get_llm_invocation_params(context, system_instruction=self._settings.system_instruction,
                                                          convert_developer_to_user=not self.supports_developer_role)
            params = self.build_chat_completion_params(pfc)
            cache_on = bool((params.get("extra_body") or {}).get("cache_prompt"))
            t0 = time.perf_counter()
            render_task = asyncio.ensure_future(self.guard.render(params)) if self.guard.ok else None
            stream = await self._client.chat.completions.create(**params)
            held, checked, reply, last_tm = [], False, [], None
            rendered = None
            redo = False
            try:
                async for chunk in stream:
                    if not checked:
                        tm = _timings(chunk)
                        if tm is None and not (chunk.choices and chunk.choices[0].delta
                                               and (chunk.choices[0].delta.content or chunk.choices[0].delta.tool_calls)):
                            held.append(chunk)
                            continue
                        checked = True
                        ttft = (time.perf_counter() - t0) * 1000
                        info = {"cache_n": (tm or {}).get("cache_n"), "prompt_n": (tm or {}).get("prompt_n"),
                                "ttft_ms": round(ttft), "cache": cache_on}
                        try:
                            rendered = await render_task if render_task else None
                            if cache_on and rendered is not None and tm is not None:
                                allow = await self.guard.allowed(rendered)
                                info["allowed"] = allow
                                self.guard.checks += 1
                                if int(tm.get("cache_n") or 0) > allow + GUARD_SLACK:
                                    self.guard.trips += 1
                                    logger.warning(f"두뇌 캐시 오염 의심: 다시 쓴 토큰 {tm.get('cache_n')} > 공통 앞부분 {allow} "
                                                   f"→ 이 답 버리고 캐시 끈 채 다시 묻기(이 대화는 캐시 끔)")
                                    self.state.event("cache_guard", cache_n=tm.get("cache_n"), allowed=allow)
                                    self.cache_off = True
                                    redo = True
                        except Exception as ex:  # noqa: BLE001
                            logger.info(f"캐시 가드를 쓸 수 없음(두뇌 서버가 apply-template·tokenize 를 모름) → 가드 끔: {ex.__class__.__name__}")
                            self.guard.ok = False
                        self.last_timing = info
                        self.timing_log.append(info)
                        if redo:
                            break
                        for h in held:
                            yield h
                        held = []
                    tl = _timings(chunk)
                    if tl is not None:
                        last_tm = tl
                    d = chunk.choices[0].delta if chunk.choices else None
                    if d is not None and d.content:
                        reply.append(d.content)
                    yield chunk
            finally:
                try:
                    await stream.close()
                except Exception:  # noqa: BLE001
                    pass
                if render_task is not None and not render_task.done():
                    render_task.cancel()
                if rendered is not None and not redo:
                    self.guard.remember(rendered, "".join(reply), int((last_tm or {}).get("predicted_n") or 0) + 1)
            if not redo:
                return

    # ---------------- 응답 처리
    async def _emit(self, text):
        if text:
            self._said.append(text)
            if self._hold is not None:
                self._hold.append(text)
                return
            self._pushed = True
            await super()._push_llm_text(text)

    async def _flush_hold(self):
        held, self._hold = self._hold, None
        for t in held or ():
            self._pushed = True
            await super()._push_llm_text(t)

    def _after_action(self, msgs):
        """방금 온 것이 행동 도구 결과인가(그 뒤 답을 잡아 두고 살필지)."""
        return self.kind in ("local", "url") and bool(set(last_tool_names(msgs)) & ACTION_TOOLS)

    def _may_retry(self, um):
        """이번 차례에 다시 물을 가능성이 있나(첫 답 글을 잡아 둘지)."""
        st = self.state
        if self.kind not in ("local", "url") or not self.tool_names or um is None:
            return False
        if getattr(st, "stop_now", False) or (st.no_tools_key is not None and st.no_tools_key == self.cur_user_key):
            return False
        user = str(um.get("content") or "")
        if self._retries.get(self.cur_user_key, 0) >= 2 or not RESCUE.wants_action(user):
            return False
        msgs = getattr(self, "_ctx_msgs", None) or []
        if msgs and isinstance(msgs[-1], dict) and msgs[-1].get("role") == "tool":   # 결과 뒤: 메모장 쓰기가 빠진 때만 다시 물음
            return "type_text" in self.tool_names and "type_text" not in self._turn_tools.get(self.cur_user_key, ())                 and bool(RESCUE.MEMO_WANT.search(user))
        return bool(RESCUE.strong_action(user))   # '켜·열어·검색·계산…' — 말로만 답해도 다시 묻는 부탁(약속 글은 짧아 안 잡아도 됨)

    async def run_function_calls(self, function_calls):
        if function_calls:
            self._called = True
            if self._hold is not None:
                await self._flush_hold()
            got = self._turn_tools.setdefault(self.cur_user_key, set())
            got.update(getattr(c, "function_name", "") for c in function_calls)
            if len(self._turn_tools) > 50:
                self._turn_tools = {self.cur_user_key: got}
        return await super().run_function_calls(function_calls)

    def _my_name(self):
        try:
            return C.names(self.cfg)[0]
        except Exception:  # noqa: BLE001
            return ""

    def _should_retry(self, um):
        """도구 없이 약속만 했나 → 한 번 더(tool_choice=required) 물을까."""
        st = self.state
        if self.kind not in ("local", "url") or not self.tool_names or self._called or um is None:
            return False
        if getattr(st, "stop_now", False) or (st.no_tools_key is not None and st.no_tools_key == self.cur_user_key):
            return False
        if self._retries.get(self.cur_user_key, 0) >= 2:
            return False
        msgs = getattr(self, "_ctx_msgs", None) or []
        after_tool = bool(msgs) and isinstance(msgs[-1], dict) and msgs[-1].get("role") == "tool"
        return RESCUE.need_retry(str(um.get("content") or ""), "".join(self._said), "".join(self._raw), self.tool_names,
                                 dropped=self._dropped, after_tool=after_tool, called=self._turn_tools.get(self.cur_user_key, ()))

    async def _push_llm_text(self, text):
        t = self._think.feed(text)
        if t:
            t = self._hanzi.feed(t)
        if not t:
            return
        self._raw.append(t)
        if self._split is not None:
            t = self._split.feed(t)
        await self._emit(t)

    def _tag_time(self, context):
        """마지막 사용자 말에 지금 시각 꼬리표를 한 번 붙여 대화에 그대로 둔다(앞부분이 다음 차례에도 같게)."""
        msgs = context.messages
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                c = m.get("content")
                if isinstance(c, str) and not TIME_TAG.search(c):
                    m["content"] = c + "\n" + now_tag()
                self.cur_user_key = id(m)
                return m
        return None

    async def _slow_note(self, key):
        b = self.cfg["두뇌"]
        sec = float(b.get("생각_먼저할말_초", 6) or 0)
        words = list(b.get("생각_먼저할말") or [])
        if sec <= 0 or not words:
            return
        await asyncio.sleep(sec)
        if not self._pushed and self.cur_user_key == key and self.state.pre_key != key and not self._body_ask:   # 몸동작 부탁엔 '잠깐만요' 안 함
            self.state.pre_key = key
            await self.push_frame(TTSSpeakFrame(words[int(time.time()) % len(words)], append_to_context=False))

    async def _process_context(self, context):
        self._pushed = False
        um = self._tag_time(context)
        self._ctx_msgs = context.messages
        st = self.state
        st.stop_now = bool(um and st.is_stop(um.get("content")))
        self._body_ask = body_line(self.cfg, (um or {}).get("content")) if um else ""
        try:
            after_act = self._after_action(context.messages)
            for attempt in range(2):
                self._hold = [] if attempt == 0 and (self._may_retry(um) or self._body_ask or after_act) else None
                await self._one_pass(context)
                if attempt == 1 or not self._should_retry(um):
                    if after_act and not self._called and self._hold is not None:
                        fixed = fix_after_tool("".join(self._hold), context.messages, str((um or {}).get("content") or ""), self._my_name())
                        if fixed is not None:
                            logger.info(f"도구 결과 뒤 답 고침: {''.join(self._hold)[:40]!r} → {fixed[:40]!r}")
                            st.event("after_tool_fixed")
                            self._hold, self._said = ([fixed] if fixed else None), ([fixed] if fixed else [])
                    if self._body_ask and not self._called and self._hold is not None and \
                            (FILLER.fullmatch("".join(self._hold)) or self_intro_only("".join(self._hold), self._my_name())):
                        self._hold, self._said = None, []      # 몸동작 부탁에 '잠깐만요.'뿐 → 버리고 동작에 맞는 한마디로
                    await self._flush_hold()
                    if self._dropped and not self._pushed:
                        await self._emit(DROP_SAY)
                    said = "".join(self._said).strip()
                    if not self._called and self.kind in ("local", "url") and (not said or self_intro_only(said, self._my_name())):
                        fb = after_tool_say(context.messages)   # 도구 결과 뒤 빈 답 → 결과로 짧게
                        if fb:
                            logger.info("두뇌가 도구 결과 뒤 빈 답 → 결과에서 짧게 말함")
                            await self._emit((" " if said else "") + fb)
                    if self._body_ask and not self._called and not "".join(self._said).strip():
                        await self._emit(self._body_ask)       # 춤 부탁에 빈 답 → 동작에 맞는 한마디(펫은 이미 움직임)
                    if not self._called and self.kind in ("local", "url") and RESCUE.is_promise("".join(self._said)) \
                            and RESCUE.wants_action(str((um or {}).get("content") or "")):
                        logger.info("두뇌가 도구 없이 약속만 함(다시 물어도) — 그 차례는 다음 기록에서 뺌")
                        st.event("tool_promise_only")
                    return
                if len(self._retries) > 50:
                    self._retries = {}
                self._retries[self.cur_user_key] = self._retries.get(self.cur_user_key, 0) + 1
                self.retried += 1
                self._hold = None          # 잡아 둔 첫 답은 버림(다시 물은 답만 내보냄)
                logger.info(f"두뇌가 도구 없이 약속만 함 → 도구를 꼭 부르게 한 번 더 물음: {''.join(self._said)[:40]!r}")
                st.event("tool_retry")
                self._force_tool = True
        finally:
            self._force_tool = False
            self._hold = None

    async def _one_pass(self, context):
        """한 번 묻고 답을 내보냄(글로 쓴 호출 건지기 포함)."""
        self._think = ThinkFilter()
        self._hanzi = HanziFilter()
        names = [n for n in self.tool_names if n in debate.allowed_names(self.cfg)] if debate.on(self.state) else self.tool_names
        self._split = RESCUE.CallSplitter(names, self.tool_first) if (self.do_rescue and names) else None
        self._said, self._raw = [], []
        self._called = False
        self._dropped = False
        st = self.state
        note = asyncio.ensure_future(self._slow_note(self.cur_user_key))
        try:
            await super()._process_context(context)
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"두뇌 응답 실패: {ex.__class__.__name__} {str(ex)[:160]}")
            st.event("brain_error", reason=ex.__class__.__name__)
            await self.push_frame(TTSSpeakFrame(i18n.tr("두뇌에 연결이 안 돼요. 설정에서 두뇌 주소를 확인해 주세요.")))
            self._called = True    # 다시 묻지 않음
            return
        finally:
            note.cancel()
        rest = self._think.flush()
        rest = self._hanzi.feed(rest) + self._hanzi.flush() if rest else self._hanzi.flush()
        sp, self._split = self._split, None
        if sp is None:
            if rest:
                await self._emit(rest)
            return
        if rest:
            self._raw.append(rest)
        await self._emit(sp.feed(rest) if rest else "")
        tail, calls, dropped = sp.finish()
        if calls:
            self.rescued += 1
            self._called = True
            logger.info(f"글로 쓴 도구 호출 건짐: {[c[0] for c in calls]}")
            st.event("tool_rescue", names=[c[0] for c in calls])
            await self.run_function_calls([
                FunctionCallFromLLM(context=context, tool_call_id="rescue_" + uuid.uuid4().hex[:10],
                                    function_name=n, arguments=a) for n, a in calls])
            return
        if dropped:
            self.dropped += 1
            logger.info("글로 쓴 도구 호출 꼴인데 읽을 수 없어 버림(화면·목소리로 내보내지 않음)")
            st.event("tool_text_dropped")
            self._dropped = True   # 다시 묻지 못하면 _process_context 가 '말이 꼬였어요'를 함
            if tail.strip():
                await self._emit(tail)
            return
        await self._emit(tail)


FILLER = re.compile(r"\s*(?:네[,.!]?\s*)?(?:잠깐만요|잠시만요|잠시만\s*기다려\s*주세요|생각해\s*볼게요|음+|네)[.!~…]*\s*")


def body_line(cfg, user_text):
    """펫 얼굴일 때 사용자 말이 몸동작 부탁이면 짧은 답, 아니면 ''."""
    try:
        if str((cfg.get("화면") or {}).get("얼굴") or "") != "펫":
            return ""
        from ..pet_link.face import motion_line
        return motion_line(str(user_text or "").split("\n")[0], C.names(cfg)[0:1])
    except Exception:  # noqa: BLE001
        return ""


def self_intro_only(text, name):
    """'김비서입니다.'·'안녕하세요. 김비서입니다. 무엇을 도와드릴까요?' 처럼 자기 이름 소개뿐인 답인가."""
    if not name:
        return False
    return bool(re.fullmatch(r"\s*(?:네[,.]?\s*)?(?:안녕하세요[.,!]?\s*)?" + re.escape(str(name)) + r"입니다[.!]?\s*"
                             r"(?:무엇을\s*도와\s*드릴까요\??)?\s*", str(text or "")))


ACTION_TOOLS = {"pc_action", "type_text", "calc", "remember", "forget", "speech_speed", "standby"}
_NUMS = re.compile(r"\d[\d,.]*")


def _since_user(msgs):
    i = max((k for k, m in enumerate(msgs or []) if isinstance(m, dict) and m.get("role") == "user"), default=-1)
    return [m for m in (msgs or [])[i + 1:] if isinstance(m, dict)]


def _call_names(m):
    out = []
    for tc in m.get("tool_calls") or []:
        f = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
        n = f.get("name") if isinstance(f, dict) else getattr(f, "name", None)
        if n:
            out.append(n)
    return out


def last_tool_names(msgs):
    """대화 끝이 도구 결과면 그 결과들을 부른 도구 이름들, 아니면 []."""
    if not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "tool":
        return []
    for m in reversed(msgs):
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            return _call_names(m)
    return []


def fix_after_tool(reply, msgs, user_text, name=""):
    """행동 도구 결과 뒤 두뇌 답 → 고친 답(바꿀 것 없으면 None, 할 말이 없으면 '').
    앞의 자기소개·인사는 떼고 / 비었거나·'잠깐만요'뿐·사용자 말 따라 하기 / (켜기·쓰기·기억 뒤) 결과에 없는 숫자 → 도구 결과의 짧은 말."""
    if not set(last_tool_names(msgs)) & ACTION_TOOLS:
        return None
    t = str(reply or "").strip()
    head = r"(?:안녕하세요[.!,~]?\s*|네[,.]\s*)?" + (r"(?:" + re.escape(str(name)) + r"입니다[.!]?\s*)?" if name else "") + r"(?:안녕하세요[.!,~]?\s*)?"
    body = re.sub(r"^" + head, "", t).strip()
    norm = lambda x: re.sub(r"[\s.!?~,]", "", str(x or ""))   # noqa: E731
    u = norm(str(user_text or "").split("\n")[0])
    nb = norm(body)
    bad = not body or bool(FILLER.fullmatch(body)) or (u and (nb in (u, u + "요") or (len(nb) >= 3 and nb != u and u.endswith(nb) and nb.endswith("줘"))))   # '기억해 줘'처럼 부탁 끝만 따라 함
    names = {n for m in _since_user(msgs) if m.get("role") == "assistant" for n in _call_names(m)}
    if not bad and names and names <= (ACTION_TOOLS - {"calc"}):
        seen = " ".join(str(m.get("content") or "") + " " + json.dumps(m.get("tool_calls") or [], ensure_ascii=False, default=str)
                        for m in _since_user(msgs)) + " " + str(user_text or "")   # 결과·호출 인자(적은 글)·사용자 말에 있던 숫자만 됨
        have = {x.replace(",", "").rstrip(".") for x in _NUMS.findall(seen)}
        bad = any(x.replace(",", "").rstrip(".") not in have for x in _NUMS.findall(body))   # 켰을 뿐인데 날씨·가격 숫자를 지어냄
    if bad:
        return after_tool_say(msgs) or ""
    return body if body != t else None


def after_tool_say(msgs):
    """도구 결과 뒤 두뇌가 빈 답(또는 '김비서입니다.'만)을 냈을 때 대신 할 짧은 말 — 마지막 도구 결과에서. 없으면 ''."""
    if not msgs or not isinstance(msgs[-1], dict) or msgs[-1].get("role") != "tool":
        return ""
    try:
        r = json.loads(msgs[-1].get("content") or "{}")
    except (TypeError, ValueError):
        return ""
    if not isinstance(r, dict):
        return ""
    if r.get("말") and not str(r["말"]).startswith("("):
        return str(r["말"])[:120]
    if "답" in r and "식" in r:
        v = r["답"]
        return f"답은 {v:,}이에요." if isinstance(v, (int, float)) and not isinstance(v, bool) else f"답은 {v}이에요."
    if r.get("저장") or r.get("이미있음"):
        return "기억할게요."
    if r.get("장소") and r.get("예보"):
        d = (r["예보"] or [{}])[0]
        return f"{r['장소']} {d.get('날', '')} {d.get('하늘', '')}, 최고 {d.get('최고기온')}도 최저 {d.get('최저기온')}도예요."
    if r.get("오류"):
        return str(r["오류"])[:120]
    return "다 했어요."


def drop_promise_turns(msgs):
    """대화 기록에서 '도구가 필요한 부탁 → 도구 없이 약속만 한 답'이 끝난 차례(사용자 말 + 그 답)를 뺀다.
    마지막 사용자 말(지금 묻는 것)과 그 뒤는 그대로 · 약속 뒤에 도구 호출·결과가 이어진 차례는 그대로."""
    last_user = max((i for i, m in enumerate(msgs) if isinstance(m, dict) and m.get("role") == "user"), default=-1)
    out = []
    for i, m in enumerate(msgs):
        if (i < last_user and isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str)
                and not m.get("tool_calls") and out and isinstance(out[-1], dict) and out[-1].get("role") == "user"
                and RESCUE.is_promise(m["content"]) and RESCUE.wants_action(str(out[-1].get("content") or ""))):
            nxt = msgs[i + 1] if i + 1 < len(msgs) else {}
            if not (isinstance(nxt, dict) and (nxt.get("tool_calls") or nxt.get("role") == "tool")):
                out.pop()
                continue
        out.append(m)
    return out


def make_llm(state, cfg, tool_names=(), guards=None, session_key=""):
    """설정 두뇌.방식에 맞는 두뇌 부품을 만든다. guards: {주소: CacheGuard} (본체 전체에서 같은 서버면 같은 가드를 씀)."""
    b = cfg["두뇌"]
    kind = str(b.get("방식") or "local")
    if kind in ("claude_cli", "codex_cli"):   # 구독 두뇌(같은 PC 의 claude·codex 명령) — core/cli_brain
        from .cli_brain import CliBrain
        return CliBrain(state, cfg, kind, tool_names=tool_names)
    temp = float(b.get("온도", 0.6))
    mt = int(b.get("최대토큰", 400))
    if kind == "claude":
        cls = _claude_class()
        key = keystore.get(b.get("열쇠_이름") or "claude", cfg)
        if not key:
            raise RuntimeError("클로드 열쇠가 없어요. 설정 화면에서 열쇠를 넣어 주세요.")
        llm = cls(state, cfg, api_key=key, settings=cls.Settings(
            model=b.get("claude_모델") or "claude-opus-5-5", temperature=temp, max_tokens=mt,
            enable_prompt_caching=bool(b.get("캐시", True))))
        return llm
    if kind == "openai":
        base = b.get("openai_주소") or "https://api.openai.com/v1"
        model = b.get("openai_모델") or ""
        key = keystore.get(b.get("열쇠_이름") or "openai", cfg)
        if not model or not key:
            raise RuntimeError("GPT 를 쓰려면 설정에 모델 이름과 열쇠가 있어야 해요.")
    elif kind == "compat":   # OpenAI 호환 API(바깥 서비스·내 열쇠): 표준 값만 보냄 — llama.cpp 전용 값(캐시·생각 끄기·슬롯)도 OpenAI 전용 값도 안 붙임
        base, model = str(b.get("호환_주소") or "").strip(), str(b.get("호환_모델") or "").strip()
        key = keystore.get("compat", cfg) or "none"
        if not base or not model:
            raise RuntimeError("OpenAI 호환 API 를 쓰려면 설정에 주소와 모델 이름이 있어야 해요.")
    else:
        base = b.get("주소") or f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1"
        model = b.get("모델") or "local"
        key = keystore.get(b.get("열쇠_이름"), cfg) if b.get("열쇠_이름") else "none"
    guard = None
    if kind == "local" and guards is not None:
        guard = guards.get(base)
        if guard is None:
            guard = guards[base] = CacheGuard(base)
    llm = BrainLLM(state, cfg, tool_names=tool_names, guard=guard, slot=int(b.get("슬롯", 0) or 0), cache_key=session_key,
                   api_key=key or "none", base_url=base,
                   settings=BrainLLM.Settings(model=model, temperature=temp, max_tokens=mt, system_instruction=""),
                   retry_timeout_secs=float(b.get("첫응답_제한_초", 30)), retry_on_timeout=False)
    llm.kind = kind
    return llm


def _claude_class():
    """클로드 두뇌 — pipecat AnthropicLLMService + 본체가 쓰는 것(시각 꼬리표·멈춤말·기록 칸).
    캐시: enable_prompt_caching 이면 pipecat 이 지시문과 마지막 차례에 cache_control 을 붙인다(앞부분 고정 순서 그대로).
    pipecat 의 클로드 쪽은 tool_choice 를 넘기지 않으므로 '그만'·폭주 멈춤은 도구 겉싸개(거부 + run_llm=False)로만 막는다
    (도구 목록을 빼면 캐시 앞부분이 바뀌므로 빼지 않음)."""
    try:
        from pipecat.services.anthropic.llm import AnthropicLLMService
    except Exception as ex:  # noqa: BLE001
        raise RuntimeError("클로드를 쓰려면 anthropic 꾸러미가 필요해요(설치.bat 의 '클로드 쓰기' 선택).") from ex

    class ClaudeLLM(AnthropicLLMService):
        def __init__(self, state, cfg, **kw):
            super().__init__(**kw)
            self.state, self.cfg = state, cfg
            self.kind = "claude"
            self.guard = None
            self.timing_log = []
            self.last_timing = None
            self.rescued = 0
            self.cur_user_key = None

        async def _process_context(self, context):
            um = BrainLLM._tag_time(self, context)
            st = self.state
            st.stop_now = bool(um and st.is_stop(um.get("content")))
            try:
                await super()._process_context(context)
            except Exception as ex:  # noqa: BLE001
                logger.warning(f"두뇌(클로드) 응답 실패: {ex.__class__.__name__}")
                st.event("brain_error", reason=ex.__class__.__name__)
                await self.push_frame(TTSSpeakFrame(i18n.tr("두뇌에 연결이 안 돼요. 설정에서 열쇠와 인터넷 연결을 확인해 주세요.")))

    return ClaudeLLM


class NoBrain(FrameProcessor):
    """두뇌를 못 만들었을 때(열쇠 없음·꾸러미 없음) 대신 들어가 사용자 말마다 이유를 말해 준다 — 본체가 꺼지지 않게."""

    def __init__(self, reason):
        super().__init__()
        self.reason = str(reason)[:200]
        self.kind = "none"
        self.guard = None
        self.timing_log = []
        self.last_timing = None
        self.rescued = 0
        self.cur_user_key = None
        self._said = 0.0

    def register_function(self, *a, **k):
        return None

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            if time.time() - self._said > 3:
                self._said = time.time()
                await self.push_frame(TTSSpeakFrame(self.reason))
            return
        await self.push_frame(frame, direction)


async def simple_text(cfg, messages, max_tokens=300, temperature=0.3, timeout=60.0):
    """대화 밖 한 번 묻기(일기 요약·자동 기억). 생각 끔, 캐시 안 씀(대화 칸을 흐트리지 않게). 실패하면 ''."""
    b = cfg["두뇌"]
    kind = str(b.get("방식") or "local")
    if kind in ("claude_cli", "codex_cli"):
        if not (cfg.get("기억") or {}).get("구독두뇌_정리", True):
            return ""
        from .cli_brain import one_shot
        return await one_shot(cfg, messages, max_chars=max_tokens * 4, timeout=timeout)
    if kind == "claude":
        return ""   # 클로드는 대화 밖 요청을 하지 않음(열쇠 요금) — 일기·자동 기억은 로컬·OpenAI 호환에서만
    if kind == "openai":
        base, model = b.get("openai_주소") or "https://api.openai.com/v1", b.get("openai_모델") or ""
        key = keystore.get(b.get("열쇠_이름") or "openai", cfg)
    elif kind == "compat":
        base, model, key = str(b.get("호환_주소") or "").strip(), str(b.get("호환_모델") or "").strip(), keystore.get("compat", cfg) or "none"
        if not base or not model:
            return ""
    else:
        base, model = b.get("주소") or f"http://127.0.0.1:{cfg['포트']['두뇌']}/v1", b.get("모델") or "local"
        key = keystore.get(b.get("열쇠_이름"), cfg) if b.get("열쇠_이름") else "none"
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": False}
    if kind in ("local", "url"):
        body["chat_template_kwargs"] = {"enable_thinking": False}
        body["cache_prompt"] = False
        body["id_slot"] = -1
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as cl:
            r = await cl.post(base.rstrip("/") + "/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {key or 'none'}"})
            r.raise_for_status()
            j = r.json()
        return str(((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except Exception as ex:  # noqa: BLE001
        logger.warning(f"두뇌 한 번 묻기 실패: {ex.__class__.__name__}")
        return ""


def warm_body(params_messages, tools, cfg):
    """대화 시작 때 앞부분(지시문·도구·이어 온 차례)을 미리 읽혀 두는 요청 본문(답 1토큰, 캐시 칸 고정)."""
    b = cfg["두뇌"]
    body = {"model": b.get("모델") or "local", "messages": tidy_messages(list(params_messages)), "max_tokens": 1, "temperature": 0,
            "stream": False, "cache_prompt": True, "id_slot": int(b.get("슬롯", 0) or 0),
            "chat_template_kwargs": {"enable_thinking": str(b.get("모드")) == "꼼꼼"}}
    if tools:
        body["tools"] = tools
    return json.loads(json.dumps(body, ensure_ascii=False))
