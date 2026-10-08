# Steam ASF deployment

The Steam business executor lives in `benefits-automation/platforms/steam`.
This directory owns NAS deployment and a human-run login helper. Hermes owns
the schedule and notice-bot delivery; no separate database or queue is needed.

Pinned versions: ASF 6.3.10.3, FreePackages 1.7.1.1. The Compose image is pinned
by digest; `prepare.py` verifies the plugin's published SHA-256 before installing.
Watchtower and ASF/plugin automatic updates are disabled for this service.

Private data lives outside both repositories under
`/vol2/1000/Docker/benefits-automation/steam-asf`:

- `config/`: ASF global/bot configuration and persistent login/session databases.
- `plugins/`: verified FreePackages binaries, mounted read-only.
- `logs/`: private QR diagnostic metadata; the Docker log is separately bounded.
  Normal ASF `log.txt` remains in the container's writable layer.
- `private/connection.json`: generated IPC identity, preserved across restores.
- `private/steam.json`: created after the user completes login and identity checks.

Directories are owned by runtime UID 988/GID 984 and mode 0700; configuration
files are 0600. Keeping the IPC config outside `/home/hermes` avoids the runtime
ACL reconciler widening permissions rejected by the Steam executor.
The NAS administrator can access these files through sudo. Never print or
commit their contents. Back up this directory privately together with the
existing benefits runtime journals/discovery state.

## Install or restore

Download the pinned plugin from the official
[release](https://github.com/Citrinate/FreePackages/releases/tag/1.7.1.1).
Then run on the NAS:

```sh
sudo install -d -o hermes -g hermes -m 700 /vol2/1000/Docker/benefits-automation/steam-asf
sudo -u hermes env -i PATH=/usr/bin:/bin python3 /home/yuwk/code/nas-cron-jobs/steam-asf/prepare.py --plugin-zip /absolute/path/FreePackages.zip
docker compose -f /home/yuwk/code/nas-cron-jobs/steam-asf/compose.yaml up -d
```

Do not overwrite existing bot configuration or login databases. `prepare.py`
preserves the existing IPC identity and bot file, and initially creates a
disabled bot with farming paused and `EnableFreePackages: false`.
The IPC listener is published only to NAS `127.0.0.1:1242` and requires an
Authentication header. No reverse proxy or public listener is created.

## First login: user participation

Prefer mobile QR authorization with the installed helper, using the existing
Hermes Python environment (it supplies `qrcode` and Pillow):

```sh
sudo -u hermes env -i PATH=/usr/bin:/bin /home/hermes/.hermes/hermes-agent/venv/bin/python /home/yuwk/cron/scripts/steam-asf/qr-login.py --steam-id YOUR_STEAMID64 --region YOUR_COUNTRY --login-name YOUR_ACCOUNT_LOGIN
```

The helper briefly recreates this ASF container with headless mode disabled,
a metadata-only NLog target and stdout/stderr redirected, because upstream otherwise
logs the QR authorization URI. IPC remains authenticated and loopback-only.
No log messages or exception text are retained; diagnostics contain only
timestamps, levels, method names and exception types. A private PNG is produced;
display it to the account owner, who scans it
and approves in Steam mobile. The account login name must match, then SteamID
is checked before enabling persistent reconnect. Normal headless deployment
is restored on success, timeout or interruption, and temporary QR files are
removed. No password or Guard code is requested. After authorization, a real
container restart must reconnect to the same account before the helper writes
the private adapter configuration. Do not force-kill this controller; use
SIGTERM so it can restore the normal service.
QR preference is reseeded for transient network disconnects, with at most three
observed challenge sessions; it never falls back to submitting credentials.

For accounts requiring password-based login instead, use hidden terminal input.
In your own interactive NAS SSH terminal, run the installed helper:

```sh
sudo -u hermes env -i PATH=/usr/bin:/bin python3 /home/yuwk/cron/scripts/steam-asf/login.py
```

`--steam-id`, `--region` and `--login-name` can prefill the non-secret account
identity. Use the Steam account name shown below the nickname in mobile Guard;
the display nickname cannot authenticate. The password and Guard code still
use hidden terminal input, never arguments. Both login helpers share a lock.

Enter the exact SteamID64 and actual Steam store country. The helper hides the
account name/password/Guard code and sends them only through authenticated
loopback IPC `/Input`; ASF does not serialize these transient inputs into its
bot config. Do not put passwords or codes in shell arguments, chat, files or
`docker attach` input: ASF's direct console path can log Guard input.
Mobile device approval remains with the user. The helper never resubmits a
password or repeats a Guard prompt. A successful login persists the refresh-token
session in the private ASF database and the login name in the private bot config
for restart reconnect, verifies SteamID, then writes the adapter config. Region
is the user's statement of the account's real store country; ASF bot metadata
does not establish that country.

## Read-only acceptance and scheduling

Call the installed Hermes entrypoint as the real runtime user:

```sh
sudo -u hermes env -i PATH=/usr/bin:/bin HERMES_HOME=/home/hermes/.hermes/profiles/lingjun python3 /home/hermes/.hermes/profiles/lingjun/scripts/benefits_steam.py
```

Read `benefits-runtime/delivery/steam.json` and the same run's saved result.
Check real PICS wire schemas, bounded automatic discovery, actual official
purchase-block evidence and owned-package results. HTTP routes existing,
simulated tests, or a no-candidate result cannot establish successful real
promotion verification. Start new installations without `--claim`.

`benefits-steam-free-claim` uses `7,37 * * * *` in Asia/Taipei. On the current NAS,
first login, same-account restart reconnect and real read-only interface checks
have passed; the user subsequently authorized free claims. The existing job ID
is retained, its launcher arguments now include `--claim`, and a real scheduler
fire in this mode has been verified. Only vetted free promotions are submitted.
For a new installation, keep it paused until those checks pass. Use Hermes' own
create/update APIs under the Lingjun runtime identity; do not hand-edit `jobs.json`.
The existing noon benefits notice job reads Steam
alongside the six prior platforms. Only exceptions produce a notice. Eligible
dry-run packages are explicitly reported as awaiting claim authorization.

The first `GetChangesSince/0` required a full history update. Its state and
adapter settings were privately backed up before setting the incremental
baseline to the first verified cursor (`39563190`); the pending queue was kept.
`private/discovery-window.json` records that older history is unverified.
Existing state/config baselines must be restored as a pair. Real changed
packages with `MissingToken=true` remain held for review. Current positive
official-store samples are DLC and excluded by the game-only rule; this does
not establish a fully eligible limited-time game promotion.

The explicitly selected acceptance game, Arena of Trophies (app 2922790), was
verified free on its real CN store page and PICS. One `RequestFreeAppLicense`
POST granted package 1135007; app/package ownership was read back, raising the
positive package count from 275 to 276. Its private durable acceptance receipt
was written before the POST and confirmed afterwards. The granted package is
also in the shared journal/rate budget. An owned recheck submitted no new POST.
This F2P sample does not enable background collection of all free games.

The private adapter config now sets `store_proxy_url` to the existing local
HTTP proxy for anonymous store GETs. The proxy had routed Steam store traffic
DIRECT, reproducing CDN TLS timeouts. A persistent exact-domain rule for
`store.steampowered.com` now uses the existing international proxy group; other
Steam domain rules and selector choices are preserved. Account country remains
CN, TLS remains verified, and IPC authentication never enters this proxy.
Store transport errors and transient 5xx retry once with 10-second per-attempt
timeouts; 429/403/redirects and license POSTs do not retry. Config/route backups
are private. To return to read-only, remove only the Steam launcher's `--claim`.

To roll back, pause the Steam job and stop only `benefits-steam-asf` with
Compose. Retain all private ASF data and benefits journals. The pre-Steam
deployment JSON is backed up in the private Lingjun directory. Restoring a
source revision must not discard durable submission intents.

## 2026-10-08 NAS 部署说明

NAS 正式入口现为 `/vol2/1000/Docker/stacks/automation/compose.yaml`，本目录 Compose 由 automation 组 include；容器 benefits-steam-asf 和持久配置不变，default 网络显式保留 benefits-steam_default。更新示例：`docker compose -p automation -f /vol2/1000/Docker/stacks/automation/compose.yaml up -d --no-deps asf`。
