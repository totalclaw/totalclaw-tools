"""CHANGEME handler(纯函数薄适配器,零重依赖)。

执行契约(SPEC §4):入参与 tool.yaml tools[].parameters 声明一致;
返回 JSON 可序列化 dict;缺凭据/缺包返回引导文案,绝不抛裸异常;
网络调用显式 timeout;大文本输出截断并带 truncated 标记。
"""
from __future__ import annotations


def changeme_action(example_param: str) -> dict:
    return {
        "success": False,
        "error": "CHANGEME 工具尚未实现(模板骨架)。",
    }
