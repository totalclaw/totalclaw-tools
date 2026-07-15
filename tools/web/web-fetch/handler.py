"""web_fetch handler(纯函数薄适配器:httpx 抓取 + 标准库 HTMLParser 抽正文)。

执行契约(SPEC §4):返回 JSON 可序列化 dict;网络显式 timeout;
输出截断带 truncated 标记;缺包/请求失败返回引导文案,绝不抛裸异常。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse

_DEFAULT_MAX_CHARS = 8000
_HARD_MAX_CHARS = 16000
_TIMEOUT_S = 30
_UA = "Mozilla/5.0 (compatible; TotalClaw/1.0; +https://gitee.com/jlzdyx/totalclaw-tools)"

_SKIP_TAGS = {"script", "style", "noscript", "template"}
_BLOCK_TAGS = {"p", "div", "section", "article", "header", "footer", "li", "tr",
               "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "blockquote", "pre"}


class _TextExtractor(HTMLParser):
    """标准库级正文抽取:跳过脚本/样式,块级标签换行,顺带取 <title>。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self._chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        elif self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r" ?\n ?", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def web_fetch(url: str, max_chars: int = _DEFAULT_MAX_CHARS) -> dict:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"success": False, "error": f"URL 不合法(仅支持 http/https):{url!r}"}
    try:
        max_chars = min(int(max_chars), _HARD_MAX_CHARS)
    except (TypeError, ValueError):
        max_chars = _DEFAULT_MAX_CHARS
    if max_chars <= 0:
        max_chars = _DEFAULT_MAX_CHARS

    try:
        import httpx
    except ImportError:
        return {"success": False,
                "error": "运行环境缺 httpx(agent 标配依赖)——请检查 agent 安装是否完整。"}

    try:
        resp = httpx.get(url, timeout=_TIMEOUT_S, follow_redirects=True,
                         headers={"User-Agent": _UA})
    except httpx.HTTPError as e:
        return {"success": False, "error": f"请求失败:{e}"}

    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    result = {
        "success": True,
        "url": str(resp.url),
        "status_code": resp.status_code,
        "content_type": content_type,
    }
    if resp.status_code >= 400:
        result["success"] = False
        result["error"] = f"HTTP {resp.status_code}"
        return result

    if content_type and not (content_type.startswith("text/")
                             or content_type in ("application/xhtml+xml", "application/xml",
                                                 "application/json")):
        # 非文本内容不回灌模型上下文,只给元信息
        result["size_bytes"] = len(resp.content)
        result["text"] = ""
        result["note"] = "非文本内容,已略过正文(如需下载文件请改用其他工具)"
        return result

    if content_type in ("text/html", "application/xhtml+xml"):
        extractor = _TextExtractor()
        extractor.feed(resp.text)
        extractor.close()
        text = extractor.text()
        result["title"] = "".join(extractor.title_parts).strip()
    else:
        text = resp.text

    result["truncated"] = len(text) > max_chars
    result["text"] = text[:max_chars]
    return result
