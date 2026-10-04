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
