# NAS cron jobs

Small host-native jobs used on the FNOS server.

Each job lives in its own directory and contains its executable source plus
systemd unit templates. Runtime scripts are deployed to `/home/yuwk/cron`;
state and credentials remain outside Git.

## Jobs

- `taglab-delete-worker/`: move Navidrome tracks matching configured rules to
  the media library's `.trash` directory.
- `shellcrash-traffic/`: 24x7 Mihomo traffic accounting, reports, rolling
  AI-friendly JSON export, and SubBoost-to-ShellCrash refresh.

This repository intentionally excludes credentials, live SQLite databases,
generated reports, browser state, and other machine-local runtime data.
