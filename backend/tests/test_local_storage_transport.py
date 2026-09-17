# ABOUTME: 本地对象 transport 的边界测试——路径不得逃出根、禁止覆盖、读取上限与删除幂等。
# ABOUTME: 纯文件系统，不连数据库或 Supabase，故无需本机栈即可运行。
from __future__ import annotations

import pytest

from sustainability_desk.persistence.local_storage_transport import LocalStorageTransport
from sustainability_desk.persistence.private_storage_transport import (
    PrivateStorageTransportError,
)
from sustainability_desk.persistence.settings import PersistenceSettings


def _transport(root) -> LocalStorageTransport:
    return LocalStorageTransport(
        PersistenceSettings(_env_file=None, local_storage_root=str(root))
    )


async def test_create_read_delete_round_trip(tmp_path):
    transport = _transport(tmp_path)
    await transport.create("materials", "acct/ws/obj.pdf", b"payload", media_type="application/pdf")

    assert await transport.read("materials", "acct/ws/obj.pdf") == b"payload"
    await transport.delete("materials", "acct/ws/obj.pdf")
    with pytest.raises(PrivateStorageTransportError):
        await transport.read("materials", "acct/ws/obj.pdf")


async def test_create_refuses_to_overwrite(tmp_path):
    """私有桶禁止 upsert：覆盖会遮盖去重与所有权错误，与 REST transport 同一语义。"""
    transport = _transport(tmp_path)
    await transport.create("materials", "a/b/c.pdf", b"first", media_type="application/pdf")
    with pytest.raises(PrivateStorageTransportError):
        await transport.create("materials", "a/b/c.pdf", b"second", media_type="application/pdf")
    assert await transport.read("materials", "a/b/c.pdf") == b"first"


async def test_read_honours_the_byte_ceiling(tmp_path):
    transport = _transport(tmp_path)
    await transport.create("materials", "a/b/c.pdf", b"0123456789", media_type="application/pdf")
    assert await transport.read("materials", "a/b/c.pdf", max_bytes=4) == b"0123"


async def test_delete_is_idempotent(tmp_path):
    """删除不存在的对象不报错：重复删除在清理路径上是正常的，不该成为失败。"""
    await _transport(tmp_path).delete("materials", "never/written.pdf")


@pytest.mark.parametrize(
    "object_path",
    ["../escape.pdf", "a/../../escape.pdf", "..", "", "   /  "],
)
async def test_path_traversal_is_refused(tmp_path, object_path):
    """对象路径由领域层用内部 UUID 拼出，但边界不依赖调用方的保证。"""
    transport = _transport(tmp_path)
    with pytest.raises(PrivateStorageTransportError):
        await transport.create("materials", object_path, b"x", media_type="application/pdf")


async def test_bucket_name_cannot_carry_a_path(tmp_path):
    transport = _transport(tmp_path)
    with pytest.raises(PrivateStorageTransportError):
        await transport.create("../materials", "a.pdf", b"x", media_type="application/pdf")


async def test_symlinked_object_path_cannot_escape_root(tmp_path):
    """解析符号链接后再比对：字面前缀检查挡不住指向外部的链接。"""
    root = tmp_path / "root"
    (root / "materials").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "materials" / "link").symlink_to(outside, target_is_directory=True)

    transport = _transport(root)
    with pytest.raises(PrivateStorageTransportError):
        await transport.create("materials", "link/escaped.pdf", b"x", media_type="application/pdf")


async def test_relative_root_is_refused():
    """相对路径的含义取决于进程 cwd，而后端、worker 与测试的 cwd 并不相同。"""
    with pytest.raises(PrivateStorageTransportError):
        LocalStorageTransport(
            PersistenceSettings(_env_file=None, local_storage_root="out/object-storage")
        )
