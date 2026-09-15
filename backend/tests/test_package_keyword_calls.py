# ABOUTME(en): Static guard against package-awareness leftovers: every call to a function that requires a
# ABOUTME(en): keyword-only `package` must pass it. Two such omissions reached production workers before this test.
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "sustainability_desk"


def _functions_requiring_package() -> set[str]:
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                    if arg.arg == "package" and default is None:
                        names.add(node.name)
    return names


def test_every_call_to_a_package_requiring_function_passes_package() -> None:
    required = _functions_requiring_package()
    assert required, "expected package-aware functions in the backend"
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name not in required:
                continue
            if any(keyword.arg == "package" for keyword in node.keywords) or any(keyword.arg is None for keyword in node.keywords):
                continue
            offenders.append(f"{path.relative_to(SRC.parent)}:{node.lineno} {name}()")
    assert not offenders, offenders
