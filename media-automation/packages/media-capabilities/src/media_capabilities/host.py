"""Small reusable plugin UI/config and single-worker helpers."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import Lock


class SingleWorker:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="media-capability")
        self.lock = Lock()
        self.futures = {}
        self.closed = False

    def submit(self, key, function, *args, **kwargs):
        with self.lock:
            if self.closed:
                raise RuntimeError("后台队列已停止")
            future = self.futures.get(key)
            if future and not future.done():
                return False
            self.futures[key] = self.pool.submit(function, *args, **kwargs)
            return True

    def busy(self):
        with self.lock:
            return any(not future.done() for future in self.futures.values())

    def stop(self):
        with self.lock:
            self.closed = True
            self.pool.shutdown(wait=False, cancel_futures=True)


def load_config(defaults, config):
    result = deepcopy(defaults)
    result.update({k: v for k, v in (config or {}).items() if k in defaults})
    for key, default in defaults.items():
        value = result[key]
        if isinstance(default, (list, dict)) and isinstance(value, str):
            value = json.loads(value)
            result[key] = value
        if isinstance(default, bool) and not isinstance(value, bool):
            raise ValueError(f"{key} 需要布尔值")
        if isinstance(default, (list, dict)) and not isinstance(value, type(default)):
            raise ValueError(f"{key} 的配置格式错误")
    return result
