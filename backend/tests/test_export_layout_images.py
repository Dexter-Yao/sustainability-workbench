# ABOUTME: 导出补图的接缝回归——诊断组合根必须交出权威 state，导出与生成共用同一张图解析函数。
# ABOUTME: 不渲染 docx、不下载对象：只钉住「导出能拿到放置事实」这一处曾经缺失的接线。
"""导出路径的排版图片。

曾经的缺口：`/api/export` 调 `render_final_docx` 时不传 `resolved_images`，而渲染器
拿不到某块的图组时**什么都不画**（不画图、不编号、不出题注）。于是人工修订后导出
会静默丢掉用户放好的图，而生成交付物里有——两份产物在「有没有这张图」上分叉。

放置事实只在权威 `state.imageBlocks` 里，不在请求体的 Report 里，因此修复的关键是
诊断组合根要把已校验的 state 一并交出。本测试钉住这两点：组合根的返回形态，
以及导出与生成消费同一个解析函数（而非各自实现一份）。

完整的「图片真的进了 docx」属渲染保真，由 Word 验收用例覆盖（需 LibreOffice 与对象存储）。
"""

from __future__ import annotations

import inspect
import typing

from sustainability_desk.api import app as api_app
from sustainability_desk.contract.models import Report
from sustainability_desk.contract.stored_report_state import StoredReportStateV4
from sustainability_desk.diagnostics import Diagnostics
from sustainability_desk.lightweight_report_generation import resolve_layout_images


def test_diagnostics_composition_root_returns_the_authoritative_state() -> None:
    """组合根的第三个返回值是已校验 state：导出据它重建放置，不信请求体。"""

    signature = inspect.signature(api_app._stored_export_diagnostics)
    # 断言解析后的类型，而非源码里的注解字符串：inspect 会把注解求值成真实类。
    assert typing.get_args(signature.return_annotation) == (
        Diagnostics,
        Report,
        StoredReportStateV4,
    )


def test_export_and_generation_share_one_image_resolver() -> None:
    """导出与生成消费同一函数——两处各写一份必然在放置语义上漂移。"""

    source = inspect.getsource(api_app.export_report)
    assert "resolve_layout_images(" in source
    assert "resolved_images=resolved_images" in source
    # 以服务端 state 为权威，而非请求体里客户端 Report 的 layoutAssetIds。
    assert "state=stored_state" in source


def test_export_passes_state_owned_records_not_request_body() -> None:
    """记录取自 layout_asset_dal，作用域是报告本身。"""

    source = inspect.getsource(api_app.export_report)
    assert "layout_asset_dal.current_layout_asset_records(pool, report_id)" in source


async def test_resolver_is_inert_without_placements() -> None:
    """没有放置事实时解析为空映射，不构造空图组、不访问存储。"""

    resolved = await resolve_layout_images(
        object(),  # 无放置时不触碰 pool
        account_id=None,
        report_id=None,
        state=StoredReportStateV4(version=4),
        records=(),
        storage=None,
        package=None,
    )
    assert resolved == {}
