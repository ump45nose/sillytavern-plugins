> 历史设计／验收记录。2026-10-15 起来源范围已收窄，本文中的已移除来源和开发要求不再执行。当前范围见 [来源清理计划](plans/2026-10-15-source-cleanup.md)。

# 采集加工 M0/M1 实施记录

日期：2026-10-11。状态：M1 服务端实现、隔离检查、运行发布与历史回填通过；用户报告客户端开发完成。本对话没有另行操作或验证 Mac。后续推进见 [M2 实施记录](collection-m2-validation.md)。

## 本轮范围

先落实 Memos/日报的阅读链路及加工运行底座。Hermes 执行记录有独立文档变体，默认不混入主阅读列表；不将执行日志当成日报正文。未新增用户问卷、记忆写入、长期分析、新 MCP 工具或 Bot 推送。

用户在执行时明确调整：手机采集放在分析模块完成后，作为增量功能，不阻塞当前采集验收。NAS 首批为 Emby 和 Navidrome。接入模板仍为草案，待现有来源完整交付后冻结。

## 已实现

- `processing/`：独立阅读契约、注册 profile、附加表迁移、任务及依赖、文档加工、读取检索与后台执行。原件 ID、源哈希、墓碑和附件归属保持。
- 真实内容变更在 `Store.ingest` 原事务中入队；重复观察不重算。传入 connection 的路径同样有队列事务保证。删除同步撤下正文、摘要、检索和依赖；发布检查输入哈希、目标代数、租约和 profile 版本。
- 文档识别标题、日报日期、标签、空正文及附件，正文原样分块；源端 NUL 只在阅读副本替换并注明，归档不变。短摘录不冒充摘要。
- 正文分页绑定 revision，变更返回 409，删除返回 404；每页正文最多 256 KiB。全文匹配覆盖分块边界，返回命中片段和分块位置。过期正文不进入搜索结果。列表使用实时 keyset 分页，未知发生时间保留为空。
- 五个内部只读接口：`contents` 列表、详情、blocks、evidence，以及 `processing/status`。沿用现有 writer/viewer 鉴权；没有增加公开加工写接口。
- `hub rebuild-content` 按稳定 ID 分批回填；`hub process-pending` 有界执行；`hub processing-status` 展示加工状态、失败及来源覆盖。备份纳入加工表。
- 现有 scheduler 增加独立单进程加工通道；启动时补缺失历史任务，随后仅在队列可执行时启动 drain，采集槽位不被占用。`processing_enabled=false` 可停加工执行，变更入队和删除撤回仍保留。`processing_backfill_on_start=false` 可关闭启动回填。
- 按用户最新分工撤回本轮 Mac 代码与 Swift 测试改动；提供 [M1 客户端开发需求](client-requirements/m1-document-reading.md) 和合成 API 样例，供用户在 Mac 独立实现。

## 验证证据

| 检查 | 结果及限制 |
| --- | --- |
| `checks/processing-test.py` | SQLite 17 项场景，16 通过，真实 PostgreSQL 并发发布/删除场景在 SQLite 跳过 |
| `HUB_PROCESSING_TEST_POSTGRES=1 .venv/bin/python checks/processing-test.py` | 真实 PostgreSQL 17 项全部通过；每项在随机 `hub_processing_test_*` schema 中运行并清理，使用独立锁域，不操作生产来源表 |
| 生命周期覆盖 | 长正文、跨块搜索、版本续页、重复去重、修改/删除与旧 Worker、过期租约、并发领取、失败恢复、账户隔离、传入事务回退、kind 变更、历史回填、备份、迁移幂等、接口鉴权和大小边界 |
| 调度覆盖 | 单一加工通道、一次启动回填、空队列不反复创建进程；单个采集槽位仍能独立工作 |
| 既有回归 | `display-smoke.py`、`query-status-smoke.py`、`unattended-collection-test.py` 均通过 |
| 真实样本隔离验证 | 复制全部 236 条 Memos 和 32 条最长 Hermes 执行记录到临时环境；268 个对象加工成功，35 篇日报、201 条普通笔记、32 条执行记录；核对 1,162,212 字正文及 153 个附件引用，没有源端写入或模型调用 |
| Mac | 用户指定本对话不操作客户端；本轮 Mac 改动已撤回，实现与真机验收由用户承担，不能视为客户端已交付 |

真实样本只在临时环境使用，未将正文、附件或访问凭据写入仓库。样本检查保证传输与原文一致，不代替用户阅读体验验收。

## 运行与发布边界

此前实现候选阶段未发布；本次按用户“只做服务端”的分工已完成服务端发布：正式 `mcp/compose.yaml` 只更新 CRM 镜像为 `local/personal-data-hub:0.4.0-reading-m1-20261011-v2`，并重启既有宿主采集与 webhook 服务。容器用户、数据挂载、网络、认证文件和其他运行容器 ID 核对保持。开机检查为 missing=[]、active_unplanned=[]、stopped_planned=[]。

迁移前保存私有 Compose、镜像及加工表快照到 `/home/yuwk/.config/personal-data-hub/releases/reading-m1-20261011/`。上线检查发现此前采集进程创建的早期表缺少业务日期及搜索列；已增加 migration 2，并用 SQLite/真实 PostgreSQL 验证只迁移加工表、原件哈希保持。新列补齐后，受影响的派生产物重算。

历史回填和单 Worker drain 已启用。真实 viewer token 在原 HTTPS 入口可读取加工状态和新列表，未授权请求返回 401；原来源接口仍正常。历史任务积压与失败单独登记，不代表数据已全部阅读就绪。客户端源码改动已撤回，本轮没有 Mac 构建、安装或授权操作。

线上阅读探针进一步核对 Memos 与 Hermes 正文、附件引用及输入哈希：正文与原始内容一致，依据的 current_matches 为 true；附件下载 SHA-256 与归档 ID 匹配。41,259 字的 Hermes 记录以 limit=1 分六页读取，拼回正文一致；错误 revision 返回 409。探针不输出私有正文或凭据，也不修改来源记录。

回退保留已采集新事实及删除清理能力，不恢复旧数据库快照来撤销新原件。Mac 客户端需求由用户独立实施，不再以远程工作台认证作为服务端阻塞。

针对指定来源回填和诊断：

```bash
.venv/bin/hub rebuild-content --source memos
.venv/bin/hub process-pending --limit 50
.venv/bin/hub processing-status
```

`rebuild-content` 默认扫描所有批次，`--limit` 是单事务批量大小；`--one-page --after <id>` 用于受控续扫。`--force` 重新整理已有内容，不改变原件。Worker 失败会退避重试，连续失败达到 5 次后需修复原因并显式重建；执行状态不能冒充来源覆盖或用户阅读验收。

## 继续顺序

1. 完成 M1 服务端发布、历史回填与真实鉴权读取，交付 Mac 接口/阅读需求。
2. 继续 M2 微信归组、原消息阅读和加工生命周期；客户端需求在对应节点追加，不等待本对话执行 Mac 构建。
3. 整体采集侧验收仍需用户提供 Mac 联调结果。记忆/分析/MCP 保持后续阶段；NAS 首批为 Emby 和 Navidrome，手机在分析完成后再做。
