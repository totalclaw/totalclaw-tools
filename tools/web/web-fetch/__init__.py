"""web-fetch — TotalClaw 网页抓取工具包(自包含:仅标准库 + httpx)。"""


def register(ctx):
    from .handler import web_fetch

    ctx.register_tool("web_fetch", web_fetch)
