# Mac 信息展示与 Google 接入

客户端 0.3.0 默认打开今日概览，首页模块为日程、健康、社交。顶部菜单切换数据趋势和最近动态；左侧提供主题页面。定制首页可开关模块、拖动排序、选择指标，保存在 Mac 私有 Application Support 中。深浅色跟随系统，窄窗口自动折行。

Google 使用 Mac 官方 REST API 适配层，与 NAS 只读采集凭据隔离。Desktop 应用配置随签名客户端打包，用户授权后的刷新凭据保存在独立 Keychain 项，已有设备配置优先；PKCE、随机 state、127.0.0.1 回调和账号校验保护授权过程。授权范围为 Tasks、自有日历事件和日历清单只读。默认不处理参会者、会议邀请或 Meet 创建。NAS 采集自有日历，primary 命名空间保持兼容。

任务支持增改删、完成和恢复、清单管理、子任务、排序和跨清单移动；重复任务等官方 API 限制通过 Google 原页处理。个人日程支持全天、跨天、日/周/月重复；修改重复事件可选本次或整个系列。更新使用 ETag，版本冲突提示刷新；写入不自动重试。失败草稿保留，需由用户再次提交。

浮窗的下一项事件单独查询，不限制为今天；跨天事件显示实际日期，使用独立缓存。NAS 展开的重复事件默认归档未来 365 天，避免无终止重复事件产生无限分页；私有来源配置 `calendar_future_days` 可调整未来窗口，窗口之外的既有归档不会删除。任务趋势展示当前未完成任务的到期日分布，不将当前待办数冒充过去每天的历史状态。

全局快捷键默认 **⌃⌥Space**，在设置中点击快捷键后录入新组合；被占用时提示。浮窗查看今日待办与下一项日程，Enter 新增任务，Esc 收起并返回原应用。应用内 ⌘N 新增任务、⌘⇧N 新增日程、⌘F 搜索、⌘1/2/3 切换概览。

归档 API 使用原只读鉴权：

- `GET /api/v1/dashboard?date=2026-10-06&tz=Asia/Shanghai&modules=agenda,health,social`
- `GET /api/v1/trends?date=2026-10-06&days=7&tz=Asia/Shanghai&modules=health,social,usage`（7 或 30 天）
- `GET /api/v1/timeline?domains=social,activity,recordings,reports,mail,git,notes&limit=30`；可传 query、kind、person、start/end 和返回的 next_cursor。时间范围必须带时区。
- 原记录列表、详情、附件、MCP 和 OAuth 入口保留。

展示索引是可重建的派生数据，随归档同事务更新和删除。`hub backfill-display` 补齐历史索引，`hub backfill-display --rebuild` 重建全部，`--rebuild --kind health_payloads` 仅重建健康索引；不改原始载荷。页面请求仅读取索引；原始活动载荷、长正文和附件只在详情读取。未知发生时间独立标注，不用归档时间代替。

健康按实际样本日期汇总；累计步数/热量按区间起始日期所属业务日取有效累计快照，不累加重复推送，午夜闭合的快照仍属于前一业务日。睡眠按会话结束日期归属，重复样本去重，重叠会话区间取并集，独立片段累加；仅代表已经收到的有效睡眠数据。缺失显示暂无数据，历史值标明日期。指标包含数据日期、来源更新时间与记录 ID。Token 使用设备/日期当前累计记录，不加总版本；财务按币种分组、转账单列，待确认账单不计入收支。已有官方摘要和文本直接阅读，不运行模型、复盘或提醒作业。

构建安装仍使用 `python3 apps/mac-client/install.py`。构建从仓库外的私有配置文件打包 Google Desktop 应用设置，`PDH_GOOGLE_CONFIG` 可指定路径；拒绝用户令牌和 Web 客户端配置，缺配置即停止构建。`--provision-google` 保留为 stdin 设备覆盖入口（仅 client_id、client_secret、expected_calendar，不复制 NAS refresh_token）；`--authorize-google` 打开用户授权。`--google-config-status` 仅返回配置/授权两个布尔状态。不得通过命令参数或日志传凭据。

客户端 0.3.4 在主窗口打开时提供 Dock 和标准应用/文件/编辑/显示/窗口菜单，支持隐藏、最小化、缩放、关闭和重新打开窗口；⌘W 或关闭按钮关闭主窗口后移除 Dock 图标，继续驻留菜单栏，最小化保留 Dock。退出查看端不停止采集。更新安装先按准确路径正常退出旧查看端，确认退出后才替换应用，避免旧进程访问已替换资源时出现签名校验失败。切页、刷新、分页、正文读取、音频和附件下载均提供加载状态，页面切换不展示其他模块的旧指标，错误时可重试。

客户端 0.4.0 的 Memos 笔记、日报、执行记录和全文阅读使用 `GET /api/v1/contents`。日报按服务端 `variant=daily_review` 与 `business_date` 展示，执行记录按 `variant=execution_log` 单列，普通笔记按 `source=memos&variant=note`。列表的 content ID 与归档 record ID 分开使用，筛选变化清空不透明游标，追加页按 content ID 去重。

阅读窗口按详情 revision 请求 `/blocks`，依赖 `next_after` 继续分页，先原样拼接已有块再统一解析 Markdown；没有旧详情的 50,000 字截断。使用 [Apple Foundation 的 Markdown 块语义](https://developer.apple.com/documentation/foundation/nspresentationintent) 展示标题、列表、引用、段落与链接，搜索根据目标分块及原文位置定位和高亮。摘要只在服务端明确提供时显示。来源记录与原件版本使用 `/evidence`，归档附件继续认证下载与 SHA-256 校验。

仅已整理且有支持的正文版本进入阅读。409 清空旧块、摘要和依据并重新读取，404 清空所有阅读数据并刷新列表；网络核对失败保留屏幕并明确标注未核对当前状态。阅读期间每 30 秒及应用激活时核对头；正文不新增永久缓存。采集状态中的内容整理独立读取 `/api/v1/processing/status`。接口及验收见 [M1 需求](client-requirements/m1-document-reading.md)。Plaud 转录继续使用现有专用接口，不自动触发 ASR。

验证入口：

- `python checks/display-smoke.py` 验证确定性展示数据与接口边界。
- Mac `swift test` 验证官方适配请求、日期、并发和授权失败。
- `--ui-smoke` 截取自己的窗口；可加 `--qa-dark`、`--qa-narrow`、`--qa-section trends|recent|social|finance` 或 `--qa-quick`。截图只存 Mac 私有目录。
- `--google-smoke` 是会创建并清理真实验收数据的显式开发入口，不在后台或启动时运行。

当前应用改用长期复用的本机代码签名证书及固定钥匙串访问助手。界面更新保留助手二进制，双方校验同一证书与指定 Bundle ID；凭据继续保存在原系统 Keychain，通过私有管道访问。助手首次访问需系统确认，Google 浏览器授权保留。签名密钥留在独立私有钥匙串，构建不需要登录密码，不允许临时签名回退。详见 [固定签名](mac-signing.md)。
