"""Push channels usable in mainland China (docs/S8_DESIGN.md).

Each channel is enabled by its environment variable; set several to fan out.
Request formats verified against the official docs on 2026-09-28:
- Server酱 Turbo -> WeChat. SERVERCHAN_SENDKEY (SCT...).
  POST https://sctapi.ftqq.com/{SendKey}.send, form title (no newlines) + desp
  (Markdown); success code == 0. Free plan: 5 messages/day.
  https://sct.ftqq.com/docs/getting-started/faq/
- PushPlus -> WeChat. PUSHPLUS_TOKEN. POST https://www.pushplus.plus/send JSON
  {token, title, content, template}; success code == 200. Account must be
  real-name verified (error 905 otherwise). https://www.pushplus.plus/doc/guide/api.html
- 企业微信群机器人. WECOM_WEBHOOK_KEY. POST
  https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY JSON
  {"msgtype":"text","text":{"content":...}}; success errcode == 0; content
  <= 2048 bytes. https://developer.work.weixin.qq.com/document/path/91770
- 飞书自定义机器人. FEISHU_WEBHOOK_TOKEN (+ optional FEISHU_WEBHOOK_SECRET when
  signing is enabled). POST https://open.feishu.cn/open-apis/bot/v2/hook/{token}
  JSON {"msg_type":"text","content":{"text":...}}; success code == 0.
  https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
Keys sit in URLs for three of these, so errors never log the URL or response body.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("marketmind.alerts.notify")

TIMEOUT_S = 15.0
WECOM_MAX_BYTES = 2048


@dataclass
class Request:
    url: str
    json: dict | None = None
    data: dict | None = None


def _truncate_bytes(text: str, limit: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[: limit - 3].decode("utf-8", errors="ignore") + "..."


def build_requests(title: str, body: str, env=os.environ) -> dict[str, Request]:
    """channel -> request, for every channel whose variable is set."""
    title = " ".join(title.split())            # Server酱 titles cannot contain newlines
    out: dict[str, Request] = {}
    if env.get("SERVERCHAN_SENDKEY"):
        out["serverchan"] = Request(f"https://sctapi.ftqq.com/{env['SERVERCHAN_SENDKEY']}.send",
                                    data={"title": title, "desp": body.replace("\n", "\n\n")})
    if env.get("PUSHPLUS_TOKEN"):
        out["pushplus"] = Request("https://www.pushplus.plus/send",
                                  json={"token": env["PUSHPLUS_TOKEN"], "title": title[:100],
                                        "content": body, "template": "txt"})
    if env.get("WECOM_WEBHOOK_KEY"):
        out["wecom"] = Request(
            f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={env['WECOM_WEBHOOK_KEY']}",
            json={"msgtype": "text",
                  "text": {"content": _truncate_bytes(f"{title}\n{body}", WECOM_MAX_BYTES)}})
    if env.get("FEISHU_WEBHOOK_TOKEN"):
        payload: dict = {"msg_type": "text", "content": {"text": f"{title}\n{body}"}}
        secret = env.get("FEISHU_WEBHOOK_SECRET")
        if secret:
            ts = str(int(time.time()))
            sign = hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()
            payload |= {"timestamp": ts, "sign": base64.b64encode(sign).decode()}
        out["feishu"] = Request(
            f"https://open.feishu.cn/open-apis/bot/v2/hook/{env['FEISHU_WEBHOOK_TOKEN']}",
            json=payload)
    return out


def succeeded(channel: str, status: int, payload: dict) -> bool:
    if status != 200 or not isinstance(payload, dict):
        return False
    if channel == "serverchan":
        return payload.get("code") == 0
    if channel == "pushplus":
        return payload.get("code") == 200
    if channel == "wecom":
        return payload.get("errcode") == 0
    if channel == "feishu":
        return payload.get("code", payload.get("StatusCode")) == 0
    return False


async def send(title: str, body: str, *, env=os.environ,
               client: httpx.AsyncClient | None = None) -> list[dict]:
    """Send to every configured channel; returns [{channel, ok, status}] (no secrets)."""
    results = []
    reqs = build_requests(title, body, env)
    if not reqs:
        logger.warning("no push channel configured (SERVERCHAN_SENDKEY / PUSHPLUS_TOKEN / "
                       "WECOM_WEBHOOK_KEY / FEISHU_WEBHOOK_TOKEN)")
        return results
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S)
    try:
        for channel, r in reqs.items():
            status, payload = 0, {}
            try:
                resp = await client.post(r.url, json=r.json, data=r.data)
                status = resp.status_code
                try:
                    payload = resp.json()
                except ValueError:
                    payload = {}
            except Exception as e:          # the URL may hold the key: log the type only
                logger.warning("push via %s failed: %s", channel, type(e).__name__)
            ok = succeeded(channel, status, payload)
            if not ok and status:
                logger.warning("push via %s rejected: HTTP %d", channel, status)
            results.append({"channel": channel, "ok": ok, "status": status})
    finally:
        if own:
            await client.aclose()
    return results
