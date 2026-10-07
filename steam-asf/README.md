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
- `logs/`: ASF logs; the Docker log is separately bounded.
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

In your own interactive NAS SSH terminal, run the installed helper:

```sh
sudo -u hermes env -i PATH=/usr/bin:/bin python3 /home/yuwk/cron/scripts/steam-asf/login.py
```

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
promotion verification. No `--claim` argument is deployed.

`benefits-steam-readonly` is registered with `7,37 * * * *` in Asia/Taipei and
paused while login/acceptance is pending. Use Hermes' own create/update APIs,
under the Lingjun runtime identity, to enable it after read-only acceptance;
do not hand-edit `jobs.json`. The existing noon benefits notice job reads Steam
alongside the six prior platforms. Only exceptions produce a notice. Eligible
dry-run packages are explicitly reported as awaiting claim authorization.

To roll back, pause the Steam job and stop only `benefits-steam-asf` with
Compose. Retain all private ASF data and benefits journals. The pre-Steam
deployment JSON is backed up in the private Lingjun directory. Restoring a
source revision must not discard durable submission intents.
