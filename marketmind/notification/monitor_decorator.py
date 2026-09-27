"""@monitor decorator — auto-capture exception, empty return, timeout."""
from __future__ import annotations
import asyncio
import functools
import logging
import os
import time
from marketmind.notification.alert_schema import Severity, ImpactScope
from marketmind.notification.alert_manager import emit_alert
from marketmind.gateway.usage_tracker import set_stage, reset_stage

logger = logging.getLogger("marketmind.notification.monitor")

DEFAULT_TIMEOUT_SEC = 120

# LLM stages make several sequential calls, each allowed up to 120 s by the
# HTTP client, so one 120 s budget for the whole stage is too tight (live run
# 1, 2026-09-27: red team and decision both cut off at ~2 min).
STAGE_TIMEOUT_SEC = {
    "scout": 180,
    "flash_triage": 300,
    "l1_narrative": 300,
    "l2_fundamental": 300,
    "l3_technical": 180,
    "red_team": 300,
    "decision": 300,
    "reflection_agent": 300,
}


def resolve_timeout(source: str, explicit: int | None = None) -> float:
    """Stage timeout: env MARKETMIND_TIMEOUT_<SOURCE> > explicit > stage table > default."""
    env_name = "MARKETMIND_TIMEOUT_" + source.upper()
    raw = os.environ.get(env_name)
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        logger.warning("Ignoring invalid %s=%r", env_name, raw)
    if explicit is not None:
        return explicit
    return STAGE_TIMEOUT_SEC.get(source, DEFAULT_TIMEOUT_SEC)


def monitor(source: str, impact: ImpactScope = ImpactScope.MAIN_PIPELINE,
            timeout_s: int | None = None):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            timeout_s_ = resolve_timeout(source, timeout_s)
            stage_token = set_stage(source)
            try:
                result = await asyncio.wait_for(
                    func(*args, **kwargs), timeout=timeout_s_
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
                    f"{source}: timed out after {timeout_s_:g}s",
                    f"Function {func.__name__} exceeded {timeout_s_:g}s timeout",
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
            finally:
                reset_stage(stage_token)
        return wrapper
    return decorator
