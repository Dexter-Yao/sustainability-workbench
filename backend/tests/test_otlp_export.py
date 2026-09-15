# ABOUTME: OTLP 镜像投影的合同测试——默认停用、属性排布与封顶、导出失败 fail-loud 计数。
# ABOUTME: 不访问网络；exporter 一律替换为内存假件。
from __future__ import annotations

from types import SimpleNamespace

import pytest

from sustainability_desk.observability.otlp_export import (
    ENDPOINT_ENV,
    MAX_SPAN_ATTRIBUTES,
    NON_PRODUCTION_SUFFIX,
    SERVICE_NAME,
    SERVICE_ROLE_ENV,
    MirrorSpan,
    OtlpTraceMirror,
    _capped_attributes,
    _resource,
    _span_id_int,
    _trace_id_int,
    reset_trace_mirror_for_tests,
    trace_mirror,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_trace_mirror_for_tests()
    _resource.cache_clear()
    yield
    reset_trace_mirror_for_tests()
    _resource.cache_clear()


def _span(**overrides) -> MirrorSpan:
    kwargs = dict(
        trace_id="run-0001",
        span_id="00000000000000aa",
        parent_span_id=None,
        name="report.generation",
        start_ns=1_000,
        end_ns=2_000,
        ok=True,
        attributes={"sustainability_desk.report_id": "r-1"},
    )
    kwargs.update(overrides)
    return MirrorSpan(**kwargs)


def test_mirror_disabled_without_endpoint(monkeypatch) -> None:
    monkeypatch.delenv(ENDPOINT_ENV, raising=False)
    mirror = trace_mirror()
    assert not mirror.enabled
    mirror.enqueue(_span())  # 空操作，不得抛错
    mirror.flush()
    assert mirror.exported_spans == 0


def test_critical_attributes_survive_cap() -> None:
    """OTLP 后端 超限丢先写入的头部；关键检索键必须排在最后且必然存活。"""
    bulk = {f"sustainability_desk.k{i}": i for i in range(300)}
    critical = {"sustainability_desk.report_id": "r-1", "sustainability_desk.trace": "run-0001"}
    capped = _capped_attributes(bulk, critical)
    assert len(capped) <= MAX_SPAN_ATTRIBUTES
    keys = list(capped)
    assert keys[-2:] == ["sustainability_desk.report_id", "sustainability_desk.trace"]
    assert capped["sustainability_desk.attributes_truncated"] > 0


def test_id_mappings_are_deterministic() -> None:
    assert _trace_id_int("run-0001") == _trace_id_int("run-0001")
    assert _trace_id_int("run-0001") != _trace_id_int("run-0002")
    assert _span_id_int("00000000000000aa") == 0xAA


def test_export_failure_is_counted_and_logged(monkeypatch, caplog) -> None:
    from opentelemetry.sdk.trace.export import SpanExportResult

    monkeypatch.setenv(ENDPOINT_ENV, "https://example.invalid/v1/traces")
    mirror = OtlpTraceMirror()
    assert mirror.enabled
    mirror._exporter = SimpleNamespace(
        export=lambda batch: SpanExportResult.FAILURE
    )
    mirror.enqueue(_span())
    with caplog.at_level("ERROR"):
        mirror.flush()
    assert mirror.failed_batches == 1
    assert mirror.exported_spans == 0
    assert any("回读" in message for message in caplog.messages)


def test_successful_export_converts_tree_faithfully(monkeypatch) -> None:
    from opentelemetry.sdk.trace.export import SpanExportResult

    _force_environment(monkeypatch, "production")
    monkeypatch.setenv(ENDPOINT_ENV, "https://example.invalid/v1/traces")
    mirror = OtlpTraceMirror()
    captured: list = []

    def _export(batch):
        captured.extend(batch)
        return SpanExportResult.SUCCESS

    mirror._exporter = SimpleNamespace(export=_export)
    mirror.enqueue(_span())
    mirror.enqueue(
        _span(span_id="00000000000000bb", parent_span_id="00000000000000aa", ok=False)
    )
    mirror.flush()
    assert mirror.exported_spans == 2
    root, child = captured
    assert root.context.trace_id == child.context.trace_id
    assert child.parent.span_id == root.context.span_id
    assert root.status.is_ok and not child.status.is_ok
    assert root.attributes["sustainability_desk.report_id"] == "r-1"
    assert root.resource.attributes["service.name"] == SERVICE_NAME


def _force_environment(monkeypatch, environment: str) -> None:
    """固定运行环境。_resource 每次都从 runtime_environment 现取，故只需清自身缓存。"""
    from sustainability_desk.runtime_environment import RuntimeEnvironment

    monkeypatch.setattr(
        "sustainability_desk.runtime_environment.runtime_environment",
        lambda: RuntimeEnvironment(environment=environment),
    )
    _resource.cache_clear()


def test_service_role_projects_to_instance_id(monkeypatch) -> None:
    """三个进程共用一个 OTLP 后端 应用；角色只落在实例维度，不改应用身份。"""
    _force_environment(monkeypatch, "production")
    monkeypatch.setenv(SERVICE_ROLE_ENV, "report-workflow-worker")
    resource = _resource()
    assert resource.attributes["service.name"] == SERVICE_NAME
    assert resource.attributes["service.instance.id"] == "report-workflow-worker"

    _resource.cache_clear()
    monkeypatch.delenv(SERVICE_ROLE_ENV, raising=False)
    assert "service.instance.id" not in _resource().attributes


def test_non_production_lands_in_separate_application(monkeypatch) -> None:
    """本机 eval / 实验不得混进生产应用的 token 与耗时统计。"""
    _force_environment(monkeypatch, "production")
    assert _resource().attributes["service.name"] == SERVICE_NAME
    assert _resource().attributes["deployment.environment"] == "production"

    for environment in ("local", "development", "test"):
        _force_environment(monkeypatch, environment)
        attributes = _resource().attributes
        assert attributes["service.name"] == f"{SERVICE_NAME}{NON_PRODUCTION_SUFFIX}"
        assert attributes["deployment.environment"] == environment
