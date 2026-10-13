"""One daily redeem intent, retained until balance readback confirms it."""

import json
import os
from pathlib import Path
from common.model import atomic_json, validate


class Journal:
    def __init__(self, context, directory=None, confirmed_path=None):
        self.context = context
        self.path = Path(directory) / "http-actions.json" if directory else None
        self.status = "unknown"
        if self.path:
            try:
                with self.path.open("rb") as stream:
                    raw = stream.read(4097)
                old = json.loads(raw)
                if (
                    len(raw) > 4096
                    or set(old) != {"version", "account", "date", "status"}
                    or old["version"] != 1
                    or old["account"] != context["account"]
                    or not isinstance(old["date"], str)
                    or old["status"] not in {"unknown", "pending", "complete"}
                ):
                    raise ValueError("invalid_action_state")
                if old["date"] == context["business_date"]:
                    self.status = old["status"]
            except FileNotFoundError:
                pass
        if confirmed_path and self.status == "unknown":
            try:
                with open(confirmed_path, "rb") as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError("invalid_previous_result")
                old = json.loads(raw)
                if not isinstance(old, dict):
                    raise ValueError("invalid_previous_result")
                previous = {
                    **context,
                    "run_id": old.get("run_id"),
                    "business_date": old.get("business_date"),
                }
                old = validate(old, previous)
                if (
                    old["business_date"] == context["business_date"]
                    and old["business"].get("checkin") == "complete"
                    and old["business"].get("reward") == "complete"
                ):
                    self.status = "complete"
            except FileNotFoundError:
                pass

    def set(self, status):
        self.status = status
        if self.path:
            atomic_json(
                self.path,
                {
                    "version": 1,
                    "account": self.context["account"],
                    "date": self.context["business_date"],
                    "status": status,
                },
            )
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
