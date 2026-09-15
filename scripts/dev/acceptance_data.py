# ABOUTME: 浏览器手动验收数据预处理：从 backend/tests/fixtures/local_e2e 的晟原合成 fixture 派生
# ABOUTME: 基本信息清单、上传文件与说明、评分/定量模板填充；fixture 是唯一事实源，本脚本零硬编码业务值。
"""用法（依赖 backend venv 的 openpyxl/pyyaml）：

  uv run --directory backend python ../scripts/dev/acceptance_data.py prepare
      生成验收材料到 backend/out/manual-acceptance/<今天>/：
      01-基本信息.md · 04-上传文件/（corpus 拷贝）· 05-上传文件说明清单.md

  uv run --directory backend python ../scripts/dev/acceptance_data.py workbooks [--report-id <uuid>]
      预先产出两份已填好的模板到材料目录（02-重要性评分表-已填写.xlsx /
      03-ESG定量信息-已填写.xlsx），与 01/04/05 一起备齐，用户按自己的节奏在页面
      填完基本信息后直接「导入」，全程无需等待任何命令。
      原理：模板指纹绑定 reportId 与基本信息三字段（报告年份/科技伦理答案/公司注册名），
      本命令按「用户照 01-基本信息.md 填完后」的预期状态本地生成模板——用户填的值与
      脚本预测的值同源于同一份 fixture，指纹必然一致。reportId 经只读 API 取当前账号
      created_at 最新的 active 报告（凭据走 Keychain 受控账号），不写入任何报告数据。
      仅当用户新建了另一份报告、或偏离 01 文档改动上述三字段时才需重跑。

  uv run --directory backend python ../scripts/dev/acceptance_data.py fill <评分模板.xlsx> <定量模板.xlsx>
      workbooks 的手动降级路径：把值填入从页面下载的模板，输出 *-已填写.xlsx。

完整流程与注意事项见 docs/local-e2e-acceptance.md「浏览器手动验收」一节。
"""
from __future__ import annotations

import datetime as _dt
import shutil
import os
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "local_e2e"
REPORT_INPUTS = FIXTURE_DIR / "shengyuan" / "shengyuan_report_inputs.yaml"
MATERIALS_MANIFEST = FIXTURE_DIR / "shengyuan" / "shengyuan_materials.yaml"
TOPIC_REGISTRY = REPO_ROOT / "backend" / "data" / "topic_registry.yaml"

# Excel 导入合同要求每项指标必须填数值或无值原因之一（与页面在线填写的留空语义不同）；
# fixture 未覆盖的指标统一标记「尚未收集」，与页面留空保存后的状态等价。
NO_VALUE_REASON = "not_collected"
CONFIG_SHEET = "填写说明"
GHG_STANDARD_CELL = "B8"
# 仅当基本信息「科技伦理敏感活动」答「是」时评分模板才出现本议题；fixture 未覆盖，给合成兜底分。
TECHNOLOGY_ETHICS_FALLBACK = ("科技伦理", (3.5, 3.8))


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"✗ fixture 不存在: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _topic_names_by_id() -> dict[str, str]:
    registry = _load_yaml(TOPIC_REGISTRY)
    names: dict[str, str] = {}
    for section in registry.values():
        if not isinstance(section, list):
            continue
        for entry in section:
            if isinstance(entry, dict) and "id" in entry and "name" in entry:
                names[entry["id"]] = entry["name"]
    return names


def _input_writes(inputs: dict) -> dict[str, object]:
    return {item["target_key"]: item.get("answer") for item in inputs.get("inputWrites", [])}


def cmd_prepare(out_dir: Path | None) -> None:
    inputs = _load_yaml(REPORT_INPUTS)
    manifest = _load_yaml(MATERIALS_MANIFEST)
    writes = _input_writes(inputs)
    out = out_dir or (REPO_ROOT / "backend" / "out" / "manual-acceptance" / _dt.date.today().isoformat())
    files_dir = out / "04-上传文件"
    files_dir.mkdir(parents=True, exist_ok=True)

    def w(key: str, default: str = "") -> str:
        value = writes.get(f"field.{key}", writes.get(key, default))
        return "" if value is None else str(value)

    basic = f"""# 基本信息页填写内容（/intake/info）

来源：`backend/tests/fixtures/local_e2e/shengyuan/shengyuan_report_inputs.yaml`
（`fixtureBasis: {inputs.get("fixtureBasis")}`，合成数据，不作为客户事实）。按页面节顺序整理，可直接复制。

## 公司主体（必填）

| 字段 | 填写值 |
|---|---|
| 公司注册名 | {inputs.get("reportingEntity")} |
| 公司简称 | {w("company_short_name")} |
| 所属行业门类 | {w("industry_major_category")} |
| 所属行业大类 | {w("industry_division")} |

## 公司简介（必填）

> {w("company_profile")}

## 报告期（必填）

报告年份 {inputs.get("reportingYear")}（默认值即可）；起止日期留空自动派生。

## 披露准则

保持默认（上交所指引），不勾选港交所补充。

## 适用范围（必填）

企业运营是否涉及…科技伦理敏感领域…活动？ → **{w("has_technology_ethics_sensitive_activity")}**

## 选填补充（折叠区，验证选填链路）

| 节 | 字段 | 填写值 |
|---|---|---|
| 发布与审批 | 报告发布方式 | {w("report_publication_channel")} |
| 发布与审批 | 公司官网地址 | {w("report_publication_website_url")} |
| 发布与审批 | 审批年份 | {w("report_approval_year")} |
| 发布与审批 | 审批月份 | {w("report_approval_month")} |
| 发布与审批 | 审批主体 | {w("report_approval_body")} |
| 读者反馈联系 | 联系地址 | {writes.get("appendix.reader_feedback.address", "")} |
| 读者反馈联系 | 联系邮箱 | {writes.get("appendix.reader_feedback.email", "")} |
| 读者反馈联系 | 联系电话 | {writes.get("appendix.reader_feedback.phone", "")} |
| 外部鉴证 / 治理制度 / 合并范围 | 留空 | 验证「缺值自动省略」分支 |

填完本页再去评分页——评分/定量模板的上下文指纹依赖报告年份、科技伦理答案与公司注册名，
先改基本信息会使已下载的模板失效。
"""
    (out / "01-基本信息.md").write_text(basic, encoding="utf-8")

    corpus = REPO_ROOT / manifest["corpusRootRelative"]
    lines = [
        "# 上传资料清单（步骤 4 /materials）\n",
        "文件已拷贝到本目录 `04-上传文件/`（带序号，可一次全选上传）。",
        "上传后为每份文件填写下表「说明」列的文案（来源为 fixture 内置声明）。\n",
        "| # | 文件 | 说明（复制到说明输入框） |",
        "|---|---|---|",
    ]
    for entry in manifest["files"]:
        src = corpus / entry["relativePath"]
        if not src.exists():
            raise SystemExit(
                f"✗ corpus 缺文件: {src}\n  （materials_docx/ 是派生产物，"
                "在 backend/ 下运行 tests/fixtures/local_e2e/shengyuan/build_materials.py 重生成）"
            )
        dest = files_dir / f"{entry['ordinal']:02d}-{src.name}"
        shutil.copy2(src, dest)
        lines.append(f"| {entry['ordinal']:02d} | {dest.name} | {entry['declaration']['description']} |")
    lines.append("\n全部说明填齐后点击「下一步：资料处理 →」（导航即提交，进入第 5 步逐份处理）。")
    (out / "05-上传文件说明清单.md").write_text("\n".join(lines), encoding="utf-8")
    (out / "README.md").write_text(
        "本目录由 scripts/dev/acceptance_data.py prepare 生成，可随时重建。\n"
        "完整验收流程、脚本用法与 trace 定位见 docs/local-e2e-acceptance.md「浏览器手动验收」。\n",
        encoding="utf-8",
    )
    print(f"✓ 验收材料已生成: {out}")
    print(f"  文件 {len(manifest['files'])} 份 · 基本信息与说明清单各 1 份")


def _fixture_values() -> tuple[dict[str, tuple[float, float]], dict[str, tuple[str, str]], str]:
    inputs = _load_yaml(REPORT_INPUTS)
    names = _topic_names_by_id()
    scores: dict[str, tuple[float, float]] = {}
    for topic_id, pair in inputs.get("assessmentScores", {}).items():
        name = names.get(topic_id)
        if name is None:
            raise SystemExit(f"✗ fixture 议题 {topic_id} 不在 topic_registry.yaml 中")
        scores[name] = (pair["financialScore"], pair["impactScore"])
    scores.setdefault(*TECHNOLOGY_ETHICS_FALLBACK)

    metrics: dict[str, tuple[str, str]] = {}
    for item in inputs.get("inputWrites", []):
        key = item["target_key"]
        if key.startswith("metric."):
            metrics[key.removeprefix("metric.")] = (
                str(item["answer"]),
                str(item.get("supplement", "")).strip(),
            )
    ghg_standard = str(inputs.get("greenhouseGasAccountingStandard", "")).strip()
    return scores, metrics, ghg_standard


def cmd_fill(scoring_path: Path, quant_path: Path) -> None:
    import openpyxl

    scores, metrics, ghg_standard = _fixture_values()

    workbook = openpyxl.load_workbook(scoring_path)
    filled, unmatched = 0, []
    for worksheet in workbook.worksheets:
        header_row = None
        for row in worksheet.iter_rows(min_row=1, max_row=20):
            texts = [str(cell.value or "") for cell in row]
            if any("议题" in t for t in texts) and any("财务" in t for t in texts):
                header_row = row[0].row
                break
        if header_row is None:
            continue
        for row in worksheet.iter_rows(min_row=header_row + 1):
            name = str(row[0].value or "").strip()
            if not name:
                continue
            if name in scores:
                worksheet.cell(row[0].row, 2, scores[name][0])
                worksheet.cell(row[0].row, 3, scores[name][1])
                filled += 1
            elif name not in {"环境", "社会", "治理"}:
                unmatched.append(name)
    out = scoring_path.with_name(scoring_path.stem + "-已填写.xlsx")
    workbook.save(out)
    print(f"✓ 评分表：填入 {filled} 个议题 → {out}")
    if unmatched:
        print(f"  ⚠ 模板中未匹配到分值的议题（已留空，导入会因不完整被拒）: {unmatched}")

    workbook = openpyxl.load_workbook(quant_path)
    if CONFIG_SHEET in workbook.sheetnames and ghg_standard:
        workbook[CONFIG_SHEET][GHG_STANDARD_CELL] = ghg_standard
    valued, placeholder = 0, 0
    for worksheet in workbook.worksheets:
        if worksheet.title == CONFIG_SHEET:
            continue
        for row in worksheet.iter_rows(min_row=9):
            key = str(row[0].value or "").strip()
            if not key:
                continue
            if key in metrics:
                value, note = metrics[key]
                worksheet.cell(row[0].row, 5, value)
                if note:
                    worksheet.cell(row[0].row, 8, note)
                valued += 1
            else:
                worksheet.cell(row[0].row, 6, NO_VALUE_REASON)
                placeholder += 1
    out = quant_path.with_name(quant_path.stem + "-已填写.xlsx")
    workbook.save(out)
    print(f"✓ 定量表：填入 {valued} 项数值，其余 {placeholder} 项标记「尚未收集」→ {out}")


API_BASE = "http://localhost:8010"
ACCOUNT_EMAIL = "internal-automation@example.com"
TEMPLATE_ROUTES = {
    "02-重要性评分表": "assessment/template",
    "03-ESG定量信息": "quantitative-metrics/template",
}


def _http_json(url: str, headers: dict[str, str] | None = None, payload: dict | None = None) -> dict:
    import json
    import urllib.request

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def cmd_workbooks(report_id: str | None) -> None:
    """按「照 01-基本信息.md 填完后」的预期报告状态本地生成两份已填模板；只读 API 取 reportId。"""
    sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
    from sustainability_desk.assets.quantitative_template import create_quantitative_template
    from sustainability_desk.assets.scoring_template import create_scoring_template
    from sustainability_desk.contract.compiled_definition import COMPILED_SEMANTICS_VERSION
    from sustainability_desk.contract.contract_version import contract_version
    from sustainability_desk.contract.report_revision import build_report_revision
    from sustainability_desk.contract.stored_report_state import StoredReportStateV4
    from sustainability_desk.contract.structured_inputs import StructuredInputContext

    if report_id is None:
        # 口令只经环境变量注入单次进程：公开仓库不预设 macOS Keychain，也不落文件、不进日志。
        password = os.environ.get("SUSTAINABILITY_DESK_ACCEPTANCE_PASSWORD", "").strip()
        if not password:
            raise SystemExit(
                "✗ 缺少 SUSTAINABILITY_DESK_ACCEPTANCE_PASSWORD；"
                "请设置该环境变量为验收账号口令后重试"
            )
        runtime = _http_json(f"{API_BASE}/api/runtime/client-config")
        token_payload = _http_json(
            f"{runtime['supabase_url']}/auth/v1/token?grant_type=password",
            headers={"apikey": runtime["supabase_anon_key"]},
            payload={"email": ACCOUNT_EMAIL, "password": password},
        )
        bearer = {"Authorization": f"Bearer {token_payload['access_token']}"}
        reports = _http_json(f"{API_BASE}/api/reports", headers=bearer)["reports"]
        active = [r for r in reports if r["status"] == "active"]
        if not active:
            raise SystemExit("✗ 当前账号没有 active 报告；请先在页面新建一份")
        chosen = max(active, key=lambda r: r["created_at"])
        report_id = chosen["id"]
        print(f"· 目标报告: {chosen.get('title') or report_id}（created_at 最新的 active 报告，只读取 id）")

    # 预期状态 = fixture 的基本信息（与 01-基本信息.md 同源）；用户照文档填写后服务端指纹与此一致。
    inputs = _load_yaml(REPORT_INPUTS)
    writes = _input_writes(inputs)
    state = StoredReportStateV4(version=4)
    state.fields.update({
        "company_registered_name": str(inputs.get("reportingEntity")),
        "company_short_name": str(writes.get("field.company_short_name", "")),
        "industry_major_category": str(writes.get("field.industry_major_category", "")),
        "industry_division": str(writes.get("field.industry_division", "")),
        "reporting_year": str(inputs.get("reportingYear")),
        # 定量表指纹含报告期起止：页面按默认规则由报告年份派生（YYYY-01-01 ~ YYYY-12-31），
        # 预测状态必须同源派生，否则定量表导入报 context_fingerprint / report_period 不一致。
        "report_period_start": f"{inputs.get('reportingYear')}-01-01",
        "report_period_end": f"{inputs.get('reportingYear')}-12-31",
        "has_technology_ethics_sensitive_activity": str(
            writes.get("field.has_technology_ethics_sensitive_activity", "否")
        ),
    })
    report = build_report_revision(state)
    import uuid as _uuid

    ctx = StructuredInputContext(
        reportId=_uuid.UUID(report_id),
        contractVersion=contract_version(),
        compiledSemanticsVersion=COMPILED_SEMANTICS_VERSION,
    )

    out = REPO_ROOT / "backend" / "out" / "manual-acceptance" / _dt.date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    scoring_path = out / "02-重要性评分表.xlsx"
    quant_path = out / "03-ESG定量信息.xlsx"
    scoring_path.write_bytes(create_scoring_template(report, context=ctx))
    quant_path.write_bytes(
        create_quantitative_template(report, context=ctx, allowed_metric_keys=None)
    )
    cmd_fill(scoring_path, quant_path)
    scoring_path.unlink()
    quant_path.unlink()  # 只保留 -已填写 成品，避免同目录混入未填模板
    print(f"✓ 成品在 {out}/：02-重要性评分表-已填写.xlsx · 03-ESG定量信息-已填写.xlsx")
    print("  前提：基本信息按 01-基本信息.md 填写（尤其报告年份/科技伦理/公司注册名三项）、")
    print("  且导入到上述目标报告；新建了别的报告或改动这三项时重跑本命令。")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "prepare":
        cmd_prepare(Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif len(sys.argv) >= 2 and sys.argv[1] == "workbooks":
        report_id = None
        if len(sys.argv) == 4 and sys.argv[2] == "--report-id":
            report_id = sys.argv[3]
        cmd_workbooks(report_id)
    elif len(sys.argv) == 4 and sys.argv[1] == "fill":
        for path in (Path(sys.argv[2]), Path(sys.argv[3])):
            if not path.exists():
                raise SystemExit(f"✗ 文件不存在: {path}")
        cmd_fill(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
