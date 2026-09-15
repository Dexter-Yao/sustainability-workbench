# ABOUTME: 模型 provider 输出的还原边界——处理「结构被误序列化成字符串」这类 provider 行为。
# ABOUTME: 三条调用路径（正文生成、表格行、image agent）共用本模块，不各自维护还原逻辑。
# ABOUTME(en): Restoration boundary for provider output: handles structures the provider mis-serializes into strings.
# ABOUTME(en): Three call paths (prose, table rows, image agent) share this module instead of each restoring on its own.
"""Provider 输出还原。

Qwen 经工具调用（ToolOutput）提交嵌套对象/数组时，会把字段序列化成 JSON 字符串，
且输出重试不改变该行为。生成模型未启用 native_structured_output，走的正是同一条
ToolOutput 路径，故三处消费点面对的是同一个 provider 行为，而非三个独立缺陷。

还原在合同边界完成，还原后仍走同一结构校验——不是绕过校验，是让校验拿到本该拿到的形状。
"""
from __future__ import annotations

import json


def parse_stringified_json(value: object) -> object:
    """把模型误序列化成 JSON 字符串的结构还原为对象；解析失败时原样返回。

    对「本就是字符串的字段」无副作用：非 JSON 文本解析失败后原样返回。
    本函数不修复畸形 JSON——需要修复的调用方在本函数返回后自行续接。
    """

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value
