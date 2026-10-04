# Hermes cron reports

Business-specific no-agent reports for Hermes scheduled tasks. Runtime reports
are read-only and use only the sources documented in each business directory.

## Business directories

- favsync/: exception-only alert for the existing daily Favsync cron. Alerts
  identify the affected platform and problem. The existing 09:10 schedule
  remains on the Hermes job.
- media-automation/: daily report from MoviePilot downloadhistory,
  FilmWatchlist plugindata.records, Emby Theme worker items, and the read-only
  MediaArchive/DiscRemux `/jobs` APIs. The API token is read from Hermes'
  protected root `.env` under a subprocess-scrubbed key and sent only as
  `X-API-KEY`; it is never placed in a cron definition or report output.
  Plugin jobs have no update timestamp, so
  that section is a current-state snapshot rather than a 24-hour change list.
  SQLite connections are read-only; the worker DB is queried in immutable mode
  only when no WAL/journal exists and the file remains stable for the read.
  Planned cadence: daily at 09:30 (Asia/Taipei), after the 09:10 Favsync run.
- benefits-automation/: exception-only report from the six existing benefits
  task delivery JSON files; no benefits API is called.

Cron delivery through `@yuwk_notice_bot` awaits the per-topic IDs for that bot.
The notice-bot sender validates its token with `getMe`, verifies each returned
chat/topic, and reads its token from Hermes' protected `.hermes/.env` file.
Per-topic routing is kept in the Hermes-local `cron/notice_topics.json` file.

Database snapshots, credentials, and runtime state must not be committed.
