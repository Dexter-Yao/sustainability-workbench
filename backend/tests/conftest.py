# ABOUTME: pytest 公共夹具。
# ABOUTME: 提供真实模板路径、契约路径、临时输出目录；并关闭测试环境外部 LLM 追踪。
import os
from pathlib import Path

import pytest
from knowledge_package_fixtures import SSE_PACKAGE
from sustainability_desk.export.format_profile import load_format_profile

# 测试环境关闭外部追踪，避免单测（含故意失败路径）产生观测噪声。
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
# 单测不出网镜像 OTLP。sustainability_desk.llm.client import 时 load_dotenv(override=False)
# 会带入 backend/.env 的真实端点，凡走 record_* 路径的测试都会把 span 灌进启用态
# 单例并在解释器退出时出网/崩溃；置空（而非删除）才能压住 .env。
# 需要启用态镜像的测试用 monkeypatch.setenv 显式开启。
os.environ["SUSTAINABILITY_DESK_OTLP_TRACES_ENDPOINT"] = ""

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def template_docx() -> Path:
    """自有导出基底（由 export/base_template.py 生成并入库）。"""

    assert SSE_PACKAGE.base_template_path.exists(), f"导出基底缺失: {SSE_PACKAGE.base_template_path}"
    return SSE_PACKAGE.base_template_path


@pytest.fixture
def base_template(template_docx, out_dir) -> Path:
    """规范化基底：ch1 子节升 Heading 2 + 注释归正 + 目录域；build/render 基于它。"""
    from sustainability_desk.export.normalize_template import normalize_template

    return normalize_template(template_docx, out_dir / "base.docx", profile=load_format_profile(SSE_PACKAGE))


@pytest.fixture
def full_contract_yaml() -> Path:
    return SSE_PACKAGE.report_contract_path


@pytest.fixture
def sample_values_yaml() -> Path:
    return SSE_PACKAGE.sample_values_path


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    """为每个测试提供隔离的渲染输出目录，避免测试产物伪装成用户交付物。"""

    d = tmp_path / "rendered-artifacts"
    d.mkdir()
    return d
