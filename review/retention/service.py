"""以可恢复压缩归档执行 raw/derived 保留策略。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import shutil
import tarfile

from review.state import StateRepository


class RetentionService:
    """Raw 到期转入压缩归档，derived 仅在年度总结确认后处理。"""

    def __init__(self, state: StateRepository, data_root: str | Path, policy: dict) -> None:
        """绑定状态库、数据根和版本化策略。"""

        self.state = state
        self.data_root = Path(data_root)
        self.policy = policy
        self.raw_root = self.data_root / "raw" / "skysight"
        self.derived_root = self.data_root / "derived" / "skysight"
        self.quarantine = self.data_root / ".retention-quarantine"

    def plan(self, now: datetime) -> dict:
        """列出将归档的严格日期目录，不跟随任意路径。"""

        raw_before = now.date() - timedelta(days=int(self.policy["retention"]["skysight_raw_days"]))
        raw = [path for path in self._dated_directories(self.raw_root) if self._date(path.name) < raw_before]
        annual_years = self._finalized_annual_years()
        derived_dirs = [
            path for path in self._dated_directories(self.derived_root)
            if self._date(path.name).year in annual_years
        ]
        summary_files = []
        summary_root = self.derived_root / "source-summaries"
        if summary_root.is_dir():
            for path in sorted(summary_root.glob("*-memory-summary.md")):
                parsed = self._date(path.name[:10])
                if parsed and parsed.year in annual_years:
                    summary_files.append(path)
        archive_before = now - timedelta(days=int(self.policy["retention"]["quarantine_days"]))
        expired_archives = []
        if self.quarantine.is_dir():
            for path in sorted(self.quarantine.glob("*/*.tar.gz")):
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo)
                if path.is_file() and modified < archive_before:
                    expired_archives.append(path)
        return {
            "raw": [str(path) for path in raw],
            "derived_directories": [str(path) for path in derived_dirs],
            "derived_summaries": [str(path) for path in summary_files],
            "expired_archives": [str(path) for path in expired_archives],
        }

    def apply(self, now: datetime, dry_run: bool = False) -> dict:
        """把到期材料压缩后删除原路径；压缩包保留以支持人工恢复。"""

        plan = self.plan(now)
        if dry_run:
            return {"status": "dry-run", **plan}
        archived: list[str] = []
        for value in plan["raw"] + plan["derived_directories"]:
            path = Path(value)
            category = "raw" if self.raw_root in path.parents else "derived"
            archived.append(str(self._archive_directory(path, category)))
        summaries = [Path(value) for value in plan["derived_summaries"]]
        if summaries:
            by_year: dict[int, list[Path]] = {}
            for path in summaries:
                by_year.setdefault(self._date(path.name[:10]).year, []).append(path)
            for year, paths in by_year.items():
                archive = self.quarantine / "derived" / f"source-summaries-{year}.tar.gz"
                archive.parent.mkdir(parents=True, exist_ok=True)
                with tarfile.open(archive, "w:gz") as stream:
                    for path in paths:
                        stream.add(path, arcname=path.name, recursive=False)
                if not archive.is_file() or archive.stat().st_size == 0:
                    raise RuntimeError("derived 摘要归档校验失败")
                for path in paths:
                    path.unlink()
                archived.append(str(archive))
        deleted_archives: list[str] = []
        for value in plan["expired_archives"]:
            path = Path(value)
            if self.quarantine not in path.parents or path.suffixes[-2:] != [".tar", ".gz"]:
                raise ValueError("拒绝删除非隔离区归档")
            path.unlink()
            deleted_archives.append(str(path))
        return {"status": "applied", "archived": archived, "deleted_archives": deleted_archives}

    def _archive_directory(self, path: Path, category: str) -> Path:
        """创建非空 tar.gz 后移除原目录；目标路径限制在 quarantine 下。"""

        if path.parent not in {self.raw_root, self.derived_root}:
            raise ValueError("拒绝归档非受管目录")
        target = self.quarantine / category / f"{path.name}.tar.gz"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "w:gz") as stream:
            stream.add(path, arcname=path.name)
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"归档校验失败：{path.name}")
        shutil.rmtree(path)
        return target

    def _finalized_annual_years(self) -> set[int]:
        """只有已写入 Memos 的年度会话才能释放该年 derived。"""

        with self.state.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM review_sessions WHERE kind='annual' AND status='finalized' AND memo_name LIKE 'memos/%'"
            ).fetchall()
        return {int(str(row["id"]).split(":", 1)[1]) for row in rows}

    @classmethod
    def _dated_directories(cls, root: Path) -> list[Path]:
        """仅返回名称为 YYYY-MM-DD 的直属目录。"""

        if not root.is_dir():
            return []
        return [path for path in sorted(root.iterdir()) if path.is_dir() and cls._date(path.name)]

    @staticmethod
    def _date(value: str) -> date | None:
        """严格解析日期目录或文件名前缀。"""

        try:
            parsed = date.fromisoformat(value)
            return parsed if parsed.isoformat() == value else None
        except ValueError:
            return None
