# backend/db/models.py
# P1:数据表模型(单一事实来源;DDL 由 Base.metadata 生成,scripts/init_db.py 落地)。
# 表结构对应《总体方案与流程图》§7.1:业务表 12 张 + 知识库 2 张。

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Profile(Base):
    """画像(结构化记忆):目标/身体数据/器械/禁忌/作息/提醒时间。"""

    __tablename__ = "profile"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), primary_key=True)
    goal: Mapped[str | None] = mapped_column(String(32))                  # 减脂 / 增肌 / 保持健康
    height_cm: Mapped[float | None] = mapped_column(Numeric(5, 1))
    target_weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 1))
    equipment: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    dietary_restrictions: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    injuries: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    schedule_pref: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    remind_times: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HealthRecord(Base):
    """每日健康记录:一天一条,同日均 UPSERT。"""

    __tablename__ = "health_records"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_health_records_user_date"),
        Index("ix_health_records_user_date", "user_id", "date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    workout_type: Mapped[str | None] = mapped_column(String(24))          # running / strength / rest / other
    workout_minutes: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2))
    sleep_hours: Mapped[float | None] = mapped_column(Numeric(4, 2))
    feeling: Mapped[str | None] = mapped_column(String(16))               # good / normal / tired
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), server_default=text("'manual'"))  # manual / llm / import
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Meal(Base):
    """饮食明细:一条 = 一个食物项。"""

    __tablename__ = "meals"
    __table_args__ = (Index("ix_meals_user_date", "user_id", "date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(16), nullable=False)    # breakfast / lunch / dinner / snack
    food: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_g: Mapped[float | None] = mapped_column(Numeric(7, 1))
    kcal: Mapped[float | None] = mapped_column(Numeric(7, 1))
    protein_g: Mapped[float | None] = mapped_column(Numeric(6, 1))
    carb_g: Mapped[float | None] = mapped_column(Numeric(6, 1))
    fat_g: Mapped[float | None] = mapped_column(Numeric(6, 1))
    source: Mapped[str] = mapped_column(String(16), server_default=text("'llm'"))     # llm / manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Plan(Base):
    """周计划(版本化;旧版 archived)。"""

    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", "version", name="uq_plans_user_week_version"),
        Index("ix_plans_user_week", "user_id", "week_start"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'active'"))  # active / archived
    summary: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanItem(Base):
    """计划明细 = 打卡单元;plan_id 为空表示计划外自由打卡。"""

    __tablename__ = "plan_items"
    __table_args__ = (Index("ix_plan_items_user_date", "user_id", "date"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("plans.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)          # workout / diet / habit
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    est_minutes: Mapped[int | None] = mapped_column(Integer)
    intensity: Mapped[int | None] = mapped_column(SmallInteger)            # 1 轻 / 2 中 / 3 高
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))  # pending/done/partial/missed
    feeling_score: Mapped[int | None] = mapped_column(SmallInteger)        # 1~5 体感评分
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Report(Base):
    """简报 / 周报。"""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)          # daily / weekly
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    content_md: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB)                       # 规则统计事实(可解释)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """站内信(提醒/简报/周报/预警);msg_key 唯一 = 幂等防重。"""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_user_read", "user_id", "read"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)          # checkin_remind/brief/weekly/alert
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    msg_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NutritionFood(Base):
    """营养库(每 100g);推荐候选必须来自本表。"""

    __tablename__ = "nutrition_foods"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    food: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)      # 蛋白质/碳水/蔬菜/水果/脂肪
    calories: Mapped[float] = mapped_column(Numeric(7, 1), nullable=False)
    protein_g: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False)
    carbs_g: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False)
    fat_g: Mapped[float] = mapped_column(Numeric(6, 1), nullable=False)
    per: Mapped[str] = mapped_column(String(16), server_default=text("'100g'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryEvent(Base):
    """事件记忆(伤病/出差/体检);带有效期,过期自动失效。"""

    __tablename__ = "memory_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)          # injury / travel / checkup / other
    description: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemorySummary(Base):
    """摘要记忆(会话/周期)。"""

    __tablename__ = "memory_summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)         # conversation / period
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WriteAudit(Base):
    """写操作审计(MCP 工具层写入)。"""

    __tablename__ = "write_audit"
    __table_args__ = (Index("ix_write_audit_idem", "idempotency_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    result: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbDoc(Base):
    """知识库文档(P9 建库)。"""

    __tablename__ = "kb_docs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KbChunk(Base):
    """知识库分块 + 向量(BGE-M3 维度 1024;P9 填充)。"""

    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_no", name="uq_kb_chunks_doc_chunk"),
        Index("ix_kb_chunks_doc", "doc_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("kb_docs.id"), nullable=False)
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list | None] = mapped_column(Vector(1024))
    meta: Mapped[dict | None] = mapped_column(JSONB)
