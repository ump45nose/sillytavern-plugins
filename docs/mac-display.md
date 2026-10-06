# Mac 信息展示与 Google 接入

客户端 0.3.0 默认打开今日概览，首页模块为日程、健康、社交。顶部菜单切换数据趋势和最近动态；左侧提供主题页面。定制首页可开关模块、拖动排序、选择指标，保存在 Mac 私有 Application Support 中。深浅色跟随系统，窄窗口自动折行。

Google 使用 Mac 官方 REST API 适配层，与 NAS 只读采集凭据隔离。桌面 OAuth 配置及刷新凭据保存在独立 Keychain 项；PKCE、随机 state、127.0.0.1 回调和账号校验保护授权过程。授权范围为 Tasks、自有日历事件和日历清单只读。默认不处理参会者、会议邀请或 Meet 创建。NAS 采集自有日历，primary 命名空间保持兼容。

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

构建安装仍使用 `python3 apps/mac-client/install.py`。OAuth 桌面配置可经 stdin 传给 `--provision-google`（仅 client_id、client_secret、expected_calendar，不复制 NAS refresh_token）；`--authorize-google` 打开用户授权。不得通过命令参数或日志传凭据。

验证入口：

- `python checks/display-smoke.py` 验证确定性展示数据与接口边界。
- Mac `swift test` 验证官方适配请求、日期、并发和授权失败。
- `--ui-smoke` 截取自己的窗口；可加 `--qa-dark`、`--qa-narrow`、`--qa-section trends|recent|social|finance` 或 `--qa-quick`。截图只存 Mac 私有目录。
- `--google-smoke` 是会创建并清理真实验收数据的显式开发入口，不在后台或启动时运行。

当前应用为本地临时签名。更新二进制后，macOS 可能再次弹出 Keychain 访问确认；在系统弹窗选择“始终允许”才能继续读取已经授权的 Google 凭据，不需要重复 Google 浏览器授权。公开发布的稳定 Developer ID 签名和公证仍不在本轮范围内。
