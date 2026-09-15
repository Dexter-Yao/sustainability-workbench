# ABOUTME: 「关于本报告」披露范围段落的变体选择合同：合并范围枚举 × 有无简称
# ABOUTME: 恰好命中一个 about.scope* 变体；未选择与历史自由文本值必须落入默认合并报表口径句。
from __future__ import annotations

from pathlib import Path

import pytest

from sustainability_desk.contract.models import Report
from sustainability_desk.contract.visibility import visible
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.loader import load_package_contract

BACKEND = Path(__file__).resolve().parents[1]

SCOPE_SLOT_IDS = (
    "about.scope",
    "about.scope_without_short_name",
    "about.scope_parent_only",
    "about.scope_parent_only_without_short_name",
    "about.scope_special",
    "about.scope_special_without_short_name",
)


def _template(SSE_PACKAGE) -> Report:
    return load_package_contract(SSE_PACKAGE)


def _with_fields(report: Report, **values: str | None) -> Report:
    fields = dict(report.fields)
    for key, value in values.items():
        fields[key] = fields[key].model_copy(update={"value": value})
    return report.model_copy(update={"fields": fields})


def _scope_blocks(report: Report) -> dict[str, object]:
    blocks: dict[str, object] = {}

    def walk(sections) -> None:
        for section in sections:
            for block in section.blocks or []:
                if block.id in SCOPE_SLOT_IDS:
                    blocks[block.id] = block
            walk(section.children or [])

    walk(report.sections)
    return blocks


def _visible_scope_ids(report: Report) -> list[str]:
    return [
        block_id
        for block_id, block in _scope_blocks(report).items()
        if visible(block, report)
    ]


@pytest.mark.parametrize(
    ("scope_value", "short_name", "expected"),
    [
        # 未选择：默认合并报表口径句。
        (None, "示例", "about.scope"),
        (None, None, "about.scope_without_short_name"),
        # 常规口径选项与默认句同文。
        ("母公司及全部并表子公司", "示例", "about.scope"),
        # 历史自由文本值（枚举化前存量）平滑落入默认句，不得让段落整体消失。
        ("本公司及纳入合并范围的子公司", "示例", "about.scope"),
        # 仅公司本部：正面陈述覆盖范围为公司本部。
        ("仅公司本部（无并表子公司）", "示例", "about.scope_parent_only"),
        ("仅公司本部（无并表子公司）", None, "about.scope_parent_only_without_short_name"),
        # 特殊口径：引用 consolidation_scope_note（缺失时 fallback，见合同 content）。
        ("特殊口径", "示例", "about.scope_special"),
        ("特殊口径", None, "about.scope_special_without_short_name"),
    ],
)
def test_exactly_one_scope_variant_visible(
    scope_value: str | None, short_name: str | None, expected: str
) -> None:
    report = _with_fields(
        _template(SSE_PACKAGE),
        consolidation_scope=scope_value,
        company_short_name=short_name,
    )
    assert _visible_scope_ids(report) == [expected]


def test_note_field_appears_only_for_special_scope() -> None:
    template = _template(SSE_PACKAGE)
    note = template.fields["consolidation_scope_note"]
    assert not visible(note, _with_fields(template, consolidation_scope=None))
    assert not visible(
        note, _with_fields(template, consolidation_scope="母公司及全部并表子公司")
    )
    assert visible(note, _with_fields(template, consolidation_scope="特殊口径"))


def test_all_scope_slots_exist_in_contract() -> None:
    assert set(_scope_blocks(_template(SSE_PACKAGE))) == set(SCOPE_SLOT_IDS)
