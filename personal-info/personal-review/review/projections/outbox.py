"""为 Mem0、Google Tasks 等非权威投影提供可重试回执 outbox。"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from review.state import StateRepository


class ProjectionOutbox:
    """读取、确认和重试投影操作，避免把待办误报成成功。"""

    EXTERNAL_ID_REQUIRED = {"mem0", "google_tasks"}

    def __init__(self, state: StateRepository, policy: dict | None = None) -> None:
        """绑定状态库和退避策略。"""

        self.state = state
        projection_policy = (policy or {}).get("projections", {})
        self.retry_max = int(projection_policy.get("retry_max", 5))
        self.backoff_minutes = int(projection_policy.get("retry_backoff_minutes", 30))

    def pending(self, destination: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """返回首次待执行和已到退避时间的失败操作。"""

        now = datetime.now().astimezone().isoformat()
        sql = (
            "SELECT * FROM projection_outbox WHERE "
            "(status='pending' OR (status='failed' AND attempts<? AND (next_attempt_at IS NULL OR next_attempt_at<=?)))"
        )
        params: list[Any] = [self.retry_max, now]
        if destination:
            sql += " AND destination=?"
            params.append(destination)
        sql += " ORDER BY id LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with self.state.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._public_row(row) for row in rows]

    def get(self, operation_id: int) -> dict[str, Any]:
        """读取一个操作，供本地 worker 应用和校验。"""

        with self.state.connect() as connection:
            row = connection.execute("SELECT * FROM projection_outbox WHERE id=?", (operation_id,)).fetchone()
        if not row:
            raise ValueError("投影操作不存在")
        return self._public_row(row)

    def complete(
        self,
        operation_id: int,
        success: bool,
        error: str | None = None,
        external_id: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按真实回执完成或失败操作；失败会进入指数退避重试。"""

        with self.state.connect() as connection:
            row = connection.execute("SELECT * FROM projection_outbox WHERE id=?", (operation_id,)).fetchone()
            if not row:
                raise ValueError("投影操作不存在")
            if row["status"] == "completed":
                if success and (not external_id or external_id == row["external_id"]):
                    return self._public_row(row)
                raise ValueError("投影操作已经完成，拒绝冲突回执")
            destination = str(row["destination"])
            if success:
                if destination in self.EXTERNAL_ID_REQUIRED and not str(external_id or "").strip():
                    raise ValueError(f"{destination} 成功回执必须包含 external_id")
                now = datetime.now().astimezone().isoformat()
                safe_receipt = self._safe_receipt(receipt or {})
                cursor = connection.execute(
                    "UPDATE projection_outbox SET status='completed',completed_at=?,failed_at=NULL,next_attempt_at=NULL,"
                    "external_id=?,receipt_json=?,error=NULL WHERE id=? AND status!='completed'",
                    (now, external_id, json.dumps(safe_receipt, ensure_ascii=False), operation_id),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError("投影操作状态竞争，请重新读取")
                payload = json.loads(row["payload_json"])
                if destination == "google_tasks":
                    self._upsert_task_mapping(connection, row["idempotency_key"], payload, str(external_id))
                return {"id": operation_id, "status": "completed", "external_id": external_id}
            attempts = int(row["attempts"] or 0) + 1
            now_dt = datetime.now().astimezone()
            delay = self.backoff_minutes * (2 ** max(0, attempts - 1))
            next_attempt = now_dt + timedelta(minutes=min(delay, 24 * 60))
            safe_error = f"{type(error).__name__}: {error}" if error and not isinstance(error, str) else str(error or "")
            connection.execute(
                "UPDATE projection_outbox SET status='failed',attempts=?,failed_at=?,next_attempt_at=?,error=? WHERE id=?",
                (attempts, now_dt.isoformat(), next_attempt.isoformat(), safe_error[:500], operation_id),
            )
            return {"id": operation_id, "status": "failed", "attempts": attempts, "next_attempt_at": next_attempt.isoformat()}

    def retry(self, operation_id: int) -> dict[str, Any]:
        """由人工显式解除退避，但不重置失败次数。"""

        with self.state.connect() as connection:
            row = connection.execute("SELECT status,attempts FROM projection_outbox WHERE id=?", (operation_id,)).fetchone()
            if not row:
                raise ValueError("投影操作不存在")
            if row["status"] != "failed":
                raise ValueError("只有 failed 投影可以重试")
            if int(row["attempts"]) >= self.retry_max:
                raise ValueError("投影已达到最大重试次数，需要人工处理")
            connection.execute(
                "UPDATE projection_outbox SET status='pending',next_attempt_at=NULL WHERE id=?", (operation_id,)
            )
        return {"id": operation_id, "status": "pending"}

    def observe_task(
        self,
        mapping_key: str,
        external_id: str,
        title: str,
        status: str,
        occurred_at: datetime,
    ) -> dict[str, Any]:
        """记录 Tasks 当前状态；completed 只能成为后续日报候选。"""

        if status not in {"pending", "completed"}:
            raise ValueError("Task 状态只能是 pending 或 completed")
        event_key = hashlib.sha256(
            f"{external_id}\0{status}\0{occurred_at.isoformat()}".encode("utf-8")
        ).hexdigest()[:20]
        now = datetime.now().astimezone().isoformat()
        with self.state.connect() as connection:
            mapping = connection.execute(
                "SELECT mapping_key FROM task_mappings WHERE mapping_key=? AND external_id=?",
                (mapping_key, external_id),
            ).fetchone()
            if not mapping:
                raise ValueError("Task 观察记录与投影映射不一致")
            connection.execute(
                "UPDATE task_mappings SET status=?,updated_at=? WHERE mapping_key=?",
                (status, now, mapping_key),
            )
            connection.execute(
                "INSERT OR IGNORE INTO task_events(event_key,mapping_key,external_id,title,status,occurred_at,observed_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (event_key, mapping_key, external_id, title.strip(), status, occurred_at.isoformat(), now),
            )
        return {"event_key": event_key, "status": status}

    @staticmethod
    def _safe_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
        """只保留非敏感、可审计的外部回执字段。"""

        allowed = {"status", "resource_id", "parent_id", "updated_at", "provider"}
        return {key: str(value)[:240] for key, value in receipt.items() if key in allowed and value is not None}

    @staticmethod
    def _public_row(row: Any) -> dict[str, Any]:
        """输出不含内部错误正文以外敏感信息的操作视图。"""

        return {
            "id": row["id"],
            "destination": row["destination"],
            "idempotency_key": row["idempotency_key"],
            "payload": json.loads(row["payload_json"]),
            "status": row["status"],
            "attempts": int(row["attempts"] or 0),
            "next_attempt_at": row["next_attempt_at"],
            "external_id": row["external_id"],
        }

    @staticmethod
    def _upsert_task_mapping(connection: Any, fallback_key: str, payload: dict[str, Any], external_id: str) -> None:
        """保存 Google Tasks 外部 ID，使父子关系和状态回流可验证。"""

        mapping_key = str(payload.get("mapping_key") or fallback_key)
        parent_external_id = None
        parent_key = payload.get("parent_mapping_key")
        if parent_key:
            parent = connection.execute(
                "SELECT external_id FROM task_mappings WHERE mapping_key=?", (str(parent_key),)
            ).fetchone()
            if not parent:
                raise ValueError(f"父任务尚未同步：{parent_key}")
            parent_external_id = str(parent["external_id"])
        now = datetime.now().astimezone().isoformat()
        connection.execute(
            "INSERT INTO task_mappings(mapping_key,kind,external_id,parent_external_id,memo_name,cycle_id,goal_id,title,status,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(mapping_key) DO UPDATE SET "
            "external_id=excluded.external_id,parent_external_id=excluded.parent_external_id,status=excluded.status,updated_at=excluded.updated_at",
            (
                mapping_key, str(payload.get("kind", "task")), external_id, parent_external_id,
                payload.get("memo_name"), payload.get("cycle_id"), payload.get("goal_id"),
                str(payload.get("title", "")), "pending", now,
            ),
        )
