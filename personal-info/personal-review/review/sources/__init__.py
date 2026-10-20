"""外部事实来源适配器。"""

from .base import SourceAdapter, SourceResult
from .email import EmailBriefSource
from .google import GoogleCalendarBriefSource, GoogleTasksBriefSource
from .health import HealthSource
from .finance import FinanceSource
from .git_activity import GitActivitySource
from .crm_activity import CrmActivitySource
from .memos import MemosSource
from .skysight import SkysightSummarySource
from .tasks import TaskCompletionSource

__all__ = [
    "EmailBriefSource",
    "GoogleCalendarBriefSource",
    "GoogleTasksBriefSource",
    "CrmActivitySource",
    "HealthSource",
    "MemosSource",
    "SkysightSummarySource",
    "SourceAdapter",
    "SourceResult",
    "TaskCompletionSource",
]
