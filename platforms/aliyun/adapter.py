"""One-account, sign-and-claim-only adapter for a hash-pinned external provider.

Never calls provider.main/run/notification/interaction/password-login routines.
The unlicensed external daily.py is not redistributed by this project.
"""

import hashlib
import logging
import os
from pathlib import Path
import sys
import time
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.model import result, atomic_json
from platforms.aliyun.state import Journal

SOURCE_SHA256 = "286563810a780f06edaa0eea2dd0633480b403d6634ab3357d0890df77b696c3"
MAX_SOURCE = 512 * 1024


def load_provider(path):
    with open(path, "rb") as source:
        raw = source.read(MAX_SOURCE + 1)
    if len(raw) > MAX_SOURCE or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("dependency_incompatible")
    name = "_benefits_pinned_aliyun"
    module = types.ModuleType(name)
    module.__file__ = str(Path(path).resolve())
    sys.modules[name] = module
    # Compile exactly the verified bytes, not a second mutable read of the path.
    exec(compile(raw, module.__file__, "exec"), module.__dict__)
    for symbol in ("Account", "AppConfig", "AliyunDevClient", "TASK_GROUPS", "API"):
        if not hasattr(module, symbol):
            raise ValueError("dependency_incompatible")
    return module


def sign_only(context, client, groups, api, sleep=time.sleep, state_dir=None):
    try:
        codes = [group["code"] for group in groups]
        if any(not isinstance(code, str) or len(code) > 32 for code in codes):
            raise ValueError("invalid_communities")
        journal = Journal(context, codes, state_dir)
    except Exception:
        return result(context, reason="invalid_action_state")
    had_error = False
    score_known = False
    pending_confirmed = False

    def finish(reason=None):
        signs = [journal.get(code, "sign") for code in codes]
        bonuses = [journal.get(code, "bonus") for code in codes]
        sign_complete = bool(signs) and all(x == "complete" for x in signs)
        success = (
            sign_complete
            and score_known
            and pending_confirmed
            and all(x in {"complete", "not_applicable"} for x in bonuses)
            and journal.value["pending_score"] in {"complete", "not_applicable"}
        )
        business = {
            "checkin": "complete" if sign_complete else "unknown",
            "reward": "complete" if success else "unknown",
        }
        # All 15 pinned communities, including excode="", fit the 32-field result limit.
        # Facts already confirmed survive another community's failure.
        for index, code in enumerate(codes):
            business[f"community_{index}_checkin"] = (
                "complete" if journal.get(code, "sign") == "complete" else "unknown"
            )
            bonus = journal.get(code, "bonus")
            business[f"community_{index}_bonus"] = (
                bonus if bonus in {"complete", "not_applicable"} else "unknown"
            )
        return result(
            context,
            "ok" if success else "failed",
            "sign_and_claim_confirmed"
            if success
            else reason or ("provider_error" if had_error else "business_unconfirmed"),
            business,
        )

    try:
        auth = client.ensure_session()
        if not isinstance(auth, dict) or auth.get("ok") is not True:
            return finish("authentication_invalid")
        if client.get_user_score() is None:
            return finish("score_unconfirmed")
    except Exception:
        return finish("provider_error")
    for code in codes:
        try:

            def detail():
                response = client.request(
                    "GET",
                    f"{api}/sign/getUserSpaceSignInDetail",
                    params={"excode": code},
                )
                data = response.get("data") if isinstance(response, dict) else None
                if not isinstance(data, dict):
                    raise ValueError("invalid_sign_detail")
                return data

            def signed(data):
                rows = data.get("signInList")
                return isinstance(rows, list) and any(
                    isinstance(x, dict)
                    and x.get("today")
                    and str(x.get("status")) == "2"
                    for x in rows
                )

            state = detail()
            group_id = state.get("taskGroupId")
            if not group_id:
                continue  # Missing community data is unknown, never aggregate completion.
            if signed(state):
                journal.set(code, "sign", "complete")
            if journal.get(code, "sign") != "complete":
                today = next(
                    (
                        x
                        for x in state.get("signInList", [])
                        if isinstance(x, dict) and x.get("today")
                    ),
                    None,
                )
                if not today:
                    continue
                if journal.get(code, "sign") != "pending":
                    body = client.get_tasks(str(group_id))
                    if not isinstance(body, dict) or not body:
                        continue
                    body = {**body, "activityCode": body.get("actionCode")}
                    journal.set(code, "sign", "pending")
                    try:
                        client.request(
                            "POST",
                            f"{api}/task/actionLog",
                            data=body,
                            headers={
                                "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
                            },
                        )
                    except Exception:
                        had_error = True
                # Includes a timed-out POST and a prior process's uncertain intent.
                # Read-only reconciliation may confirm it; never resend this day's write.
                for _ in range(30):
                    sleep(2)
                    if signed(detail()):
                        journal.set(code, "sign", "complete")
                        break
            if journal.get(code, "sign") != "complete":
                continue
            if journal.get(code, "bonus") == "complete":
                continue
            bonus = client.request(
                "GET",
                f"{api}/sign/assessSignInBonusQualification",
                params={"taskGroupId": group_id},
            )
            eligible = (
                bonus.get("data")
                if isinstance(bonus, dict) and str(bonus.get("code")) == "200"
                else None
            )
            if eligible is True and journal.get(code, "bonus") != "pending":
                journal.set(code, "bonus", "pending")
                claimed = client.request(
                    "POST",
                    f"{api}/sign/receiveSignInBonus",
                    data={"taskGroupId": group_id},
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
                    },
                )
                if isinstance(claimed, dict) and str(claimed.get("code")) == "200":
                    journal.set(code, "bonus", "complete")
            elif eligible is False and journal.get(code, "bonus") != "pending":
                journal.set(code, "bonus", "not_applicable")
            # An eligibility flag disappearing does not prove an ambiguous claim paid.
        except Exception:
            had_error = True
    try:
        pending = client.get_pending_score()
        if pending == 0 and pending is not None:
            journal.set_pending(
                "complete"
                if journal.value["pending_score"] in {"pending", "complete"}
                else "not_applicable"
            )
            pending_confirmed = True
        elif pending is not None and pending > 0:
            if journal.value["pending_score"] not in {"pending", "complete"}:
                journal.set_pending("pending")
                try:
                    claimed = client.request(
                        "GET",
                        f"{api}/score/pending/receiveAllPendingScore",
                        params={"appCode": "developer"},
                    )
                    if isinstance(claimed, dict) and str(claimed.get("code")) in {
                        "0",
                        "200",
                    }:
                        journal.set_pending("complete")
                        pending_confirmed = True
                except Exception:
                    had_error = True
                if (
                    journal.value["pending_score"] == "pending"
                    and client.get_pending_score() == 0
                ):
                    journal.set_pending("complete")
                    pending_confirmed = True
        elif pending is None:
            # Successful earlier claims are facts, but do not establish today's
            # currently unknown pending balance. Keep the aggregate uncertain.
            return finish("provider_error" if had_error else "business_unconfirmed")
        score_known = client.get_user_score() is not None
    except Exception:
        had_error = True
    return finish()


def execute(context, provider, cookie, proxy=None, state_dir=None):
    if not cookie or "\r" in cookie or "\n" in cookie:
        return result(context, reason="missing_or_invalid_cookie")
    client = None
    try:
        account = provider.Account(name=context["account"], cookie=cookie)
        cfg = provider.AppConfig(
            accounts=[account],
            max_retries=1,
            timeout=30,
            enable_scene=False,
            enable_video=False,
            enable_stock=False,
        )
        client = provider.AliyunDevClient(account, cfg, {})
        # No ambient proxy/credential discovery through requests' trust_env.
        client.session.trust_env = False
        if proxy:
            client.session.proxies.update({"http": proxy, "https": proxy})
        return sign_only(
            context, client, provider.TASK_GROUPS, provider.API, state_dir=state_dir
        )
    except Exception:
        return result(context, reason="dependency_or_provider_error")
    finally:
        if client is not None:
            client.session.close()


def main():
    context = {
        k: os.environ["BENEFITS_" + k.upper()]
        for k in ("run_id", "platform", "account", "business_date")
    }
    # No provider logger output: upstream debug text can contain response bodies.
    logging.getLogger("aliyun_dev").disabled = True
    path = os.getenv("ALIYUN_UPSTREAM_PATH", "")
    cookie = os.getenv("ALIYUN_COOKIE", "")
    if not cookie:
        output = result(context, reason="missing_or_invalid_cookie")
    elif not path:
        output = result(context, reason="dependency_unavailable")
    else:
        try:
            provider = load_provider(path)
        except Exception:
            output = result(context, reason="dependency_unavailable_or_incompatible")
        else:
            output = execute(
                context,
                provider,
                cookie,
                os.getenv("ALIYUN_PROXY"),
                os.environ.get("BENEFITS_STATE_DIR"),
            )
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
