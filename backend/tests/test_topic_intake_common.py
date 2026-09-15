from knowledge_package_fixtures import SSE_PACKAGE


# ABOUTME: topic_intake_common 固定题的投影合同：认证范围边界只随「认证」题进入消费它的块。
# ABOUTME: 锁定 generationBoundary 不进全局正文合同，避免无关块承担该文本。


def test_certification_scope_is_bounded_at_the_question_not_globally() -> None:
    """认证范围的边界随「认证」这道题投影，只进消费该题的 22 个治理块。

    认证范围（证书覆盖的产品与业务）是企业整体情况，「关于公司」已承载。一张体系认证
    常横跨多个议题——如 ISO 14001 同时适用环境、能源、污染物、
    废弃物、水资源等议题，其产品名串会在多个议题正文中重复出现。

    边界写在 `generationBoundary` 而非全局正文合同：后者会进入每一个段落块的 System，
    与认证无关的块白白承担这段文本。题目在模板里只声明一次，展开后覆盖全部议题。
    """

    import sustainability_desk.planner as planner

    items = planner._load_common_topic_intake_templates(SSE_PACKAGE.topic_intake_dir, SSE_PACKAGE)
    certs = [item for item in items if item.key.endswith("q_governance_certifications")]
    assert len(certs) == 22
    for item in certs:
        assert item.generationBoundary is not None
        assert "认证覆盖的产品与业务范围不写入本段" in item.generationBoundary
