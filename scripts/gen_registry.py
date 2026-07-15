#!/usr/bin/env python3
"""生成 registry.json —— 本仓唯一的索引生成入口。

遍历 tools/<category>/<name>/,读取每个 tool.yaml,计算逐文件 sha256 与
bundle_hash(排序遍历的确定性摘要,与 agent 侧 bundle_content_hash 同构),
输出市场兼容(schema_version=1)的 registry.json。

与 totalclaw-plugins 仓 gen_registry 同构;差异:manifest 为 tool.yaml,
且必须声明 `tools:` 块(模型可见 schema 的单一事实源,SPEC §2),
callable name 全仓唯一(所有工具包共享一个函数命名空间,SPEC §1)。

用法:python3 scripts/gen_registry.py [--check]
  --check  只校验现有 registry.json 是否与磁盘一致(CI 用),不一致退出码 1
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "tools"
REGISTRY = ROOT / "registry.json"
REGISTRY_NAME = "totalclaw-tools"
REPO_RAW_BASE = "https://gitee.com/jlzdyx/totalclaw-tools/raw/master"
REPO_GIT = "https://gitee.com/jlzdyx/totalclaw-tools.git"
SKIP_NAMES = {"_TEMPLATE"}
SKIP_FILES = {".DS_Store"}

# name/category/callable 字符集(SPEC §1/§7):发布后永不改名 —— id 稳定性的根基
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CATEGORY_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
CALLABLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _require_yaml():
    try:
        import yaml  # type: ignore
        return yaml
    except ImportError:
        print("需要 PyYAML:pip install pyyaml", file=sys.stderr)
        raise SystemExit(2)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bundle_hash(files: "list[dict]") -> str:
    """排序遍历的确定性 bundle 摘要:sha256(rel + ':' + file_sha256 换行拼接)。"""
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: x["path"]):
        h.update(f"{f['path']}:{f['sha256']}\n".encode("utf-8"))
    return h.hexdigest()


def _validate_tools_block(manifest_path: Path, manifest: dict) -> "list[dict]":
    """校验 tools: 声明块(SPEC §2 单一事实源),返回 provides 列表。"""
    tools = manifest.get("tools")
    if not isinstance(tools, list) or not tools:
        raise SystemExit(f"{manifest_path}: 缺 tools: 声明块(至少 1 个 callable,SPEC §2)")
    provides = []
    for item in tools:
        if not isinstance(item, dict):
            raise SystemExit(f"{manifest_path}: tools 条目须为对象")
        cname = str(item.get("name") or "").strip()
        if not CALLABLE_RE.match(cname):
            raise SystemExit(
                f"{manifest_path}: callable name={cname!r} 不合法(snake_case [a-z][a-z0-9_]*)")
        if not item.get("description"):
            raise SystemExit(f"{manifest_path}: callable {cname} 缺 description")
        params = item.get("parameters")
        if not isinstance(params, dict) or params.get("type") != "object":
            raise SystemExit(
                f"{manifest_path}: callable {cname} 的 parameters 须为 type: object 的 JSON Schema")
        provides.append({
            "name": cname,
            "description": item["description"],
            "parameters": params,
        })
    cnames = [p["name"] for p in provides]
    if len(cnames) != len(set(cnames)):
        raise SystemExit(f"{manifest_path}: tools 块内 callable name 重复")
    return provides


def _collect_tool(tool_dir: Path, category: str) -> dict:
    yaml = _require_yaml()
    manifest_path = tool_dir / "tool.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    name = str(manifest.get("name") or "").strip()
    if not name:
        raise SystemExit(f"{manifest_path}: tool.yaml 缺 name")
    if name != tool_dir.name:
        raise SystemExit(f"{manifest_path}: name={name!r} 与目录名 {tool_dir.name!r} 不一致")
    if not NAME_RE.match(name):
        raise SystemExit(f"{manifest_path}: name={name!r} 不合法(仅 [a-z0-9_-],字母数字开头)")
    if not CATEGORY_RE.match(category):
        raise SystemExit(f"tools/{category}: 品类目录名不合法(仅 [a-z0-9_],字母数字开头)")
    if manifest.get("manifest_version") != 1:
        raise SystemExit(f"{manifest_path}: manifest_version 必须为 1")
    if not manifest.get("version"):
        raise SystemExit(f"{manifest_path}: 缺 version")
    provides = _validate_tools_block(manifest_path, manifest)

    rel_root = tool_dir.relative_to(ROOT).as_posix()
    files = []
    for p in sorted(tool_dir.rglob("*")):
        if not p.is_file() or p.name in SKIP_FILES:
            continue
        rel = p.relative_to(tool_dir).as_posix()
        files.append({"path": rel, "sha256": _sha256(p), "size": p.stat().st_size})
    if not files:
        raise SystemExit(f"{tool_dir}: 空工具包目录")

    entry = {
        # ── 市场 schema v1 兼容字段(agent 既有 resolve/install 消费) ──
        "name": name,
        # 系统唯一 ID(SPEC §7):<registry>/<category>/<name>,发布后永不变;
        # 安装器按 name 或 id 均可寻址(spec 含 "/" 走 id 精确匹配)
        "id": f"{REGISTRY_NAME}/{category}/{name}",
        "display_name": manifest.get("display_name") or name,
        "description": manifest.get("description") or "",
        "version": str(manifest["version"]),
        "author": manifest.get("author") or "",
        "verified": True,  # 官方仓内置即 verified;第三方 PR 由维护者审后置位
        # tested_with 由工具包自声明(PEP 440,对 agent 版本软检查)
        **({"tested_with": manifest["tested_with"]} if manifest.get("tested_with") else {}),
        # ── 单仓多工具包扩展字段(下载器 tool_hub 消费;legacy 解析器忽略) ──
        "category": category,
        "path": rel_root,
        "raw_base": f"{REPO_RAW_BASE}/{rel_root}",
        "git_sparse": {"repo": REPO_GIT, "subdir": rel_root},
        "files": files,
        "bundle_sha256": _bundle_hash(files),
        "kind": manifest.get("kind") or "function",
        # 模型可见工具面(单一事实源,SPEC §2):市场/qiye-app 无需执行代码即可展示
        "provides": provides,
        "requires_env": manifest.get("requires_env") or [],
    }
    return entry


def build() -> dict:
    entries = []
    for category_dir in sorted(TOOLS_DIR.iterdir()):
        if not category_dir.is_dir() or category_dir.name in SKIP_NAMES:
            continue
        for tool_dir in sorted(category_dir.iterdir()):
            if not tool_dir.is_dir() or tool_dir.name in SKIP_NAMES:
                continue
            if not (tool_dir / "tool.yaml").exists():
                raise SystemExit(f"{tool_dir}: 缺 tool.yaml")
            entries.append(_collect_tool(tool_dir, category_dir.name))
    names = [e["name"] for e in entries]
    if len(names) != len(set(names)):
        raise SystemExit(f"工具包 name 重复:{sorted(n for n in names if names.count(n) > 1)}")
    callables = [p["name"] for e in entries for p in e["provides"]]
    if len(callables) != len(set(callables)):
        raise SystemExit(
            f"callable name 跨包重复(全仓共享函数命名空间,SPEC §1):"
            f"{sorted(c for c in callables if callables.count(c) > 1)}")
    return {
        "schema_version": 1,
        "registry": REGISTRY_NAME,
        "id_scheme": "<registry>/<category>/<name>",
        "source": REPO_GIT,
        "tools": entries,
    }


def main() -> None:
    data = build()
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if "--check" in sys.argv:
        current = REGISTRY.read_text(encoding="utf-8") if REGISTRY.exists() else ""
        if current != rendered:
            print("registry.json 与磁盘不一致 — 运行 python3 scripts/gen_registry.py 重新生成", file=sys.stderr)
            raise SystemExit(1)
        print(f"registry.json 一致({len(data['tools'])} 个工具包)")
        return
    REGISTRY.write_text(rendered, encoding="utf-8")
    print(f"registry.json 已生成:{len(data['tools'])} 个工具包")


if __name__ == "__main__":
    main()
