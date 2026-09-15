# ABOUTME: §3.6 回归——整节重写不得因缺冻结 Mapping 而把证据门控块的既有正文抹平。
# ABOUTME: 断言落在 apply_generation_results 这一层；端点侧的 fail-closed 前置另由 API 测试覆盖。
"""整节重写与证据门控块。

曾经的链条（逐环实测过）：整节重写调 `generate_all` 时不传 `mapped_evidence_by_block`
→ 门控块拿到 `decision=None` → 门控关闭、判 `omitted` → `_is_allowed_omission` 对门控块
**在读 `allow_contract_omissions` 之前就返回 True** → 于是「伪省略」被当成功写进账本，
既有正文被静默抹平。

因此本文件钉住两件事：

1. **受控省略确实会清空正文**——这是门控语义的一部分（该内容单元从正文与目录消失），
   不是 bug，故必须显式记录它的威力，说明为什么前置必须 fail-closed。
2. `allow_contract_omissions=False` **对门控块无效**，即调用方不能靠这个旗标自保；
   保护只能来自「装配了冻结 Mapping」或「拒绝重写」。

真正的防线是端点侧：本节含门控块而报告尚无资料快照时返回 422（见 api/app.py 的
`generate_section`）。
"""

from __future__ import annotations

import pytest

from sustainability_desk.persistence.section_generations import (
    apply_generation_results,
    material_gated_block_ids,
)
from knowledge_package_fixtures import SSE_PACKAGE

#: 上交所包里确实声明 omit_if_unsupported 的块之一（资格以编译合同为准）。
GATED_BLOCK = "sm.strategy"


def _state_with_existing_prose(block_id: str) -> dict:
    return {
        "version": 4,
        "fields": {},
        "intakeItems": {},
        "generatedBlocks": {
            block_id: {
                "content": [{"kind": "text", "text": "用户已修订过的既有正文"}],
                "state": "ready",
            }
        },
        "tableBlocks": {},
    }


def test_the_gated_block_is_really_gated_by_the_compiled_contract() -> None:
    """夹具用的块必须真的在合同声明的门控集合里，否则本文件在测一个不存在的风险。"""

    assert GATED_BLOCK in material_gated_block_ids(SSE_PACKAGE)


def test_controlled_omission_clears_prose_which_is_why_the_precondition_must_fail_closed() -> None:
    """门控块的受控省略会把正文清空——威力如此，故缺 Mapping 时必须拒绝而非放行。"""

    result = apply_generation_results(
        _state_with_existing_prose(GATED_BLOCK),
        (GATED_BLOCK,),
        [
            {
                "blockId": GATED_BLOCK,
                "kind": "paragraph",
                "status": "omitted",
                "reason": "无可采用的文件资料",
            }
        ],
        package=SSE_PACKAGE,
    )

    assert result["generatedBlocks"][GATED_BLOCK] == {"state": "omitted"}
    assert "content" not in result["generatedBlocks"][GATED_BLOCK]


def test_allow_contract_omissions_false_does_not_protect_gated_blocks() -> None:
    """该旗标对门控块无效：它在资格判定里被短路，故不能当作保护。

    这解释了为什么保护必须放在端点前置，而不是靠账本参数。
    """

    for flag in (False, True):
        result = apply_generation_results(
            _state_with_existing_prose(GATED_BLOCK),
            (GATED_BLOCK,),
            [
                {
                    "blockId": GATED_BLOCK,
                    "kind": "paragraph",
                    "status": "omitted",
                    "reason": "无可采用的文件资料",
                }
            ],
            allow_contract_omissions=flag,
            package=SSE_PACKAGE,
        )
        assert result["generatedBlocks"][GATED_BLOCK]["state"] == "omitted"


def test_omission_without_a_reason_is_rejected_regardless_of_gating() -> None:
    """没有理由的省略不算受控省略：账本按失败处理，正文不被改写。"""

    with pytest.raises(ValueError):
        apply_generation_results(
            _state_with_existing_prose(GATED_BLOCK),
            (GATED_BLOCK,),
            [{"blockId": GATED_BLOCK, "kind": "paragraph", "status": "omitted"}],
            package=SSE_PACKAGE,
        )


def test_non_gated_block_omission_is_never_accepted_as_success() -> None:
    """非门控块的省略不在合同资格内，必须失败——否则任何块都能被「省略」掉。"""

    non_gated = "climate_change.gov_structure"
    assert non_gated not in material_gated_block_ids(SSE_PACKAGE)
    with pytest.raises(ValueError):
        apply_generation_results(
            _state_with_existing_prose(non_gated),
            (non_gated,),
            [
                {
                    "blockId": non_gated,
                    "kind": "paragraph",
                    "status": "omitted",
                    "reason": "无可采用的文件资料",
                }
            ],
            package=SSE_PACKAGE,
        )
