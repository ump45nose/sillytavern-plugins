-- 保存结构化日报材料和内部来源状态，用户 Markdown 只使用 material_text。
ALTER TABLE review_sessions ADD COLUMN material_json TEXT;
