"""@monitor decorator — auto-capture exception, empty return, timeout."""
from __future__ import annotations
import asyncio
import functools
import time
from marketmind.notification.alert_schema import Severity, ImpactScope
from marketmind.notification.alert_manager import emit_alert

DEFAULT_TIMEOUT_SEC = 120


def monitor(source: str, impact: ImpactScope = ImpactScope.MAIN_PIPELINE,
            timeout_s: int = DEFAULT_TIMEOUT_SEC):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=timeout_s
                )
                if result is None or result == "":
                    emit_alert(
                        Severity.ERROR, source, impact,
                        f"{source}: returned empty result",
                        f"Function {func.__name__} returned None or empty string",
                        "检查数据源和上游输入", degraded_output=True,
                    )
                return result
            except asyncio.TimeoutError:
                emit_alert(
                    Severity.ERROR, source, impact,
                    f"{source}: timed out after {timeout_s}s",
                    f"Function {func.__name__} exceeded {timeout_s}s timeout",
                    "检查网络连接或API响应时间", degraded_output=True,
                )
                return None
            except Exception as e:
                emit_alert(
                    Severity.ERROR, source, impact,
                    f"{source}: {type(e).__name__}",
                    str(e),
                    "需要修复 — 查看日志详情", degraded_output=True,
                )
                raise
        return wrapper
    return decorator
