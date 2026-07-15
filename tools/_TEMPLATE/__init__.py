"""CHANGEME — TotalClaw 工具包(自包含:仅标准库 + httpx)。"""


def register(ctx):
    from .handler import changeme_action

    ctx.register_tool("changeme_action", changeme_action)
