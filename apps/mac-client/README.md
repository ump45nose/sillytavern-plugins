# Mac 客户端

原生 SwiftUI / AppKit 菜单栏客户端（macOS 13+），参考本机 Token Monitor 的常驻菜单栏、独立信息窗口、单实例和开机启动使用方式。没有第三方构建依赖。

- 默认今日概览：日程任务、健康、最近交流；首页模块可开关、排序和选择指标。
- 数据趋势按最近 7 / 30 天展示，最近动态按系统时区分组，每页 30 项；主题页和搜索用于下钻。
- Mac 直连 Google 官方 API 管理任务、清单和个人日程；NAS 仍使用原只读凭据定期归档。
- 全局 ⌃⌥Space 呼出任务浮窗；应用内 ⌘N / ⌘⇧N 新增任务 / 日程，⌘F 搜索，⌘1 / 2 / 3 切换概览。全局组合在设置中修改，冲突会提示。
- 联系人资料及交流时间线、健康图表、阅读式正文和录音播放；原始 JSON 折叠，完整导出和附件校验保留。
- 查看现有微信与电脑活动 Agent 状态、交付水位；请求现有 launchd 实例立即同步电脑活动。
- 关闭窗口后驻留菜单栏。退出客户端不影响现有采集；开机启动可在设置中开关。

## 安装

在 Mac 的同仓库检出执行：

```bash
python3 apps/mac-client/install.py
open "$HOME/Applications/Personal Data Hub.app" --args --show
```

构建使用本机 Xcode 的 `swift build -c release`，生成并本地签名 `.app`，安装到 `~/Applications`。更新保留上一份应用以便回退。应用尚未做公开发布的 Developer ID 签名和公证。

现有采集 Agent 由 `agents/mac/install.py` 管理，保留原 TCC 责任主体、launchd label、白名单和检查点；客户端不直接读取应用组缓存或微信数据库，不创建第二个采集进程。

## 连接

设置中填写 HTTPS 服务地址与只读访问凭据。凭据保存在系统 Keychain；非秘密的地址保存在 `~/Library/Application Support/PersonalDataHub/connection.json`。没有默认凭据，不使用日志或命令参数传递秘密。

NAS 私有配置的 `hub_viewer_token_file` 指向单独凭据，允许来源、类型、记录和附件的 GET，不能上传、采集写入或删除。原 API Bearer 和 CRM OAuth 保持兼容。服务跳转不自动跟随，避免把凭据发送到其他地址。

部署也可将 `{ "endpoint": "https://...", "token": "..." }` 经 stdin 交给应用的 `--provision` 入口；不得在 shell 参数或仓库文件中保存这个 JSON。Google 桌面配置经 stdin 交给 `--provision-google`，仅传 client_id、client_secret 和 expected_calendar，不复制 NAS 刷新凭据。同客户端配置更新保留已授权的 Mac 刷新凭据。首次在设置中连接 Google，独立浏览器授权完成后保存到 Keychain。

`--smoke` 检查来源、分页、详情、附件校验和本机 Agent；`--sync` 请求既有 Agent 同步。`--ui-smoke` 及 `--interaction-smoke` 用于开发验收，截图仅在 Mac 私有目录保存。Google 离线时使用最近缓存并标注同步时间，编辑草稿本地保留，恢复后由用户再次提交。

列表不传输原始 AX 事件、长正文或附件。长内容和原始数据界面预览最多 50,000 字符，导出保留完整数据。事件时间缺失显示“时间未提供”，不会用归档时间冒充发生时间。

接口、数据口径及验收见 [展示说明](../../docs/mac-display.md) 与 [验证记录](../../docs/mac-display-validation.md)。
