# ABOUTME: 公共合同与演示实例导出测试，确保生成 JSON 可由严格 Report 边界重新解析。
# ABOUTME: 导出器不得依赖 model_copy 绕过 date、month、percent 等字段类型校验。
from pathlib import Path

from sustainability_desk.contract.export_json import export_contract_json, export_instance_json
from sustainability_desk.contract.loader import load_contract
from knowledge_package_fixtures import SSE_PACKAGE

BACKEND = Path(__file__).resolve().parents[1]


def test_exported_contract_and_instance_round_trip_through_report_parser(tmp_path: Path) -> None:
    contract_path = export_contract_json(
        SSE_PACKAGE,
        tmp_path / "contract.json",
    )
    instance_path = export_instance_json(
        SSE_PACKAGE,
        tmp_path / "instance.json",
    )

    contract = load_contract(contract_path)
    instance = load_contract(instance_path)

    assert contract.title == instance.title
    assert instance.fields["report_period_start"].value == "2025-01-01"
    assert instance.fields["report_approval_month"].value == "2026-04"
    assert instance.fields["board_attendance_rate"].value == 98
    assert any(section.reportModuleId for section in instance.sections)
