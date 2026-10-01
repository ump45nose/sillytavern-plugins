"""Offline contract checks for the pinned Epic application, without importing it."""

import ast
import json
from pathlib import Path
from common.contracts import verify_files

REQUIRED = {
    "app/services/epic_games_service.py": {
        "EpicGames": {
            "_empty_cart",
            "_submit_place_order",
            "_uk_confirm_order",
            "_active_purchase_container",
        }
    },
    "app/services/epic_authorization_service.py": {
        "EpicAuthorization": {
            "_wait_for_login_form",
            "_submit_login_or_accept_challenge",
            "_await_login_outcome",
            "_has_account_session",
        }
    },
}


def preflight(root):
    manifest = json.loads(
        Path(__file__).with_name("upstream-contract.json").read_text()
    )
    error = verify_files(root, manifest["files"])
    if error:
        return error
    for file, classes in REQUIRED.items():
        tree = ast.parse((Path(root) / file).read_text())
        for name, methods in classes.items():
            cls = next(
                (
                    x
                    for x in tree.body
                    if isinstance(x, ast.ClassDef) and x.name == name
                ),
                None,
            )
            if cls is None or not methods.issubset(
                {
                    x.name
                    for x in cls.body
                    if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            ):
                return "dependency_incompatible"
    # Explicit gates, not an import-and-see probe: upstream currently records video,
    # chooses source-tree state paths and invokes challenge/terms handling internally.
    return "native_paths_challenge_and_checkout_audit_required"
