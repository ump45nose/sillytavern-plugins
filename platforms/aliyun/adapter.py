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


def sign_only(context, client, groups, api, sleep=time.sleep):
    verified = 0
    sign_uncertain = False
    reward_uncertain = False
    try:
        auth = client.ensure_session()
        if not isinstance(auth, dict) or auth.get("ok") is not True:
            return result(context, reason="authentication_invalid")
        before = client.get_user_score()
        if before is None:
            return result(context, reason="score_unconfirmed")
        for group in groups:

            def detail():
                response = client.request(
                    "GET",
                    f"{api}/sign/getUserSpaceSignInDetail",
                    params={"excode": group["code"]},
                )
                data = response.get("data") if isinstance(response, dict) else None
                if not isinstance(data, dict):
                    raise ValueError("invalid_sign_detail")
                return data

            state = detail()
            group_id = state.get("taskGroupId")
            if not group_id:
                continue  # Preserve the existing adapter's unavailable-community policy.
            today = next(
                (x for x in state.get("signInList", []) if x.get("today")), None
            )
            if not today:
                sign_uncertain = True
                continue
            if str(today.get("status")) != "2":
                body = client.get_tasks(str(group_id))
                if not isinstance(body, dict) or not body:
                    sign_uncertain = True
                    continue
                body = {**body, "activityCode": body.get("actionCode")}
                client.request(
                    "POST",
                    f"{api}/task/actionLog",
                    data=body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
                    },
                )
                # Only reread after submission. Never replay an uncertain write.
                for _ in range(30):
                    sleep(2)
                    state = detail()
                    today = next(
                        (x for x in state.get("signInList", []) if x.get("today")), None
                    )
                    if today and str(today.get("status")) == "2":
                        break
            if not today or str(today.get("status")) != "2":
                sign_uncertain = True
                continue
            verified += 1
            bonus = client.request(
                "GET",
                f"{api}/sign/assessSignInBonusQualification",
                params={"taskGroupId": group_id},
            )
            # The pinned provider's assess_bonus reads data as eligibility.
            # Only explicit true authorizes this optional claim; unknown stays unknown.
            eligible = (
                bonus.get("data")
                if isinstance(bonus, dict) and str(bonus.get("code")) == "200"
                else None
            )
            if eligible is True:
                claimed = client.request(
                    "POST",
                    f"{api}/sign/receiveSignInBonus",
                    data={"taskGroupId": group_id},
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
                    },
                )
                if not isinstance(claimed, dict) or str(claimed.get("code")) != "200":
                    reward_uncertain = True
            elif eligible is not False:
                reward_uncertain = True
        pending = client.get_pending_score()
        if pending is None:
            reward_uncertain = True
        elif pending:
            # This GET is side-effecting; max_retries=1 also applies to it.
            claimed = client.request(
                "GET",
                f"{api}/score/pending/receiveAllPendingScore",
                params={"appCode": "developer"},
            )
            if not isinstance(claimed, dict) or str(claimed.get("code")) not in (
                "0",
                "200",
            ):
                reward_uncertain = True
        after = client.get_user_score()
        if after is None:
            reward_uncertain = True
    except Exception:
        # Do not propagate provider exceptions containing raw requests/cookies.
        return result(
            context,
            reason="provider_error",
            business={
                "checkin": "complete" if verified and not sign_uncertain else "unknown",
                "reward": "unknown",
            },
        )
    sign_complete = verified > 0 and not sign_uncertain
    success = sign_complete and not reward_uncertain
    return result(
        context,
        "ok" if success else "failed",
        "sign_and_claim_confirmed" if success else "business_unconfirmed",
        {
            "checkin": "complete" if sign_complete else "unknown",
            "reward": "complete" if success else "unknown",
        },
    )


def execute(context, provider, cookie, proxy=None):
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
        return sign_only(context, client, provider.TASK_GROUPS, provider.API)
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
            output = execute(context, provider, cookie, os.getenv("ALIYUN_PROXY"))
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
