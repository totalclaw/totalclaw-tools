# totalclaw-tools — TotalClaw 官方工具仓

TotalClaw agent 与 qiye-app 的**工具**分发源。工具 = 模型可直接调用的函数单元
(name + JSON Schema 参数 + handler),安装后注入 agent 的工具面。
按**工具包名称(name)或系统唯一 ID(id)**下载安装单个工具包,无需 clone 整仓。

与姊妹仓的分工:

| 仓 | 分发物 | 形态 |
|---|---|---|
| totalclaw-skills | 技能(知识) | markdown 指引,不执行代码 |
| **totalclaw-tools** | **工具(函数)** | **JSON Schema + 纯函数 handler,模型直接调用** |
| totalclaw-plugins | 插件(集成) | 生命周期 hooks / provider,深度集成 agent 内部 |

## 寻址坐标(SPEC §7)

每个工具包有两个等效寻址坐标,安装命令二者皆可:

- `name`:仓内唯一短 ID,如 `web-fetch`;
- `id`:跨仓全局唯一 ID `<registry>/<category>/<name>`,如
  `totalclaw-tools/web/web-fetch`(gen_registry 自动派生,发布后终身不变,
  适合 agent 写进配置/会话持久引用)。

解析规则:spec 含 `/` 走 id 精确匹配,否则走 name 精确匹配;可选 `@<version>` 钉扎
(与 registry 当前版本不符即报错,本仓只分发最新版)。

## 安装方式

```bash
# CLI(agent 市场机制,TOTALCLAW_TOOL_REGISTRY 指向本仓 registry.json)
totalclaw tools install web-fetch                          # 按 name
totalclaw tools install totalclaw-tools/web/web-fetch      # 按唯一 id
totalclaw tools install web-fetch@0.1.0                    # 版本钉扎
totalclaw tools enable  web-fetch   # 装完默认不启用,显式启用才生效

# REST(qiye-app 用)
POST /v1/tools/install   {"spec": "<name 或 id>[@version]"}
POST /v1/tools/<name>/enable {"enabled": true}
```

注册表地址(供 `TOTALCLAW_TOOL_REGISTRY` 配置):

```
https://gitee.com/jlzdyx/totalclaw-tools/raw/master/registry.json
```

## 仓库布局

```
registry.json                  # 市场索引(机器生成,勿手改)——name/版本/文件清单/sha256/工具 schema
scripts/gen_registry.py        # 索引生成器:遍历 tools/ 计算逐文件 sha256 与 bundle hash
scripts/ci_check.py            # 机检:registry 一致/manifest/version 递增/import 面/危险模式
SPEC.md                        # 工具工程规范(必读:自包含原则/执行契约/安全要求/发布流程)
tools/
  _TEMPLATE/                   # 新工具包模板
  web/                         # 品类目录
    web-fetch/                 # 网页抓取(标准库解析正文,零凭据)
  communication/
    comm-webhook/              # 群机器人通知(企业微信/钉钉/飞书 webhook)
```

## 工具包结构(SPEC §2-§4)

```
tools/<category>/<name>/
  tool.yaml       # manifest:元数据 + tools: 声明块(模型可见 schema 的单一事实源)
  __init__.py     # register(ctx):只做 handler 绑定,零副作用
  handler.py      # 纯函数实现(标准库 + httpx,零重依赖)
  README.md       # 能力/参数/凭据获取方式
```

模型看到的工具 schema 只来自 tool.yaml 的 `tools:` 块;代码只绑 handler——
市场与 qiye-app 无需执行任何代码即可展示工具面。

## 下载协议(客户端实现参考)

三级策略(与 totalclaw-plugins / totalclaw-skills 仓同款):

1. 读 `registry.json`(Gitee raw)→ 按 SPEC §7 解析 spec(name 或 id,可选 @version)
   命中条目,拿 `path` 与 `files[]`(相对路径+sha256);
2. 逐文件 Gitee raw 下载 → **sha256 校验**(任一不匹配即整体拒绝);
3. 兜底:`git clone --depth 1 --sparse` 只拉 `tools/<category>/<name>/`。

安装落盘到 `<TOTALCLAW_HOME>/tools/<name>/`,随后走 agent 既有流水线:
manifest 严格校验 → 内容安全扫描 → 落盘登记 → **默认禁用**,显式 enable 后由
tool loader 读 manifest 注入模型工具面并绑定 handler。

## 安全模型

- registry.json 声明每个文件的 sha256;客户端下载后必须校验;
- 工具代码在 agent 主进程执行——**默认禁用 + 安装前扫描 + 校验和**三关是底线;
- 工具只含**薄适配器**(纯函数,标准库 + httpx,几百行,零重依赖);
  重运行时/深度集成一律不进本仓(归 totalclaw-plugins 的 Runtime 部署包体系);
- 秘钥只从 env 读(`requires_env` 声明,qiye-app 向导写入),绝不落日志。

## 许可

本仓以 [Apache-2.0](LICENSE) 发布(宽松 + 显式专利授权;**推送公网前需法务终审**)。
工具若引入第三方代码,在该工具包目录 README 内逐项声明来源与许可。

## 发布流程(维护者)

1. 首次 clone 后启用机检钩子(一次性):`git config core.hooksPath scripts/hooks`;
2. 在 `tools/<category>/<name>/` 完成工具包(照 `_TEMPLATE`,过 SPEC.md 检查清单);
3. `python3 scripts/gen_registry.py` 重新生成 registry.json(校验和/schema 自检);
4. `python3 scripts/ci_check.py` 机检全绿(registry 一致/manifest 校验/version 递增/
   禁 import 面/危险模式/绑定一致性;pre-push 钩子会自动跑同一套);
5. 提交 PR / push(registry 与工具包同 commit);客户端 1 小时缓存 TTL 后可见。
