# 嘉颖连续生活与陪伴 cron

源码归属：确定性素材同步、30 天历史、执行刷新与聊天 hook 在 `hermes/companion_*.py`；筛选改编、生活规划与任务生成在 `model/companion_*.py` 和 `model/lingjun-companion-generator.py`。Hermes 内核不新增调度器或记忆系统。

数据流：Favsync 既有小红书账号 → 作者缓存与 CPU OCR → 独立只读素材 API → Profile 私有素材库 → 模型筛选 → 日期唯一的生活计划 → 4–6 个单次任务。每日 23:30 规划次日，09:00–22:30 投递，间隔至少两小时，独立随机 75% 自拍。排程按间隔预留空间后抽样，确保选出目标数量。动作和画面来自当日活动，不再使用固定关心模板与场景表。

不足四条的旧日计划可在剩余窗口内补齐：保留原时段、索引、任务 ID 和已激活的生活进度，仅追加分享角度，不再推进当天活动。补充时段预留至少十五分钟供规划与创建；剩余时间不够时明确失败，不回填过去时段。四至六条指排程数量，执行前仍可能因重复话题、明确拒绝或信息不足而静默。

三条生活线为相册整理、做菜练习、摄影与城市散步。一天最多推进一条，计划与实际激活分开：未来计划不会提前变成当前事实，当天由执行刷新或聊天 hook 激活一次。`plans.day`、`applied_days.day`、`events.name` 唯一；任务重跑复用已存计划及 Hermes 任务名称。暂停活动不会被当天计划覆盖。

正文、来源、OCR、原帖链接和前后关系保存在 Lingjun 私有 `companion/state.sqlite3`。出处不进入角色聊天上下文；角色生活不写入人类用户 USER.md、Mem0 或 shared-state。嘉颖身份和外貌继续由现有 SOUL 与 profile_selfie 参考图决定。

筛选按具体行动、过程与结果去重，排除广告、商品卖点、纯摆拍和空泛感慨。改编只调整身份、地点与时机，保留素材中的具体过程和结果；不把正常成功统一改成翻车，也不凭空增加补救和丢东西的桥段。待续内容是未来意向。素材更新可以重新整理未使用且未预约的条目，已经进入日计划或生活状态的经历保持稳定。

历史只读 Lingjun `state.db` 内精确匹配 Telegram owner/chat/topic 13429 的用户、助手正文，另联结对应 cron 输出、`executions.db` 与 `deliveries.db`。投递分 delivered、failed、silent、pending、unconfirmed；终态 journal 缺失的旧输出保守记待确认，成功执行不等同已投递。镜像不算用户回应。已送达活动主题/场景记录进生活状态，明确活动拒绝/恢复与相关用户回应也保存到私有状态。

历史最多 8,000 token：能容纳时保留完整 30 天，否则最多 6,000 近期原文与 2,000 跨日摘录摘要。额外上下文总量最多 12,000，并受部署配置中的模型窗口减去系统、工具与输出预留限制；窗口取自 Hermes 当前路由的模型元数据，缺少精确条目时采用保守配置。执行 prompt 不冻结历史，只有 `companion_pre_run.py` 刷新的一个上下文。普通聊天 hook 使用较小的 2,000 token / 8,000 字符上限，严格匹配 Profile、用户与话题。

素材接口只读缓存，失效时使用现有缓存；素材不足延续待续活动，没有可用进展则静默。历史数据库、任务清单或投递日志不可可靠读取时，预运行脚本记录运维错误并以成功、空 stdout 返回，Hermes 不启动消息模型。图片失败也要求静默，不投递运维信息。

## 安装

私有 `hermes.local.json` 的 `companion` 配置参照 `local.example.json`；素材令牌只保存在 Profile 的 `companion/materials.token`。模型 helper 使用 Hermes 的 Profile 密钥作用域，固定既有 CPA/grok 路由，不复制凭据或改用其他模型。

```bash
python3 deploy-hermes.py \
  --only hermes/companion_runtime.py \
  --only hermes/companion_pre_run.py \
  --only hermes/companion_chat_hook.py \
  --only model/companion_llm.py \
  --only model/companion_planner.py \
  --only model/lingjun-companion-generator.py
```

仅选中的源文件和对应 manifest 薄包装会被更新，其他修改不会安装。Profile `hooks.pre_llm_call` 注册 `<Hermes源码>/venv/bin/python <profile>/scripts/companion_chat_hook.py`，timeout 15；只允许这一条可信 hook，不启用全局 auto_accept。生成器也复用这一解释器及其 SQLite。配置修改后更新 Lingjun Gateway。

`--prepare-materials` 只同步和筛选缓存；`--dry-run` 做规划预览，不保存日计划、推进活动或创建任务。两者可能更新素材缓存。检验近 14 天至少 14 条独立可用素材、7 条未使用且未预约的储备，以 `inventory` 为准，不以原帖数量为准。

## 验证与回退

只允许相关静态/导入检查和单路径业务冒烟；不新增或默认执行自动化测试套件，默认不发送试验陪伴消息。用户明确要求时可通过原生 cron 执行并核对投递终态。验证 OCR、接口鉴权、30 天范围/投递分类、规划预览、重复运行唯一性与聊天 hook 上下文。部署后执行既有 `container-boot.py --check`。

回退先关闭私有 `companion.enabled` 和 Favsync `xhs_creators.enabled`，移除指定聊天 hook；恢复部署前备份的旧生成器。只对陪伴任务清除新增 pre-run 脚本，并用旧生成器重建未来提示词；不要用整个旧 jobs.json 覆盖其他任务的新状态。Favsync 保留增量表和支持当前 schema 的镜像，不降低 SQLite user_version 或删表。素材缓存与生活状态保留，以便恢复。
