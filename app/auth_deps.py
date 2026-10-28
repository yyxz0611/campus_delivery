"""统一鉴权依赖：解析 x-auth-token 并校验角色。

与各 router 里手写 parse_token 的区别：依赖注入一次声明，
路由函数不再重复判空与判断角色。
"""

from __future__ import annotations

from typing import Callable

from fastapi import Header, HTTPException

from .security import parse_token


def require_role(*roles: str) -> Callable:
    def dependency(x_auth_token: str | None = Header(None)) -> tuple[int, str]:
        current = parse_token(x_auth_token)
        if not current:
            raise HTTPException(401, "未登录或登录已过期")

        user_id, role = current
        if roles and role not in roles:
            raise HTTPException(403, "无权访问该接口")

        return user_id, role

    return dependency