"""One-shot Rainyun workflow. Importing this module starts no browser or network."""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.details import metric, number
from common.model import atomic_json, result
from platforms.rainyun.state import Journal
from platforms.rainyun.browser import Browser, RainyunError


def load_config(filename):
    if not filename:
        raise RainyunError("missing_configuration")
    path = Path(filename)
    repository = Path(__file__).resolve().parents[2]
    if not path.is_absolute() or repository in path.resolve().parents:
        raise RainyunError("invalid_configuration")
    try:
        with path.open("rb") as stream:
            if stat.S_IMODE(os.fstat(stream.fileno()).st_mode) & 0o077:
                raise RainyunError("private_file_permissions")
            raw = stream.read(16385)
        config = json.loads(raw)
    except (OSError, ValueError, UnicodeDecodeError):
        raise RainyunError("invalid_configuration") from None
    required = {"username", "password", "chromium_path", "chromedriver_path", "provider_root"}
    if (len(raw) > 16384 or not isinstance(config, dict)
            or set(config) - required - {"proxy"} or not required <= set(config)
            or any(not isinstance(config[k], str) or not config[k]
                   or len(config[k]) > 4096 or "\x00" in config[k] for k in required)):
        raise RainyunError("invalid_configuration")
    if any(not Path(config[k]).is_absolute()
           for k in ("chromium_path", "chromedriver_path", "provider_root")):
        raise RainyunError("invalid_configuration")
    proxy = config.get("proxy")
    if proxy:
        try:
            target = urlsplit(proxy)
            if (target.scheme not in {"http", "https"} or not target.hostname
                    or target.username or target.password or target.path not in {"", "/"}
                    or target.query or target.fragment or not target.port):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise RainyunError("invalid_proxy") from None
    elif proxy not in (None, ""):
        raise RainyunError("invalid_proxy")
    return config


def execute(context, browser, journal, *, read_only=False):
    before = after = None
    checkin = "unknown"

    def finish(reason, failed=False):
        current = after if after is not None else before
        delta = after - before if before is not None and after is not None else None
        return result(context, "failed" if failed else "ok", reason,
                      {"checkin": checkin, "balance": "complete" if after is not None else "unknown"},
                      {"metrics": {"balance": metric("points", current, before=before,
                                                       after=after, delta=delta)}, "items": []})

    try:
        browser.open()
        initial = browser.read()
        checkin = initial["checkin"]
        before = number(initial.get("balance"))
        if before is not None and before < 0:
            before = None
        after = before
        if checkin == "complete":
            journal.set("complete")
            return finish("checkin_confirmed" if after is not None
                          else "checkin_confirmed_balance_unavailable")
        if checkin != "incomplete":
            return finish("checkin_state_unknown")
        if journal.status == "complete":
            checkin = "unknown"
            return finish("checkin_state_conflict")
        if journal.status == "pending":
            checkin = "unknown"
            return finish("claim_pending_readback")
        if read_only:
            return finish("status_only")

        def before_submit():
            journal.set("pending")

        failure = None
        after = None
        try:
            browser.claim(before_submit)
        except RainyunError as error:
            failure = str(error)
        except OSError:
            failure = "action_state_io_error"
        except Exception:
            failure = "browser_operation_failed"
        # A click can reach the server before a transport/renderer exception.
        # One independent readback is permitted; a second claim is not.
        try:
            observed = browser.read()
            checkin = observed["checkin"]
            after = number(observed.get("balance"))
            if after is not None and after < 0:
                after = None
        except Exception:
            checkin = "unknown"
            return finish(failure or "claim_readback_failed", failed=True)
        if checkin == "complete":
            journal.set("complete")
            return finish("checkin_confirmed" if after is not None
                          else "checkin_confirmed_balance_unavailable")
        if failure and failure.startswith("captcha_"):
            checkin = "blocked"
        return finish(failure or "checkin_not_confirmed", failed=failure is not None)
    except RainyunError as error:
        return finish(str(error), failed=True)
    except OSError:
        return finish("action_state_io_error", failed=True)
    except Exception:
        return finish("browser_operation_failed", failed=True)


def main():
    context = {k: os.environ["BENEFITS_" + k.upper()]
               for k in ("run_id", "platform", "account", "business_date")}
    browser = None
    try:
        config = load_config(os.environ.get("RAINYUN_CONFIG"))
        identity = hashlib.sha256(config["username"].encode()).hexdigest()[:24]
        directory = Path(os.environ["BENEFITS_STATE_DIR"]) / identity
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            journal = Journal(context, directory)
        except (OSError, ValueError):
            raise RainyunError("invalid_action_state") from None
        browser = Browser(config, directory)
        output = execute(context, browser, journal, read_only="--status" in sys.argv[1:])
    except RainyunError as error:
        output = result(context, reason=str(error))
    except ImportError:
        output = result(context, reason="dependency_unavailable")
    except (OSError, ValueError):
        output = result(context, reason="configuration_or_io_error")
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                if "output" in locals():
                    output.update(execution_status="failed", reason="browser_cleanup_unverified")
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
