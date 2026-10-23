# 用量统计 MCP

将 Token Monitor 和 ShellCrash 合为一个只读 MCP。每天 23:00（Asia/Taipei）生成当天 00:00 至生成时的数据，保存明细并发布 usage.daily_ready。可同进程加载钉钉事件包；原钉钉业务工具仍由原 MCP 提供。

## 数据范围

- Token：从 devices.json 逐设备读取明确的当天窗口；历史日期只取 history.daily 的同日记录。Asia/Shanghai 与 Asia/Taipei 的当日日界线相同，可合并；日界线不同、日期过期或缺少可靠时区的来源会明确排除，不算为 0。
- 展示总 Token、模型、工具和设备维度，保留缓存读取、缓存写入、输出与未分类 Token。维度是同一批用量的不同分类，不再相加。上游没有跨设备请求 ID，无法排除同一日志重复采集。
- 估算美元成本来自 Token Monitor，不是订阅实付。订阅配置单独列出；空配置显示“未配置”，实际当日付款始终标为未知，因为没有支付流水。
- 额度使用生成时的来源状态。优先复用已认证 /api/stats 的账户合并结果与过期阈值；失败退回已有文件，不将缺失额度写为 0。额度不伪装为历史日期状态。
- 流量只读 traffic.sqlite3 的目标日事实行，分别汇总上传、下载、策略组、流量池、节点和订阅源。ai-summary.json 是滚动 30 日快照，本服务不使用它的总数冒充单日。
- 采集器每秒采样、按小时保存；报告保留采样空缺、最后采样时间和无流量记录的小时。源库未记录每次采样，精确覆盖率标为未知；无流量记录不直接判定采集故障。

## 工具

| 工具 | 用途 |
|---|---|
| get_daily_usage(date) | 获取指定日当前可得的摘要；默认今天。查询不保存报告。 |
| list_usage_reports(offset, limit) | 分页列出已存档日报。 |
| get_usage_report(report_id, section, offset, limit) | 获取存档摘要或分页明细。summary 返回可用 section。 |
| get_usage_event_status() | 查询日报启用状态、时间和最近入队记录。 |
| get_dingtalk_event_status() | 已启用时，查询钉钉采集状态与受阻原因。 |
| list_dingtalk_events(limit) | 已启用时，读取最近钉钉事件。 |
| get_dingtalk_event(event_id) | 已启用时，读取钉钉事件详情。 |

所有业务工具复用公共 OAuth 与 read 权限；用量数据额外核对 USAGE_EVENT_SUBJECT，钉钉包核对各自来源主体。没有认证的开发模式只能监听回环地址，生产不能缺省放行。

## 事件与保存

事件协议、订阅、签名、到期、去重和投递重试由 mcp-platform 的 EventService 统一提供。业务包只注册定义、准备数据和调用 publish。

每日事件 ID 为 usage.daily_ready:日期；报告 ID 为 usage-日期。首次成功生成后明细不再覆盖，服务崩溃后的重试复用原报告与事件内容。重启仅补当天已经到期的报告，不回放历史日期。新增订阅只接收之后发生的事件；此前报告可由工具读取。

事件只包含摘要与报告 ID，完整明细保存在 /data/reports。/data/events 保存公共事件状态，/data/oauth 保存既有 OAuth 状态，/data/dingtalk-events 保存钉钉采集与事件记录。整个 /data 使用同一个服务持久卷，不增加数据库或 Redis。报告目录 700、文件 600。

## 配置与权限

mcp.app.yaml 是部署唯一清单，明确使用 deployment_mode: existing。本项目负责离线构建镜像和启动业务容器；公共 mcpctl 的 existing 路径仅协调 OAuth、共享 Tunnel、DNS 与入口核验。业务监听端口和挂载依据清单生成独立 Compose 配置，不走公共 generic build_bundle 的镜像构建路径。

新服务运行用户为 1000:1001，保留两个上游项目的读权限；来源目录以只读 bind mount 挂载，SQLite 以 mode=ro 和 query_only 读取，且挂载目录保留 WAL/SHM。

| 环境变量 | 配置 |
|---|---|
| USAGE_DATA_DIR | /data |
| TOKEN_MONITOR_DATA_FILE | /sources/token-monitor/devices.json |
| SHELLCRASH_TRAFFIC_DB | /sources/shellcrash/traffic.sqlite3 |
| USAGE_TIMEZONE | Asia/Taipei |
| SHELLCRASH_TIMEZONE | Asia/Shanghai |
| USAGE_DAILY_HOUR / USAGE_DAILY_MINUTE | 23 / 0 |
| USAGE_EVENT_SUBJECT | 必填的来源所属用户名，必须已在 OIDC_AUTHORIZED_USERNAMES 中 |
| USAGE_EVENTS_ENABLED | 部署时显式设为 true 才启动日报生产 |
| TOKEN_MONITOR_STATS_URL | 私有 /api/stats URL，生产值在清单中 |
| TOKEN_MONITOR_SECRET_FILE | /run/secrets/token-monitor-secret，仅一行既有秘密值 |
| TOKEN_MONITOR_STALE_AFTER_SECONDS | 600；API 不可用时的后备过期阈值 |
| DINGTALK_EVENTS_ENABLED | true 才加载钉钉包并启动其生产任务 |
| DINGTALK_EVENTS_CONFIG | /run/secrets/dingtalk-events.json，固定来源主体及已授权接口 |

秘密目录在仓库之外，以只读目录挂载到 /run/secrets；秘密文件 600、归属 UID 1000。源文件、OAuth 状态、真实业务记录和凭据均不得加入 Git 或镜像。

## 构建和验证

当前固定公共运行时 mcp-platform 0.1.6（提交 dea309a5d83b6365a57937bc6e11affe692bfcaf），包含 MCP 2.0 必需的 cache 字段修复；钉钉事件包保持 0.1.1。公共运行时升级时同时更新业务 wheel 的精确依赖，再校验 pip check。

生产使用 Python 3.12。由宿主机取得并构建固定提交的 mcp-platform、usage-monitor-mcp、dingtalk-events 三个 wheel；容器构建使用本项目 Dockerfile，从已有、已核验的认证运行时镜像离线安装。这样私有 Git 依赖在宿主机完成，不进入镜像内的依赖安装步骤。

1. 检查 deployment/wheels.lock.json：记录三个 wheel 的名称、版本、来源提交、SHA256，以及基础镜像 local/personal-crm:refresh-policy-0.1.3 的完整镜像 ID。公共包和钉钉的来源必须同时与 uv.lock 一致。业务 wheel 若早于当前文档提交，脚本会核验其后 Python 源码及依赖没有变化。
2. 在干净业务仓库运行 scripts/prepare_build.py，提供 --build-dir、--platform-wheel、--dingtalk-wheel、--usage-wheel 和 --image-tag。脚本校验来源、哈希、wheel metadata、实际本地基础镜像 ID，再把受控源码和三个 wheel 复制到新的仓库外目录，生成 build-record.json。--check-only 仅校验；脚本始终不构建或启动容器，也不读取秘密文件。
3. 审核 build-record.json 内的 source_commit、source_files、wheels 与 build_command，执行其 Docker 构建命令。构建指定 --pull=false 与 --network=none。Dockerfile 仅在新镜像层移除继承的 personal-crm 分发包，离线安装三个 wheel 并执行 pip check；原 CRM 镜像和容器不变。
4. 宿主机部署步骤准备 /data 卷权限、只读来源和秘密挂载，启动本服务；随后运行 mcpctl doctor、plan、deploy 的 existing 路径，协调认证和公网入口。OAuth 签名、存储密钥及事件状态保存在仓库外的持久目录，升级保留它们。

build-record.json 与构建目录不加入 Git。每次构建目录必须是新的绝对路径，脚本不会覆盖已有构建；输入只允许已审定的三个 wheel，源码只复制 Git 跟踪的 Python 包、Dockerfile 与指定构建资料。镜像中的依赖安装不使用 uv export 或私有 Git URL。

只读诊断命令 usage-monitor-check 默认只打印日期和来源可用性。--summary 会显示实际统计，日常部署冒烟不需要该选项。验证涵盖日界线、离线设备、历史精确日期、费用缺失、跨日流量空缺、报告不可覆盖、分页限制和每日事件重试；测试使用临时数据，不触碰实际来源、不外发。

部署后核对健康、匿名 initialize 拒绝、OAuth 发现、授权工具列表、MCP Events 发现及真实订阅状态。入队、服务器投递成功与客户端显示通知是三个状态，不能互相替代。

升级只更换本服务镜像并保留 /data、OAuth 密钥与签名配置。回滚只恢复前一个镜像，不回退报告、事件状态或上游业务数据。


## Hub HTTP 只读接入

`USAGE_HTTP_READ_TOKEN_FILE` 指向仓库外 `/run/secrets/hub-http-read-token`。
固定来源所属人的独立随机 Bearer 只读令牌只用于 `/api/v1/net`、`/api/v1/limits`；
缺省未配置返回 503，匿名或错误令牌返回 401。MCP OAuth、事件生产和数据归属保持。

`net` 返回 `{data: {pools, today, month_bytes, hourly}, updated_at, gaps}`。SQLite
使用原只读挂载、同一事务，按本地小时在库内聚合；缺失和未来小时返回 null。
流量库没有订阅配额/有效期，Mihomo 本次 21 个 provider 也都无 subscriptionInfo。
因此 `pools` 为 null，不能把机场/机房等路由分类当成订阅，或以本月流量冒充套餐已用量。
`limits` 复用原已鉴权 Token Monitor API 与额度去重/过期逻辑，不暴露来源凭据。
Hub 自己读取 stats 时可直接使用其额度，避免同时再请求 limits 导致重复 I/O。
HTTP 不生成报告、不发布事件、不写业务数据库，不自动重试写操作。
