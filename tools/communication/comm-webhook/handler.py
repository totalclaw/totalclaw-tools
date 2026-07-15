"""webhook_send handler(纯函数薄适配器:按 webhook 域名适配三家消息格式)。

执行契约(SPEC §4):凭据只从 env 读(TOTALCLAW_TOOL_WEBHOOK_URL),
缺凭据返回引导文案;网络显式 timeout;绝不把 webhook 地址回显进返回值
(含 key/token,视同秘钥,SPEC §5)。
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

_ENV_URL = "TOTALCLAW_TOOL_WEBHOOK_URL"
_TIMEOUT_S = 15
_MAX_TEXT = 2000  # 三家机器人文本消息均有长度上限,统一保守截断


def _build_payload(host: str, text: str, at_all: bool) -> tuple[str, dict]:
    """按 webhook 域名返回 (provider, 请求体)。未知域名走通用 {"text": ...}。"""
    if host.endswith("qyapi.weixin.qq.com"):
        return "wecom", {
            "msgtype": "text",
            "text": {"content": text,
                     "mentioned_list": ["@all"] if at_all else []},
        }
    if host.endswith("oapi.dingtalk.com"):
        return "dingtalk", {
            "msgtype": "text",
            "text": {"content": text},
            "at": {"isAtAll": bool(at_all)},
        }
    if host.endswith("open.feishu.cn") or host.endswith("open.larksuite.com"):
        return "feishu", {"msg_type": "text", "content": {"text": text}}
    return "generic", {"text": text}


def _remote_error(provider: str, body: str) -> str | None:
    """解析机器人平台返回体;非零错误码返回错误信息,成功返回 None。"""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None  # 非 JSON 返回体(generic webhook),以 HTTP 状态码为准
    if not isinstance(data, dict):
        return None
    code = data.get("errcode", data.get("code", 0))
    if code not in (0, None):
        return str(data.get("errmsg") or data.get("msg") or f"平台错误码 {code}")
    return None


def webhook_send(text: str, at_all: bool = False) -> dict:
    url = os.environ.get(_ENV_URL, "").strip()
    if not url:
        return {"success": False,
                "error": f"未配置群机器人 webhook——请在 qiye-app 设置向导中配置 {_ENV_URL}"
                         "(企业微信/钉钉/飞书群里添加机器人后复制其 webhook 地址)。"}
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return {"success": False,
                "error": f"{_ENV_URL} 配置不合法(须为 https:// 开头的 webhook 地址),请重新配置。"}

    text = str(text or "").strip()
    if not text:
        return {"success": False, "error": "通知文本不能为空"}
    truncated = len(text) > _MAX_TEXT
    if truncated:
        text = text[:_MAX_TEXT]

    provider, payload = _build_payload(parsed.netloc.lower(), text, bool(at_all))

    try:
        import httpx
    except ImportError:
        return {"success": False,
                "error": "运行环境缺 httpx(agent 标配依赖)——请检查 agent 安装是否完整。"}

    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT_S)
    except httpx.HTTPError as e:
        return {"success": False, "provider": provider, "error": f"发送失败:{e}"}

    if resp.status_code >= 400:
        return {"success": False, "provider": provider,
                "error": f"发送失败:HTTP {resp.status_code}"}
    remote_err = _remote_error(provider, resp.text)
    if remote_err:
        return {"success": False, "provider": provider, "error": f"平台拒绝:{remote_err}"}
    return {"success": True, "provider": provider, "truncated": truncated}
