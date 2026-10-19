# Retired Telegram recovery timer

Disabled on 2026-10-13. The old checker restarted an entire gateway whenever
it saw a retryable Telegram network error. Hermes already rebuilds failed
adapters in its background reconnect queue. The incident logs show native
reconnect attempts followed by external gateway restarts; one gateway then
exceeded its stop deadline and was killed.

The script and units are retained for reference, but the timer must remain
disabled. Keep the gateways' existing systemd `Restart=always` policy for
actual process exits. Do not restart a healthy gateway merely because its
Telegram adapter is retrying.

The runtime script is `/home/yuwk/cron/scripts/hermes-telegram-recovery-check`;
its inactive units remain under `/home/yuwk/cron/systemd`. No profile,
credential, session, schedule or gateway source was changed.
