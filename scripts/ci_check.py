#!/usr/bin/env python3
"""仓库机检(SPEC §6 清单的机器化部分)—— CI 与 pre-push 钩子共用入口。

检查项:
  1. registry.json 与磁盘一致(gen_registry 重建比对;tools: 声明块合法性在此一并硬校验)
  2. 全 tool.yaml 必填面/semver/字符集/tested_with(PEP 440)/requires_env 形态/kind
  3. version 递增机检:对基线(origin/master,兜底 HEAD)的 registry.json,
     内容(bundle_sha256)变了版本必须升;版本永不回退;name 消失即警示(id 永不复用)
  4. 禁 import 面扫描(SPEC §3.2/§3.3):
     顶层 import 只许 标准库 + httpx + totalclaw_tool_sdk;惰性(缩进)import 放行轻量
     三方包,但重运行时(torch/cv2/...)与 agent 内部模块(totalclaw_core/...)永远禁止
  5. 危险模式扫描(SPEC §5):exec(/eval(/pip install
  6. 声明↔绑定一致性(SPEC §2/§4):tool.yaml tools: 块声明的每个 callable
     必须在 __init__.py 中以字符串字面量出现(register_tool 绑定)

用法:python3 scripts/ci_check.py [--against <git-ref>]
  --against  version 递增比对的基线 ref(默认 origin/master,不存在则 HEAD)
退出码:0 全绿;1 有 FAIL(警示不影响退出码)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_registry  # noqa: E402

ROOT = gen_registry.ROOT
TOOLS_DIR = gen_registry.TOOLS_DIR

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# tested_with:PEP 440 版本约束的宽松形态校验(逗号分隔的 比较符+版本号)
TESTED_WITH_RE = re.compile(r"^\s*(==|>=|<=|~=|!=|>|<)\s*\d+(\.\d+)*(\.\*)?"
                            r"(\s*,\s*(==|>=|<=|~=|!=|>|<)\s*\d+(\.\d+)*(\.\*)?)*\s*$")
IMPORT_RE = re.compile(r"^(\s*)(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))")

# 契约 import 面(SPEC §3.2):工具是纯函数,唯一可选的 totalclaw 面是 tool SDK
ALLOWED_PREFIXES = ("totalclaw_tool_sdk",)
ALLOWED_THIRD_PARTY = {"httpx"}
# 永远禁止(顶层与惰性一律拒):agent 内部模块 + 重运行时(SPEC §3.2/§3.3)
BANNED_PREFIXES = ("totalclaw_cli", "run_agent", "agent")
BANNED_HEAVY = {"torch", "torchvision", "torchaudio", "tensorflow", "cv2",
                "onnxruntime", "paddle", "paddlepaddle", "transformers",
                "ffmpeg", "av", "mediapipe"}
DANGEROUS_PATTERNS = [
    (re.compile(r"(?<![\w.])exec\s*\("), "exec("),
    (re.compile(r"(?<![\w.])eval\s*\("), "eval("),
    (re.compile(r"pip\s+install"), "pip install"),
]

REQUIRED_MANIFEST_FIELDS = ["manifest_version", "requires_protocol_version", "name",
                            "display_name", "version", "description", "author", "kind"]
VALID_KINDS = {"function"}

failures: list[str] = []
warnings: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


# Python <3.10 无 sys.stdlib_module_names 的兜底清单(常用标准库顶层模块)
_STDLIB_FALLBACK = frozenset({
    "abc", "argparse", "asyncio", "base64", "binascii", "bisect", "calendar",
    "collections", "concurrent", "configparser", "contextlib", "copy", "csv",
    "ctypes", "dataclasses", "datetime", "decimal", "difflib", "email", "enum",
    "errno", "fnmatch", "fractions", "functools", "gettext", "glob", "gzip",
    "hashlib", "heapq", "hmac", "html", "http", "importlib", "inspect", "io",
    "ipaddress", "itertools", "json", "logging", "math", "mimetypes",
    "multiprocessing", "operator", "os", "pathlib", "pickle", "platform",
    "plistlib", "pprint", "queue", "random", "re", "secrets", "select",
    "selectors", "shlex", "shutil", "signal", "socket", "sqlite3", "ssl",
    "stat", "statistics", "string", "struct", "subprocess", "sys", "tarfile",
    "tempfile", "textwrap", "threading", "time", "traceback", "types",
    "typing", "unicodedata", "unittest", "urllib", "uuid", "warnings",
    "weakref", "xml", "zipfile", "zlib",
})


def _stdlib_names() -> frozenset:
    return getattr(sys, "stdlib_module_names", None) or _STDLIB_FALLBACK


def iter_tool_dirs():
    for category_dir in sorted(TOOLS_DIR.iterdir()):
        if not category_dir.is_dir() or category_dir.name in gen_registry.SKIP_NAMES:
            continue
        for tool_dir in sorted(category_dir.iterdir()):
            if tool_dir.is_dir() and tool_dir.name not in gen_registry.SKIP_NAMES:
                yield category_dir.name, tool_dir


def check_registry_consistency() -> dict:
    data = gen_registry.build()
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    current = gen_registry.REGISTRY.read_text(encoding="utf-8") if gen_registry.REGISTRY.exists() else ""
    if current != rendered:
        fail("registry.json 与磁盘不一致 —— 运行 python3 scripts/gen_registry.py 重新生成")
    return data


def check_manifests() -> None:
    yaml = gen_registry._require_yaml()
    for category, tool_dir in iter_tool_dirs():
        rel = tool_dir.relative_to(ROOT).as_posix()
        manifest = yaml.safe_load((tool_dir / "tool.yaml").read_text(encoding="utf-8")) or {}
        for field in REQUIRED_MANIFEST_FIELDS:
            if not manifest.get(field):
                fail(f"{rel}/tool.yaml: 缺必填字段 {field}")
        version = str(manifest.get("version") or "")
        if version and not SEMVER_RE.match(version):
            fail(f"{rel}/tool.yaml: version={version!r} 非 semver(x.y.z)")
        kind = manifest.get("kind")
        if kind and kind not in VALID_KINDS:
            fail(f"{rel}/tool.yaml: kind={kind!r} 非法(v1 只有 {sorted(VALID_KINDS)})")
        tested_with = manifest.get("tested_with")
        if not tested_with:
            fail(f"{rel}/tool.yaml: 缺 tested_with(PEP 440 对 agent 版本)")
        elif not TESTED_WITH_RE.match(str(tested_with)):
            fail(f"{rel}/tool.yaml: tested_with={tested_with!r} 非法(需 PEP 440 约束,如 \">=0.63.72\")")
        for key in ("requires_env", "optional_env"):
            env_list = manifest.get(key) or []
            if not isinstance(env_list, list):
                fail(f"{rel}/tool.yaml: {key} 必须是列表")
                continue
            for item in env_list:
                if not isinstance(item, dict) or not item.get("name"):
                    fail(f"{rel}/tool.yaml: {key} 条目须为含 name 的对象(富对象供设置向导渲染)")
                elif key == "requires_env" and not (item.get("description") and item.get("prompt")):
                    warn(f"{rel}/tool.yaml: requires_env.{item['name']} 缺 description/prompt(向导渲染降级)")
        # 必备文件面(SPEC §1)
        for fname in ("__init__.py", "handler.py", "README.md"):
            if not (tool_dir / fname).exists():
                fail(f"{rel}: 缺必备文件 {fname}(SPEC §1)")


def _parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def check_version_monotonic(new_data: dict, baseline_ref: str | None) -> None:
    refs = [baseline_ref] if baseline_ref else ["origin/master", "HEAD"]
    old_raw = None
    used_ref = None
    for ref in refs:
        r = subprocess.run(["git", "show", f"{ref}:registry.json"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode == 0:
            old_raw, used_ref = r.stdout, ref
            break
    if old_raw is None:
        warn("找不到基线 registry.json(origin/master/HEAD 均无)——跳过 version 递增机检")
        return
    try:
        old_entries = {e["name"]: e for e in json.loads(old_raw).get("tools", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        warn(f"基线 {used_ref} 的 registry.json 解析失败——跳过 version 递增机检")
        return
    new_entries = {e["name"]: e for e in new_data.get("tools", [])}
    for name, new_e in new_entries.items():
        old_e = old_entries.get(name)
        if old_e is None:
            continue  # 新工具包
        try:
            old_v, new_v = _parse_version(old_e["version"]), _parse_version(new_e["version"])
        except ValueError:
            fail(f"{name}: 版本号无法解析比较({old_e.get('version')} → {new_e.get('version')})")
            continue
        if new_v < old_v:
            fail(f"{name}: version 回退 {old_e['version']} → {new_e['version']}(基线 {used_ref})")
        elif new_e.get("bundle_sha256") != old_e.get("bundle_sha256") and new_v <= old_v:
            fail(f"{name}: 内容变更但 version 未递增(仍为 {new_e['version']},基线 {used_ref})——发布纪律:改动必递增")
        # callable 面收缩/改名警示(模型侧函数名一经发布即有会话/配置引用)
        old_c = {p["name"] for p in old_e.get("provides", [])}
        new_c = {p["name"] for p in new_e.get("provides", [])}
        for gone in sorted(old_c - new_c):
            warn(f"{name}: callable {gone} 从声明中消失——callable name 发布后冻结(SPEC §1),确认走弃用流程")
    for name in old_entries.keys() - new_entries.keys():
        warn(f"{name}: 从 registry 消失(下架?)——注意 name/id 永不复用(SPEC §7)")


def check_import_surface() -> None:
    stdlib = _stdlib_names()
    for category, tool_dir in iter_tool_dirs():
        for py in sorted(tool_dir.rglob("*.py")):
            rel = py.relative_to(ROOT).as_posix()
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                m = IMPORT_RE.match(line)
                if not m:
                    continue
                indent, module = m.group(1), (m.group(2) or m.group(3))
                if module.startswith("."):
                    continue  # 相对 import:工具包自包含内部引用
                top = module.split(".")[0]
                loc = f"{rel}:{lineno}"
                # 永远禁止:agent 内部模块(totalclaw_* 除 SDK 面)/ 重运行时
                if any(module == p or module.startswith(p + ".") for p in BANNED_PREFIXES):
                    fail(f"{loc}: 禁止 import {module}(agent 内部模块,SPEC §3.2)")
                elif top.startswith("totalclaw") and not any(
                        module == p or module.startswith(p + ".") for p in ALLOWED_PREFIXES):
                    fail(f"{loc}: 禁止 import {module}(工具只开放 totalclaw_tool_sdk 契约面,SPEC §3.2)")
                elif top in BANNED_HEAVY:
                    fail(f"{loc}: 禁止重依赖 {top}(SPEC §3.3 零重依赖——重活归独立服务)")
                elif indent == "":
                    # 顶层 import 只许:标准库 / httpx / SDK 面
                    ok = (any(module == p or module.startswith(p + ".") for p in ALLOWED_PREFIXES)
                          or top in stdlib or top in ALLOWED_THIRD_PARTY
                          or top == "__future__")
                    if not ok:
                        fail(f"{loc}: 顶层 import {module} 不在契约面(三方包须方法内惰性 import,SPEC §3.3)")


def check_dangerous_patterns() -> None:
    for category, tool_dir in iter_tool_dirs():
        for py in sorted(tool_dir.rglob("*.py")):
            rel = py.relative_to(ROOT).as_posix()
            for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                for pattern, label in DANGEROUS_PATTERNS:
                    if pattern.search(line):
                        fail(f"{rel}:{lineno}: 危险模式 {label}(SPEC §5 禁自更新/远程代码加载)")


def check_binding_consistency() -> None:
    """SPEC §2/§4:manifest 声明的每个 callable 必须在 __init__.py 里被绑定。

    机检取最低可靠面:callable name 以字符串字面量出现在 __init__.py
    (register_tool 绑定必然携带);未出现即视为漏绑。
    """
    yaml = gen_registry._require_yaml()
    for category, tool_dir in iter_tool_dirs():
        rel = tool_dir.relative_to(ROOT).as_posix()
        init_path = tool_dir / "__init__.py"
        if not init_path.exists():
            continue  # check_manifests 已 FAIL
        src = init_path.read_text(encoding="utf-8")
        manifest = yaml.safe_load((tool_dir / "tool.yaml").read_text(encoding="utf-8")) or {}
        for item in manifest.get("tools") or []:
            cname = (item or {}).get("name")
            if not cname:
                continue  # gen_registry.build 已硬校验
            if f'"{cname}"' not in src and f"'{cname}'" not in src:
                fail(f"{rel}/__init__.py: 声明的 callable {cname} 未见绑定"
                     f"(需 ctx.register_tool(\"{cname}\", handler),SPEC §4)")
        if "def register(" not in src:
            fail(f"{rel}/__init__.py: 缺 register(ctx) 入口(SPEC §4)")


def main() -> None:
    baseline = None
    if "--against" in sys.argv:
        baseline = sys.argv[sys.argv.index("--against") + 1]
    data = check_registry_consistency()
    check_manifests()
    check_version_monotonic(data, baseline)
    check_import_surface()
    check_dangerous_patterns()
    check_binding_consistency()

    for w in warnings:
        print(f"WARN  {w}")
    for f_ in failures:
        print(f"FAIL  {f_}", file=sys.stderr)
    n = len(data.get("tools", []))
    if failures:
        print(f"\n机检未过:{len(failures)} 项 FAIL,{len(warnings)} 项警示({n} 个工具包)", file=sys.stderr)
        raise SystemExit(1)
    print(f"机检通过:{n} 个工具包,0 FAIL,{len(warnings)} 项警示")


if __name__ == "__main__":
    main()
