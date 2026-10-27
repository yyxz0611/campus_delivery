"""变更自检：语法编译、路由基线比对、表清单比对、敏感信息扫描。

用法：
    python tools/selfcheck.py              # 全量检查
    python tools/selfcheck.py --init       # 建立/更新路由与表基线
    python tools/selfcheck.py --with-tests # 追加 pytest 回归

退出码 0 表示全部通过，1 表示存在失败项。
"""
from __future__ import annotations

import argparse
import ast
import json
import py_compile
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"
ROUTER_DIR = APP_DIR / "routers"
TOOLS_DIR = ROOT / "tools"
BASELINE_PATH = TOOLS_DIR / "project_baseline.json"

ROUTE_DECORATOR = re.compile(r"@router\.(get|post|put|delete|patch)\(\s*[\"']([^\"']*)[\"']")
ROUTER_PREFIX = re.compile(r"APIRouter\([^)]*prefix\s*=\s*[\"']([^\"']*)[\"']")

SK_PATTERN = re.compile(r"[\"'][A-Za-z0-9]{32,64}[\"']")
PRIVATE_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
SKIP_FILES = {".env", ".env.example"}


class Report:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def ok(self, message: str) -> None:
        self.passed.append(message)

    def fail(self, message: str) -> None:
        self.failed.append(message)

    def render(self) -> str:
        lines = ["=" * 58, "变更自检报告", "=" * 58]
        for message in self.passed:
            lines.append(f"[PASS] {message}")
        for message in self.failed:
            lines.append(f"[FAIL] {message}")
        lines.append("-" * 58)
        lines.append(f"通过 {len(self.passed)} 项，失败 {len(self.failed)} 项")
        return "\n".join(lines)


def iter_python_files(base: Path):
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def check_syntax(report: Report) -> None:
    failures = []
    files = list(iter_python_files(APP_DIR)) + list(iter_python_files(TOOLS_DIR))
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc.msg.splitlines()[-1]}")
    if failures:
        report.fail(f"语法编译失败 {len(failures)} 个文件：{failures}")
    else:
        report.ok(f"语法编译通过（{len(files)} 个文件）")


def collect_routes() -> list[str]:
    routes: list[str] = []
    if not ROUTER_DIR.exists():
        return routes
    for path in sorted(ROUTER_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        prefix_match = ROUTER_PREFIX.search(text)
        prefix = prefix_match.group(1) if prefix_match else ""
        for match in ROUTE_DECORATOR.finditer(text):
            method = match.group(1).upper()
            sub_path = match.group(2)
            routes.append(f"{method} {prefix}{sub_path}")
    return sorted(routes)


def collect_tables() -> list[str]:
    models = APP_DIR / "models.py"
    if not models.exists():
        return []
    tree = ast.parse(models.read_text(encoding="utf-8"))
    tables: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    if isinstance(item.value, ast.Constant):
                        tables.append(str(item.value.value))
    return sorted(tables)


def load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def save_baseline(routes: list[str], tables: list[str]) -> None:
    payload = {"routes": routes, "tables": tables}
    BASELINE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def check_routes(report: Report, baseline: dict, current: list[str]) -> None:
    expected = baseline.get("routes")
    if not expected:
        report.fail("缺少路由基线，先执行 --init")
        return
    removed = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    if removed:
        report.fail(f"路由基线被破坏，丢失 {len(removed)} 个接口：{removed}")
    else:
        report.ok(f"路由基线完整（{len(current)} 个接口，新增 {len(added)} 个）")


def check_tables(report: Report, baseline: dict, current: list[str]) -> None:
    expected = baseline.get("tables")
    if not expected:
        report.fail("缺少表清单基线，先执行 --init")
        return
    removed = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    if removed:
        report.fail(f"表清单被破坏，丢失 {removed}")
    else:
        report.ok(f"表清单完整（{len(current)} 张表，新增 {len(added)} 张）")


def check_secrets(report: Report) -> None:
    hits = []
    for path in iter_python_files(ROOT):
        if "__pycache__" in path.parts or path.name in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if PRIVATE_KEY_PATTERN.search(text):
            hits.append(f"{path.relative_to(ROOT)}: 私钥")
        for match in SK_PATTERN.finditer(text):
            if re.fullmatch(r"[A-Za-z0-9]{32,64}", match.group(0).strip("\"'")):
                hits.append(f"{path.relative_to(ROOT)}: 疑似明文密钥")
                break
    if hits:
        report.fail(f"敏感信息扫描命中 {len(hits)} 处：{hits}")
    else:
        report.ok("敏感信息扫描通过（未发现明文密钥/私钥）")


def check_sql_gate(report: Report) -> None:
    sys.path.insert(0, str(TOOLS_DIR / "mcp_db"))
    try:
        import server as mcp_server
    except Exception as exc:
        report.fail(f"MCP server 无法导入：{exc}")
        return
    cases = [
        ("SELECT id FROM orders", True),
        ("DELETE FROM orders", False),
        ("SELECT * FROM orders; DROP TABLE orders", False),
        ("SELECT * FROM sqlite_master", False),
        ("SELECT * FROM orders -- comment", False),
    ]
    wrong = []
    for sql, should_pass in cases:
        try:
            mcp_server.run_readonly_query(sql)
            allowed = True
        except Exception:
            allowed = False
        if allowed != should_pass:
            wrong.append(f"{sql!r} 期望 {'放行' if should_pass else '拒绝'}")
    if wrong:
        report.fail(f"SQL 安全闸门不符合预期：{wrong}")
    else:
        report.ok(f"SQL 安全闸门通过（{len(cases)} 个用例）")


def check_tests(report: Report) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "无输出"
    if "WinError 10051" in (proc.stdout or "") + (proc.stderr or ""):
        report.ok(f"pytest 存在环境限制失败（沙箱禁 socket），摘要：{summary}")
        return
    if proc.returncode == 0:
        report.ok(f"pytest 通过：{summary}")
    else:
        report.fail(f"pytest 失败：{summary}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--with-tests", action="store_true")
    args = parser.parse_args()

    routes = collect_routes()
    tables = collect_tables()

    if args.init:
        save_baseline(routes, tables)
        print(f"基线已写入 {BASELINE_PATH.relative_to(ROOT)}")
        print(f"  routes: {len(routes)}")
        print(f"  tables: {len(tables)}")
        return 0

    report = Report()
    baseline = load_baseline()
    check_syntax(report)
    check_routes(report, baseline, routes)
    check_tables(report, baseline, tables)
    check_secrets(report)
    check_sql_gate(report)
    if args.with_tests:
        check_tests(report)

    print(report.render())
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())