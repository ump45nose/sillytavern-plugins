"""SQLite 运行状态仓库；不保存人工历史账本。"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import fcntl
import threading
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS checkpoints (
  source TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
  scope TEXT NOT NULL,
  key TEXT NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(scope, key)
);
CREATE TABLE IF NOT EXISTS review_sessions (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  status TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  prepared_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  final_content TEXT,
  memo_name TEXT,
  material_text TEXT,
  material_json TEXT
);
CREATE TABLE IF NOT EXISTS pending_checkpoints (
  session_id TEXT NOT NULL,
  source TEXT NOT NULL,
  value TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  prepared_at TEXT NOT NULL,
  committed_at TEXT,
  delivery_id TEXT,
  PRIMARY KEY(session_id, source)
);
CREATE TABLE IF NOT EXISTS stage_cycles (
  id TEXT PRIMARY KEY,
  starts_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  status TEXT NOT NULL,
  summary_memo TEXT
);
CREATE TABLE IF NOT EXISTS mainlines (
  domain TEXT PRIMARY KEY,
  memo_name TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stage_goals (
  id TEXT PRIMARY KEY,
  cycle_id TEXT NOT NULL REFERENCES stage_cycles(id),
  domain TEXT NOT NULL,
  memo_name TEXT,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projection_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  destination TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  completed_at TEXT,
  failed_at TEXT,
  next_attempt_at TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  external_id TEXT,
  receipt_json TEXT,
  error TEXT,
  UNIQUE(destination, idempotency_key)
);
CREATE TABLE IF NOT EXISTS task_mappings (
  mapping_key TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  external_id TEXT NOT NULL,
  parent_external_id TEXT,
  memo_name TEXT,
  cycle_id TEXT,
  goal_id TEXT,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
  event_key TEXT PRIMARY KEY,
  mapping_key TEXT,
  external_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence_fingerprints (
  fingerprint TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  session_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_id TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  source_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  memo_name TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  error TEXT,
  UNIQUE(message_id, sha256)
);
"""


def serialized(method):
    """Serialize service side effects across the HTTP server and CLI processes."""
    @wraps(method)
    def invoke(self, *args, **kwargs):
        with self.state.operation():
            return method(self, *args, **kwargs)
    return invoke


class StateRepository:
    """以事务方式管理 checkpoint、会话和投影 outbox。"""

    def __init__(self, path: str | Path) -> None:
        """记录数据库路径，实际连接在每次操作时创建。"""

        self.path = Path(path)
        self._operation_mutex = threading.RLock()
        self._operation_local = threading.local()

    @contextmanager
    def operation(self):
        """Hold one reentrant process-shared lock across Memos and local receipts."""
        with self._operation_mutex:
            if getattr(self._operation_local, 'active', False):
                yield
                return
            with self.path.with_suffix('.write.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self._operation_local.active = True
                try:
                    yield
                finally:
                    self._operation_local.active = False
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def initialize(self) -> None:
        """创建父目录及运行状态表。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_columns(connection)

    @staticmethod
    def _migrate_columns(connection: sqlite3.Connection) -> None:
        """为既有状态库补充非破坏列，保证原地升级可重复执行。"""

        existing = {row[1] for row in connection.execute("PRAGMA table_info(projection_outbox)").fetchall()}
        additions = {
            "failed_at": "TEXT",
            "next_attempt_at": "TEXT",
            "attempts": "INTEGER NOT NULL DEFAULT 0",
            "external_id": "TEXT",
            "receipt_json": "TEXT",
        }
        for name, declaration in additions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE projection_outbox ADD COLUMN {name} {declaration}")
        session_columns = {row[1] for row in connection.execute("PRAGMA table_info(review_sessions)").fetchall()}
        if "material_text" not in session_columns:
            connection.execute("ALTER TABLE review_sessions ADD COLUMN material_text TEXT")
        if "material_json" not in session_columns:
            connection.execute("ALTER TABLE review_sessions ADD COLUMN material_json TEXT")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """打开带 Row 返回和事务语义的 SQLite 连接。"""

        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def checkpoint(self, source: str) -> str | None:
        """读取来源最后一次成功 checkpoint。"""

        with self.connect() as connection:
            row = connection.execute("SELECT value FROM checkpoints WHERE source=?", (source,)).fetchone()
        return str(row["value"]) if row else None

    def commit_checkpoint(self, source: str, value: str) -> None:
        """仅在来源处理成功后原子推进 checkpoint。"""

        now = datetime.now().astimezone().isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO checkpoints(source,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(source) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (source, value, now),
            )

    def commit_checkpoints(self, values: dict[str, str]) -> None:
        """在材料包成功冻结后一次性推进全部来源 checkpoint。"""

        if not values:
            return
        now = datetime.now().astimezone().isoformat()
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO checkpoints(source,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(source) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                [(source, value, now) for source, value in values.items()],
            )

    def stage_checkpoints(self, session_id: str, values: dict[str, str]) -> int:
        """把本次材料对应游标暂存为 pending，投递确认前不影响后续采集。"""

        if not values:
            return 0
        now = datetime.now().astimezone().isoformat()
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO pending_checkpoints(session_id,source,value,status,prepared_at,committed_at,delivery_id) "
                "VALUES(?,?,?,'pending',?,NULL,NULL) ON CONFLICT(session_id,source) DO UPDATE SET "
                "value=excluded.value,status='pending',prepared_at=excluded.prepared_at,committed_at=NULL,delivery_id=NULL",
                [(session_id, source, value, now) for source, value in values.items()],
            )
        return len(values)

    def acknowledge_checkpoints(self, session_id: str, delivery_id: str) -> dict[str, Any]:
        """收到稳定投递标识后原子提交该材料的全部 pending checkpoint。"""

        delivery = str(delivery_id or "").strip()
        if not delivery:
            raise ValueError("delivery_id 不能为空")
        now = datetime.now().astimezone().isoformat()
        with self.connect() as connection:
            # 先取得写锁，避免两个投递回执同时读取 pending 后重复竞争提交。
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT source,value,status,delivery_id FROM pending_checkpoints WHERE session_id=? ORDER BY source",
                (session_id,),
            ).fetchall()
            if not rows:
                raise ValueError("该会话没有待确认 checkpoint")
            pending = [row for row in rows if row["status"] == "pending"]
            if not pending:
                existing = {str(row["delivery_id"] or "") for row in rows}
                # refresh 可能只重开部分来源，因此同一会话可保留早期来源的旧回执。
                if delivery in existing:
                    return {"session_id": session_id, "status": "already-acknowledged", "committed": 0}
                raise ValueError("checkpoint 已由另一 delivery_id 确认")
            connection.executemany(
                "INSERT INTO checkpoints(source,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(source) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                [(row["source"], row["value"], now) for row in pending],
            )
            connection.execute(
                "UPDATE pending_checkpoints SET status='committed',committed_at=?,delivery_id=? "
                "WHERE session_id=? AND status='pending'",
                (now, delivery, session_id),
            )
        return {"session_id": session_id, "status": "acknowledged", "committed": len(pending)}

    def pending_checkpoint_batch(self, session_id: str) -> dict[str, Any]:
        """返回会话待确认游标数量和最新暂存时间，不暴露游标正文。"""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total,"
                "SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,"
                "MAX(CASE WHEN status='pending' THEN prepared_at END) AS latest_prepared_at "
                "FROM pending_checkpoints WHERE session_id=?",
                (session_id,),
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "pending": int(row["pending"] or 0),
            "latest_prepared_at": row["latest_prepared_at"],
        }

    def record_evidence(self, session_id: str, items: list[Any]) -> None:
        """记录已冻结证据指纹，供重复同步和审计使用，不保存新的事实正文。"""

        now = datetime.now().astimezone().isoformat()
        with self.connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO evidence_fingerprints(fingerprint,source,occurred_at,first_seen_at,session_id) "
                "VALUES(?,?,?,?,?)",
                [(item.evidence_id, item.source, item.occurred_at.isoformat(), now, session_id) for item in items],
            )

    def get_idempotent(self, scope: str, key: str) -> dict[str, Any] | None:
        """读取已经完成的副作用结果。"""

        with self.connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM idempotency WHERE scope=? AND key=?", (scope, key)
            ).fetchone()
        return json.loads(row["result_json"]) if row else None

    def put_idempotent(self, scope: str, key: str, result: dict[str, Any]) -> None:
        """记录副作用结果，重复键不会覆盖第一次成功事实。"""

        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO idempotency(scope,key,result_json,created_at) VALUES(?,?,?,?)",
                (scope, key, json.dumps(result, ensure_ascii=False), datetime.now().astimezone().isoformat()),
            )

    def save_session(self, values: dict[str, Any]) -> None:
        """保存冻结的材料包；相同会话只更新生命周期字段。"""

        payload = dict(values)
        payload.setdefault("material_text", None)
        payload.setdefault("material_json", None)
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO review_sessions(
                       id,kind,window_start,window_end,status,evidence_json,prepared_at,expires_at,final_content,memo_name,material_text,material_json
                   ) VALUES(:id,:kind,:window_start,:window_end,:status,:evidence_json,:prepared_at,:expires_at,:final_content,:memo_name,:material_text,:material_json)
                   ON CONFLICT(id) DO UPDATE SET
                     status=CASE
                       WHEN review_sessions.status='finalized' THEN review_sessions.status
                       ELSE excluded.status
                     END,
                     final_content=COALESCE(review_sessions.final_content,excluded.final_content),
                     memo_name=COALESCE(review_sessions.memo_name,excluded.memo_name),
                     material_text=COALESCE(review_sessions.material_text,excluded.material_text),
                     material_json=COALESCE(review_sessions.material_json,excluded.material_json)""",
                payload,
            )

    def refresh_session_material(
        self,
        session_id: str,
        evidence_json: str,
        material_text: str,
        material_json: str,
        prepared_at: str,
    ) -> None:
        """显式 refresh 时替换开放会话材料；普通 prepare 永远不能走此路径。"""

        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE review_sessions SET evidence_json=?,material_text=?,material_json=?,prepared_at=? "
                "WHERE id=? AND status='open'",
                (evidence_json, material_text, material_json, prepared_at, session_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("只有 open 会话可以 refresh")

    def load_session(self, session_id: str) -> sqlite3.Row | None:
        """读取指定复盘会话。"""

        with self.connect() as connection:
            return connection.execute("SELECT * FROM review_sessions WHERE id=?", (session_id,)).fetchone()

    def enqueue_projection(self, destination: str, key: str, payload: dict[str, Any]) -> None:
        """把非权威投影写入幂等 outbox，等待适配器执行。"""

        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO projection_outbox(destination,idempotency_key,payload_json,status,created_at) "
                "VALUES(?,?,?,'pending',?)",
                (destination, key, json.dumps(payload, ensure_ascii=False), datetime.now().astimezone().isoformat()),
            )
