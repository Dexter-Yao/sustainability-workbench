# ABOUTME(en): Contract version contract tests — the digest covers every authoring file of one package,
# ABOUTME(en): keeps a stable format, and changes whenever any package file changes.
from __future__ import annotations

import hashlib

from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.contract.contract_version import contract_files, contract_version


def test_contract_files_cover_every_authoring_surface():
    names = {path.relative_to(SSE_PACKAGE.root).as_posix() for path in contract_files(SSE_PACKAGE)}
    assert "package.yaml" in names
    assert "report_contract.yaml" in names
    assert "topic_registry.yaml" in names
    assert "quantitative_metrics.json" in names
    assert "prompt_profile.yaml" in names
    assert "format_profile.yaml" in names
    assert "topic_sections/climate_change.yaml" in names
    assert "topic_intake/climate_change.yaml" in names
    assert "standard_disclosure_requirements/climate_change.yaml" in names
    # Generated deliverable templates are derived from the profile, not authored.
    assert not any(name.startswith("export/") for name in names)


def test_version_format_and_stability():
    v1 = contract_version(SSE_PACKAGE)
    assert v1.startswith("cv-") and len(v1) == 15
    assert contract_version(SSE_PACKAGE) == v1


def test_content_change_changes_digest():
    files = contract_files(SSE_PACKAGE)
    base = hashlib.sha256()
    mutated = hashlib.sha256()
    for path in files:
        relative = path.relative_to(SSE_PACKAGE.root).as_posix().encode()
        base.update(relative)
        base.update(path.read_bytes())
        mutated.update(relative)
        mutated.update(path.read_bytes())
    mutated.update(b"x")
    assert base.hexdigest() != mutated.hexdigest()
