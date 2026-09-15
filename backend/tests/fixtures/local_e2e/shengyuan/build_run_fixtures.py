# ABOUTME: 生成晟原 corpus 的实验 CLI 输入：报告输入 recipe 与资料 selection manifest。
# ABOUTME: 指纹与 sha256 由合同和实际文件现算，不手写，避免与合同漂移。
"""生成实验 CLI 所需的两份 fixture。

- `shengyuan_report_inputs.yaml`：`sustainability_desk.local_e2e_report_input_fixture.v1`
  基础资料、治理长文本与定量指标经 inputWrites 写入；指纹由
  `LightweightReportInputAdapter.target_fingerprint()` 现算。
- `shengyuan_materials.yaml`：`sustainability_desk.local_e2e_selection_manifest.v3`
  （v3 支持 1–30 份且不要求 selectionDomains）语义 docx 与合成排版素材的路径、大小与 sha256 现算。

数值与文本的唯一来源是同目录 README.md 的「事实基准」与 `fill_workbook.py`。

用法（在 backend/ 下）：
    uv run python tests/fixtures/local_e2e/shengyuan/build_run_fixtures.py
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from sustainability_desk.material.input_adapter import LightweightReportInputAdapter

from fill_workbook import (  # type: ignore[import-not-found]
    ARTICLES,
    COMPANY_PROFILE,
    GOVERNANCE_DUTIES,
    GOVERNANCE_STRUCTURE,
    METRICS,
    SCORES,
)

FIXTURE_DIR = Path(__file__).resolve().parent
DOCX_DIR = FIXTURE_DIR / "materials_docx"
REPO_ROOT = FIXTURE_DIR.parents[4]

# 评分表行号 → 官方议题 id，与 README §2「评分表映射」同源。
SCORE_ROW_TO_TOPIC = {
    10: "climate_change",
    11: "environmental_compliance_management",
    12: "pollutant_emissions_management",
    13: "waste_management",
    14: "circular_economy_promotion",
    15: "energy_management",
    16: "water_resource_management",
    17: "ecosystem_biodiversity_protection",
    19: "human_capital_development",
    20: "occupational_health_safety",
    21: "rural_revitalization",
    22: "social_contribution",
    23: "sustainable_supply_chain_management",
    24: "sme_fair_treatment",
    25: "technology_ethics",
    26: "innovation_driven",
    27: "product_quality_safety",
    28: "customer_service_quality_management",
    29: "data_security_customer_privacy_protection",
    31: "anti_bribery_anti_corruption",
    32: "anti_unfair_competition",
    33: "risk_management",
    34: "due_diligence",
}

# target_key → 答案。字段与长文本走 field./裸 key，定量走 metric. 前缀。
FIELD_ANSWERS: dict[str, object] = {
    "field.company_short_name": "晟原精密",
    "field.industry_major_category": "制造业",
    "field.industry_division": "计算机、通信和其他电子设备制造业",
    "field.has_technology_ethics_sensitive_activity": "是",
    "field.report_approval_year": 2026,
    "field.report_approval_month": "2026-04",
    "field.report_approval_body": "董事会",
    "field.board_meeting_count": 8,
    "field.board_attendance_rate": 96,
    "company_profile": COMPANY_PROFILE,
    "articles": ARTICLES,
    "sustainability_governance_structure": GOVERNANCE_STRUCTURE,
    "sustainability_governance_duties": GOVERNANCE_DUTIES,
    "appendix.reader_feedback.address": "江苏省苏州市工业园区晟原路 18 号",
    "appendix.reader_feedback.email": "esg@example-shengyuan.com",
    "appendix.reader_feedback.phone": "0512-00000000",
}

GHG_STANDARD = "ISO 14064-1:2018及《工业企业温室气体排放核算和报告通则》（GB/T 32150-2015）"



def build_input_writes(adapter: LightweightReportInputAdapter) -> list[dict[str, object]]:
    """把答案与定量指标编成带指纹的 inputWrites。"""

    writes: list[dict[str, object]] = []

    def append(target_key: str, answer: object, supplement: str | None = None) -> None:
        entry: dict[str, object] = {
            "target_key": target_key,
            "answer": answer,
            "expected_definition_fingerprint": adapter.target_fingerprint(target_key),
            # 乐观锁：断言写入时该目标仍是空值（空白报告的当前值为 (None, None)）。
            "expected_target_fingerprint": adapter.fingerprint(None, None),
        }
        if supplement:
            entry["supplement"] = supplement
        writes.append(entry)

    for key, answer in FIELD_ANSWERS.items():
        append(key, answer)

    # 气候章节的三项核心判断（requiredBefore: generation）：完整路径据此产出
    # 物理/转型风险表与机遇表的受控行。选项取自 topic_intake/climate_change.yaml。
    for key, answer, supplement in CLIMATE_CORE_JUDGMENTS:
        append(key, answer, supplement)

    # r07 由范围一与范围二自动求和，不写入。
    for metric_key, (value, _department, remark) in METRICS.items():
        if metric_key == "economic_environment_r07":
            continue
        append(f"metric.{metric_key}", value, remark)

    return writes


def build_recipe(adapter: LightweightReportInputAdapter) -> dict[str, object]:
    scores = {
        SCORE_ROW_TO_TOPIC[row]: {"financialScore": financial, "impactScore": impact}
        for row, (financial, impact) in SCORES.items()
    }
    return {
        "contract": "sustainability_desk.local_e2e_report_input_fixture.v1",
        "fixtureId": "shengyuan-synthetic-full-lightweight-v1",
        "artifactPurpose": "local_e2e_test",
        "fixtureBasis": "simulated_for_local_e2e",
        "corpusId": MANIFEST_ID,
        "reportingEntity": "晟原精密电子股份有限公司",
        "reportingYear": 2025,
        "consolidationScope": "报告范围为公司本部及苏州主生产基地，无并表子公司。",
        "assessmentScores": scores,
        "greenhouseGasAccountingStandard": GHG_STANDARD,
        "inputWrites": build_input_writes(adapter),
    }


MANIFEST_ID = "shengyuan-synthetic-corpus"

CLIMATE_CORE_JUDGMENTS: tuple[tuple[str, object, str], ...] = (
    (
        "climate.q_climate_risk_choices",
        ["台风", "极端高温", "碳定价与排放监管政策变化", "消费者偏好转变风险"],
        "合成判断：苏州基地面临台风与夏季高温，产品出口受碳定价与客户低碳偏好影响。",
    ),
    (
        "climate.q_climate_opportunity_choices",
        ["运营资源效率提升机遇", "低碳产品方案开发机遇", "能源绿色转型"],
        "合成判断：注塑与冲压工序节能改造、低碳连接器方案与屋顶光伏。",
    ),
    (
        "climate.q_climate_target_status",
        "正在制定相关目标",
        "合成信息：正在围绕单位产值能耗与范围一二排放制定目标与口径。",
    ),
)
LAYOUT_DIR = FIXTURE_DIR.parent / "layout_assets"

# 语义资料的例外声明：默认按文件名归属，只有与报告无关的对照文件需要单独说明。
SEMANTIC_OVERRIDES: dict[str, tuple[str, str]] = {
    "食堂周菜单示例": (
        "与任何议题无关的日常行政资料，用于覆盖不相关资料的分流链路。",
        "员工食堂周菜单，行政部日常资料。",
    ),
}

# 合成排版素材（与语义资料分开上传）：识别成功 / 坏字节失败 / 气候范围 / 证书事实。
LAYOUT_ASSETS: tuple[tuple[str, dict[str, str]], ...] = (
    ("可持续发展治理组织架构图.jpg", {
        "rationale": "合成治理组织架构示意图，覆盖 Image Agent 识别、提升与确定性放置链路。",
        "analysis": "succeeded",
        "description": "公司可持续发展治理组织架构示意图，供报告排版插图使用。",
    }),
    ("损坏图片字节模拟.jpg", {
        "rationale": "合法 JPEG 头加损坏内容字节，覆盖识别失败不阻断生成且跳过放置的分支。",
        "analysis": "failed",
        "description": "本地验收合成的损坏图片字节，用于模拟素材识别失败分支。",
    }),
    ("温室气体排放核查声明示意图.jpg", {
        "rationale": "合成温室气体排放核查声明示意图；素材须落在气候议题承载位才能被放置与嵌图，因此单独提供气候范围素材。",
        "analysis": "succeeded",
        "description": "公司年度温室气体排放核查声明示意图，供气候变化章节排版插图使用。",
    }),
    ("质量管理体系认证证书示意图.jpg", {
        "rationale": "合成质量管理体系认证证书示意图，整图带「测试样例·非真实证书」水印——它会被识别成 typed 证书事实并进正文表，必须一眼可辨是测试件。",
        "analysis": "succeeded",
        "category": "certificate_or_award",
        "description": "公司质量管理体系认证证书示意图，供报告排版插图使用。",
    }),
)


def build_manifest() -> dict[str, object]:
    docx_files = sorted(DOCX_DIR.glob("*.docx"))
    if not docx_files:
        raise SystemExit(f"{DOCX_DIR} 下没有 docx，请先运行 build_materials.py")

    corpus_root = DOCX_DIR.relative_to(REPO_ROOT)
    files: list[dict[str, object]] = []
    for ordinal, path in enumerate(docx_files, start=1):
        data = path.read_bytes()
        rationale, description = SEMANTIC_OVERRIDES.get(
            path.stem,
            (
                "晟原合成 corpus 的语义资料，按文件名表达内容归属。",
                f"{path.stem}，晟原精密 2025 年度可持续发展相关资料。",
            ),
        )
        files.append(
            {
                "caseId": f"material-{ordinal:02d}",
                "ordinal": ordinal,
                "relativePath": path.name,
                "selectionRationale": rationale,
                "expectedKind": "docx",
                "expectedMediaType": (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
                "expectedSizeBytes": len(data),
                "expectedSha256": hashlib.sha256(data).hexdigest(),
                "expectedPdfPageCount": None,
                "declaration": {
                    "description": description,
                    "role": "semantic_material",
                    "topic_tags": ["uncertain"],
                },
            }
        )

    batch_size = 10
    batches = [
        [entry["caseId"] for entry in files[index : index + batch_size]]
        for index in range(0, len(files), batch_size)
    ]
    layout_assets: list[dict[str, object]] = []
    for ordinal, (filename, meta) in enumerate(LAYOUT_ASSETS, start=1):
        data = (LAYOUT_DIR / filename).read_bytes()
        entry: dict[str, object] = {
            "caseId": f"layout-{ordinal:02d}",
            "ordinal": ordinal,
            "relativePath": filename,
            "selectionRationale": meta["rationale"],
            "expectedKind": "jpeg",
            "expectedMediaType": "image/jpeg",
            "expectedSizeBytes": len(data),
            "expectedSha256": hashlib.sha256(data).hexdigest(),
            "expectedPdfPageCount": None,
            "expectedImageAnalysis": meta["analysis"],
        }
        if meta.get("category"):
            entry["expectedImageCategory"] = meta["category"]
        entry["declaration"] = {
            "description": meta["description"],
            "role": "layout_asset",
            "topic_tags": ["uncertain"],
            "asset_title": None,
        }
        layout_assets.append(entry)

    return {
        "contract": "sustainability_desk.local_e2e_selection_manifest.v3",
        "manifestId": MANIFEST_ID,
        "artifactPurpose": "local_e2e_test",
        "corpusRootRelative": str(corpus_root),
        "selectionBasis": "path_and_filename_only",
        "selectionPolicyVersion": "shengyuan-synthetic-corpus.v1",
        "selectedFileCount": len(files),
        "excludedPathSegments": [],
        "uploadBatches": batches,
        "files": files,
        "layoutAssetRootRelative": str(LAYOUT_DIR.relative_to(REPO_ROOT)),
        "layoutAssets": layout_assets,
    }


def main() -> None:
    adapter = LightweightReportInputAdapter()
    recipe_path = FIXTURE_DIR / "shengyuan_report_inputs.yaml"
    manifest_path = FIXTURE_DIR / "shengyuan_materials.yaml"

    recipe = build_recipe(adapter)
    manifest = build_manifest()

    for path, payload in ((recipe_path, recipe), (manifest_path, manifest)):
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    print(
        f"已生成 {recipe_path.name}（{len(recipe['inputWrites'])} 条写入 / "
        f"{len(recipe['assessmentScores'])} 个议题打分）"
    )
    print(f"已生成 {manifest_path.name}（{manifest['selectedFileCount']} 份资料）")


if __name__ == "__main__":
    main()
