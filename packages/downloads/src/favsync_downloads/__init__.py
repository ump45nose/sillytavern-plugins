"""Reusable synchronous download transports; no application runtime or import side effects."""

from .errors import (
    DownloadError,
    DownloadRateLimitError,
    DownloadServiceError,
    DownloadSizeLimitError,
    DownloadTimeout,
)
from .transports import download_http, download_ytdlp

__all__ = [
    "DownloadError", "DownloadTimeout", "DownloadServiceError",
    "DownloadRateLimitError", "DownloadSizeLimitError", "download_http", "download_ytdlp",
]
