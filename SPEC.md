# 工具工程规范 v1

> 适用:本仓所有工具包。违反任一"硬规则"的 PR 不合并。
>
> 定位(与姊妹仓的分工):**tools = 模型可直接调用的函数单元**(name + JSON Schema 参数 + handler),
> 对应 agent 的 ToolRegistry(OpenAI-style function schema)。
> 需要生命周期 hooks / provider / 深度集成 agent 内部的能力归 totalclaw-plugins;
> 纯知识型的 markdown 指引归 totalclaw-skills。

## 1. 目录与命名

- 布局:`tools/<category>/<name>/`,安装后落 `<TOTALCLAW_HOME>/tools/<name>/`(扁平)。
- `name`(工具包名)= 全仓唯一短 ID,仅 `[a-z0-9_-]`(字母数字开头),带品类前缀防撞名
  (web 品类用 `web-`,communication 用 `comm-`,data 用 `data-`,以此类推,如 `web-fetch`)。
- 每个工具包另有**系统唯一 ID** `id = <registry>/<category>/<name>`(如
  `totalclaw-tools/web/web-fetch`),由 gen_registry.py 自动派生写入 registry——
  不进 tool.yaml、不许手填;寻址与安装协议见 §7。
- **发布后永不改名**:name/id 一经进入 master 的 registry.json 即冻结;确需改名 =
  新建工具包(新 name)+ 旧条目走弃用流程,绝不复用旧 name 指向不同工具。
- 每工具包必含:`tool.yaml`、`__init__.py`、`handler.py`、`README.md`;可选 `after-install.md`。
- **callable name**(模型可见函数名):声明于 tool.yaml `tools:` 块,snake_case
  `[a-z][a-z0-9_]*`,**全仓唯一**(所有工具包共享一个函数命名空间);一个工具包可声明
  1~N 个 callable(建议只放紧密相关的一组,如 `stock_quote` + `stock_history`)。
  callable name 同样发布后冻结。

## 2. tool.yaml 必填面

```yaml
manifest_version: 1                  # 安装器兼容检查(硬性)
requires_protocol_version: ">=1"     # 工具协议版本(安装期 strict 校验)
tested_with: ">=0.63.72"             # 实测过的 agent 版本下限(PEP 440,软检查)
name: web-fetch                      # 工具包名(与目录名一致)
display_name: 网页抓取
version: 0.1.0                       # semver;改动必须递增
description: 一句话说清能力与边界
author: totalclaw
kind: function                       # v1 只有 function(预留扩展)
tools:                               # ★ 模型可见面的单一事实源(市场/qiye-app/agent 只认这里)
  - name: web_fetch                  # callable name(snake_case,全仓唯一)
    description: 抓取网页并返回正文文本——一句话让模型知道何时调用
    parameters:                      # JSON Schema(OpenAI function 规范)
      type: object
      properties:
        url:
          type: string
          description: 目标网页 URL(http/https)
      required: [url]
requires_env:                        # 富对象:qiye-app 设置向导据此渲染表单
  - name: SOME_API_KEY
    description: 某服务 API Key
    prompt: 请输入某服务 API Key
optional_env: []
```

**单一事实源铁律**:模型看到的 name/description/parameters **只来自 tool.yaml**;
`__init__.py` 只做 handler 绑定(§4),不得在代码里另写一份 schema——防止 manifest
与代码漂移,也让市场无需执行代码即可展示工具面。

## 3. 自包含铁律(比插件更严)

1. **代码全在工具包目录内**——不得依赖 agent 仓库中"恰好存在"的内部模块。
2. **import 面只有三样**:
   - Python 标准库;
   - `httpx`(agent 保证可用的唯一三方包);
   - `totalclaw_tool_sdk.*`(可选类型/辅助面,agent 侧提供后才可用)。
   其余 `totalclaw_*`、`run_agent`、`agent.*` 一律禁止——工具不集成 agent 内部,
   handler 是纯函数,上下文由安装器注入的 `ctx` 鸭子类型承载。
3. **零重依赖**:不得引入 torch/CUDA/ffmpeg/opencv 等重运行时;重活走独立服务,
   工具只写薄适配器(HTTP/WS 客户端)。若确需轻量三方包,写进 README 声明,
   import 必须惰性(方法内 import)且缺包时返回引导文案(§4)。
4. **注册期零副作用**:`register(ctx)` 只做 handler 绑定;绝不发网络请求、绝不
   拉起进程、绝不读写全局状态。可用性判断(凭据是否配置)放到 handler 调用期。

## 4. 执行契约

```python
# __init__.py 骨架(见 tools/_TEMPLATE/)
def register(ctx):
    from .handler import web_fetch

    ctx.register_tool("web_fetch", web_fetch)   # 只许绑定 tool.yaml 已声明的 callable
```

- `ctx.register_tool(name, handler)`:name 必须与 manifest `tools:` 块中某条声明
  逐字一致(安装器校验,未声明的绑定拒绝加载);schema 由 loader 从 manifest 读取注入。
- **handler 签名**:`handler(**params)`,入参即 `tools[].parameters` 声明的字段;
  sync / async 均可(agent registry 透明 await)。
- **返回值**:JSON 可序列化 dict。成功 `{"success": True, ...}`;
  失败 `{"success": False, "error": "<人话>"}`——绝不抛裸异常给模型。
- **凭据解析**:只从 env 读(`requires_env` 声明的变量,qiye-app 向导写入);
  缺凭据时返回带"请在 qiye-app 配置 X"的引导文案,不抛异常。
- **超时纪律**:一切网络调用必须显式 timeout(单次 ≤60s);禁止无界重试。
- **大输出纪律**:返回文本默认截断(建议 ≤16k 字符)并带 `truncated` 标记,
  防止工具结果撑爆模型上下文。

## 5. 安全要求

- registry.json 由 `scripts/gen_registry.py` 生成,含逐文件 sha256——**手改 registry 无效且视为投毒**;
- 不得包含任何形式的自更新/远程代码加载(`exec` 远程内容、动态 pip install);
- 网络访问只许指向工具用途所必需的官方 endpoint 或用户配置的 endpoint;
- 秘钥只从 env 读,绝不落日志、绝不回显进返回值;
- handler 不得读写用户文件系统,除非路径由调用参数显式传入且属工具声明用途。

## 6. 发布检查清单

- [ ] tool.yaml 必填面齐全(含 `tools:` 声明块),version 已递增
- [ ] import 面合规(§3.2),重依赖为零(§3.3)
- [ ] register 零副作用;绑定的 callable 与 manifest 声明一一对应
- [ ] 缺凭据路径返回引导文案(人肉跑一遍)
- [ ] README 写清:能力/参数/凭据获取方式/输出形态
- [ ] `python3 scripts/gen_registry.py` 通过且 registry.json 已更新
- [ ] `python3 scripts/ci_check.py` 全绿

## 7. 寻址与安装协议(name / 唯一 ID / 版本钉扎)

agent(及任何安装器)对本仓工具包的寻址坐标,**双坐标 + 可选版本钉扎**,
解析规则与 totalclaw-plugins SPEC §8 完全同款:

| 坐标 | 形态 | 例 | 唯一域 |
|---|---|---|---|
| `name` | `[a-z0-9_-]` 短 ID | `web-fetch` | 本仓唯一 |
| `id` | `<registry>/<category>/<name>` | `totalclaw-tools/web/web-fetch` | 跨仓全局唯一 |

安装 spec 字符串文法:

```
spec := (id | name) ["@" version]
```

**解析规则(安装器必须实现,无歧义)**:

1. 先剥离可选 `@<version>` 后缀;
2. 剩余部分**含 `/`** → 按 `id` 字段精确匹配(name 字符集禁 `/`,故无歧义);
   不含 `/` → 按 `name` 字段精确匹配;
3. 只做大小写敏感的精确匹配,**不做模糊/前缀匹配**;未命中时可在错误信息里
   列近似候选,但绝不自动替用户选;
4. 带 `@version` 钉扎时:与 registry 当前 version 逐字比对,不一致即报错
   "registry 仅分发最新版 X,请去掉钉扎或等待发布"——本仓 raw/master 只 serve
   最新版,历史版本回溯是期权(git tag `<name>/v<version>`);
5. 完整性锚点:命中条目后以 `files[].sha256` 逐文件校验 + `bundle_sha256`
   整体校验(下载协议见 README),不是以 URL 为信任根。

**ID 稳定性契约**(为什么 agent 可以放心把 id 存进配置/会话/工单):

- `id` 由 gen_registry.py 从目录结构派生,人手不可篡改(手改 registry 视为投毒,§5);
- name/category 发布后冻结(§1)→ id 终身不变;工具包下架时条目移除,id 永不复用;
- registry 顶层 `id_scheme` 字段自描述派生规则,多仓共存时以 `registry` 字段区分命名空间。
