# ABOUTME: `.env.example` 的可用性合同——模板里启用的值必须是照抄即能跑的值。
# ABOUTME: 受检的「必须绝对路径」键集从源码现算，不手写清单，避免与实现漂移。
"""环境模板合同。

README 指示用户 `cp backend/.env.example backend/.env` 后填写，因此模板里**已启用**
（未注释）的每一行都会原样成为真实配置。曾出现过
`SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT=out/report_artifacts` 这类相对路径：代码要求绝对路径，
照抄模板即让报告生成失败，而本机 `.env` 恰好没设该键，于是长期无人踩到。

本测试固化两件可机器判定的事：模板语法可解析，且凡代码强制绝对路径的键在模板里
不得以启用状态给出相对值（注释掉的示例值不受约束——它们是给人看的样例，不会生效）。
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SOURCE = BACKEND / "src" / "sustainability_desk"
ENV_EXAMPLE = BACKEND / ".env.example"

#: 形如 `KEY=value` 的启用行；注释行与空行不计。
_ENABLED_ASSIGNMENT = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*)=(?P<value>.*)$")

#: 源码里「该环境变量必须是绝对路径」的表达形态：
#: `if not root.is_absolute(): raise ...("<KEY> 必须是绝对路径")`。
#: 只认带 KEY 字面量的错误消息，因此新增同类校验会自动纳入本测试。
_ABSOLUTE_REQUIRED = re.compile(r"\"(SUSTAINABILITY_DESK_[A-Z0-9_]+) 必须是绝对路径\"")


def enabled_assignments() -> dict[str, str]:
    """解析模板中真正会生效的赋值。"""

    assignments: dict[str, str] = {}
    for raw in ENV_EXAMPLE.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENABLED_ASSIGNMENT.match(line)
        assert match is not None, f".env.example 有无法解析的行：{raw!r}"
        assignments[match.group("key")] = match.group("value").strip()
    return assignments


def keys_requiring_absolute_path() -> set[str]:
    """从源码现算出强制绝对路径的环境变量名。"""

    found: set[str] = set()
    for path in SOURCE.rglob("*.py"):
        found.update(_ABSOLUTE_REQUIRED.findall(path.read_text("utf-8")))
    return found


def test_template_is_parseable() -> None:
    """模板每一行都可解析成赋值、注释或空行。

    不断言键必须带 `SUSTAINABILITY_DESK_` 前缀：模型凭据刻意用服务商原生变量名
    （`AZURE_OPENAI_API_KEY`、`OPENAI_COMPAT_BASE_URL` 等），注册表只登记变量名、不登记值。
    """

    assignments = enabled_assignments()
    assert assignments, ".env.example 应至少启用本机栈所需的键"


def test_absolute_path_keys_are_not_enabled_with_relative_values() -> None:
    """代码强制绝对路径的键，模板不得以启用状态给出相对值。

    照抄模板必须可运行。若要在模板里示范这类键，注释掉并给绝对路径样例。
    """

    required = keys_requiring_absolute_path()
    assert required, "未能从源码识别出任何「必须是绝对路径」的键，正则可能已失效"

    assignments = enabled_assignments()
    offenders = {
        key: value
        for key, value in assignments.items()
        if key in required and value and not Path(value).is_absolute()
    }
    assert not offenders, (
        "以下键在 .env.example 里被启用且给了相对路径，照抄模板会导致运行失败："
        f"{offenders}"
    )
