# 기본 도구 11개 처리 함수 — HANDLERS = {이름: async 함수(ctx, args) → dict}
#   remember·recall·forget : 이 PC 기억(core/memory)   web_search·read_page·get_weather : web.py
#   pc_action : pc_action.py(허용목록)   type_text : type_text.py(김비서가 연 메모장에만 쓰기)
#   speech_speed : 말 빠르기 1.0/1.2/1.4   standby : 대기(이름 부르기 모드)   calc : 안전한 계산(숫자 없는 '계산기'면 계산기 프로그램 열기)
import ast
import asyncio
import importlib.util
import operator
import os
import re

from app.core.i18n import tr

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location("kimbiseo_basic_" + name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


web = _load("web")
pc = _load("pc_action")
typing = _load("type_text")


def _web_cfg(ctx):
    w = dict(((ctx.cfg.get("도구") or {}).get("웹")) or {})
    w.setdefault("기본장소", (ctx.cfg.get("사용자") or {}).get("기본장소") or "서울")
    return w


# ---------------- 기억
async def remember(ctx, a):
    if ctx.memory is None:
        return {"오류": tr("기억이 꺼져 있어요.")}
    r = ctx.memory.add(a.get("content"), source="말")
    if r.get("저장") or r.get("이미있음"):
        r["안내"] = tr("'기억할게요'라고 한 번만 짧게 답하세요.")
    return r


async def recall(ctx, a):
    if ctx.memory is None:
        return {"오류": tr("기억이 꺼져 있어요.")}
    r = ctx.memory.recall(a.get("query"), a.get("day"))
    r["안내"] = tr("찾은 것으로만 짧게 답하세요. 없으면 기억에 없다고 말하세요.")
    return r


async def forget(ctx, a):
    if ctx.memory is None:
        return {"오류": tr("기억이 꺼져 있어요.")}
    return ctx.memory.forget(a.get("what"), bool(a.get("all")))


# ---------------- 웹
async def web_search(ctx, a):
    return await web.web_search(_web_cfg(ctx), a.get("query"), a.get("count"))


async def read_page(ctx, a):
    w = _web_cfg(ctx)
    return await web.read_page(w, a.get("url"), w.get("본문_최대_글자"), focus=a.get("find"))


async def get_weather(ctx, a):
    return await web.weather(_web_cfg(ctx), a.get("place"), a.get("day"))


# ---------------- 컴퓨터 열기
async def pc_action(ctx, a):
    pcfg = (ctx.cfg.get("도구") or {}).get("컴퓨터조작") or {}
    act, err = pc.from_llm(a, pcfg.get("사이트") or {}, pcfg.get("별명") or {})
    if err:
        return err
    if act.get("action") == "open_program" and act.get("program") == "notepad":
        # 메모장은 '우리 메모'로 연다 — 뒤이어 type_text 가 그 창에만 쓸 수 있게
        return await asyncio.to_thread(typing.open_result, _memo_dir(ctx), bool(pcfg.get("시험_실행안함")))
    return await asyncio.to_thread(pc.run_checked, act, bool(pcfg.get("시험_실행안함")))


# ---------------- 메모장에 쓰기
def _memo_dir(ctx):
    w = (ctx.cfg.get("도구") or {}).get("글쓰기") or {}
    return typing.memo_dir(str(w.get("메모_폴더") or ""))


async def type_text(ctx, a):
    tc = ctx.cfg.get("도구") or {}
    pcfg = tc.get("컴퓨터조작") or {}
    lim = int((tc.get("글쓰기") or {}).get("최대_글자", typing.MAX_CHARS) or typing.MAX_CHARS)
    return await asyncio.to_thread(typing.type_memo, a.get("text"), _memo_dir(ctx), bool(a.get("new_memo")),
                                   min(lim, typing.MAX_CHARS), bool(pcfg.get("시험_실행안함")))


# ---------------- 말 빠르기
_STEPS = (1.0, 1.2, 1.4)


async def speech_speed(ctx, a):
    st = ctx.state
    cur = min(_STEPS, key=lambda x: abs(x - float(st.speed or 1.0)))
    v = str(a.get("speed") or "").strip().lower()
    if v == "status":
        return {"지금_빠르기": cur, "안내": tr(f"지금 말 빠르기는 {cur}배라고 짧게 답하세요.")}
    if v == "faster":
        new = _STEPS[min(len(_STEPS) - 1, _STEPS.index(cur) + 1)]
    elif v == "slower":
        new = _STEPS[max(0, _STEPS.index(cur) - 1)]
    else:
        try:
            new = min(_STEPS, key=lambda x: abs(x - float(v)))
        except ValueError:
            return {"오류": tr("빠르기는 1.0, 1.2, 1.4 중 하나예요.")}
    st.speed = new
    save = ctx.actions.get("save_settings")
    if save:
        save({"목소리": {"말속도": new}})
    st.event("speed", speed=new)
    return {"빠르기": new, "안내": tr(f"다음 말부터 {new}배로 말한다고 한 문장으로만 답하세요.")}


# ---------------- 대기
async def standby(ctx, a):
    st = ctx.state
    link = ctx.actions.get("phone")
    if link is not None:      # 폰 앱: 이 말을 다 들려준 뒤 폰이 대화를 끝내고 첫 화면으로(다시 말하려면 마이크 단추)
        link.send({"type": "standby"})
        return {"대기": True, "안내": tr("대화를 마칩니다. '네, 필요하면 다시 불러 주세요.'처럼 한 문장으로만 답하세요.")}
    st.set_wake(True, why="대기 도구")
    st.wake_until = 0.0
    name = st.names.name
    return {"대기": True, "안내": tr(f"대기에 들어갔습니다. '네, 필요하면 {name}라고 불러 주세요.'처럼 한 문장으로만 답하세요.")}


# ---------------- 계산
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}


def _eval(node, depth=0):
    if depth > 40:
        raise ValueError("식이 너무 깊어요")
    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand, depth + 1)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        x, y = _eval(node.left, depth + 1), _eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and (abs(y) > 64 or abs(x) > 1e6):
            raise ValueError("거듭제곱이 너무 커요")
        return _OPS[type(node.op)](x, y)
    raise ValueError("숫자와 + - * / ( ) 만 쓸 수 있어요")


def calc_expr(expr):
    s = str(expr or "").strip()[:200]
    s = s.replace("×", "*").replace("÷", "/").replace(",", "").replace("x", "*").replace("X", "*")
    s = s.replace("%", "/100")
    if not s:
        raise ValueError("식이 비었어요")
    v = _eval(ast.parse(s, mode="eval"))
    if isinstance(v, float):
        v = round(v, 6)
        if v.is_integer():
            v = int(v)
    return v


_CALC_APP = re.compile(r"^\s*(윈도우\s*)?(계산기|calculator|calc(\.exe)?)(\s*(프로그램|앱|창))?\s*((켜|열|실행|띄워)[가-힣\s]*)?$", re.I)


async def calc(ctx, a):
    """숫자 계산. 작은 두뇌가 '계산기 켜 줘'를 calc(계산기) 로 부르면 → 계산기 프로그램 열기로 바꿈(숫자가 하나도 없을 때만)."""
    ex = str(a.get("expression") or "")
    if not re.search(r"\d", ex) and _CALC_APP.match(ex) and ((ctx.cfg.get("도구") or {}).get("컴퓨터조작") or {}).get("켜기", True):
        r = await pc_action(ctx, {"action": "open_program", "program": "calculator"})
        if isinstance(r, dict):
            r = dict(r, 안내="계산기 프로그램을 켰다고 한 문장으로 답한다.")
        return r
    try:
        v = calc_expr(a.get("expression"))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as ex:
        return {"오류": f"계산할 수 없어요({ex})."}
    return {"식": str(a.get("expression"))[:200], "답": v, "안내": tr("답을 자연스러운 한국어로 말하세요(큰 수는 만·억 단위로).")}


HANDLERS = {"remember": remember, "recall": recall, "forget": forget, "web_search": web_search, "read_page": read_page,
            "get_weather": get_weather, "pc_action": pc_action, "type_text": type_text, "speech_speed": speech_speed, "standby": standby, "calc": calc}
