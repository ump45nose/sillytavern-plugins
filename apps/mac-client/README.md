# Mac 客户端

原生 SwiftUI / AppKit 菜单栏客户端（macOS 13+），参考本机 Token Monitor 的常驻菜单栏、独立信息窗口、单实例和开机启动使用方式。没有第三方构建依赖。

- 查看所有归档来源的条数、最近接收时间和采集状态。
- 按来源、类型、最近 7 / 30 天筛选；搜索标题和摘要，每页 50 条。
- 查看信息内容、来源时间、原始数据；导出完整 JSON，保存并校验附件。
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

部署也可将 `{ "endpoint": "https://...", "token": "..." }` 经 stdin 交给应用的 `--provision` 入口；不得在 shell 参数或仓库文件中保存这个 JSON。`--smoke` 从 Keychain 读取凭据，检查真实来源、分页、详情和本机 Agent，只输出条数。

列表不传输原始 AX 事件、长正文或附件。长内容和原始数据界面预览最多 50,000 字符，导出保留完整数据。事件时间缺失显示“时间未提供”，不会用归档时间冒充发生时间。
