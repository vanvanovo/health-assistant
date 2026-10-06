# backend/api/v1/profile.py
# 画像读取/更新(画像页;与对话确认卡同一落库口径)。

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.agents.common import tools
from backend.dependencies import get_current_user

router = APIRouter(prefix="/profile", tags=["画像"])


class ProfilePatch(BaseModel):
    patch: dict


@router.get("")
async def get_profile(user: dict = Depends(get_current_user)):
    """当前画像(目标/身体数据/器械/禁忌/伤病/作息/提醒时间)。"""
    return tools.tool_data(await tools.call_tool("get_profile", {}), {}) or {}


@router.put("")
async def update_profile(req: ProfilePatch, user: dict = Depends(get_current_user)):
    """更新画像(白名单字段由 MCP 工具二次校验)。"""
    res = await tools.call_tool("update_profile", {"patch": req.patch})
    if not isinstance(res, dict) or res.get("status") not in ("success", "duplicate"):
        raise HTTPException(status_code=400, detail=(res or {}).get("message", "画像更新失败"))
    return tools.tool_data(res) or {}
