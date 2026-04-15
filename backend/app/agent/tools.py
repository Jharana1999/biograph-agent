from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ToolCallLog


def stable_id(*parts: str) -> str:
    return hashlib.sha256("::".join(parts).encode()).hexdigest()[:24]


async def log_tool_call(
    session: AsyncSession,
    *,
    run_id: str,
    tool_name: str,
    request: dict[str, Any],
    response: dict[str, Any] | None,
    ok: bool,
    error: str | None = None,
) -> None:
    session.add(ToolCallLog(
        run_id=run_id,
        tool_name=tool_name,
        request=request,
        response=response or {},
        ok=ok,
        error=error,
    ))
    await session.commit()
