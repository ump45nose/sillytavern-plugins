# 2026-10-15 来源清理集成要求

来源清理与 P1 性能修复已按用户要求完成代码集成，过程和验证见 [合并记录](plans/2026-10-15-integration.md)。本轮没有部署，发布时使用已集成版本及私有配置候选，不单独覆盖 CRM、发布锁或调度文件。

1. 分别用 `deployment/cleanup-source-config.py` 为宿主和容器私有配置生成独立候选。它只移除不再支持的来源条目；不复制密钥到仓库、不改变保留来源的设置和后台暂停状态。
2. 新镜像拒绝含已退出适配器的配置；部署必须使用候选。历史数据库行、任务、水位、附件和 OAuth 状态保留。原系统的独立服务与任务不调整。
3. `deployment/build-image.sh` 不再打包或依赖 usage-monitor-mcp。公共 SDK、认证、镜像基线和既有挂载沿用现有流程。
4. 指定正式 mcp 组的 crm 服务更新；不启动已禁用的轮询/加工，不运行全库回填或旧 collect all。
5. 最终检查保留来源推送、认证查询和工具发现，确认 Memos 日报工具不再发现。Mac 按 [调整清单](client-requirements/source-cleanup.md) 在部署后联调。实际部署后才执行启动登记检查。

本轮范围和验证结果见 [清理计划](plans/2026-10-15-source-cleanup.md)。以下保留的是迁移及历次发布记录，其中已移除来源的旧命令不再执行。

---

# 部署与维护

## 当前 NAS 入口

| 入口 | 管理方式 | 持久化 |
| --- | --- | --- |
| 统一 API / CRM MCP | 正式 `mcp` Compose 项目的 `crm` 服务，保留原容器名、18086 端口及公网 CRM URL | 原 OAuth 卷、统一 PostgreSQL、统一文件卷 |
| Health / AutoAccounting | 原 `health-webhook.service`，保留 8765 端口，使用 `90-personal-data-hub.conf` drop-in | 直接写统一 PostgreSQL |
| 周期采集 | `personal-data-hub-collectors.service` | 统一运行记录、提交水位和附件 |
| ShellCrash 原始计量 | 原 `shellcrash-traffic-collector.service` | 原流量 SQLite；同一生产者 |
| 独立用量 MCP | 原 `usage-monitor-mcp` 服务 | 原用量数据、OAuth 和配置 |

已复用现有 PostgreSQL、网络、Cloudflare 路由、Authelia 和持久卷。没有另建 PostgreSQL 或身份体系。主仓库的 `mcp.app.yaml` 是原 CRM 身份的当前部署清单；独立用量 MCP 的清单仍在 `apps/usage-monitor/`。

私有配置目录为 `/home/yuwk/.config/personal-data-hub`，容器只读配置位于其 `container/` 子目录。`personal-data-hub-assets` 是 `/vol1/1000/personal-data-hub/assets` 的绑定命名卷。生产密码和凭据不放入 Git，不在构建上下文中传递。

宿主采集器以原用户运行。Google 的既有凭据由隔离只读导出进程读取，只返回采集结果；未放宽原凭据目录权限。Plaud 官方 MCP 在专用 Python 环境运行，自有采集入口为 `agents/nas/plaud-sync.py`。邮件适配只调用现有邮件服务容器的只读函数，保留原授权、筛选和附件政策，不修改未读状态。

## 更新

```bash
uv sync --python 3.12 --no-dev
HUB_IMAGE=local/personal-data-hub:0.1.0-stage1 ./deployment/build-image.sh
.venv/bin/mcpctl plan personal-crm --source /home/yuwk/code/personal-data-hub --target nas
.venv/bin/mcpctl deploy personal-crm --source /home/yuwk/code/personal-data-hub --target nas
sudo systemctl restart personal-data-hub-collectors.service health-webhook.service
```

构建复用已锁定的公共 MCP 基础镜像，安装自有 wheel、PostgreSQL 驱动和独立用量库要求的锁定公共事件库。`uv sync` 先填充锁定 Git 缓存；也可通过 `HUB_EVENTS_SOURCE` 指定该事件库源码路径。构建必须通过 `uv pip check`。Docker 命令需当前操作账户已有的权限；若使用 sudo，需保留 `uv` 所在 PATH。既有部署模式复用当前镜像，因此首次切换镜像应先在原 Compose 项目更新 `crm` 服务，再由 `mcpctl` 记录和校验部署，保留其他服务。

观察采集：`hub status`、`systemctl status personal-data-hub-collectors.service`。失败运行的 `error` 字段保存 JSON 字符串，包含错误类别 `type`、安全可读的原因 `reason`；组合异常另存 `causes`，隔离采集也保留这些诊断。日志和诊断不得包含消息正文、邮件内容、凭据或原始响应。`partial` / `segment_invalid` 表示本轮遇到无效片段；归档历史异常数量放在 `quality_warnings`，不会令以后成功的运行一直显示 `partial`。旧运行记录保持原状，不回写历史状态。

周期采集按来源启动独立进程，默认最多 3 个；来源超时默认 900 秒，可用 `run_timeout_seconds` 设置。失败按 30 秒递增退避，最长不超过该来源的正常采集间隔；成功后恢复正常间隔。超时或服务停止会结束整个工作进程组；重启后以来源锁确认旧工作进程已退出，结束遗留的 running 记录再续跑。只有完整采集成功后提交水位，已入库记录按哈希去重，重复内容不重新读正文或生成预览。Google 隔离导出使用 LF 划分 JSONL，保留正文中的 Unicode 行分隔字符。

状态接口按窄列一次汇总来源统计。既有 PostgreSQL 升级时，在事务外补建 `CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_hub_records_source_observed_at ON hub_records (source, observed_at)`，再执行 `ANALYZE hub_records`；新数据库的表定义已含此索引。2026-10-11 生产更新前状态接口实测约 40 秒，更新统计后为 0.04 秒。统计与索引操作保留业务记录和身份。

### 2026 年 10 月采集故障修复

| 故障 | 已确认原因和修复 | 生产证据 |
| --- | --- | --- |
| 电脑活动片段被误判无效 | `splitlines()` 拆开 JSON 字符串内的 Unicode 行分隔符；改用 LF，并按解析器版本重验旧异常 | 自动恢复 16 个片段；后续运行为 ok，9 个缺事件文件的历史记录仍单独告警 |
| 残留 running、一个来源拖住其他来源 | 原调度串行且缺少每来源时限；补上独立工作进程、超时、退避及中断恢复 | Email、Git、Google、Mem0、Plaud、CRM 等来源均在新调度下完成；CRM 全量对账复用 26,942 条记录 |
| 数据库轮询挤占采集资源 | 状态接口逐来源重复扫描，重复入库读取大正文和重建预览 | 一次汇总、联合索引和批量重复记录更新已部署；来源接口与采集均实际完成 |
| Plaud 失败后不再处理 | 云端、融合与摘要的永久单次请求哨兵；任务只处理昨天、只在凌晨运行；回查仅 3 天 | 同一作业改为全天 `run-pending`，持久退避和输入身份缓存；自动发现 10 月 8 日迟到的第三条录音，Groq / SenseVoice 已补到 33 块 |
| Gemini 失败格式和真实时间异常混在一起 | 固定解析器不认识毫秒 SRT；数值请求还会把分秒写为十进制数字；另有真正越界、倒序的时间 | 保存原稿后解析合法 SRT 和单数字分钟；新结构化请求要求明确分秒字符串；真实异常隔离并自动细分重试，复用成功小段和有效响应 |
| 原子产物暂存文件阻止重启恢复 | 固定 `.part` 名称的排他创建在进程中断后永久冲突 | 产物改用独立暂存名称；保留旧暂存证据，同内容可复用，已完成内容仍禁止改写 |
| NAS Grok 后台额度不可用 | 沿 systemd Agent 实际环境复现直连 `ECONNRESET`，原服务未声明代理；CLI 可刷新令牌后报不支持 billing 方法，网页回退原先仍持有刷新前的令牌 | 给受影响 Agent 安装现有 ShellCrash 代理 drop-in；网页回退重读令牌，凭据优先级不变；Hub 18:52、19:37 等自动上传均为 ok |
| Mac Grok 登录过期后不能自动续期 | 原签名桌面应用的启动环境找不到已经安装的 `~/.grok/bin/grok`；访问令牌过期，刷新凭据仍有效 | 原 CLI 成功续期；给原 launchd 启动项增加 `open --env GROK_CLI_PATH=...`，原应用环境已确认收到路径；20:43:46 自动额度状态为 ok，并已归档 |
| 来源异常只有异常类型 | 旧运行未记录底层诊断，无法据此断定旧 RuntimeError 的具体网络或鉴权原因 | 新记录保留脱敏类别、HTTP 状态与原因；邮件桥接也传递安全原因；Google 暂时网络错误自动重试，Git / Mem0 使用配置的出站代理 |

9 个缺失事件文件属于 2026 年 9 月旧片段。NAS 文件和归档修订均缺事件；从已获授权的 Mac 后台链验证原机缓存只剩最近片段，9 个原目录都已轮转。保留缺失记录，不制造空事件或删除告警来冒充恢复。现有 Mac 交付采用闭合快照、组合哈希、暂存提交和 NAS 回执，回执成功后才推进水位。

2026-10-11 18:25，采集服务 active，正式镜像为 `local/personal-data-hub:0.3.6-unattended-20261011-v2`，MCP 部署核对无认证、路由及共享服务变更。来源 API 和健康接口实测 200，计划内 47 个常驻容器无缺失或额外启动。后续已通过原连接的真实 MCP 来源查询。NAS Grok 的代理配置模板为 `deployment/systemd/token-monitor-agent-proxy.conf`，安装到原服务的 `outbound-proxy.conf` drop-in；来源代码沿既有登记例外位于 `/vol2/1000/Docker/token-monitor/app`，只修改 Grok 回退、测试和对应说明。运行环境原凭据保留，受影响源码备份位于私有 `source-backups/20261011-unattended-175317/token-monitor`。Windows ZAI 经用户说明为无会员且赠送额度用尽时不可查询，属于预期账户条件，移出待修故障。

Plaud 的新日期发现限定为最近七个已结束的日历日，已经入队的未完成日期跨窗口仍保留。一次同步同时建立全部待处理日期标记，按最近尝试时间轮转，避免某日失败阻塞其他日期。10 月 5 日的真实全天定时运行已补齐 15 块 Groq、15 块 SenseVoice 和 13 块 Gemini；两个合法单数字分钟响应在解析修正后复用，三源已全部通过覆盖、哈希和时间校验。20:00 定时触发在全局锁占用时安静退出，不重复付费提交。模型融合响应省略说话人标签时，保留原始响应，明确标为未知 `Speaker ?`，不推断身份；时间顺序、范围和录音覆盖仍需通过。20:12:17 已按原运行账户补跑并发布 10 月 5 日完整融合稿和摘要，融合请求 1 次、摘要请求 1 次；其余 10 月 9、10、8、4 日保留在自动队列，后续按实际状态确认。

20:30 原 Hermes 定时任务自行启动，20:32:39 自动接续 10 月 9 日三条录音的处理，未人工触发或选择日期；当前状态为 `processing`。无人值守验收已覆盖自然定时触发、锁占用退出、待处理日期选择和接续；10 月 5 日的完整发布经过同一运行账户验证。四个积压日期全部完成仍以最终 `complete` 产物为准。

Mac 修复入口为 `python3 agents/mac/configure-token-monitor-grok.py --restart`，仅用于已有原启动项和 Grok CLI 的受影响 Mac；脚本在 Application Support 内备份 plist，保留其他字段，并等待应用退出后再启动。实际应用仍是原 Developer ID 签名的 Token Monitor 0.68.0，签名验证通过，未修改包内代码或凭据。固定额度刷新间隔为 300 秒；该签名版仍使用旧的 CLI 回退读法，续期当次可能回退一次旧令牌，后续固定刷新会重读新令牌。NAS 源码已修正这处旧令牌回退，并保存补丁；Mac 此次修复的是导致一直不能续期的启动环境。

验证入口：`.venv/bin/python checks/unattended-collection-test.py`、`checks/collection-errors-test.py`、`checks/plaud-content-smoke.py`，以及 [Plaud 的三个 smoke](../processors/plaud/README.md)。模拟验证覆盖超时后继续处理其他来源、水位保护、孤立运行恢复、缓存、迟到录音、音频尾块、暂存中断和已保存融合响应的无请求恢复。生产 Plaud 积压的后续定时完成记录仍需按运行状态确认，不能以正在处理或草稿作为完成证据。

Token Monitor 的 Grok 相关 47 项测试通过；用锁定依赖在独立源码副本运行 `npm run verify`，lint 通过，5,624 项测试中 5,581 通过、42 失败、1 跳过。将该副本恢复为修复前的 Grok 源码后，失败的五个测试文件仍为相同 42 个失败，未扩展修改既有界面和流式会话问题。外部源码的可复查补丁保存在 `deployment/patches/token-monitor-grok-token-refresh.patch`。

采集异常通知由 `/home/yuwk/code/nas-cron-jobs` 维护，部署到 `/home/yuwk/cron/hermes`，复用 Hermes 定时任务和通知机器人。只推送当前尚未恢复的任务及原因；正常完成后停止报告旧失败，重试开始本身不代表恢复。历史记录和详细诊断留在 Hub 数据库，不随通知展开。

## Mac 同步 Agent

统一应用 0.3.1 起，日常更新使用下文的 `apps/mac-client/install.py`；它打包并迁移已有 Agent。单独的源码 Agent 安装器保留供初始配置维护使用：

```bash
/usr/bin/python3 /Users/yuwk/WorkSpace/Code/github/personal-data-hub/agents/mac/install.py
```

源码安装器复用 `com.yuwk.personal-review-skysight` 和 `com.personal-crm.wechat`。保留原 Python / ChatGPT Node 授权路径、设备身份、白名单和检查点；Skysight 间隔为 900 秒。微信私有 `.env` 放在 Application Support。统一应用安装后改用包内 Python 和采集代码，不再使用仓库虚拟环境；不要交替运行两个安装器切换代码位置。

Mac 先交付稳定闭合文件，再由 NAS 校验组合哈希并提交归档；收到提交回执后才更新水位。计数修复只发生在交付副本，原 metadata 与验证记录同时保存。缓存轮转不产生删除事件。客户端在 `apps/mac-client` 管理，复用这两个 Agent。

2026-10-07 微信采集默认改为全部单聊和群聊，原始消息 JSON 与正文直接归档，Fact 抽取关闭。媒体增量升级后的生产镜像为 `local/personal-data-hub:wechat-media-0a7fe87`，Mac 查看端为 0.3.0 build 7；历史回填、保留的旧记录和媒体文件限制见 [微信采集验收](wechat-faithful-validation.md)。

后续媒体采集的 Mac 依赖在 `agents/mac/wechat-media-requirements.txt` 锁定上游提交，安装器先安装到原 CRM Python 环境，再设置 `WECHAT_MEDIA_ENABLED=true` 和仓库外的 `WECHAT_MEDIA_QUEUE`。只复用既有数据库缓存 key，图片保存原始加密 `.dat`，不提取图片密钥。NAS 需先部署支持微信媒体 PUT 的服务端；升级后重启周期采集器，使正文对账保留附件。保留媒体队列和 spool、正文 checkpoint、设备身份、原 webhook token 与全部持久卷。

## Mac 客户端

`python3 apps/mac-client/install.py` 在已有采集配置的 Mac 构建并安装统一应用 0.3.1 build 9 到 `~/Applications/Personal Data Hub.app`，保留前一版为 `Personal Data Hub.previous.app`，注册登录启动并迁移两个原采集任务。`dist/Personal Data Hub.zip` 是同一签名应用的本机更新包。签名资源包含微信 Python 3.12、依赖、采集代码、固定原生读取器及 Skysight 脚本；私有凭据、数据库、附件、正文水位和媒体队列均不入包。

组件安装前校验签名、哈希及迁移后解释器的 imports，并通过临时 launchd 任务验证真实后台权限链能读取微信目录；验证失败时两个原任务继续运行。运行副本放在 `~/Library/Application Support/PersonalDataHub/Agents/versions/<SHA256>/`。保留原两个 launchd label、设备身份、水位、未来媒体 cutoff 和钥匙串访问助手。微信使用原获准 Python 的真实路径运行简单启动脚本，再启动包内 Python，电脑活动继续使用已授权的 Python / ChatGPT Node；这些外部执行器需保留，不依赖仓库链接。安装前备份原 plist 和停止后的水位到 `PersonalDataHub/backups/collection-app-*`；迁移失败恢复原 plist 及加载状态。登录项注册在采集迁移前完成，避免注册失败留下部分迁移状态。

客户端的 Keychain 凭据和连接设置位于仓库外；关闭窗口后驻留菜单栏，退出界面不停止后台采集。`--agent-bundle-status` / `--login-status` 分别查询组件和登录项；只有 `enabled` 表示界面登录启动已生效，`requiresApproval` 需在系统设置批准。新 Mac 仍需既有配置、固定签名及首次数据权限，公开分发需要另行签名和公证。真机验证见 [统一应用验收](mac-app-bundle-validation.md)。

NAS 在私有配置中增加 `hub_viewer_token_file`。容器目录中的对应文件只读挂载到 `/run/hub`；不替换原 `hub_api_token_file`、Health / 财务 token 或 OAuth。升级服务后执行 `hub backfill-previews` 补齐历史查看字段，新采集自动维护。客户端连接原 HTTPS 公网入口，无新域名或端口。

第二阶段镜像为 `local/personal-data-hub:0.2.0-mac`，原 `personal-crm` Compose 项目只替换 `crm` 服务镜像；新候选清单位于 NAS 私有运行目录的 `releases/personal-data-hub-stage2/compose.yaml`。

2026-10-06 的列表与状态修正已更新至 `local/personal-data-hub:0.2.1-query`，当前候选清单为 `releases/personal-data-hub-0.2.1-query/compose.yaml`。Mac 客户端同步更新为 `0.2.1`；验证见 [列表与状态修正验收](query-status-validation.md)。

展示改造已部署为 `local/personal-data-hub:0.3.0-display`，候选清单为 `releases/personal-data-hub-0.3.0-display/compose.yaml`；仍只替换原 `crm` 镜像。来源状态、旧列表/详情、OAuth、MCP 和既有推送入口保留。展示索引初次回填全部归档；健康业务日修正后只重建 `health_payloads` 索引。服务请求不扫描大型正文。

私有宿主与容器配置中 `sources.google.calendar_scope` 设为 `owned`；只读 NAS 凭据保持原样，同账号 primary 身份仍使用原命名空间。修改前的两个配置分别备份为相邻的 `config.pre-display.json`。

Mac 客户端 0.3.0 使用独立 Keychain 项保存 Google 桌面授权；本轮浏览器授权已完成，同账号自有日历及 Tasks 操作由 Mac 官方适配层执行。当前 build 6 使用固定本机证书签名及固定钥匙串访问助手；构建自动解锁独立签名钥匙串，更新界面不重编译助手。助手首次访问的系统许可已完成，真实凭据跨版本无弹窗验收通过，见 [固定签名](mac-signing.md)。原 0.2.1 应用保存在 `/Users/yuwk/Applications/Personal Data Hub.pre-display.app`；回退时正常退出客户端后恢复此副本。NAS 回退使用原 0.2.1 Compose 候选清单，必要时恢复 `config.pre-display.json`，不用回滚数据库或删除派生索引；原始归档和已有采集进程继续保留。

## AutoAccounting 接入

使用官方 AutoAccounting 的账单 Webhook 导出，无需修改或安装自建 APK。官方已在提交 `1210983f`（PR #1390）合入此功能，验收时核对的官方 master 为 `34b38f82`。手机端沿用原 HTTPS `/autoaccounting/v1/bills` 地址及 Bearer；聚合端保留 `BillInfoModel` JSON 请求和 HTTP 2xx 回执兼容。

官方导出读取 Synced、Edited、Wait2Edit 三种状态，不主动发出删除事件。缺失账单不能推断为删除。`hub-deletion-outbox.patch` 和构建回执仅保留为可选扩展资料，未启用，不属于验收或客户端安装前提。服务端显式删除接口继续保留。

## 2026-10-11 M2 微信会话加工

M2 发布时 CRM 镜像为 `local/personal-data-hub:0.4.1-conversations-m2-20261011-v4`，仍只更新 mcp 正式组的 crm；容器身份、环境值、网络、认证和持久卷保持。宿主既有采集与 webhook 服务加载新加工钩子。migration 3 增加加工表及单记录任务归属；原件字段、身份和哈希保持。为历史回填并发补建 kind/id/source 查询索引，先选窄 ID 再取正文。

宿主配置的 conversation_model 复用 CPA/grok-4.7 及已有 Hermes 私有凭据文件，API 容器仅保存非秘密模型配置。原文与模型使用独立通道；每日默认 24 个预留请求、每个会话最多 4 个输入窗口，可在配置中调整。模型设置变更后的定向重建、窗口缓存、限额及回退要求见 [M2 实施记录](collection-m2-validation.md)，客户端接口见 [M2 客户端需求](client-requirements/m2-wechat-conversations.md)。旧 M1 直接回退会被 schema 版本保护拒绝，使用已准备的 schema3 兼容镜像并保留新数据与删除钩子。

## 备份与回退

`hub backup --destination PATH` 生成包含归档表、版本、墓碑、水位和 CRM 兼容表的事务一致 JSONL；文件目录另行备份。生产 PostgreSQL 同时沿用现有运维备份，不以 SQLite 替代。

迁移前的原 Compose、环境文件、镜像信息、旧 ShellCrash 入口以及已暂停 Hermes 作业清单保存在私有 `rollback/`。旧数据卷保留；2026-10-07 源码整理后，旧 CRM、用量和 Plaud 项目目录移除，运行入口直接使用本仓库；私有环境和旧文件快照保留在仓库外的 `source-backups/20261007-consolidation`，见 [源码管理](source-management.md)。回退恢复原服务时应先停止统一采集和新推送入口；切换后产生的 PostgreSQL 数据需另行处理，旧 SQLite 不是新数据的同步副本。不可丢弃墓碑后直接重放旧备份。

第一阶段曾暂停 12 个旧个人处理作业。Plaud 三源日报随后恢复；2026-10-09 将其正式入口迁至 `agents/nas/plaud-daily.sh` / `processors/plaud`，保持原作业 ID `58d4a4c46d49`、半小时节奏、运行账户、凭据及缓存。私有配置为 `plaud-processing.yaml`；原 `/home/yuwk/cron/model/plaud-daily.sh` 仅兼容转发。统一采集服务归档分源稿、融合日报、摘要与每日期状态，接口和验证见 [Plaud 处理说明](../processors/plaud/README.md)。

2026-10-07 的 [MCP 订阅修复](event-subscriptions-repair.md)恢复原聊天事件的显式部署配置，并为 CRM、邮件、独立用量服务增加当前账户的订阅及投递状态查询。三个服务的原连接、卷和认证保留；新镜像及私有回退记录见验收文档。日常升级构建现在同时安装锁定版本的公共运行时 wheel，避免基础镜像中的旧版本覆盖新依赖。

## 2026-10-11 M1 服务端阅读链路

正式 `mcp/compose.yaml` 的 CRM 镜像更新为 `local/personal-data-hub:0.4.0-reading-m1-20261011-v2`，只改 CRM image；容器身份、认证挂载、两个持久卷、data_net 和其他容器保持。宿主 `personal-data-hub-collectors.service` 与 `health-webhook.service` 已重启以加载变更钩子及加工通道，没有新增服务或调度器。

加工数据库 migration 2 补齐早期表缺失的 business_date/search_text，受影响任务重新整理；原件、修订、水位及附件归属不变。启动回填后沿用单 Worker 有界 drain；API 可显示 pending，不把积压当成采集失败。加工状态通过已有 viewer 鉴权的 `/api/v1/processing/status` 查询。

私有回退资料位于 `/home/yuwk/.config/personal-data-hub/releases/reading-m1-20261011/`，包括 Compose 原件、原镜像/容器身份、加工表旧数据和候选清单。回退不能恢复旧数据库快照覆盖新原件，也不能丢掉删除清理钩子。Mac 本轮没有代码或安装变更；开发需求见 [M1 客户端需求](client-requirements/m1-document-reading.md)，验证证据见 [M1 实施记录](collection-m1-validation.md)。


## M3 当前来源加工（2026-10-12）

M3 发布时 crm 镜像为 `local/personal-data-hub:0.4.2-reading-m3-20261012`，仍通过 `/vol2/1000/Docker/stacks/mcp/compose.yaml` 只更新 crm。增加邮件、活动、录音、日指标、业务对象和辅助状态加工，以及内部 contents 的 type 筛选；旧仪表盘与日报复用 `metric_rules`。没有 schema 升级、私有配置修改、新模型调用或新服务。

宿主采集服务、health-webhook 与 crm 已加载新代码。容器 healthy，两项宿主服务 active；容器用户、按挂载目标比较的卷/只读配置、网络名保持。其他容器 ID 不变；既有启动检查 missing=[]、active_unplanned=[]、stopped_planned=[]。功能测试按用户要求留到采集侧完成后统一做，不以本次运行状态确认代替业务验收。

发布前源码、Compose 及加工表一致性快照保存在私有 `/home/yuwk/.config/personal-data-hub/releases/reading-m3-20261012/`，加工快照 76,046,722 字节。原件、凭据、配置、设备身份及卷未改。新增 profile 队列存在后，回退读取入口时应保留当前加工注册表和删除钩子，不能直接恢复旧 profile 集合或旧数据库。当前历史加工交给既有回填和后台队列。

客户端契约见 `docs/client-requirements/m3-current-sources.md`，实施边界见 `docs/collection-m3-delivery.md`。


## M4 Git 与 NAS 活动（2026-10-12）

M4 发布时 crm 镜像为 `local/personal-data-hub:0.4.3-nas-git-m4-20261012`。宿主配置仅更新 git 的窗口/PR 选项，并新增 emby、navidrome；沿用 personal-data-hub-collectors 和 health-webhook。容器配置、OAuth、CPA、原密钥、媒体服务、网络和卷未改。只有 crm 容器 ID 更新，其他容器 ID 保持。

Emby 从既有宿主 API 用原密钥采样；Navidrome 对既有 0.64.2 源库取只读 WAL 快照，不需要新 API 账号。两个适配器仅在宿主采集，容器负责读取已加工内容，无需增加媒体库或秘密挂载。activity-v1 profile 2 同时修正一条已出现的摘要头解析失败。

上线状态：crm healthy，采集与 webhook active；现有启动检查无缺失、未登记服务或意外停机。功能测试留到采集侧末尾。首次历史归档和重建由现有后台继续，不将配置生效或队列入队当作全量验收。

私有回退信息：`/home/yuwk/.config/personal-data-hub/releases/nas-git-m4-20261012/`。来源契约在 `docs/sources/`，Mac 控件需求在 `docs/client-requirements/m4-nas-git.md`。


## 微信模型提炼暂缓（2026-10-12）

按用户要求，微信主题/要点/摘要提炼移到后续分析模块统一设计。当前镜像为 `local/personal-data-hub:0.4.4-collection-only-20261012`：注释宿主调度器的模型 Worker 启动段，采集路由不为新会话创建提炼 scope；保留旧 profile 用于历史结果的失效和删除维护。宿主与容器配置仅将 conversation_model.enabled 改为 false，模型名称、凭据引用及其他配置保留。

insights 读取入口返回 disabled / deferred_to_analysis_module。processing/status 只统计当前采集加工规则，旧提炼任务及模型预算/失败不再出现在当前积压与错误统计中，并列出 deferred_processors。没有删除历史结果、模型调用账本或缓存表。

只更新正式 crm 镜像并重启既有宿主采集与 webhook 进程；本次没有 schema 升级。私有回退信息位于 `/home/yuwk/.config/personal-data-hub/releases/defer-wechat-insights-20261012/`。当前不处理旧提炼积压，后续分析模块重新设计后再确定启用方式，不直接恢复旧调度当作需求完成。

## M5 服务端收口修复（2026-10-12 至 13）

正式 crm 镜像为 `local/personal-data-hub:0.4.7-collection-closure-m5-20261012`。在已有 Hub PostgreSQL 中并发补建正文 trigram 和阅读排序索引；列表匹配集合明确物化，整页一起提取首个命中摘录。加工 schema 保持 3，原件、来源水位及微信提炼暂停配置保留。

宿主历史回填改为每批 50 条，与阅读队列交替执行。入队事务同时写入既有 `hub_checkpoints` 的内部 `processing:reading-backfill` 位置；重启续跑，规则版本变化重新核对。没有新建数据库、常驻服务或客户端改动。

发布后 crm healthy，两项既有宿主服务 active，实际回填位置已推进。31 种阅读类型的正文/依据核对及隔离库的回填续跑检查通过；实际正文搜索仍超时，CRM 全量同步达到执行限时，M5 尚未整体完成。同期其他项目出现的 Face Baseline QA 未登记运行项保留在最终启动检查记录中，不归入本任务修复范围。完整结果见 [M5 记录](collection-m5-validation.md)。

私有回退资料位于 `/home/yuwk/.config/personal-data-hub/releases/collection-m5-20261012/`。只恢复对应的受影响源码和 crm 镜像，保留采集数据、来源与内部回填位置、索引和原凭据；不恢复旧数据库快照。

## 后台负载修复（2026-10-13）

该轮发布 crm 镜像为 `local/personal-data-hub:0.4.8-runtime-performance-20261013`。正式 Compose 仅替换 crm.image，重启原采集及健康 webhook 两项宿主服务。保留 1000:1001 身份、认证、两个持久卷、只读配置挂载及 data_net，没有新增服务或修改客户端。

宿主私有配置中，普通来源 interval_seconds 与 processing_interval_seconds 均为 21,600：成功采集后约每 6 小时再次运行，加工窗口持续处理已有队列，空闲后等待 6 小时。processing_backfill_on_start 显式为 false；历史加工通过定向 rebuild-content 维护，不再自动遍历。Emby 当前只有 /Sessions 观察接口，保持 60 秒采样；既有推送仍正常接收。

周期拉取的相同内容不再更新原件和展示索引的 observed_at，来源是否检查过以 last_run.ended_at 为准；逐条 observed_at 表示最近真实归档或变更时间。显式设备推送保留原观察时间语义。调度父进程初始化数据库一次，子任务带 --skip-schema-init，省去重复 DDL；独立 CLI 默认仍初始化。没有 schema 或来源水位变更，微信模型保持暂停。

Hub healthy、两项宿主服务 active，健康与鉴权阅读接口返回 200，3 项针对性隔离检查通过。发布后没有历史扫描日志，CRM 核对 27,328 条重复记录成功，单轮仍约 321 秒；正文搜索性能及未完成历史加工继续见 [M5 记录](collection-m5-validation.md)。启动检查通过，同期 token-monitor-hub 的独立变更不归入本轮部署。

私有回退资料位于 `/home/yuwk/.config/personal-data-hub/releases/runtime-performance-20261013/`。只恢复受影响源码和 crm 镜像，保留本次确定的每 6 小时调度、自动回填关闭、模型暂停设置及全部业务数据，不恢复旧数据库或旧同步频率。

## 性能止血（2026-10-13）

最终镜像为 `local/personal-data-hub:0.4.9-performance-relief-20261013`。关闭后台加工、自动回填和 CRM 全量轮询；其他轮询单 worker 仍影响响应，因此最终停止并禁用宿主轮询调度器。微信、健康、账单及已有设备推送继续归档，阅读结果、任务和来源水位保留；依赖轮询的来源及阅读加工保持暂停。

代码修正积压绕过加工间隔的行为：成功、失败和超时后均等待配置间隔，每批最多一个任务。发布在单连接事务中尝试取得全局写锁，有入库占用时让位；PostgreSQL 17 的事务内超时将发布限制为 10 秒。保留原件、删除与版本一致性保护，不修改共享数据库全局参数。

宿主连接因 NAS 重启后容器 IP 改变而失败，已将本机两处数据库引用修正为实际 data_net 地址；容器保留原 `postgresql` 服务名。只有 crm 镜像与已有两项宿主服务更新，数据库、身份、授权、挂载和网络保持。临时宿主 IP 不是长期固定入口，后续网络重建需要核对。

四项针对性隔离 PostgreSQL 检查通过，覆盖积压/失败的真实间隔、发布让位及本地超时、更新和删除的旧任务屏障。正式运行结果及恢复边界见 [性能止血记录](performance-relief-20261013.md)。回退继续保持本轮停用设置和新数据，不照搬旧连接 IP 或旧持续加工策略。
