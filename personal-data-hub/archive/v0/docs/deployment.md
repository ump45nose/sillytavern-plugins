# 部署与维护

## 当前 NAS 入口

| 入口 | 管理方式 | 持久化 |
| --- | --- | --- |
| 统一 API / CRM MCP | 原 `personal-crm` Compose 项目、`crm` 服务、18086 端口及公网 CRM URL | 原 OAuth 卷、统一 PostgreSQL、统一文件卷 |
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

观察采集：`hub status`、`systemctl status personal-data-hub-collectors.service`。运行日志只记录来源、数量和错误类别，避免输出消息正文、邮件内容及凭据。`partial` / `segment_invalid` 表示本轮遇到无效片段；归档历史异常数量放在 `quality_warnings`，不会令以后成功的运行一直显示 `partial`。旧运行记录保持原状，不回写历史状态。

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

## 备份与回退

`hub backup --destination PATH` 生成包含归档表、版本、墓碑、水位和 CRM 兼容表的事务一致 JSONL；文件目录另行备份。生产 PostgreSQL 同时沿用现有运维备份，不以 SQLite 替代。

迁移前的原 Compose、环境文件、镜像信息、旧 ShellCrash 入口以及已暂停 Hermes 作业清单保存在私有 `rollback/`。旧数据卷保留；2026-10-07 源码整理后，旧 CRM、用量和 Plaud 项目目录移除，运行入口直接使用本仓库；私有环境和旧文件快照保留在仓库外的 `source-backups/20261007-consolidation`，见 [源码管理](source-management.md)。回退恢复原服务时应先停止统一采集和新推送入口；切换后产生的 PostgreSQL 数据需另行处理，旧 SQLite 不是新数据的同步副本。不可丢弃墓碑后直接重放旧备份。

第一阶段曾暂停 12 个旧个人处理作业。Plaud 三源日报随后恢复；2026-10-09 将其正式入口迁至 `agents/nas/plaud-daily.sh` / `processors/plaud`，保持原作业 ID `58d4a4c46d49`、半小时节奏、运行账户、凭据及缓存。私有配置为 `plaud-processing.yaml`；原 `/home/yuwk/cron/model/plaud-daily.sh` 仅兼容转发。统一采集服务归档分源稿、融合日报、摘要与每日期状态，接口和验证见 [Plaud 处理说明](../processors/plaud/README.md)。

2026-10-07 的 [MCP 订阅修复](event-subscriptions-repair.md)恢复原聊天事件的显式部署配置，并为 CRM、邮件、独立用量服务增加当前账户的订阅及投递状态查询。三个服务的原连接、卷和认证保留；新镜像及私有回退记录见验收文档。日常升级构建现在同时安装锁定版本的公共运行时 wheel，避免基础镜像中的旧版本覆盖新依赖。
