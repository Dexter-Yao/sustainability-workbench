# ABOUTME(en): Format profile parse-contract guard — each package's format_profile.yaml is the only SSOT of its
# ABOUTME(en): Word parameters; the id and language must agree with the package manifest.
from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.export.format_profile import (
    WordFormatProfile,
    load_format_profile,
    rgb,
)


def test_profile_parses_with_strict_schema() -> None:
    profile = load_format_profile(SSE_PACKAGE)
    assert profile.profile_id == SSE_PACKAGE.id
    assert profile.language == SSE_PACKAGE.language == "zh-Hans"
    assert profile.numbering.figure_numbering == "sequential_whole_document"
    assert profile.captions.figure_position == "below"
    assert profile.captions.table_position == "above"


def test_profile_rejects_unknown_fields() -> None:
    raw = SSE_PACKAGE.format_profile_path.read_text(encoding="utf-8") + "\nunknown_key: 1\n"

    with pytest.raises(ValidationError):
        WordFormatProfile.model_validate(yaml.safe_load(raw))


def test_rgb_helper() -> None:
    assert rgb("1F4E79") == rgb("#1F4E79")
    with pytest.raises(ValueError):
        rgb("1F4E")


def test_profile_owns_delivery_wording_and_heading_font() -> None:
    profile = load_format_profile(SSE_PACKAGE)
    assert profile.labels.toc_title == "目录"
    assert profile.labels.page_number_prefix.strip() == "第"
    assert "{year}" in profile.labels.reporting_period_template
    assert profile.headings.east_asia_font == "黑体"
    assert profile.numbering.section_scheme == "chapter_cn"
