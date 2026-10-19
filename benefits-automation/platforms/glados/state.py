"""One account/day's persisted check-in intent and direct confirmation."""

from datetime import date
import json
import os
from pathlib import Path

from common.details import number
from common.model import atomic_json


class Journal:
    def __init__(self, context, directory):
        self.path = Path(directory) / "checkin.json"
        self.value = {"version": 1, "account": context["account"],
                      "date": context["business_date"], "status": "unknown", "reward": None}
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(4097)
            old = json.loads(raw)
            if (len(raw) > 4096 or not isinstance(old, dict) or set(old) != set(self.value)
                    or old["version"] != 1 or old["account"] != context["account"]
                    or old["status"] not in {"unknown", "pending", "complete"}
                    or not isinstance(old["date"], str)
                    or old["reward"] is not None and
                    (number(old["reward"]) is None or number(old["reward"]) < 0)):
                raise ValueError("invalid_action_state")
            date.fromisoformat(old["date"])
            if old["date"] == context["business_date"]:
                self.value = old
        except FileNotFoundError:
            pass

    @property
    def status(self):
        return self.value["status"]

    @property
    def reward(self):
        return self.value["reward"]

    def set(self, status, reward=None):
        self.value.update(status=status, reward=reward)
        atomic_json(self.path, self.value)
        directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
