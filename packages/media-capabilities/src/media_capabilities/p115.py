"""Compatibility boundary for installed P115 plugins. Upload has no library effects."""
from pathlib import Path, PurePosixPath

from .models import FileAsset


class P115Gateway:
    @staticmethod
    def service():
        from app.plugins.p115strmhelper.service import servicer
        if not servicer.client:
            raise RuntimeError("115 插件客户端未启动")
        return servicer

    def directory_id(self, path: str, *, create=False) -> int:
        if not path.startswith("/Media/") or ".." in PurePosixPath(path).parts:
            raise ValueError("115 目标目录需要位于 /Media 下")
        from app.plugins.p115strmhelper.core.p115 import get_pid_by_path
        pid = int(get_pid_by_path(self.service().client, path, mkdir=create, update_cache=False,
                                  by_cache=False, request_timeout=30))
        if pid <= 0:
            raise RuntimeError("115 目标目录不可用")
        return pid

    def entries(self, directory: str) -> list[dict]:
        from p115client.tool.fs_files import fs_files_iter
        from p115client.tool.attr import normalize_attr
        pid = self.directory_id(directory)
        result = []
        for batch in fs_files_iter(self.service().client, pid, cooldown=0):
            result.extend(normalize_attr(row) for row in batch.get("data", []))
        return result

    def get_file(self, file_id: int) -> dict:
        from p115client.tool.attr import get_attr
        return get_attr(self.service().client, id=int(file_id))

    def find(self, asset: FileAsset, directory: str, name: str) -> dict | None:
        self.directory_id(directory, create=True)
        matches = [row for row in self.entries(directory) if row.get("name") == name]
        if len(matches) > 1:
            raise ValueError("云端目标存在重复同名文件")
        if not matches:
            return None
        receipt = self._receipt(matches[0], directory)
        self.verify(asset, receipt)
        return receipt

    @staticmethod
    def _receipt(row: dict, directory: str) -> dict:
        return {"id": int(row["id"]), "name": str(row["name"]),
                "path": directory.rstrip("/") + "/" + str(row["name"]),
                "size": int(row.get("size") or 0), "sha1": str(row.get("sha1") or "").upper(),
                "pickcode": str(row.get("pickcode") or row.get("pick_code") or "")}

    def upload(self, asset: FileAsset, directory: str, name: str) -> dict:
        if PurePosixPath(name).name != name:
            raise ValueError("上传文件名不能包含目录")
        self.directory_id(directory, create=True)
        from app.plugins.p115strmhelper.core.p115disk import P115DiskCore
        core = P115DiskCore(client=self.service().client)
        target = core._p115_api.get_item(Path(directory))
        if not target or not callable(getattr(core, "upload", None)):
            raise RuntimeError("安装版 115 上传接口不兼容")
        # Reuse the checksum already computed by the file capability. The
        # installed uploader asks its storage API to hash the same file again.
        original_hash = core._p115_api._calc_sha1
        def checked_hash(path):
            if Path(path) != Path(asset.path) or not asset.sha1:
                return original_hash(path)
            stat = Path(path).stat()
            if (stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino) != (
                    asset.size, asset.mtime_ns, asset.device, asset.inode):
                raise ValueError("上传源文件已变化")
            return asset.sha1
        core._p115_api._calc_sha1 = checked_hash
        # This method is a file upload, not a directory monitor/organizer.
        result = core.upload(target_dir=target, local_path=Path(asset.path), new_name=name)
        if not result:
            raise RuntimeError("115 未确认上传结果")
        observed = self.find(asset, directory, name)
        if observed is None:
            raise RuntimeError("115 上传后尚未查到文件")
        return observed

    def verify(self, asset: FileAsset, receipt: dict) -> None:
        current = self.get_file(receipt["id"])
        if current.get("is_dir") or int(current.get("size") or 0) != asset.size or \
                not asset.sha1 or str(current.get("sha1") or "").upper() != asset.sha1.upper():
            raise ValueError("云端文件大小或 SHA1 无法确认")
        if str(current.get("name")) != receipt["name"]:
            raise ValueError("云端文件名称已变化")

    def create_strm(self, data: list[dict]) -> int:
        from app.plugins.p115strmhelper.api import Api
        from app.plugins.p115strmhelper.schemas.strm_api import StrmApiData, StrmApiPayloadData, StrmApiStatusCode
        payload = [StrmApiData(**row) for row in data]
        result = Api(client=self.service().client).api_strm_sync_creata(StrmApiPayloadData(data=payload))
        if result.code not in {0, StrmApiStatusCode.Success} or not result.data or result.data.success_count < len(payload):
            raise RuntimeError("115 STRM 生成结果未确认")
        return int(result.data.success_count)

    def generate_strm(self, cloud_root: str, local_root: str, root_ids: tuple[int, ...],
                      *, refresh_library=False) -> int:
        from p115client.tool.iterdir import iter_files_with_path_skim
        Path(local_root).mkdir(parents=True, exist_ok=True)
        data = []
        for file_id in root_ids:
            root = self.get_file(file_id)
            items = iter_files_with_path_skim(self.service().client, cid=int(file_id), with_ancestors=True) \
                if root.get("is_dir") else [{**root, "path": cloud_root + "/" + root["name"]}]
            for row in items:
                if Path(row.get("name", "")).suffix.lower() not in {".mkv", ".mp4"}:
                    continue
                data.append({"id": int(row["id"]), "name": row["name"], "sha1": row.get("sha1"),
                             "size": int(row.get("size") or 0), "pick_code": row.get("pickcode"),
                             "pan_path": row.get("path"), "local_path": local_root,
                             "pan_media_path": cloud_root, "media_server_refresh": refresh_library,
                             "scrape_metadata": False})
        return self.create_strm(data) if data else 0
