# media-capabilities

Independently built Python wheel for media automation. Requires Python 3.11+ and httpx.
Provider-neutral models, ports and policies have no MoviePilot imports. Explicit adapters
provide local file operations, Emby, MoviePilot/qB, installed P115 helpers and MakeMKV.

Upload does not publish to a media server. Disc preparation delivers verified files.
STRM publication and Emby state migration are separate capabilities. Application
workflows and persistence belong to the consuming plugins.

Build with `python3 -m pip wheel --no-deps ./packages/media-capabilities` from the repository root.
MoviePilot adapters require the host's packages; no MoviePilot dependency is installed by this wheel.
See `docs/media-archive-and-remux.md` in the maintenance repository for installation and contracts.

Version 0.3.2 provides the optional `acquisition` extra: shared Mini4K/M-Team boundaries,
BT evidence, media targets, selection profiles, durable submission registry and HTTP client.
FilmWatchlist's old module paths are compatibility imports of this package. New web/MCP
entrypoints import host-neutral DTOs and the HTTP client; MoviePilot host imports remain
deferred in explicit adapters. `MediaCapabilities` is the independent MoviePilot host;
adapters receive explicit settings and factories rather than a FilmWatchlist instance.
Its runtime and persistent registry serve all three consumers, with one-time legacy
imports and shared process locks across host reloads. See `docs/media-acquisition.md`.

Resource search falls back to the supplied title and optional year when metadata is
missing or unavailable. Responses mark the identity as unverified; download requests
still require confirmed identity and episode coverage.
