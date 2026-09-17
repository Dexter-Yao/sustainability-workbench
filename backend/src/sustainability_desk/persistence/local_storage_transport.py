# ABOUTME: 私有对象的本地文件系统 transport；与 PrivateStorageTransport 同形，供无 Storage 服务的安装使用。
# ABOUTME: 对象路径由领域层用内部 UUID 生成，此处仍逐段校验，绝不让路径逃出根目录。
# ABOUTME(en): Filesystem transport for private objects, shaped like PrivateStorageTransport.
# ABOUTME(en): Paths come from the domain layer as internal UUIDs; every segment is still checked to stay in root.
from __future__ import annotations

from pathlib import Path

from sustainability_desk.persistence.private_storage_transport import (
    PrivateStorageTransportError,
)
from sustainability_desk.persistence.settings import PersistenceSettings


class LocalStorageTransport:
    """把私有对象存在本机磁盘上，接口与 Supabase Storage transport 一致。

    存在的理由是体积：storage-api 镜像约 818 MB，而本产品对它的全部用法只有
    「写一个对象、读回来、删掉」三件事——对自用安装来说，这三件事文件系统本来就做。
    报告交付物（Word）本就落本地盘（`report_artifact_root`），资料对象走同一形态
    只是把最后一处外部依赖收回来。

    两种 transport 的方法签名刻意逐字对齐（create / read / delete），调用方
    `MaterialStorageClient` 因此不需要知道自己在跟谁说话。
    """

    def __init__(self, settings: PersistenceSettings) -> None:
        root = settings.local_storage_root
        if not root:
            raise PrivateStorageTransportError("本地对象存储根目录未配置")
        path = Path(root)
        if not path.is_absolute():
            # 与 SUSTAINABILITY_DESK_REPORT_ARTIFACT_ROOT 同一纪律：相对路径的含义
            # 取决于进程 cwd，而后端、worker 与测试的 cwd 并不相同——那会让同一份
            # 配置在三处指向三个目录，且只在读不到对象时才暴露。
            raise PrivateStorageTransportError("本地对象存储根目录必须是绝对路径")
        self._root = path

    def _object_file(self, bucket: str, object_path: str) -> Path:
        """解析对象在磁盘上的位置，并确保它落在根目录之内。

        对象路径由领域层用内部 UUID 拼出（见 `MaterialStorageClient.object_path`），
        正常情况下不含 `..`；这里仍然校验，因为「调用方保证」不是边界该依赖的东西。
        """

        if not bucket or "/" in bucket or bucket in {".", ".."}:
            raise PrivateStorageTransportError("非法的 bucket 名")
        # 先剔空段再判定：空白段（如 "a/  /b"）会在磁盘上造出名为空格的目录，
        # 那是个既不可见又无法由领域层复现的路径。
        segments = [segment for segment in object_path.split("/") if segment.strip()]
        if not segments or any(segment.strip() in {".", ".."} for segment in segments):
            raise PrivateStorageTransportError("非法的对象路径")
        if any(segment != segment.strip() for segment in segments):
            raise PrivateStorageTransportError("对象路径段不得含首尾空白")
        resolved = (self._root / bucket).joinpath(*segments)
        root = self._root.resolve()
        # 解析符号链接后再比对：resolve() 之前的字面比较挡不住指向外部的链接。
        if not resolved.resolve().is_relative_to(root):
            raise PrivateStorageTransportError("对象路径越出存储根目录")
        return resolved

    async def create(
        self, bucket: str, object_path: str, data: bytes, *, media_type: str
    ) -> None:
        """创建不可覆盖对象；已存在即失败，与私有桶禁止 upsert 的语义一致。

        media_type 不落盘：对象类型由数据库记录，文件系统没有对应位置存它，
        而凭扩展名回推类型正是本产品在别处刻意避免的做法。
        """

        del media_type
        target = self._object_file(bucket, object_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # "xb" 让「已存在」成为原子失败，而不是先查后写留出竞态窗口。
            with open(target, "xb") as handle:
                handle.write(data)
        except FileExistsError as error:
            raise PrivateStorageTransportError("对象已存在", status_code=409) from error
        except OSError as error:
            raise PrivateStorageTransportError(f"写入对象失败：{type(error).__name__}") from error

    async def read(
        self, bucket: str, object_path: str, *, max_bytes: int | None = None
    ) -> bytes:
        """读取对象；给定上限时只读到上限为止，不把整份内容装进内存。"""

        if max_bytes is not None and max_bytes < 1:
            raise ValueError("Storage 读取上限必须为正数")
        target = self._object_file(bucket, object_path)
        try:
            with open(target, "rb") as handle:
                return handle.read() if max_bytes is None else handle.read(max_bytes)
        except FileNotFoundError as error:
            raise PrivateStorageTransportError("对象不存在", status_code=404) from error
        except OSError as error:
            raise PrivateStorageTransportError(f"读取对象失败：{type(error).__name__}") from error

    async def delete(self, bucket: str, object_path: str) -> None:
        """删除对象；不存在即成功，与重复删除应当幂等的既有语义一致。"""

        target = self._object_file(bucket, object_path)
        try:
            target.unlink(missing_ok=True)
        except OSError as error:
            raise PrivateStorageTransportError(f"删除对象失败：{type(error).__name__}") from error
