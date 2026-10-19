"""Pinned gallery-dl DataJob boundary shared by EH and Pixiv."""
import json
import sys
import tempfile

from .common import SyncError


def read_events(config, url, timeout, *, runner, warnings_are_errors,
                module="gallery_dl"):
    """Read a complete DataJob without mistaking exit zero for completeness.

    Platform configuration and work visibility stay with the calling adapter.
    Warning policy belongs to each platform; terminal -1 events always stop a
    complete commit, regardless of that policy.
    """
    with tempfile.TemporaryFile() as output:
        runner([sys.executable, "-m", module, "--config-ignore", "-c", config, "-j", url],
               timeout, output, warnings_are_errors=warnings_are_errors)
        output.seek(0)
        try:
            events = json.load(output)
        except ValueError:
            raise SyncError("invalid_export") from None
    if not isinstance(events, list):
        raise SyncError("invalid_export")
    errors = [event[-1] for event in events if isinstance(event, list) and event and event[0] == -1]
    if errors:
        names = {str(error.get("error", "")) for error in errors if isinstance(error, dict)}
        if names & {"AuthenticationError", "AuthorizationError"}:
            raise SyncError("auth_required")
        raise SyncError("scan_incomplete")
    return events
