-- PostgreSQL 等价迁移；执行前备份。正常部署使用 Alembic upgrade head。
BEGIN;
ALTER TABLE interactions ADD COLUMN IF NOT EXISTS message JSON;
UPDATE alembic_version SET version_num = '003_wechat_messages'
    WHERE version_num = '002_sync_clients';
COMMIT;
