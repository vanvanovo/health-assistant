# backend/api/v1/jobs.py
# 主动服务手动触发(演示/验收用):无需等到 20:00/周日 即可复现四类消息。
# 生产可关:JOB_TRIGGER_ENABLED=false。

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.config import get_settings
from backend.core.jobs import JOBS
from backend.dependencies import get_current_user

router = APIRouter(prefix="/jobs", tags=["主动服务"])


class RunRequest(BaseModel):
    job: str
    date: str | None = None


@router.post("/run")
async def run_job(req: RunRequest, user: dict = Depends(get_current_user)):
    if not get_settings().job_trigger_enabled:
        raise HTTPException(status_code=403, detail="手动触发已关闭(JOB_TRIGGER_ENABLED=false)")
    fn = JOBS.get(req.job)
    if not fn:
        raise HTTPException(status_code=400, detail=f"未知任务:{req.job}(可用:{sorted(JOBS)})")
    try:
        return await fn(req.date)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"任务执行失败:{e}") from e
