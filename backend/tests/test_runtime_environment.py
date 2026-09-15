# ABOUTME: 运行环境边界测试：本机栈只能 loopback，生产必须显式声明项目且不得 loopback。
# ABOUTME: 项目名不再绑定任何云实例 id；本文件只覆盖仍然存在的两条硬边界。
import pytest

from sustainability_desk.runtime_environment import RuntimeEnvironment, assert_environment_boundary


def test_unconfigured_local_runtime_does_not_require_project() -> None:
    runtime = RuntimeEnvironment(environment="local", supabase_project="")
    assert_environment_boundary(runtime, persistence_configured=False)


def test_configured_local_runtime_requires_local_project_and_loopback_supabase() -> None:
    runtime = RuntimeEnvironment(environment="local", supabase_project="sustainability-desk-local")
    assert_environment_boundary(
        runtime,
        persistence_configured=True,
        supabase_url="http://127.0.0.1:54321",
    )

    with pytest.raises(RuntimeError, match="loopback"):
        assert_environment_boundary(
            runtime,
            persistence_configured=True,
            supabase_url="https://auth.example.test",
        )


def test_local_runtime_rejects_other_project_names() -> None:
    runtime = RuntimeEnvironment(environment="local", supabase_project="something-else")
    with pytest.raises(RuntimeError, match="sustainability-desk-local"):
        assert_environment_boundary(
            runtime,
            persistence_configured=True,
            supabase_url="http://127.0.0.1:54321",
        )


def test_production_requires_declared_project_and_non_loopback_supabase() -> None:
    with pytest.raises(RuntimeError, match="SUSTAINABILITY_DESK_SUPABASE_PROJECT"):
        assert_environment_boundary(
            RuntimeEnvironment(environment="production", supabase_project=""),
            persistence_configured=True,
            supabase_url="https://db.example.test",
        )
    with pytest.raises(RuntimeError, match="loopback"):
        assert_environment_boundary(
            RuntimeEnvironment(environment="production", supabase_project="my-prod"),
            persistence_configured=True,
            supabase_url="http://127.0.0.1:54321",
        )
    assert_environment_boundary(
        RuntimeEnvironment(environment="production", supabase_project="my-prod"),
        persistence_configured=True,
        supabase_url="https://db.example.test",
    )


def test_development_runtime_accepts_any_declared_project() -> None:
    assert_environment_boundary(
        RuntimeEnvironment(environment="development", supabase_project="shared-dev"),
        persistence_configured=True,
        supabase_url="https://db.example.test",
    )
