"""Small compatibility boundary around the installed P115StrmHelper services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .selection import inspect_files
from .media_types import normalize_media_type


@dataclass(frozen=True)
class ShareEvidence:
    files: tuple[str, ...]
    video_bytes: int
    total_bytes: int
    root_ids: tuple[int, ...]
    root_names: tuple[str, ...]


class P115TaskAdapter:
    def __init__(self, movie_path: str = '/Media/Movie', tv_path: str = '/Media/TV_Show',
                 local_strm_root: str = '/Media/115_strm'):
        self.movie_path = movie_path.rstrip('/')
        self.tv_path = tv_path.rstrip('/')
        self.local_strm_root = local_strm_root.rstrip('/')
        for path in (self.movie_path, self.tv_path):
            if not path.startswith('/Media/') or '..' in Path(path).parts:
                raise ValueError('115 目标目录必须是 /Media 下的固定目录')
        if self.movie_path == self.tv_path:
            raise ValueError('电影和剧集不能共用 115 目标目录')

    @staticmethod
    def _service():
        from app.plugins.p115strmhelper.service import servicer
        if not servicer.client or not servicer.offlinehelper:
            raise RuntimeError('115 插件客户端或离线服务未启动')
        return servicer

    def target_path(self, media_type: str) -> str:
        return self.movie_path if normalize_media_type(media_type) == 'movie' else self.tv_path

    def _target_id(self, media_type: str) -> int:
        from app.plugins.p115strmhelper.core.p115 import get_pid_by_path
        service = self._service()
        path = self.target_path(media_type)
        pid = get_pid_by_path(service.client, path, mkdir=False, update_cache=False,
                              by_cache=False, request_timeout=20)
        if int(pid) <= 0:
            raise RuntimeError('115 目标媒体目录不存在')
        return int(pid)

    def validate_target(self, media_type: str) -> None:
        self._target_id(media_type)

    def submit_magnet(self, magnet: str, media_type: str) -> bool:
        self._target_id(media_type)
        service = self._service()
        okay, count = service.offlinehelper.add_urls_to_path(
            [magnet], self.target_path(media_type))
        return bool(okay and count >= 1)

    def offline_task(self, info_hash: str) -> dict | None:
        for item in self._service().offlinehelper.get_tasks():
            if str(item.get('info_hash') or '').casefold() == info_hash.casefold():
                return item
        return None

    @staticmethod
    def _share_payload(url: str) -> tuple[str, str]:
        from p115client.util import share_extract_payload
        payload = share_extract_payload(url)
        code, receive = payload.get('share_code'), payload.get('receive_code') or ''
        if not code:
            raise ValueError('115 分享链接无效')
        return str(code), str(receive)

    def preview_share(self, url: str, title: str,
                      expected_episodes: set[int] | None = None) -> ShareEvidence:
        from p115client.tool.iterdir import share_iterdir
        from pathlib import PurePosixPath
        client = self._service().client
        code, receive = self._share_payload(url)
        root = list(share_iterdir(client, code, receive, cid=0, max_workers=0))
        if not root:
            raise ValueError('115 分享为空或提取码无效')
        files: list[tuple[str, int]] = []

        def walk(items: list[dict], prefix: str = '', depth: int = 0):
            if depth > 5 or len(files) > 300:
                raise ValueError('115 分享目录超过预检限制')
            for item in items:
                name = str(item.get('name') or '')
                path = f'{prefix}/{name}'.lstrip('/')
                if item.get('is_dir'):
                    children = list(share_iterdir(client, code, receive,
                                                  cid=int(item['id']), max_workers=0))
                    walk(children, path, depth + 1)
                else:
                    files.append((path, int(item.get('size') or 0)))

        walk(root)
        names = tuple(name for name, _ in files)
        valid, reason = inspect_files(title, list(names), expected_episodes)
        if not valid:
            raise ValueError(reason)
        video_bytes = sum(size for name, size in files if PurePosixPath(name).suffix.casefold()
                          in ('.mkv', '.mp4'))
        if not video_bytes:
            raise ValueError('无法核实 115 分享的视频大小')
        return ShareEvidence(names, video_bytes, sum(size for _, size in files),
                             tuple(int(item['id']) for item in root),
                             tuple(str(item.get('name') or '') for item in root))

    def submit_share(self, url: str, media_type: str,
                     evidence: ShareEvidence) -> bool:
        """Reuse P115 client; avoid the GET endpoint that logs extraction codes."""
        code, receive = self._share_payload(url)
        parent_id = self._target_id(media_type)
        from app.plugins.p115strmhelper.core.config import configer
        payload = {'share_code': code, 'receive_code': receive,
                   'file_id': ','.join(str(value) for value in evidence.root_ids),
                   'cid': parent_id, 'is_check': 0}
        response = self._service().client.share_receive(
            payload, **configer.get_ios_ua_app(app=False))
        return bool(response.get('state'))

    def cloud_items(self, media_type: str, names: tuple[str, ...]) -> list[dict]:
        """Find copied root entries by name without moving other cloud files."""
        from p115client.tool.fs_files import fs_files_iter
        from p115client.tool.attr import normalize_attr
        client = self._service().client
        wanted = set(names)
        result = []
        for batch in fs_files_iter(client, self._target_id(media_type), cooldown=0):
            for raw in batch.get('data', []):
                item = normalize_attr(raw)
                if item.get('name') in wanted:
                    result.append(item)
        return result

    def ensure_strm(self, media_type: str, root_ids: tuple[int, ...]) -> int:
        """Generate STRM only for files belonging to this task, under the matching local directory."""
        media_type = normalize_media_type(media_type)
        from p115client.tool.attr import get_attr
        from p115client.tool.iterdir import iter_files_with_path_skim
        from app.plugins.p115strmhelper.api import Api
        from app.plugins.p115strmhelper.schemas.strm_api import StrmApiData, StrmApiPayloadData

        service = self._service()
        cloud_root = self.target_path(media_type)
        local_root = Path(self.local_strm_root) / ('Movie' if media_type == 'movie' else 'TV_Show')
        local_root.mkdir(parents=True, exist_ok=True)
        data = []
        for root_id in root_ids:
            root = get_attr(service.client, id=int(root_id))
            if root.get('is_dir'):
                items = iter_files_with_path_skim(service.client, cid=int(root_id),
                                                  with_ancestors=True)
            else:
                items = [{**root, 'path': f"{cloud_root}/{root.get('name', '')}"}]
            for item in items:
                name = str(item.get('name') or '')
                if Path(name).suffix.casefold() not in ('.mkv', '.mp4'):
                    continue
                data.append(StrmApiData(
                    id=int(item['id']), name=name, sha1=item.get('sha1'),
                    size=int(item.get('size') or 0), pick_code=item.get('pickcode'),
                    pan_path=item.get('path'), local_path=str(local_root),
                    pan_media_path=cloud_root, media_server_refresh=True,
                    scrape_metadata=False,
                ))
        if not data:
            return 0
        response = Api(client=service.client).api_strm_sync_creata(StrmApiPayloadData(data=data))
        if response.code != 0 or not response.data or response.data.success_count < len(data):
            raise RuntimeError('115 STRM 生成失败')
        return int(response.data.success_count)
