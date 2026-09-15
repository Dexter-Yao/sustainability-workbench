# ABOUTME: 契约版本标识——对一个知识包的全部作者数据文件做内容摘要。
# ABOUTME: 任何契约文件变更即产生新版本号；reports.contract_version 建报时钉住，回答"这份报告按哪个版本契约编制"。
# ABOUTME(en): Contract version identity: a content digest over one knowledge package's authoring files.
# ABOUTME(en): Any file change yields a new version; reports.contract_version is pinned at report creation.
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from sustainability_desk.contract.knowledge_packages import (
    KnowledgePackage,
    load_knowledge_package,
)


def contract_files(package: KnowledgePackage) -> tuple[Path, ...]:
    """The files whose content defines the package's contract version."""

    return package.authoring_files()


@lru_cache(maxsize=None)
def _contract_version(package_id: str) -> str:
    package = load_knowledge_package(package_id)
    digest = hashlib.sha256()
    for path in contract_files(package):
        digest.update(path.relative_to(package.root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"cv-{digest.hexdigest()[:12]}"


def contract_version(package: KnowledgePackage) -> str:
    return _contract_version(package.id)
