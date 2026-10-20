-- 已处于 001_initial 的 SQLite 数据库升级脚本；执行前使用 SQLite backup API 备份。
-- 正常部署使用 alembic upgrade head；本文件保留可审计的等价 SQL，不重复执行。
BEGIN IMMEDIATE;
ALTER TABLE interactions ADD COLUMN source_message_key VARCHAR(64);
CREATE UNIQUE INDEX uq_interaction_source_message
    ON interactions (source_type, source_message_key);
CREATE TABLE sync_clients (
    source VARCHAR(80) NOT NULL,
    client_id VARCHAR(80) NOT NULL,
    last_batch_id VARCHAR(36),
    synced_through DATETIME,
    last_seen_at DATETIME NOT NULL,
    accepted_total INTEGER NOT NULL,
    duplicate_total INTEGER NOT NULL,
    PRIMARY KEY (source, client_id)
);
UPDATE alembic_version SET version_num = '002_sync_clients'
    WHERE version_num = '001_initial';
COMMIT;
