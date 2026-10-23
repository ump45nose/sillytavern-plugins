# CRM 人物与交互归档验收

2026-10-15 完成人物、交互、私聊增量归档、HTTP / MCP 读写及既有消费者切换。没有新增表现界面。

## 当前使用入口

- HTTP：`https://crm-home.172906573.xyz/api/v1/crm`。
- MCP：沿用 `https://crm-home.172906573.xyz/mcp` 及既有 OAuth 注册身份；若客户端仍显示旧工具，刷新工具清单。
- API Bearer 可写；原 viewer 凭据只读。没有升级只读权限。
- 读写与附件续传示例：[使用说明](../apps/crm/docs/usage.md)。

## 2026-10-15 迁移对账

| 项目 | 结果 |
| --- | ---: |
| 有效人物 | 78 |
| 私聊消息 | 14,143 |
| 有内容的手工记录 | 1 |
| 分段后交互 | 1,298 |
| 排除的群聊或泛化空内容记录 | 13,773 |
| 已取得并保留的附件文件 | 43 |

14,143 条迁移消息逐条与最终归档正文比较，未发现缺失或差异。43 个已有文件均存在，大小与元数据一致。缺少文件的附件仍保留元数据和稳定引用，读取返回 `available=false`；后续取得文件后补齐，不重写正文。

旧表和旧 Hub 历史镜像没有物理删除。新业务只写 `crm_*`，不再生成 Hub 自我镜像；来源清理与历史删除仍是不同操作。

## 实测证据

- 本地 `pytest apps/crm/tests`：32 passed；NAS 较新主线集成后的完整 CRM 测试：31 passed。覆盖多人共享、合并改绑、编辑追加、删除去重、30 分钟边界、跨日跨批、配置变更、迟到消息、时区、搜索分页、附件及权限。
- PostgreSQL 临时 schema：归档/迁移/接口测试通过；最后新增的共享附件 GC 回归单独通过。临时 schema 用后删除，不在生产业务表放测试样例。
- `checks/daily-push-smoke.py`：通过。日报改读新交互，保留健康/财务口径、分页、已发布报告快照和身份限制。测试中的跨身份拒绝日志是预期结果。
- 实际运行服务：HTTP 人物/多人交互 CRUD、viewer 禁写、匿名拒绝、附件上传下载、MCP 查询及写删均通过；测试记录已清理。
- 真实微信链路：MacAir 原签名后台入口读取 2 秒窗口中的 1 条私聊，实际 POST 新批量入口；服务器识别为已迁移消息，返回 duplicates=1、accepted=0、errors=[]。随后通过 MCP 读出对应交互并比对真实正文。没有为验证修改来源身份或补抓历史。
- 真实采样暴露了空会话遍历问题；跳过 message_count=0 的会话后，同一采样从 90 秒超时降至 12.07 秒。缺少该字段的会话仍正常读取。
- 两台设备恢复原任务后成功水位继续推进。没有额外创建人物、扫描通讯录或启动全量回填。
- 共享附件使用既有分片文件布局。上传与清理共用文件写锁；删除 Hub 记录后，仍被 CRM 引用的文件可正常读取。
- Wheel 构建通过；包含新归档及 004 迁移，不包含已移除的提醒、指标、Fact 与旧业务仓储。
- 最终服务健康检查及公网 `/healthz` 返回 200。公网直连探测超时，本机经既有网络代理访问成功；容器内公开域名探测曾连接失败，未将其当作应用失败或权限问题。

## 部署与恢复位置

NAS 当前镜像：`local/personal-data-hub:crm-readable-20261016-r2`，CRM 包版本 `0.2.1`。服务仍为 `personal-crm-crm-1`，复用原 PostgreSQL、OAuth 状态、附件卷及共享 Compose。

2026-10-16 的姓名/发言人/附件修复来自独立仓库 `ump45nose/personal-crm`。本仓库只增加打包器的 `--connector-source` 入参，用独立来源更新签名包，不再要求复制 CRM 源码回来。MacAir / MacPro 已安装并继续成功增量轮询。归档更新 76 个人物、1,091 条聊天，重跑零变更；附件补齐 1,319 条，当前 1,450 条元数据中 1,362 个文件实际存在，88 条缺少本地原文件、消息或定位。真实 HTTP 附件下载及 MCP/HTTP 正文比对通过。

本轮发布目录 `/home/yuwk/.config/personal-data-hub/releases/crm-readable-20261016` 保留宿主兼容构建及变更前 Compose；受影响文本字段备份位于 `/vol1/1000/personal-data-hub/backups/crm-readable-20261016`。原始迁移与备份如下：

- 发布目录：`/home/yuwk/.config/personal-data-hub/releases/crm-person-20261015`。包含候选 wheel、Dockerfile、原镜像记录、迁移报告及 `rollback.py`。
- 备份：`/vol1/1000/personal-data-hub/backups/crm-person-20261015/database.dump`，1,127,255,946 字节；`pg_restore` 可列出 245 个目录项。原 Compose 与私有配置同目录备份。
- 回退脚本仅恢复原 CRM 镜像及 CRM 来源配置，不覆盖数据库或其他并行配置变更。回退不等于删除新系统写入的数据。
- MacAir 与 MacPro 均通过 `apps/mac-client/update-wechat.py` 更新采集资源，保留原界面二进制、签名身份、获准助手、launchd 入口、checkpoint 和媒体队列。
- 各设备旧应用与任务配置在 `~/Library/Application Support/PersonalDataHub/backups/crm-collector-*`；其他采集任务未重启。
- 已发布聊天报告保持原内容；只对切换前已完成历史分段建立事件基线，避免把迁移历史重新推送。

## 源码与主线边界

Mac 本地：`.worktree/crm-person-design`，分支 `codex/crm-person-design`，基于本地 `1a11e68`。
NAS：聚合仓库 `/home/yuwk/code` 的 `.worktree/crm-person-archive/personal-data-hub`，分支 `codex/crm-person-archive`，基于 `57c5b99`。NAS 的来源清理和加工代码较新，集成时保留了这些变化。

生产原镜像与 NAS 当前源码并非同一版本，因此本次使用原运行镜像叠加 CRM 改动，未顺带上线新的来源策略或其他加工系统，也未用旧本地根包覆盖 NAS 新源码。后续发布完整源码时，应按现有来源清理文档处理候选配置。

两个独立分支保留实现检查点；没有合并或推送主线。主工作树的其他修改保持原归属。
