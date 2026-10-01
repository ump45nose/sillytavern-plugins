"""Offline upstream and resource-safety config checks, no Node imports."""

import json
from pathlib import Path
from common.contracts import verify_files


def validate_config(config, accounts):
    if not isinstance(accounts, list) or len(accounts) != 1:
        return "single_account_required"
    if not isinstance(config, dict):
        return "invalid_config"
    if (
        config.get("clusters") != 1
        or config.get("searchSettings", {}).get("parallelSearching") is not False
        or config.get("searchSettings", {}).get("clusterSearch") is not False
    ):
        return "parallel_browser_unsupported"
    if config.get("headless") is not True:
        return "headless_required"
    if config.get("workers", {}).get("doDailySet") is not False:
        return "duplicate_daily_execution_risk"
    return None


def preflight(root):
    manifest = json.loads(
        Path(__file__).with_name("upstream-contract.json").read_text()
    )
    error = verify_files(root, manifest["files"])
    if error:
        return error
    # Official release is a candidate, not proof of equivalence to the private image.
    return "session_schema_build_and_browser_serialization_audit_required"
