-- 为日报材料增加可重复回放正文，并把 checkpoint 改成投递确认后提交。
ALTER TABLE review_sessions ADD COLUMN material_text TEXT;

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
