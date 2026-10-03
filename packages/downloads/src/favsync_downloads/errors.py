"""Stable failure types containing only redacted, machine-readable messages."""


class DownloadError(RuntimeError):
    """An input, item, filesystem, or transport failure."""


class DownloadTimeout(DownloadError):
    """The socket timeout or absolute wall-clock deadline was exceeded."""


class DownloadServiceError(DownloadError):
    """A blocked or unavailable upstream transport."""


class DownloadRateLimitError(DownloadServiceError):
    """An explicit upstream rate limit."""


class DownloadSizeLimitError(DownloadError):
    """The configured byte budget was exceeded."""


def classify_ytdlp_error(stderr: str) -> DownloadError:
    text = stderr.casefold()
    if any(word in text for word in (
        "video unavailable", "private video", "removed", "not available in your country",
        "copyright", "requested format is not available",
    )):
        return DownloadError("item_unavailable")
    if "429" in text:
        return DownloadRateLimitError("transport_rate_limited")
    if any(word in text for word in (
        "sign in", "confirm you", "403", "timed out", "connection", "network",
        "502", "503", "unable to download webpage",
    )):
        return DownloadServiceError("transport_blocked_or_unavailable")
    return DownloadError("unclassified_download_failure")
