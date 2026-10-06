# backend/dependencies.py
# JWT 认证骨架(演示账号版;P4 接 users 表后换 bcrypt 校验)。

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.config import get_settings
from backend.core.exceptions import AuthenticationError

_bearer = HTTPBearer(auto_error=False)


def create_access_token(username: str, expires_minutes: int | None = None) -> str:
    """签发 JWT(演示账号用)。"""
    s = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or s.jwt_access_token_expire_minutes
    )
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    """校验并解析 JWT;失败抛 AuthenticationError。"""
    s = get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError as e:
        raise AuthenticationError(f"令牌无效或已过期: {e}") from e


def verify_demo_credentials(username: str, password: str) -> bool:
    """演示账号校验(P4 换 users 表 + bcrypt)。"""
    s = get_settings()
    return username == s.demo_username and password == s.demo_password


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """FastAPI 依赖:从 Authorization: Bearer <token> 取当前用户。"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少认证令牌")
    try:
        payload = decode_token(credentials.credentials)
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)) from e
    return {"username": payload.get("sub")}
