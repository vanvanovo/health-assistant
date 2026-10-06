# backend/core/notify_store.py
# 站内信 / 报告 存取层(网关内部模块;msg_key 唯一约束实现幂等)。
# 说明:站内信与报告是应用内通知数据(非 Agent 工具),直接经 SQLAlchemy 会话读写。

from __future__ import annotations

from sqlalchemy import func, select, update

from backend.config import get_settings
from backend.db import models as M
from backend.db.base import get_sessionmaker


async def _demo_uid(session) -> int | None:
    s = get_settings()
    return (
        await session.execute(select(M.User.id).where(M.User.username == s.demo_username))
    ).scalar_one_or_none()


# ── 站内信 ───────────────────────────────────────────────────
async def message_exists(msg_key: str) -> bool:
    async with get_sessionmaker()() as session:
        row = (
            await session.execute(select(M.Message.id).where(M.Message.msg_key == msg_key).limit(1))
        ).scalar_one_or_none()
        return row is not None


async def add_message(
    type: str, title: str, body: str, msg_key: str, payload: dict | None = None
) -> dict | None:
    """写入站内信;msg_key 已存在 → 返回 None(幂等跳过)。"""
    async with get_sessionmaker()() as session:
        uid = await _demo_uid(session)
        if not uid:
            return None
        exists = (
            await session.execute(select(M.Message.id).where(M.Message.msg_key == msg_key).limit(1))
        ).scalar_one_or_none()
        if exists:
            return None
        msg = M.Message(user_id=uid, type=type, title=title, body=body, payload=payload, msg_key=msg_key)
        session.add(msg)
        await session.commit()
        return {"id": msg.id, "msg_key": msg_key}


def _message_view(m: M.Message) -> dict:
    return {
        "id": m.id,
        "type": m.type,
        "title": m.title,
        "body": m.body,
        "payload": m.payload,
        "msg_key": m.msg_key,
        "read": bool(m.read),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def list_messages(unread_only: bool = False, limit: int = 50) -> list[dict]:
    async with get_sessionmaker()() as session:
        uid = await _demo_uid(session)
        if not uid:
            return []
        q = select(M.Message).where(M.Message.user_id == uid)
        if unread_only:
            q = q.where(M.Message.read.is_(False))
        rows = (
            await session.execute(q.order_by(M.Message.id.desc()).limit(limit))
        ).scalars().all()
        return [_message_view(m) for m in rows]


async def count_unread() -> int:
    async with get_sessionmaker()() as session:
        uid = await _demo_uid(session)
        if not uid:
            return 0
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(M.Message).where(
                        M.Message.user_id == uid, M.Message.read.is_(False)
                    )
                )
            ).scalar_one()
        )


async def mark_read(message_id: int | None = None, all_: bool = False) -> int:
    async with get_sessionmaker()() as session:
        uid = await _demo_uid(session)
        if not uid:
            return 0
        stmt = update(M.Message).where(M.Message.user_id == uid, M.Message.read.is_(False))
        if not all_ and message_id is not None:
            stmt = stmt.where(M.Message.id == message_id)
        result = await session.execute(stmt.values(read=True))
        await session.commit()
        return int(result.rowcount or 0)


# ── 报告 ─────────────────────────────────────────────────────
async def save_report(
    type: str, period_start: str, period_end: str, content_md: str, data: dict | None = None
) -> dict | None:
    from datetime import date as _date

    async with get_sessionmaker()() as session:
        uid = await _demo_uid(session)
        if not uid:
            return None
        rpt = M.Report(
            user_id=uid, type=type,
            period_start=_date.fromisoformat(period_start),
            period_end=_date.fromisoformat(period_end),
            content_md=content_md, data=data,
        )
        session.add(rpt)
        await session.commit()
        return {"id": rpt.id, "type": type, "period_start": period_start, "period_end": period_end}


async def list_reports(type: str | None = None, limit: int = 20) -> list[dict]:
    async with get_sessionmaker()() as session:
        uid = await _demo_uid(session)
        if not uid:
            return []
        q = select(M.Report).where(M.Report.user_id == uid)
        if type:
            q = q.where(M.Report.type == type)
        rows = (
            await session.execute(q.order_by(M.Report.id.desc()).limit(limit))
        ).scalars().all()
        return [
            {
                "id": r.id,
                "type": r.type,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "content_md": r.content_md,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
