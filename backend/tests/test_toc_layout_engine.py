# ABOUTME: 可选版式引擎（LibreOffice）的可用性合同：「可用」指可执行文件真能运行，不只是 PATH 上找得到。
# ABOUTME(en): Availability contract of the optional layout engine (LibreOffice) that pre-computes TOC page numbers.
# ABOUTME(en): "Available" means the executable runs, not merely that its name resolves on PATH.
from __future__ import annotations

import stat
from pathlib import Path

import pytest

import sustainability_desk.export.toc as toc
from sustainability_desk.export.toc import page_layout_renderer


def _install_fake_soffice(directory: Path, script_body: str) -> Path:
    executable = directory / "soffice"
    executable.write_text(f"#!/bin/sh\n{script_body}\n", encoding="utf-8")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return executable


@pytest.fixture
def isolated_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH holding only the test's fake executables, so a real LibreOffice never leaks in."""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    return bin_dir


def test_leftover_wrapper_that_cannot_start_counts_as_unavailable(isolated_path: Path) -> None:
    """Uninstalling the app can leave Homebrew's wrapper on PATH, exec-ing a bundle that is gone.

    Treating that wrapper as an installed engine sent every Word export into TOC finalization,
    which then failed with TocFinalizationError instead of taking the reader-resolved path.
    """

    _install_fake_soffice(
        isolated_path, 'exec "/nonexistent/LibreOffice.app/Contents/MacOS/soffice" "$@"'
    )

    assert page_layout_renderer() is None


def test_engine_that_hangs_past_the_probe_timeout_counts_as_unavailable(
    isolated_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(toc, "LAYOUT_ENGINE_PROBE_TIMEOUT_SECONDS", 0.2)
    _install_fake_soffice(isolated_path, "exec /bin/sleep 5")

    assert page_layout_renderer() is None


def test_runnable_engine_is_returned(isolated_path: Path) -> None:
    executable = _install_fake_soffice(isolated_path, 'echo "LibreOffice 26.8.0"')

    assert page_layout_renderer() == str(executable)


def test_no_engine_on_path_is_unavailable(isolated_path: Path) -> None:
    assert page_layout_renderer() is None
