# Emby Theme Worker

Python 3.12 worker that discovers Emby movie and series theme songs, produces a normalized `theme.mp3`, and verifies the audio actually served by Emby. Version 0.3 adds a MoviePilot v2 Vue management plugin. Heavy processing stays in the independent Worker container; a private Unix socket connects the plugin, with no new TCP port.

**0.3 is staged for audition.** Automatic scheduling and migration default to disabled until sample review and a single real application pass. A healthy container or a high candidate score does not establish theme quality.

## Features

- Enumerates `Movie` and `Series` items through the Emby API with pagination and `HasThemeSong=false`.
- Restricts all work to a configured media root and checks both Emby `ThemeSongs` and the filesystem before writing.
- Uses exact provider identifiers first, then scores concurrent fuzzy candidates on title, year/type, theme intent, duration, and cross-source consensus.
- Extracts movie credits/tail audio, or representative series intros; unmarked series scan bounded opening/ending regions of three regular episodes.
- Downloaded tracks and manual uploads keep their full duration by default, with loudness normalization, short fades and 192 kbps MP3 encoding. Optional per-track cropping appears only after clicking its control. Local video fallback uses CPU-only inaSpeechSegmenter to select roughly 45-second music-dominant windows, with explicit low-confidence signal analysis when the model fails.
- Protects unrelated themes and user locks; managed fallback upgrades use hash checks, backups, atomic replacement and conditional rollback.
- Stores resumable state, backoff, provider circuits, candidate evidence, and output hashes in SQLite.
- Provides media browsing, candidate audition, uploads, waveform trimming, completion locks, jobs and feedback through MoviePilot; CLI diagnostics remain available.

## Safety model

- Only paths contained by `allowed_path` are eligible. The production container mounts `/Media` but not `/Adult`.
- The worker runs as `1000:1001` with a read-only root filesystem, all Linux capabilities dropped, and `no-new-privileges` enabled.
- STRM files must contain exactly one absolute HTTP(S) URL.
- URLs, query strings, API keys, cookies, and authorization values are redacted from logs.
- SQLite stores hashes of source URLs, never source URLs or credentials.
- The dedicated Emby API key and optional provider cookies are read from files below `/run/secrets`.
- Completion requires the matching theme resource path and a hash match against audio served by Emby. Execution completion and the user's completion lock are separate states. Automatic jobs and Studio applications use the same theme-specific publisher for guarded ownership checks, persistent replacement intent, verification and conditional rollback.

## Provider pipeline

Exact resolvers are collected in priority order and transport failures continue to the next candidate:

| Media type | Exact order |
| --- | --- |
| Anime | AnimeThemes strict title/year OP1 -> ThemerrDB TMDb -> Plex TVDb theme -> TelevisionTunes |
| Series | ThemerrDB TMDb -> Plex TVDb theme -> TelevisionTunes |
| Movie | ThemerrDB TMDb |

If the exact layer misses, the worker queries Archive.org, YouTube, Bilibili, NetEase, and QQ Music concurrently. Archive.org candidates require explicit Creative Commons or public-domain metadata. Anonymous Tunefind scraping is deliberately disabled; its official API adapter remains gated on issued credentials and documentation.

Resolver health and transport health are separate. A valid ThemerrDB mapping whose YouTube download fails opens the YouTube transport circuit, not the ThemerrDB resolver circuit.

The search pipeline collects exact mappings (TMDb then IMDb for ThemerrDB), MusicBrainz soundtrack metadata, and up to four queries per search source, ten results per query. It has a 180-second global budget and two network workers. MusicBrainz supplies metadata, not audio. TelevisionTunes title matching is not represented as an exact ID match.

Scoring separates association (40), theme intent (25), provenance (15), duration (10), and independent-source consensus (10). Thresholds are 80 for new themes and 85 for online upgrades. Instrumental tracks are not generally penalized. Ordinary album membership alone cannot establish theme suitability. At most three distinct online audio sources are attempted. Legacy `local_opening` files may instead be upgraded to intelligent extraction; online themes never fall back to lower-quality extraction.

## Requirements

- Docker Engine with Compose v2
- An Emby server reachable from the container
- A dedicated Emby API key
- A writable media mount using the same paths Emby reports through its API
- Optional Netscape-format cookie files for providers that require authentication

The image pins its Python base digest, FFmpeg, yt-dlp, audio classifier version and classifier model SHA256. Primary CPU audio dependencies are pinned in `requirements-audio.lock`; their transitive dependencies are resolved at build time.

## Quick start

1. Clone and build:

   ```bash
   gh repo clone ump45nose/emby-theme-worker
   cd emby-theme-worker
   mkdir -p models
   curl -fL -o models/keras_speech_music_noise_cnn.hdf5 \
     https://github.com/ina-foss/inaSpeechSegmenter/releases/download/models/keras_speech_music_noise_cnn.hdf5
   docker build --build-context models=./models -t local/emby-theme-worker:0.3.0 .
   ```

2. Create persistent directories and copy the public configuration:

   ```bash
   install -d -m 0750 \
     /vol2/1000/Docker/emby-theme-worker/data \
     /vol2/1000/Docker/emby-theme-worker/config \
     /vol2/1000/Docker/emby-theme-worker/secrets
   install -m 0644 config/config.yaml \
     /vol2/1000/Docker/emby-theme-worker/config/config.yaml
   ```

3. Install a dedicated Emby API key without placing it in the repository:

   ```bash
   install -m 0400 /path/to/emby_api_key \
     /vol2/1000/Docker/emby-theme-worker/secrets/emby_api_key
   chown -R 1000:1001 /vol2/1000/Docker/emby-theme-worker
   ```

4. Review the host paths and identity in `compose.yaml`, then start the service:

   ```bash
   docker compose config --quiet
   docker compose up -d
   docker compose exec -T emby-theme-worker emby-theme-worker doctor
   docker compose exec -T emby-theme-worker emby-theme-worker preview --json
   ```

The supplied Compose file targets this private instance:

- Emby: `http://127.0.0.1:28096`
- Media: `/vol1/1000/Media:/Media:rw`
- Stack: `/vol2/1000/Docker/stacks/emby-theme-worker`
- Persistent state: `/vol2/1000/Docker/emby-theme-worker`
- Network mode: `host`

## CLI

```bash
# Connectivity, permissions, binaries, credentials, and SQLite
docker compose exec -T emby-theme-worker emby-theme-worker doctor

# Read-only scope and provider routing preview
docker compose exec -T emby-theme-worker emby-theme-worker preview --json
docker compose exec -T emby-theme-worker emby-theme-worker preview --json --item 136511

# Read-only provider resolution and scoring
docker compose exec -T emby-theme-worker emby-theme-worker probe --item 136511 --json

# Bounded manual work
docker compose exec -T emby-theme-worker emby-theme-worker run --item 136511
docker compose exec -T emby-theme-worker emby-theme-worker run --limit 10

# Audit and safely replace worker-owned legacy local openings
docker compose exec -T emby-theme-worker emby-theme-worker migrate-local --dry-run --type Movie --limit 25
docker compose exec -T emby-theme-worker emby-theme-worker migrate-local --dry-run --item EMBY_ID
docker compose exec -T emby-theme-worker emby-theme-worker migrate-local --type Movie --limit 1

# Emby intro-marker pilot for a single library
docker compose exec -T emby-theme-worker emby-theme-worker intro status --library 136475 --json
docker compose exec -T emby-theme-worker emby-theme-worker intro enable --library 136475
docker compose exec -T emby-theme-worker emby-theme-worker intro run --library 136475

# Progress and health
docker compose exec -T emby-theme-worker emby-theme-worker status --json
docker compose exec -T emby-theme-worker emby-theme-worker health
```

The default command is `serve`, with schedule `30 9 * * *` in `Asia/Taipei`. Set `automation_enabled: true` after audition to enqueue up to 25 missing items per daily run. Set `migration_enabled: true` separately for batches of up to 25 managed fallbacks. Automatic jobs do not start between 00:45 and 09:00. Manual jobs take priority; pausing stops new jobs after the current operation finishes.

## MoviePilot v2 plugin

Build the Vue assets with `cd moviepilot/frontend && npm ci && npm run build`. The local plugin package is under `moviepilot/plugins.v2/themestudio`; its manifest is `moviepilot/package.v2.json`. Merge that entry into an existing MoviePilot local repository instead of replacing unrelated entries. Install `ThemeStudio` using MoviePilot's local repository support. Do not upgrade MoviePilot as part of this installation.

Mount the Worker's socket directory at `/run/theme-worker` in both containers (read-write in Worker, read-only in MoviePilot). The socket is mode 0660; MoviePilot needs directory traversal and the Worker's group (1001 by default). Do not share the SQLite file with MoviePilot and do not use the Docker socket.

The plugin page is `/plugin-app/ThemeStudio/main`. Host authentication protects the plugin proxy. Uploads are capped at 32 MiB; supported public single-video/song URLs are canonicalized. Processing returns a job ID. Uploaded/selected/cropped audio is previewed before explicit application. Successful manual application locks the item; unrelated existing files require explicit takeover. Original-source waveform preview is limited to ten minutes. Downloads, prepared audio, streamed previews and Emby hash readback share a 64 MiB media budget. Upload requests retain the 32 MiB limit. Complete tracks that cannot fit the media budget are rejected before publication, never automatically shortened to fit.

The private socket exposes `/media`, `/status`, `/jobs`, `/diagnostics/{id}`, `/current/{id}`, `/audio/{asset}`, `/source-audio/{asset}`, `/upload/{id}`, `/source`, `/lock`, `/pause` and `/feedback`. Only Worker writes SQLite. Candidate handles are process-local: after a restart, repeat the search before preparing a candidate. Queued jobs persist; interrupted jobs are shown explicitly rather than blindly replaying an application.

## Configuration

Public settings live in `config/config.yaml`:

| Setting | Default | Purpose |
| --- | --- | --- |
| `emby_url` | `http://127.0.0.1:28096` | Emby endpoint reachable through host networking |
| `allowed_path` | `/Media` | Only eligible physical media root |
| `database_path` | `/data/worker.db` | SQLite state database |
| `schedule` | `30 9 * * *` | Cron schedule interpreted in `timezone`, after the fixed Emby downtime |
| `target_seconds` | `45` | Local video fallback duration; downloaded music stays full-length |
| `providers.threshold` | `80` | Minimum fuzzy auto-selection score |
| `providers.replacement_threshold` | `85` | Minimum score for replacing a worker-owned local opening |
| `providers.ytdlp_search_timeout_seconds` | `60` | Hard wall-clock deadline for one yt-dlp search |
| `providers.ytdlp_download_timeout_seconds` | `180` | Hard wall-clock deadline for one yt-dlp download |
| `limits.network_concurrency` | `2` | Provider lookups, bounded to 1–2 workers in the sole search pipeline |
| `limits.media_concurrency` | `1` | Download and FFmpeg concurrency boundary |
| `refresh.full_scan_after_scheduled_run` | `true` | Register pending files with one end-of-batch scan |

Cookie configuration contains file paths only. Missing optional cookie files disable cookie use without exposing secrets.

## Theme registration and state

Some Emby installations do not register newly written themes on per-item refresh. Such files remain `pending_refresh`; the explicit registration action can request a library scan. Replacing an existing theme rolls back if registration verification fails. Verification associates the theme resource path and compares the served audio hash, rather than accepting any non-empty theme list.

Manual `run --item` never starts the global scan. This keeps smoke tests bounded and distinguishes these states:

- `complete`: the matching audio resource has been verified; this does not imply a user completion lock.
- `pending_refresh`: a worker-owned, hash-matched file awaits registration.
- `skipped_existing`: Emby already indexes a theme.
- `skipped_existing_unindexed`: an unrelated disk theme exists and is preserved.
- `failed`: provider, score, download, media, or refresh failure with retry metadata.

Backoff defaults are 30 days for no result, 7 days for low score, and 6 hours increasing through 24 hours, 3 days, and 7 days for transient network failures.

## Development and testing

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
python -m compileall -q emby_theme_worker
```

The bounded smoke suite covers configuration validation, path containment, log redaction, scoring, STRM validation, atomic no-overwrite behavior, and existing-theme preservation.

## Optional shared download wheel

Theme remains independently installable and executable. The optional `shared-downloads`
extra uses the standalone `favsync-downloads` package for selected HTTP/yt-dlp downloads;
it does not import or start Favsync, MoviePilot, Bili-sync, or any account service.
Search, scoring, audio preparation, publication and state remain in Theme.

The package is staged locally and is not assumed to exist on a public package index.
Build its wheel from the matching Favsync checkout, then install from that wheelhouse:

```bash
python -m pip wheel --no-deps --wheel-dir ./wheelhouse /path/to/favsync/packages/downloads
python -m pip install --find-links ./wheelhouse '.[shared-downloads]'
```

The same byte/time budgets and redacted failure classes are passed through the adapter.
Returned artifact paths are used directly, including private subdirectories. The shared transport requires an existing work directory with no symlink path components and returns one regular, nonempty artifact.
Without the optional package, the existing transport remains as a standalone
compatibility fallback at this staging phase; transport duplication is not yet fully
removed. Errors from a broken installed package do not silently fall back.

The default Docker build is unchanged. To layer only the locally built wheel onto an
already built Theme image, use the wheelhouse as the build context:

```bash
docker build -f Dockerfile.shared-downloads \
  --build-arg WORKER_IMAGE=local/emby-theme-worker:0.3.0 \
  -t local/emby-theme-worker:0.3.0-shared ./wheelhouse
```

This optional overlay preserves the original entrypoint, user, configuration and
socket paths. Building an image does not start or deploy it.

## Backup and rollback

Keep `/data/worker.db` with the media files it audits. It records generated paths and hashes for later review.

To roll back, stop or recreate only this independent container with a retained image tag. Do not delete `/data`, and do not automatically remove generated `theme.mp3` files:

```bash
docker compose stop emby-theme-worker
docker tag local/emby-theme-worker:rollback-last-deployed local/emby-theme-worker:0.2.0
docker compose up -d --force-recreate
```

## Private-use notice

ThemerrDB entries can point to YouTube, and several fuzzy providers rely on scraping or unofficial download behavior. This worker is intended for a private media instance. Provider policies, regional restrictions, and anti-bot changes are expected operational failures handled by retries and provider circuits. Operators remain responsible for authorization and licensing of downloaded media.

## Acknowledgements

- [Themearr](https://github.com/Themearr/themearr) inspired candidate scoring and resumable provider-state design; this repository is not a fork.
- [ThemerrDB](https://github.com/LizardByte/ThemerrDB) supplies exact TMDb mappings.
- [AnimeThemes](https://animethemes.moe/) supplies anime opening metadata and media.
- [emby-theme-maker](https://github.com/Oratorian/emby-theme-maker) documents the full-library-scan registration behavior.

No GPL or AGPL plugin source is copied into this project.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
# 0.2.1 safety and migration update

- Transport circuits count download service failures only; direct HTTP is isolated by hostname. Legacy transport diagnostics are archived in SQLite before resetting their ambiguous circuit state.
- Fuzzy scoring reads explicit years and movie/series labels from source titles and album metadata, never from query defaults or upload dates. Thresholds remain 80 for new themes and 85 for replacements; sparse metadata still requires more evidence.
- Permanent `.theme.mp3.lock` files preserve cross-process locking. Backups are hash-checked and durable; rollback uses compare-and-swap and preserves externally edited files. Interrupted replacements are recovered from the SQLite journal before the next migration batch.
- Optional `migration_enabled: true` runs resumable batches (`migration_batch_size: 25`, maximum 25) alongside the normal 09:30 missing-theme schedule. Each failure has durable backoff; changed/missing files and removed Emby items require manual review. A shared migration lock prevents concurrent CLI/scheduler batches.
- Migration starts no new item between 00:45 and 09:00 in the configured timezone. In-flight work may finish later; Emby shutdown/refresh failure rolls the replacement back. Stop signals are observed between items. A batch is not a promise that 25 replacements will succeed.
