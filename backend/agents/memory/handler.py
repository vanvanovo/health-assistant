# backend/agents/memory/handler.py
# 长期记忆:抽取(LLM)→ 校验(白名单/范围/日期)→ 确认卡(签名 token,10 分钟)
# → 用户点「确认写入」→ apply(调 MCP 落库)。
# 纪律:写入必须经用户确认;token 防篡改、限时;列表字段追加不覆盖。

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from jose import JWTError, jwt

from backend.agents.common import llm_json, tools
from backend.agents.common.result import agent_result
from backend.config import get_settings

from . import prompts

PROFILE_FIELDS = {
    "goal", "height_cm", "target_weight_kg", "equipment",
    "dietary_restrictions", "injuries", "schedule_pref", "remind_times",
}
LIST_FIELDS = {"equipment", "dietary_restrictions", "injuries"}
EVENT_KINDS = {"injury", "travel", "checkup", "other"}
TOKEN_TTL_MINUTES = 10


def _parse_date(s) -> date | None:
    if isinstance(s, date):
        return s
    if isinstance(s, str) and s.strip():
        try:
            return date.fromisoformat(s.strip()[:10])
        except ValueError:
            return None
    return None


# ── 签名 token ───────────────────────────────────────────────
def encode_memory_token(payload: dict, ttl_minutes: int = TOKEN_TTL_MINUTES) -> str:
    s = get_settings()
    claims = {
        "typ": "memory",
        "sub": s.demo_username,
        "payload": payload,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_memory_token(token: str) -> dict:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError as e:
        raise ValueError(f"链接无效或已过期({e})") from e
    if claims.get("typ") != "memory":
        raise ValueError("链接类型不正确")
    return claims


# ── 校验 ─────────────────────────────────────────────────────
def _validate_patch(patch) -> tuple[dict, list[str]]:
    clean: dict = {}
    problems: list[str] = []
    if not isinstance(patch, dict) or not patch:
        return {}, ["没有提取到可更新的画像字段"]
    for k, v in patch.items():
        if k not in PROFILE_FIELDS:
            problems.append(f"不支持更新的字段:{k}")
            continue
        if k in LIST_FIELDS:
            if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                problems.append(f"{k} 需为字符串数组")
                continue
            clean[k] = [x.strip()[:60] for x in v][:10]
        elif k == "goal":
            if not isinstance(v, str) or not v.strip():
                problems.append("goal 不合法")
                continue
            clean[k] = v.strip()[:32]
        elif k in ("height_cm", "target_weight_kg"):
            try:
                num = float(v)
            except (TypeError, ValueError):
                problems.append(f"{k} 需为数字")
                continue
            ok = (50 <= num <= 250) if k == "height_cm" else (30 <= num <= 300)
            if not ok:
                problems.append(f"{k} 超出合理范围")
                continue
            clean[k] = round(num, 1)
        else:  # schedule_pref / remind_times
            if not isinstance(v, dict):
                problems.append(f"{k} 需为对象")
                continue
            clean[k] = v
    return clean, problems


def _validate_event(ev) -> tuple[dict, list[str]]:
    if not isinstance(ev, dict):
        return {}, ["没有提取到事件内容"]
    kind = ev.get("kind")
    desc = str(ev.get("description") or "").strip()
    d1 = _parse_date(ev.get("start_date"))
    d2 = _parse_date(ev.get("end_date")) if ev.get("end_date") else None
    problems: list[str] = []
    if kind not in EVENT_KINDS:
        problems.append(f"kind 仅支持 {sorted(EVENT_KINDS)}")
    if not desc or len(desc) > 500:
        problems.append("description 不能为空且 ≤500 字")
    if not d1:
        problems.append("start_date 不合法")
    if ev.get("end_date") and not d2:
        problems.append("end_date 不合法")
    if d1 and d2 and d2 < d1:
        problems.append("end_date 不能早于 start_date")
    if problems:
        return {}, problems
    return {
        "kind": kind, "description": desc,
        "start_date": d1.isoformat(),
        "end_date": d2.isoformat() if d2 else None,
    }, []


# ── 主流程 ───────────────────────────────────────────────────
async def run_memory(user_input: str, today: str | None = None) -> dict:
    """抽取 → 校验 → 返回带签名 token 的确认卡(不直接写库)。"""
    t = today or date.today().isoformat()
    data = await llm_json.chat_json(
        [
            {"role": "system", "content": prompts.build_extract(t)},
            {"role": "user", "content": user_input},
        ],
        temperature=0,
    )
    action = data.get("action")
    summary = str(data.get("summary") or "").strip()[:200]

    if action == "profile_patch":
        clean, problems = _validate_patch(data.get("patch"))
        if problems:
            return agent_result("memory", "ok", "这条没法自动写入:" + ";".join(problems))
        payload = {
            "type": "profile_patch", "patch": clean,
            "append_fields": sorted(k for k in clean if k in LIST_FIELDS),
            "summary": summary,
        }
        token = encode_memory_token(payload)
        preview = "、".join(f"{k}={v}" for k, v in clean.items())
        message = f"我理解你想更新画像:{summary or preview}。点卡片上的「确认写入」才会保存(10 分钟内有效)。"
        return agent_result(
            "memory", "ok", message,
            card={
                "type": "profile_update",
                "payload": {
                    "status": "pending", "summary": summary, "patch": clean,
                    "append_fields": payload["append_fields"], "token": token,
                },
            },
        )

    if action == "event":
        clean, problems = _validate_event(data.get("event"))
        if problems:
            return agent_result("memory", "ok", "这条事件没法写入:" + ";".join(problems))
        payload = {"type": "event", "event": clean, "summary": summary}
        token = encode_memory_token(payload)
        span = clean["start_date"] + " ~ " + (clean.get("end_date") or "长期")
        message = f"记一个事件:{clean['description']}({span})。点「确认写入」保存(10 分钟内有效)。"
        return agent_result(
            "memory", "ok", message,
            card={
                "type": "profile_update",
                "payload": {"status": "pending", "summary": summary, "event": clean, "token": token},
            },
        )

    return agent_result(
        "memory", "ok",
        str(data.get("reason") or "这条我理解为普通交流,没有需要长期记住的信息。"),
    )


async def apply_memory_token(token: str) -> dict:
    """确认写入:解 token → 合并(列表追加去重)→ 调 MCP 落库。"""
    claims = decode_memory_token(token)
    payload = claims.get("payload") or {}
    ptype = payload.get("type")
    key = "mem-" + hashlib.sha1(token.encode("utf-8")).hexdigest()[:12]

    if ptype == "profile_patch":
        profile = tools.tool_data(await tools.call_tool("get_profile", {}), {}) or {}
        final: dict = {}
        for k, v in (payload.get("patch") or {}).items():
            if k in (payload.get("append_fields") or []):
                merged = list(profile.get(k) or [])
                for x in v:
                    if x not in merged:
                        merged.append(x)
                final[k] = merged
            else:
                final[k] = v
        res = await tools.call_tool("update_profile", {"patch": final, "idempotency_key": key})
        data = tools.tool_data(res)
        if data is None:
            raise RuntimeError((res or {}).get("message", "画像写入失败"))
        return {"status": "applied", "kind": "profile_patch", "summary": payload.get("summary"), "profile": data}

    if ptype == "event":
        ev = payload.get("event") or {}
        res = await tools.call_tool("add_memory_event", {**ev, "idempotency_key": key})
        if isinstance(res, dict) and res.get("status") == "duplicate":
            return {"status": "applied", "kind": "event", "event_id": res.get("event_id"), "note": "重复提交,已忽略"}
        data = tools.tool_data(res)
        if data is None:
            raise RuntimeError((res or {}).get("message", "事件写入失败"))
        return {"status": "applied", "kind": "event", "summary": payload.get("summary"), "event": data}

    raise ValueError("未知的记忆类型")
