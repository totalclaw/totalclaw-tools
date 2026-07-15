"""comm-webhook — TotalClaw 群机器人通知工具包(自包含:仅标准库 + httpx)。"""


def register(ctx):
    from .handler import webhook_send

    ctx.register_tool("webhook_send", webhook_send)
