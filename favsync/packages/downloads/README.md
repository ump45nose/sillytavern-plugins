# favsync-downloads

Small, independently installable synchronous download transports. No Favsync runtime,
Theme configuration, database, model objects, persistent service, or credential discovery
is involved. Importing the package performs no I/O or process startup.

Requires Python 3.11+. Install this directory or its wheel:

```sh
python -m pip install ./packages/downloads
# Only for callers that need the yt-dlp transport:
python -m pip install './packages/downloads[ytdlp]'
```

```python
from pathlib import Path
from favsync_downloads import download_http, download_ytdlp

artifact = download_http(
    "https://example.org/audio.mp3",
    workdir=Path("/existing/private/workdir"),
    timeout_seconds=15,
    hard_timeout_seconds=180,
    max_bytes=64 * 1024 * 1024,
)
artifact = download_ytdlp(
    "https://example.org/the-selected-source",
    workdir=Path("/existing/private/workdir"),
    cookie_file=None,  # Only an explicitly supplied file is read.
    socket_timeout_seconds=15,
    hard_timeout_seconds=180,
    max_bytes=64 * 1024 * 1024,
)
```

## Contract

- A call returns one nonempty, regular file inside a fresh private subdirectory of
  the existing `workdir`. Always use the returned path instead of globbing the root.
  Successful calls leave that directory and file for the caller to use and remove.
- Workdir and its existing path components cannot be symlinks. Existing workdir
  contents are never selected, overwritten, or removed. Download artifact symlinks,
  hard links, unexpected paths, ambiguous outputs, and unfinished files are rejected.
- HTTP(S) follows redirects, streams in 256 KiB chunks, uses a conservative URL
  extension (otherwise `.media`), rejects oversized advertised lengths, and checks
  the actual decoded bytes even when lengths are missing or compressed. It does not
  validate the media container or duration; that remains the caller's responsibility.
- An isolated subprocess gives both transports a wall-clock deadline, including
  stalled HTTP headers/reads, extraction, subprocess startup and artifact validation.
  The socket timeout is separate; yt-dlp's is capped at 15 seconds. On POSIX, the
  complete subprocess group is killed after timeout/error or completion so a child
  cannot remain behind. On non-POSIX platforms only the immediate child is killed;
  use POSIX when descendant-process cleanup is required.
- yt-dlp uses `bestaudio/best`, `--no-playlist`, `source.%(ext)s`, ignored local
  configuration, disabled cache, and one retry. `--max-filesize` and in-flight disk
  checks complement a strict final byte check. Aggregate in-flight disk and log
  checks are polling-based and can overshoot briefly between checks; this is not an
  operating-system quota or an adversarial-process sandbox.
- An explicitly supplied cookie file is copied to a private temporary directory
  with mode 0600, used by yt-dlp and removed on every exit. The original is unchanged.
  Missing/nonregular files and files over 4 MiB fail closed. No browser credential
  store is read and no cookies/config are inferred from a provider or user profile.
- Error/cancellation removes the call's entire staging directory, including parts.
  Cancellation includes `KeyboardInterrupt`; another invocation's output is untouched.
  The caller owns the workdir and must prevent untrusted concurrent mutation.

## Errors

`DownloadError` is the common base. Messages are redacted stable codes, never raw
URLs, cookie paths, headers or upstream stderr. Subclasses are `DownloadTimeout`,
`DownloadServiceError`, `DownloadRateLimitError` (a service error), and
`DownloadSizeLimitError`. An unavailable yt-dlp extra raises a service error;
private/removed/unavailable items remain item errors and should not disable an
entire provider. Some yt-dlp sources require native ffmpeg or Deno executables;
this package does not install those tools. Install version is `0.1.0`.

## Local verification

```sh
python -m pip install -e './packages/downloads[test]'
python -m pytest packages/downloads/tests
python -m build packages/downloads
```

Tests use local HTTP fixtures and a stub yt-dlp module, with no real service
accounts, production credentials, or live-provider calls. Tests cover deadlines,
resource limits, safe artifacts, redaction, cookie lifecycle and process cleanup.
