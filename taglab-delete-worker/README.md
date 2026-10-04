# TagLab delete worker

A small one-shot Navidrome cleanup worker extracted from the former TagLab
deployment. It selects tracks using Navidrome metadata and moves matching files
under the library's `.trash` tree instead of deleting them.

The production timer runs every five minutes. Credentials live in
`/home/yuwk/cron/env/taglab-delete-worker.env` and are not stored in Git.

Logs go to journald:

```bash
journalctl -u taglab-delete-worker.service
```

Use `DRY_RUN=true` when validating rule changes.
