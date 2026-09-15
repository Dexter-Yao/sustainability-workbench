# ABOUTME: 素材承载位契约测试:scope 派生完整性、放置投影合并与可渲染性门禁。
# ABOUTME: 承载位目录必须覆盖三个静态章与全部议题章节,且每 scope 唯一。
from __future__ import annotations

from uuid import uuid4

import pytest

from sustainability_desk.contract.compiled_definition import load_compiled_report_definition
from sustainability_desk.contract.layout_asset_slots import (
    layout_asset_block_by_scope,
    layout_asset_slots,
)
from sustainability_desk.contract.models import Block, ImageModel
from sustainability_desk.contract.renderability import block_is_renderable
from sustainability_desk.contract.report_revision import build_report_revision
from sustainability_desk.contract.stored_report_state import (
    StoredImageBlock,
    empty_stored_report_state,
)
from knowledge_package_fixtures import SSE_PACKAGE


def _definition():
    return load_compiled_report_definition(SSE_PACKAGE)


def test_slots_cover_static_areas_and_every_topic_section() -> None:
    definition = _definition()
    slots = layout_asset_slots(definition)
    by_scope = layout_asset_block_by_scope(definition)
    assert len(slots) == len(by_scope), "每个报告范围至多一个承载位"

    area_scopes = {s.scope_id for s in slots if s.scope_kind == "report_area"}
    assert area_scopes == {
        "report-area:company_intro",
        "report-area:governance",
        "report-area:sustainability_mgmt",
        # 可持续发展成果章的认证证书图集：证书是企业整体事实，
        # 集中承载而非按议题分散，故是报告区承载位而非议题承载位。
        "report-area:sustainable_achievements",
    }
    topic_scopes = {s.scope_id for s in slots if s.scope_kind == "esg_topic"}
    expected_topics = {
        f"report-section:{section.id}" for section in definition.report_sections
    }
    assert topic_scopes == expected_topics


def test_slot_blocks_are_not_generable_and_not_renderable_when_empty() -> None:
    state = empty_stored_report_state()
    report = build_report_revision(state, package=SSE_PACKAGE)

    def find_block(block_id: str) -> Block | None:
        def walk(sections):
            for section in sections:
                for block in section.blocks:
                    if block.id == block_id:
                        return block
                found = walk(section.children or [])
                if found is not None:
                    return found
            return None

        return walk(report.sections)

    block = find_block("company_intro.layout_assets")
    assert block is not None
    assert block.generation is None
    assert block.image is not None and block.image.layoutAssetSlot
    assert not block_is_renderable(block, report)


def test_image_block_state_projects_layout_assets_and_renders() -> None:
    state = empty_stored_report_state()
    asset_id = uuid4()
    state.imageBlocks["company_intro.layout_assets"] = StoredImageBlock(
        layoutAssetIds=[asset_id]
    )
    report = build_report_revision(state, package=SSE_PACKAGE)

    def find_block(sections):
        for section in sections:
            for block in section.blocks:
                if block.id == "company_intro.layout_assets":
                    return block
            found = find_block(section.children or [])
            if found is not None:
                return found
        return None

    block = find_block(report.sections)
    assert block is not None
    assert block.image is not None
    assert block.image.layoutAssetIds == [asset_id]
    assert block.state == "ready"
    assert block_is_renderable(block, report)


def test_layout_asset_ids_require_declared_slot() -> None:
    with pytest.raises(ValueError, match="承载位"):
        ImageModel(layoutAssetIds=[uuid4()])
    with pytest.raises(ValueError, match="一种内容来源"):
        ImageModel(
            layoutAssetSlot=True,
            layoutAssetIds=[uuid4()],
            evidenceAssetId=uuid4(),
        )
