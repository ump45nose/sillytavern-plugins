"""Private subprocess entry point; stdin carries request data, stderr only safe codes."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

STREAM_CHUNK_BYTES = 256 * 1024


def main() -> int:
    try:
        request = json.load(sys.stdin)
        target = Path(request["target"])
        max_bytes = request["max_bytes"]
        with httpx.stream(
            "GET", request["url"], timeout=request["timeout_seconds"],
            follow_redirects=True, headers={"User-Agent": "favsync-downloads/0.1"},
        ) as response:
            if response.status_code == 429:
                return fail("transport_rate_limited")
            if response.status_code in (401, 403) or response.status_code >= 500:
                return fail("transport_blocked_or_unavailable")
            response.raise_for_status()
            length = response.headers.get("content-length")
            if length is not None and int(length) > max_bytes:
                return fail("download_size_limit_exceeded")
            total = 0
            # Never follow or overwrite an existing destination.
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                for chunk in response.iter_bytes(STREAM_CHUNK_BYTES):
                    total += len(chunk)
                    if total > max_bytes:
                        return fail("download_size_limit_exceeded")
                    handle.write(chunk)
            if not total:
                return fail("empty_download")
        return 0
    except httpx.TimeoutException:
        return fail("socket_timeout")
    except httpx.HTTPStatusError:
        return fail("item_unavailable")
    except httpx.RequestError:
        return fail("transport_blocked_or_unavailable")
    except Exception:
        # Never print raw exceptions, URLs, headers, or local credential paths.
        return fail("download_failed")


def fail(code: str) -> int:
    sys.stderr.write(code)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
