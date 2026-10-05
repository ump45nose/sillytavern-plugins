#!/usr/bin/env python3
"""env-base auditor — enforce the shared-secret storage rule.

RULE (see CLUSTER.md §Provider与凭据):
  A secret that is SHARED across profiles (provider keys, cross-profile MCP
  auth, server/service tokens) MUST live in the root ~/.hermes/.env only.
  A per-profile .env may hold ONLY per-identity secrets: that profile's own
  bot token / channel identity (TELEGRAM_BOT_TOKEN, WEIXIN_*).

This script is the executable form of that rule. It reads only KEY NAMES —
never secret values — and exits non-zero (and prints) when a shared secret is
found in a profile .env, so a cron/CI can alert. Read-only: it never edits.
"""
import glob
import os
import re
import sys

ROOT = "/home/hermes/.hermes"
GLOBAL_ENV = f"{ROOT}/.env"

# Secrets that are per-identity and legitimately live per-profile.
PER_PROFILE_OK = re.compile(
    r"^(TELEGRAM_BOT_TOKEN|WEIXIN_[A-Z0-9_]+)$"
)
# Anything matching this is a SHARED secret and must be global-only.
SHARED_SECRET = re.compile(
    r"(_API_KEY|_SECRET|_TOKEN|SECRET_KEY|CLIENT_ID|CLIENT_SECRET|WEBHOOK)$",
    re.I,
)


def key_names(path):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if not t or t.startswith("#") or "=" not in t:
                    continue
                out.append(t.split("=", 1)[0].strip())
    except FileNotFoundError:
        pass
    return out


def main():
    violations = []
    for env in sorted(glob.glob(f"{ROOT}/profiles/*/.env")):
        profile = env.split("/")[-2]
        for k in key_names(env):
            if PER_PROFILE_OK.match(k):
                continue
            if SHARED_SECRET.search(k):
                violations.append((profile, k))

    if violations:
        print("SHARED-SECRET RULE VIOLATION — these belong in root .env only:")
        for prof, k in violations:
            print(f"  [{prof}] {k}")
        print(f"\nFix: move each to {GLOBAL_ENV} and delete it from the "
              f"profile .env (values stay secret; configs use key_env).")
        return 1

    gcount = len(key_names(GLOBAL_ENV))
    print(f"OK — no shared secret leaked into any profile .env "
          f"(root .env holds {gcount} keys; per-profile .env limited to "
          f"bot/channel identity).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
