# backend/mcp/health_server.py
# 个人健康助手 · MCP 健康工具服务(P2)
#
# 设计原则:
#   1) 参数化工具,不暴露 SQL 直通(注入面从根上消除)
#   2) 统一 JSON 返回:{"status": "success|invalid|not_found|duplicate|rejected", "data"/"message": ...}
#   3) 写操作:幂等键(idempotency_key)+ 审计(write_audit)
#   4) 统计口径走 backend/core/stats.py(与看板/周报共用,可解释)
#
# 工具清单(四域 15 个):
#   记录:upsert_health_record / query_records / get_range_summary / import_records
#   计划:save_plan / get_active_plan / upsert_checkin / get_plan_progress
#   营养:search_food / add_meal / get_day_intake
#   画像:get_profile / update_profile / add_memory_event / list_active_events
#
# 独立运行:python -m backend.mcp.health_server → http://localhost:8121/mcp
# 网关挂载:backend/main.py → /mcp/health(含 X-MCP-Key 鉴权)

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from mcp.server.fastmcp import FastMCP
from sqlalchemy import func, select, update

from backend.config import get_settings
from backend.core.logger import get_logger
from backend.core.stats import summarize_checkins, summarize_records
from backend.db import models as M
from backend.db.base import get_sessionmaker

logger = get_logger(__name__)

mcp = FastMCP(name="HealthTools", stateless_http=True, json_response=True)

# ── 白名单与取值范围 ─────────────────────────────────────────
WORKOUT_TYPES = {"running", "strength", "rest", "other"}
FEELINGS = {"good", "normal", "tired"}
MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
CHECKIN_STATUS = {"done", "partial", "missed"}
KINDS = {"workout", "diet", "habit"}
EVENT_KINDS = {"injury", "travel", "checkup", "other"}
PROFILE_FIELDS = {
    "goal", "height_cm", "target_weight_kg", "equipment",
    "dietary_restrictions", "injuries", "schedule_pref", "remind_times",
}
WEIGHT_RANGE, SLEEP_RANGE, MINUTES_RANGE = (30.0, 300.0), (0.0, 24.0), (0, 600)
FEELING_RANGE, INTENSITY_RANGE = (1, 5), (1, 3)


# ── 基础工具 ─────────────────────────────────────────────────
def _f(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _ok(data) -> str:
    return json.dumps({"status": "success", "data": data}, ensure_ascii=False, default=_jsonable)


def _msg(status: str, message: str, **extra) -> str:
    return json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False, default=_jsonable)


def _today() -> date:
    return date.today()


def _parse_date(s) -> date | None:
    if isinstance(s, date):
        return s
    if isinstance(s, str) and s.strip():
        try:
            return date.fromisoformat(s.strip()[:10])
        except ValueError:
            return None
    return None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _in_range(v: float, rng: tuple[float, float]) -> bool:
    return rng[0] <= v <= rng[1]


async def _resolve_user(session, user_id: int | None) -> int | None:
    """单用户场景:未显式传 user_id 时解析为演示账号。"""
    if user_id:
        return (await session.execute(select(M.User.id).where(M.User.id == user_id))).scalar_one_or_none()
    s = get_settings()
    return (
        await session.execute(select(M.User.id).where(M.User.username == s.demo_username))
    ).scalar_one_or_none()


async def _idem(session, action: str, key: str | None):
    """幂等检查:同 action+key 已执行过 → 返回当时审计行(含 target)。"""
    if not key:
        return None
    return (
        await session.execute(
            select(M.WriteAudit)
            .where(M.WriteAudit.action == action, M.WriteAudit.idempotency_key == key)
            .order_by(M.WriteAudit.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def _audit(session, action: str, target: str | None, key: str | None, user_id: int | None, result: str = "ok") -> None:
    session.add(
        M.WriteAudit(user_id=user_id, action=action, target=target, idempotency_key=key, result=result)
    )


def _record_view(r: M.HealthRecord) -> dict:
    return {
        "id": r.id, "date": r.date.isoformat(), "workout_type": r.workout_type,
        "workout_minutes": r.workout_minutes, "weight_kg": _f(r.weight_kg),
        "sleep_hours": _f(r.sleep_hours), "feeling": r.feeling, "note": r.note, "source": r.source,
    }


def _plan_item_view(it: M.PlanItem) -> dict:
    return {
        "id": it.id, "plan_id": it.plan_id, "date": it.date.isoformat(), "kind": it.kind,
        "title": it.title, "detail": it.detail, "est_minutes": it.est_minutes,
        "intensity": it.intensity, "status": it.status, "feeling_score": it.feeling_score,
        "checked_at": it.checked_at.isoformat() if it.checked_at else None,
    }


def _profile_view(p: M.Profile) -> dict:
    return {
        "user_id": p.user_id, "goal": p.goal, "height_cm": _f(p.height_cm),
        "target_weight_kg": _f(p.target_weight_kg), "equipment": p.equipment,
        "dietary_restrictions": p.dietary_restrictions, "injuries": p.injuries,
        "schedule_pref": p.schedule_pref, "remind_times": p.remind_times,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _validate_record_fields(workout_type, workout_minutes, weight_kg, sleep_hours, feeling) -> str | None:
    """返回错误信息;None = 通过。"""
    if workout_type is not None and workout_type not in WORKOUT_TYPES:
        return f"workout_type 仅支持 {sorted(WORKOUT_TYPES)}"
    if workout_minutes is not None and not _in_range(float(workout_minutes), (MINUTES_RANGE[0], MINUTES_RANGE[1])):
        return f"workout_minutes 需在 {MINUTES_RANGE[0]}~{MINUTES_RANGE[1]} 分钟"
    if weight_kg is not None and not _in_range(float(weight_kg), WEIGHT_RANGE):
        return f"weight_kg 需在 {WEIGHT_RANGE[0]}~{WEIGHT_RANGE[1]} kg"
    if sleep_hours is not None and not _in_range(float(sleep_hours), SLEEP_RANGE):
        return f"sleep_hours 需在 {SLEEP_RANGE[0]}~{SLEEP_RANGE[1]} 小时"
    if feeling is not None and feeling not in FEELINGS:
        return f"feeling 仅支持 {sorted(FEELINGS)}"
    return None


# ── 记录域 ───────────────────────────────────────────────────
@mcp.tool()
async def upsert_health_record(
    date: str,
    workout_type: str | None = None,
    workout_minutes: int | None = None,
    weight_kg: float | None = None,
    sleep_hours: float | None = None,
    feeling: str | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    user_id: int | None = None,
) -> str:
    """记录或更新某一天的健康数据(同一天重复调用 = 更新,只改传入的字段)。

    Args:
        date: 日期,格式 YYYY-MM-DD,不能晚于今天
        workout_type: 训练类型 running/strength/rest/other
        workout_minutes: 训练时长(分钟,0~600)
        weight_kg: 体重(kg,30~300)
        sleep_hours: 睡眠时长(小时,0~24)
        feeling: 体感 good/normal/tired
        note: 备注
        idempotency_key: 幂等键(建议 记录+日期 生成);同键重复调用返回首次结果
    """
    d = _parse_date(date)
    if not d:
        return _msg("invalid", f"日期格式不正确:{date}(应为 YYYY-MM-DD)")
    if d > _today():
        return _msg("invalid", f"日期不能晚于今天:{d.isoformat()}")
    err = _validate_record_fields(workout_type, workout_minutes, weight_kg, sleep_hours, feeling)
    if err:
        return _msg("invalid", err)

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在(演示环境请先执行 scripts/gen_demo_data.py)")

        if idempotency_key:
            ex = await _idem(session, "upsert_health_record", idempotency_key)
            if ex and ex.target:
                rec = await session.get(M.HealthRecord, int(ex.target))
                return _msg("duplicate", "该幂等键已处理过,返回原记录",
                            data={"record": _record_view(rec)} if rec else None)

        rec = (
            await session.execute(
                select(M.HealthRecord).where(M.HealthRecord.user_id == uid, M.HealthRecord.date == d)
            )
        ).scalars().first()
        created = rec is None
        if created:
            rec = M.HealthRecord(user_id=uid, date=d, source="llm")
            session.add(rec)
        for field, val in (
            ("workout_type", workout_type), ("workout_minutes", workout_minutes),
            ("weight_kg", weight_kg), ("sleep_hours", sleep_hours),
            ("feeling", feeling), ("note", note),
        ):
            if val is not None:
                setattr(rec, field, val)
        await session.flush()
        await _audit(session, "upsert_health_record", str(rec.id), idempotency_key, uid)
        await session.commit()
        return _ok({"created": created, "updated": not created, "record": _record_view(rec)})


@mcp.tool()
async def query_records(date_from: str, date_to: str, limit: int = 60, user_id: int | None = None) -> str:
    """查询时间范围内的健康记录(按日期升序)。

    Args:
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        limit: 最多返回条数(1~180,默认 60)
    """
    d1, d2 = _parse_date(date_from), _parse_date(date_to)
    if not d1 or not d2 or d1 > d2:
        return _msg("invalid", "日期范围不正确(需 YYYY-MM-DD 且 from <= to)")
    limit = max(1, min(int(limit), 180))

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        rows = (
            await session.execute(
                select(M.HealthRecord)
                .where(M.HealthRecord.user_id == uid, M.HealthRecord.date.between(d1, d2))
                .order_by(M.HealthRecord.date)
                .limit(limit)
            )
        ).scalars().all()
        return _ok({"count": len(rows), "records": [_record_view(r) for r in rows]})


@mcp.tool()
async def get_range_summary(date_from: str, date_to: str, user_id: int | None = None) -> str:
    """统计时间范围内的健康数据(纯规则聚合,与看板同口径):训练量/体重趋势/睡眠/体感/计划完成率。

    Args:
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
    """
    d1, d2 = _parse_date(date_from), _parse_date(date_to)
    if not d1 or not d2 or d1 > d2:
        return _msg("invalid", "日期范围不正确(需 YYYY-MM-DD 且 from <= to)")

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        recs = (
            await session.execute(
                select(M.HealthRecord)
                .where(M.HealthRecord.user_id == uid, M.HealthRecord.date.between(d1, d2))
                .order_by(M.HealthRecord.date)
            )
        ).scalars().all()
        items = (
            await session.execute(
                select(M.PlanItem)
                .where(M.PlanItem.user_id == uid, M.PlanItem.date.between(d1, d2))
            )
        ).scalars().all()
        data = summarize_records(
            [
                {
                    "date": r.date, "workout_type": r.workout_type,
                    "workout_minutes": r.workout_minutes, "weight_kg": _f(r.weight_kg),
                    "sleep_hours": _f(r.sleep_hours), "feeling": r.feeling,
                }
                for r in recs
            ],
            checkin_items=[{"status": it.status, "kind": it.kind} for it in items],
        )
        return _ok(data)


@mcp.tool()
async def import_records(rows: list[dict], idempotency_key: str | None = None, user_id: int | None = None) -> str:
    """批量导入健康记录(CSV 导入后的统一入口;逐行校验,单行失败不影响其他行)。

    Args:
        rows: 记录数组,每项含 date(必需)与 workout_type/workout_minutes/weight_kg/sleep_hours/feeling/note
        idempotency_key: 可选幂等键(批次级);重复调用直接返回上一次结果
    """
    if not isinstance(rows, list) or not rows or len(rows) > 180:
        return _msg("invalid", "rows 需为 1~180 条的数组")

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        if idempotency_key:
            ex = await _idem(session, "import_records", idempotency_key)
            if ex:
                return _msg("duplicate", "该批次幂等键已导入过", target=ex.target)

        imported = updated = 0
        errors: list[dict] = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append({"index": i, "error": "行数据需为对象"})
                continue
            d = _parse_date(row.get("date"))
            if not d or d > _today():
                errors.append({"index": i, "error": f"日期不合法:{row.get('date')}"})
                continue
            err = _validate_record_fields(
                row.get("workout_type"), row.get("workout_minutes"),
                row.get("weight_kg"), row.get("sleep_hours"), row.get("feeling"),
            )
            if err:
                errors.append({"index": i, "error": err})
                continue
            rec = (
                await session.execute(
                    select(M.HealthRecord).where(M.HealthRecord.user_id == uid, M.HealthRecord.date == d)
                )
            ).scalars().first()
            if rec is None:
                rec = M.HealthRecord(user_id=uid, date=d, source="import")
                session.add(rec)
                imported += 1
            else:
                updated += 1
            for field in ("workout_type", "workout_minutes", "weight_kg", "sleep_hours", "feeling", "note"):
                val = row.get(field)
                if val is not None:
                    setattr(rec, field, val)

        await session.flush()
        await _audit(session, "import_records", f"imported={imported},updated={updated}", idempotency_key, uid)
        await session.commit()
        return _ok({
            "imported": imported, "updated": updated,
            "invalid": len(errors), "errors": errors[:10],
        })


# ── 计划与打卡域 ─────────────────────────────────────────────
def _validate_plan_items(items: list[dict], week_start: date) -> tuple[list[dict] | None, list[dict]]:
    errors: list[dict] = []
    normalized: list[dict] = []
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            errors.append({"index": i, "error": "计划项需为对象"})
            continue
        d = _parse_date(it.get("date"))
        if not d or not (week_start <= d <= week_start + timedelta(days=6)):
            errors.append({"index": i, "error": f"日期不在本周:{it.get('date')}"})
            continue
        kind = it.get("kind")
        title = (it.get("title") or "").strip()
        if kind not in KINDS:
            errors.append({"index": i, "error": f"kind 仅支持 {sorted(KINDS)}"})
            continue
        if not title or len(title) > 128:
            errors.append({"index": i, "error": "title 不能为空且 ≤128 字"})
            continue
        est = it.get("est_minutes")
        if est is not None and not (0 <= int(est) <= 300):
            errors.append({"index": i, "error": "est_minutes 需在 0~300"})
            continue
        intensity = it.get("intensity")
        if intensity is not None and not (INTENSITY_RANGE[0] <= int(intensity) <= INTENSITY_RANGE[1]):
            errors.append({"index": i, "error": "intensity 需在 1~3"})
            continue
        normalized.append({
            "date": d, "kind": kind, "title": title,
            "detail": it.get("detail"), "est_minutes": est, "intensity": intensity,
        })
    return (normalized if not errors else None), errors


@mcp.tool()
async def save_plan(
    week_start: str,
    items: list[dict],
    summary: str | None = None,
    rationale: str | None = None,
    idempotency_key: str | None = None,
    user_id: int | None = None,
) -> str:
    """保存某周计划(版本化:同周再次保存 = 新版本,旧版自动归档为 archived)。

    Args:
        week_start: 周一日期 YYYY-MM-DD(非周一自动归一到当周周一)
        items: 计划项数组,每项 {date, kind(workout/diet/habit), title, detail?, est_minutes?, intensity?}
        summary: 一句话计划概要
        rationale: 生成依据/调档说明(可解释性)
        idempotency_key: 幂等键;同键重复调用返回第一次的 plan_id/version
    """
    d = _parse_date(week_start)
    if not d:
        return _msg("invalid", f"week_start 格式不正确:{week_start}")
    ws = _monday(d)
    if not items or len(items) > 30:
        return _msg("invalid", "items 需为 1~30 条")

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")

        if idempotency_key:
            ex = await _idem(session, "save_plan", idempotency_key)
            if ex and ex.target:
                parts = ex.target.split(":")   # plan:{id}:v{version}
                return _msg("duplicate", "该幂等键已保存过计划",
                            plan_id=int(parts[1]), version=int(parts[2].lstrip("v")))

        normalized, errors = _validate_plan_items(items, ws)
        if errors:
            return _msg("invalid", "计划项校验失败", errors=errors[:10])

        max_version = (
            await session.execute(
                select(func.max(M.Plan.version)).where(M.Plan.user_id == uid, M.Plan.week_start == ws)
            )
        ).scalar() or 0
        await session.execute(
            update(M.Plan)
            .where(M.Plan.user_id == uid, M.Plan.week_start == ws, M.Plan.status == "active")
            .values(status="archived")
        )
        plan = M.Plan(
            user_id=uid, week_start=ws, version=max_version + 1,
            status="active", summary=summary, rationale=rationale,
        )
        session.add(plan)
        await session.flush()
        item_objs = []
        for it in normalized:
            obj = M.PlanItem(
                plan_id=plan.id, user_id=uid, date=it["date"], kind=it["kind"],
                title=it["title"], detail=it["detail"], est_minutes=it["est_minutes"],
                intensity=it["intensity"], status="pending",
            )
            session.add(obj)
            item_objs.append(obj)
        await session.flush()
        await _audit(session, "save_plan", f"plan:{plan.id}:v{plan.version}", idempotency_key, uid)
        await session.commit()
        return _ok({
            "plan_id": plan.id, "version": plan.version, "week_start": ws.isoformat(),
            "item_count": len(item_objs),
            "items": [{"id": o.id, "date": o.date.isoformat(), "kind": o.kind, "title": o.title} for o in item_objs],
        })


@mcp.tool()
async def get_active_plan(date: str, user_id: int | None = None) -> str:
    """查询某天所在周的计划(含明细与完成率)。

    Args:
        date: 任意日期 YYYY-MM-DD(自动定位到当周)
    """
    d = _parse_date(date)
    if not d:
        return _msg("invalid", f"日期格式不正确:{date}")
    ws = _monday(d)

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        plan = (
            await session.execute(
                select(M.Plan)
                .where(M.Plan.user_id == uid, M.Plan.week_start == ws)
                .order_by((M.Plan.status == "active").desc(), M.Plan.version.desc())
                .limit(1)
            )
        ).scalars().first()
        if not plan:
            return _msg("not_found", f"{ws.isoformat()} 这一周还没有计划")
        items = (
            await session.execute(
                select(M.PlanItem).where(M.PlanItem.plan_id == plan.id).order_by(M.PlanItem.date, M.PlanItem.id)
            )
        ).scalars().all()
        progress = summarize_checkins([{"status": it.status} for it in items])
        return _ok({
            "plan_id": plan.id, "version": plan.version, "status": plan.status,
            "week_start": plan.week_start.isoformat(), "summary": plan.summary,
            "rationale": plan.rationale,
            "items": [_plan_item_view(it) for it in items],
            "progress": progress,
        })


@mcp.tool()
async def upsert_checkin(
    plan_item_id: int | None = None,
    date: str | None = None,
    kind: str = "habit",
    title: str | None = None,
    status: str = "done",
    feeling_score: int | None = None,
    note: str | None = None,
    idempotency_key: str | None = None,
    user_id: int | None = None,
) -> str:
    """打卡:更新计划内的一项(传 plan_item_id),或新增计划外自由打卡(传 date)。

    Args:
        plan_item_id: 计划项 id(模式 A:计划内打卡)
        date: 日期 YYYY-MM-DD(模式 B:计划外自由打卡)
        kind: 自由打卡类型 workout/diet/habit(默认 habit)
        title: 自由打卡标题(默认「{kind}打卡」)
        status: done(完成)/partial(部分完成)/missed(未完成)
        feeling_score: 体感评分 1~5
        note: 备注
        idempotency_key: 幂等键(自由打卡必带,防重复插入)
    """
    if status not in CHECKIN_STATUS:
        return _msg("invalid", f"status 仅支持 {sorted(CHECKIN_STATUS)}")
    if feeling_score is not None and not (FEELING_RANGE[0] <= int(feeling_score) <= FEELING_RANGE[1]):
        return _msg("invalid", "feeling_score 需在 1~5")
    if not plan_item_id and not date:
        return _msg("invalid", "需提供 plan_item_id(计划内)或 date(计划外)")

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")

        if plan_item_id:
            if idempotency_key:
                ex = await _idem(session, "upsert_checkin", idempotency_key)
                if ex:
                    return _msg("duplicate", "该幂等键已打卡", plan_item_id=int(ex.target or 0))
            item = (
                await session.execute(
                    select(M.PlanItem).where(M.PlanItem.id == int(plan_item_id), M.PlanItem.user_id == uid)
                )
            ).scalars().first()
            if not item:
                return _msg("not_found", f"计划项不存在:{plan_item_id}")
            item.status = status
            if feeling_score is not None:
                item.feeling_score = int(feeling_score)
            if note is not None:
                item.detail = note if not item.detail else f"{item.detail} | {note}"
            item.checked_at = datetime.now(timezone.utc)
            await session.flush()
            await _audit(session, "upsert_checkin", str(item.id), idempotency_key, uid)
            await session.commit()
            return _ok({"ad_hoc": False, "item": _plan_item_view(item)})

        # 模式 B:计划外自由打卡
        d = _parse_date(date)
        if not d or d > _today():
            return _msg("invalid", f"日期不合法:{date}")
        if kind not in KINDS:
            return _msg("invalid", f"kind 仅支持 {sorted(KINDS)}")
        if idempotency_key:
            ex = await _idem(session, "upsert_checkin", idempotency_key)
            if ex:
                return _msg("duplicate", "该幂等键已打卡", plan_item_id=int(ex.target or 0))
        item = M.PlanItem(
            plan_id=None, user_id=uid, date=d, kind=kind,
            title=(title or f"{kind}打卡")[:128], detail=note,
            status=status, feeling_score=int(feeling_score) if feeling_score is not None else None,
            checked_at=datetime.now(timezone.utc),
        )
        session.add(item)
        await session.flush()
        await _audit(session, "upsert_checkin", str(item.id), idempotency_key, uid)
        await session.commit()
        return _ok({"ad_hoc": True, "item": _plan_item_view(item)})


@mcp.tool()
async def get_plan_progress(week_start: str | None = None, user_id: int | None = None) -> str:
    """查看某周计划完成情况(完成率 = done + 0.5*partial;pending 不计入分母)。

    Args:
        week_start: 周一日期 YYYY-MM-DD,缺省为本周
    """
    if week_start:
        d = _parse_date(week_start)
        if not d:
            return _msg("invalid", f"日期格式不正确:{week_start}")
        ws = _monday(d)
    else:
        ws = _monday(_today())

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        items = (
            await session.execute(
                select(M.PlanItem)
                .where(M.PlanItem.user_id == uid, M.PlanItem.date.between(ws, ws + timedelta(days=6)))
                .order_by(M.PlanItem.date, M.PlanItem.id)
            )
        ).scalars().all()
        progress = summarize_checkins([{"status": it.status} for it in items])
        by_kind: dict[str, int] = {}
        for it in items:
            by_kind[it.kind] = by_kind.get(it.kind, 0) + 1
        missed = [
            {"id": it.id, "date": it.date.isoformat(), "title": it.title}
            for it in items if it.status == "missed"
        ]
        return _ok({"week_start": ws.isoformat(), "progress": progress, "by_kind": by_kind, "missed": missed})


@mcp.tool()
async def list_plans(weeks: int = 4, user_id: int | None = None) -> str:
    """返回最近 N 周计划概要(周起始/版本/状态/摘要/动作标题),按周从新到旧(供换项判断)。

    Args:
        weeks: 最近多少周(1~12,默认 4)
    """
    weeks = max(1, min(int(weeks), 12))
    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        rows = (
            await session.execute(
                select(M.Plan)
                .where(M.Plan.user_id == uid)
                .order_by(M.Plan.week_start.desc(), M.Plan.version.desc())
            )
        ).scalars().all()
        picked, seen = [], set()
        for p in rows:
            key_s = p.week_start.isoformat()
            if key_s in seen:
                continue
            seen.add(key_s)
            picked.append(p)
            if len(picked) >= weeks:
                break
        plans = []
        for p in picked:
            items = (
                await session.execute(select(M.PlanItem).where(M.PlanItem.plan_id == p.id))
            ).scalars().all()
            plans.append({
                "week_start": p.week_start.isoformat(),
                "version": p.version,
                "status": p.status,
                "summary": p.summary,
                "titles": [it.title for it in items if it.kind == "workout"],
            })
        return _ok({"count": len(plans), "plans": plans})


# ── 营养域 ───────────────────────────────────────────────────
def _food_view(f: M.NutritionFood) -> dict:
    kcal = _f(f.calories) or 0.0
    protein = _f(f.protein_g) or 0.0
    return {
        "food": f.food, "category": f.category, "calories": kcal,
        "protein_g": protein, "carbs_g": _f(f.carbs_g), "fat_g": _f(f.fat_g), "per": f.per,
        "protein_density": round(protein / kcal, 3) if kcal > 0 else None,
    }


@mcp.tool()
async def search_food(keyword: str | None = None, category: str | None = None, limit: int = 10) -> str:
    """检索营养库(推荐候选必须来自本库);默认按蛋白密度(蛋白/热量)降序。

    Args:
        keyword: 食物名关键词(模糊匹配),如 "鸡胸"
        category: 类别 蛋白质/碳水/蔬菜/水果/脂肪
        limit: 返回条数 1~50(默认 10)
    """
    limit = max(1, min(int(limit), 50))
    async with get_sessionmaker()() as session:
        q = select(M.NutritionFood)
        if keyword:
            q = q.where(M.NutritionFood.food.ilike(f"%{keyword.strip()}%"))
        if category:
            q = q.where(M.NutritionFood.category == category.strip())
        rows = (await session.execute(q)).scalars().all()
        views = [_food_view(r) for r in rows]
        views.sort(key=lambda v: (-(v["protein_density"] or 0), v["calories"]))
        return _ok({"count": len(views[:limit]), "total_matched": len(views), "foods": views[:limit]})


@mcp.tool()
async def add_meal(
    date: str,
    meal_type: str,
    items: list[dict],
    source: str = "llm",
    idempotency_key: str | None = None,
    user_id: int | None = None,
) -> str:
    """记录一餐饮食(一条 = 一个食物项);营养值缺省时按营养库自动换算。

    Args:
        date: 日期 YYYY-MM-DD
        meal_type: breakfast/lunch/dinner/snack
        items: 食物项数组 [{food, amount_g, kcal?, protein_g?, carb_g?, fat_g?}]
        source: 来源 llm/manual
        idempotency_key: 幂等键;重复调用不重复插入
    """
    d = _parse_date(date)
    if not d or d > _today():
        return _msg("invalid", f"日期不合法:{date}")
    if meal_type not in MEAL_TYPES:
        return _msg("invalid", f"meal_type 仅支持 {sorted(MEAL_TYPES)}")
    if not items or len(items) > 10:
        return _msg("invalid", "items 需为 1~10 条")

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        if idempotency_key:
            ex = await _idem(session, "add_meal", idempotency_key)
            if ex:
                return _msg("duplicate", "该幂等键已记录过这一餐", target=ex.target)

        foods = {
            f.food: f
            for f in (await session.execute(select(M.NutritionFood))).scalars().all()
        }
        inserted = 0
        errors: list[dict] = []
        totals = {"kcal": 0.0, "protein_g": 0.0, "carb_g": 0.0, "fat_g": 0.0}
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                errors.append({"index": i, "error": "条目需为对象"})
                continue
            food = (it.get("food") or "").strip()
            amount = _f(it.get("amount_g"))
            if not food or amount is None or not (0 < amount <= 2000):
                errors.append({"index": i, "error": "food 与 amount_g(0~2000)必填"})
                continue
            kcal, protein, carb, fat = (
                _f(it.get("kcal")), _f(it.get("protein_g")), _f(it.get("carb_g")), _f(it.get("fat_g")),
            )
            if kcal is None:
                ref = foods.get(food)
                if not ref:
                    errors.append({"index": i, "error": f"营养库中未找到 {food},且未提供 kcal"})
                    continue
                kcal = round((_f(ref.calories) or 0) * amount / 100, 1)
                protein = protein if protein is not None else round((_f(ref.protein_g) or 0) * amount / 100, 1)
                carb = carb if carb is not None else round((_f(ref.carbs_g) or 0) * amount / 100, 1)
                fat = fat if fat is not None else round((_f(ref.fat_g) or 0) * amount / 100, 1)
            session.add(M.Meal(
                user_id=uid, date=d, meal_type=meal_type, food=food, amount_g=amount,
                kcal=kcal, protein_g=protein, carb_g=carb, fat_g=fat, source=source,
            ))
            inserted += 1
            totals["kcal"] += kcal or 0
            totals["protein_g"] += protein or 0
            totals["carb_g"] += carb or 0
            totals["fat_g"] += fat or 0

        await session.flush()
        await _audit(session, "add_meal", f"meal:{d.isoformat()}:{meal_type}:{inserted}", idempotency_key, uid)
        await session.commit()
        return _ok({
            "inserted": inserted, "date": d.isoformat(), "meal_type": meal_type,
            "totals": {k: round(v, 1) for k, v in totals.items()},
            "errors": errors,
        })


@mcp.tool()
async def get_day_intake(date: str, user_id: int | None = None) -> str:
    """查看某天的饮食摄入汇总(按餐次 + 合计)。

    Args:
        date: 日期 YYYY-MM-DD
    """
    d = _parse_date(date)
    if not d:
        return _msg("invalid", f"日期格式不正确:{date}")
    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        rows = (
            await session.execute(
                select(M.Meal).where(M.Meal.user_id == uid, M.Meal.date == d).order_by(M.Meal.id)
            )
        ).scalars().all()
        by_meal: dict[str, dict] = {}
        total = {"kcal": 0.0, "protein_g": 0.0, "carb_g": 0.0, "fat_g": 0.0}
        items = []
        for r in rows:
            kcal, protein = _f(r.kcal) or 0, _f(r.protein_g) or 0
            blk = by_meal.setdefault(r.meal_type, {"kcal": 0.0, "protein_g": 0.0, "count": 0})
            blk["kcal"] += kcal
            blk["protein_g"] += protein
            blk["count"] += 1
            total["kcal"] += kcal
            total["protein_g"] += protein
            total["carb_g"] += _f(r.carb_g) or 0
            total["fat_g"] += _f(r.fat_g) or 0
            items.append({"meal_type": r.meal_type, "food": r.food, "amount_g": _f(r.amount_g), "kcal": kcal})
        for blk in by_meal.values():
            blk["kcal"] = round(blk["kcal"], 1)
            blk["protein_g"] = round(blk["protein_g"], 1)
        return _ok({
            "date": d.isoformat(), "meals": by_meal,
            "total": {k: round(v, 1) for k, v in total.items()},
            "items": items,
        })


# ── 画像与记忆域 ─────────────────────────────────────────────
@mcp.tool()
async def get_profile(user_id: int | None = None) -> str:
    """获取健康画像(目标/身高/目标体重/器械/饮食禁忌/伤病/日程偏好/提醒时间)。"""
    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        p = (await session.execute(select(M.Profile).where(M.Profile.user_id == uid))).scalars().first()
        if not p:
            return _msg("not_found", "画像尚未建立")
        return _ok(_profile_view(p))


def _validate_profile_patch(patch: dict) -> str | None:
    unknown = set(patch) - PROFILE_FIELDS
    if unknown:
        return f"不支持更新的字段:{sorted(unknown)}(可用:{sorted(PROFILE_FIELDS)})"
    if "goal" in patch and (not isinstance(patch["goal"], str) or len(patch["goal"]) > 32):
        return "goal 需为 ≤32 字的字符串"
    if "height_cm" in patch and not _in_range(float(patch["height_cm"]), (50, 250)):
        return "height_cm 需在 50~250"
    if "target_weight_kg" in patch and not _in_range(float(patch["target_weight_kg"]), WEIGHT_RANGE):
        return f"target_weight_kg 需在 {WEIGHT_RANGE[0]}~{WEIGHT_RANGE[1]}"
    for key in ("equipment", "dietary_restrictions", "injuries"):
        if key in patch and (not isinstance(patch[key], list) or not all(isinstance(x, str) for x in patch[key])):
            return f"{key} 需为字符串数组"
    for key in ("schedule_pref", "remind_times"):
        if key in patch and not isinstance(patch[key], dict):
            return f"{key} 需为对象"
    return None


@mcp.tool()
async def update_profile(patch: dict, idempotency_key: str | None = None, user_id: int | None = None) -> str:
    """更新健康画像(白名单字段;画像类记忆写入需经用户确认后调用)。

    Args:
        patch: 要更新的字段对象,如 {"goal": "减脂", "injuries": ["右膝不适"]}
        idempotency_key: 可选幂等键
    """
    if not isinstance(patch, dict) or not patch:
        return _msg("invalid", "patch 需为非空对象")
    err = _validate_profile_patch(patch)
    if err:
        return _msg("invalid", err)

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        p = (await session.execute(select(M.Profile).where(M.Profile.user_id == uid))).scalars().first()
        if not p:
            p = M.Profile(user_id=uid)
            session.add(p)
        for k, v in patch.items():
            if k in ("height_cm", "target_weight_kg"):
                v = float(v)
            setattr(p, k, v)
        # 显式写 updated_at:不依赖 onupdate 的 DB 生成值(commit 后访问会被标记过期,
        # 在异步会话里触发懒加载 → MissingGreenlet;2026-10-06 实测坑)
        p.updated_at = datetime.now(timezone.utc)
        await session.flush()
        await _audit(session, "update_profile", f"user:{uid}", idempotency_key, uid)
        await session.commit()
        return _ok(_profile_view(p))


@mcp.tool()
async def add_memory_event(
    kind: str,
    description: str,
    start_date: str,
    end_date: str | None = None,
    idempotency_key: str | None = None,
    user_id: int | None = None,
) -> str:
    """新增事件记忆(伤病/出差/体检等,带有效期;计划生成时作为约束注入,过期自动失效)。

    Args:
        kind: injury/travel/checkup/other
        description: 事件描述(≤500 字)
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期(可空 = 长期有效)
        idempotency_key: 幂等键;重复调用返回原事件
    """
    if kind not in EVENT_KINDS:
        return _msg("invalid", f"kind 仅支持 {sorted(EVENT_KINDS)}")
    desc = (description or "").strip()
    if not desc or len(desc) > 500:
        return _msg("invalid", "description 不能为空且 ≤500 字")
    d1 = _parse_date(start_date)
    d2 = _parse_date(end_date) if end_date else None
    if not d1 or (end_date and not d2):
        return _msg("invalid", "日期格式不正确(需 YYYY-MM-DD)")
    if d2 and d2 < d1:
        return _msg("invalid", "end_date 不能早于 start_date")

    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        if idempotency_key:
            ex = await _idem(session, "add_memory_event", idempotency_key)
            if ex and ex.target:
                return _msg("duplicate", "该幂等键已记录过事件", event_id=int(ex.target))
        ev = M.MemoryEvent(user_id=uid, kind=kind, description=desc, start_date=d1, end_date=d2)
        session.add(ev)
        await session.flush()
        await _audit(session, "add_memory_event", str(ev.id), idempotency_key, uid)
        await session.commit()
        return _ok({"event_id": ev.id, "kind": kind, "start_date": d1.isoformat(),
                    "end_date": d2.isoformat() if d2 else None})


@mcp.tool()
async def list_active_events(date: str | None = None, user_id: int | None = None) -> str:
    """查询某天仍然有效的事件记忆(条件:start_date ≤ 日期 ≤ end_date 或 end_date 为空)。

    Args:
        date: 日期 YYYY-MM-DD,缺省为今天
    """
    d = _parse_date(date) if date else _today()
    if not d:
        return _msg("invalid", f"日期格式不正确:{date}")
    async with get_sessionmaker()() as session:
        uid = await _resolve_user(session, user_id)
        if not uid:
            return _msg("not_found", "用户不存在")
        rows = (
            await session.execute(
                select(M.MemoryEvent)
                .where(
                    M.MemoryEvent.user_id == uid,
                    M.MemoryEvent.start_date <= d,
                    (M.MemoryEvent.end_date.is_(None)) | (M.MemoryEvent.end_date >= d),
                )
                .order_by(M.MemoryEvent.start_date.desc())
            )
        ).scalars().all()
        return _ok({
            "date": d.isoformat(),
            "count": len(rows),
            "events": [
                {
                    "id": r.id, "kind": r.kind, "description": r.description,
                    "start_date": r.start_date.isoformat(),
                    "end_date": r.end_date.isoformat() if r.end_date else None,
                }
                for r in rows
            ],
        })


# ── 独立运行入口(可选;默认由网关挂载)─────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = 8121
    print(f"Health MCP Server → http://localhost:{port}/mcp")
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port)
