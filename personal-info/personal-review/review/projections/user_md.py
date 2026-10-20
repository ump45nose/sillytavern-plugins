"""只更新 USER.md 中受管理的当前状态区块。"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re


BEGIN_PATTERN = re.compile(r"<!-- PERSONAL_REVIEW:BEGIN sha256=([0-9a-f]{64}) -->")
END_MARKER = "<!-- PERSONAL_REVIEW:END -->"


class UserMdProjection:
    """以区块哈希防止覆盖人工或 Profile 个性内容。"""

    def __init__(self, path: str | Path) -> None:
        """记录目标 USER.md。"""

        self.path = Path(path)

    @staticmethod
    def _hash(content: str) -> str:
        """计算规范化区块内容哈希。"""

        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    def render(self, active_state: str) -> str:
        """生成带完整性哈希的受管理区块。"""

        content = active_state.strip()
        return f"<!-- PERSONAL_REVIEW:BEGIN sha256={self._hash(content)} -->\n{content}\n{END_MARKER}"

    def apply(self, active_state: str, dry_run: bool = False) -> str:
        """校验旧区块哈希后替换；冲突时拒绝自动覆盖。"""

        original = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        match = BEGIN_PATTERN.search(original)
        replacement = self.render(active_state)
        if match:
            end = original.find(END_MARKER, match.end())
            if end < 0:
                raise ValueError("USER.md 受管理区块缺少结束标记")
            old_content = original[match.end():end].strip()
            if self._hash(old_content) != match.group(1):
                raise ValueError("USER.md 受管理区块已被人工修改，停止覆盖")
            updated = original[:match.start()] + replacement + original[end + len(END_MARKER):]
        else:
            separator = "\n\n" if original.strip() else ""
            updated = original.rstrip() + separator + replacement + "\n"
        if not dry_run:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(updated, encoding="utf-8")
            temporary.replace(self.path)
        return updated

