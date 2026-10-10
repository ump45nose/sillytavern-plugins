# Mac 客户端

原生 SwiftUI / AppKit 客户端（macOS 13+），同时提供 Dock、标准应用菜单与常驻菜单栏、独立信息窗口、单实例和开机启动。没有第三方构建依赖。

- 默认今日概览：日程任务、健康、最近交流；首页模块可开关、排序和选择指标。
- 数据趋势按最近 7 / 30 天展示，最近动态按系统时区分组，每页 30 项；主题页和搜索用于下钻。
- Mac 直连 Google 官方 API 管理任务、清单和个人日程；NAS 仍使用原只读凭据定期归档。
- 全局 ⌃⌥Space 呼出任务浮窗；应用内 ⌘N / ⌘⇧N 新增任务 / 日程，⌘F 搜索，⌘1 / 2 / 3 切换概览。全局组合在设置中修改，冲突会提示。
- 联系人资料及交流时间线、健康图表、阅读式正文和录音播放；原始 JSON 折叠，完整导出和附件校验保留。
- 日报入口读取归档库中的 Memos `#日报 YYYY-MM-DD` 正文；Hermes 定时任务日志单列为执行记录，源日志没有正文时不当作完整日报。
- 切页、刷新、分页、详情和附件提供加载反馈；请求代次保护防止较早请求覆盖新页面。主窗口打开时显示 Dock 和完整应用菜单；⌘W 或关闭按钮关闭主窗口后移除 Dock 图标，继续驻留菜单栏，可通过菜单栏重新打开。最小化保留 Dock。
- 查看现有微信与电脑活动 Agent 状态、交付水位；请求现有 launchd 实例立即同步电脑活动。
- 关闭窗口后驻留菜单栏。退出客户端不影响现有采集；开机启动可在设置中开关。

## 安装

在 Mac 的同仓库检出执行：

```bash
python3 apps/mac-client/install.py
open "$HOME/Applications/Personal Data Hub.app" --args --show
```

构建使用本机 Xcode 的 `swift build -c release`，使用长期复用的本机证书签名 `.app`，安装到 `~/Applications`，并通过 macOS `SMAppService` 注册登录启动。构建产物为 `apps/mac-client/dist/Personal Data Hub.app` 和安装成功后生成的 `Personal Data Hub.zip`。当前安装流程迁移本机已有的两个采集任务，保留既有私有配置。未授权时先完成应用安装，原采集任务保持原状；新 Mac 的设备连接配置仍需先完成。

应用图标使用蓝色归档盒与资料卡。`swift apps/mac-client/create-icon.swift` 通过原生矢量绘制生成 `Resources/AppIcon.png` 和包含 16–1024 像素尺寸的 `AppIcon.icns`；构建直接使用保存的 ICNS。

应用包含微信采集代码、Python 3.12 及依赖、固定版本的原生读取器、Node 和电脑活动同步脚本。签名资源中的 `collection.tar.gz` 只保存运行代码，不含凭据、数据库、附件、水位或媒体队列。安装时校验签名、资源哈希和运行环境，再由临时 launchd 任务分别验证微信与电脑活动可读，检查通过才将两个原任务的启动入口切到客户端。运行代码解压至 `~/Library/Application Support/PersonalDataHub/Agents/versions/<SHA256>/`，保留原 launchd label、设备身份、采集范围和检查点。兼容旧微信控制台脚本、直接 Node 任务和 Python 包装任务；同版再次检查仍验证后台读取，但不重启原采集任务，失败时恢复原采集配置。客户端采集模式明确关闭旧 CRM 的自动事实提取，防止旧配置导致只归档的服务拒绝整批消息。安装前的配置和水位备份保存在 `PersonalDataHub/backups/collection-app-*`。

客户端是两个采集任务的系统授权主体：`launchd → Personal Data Hub → 内置 Python / Node → 采集器`。用户在「设置 → 本机采集」打开完全磁盘访问设置，为 Personal Data Hub 授权一次，再回到客户端启用采集。检查针对真实后台入口，不把终端继承的权限当作后台已获授权；读取检查只返回状态，不打印会话或活动内容。首次授权由用户在 macOS 明确完成，应用不会修改 TCC 数据库。正常更新复用本机证书与 Bundle ID；撤销授权或系统规则变化时重新显示授权提示。归档凭据及 Google 登录是独立的服务配置，不属于本机数据访问授权。

退出查看端不停止采集，登录后的界面驻留菜单栏。设置中可关闭界面的登录启动；两个已有 launchd 后台任务保持各自的运行规则。构建机器缺少新版 SwiftUI 编译插件时，可通过 `PDH_SWIFT_SDK` 指定本机已安装的兼容 macOS SDK；此设置只影响构建，不改变采集入口。

签名身份保存在仓库外的私有 Signing 目录，构建自动解锁独立签名钥匙串，无需登录密码。系统 Keychain 由固定访问助手读写，更新界面时保留助手二进制，不改变钥匙串许可。双方校验证书与 Bundle ID，普通脚本不能调用助手取凭据。首次允许助手访问归档和 Google 两项后，界面更新不用再次输密码；签名或助手校验失败时停止，不退回临时签名。包内带助手代码副本，现有 Mac 继续使用原 Application Support 路径中的获准助手。详见 [固定签名](../../docs/mac-signing.md)。当前自签名产物用于本机更新，不作为公开分发安装包。

## 连接

设置中填写 HTTPS 服务地址与只读访问凭据。凭据保存在系统 Keychain；非秘密的地址保存在 `~/Library/Application Support/PersonalDataHub/connection.json`。没有默认凭据，不使用日志或命令参数传递秘密。

NAS 私有配置的 `hub_viewer_token_file` 指向单独凭据，允许来源、类型、记录和附件的 GET，不能上传、采集写入或删除。原 API Bearer 和 CRM OAuth 保持兼容。服务跳转不自动跟随，避免把凭据发送到其他地址。

部署也可将 `{ "endpoint": "https://...", "token": "..." }` 经 stdin 交给应用的 `--provision` 入口；不得在 shell 参数或仓库文件中保存这个 JSON。Google Desktop 应用配置在构建时读取仓库外的 `~/Library/Application Support/PersonalDataHub/google-desktop-config.json`，也可通过 `PDH_GOOGLE_CONFIG` 指定私有文件路径；缺失配置则停止构建。包内签名资源仅包含 client_id、Desktop client_secret 和可选 expected_calendar，不含任何用户令牌，不接受 Web 客户端配置。最终用户安装后可以直接打开浏览器授权，授权产生的刷新凭据只写入 Keychain。已有设备 Keychain 配置优先，`--provision-google` 仍可通过 stdin 做设备覆盖，同客户端配置更新保留已授权的 Mac 刷新凭据。

`--smoke` 检查来源、分页、详情、附件校验和本机 Agent；`--sync` 请求既有 Agent 同步。`--agent-bundle-status` 查询组件安装和后台加载状态，`--install-agents` 迁移/更新已有采集组件。`--enable-login`、`--disable-login` 和 `--login-status` 管理界面的登录启动；若状态为 `requiresApproval`，需要在 macOS「登录项」设置中批准，不能视作已启用。`--ui-smoke` 及 `--interaction-smoke` 用于开发验收，截图仅在 Mac 私有目录保存。Google 离线时使用最近缓存并标注同步时间，编辑草稿本地保留，恢复后由用户再次提交。

列表不传输原始 AX 事件、长正文或附件。长内容和原始数据界面预览最多 50,000 字符，导出保留完整数据。事件时间缺失显示“时间未提供”，不会用归档时间冒充发生时间。

接口、数据口径及验收见 [展示说明](../../docs/mac-display.md) 与 [验证记录](../../docs/mac-display-validation.md)。
