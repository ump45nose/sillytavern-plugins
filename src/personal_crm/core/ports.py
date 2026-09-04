"""核心模块依赖的最小端口定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class RepositoryPort(Protocol):
    """描述核心服务所需的仓储能力，便于未来替换 SQLite。"""

    def upsert_person(self, person_id: str | None = None, **values: Any) -> tuple[Any, dict]:
        """创建或更新人物。"""

    def get_person(self, person_id: str) -> Any | None:
        """读取人物。"""

    def search_people(self, query: str = "", limit: int = 50) -> list[Any]:
        """搜索人物。"""

    def record_interaction(self, **values: Any) -> tuple[Any, bool, int]:
        """记录互动并返回实体、是否新增和完成提醒数。"""

    def record_fact(self, **values: Any) -> tuple[Any, bool]:
        """记录幂等事实。"""

    def update_fact_status(self, fact_id: str, status: str) -> tuple[Any, dict]:
        """更新事实生命周期。"""

    def create_reminder(self, **values: Any) -> Any:
        """创建提醒。"""

    def update_reminder(self, reminder_id: str, **values: Any) -> tuple[Any, dict]:
        """更新提醒。"""


class ReminderRepositoryPort(Protocol):
    """Reminder 策略所需的公开仓储查询。"""

    def list_yearly_important_reminders(self) -> list[Any]:
        """列出年度重要日期模板。"""

    def find_reminder_cycle(
        self, person_id: str, reminder_type: str, due_at: datetime
    ) -> Any | None:
        """查询指定周期是否已经存在。"""

    def list_open_important_reminders(
        self, start: datetime, end: datetime, limit: int
    ) -> list[Any]:
        """列出窗口内的重要提醒。"""

    def list_active_cadence_people(self) -> list[Any]:
        """列出启用 cadence 的活跃人物。"""

    def has_open_follow_up(self, person_id: str) -> bool:
        """判断是否已有未完成的跟进提醒。"""

    def create_reminder(self, **values: Any) -> Any:
        """创建新提醒。"""


class MetricsRepositoryPort(Protocol):
    """周绩效计算所需的公开仓储查询。"""

    def list_reminders_due_between(
        self, start: datetime, end: datetime, *, excluded_statuses: set[str] | None = None
    ) -> list[Any]:
        """列出指定时间窗内的提醒。"""
