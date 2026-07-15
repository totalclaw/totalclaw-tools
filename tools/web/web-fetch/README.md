# web-fetch — 网页抓取

抓取指定 URL,抽取标题与正文纯文本返回给模型。标准库 `HTMLParser` 去脚本/样式 +
块级换行,零凭据、零重依赖(仅 httpx),不执行 JavaScript——重渲染场景
(SPA/反爬)不在能力边界内。

## 提供的 callable

| callable | 参数 | 说明 |
|---|---|---|
| `web_fetch` | `url`(必填)、`max_chars`(默认 8000,上限 16000) | 返回 `{success, url, status_code, title, text, truncated}` |

- 非文本内容(图片/二进制)只返回元信息(`content_type`/`size_bytes`),不回灌上下文;
- HTTP ≥400 返回 `success: false` 与状态码;
- 超时 30s,自动跟随重定向。

## 凭据

无需任何凭据。
