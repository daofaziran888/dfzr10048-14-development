"""业务路由汇总：修订接口先于通用 /{module}/{entry_id} 路由注册。"""
from __future__ import annotations

from app.routers import resource, revision

ROUTERS = [revision, resource]
