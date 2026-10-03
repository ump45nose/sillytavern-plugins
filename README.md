# Hermes cron reports

Business-specific no-agent reports for Hermes scheduled tasks. Runtime reports
are read-only and use only the sources documented in each business directory.

## Business directories

- favsync/: exception-only alert for the existing daily Favsync cron. Alerts
  identify the affected platform and problem. The existing Ops topic and
  09:10 schedule remain on the Hermes job.
- media-automation/: daily report from MoviePilot downloadhistory,
  FilmWatchlist plugindata.records, and Emby Theme worker items.
  SQLite connections use read-only mode; no new API or database write is used.
  Planned cadence: daily at 09:30 (Asia/Taipei), after the 09:10 Favsync run.
  Hermes cron registration awaits runtime read access and the Film Telegram topic.
- benefits-automation/: reserved until the benefits task's JSON contract is
  available.

Database snapshots, credentials, and runtime state must not be committed.
