"""Persistence bridges. Each plugin supplies its own data namespace."""
from copy import deepcopy
from threading import RLock


class PluginTaskStore:
    def __init__(self, plugin, key: str = "workflow_v1"):
        self.plugin, self.key = plugin, key
        self.lock = RLock()

    def read(self) -> dict:
        with self.lock:
            return deepcopy(self.plugin.get_data(self.key) or {})

    def write(self, state: dict) -> None:
        with self.lock:
            self.plugin.save_data(self.key, deepcopy(state))


class MemoryTaskStore:
    def __init__(self):
        self.state = {}

    def read(self):
        return deepcopy(self.state)

    def write(self, state):
        self.state = deepcopy(state)
