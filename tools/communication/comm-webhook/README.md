# comm-webhook — 群机器人通知

通过用户配置的群机器人 webhook 发送文本通知。按 webhook 域名自动适配消息格式:

| 平台 | 域名 | @所有人 |
|---|---|---|
| 企业微信 | `qyapi.weixin.qq.com` | 支持(`at_all: true`) |
| 钉钉 | `oapi.dingtalk.com` | 支持(`at_all: true`) |
| 飞书/Lark | `open.feishu.cn` / `open.larksuite.com` | 不支持(参数忽略) |
| 其他 | 任意 https 地址 | 通用 `{"text": ...}` 格式 |

## 提供的 callable

| callable | 参数 | 说明 |
|---|---|---|
| `webhook_send` | `text`(必填)、`at_all`(默认 false) | 返回 `{success, provider, truncated}`;文本超 2000 字符自动截断 |

## 凭据

| env | 获取方式 |
|---|---|
| `TOTALCLAW_TOOL_WEBHOOK_URL` | 在群设置里添加"群机器人",复制其 webhook 地址(企业微信/钉钉/飞书均可) |

钉钉机器人若开启"加签"安全设置,本工具暂不支持(v1 只支持关键词/IP 白名单模式);
webhook 地址含 key/token,视同秘钥——工具不会在返回值或日志中回显。
