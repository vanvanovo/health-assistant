# backend/api/v1/auth.py
# 认证:演示账号登录(JWT)。

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.dependencies import create_access_token, get_current_user, verify_demo_credentials

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(req: LoginRequest):
    """演示账号登录,P4 起前端存 token 用于 SSE/REST。"""
    if not verify_demo_credentials(req.username, req.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码不正确")
    return {
        "access_token": create_access_token(req.username),
        "token_type": "bearer",
        "username": req.username,
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"]}
