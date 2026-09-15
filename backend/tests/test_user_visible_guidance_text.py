# ABOUTME: 用户可见说明文本的质量合同：两段之间、以及与标签/题干之间不得复述。
# ABOUTME: 只拦「包含式复述」这一可判定子集；改写式复述测不出来，须靠人看页面（见下方说明）。
from __future__ import annotations

import re

from sustainability_desk.contract.loader import load_contract
from knowledge_package_fixtures import SSE_PACKAGE

CONTRACT = SSE_PACKAGE.report_contract_path


def _core(text: str) -> str:
    """去掉标点与空白后的比较用词干；「公司地址。」与「公司地址」应视为同一句。"""

    return re.sub(r"[。；，、：\s（）()「」“”]", "", text or "")


def _restates(shorter: str, longer: str) -> bool:
    """一段完整包含另一段（去标点后）即视为复述——读第二遍拿不到新信息。

    局限（务必知悉）：这里只能判定「包含式复述」。把同一件事换个说法写两遍——
    例如题干写「请介绍公司主营业务与发展历程」而 hint 写
    「介绍公司主营业务与基本情况」——字面无交集，本函数判不出来。这类改写式复述
    只能靠真人打开页面看出来，不是靠测试。本文件是回归网，不是验收替代品。
    """

    a, b = _core(shorter), _core(longer)
    if not a or not b:
        return False
    return a in b or b in a


def test_input_guidance_two_segments_do_not_restate_each_other() -> None:
    report = load_contract(CONTRACT)
    offenders = [
        path
        for path, guidance in (report.inputGuidance or {}).items()
        if guidance.helpText
        and guidance.termExplanation
        and _restates(guidance.helpText, guidance.termExplanation)
    ]
    assert not offenders, f"常驻段与 ⓘ 复述同一件事：{offenders}"


def test_input_guidance_help_text_adds_something_beyond_the_field_label() -> None:
    """只把标签重说一遍的说明没有信息量，应改写成真正的填写要点或整条删除。

    判据不是「是否包含标签」——「公司官网地址；仅在选择…时填写」包含标签却补充了条件依赖，
    是合格文案。判据是「去掉标签之后还剩多少」：几乎不剩，就说明这句话只是把标签重说一遍。
    """

    report = load_contract(CONTRACT)
    offenders = []
    for path, guidance in (report.inputGuidance or {}).items():
        match = re.fullmatch(r"fields\.([A-Za-z0-9_]+)\.value", path)
        if not match:
            continue
        field = report.fields.get(match.group(1))
        if not field or not guidance.helpText:
            continue
        remainder = _core(guidance.helpText).replace(_core(field.label), "")
        if len(remainder) < 6:
            offenders.append(f"{path}：标签「{field.label}」/ 说明「{guidance.helpText}」")
    assert not offenders, "说明只是复述字段标签：" + "；".join(offenders)


def test_intake_item_hint_does_not_restate_its_own_prompt() -> None:
    """题干已说清要填什么时，hint 只该补充题干没说的部分。"""

    report = load_contract(CONTRACT)
    offenders = [
        item.key
        for item in report.intakeItems
        if item.hint and _restates(item.hint, item.prompt)
    ]
    assert not offenders, f"hint 复述题干：{offenders}"
