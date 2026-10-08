# 钉钉公网入口与 GPT 网页连接

`mcp.app.yaml` 维护入口与正式展示资料。既有 MCPHub 1.0.38 继续从 `http://192.168.31.201:3100` 聚合钉钉官方 MCP，公网为 `https://mcphub-home.172906573.xyz/mcp`，保留北向 OAuth；未重启 MCPHub 或复制业务代码。

2026-10-05 已通过 ChatGPT「创建自定义 MCP 服务器」原生表单注册并完成现有 MCPHub 账号授权：[打开钉钉](https://chatgpt.com/plugins/plugin_asdk_app_6ac287394cdc819192509b34e64e6557)。实际 App ID 为 `asdk_app_6ac287394cdc819192509b34e64e6557`；官方图标已在网页详情与已安装列表确认。清单和本地 `.app.json` 已同步该原生身份。

旧 Plugin Creator 展示包 `Plugin_6e7cd81e16288191be4471f450fd078a` 的 `1.1.4` release 仅为历史记录。后续网页部署禁止使用 Plugin Creator，不用 ZIP 包保存结果代替原生连接。

源码现位于 `mcp-platform/integrations/dingtalk/`。本次未修改 NAS 私有 `source_roots.dingtalk`，运行环境仍使用原部署路径；切换本目录需另行部署。existing 模式协调入口和清单声明的北向 OAuth 期限。清单使用 `oauth_provider: mcphub`，刷新期限省略时为 180 天；NAS 目标引用现有设置文件。只有期限变化时短暂停止／启动 MCPHub，保留注册、令牌和所有官方后端，不调用钉钉写工具。官方图标源见 `assets/plugin/SOURCES.md`；网页压缩副本及 10 KB 限制见平台网页部署记录。

```bash
sudo -n /home/yuwk/code/mcp-platform/.venv/bin/mcpctl plan dingtalk --target nas
```


## 钉钉事件

`events/` 维护只读事件生产器，由用量统计 MCP 加载并交给公共事件服务投递。已支持当前用户待办新增、重要字段变化、临期与新待审批；首次完整读取只建立基准。当前官方主日历查询缺少日程 ID，日历事件暂不启用。原钉钉 App、MCPHub 与北向 OAuth 保留原身份；没有新增聚合网关或钉钉业务写入。配置、主体隔离、状态和回退方法见 [事件生产器说明](events/README.md)。

## 仓库收束（2026-10-08）

来自私有源仓库 `ump45nose/dingtalk-workspace-plugin` 的提交
`650c65afb23930faaa85be7a2dae2ca37aac210a`。原 `mmp-platform/` 内容成为本目录，
原根目录展示包完整保存在 `legacy-plugin/`，仅作历史记录，不用于当前网页部署。
两种 App 身份不可互换；当前原生连接、OAuth、域名和官方图标保持不变。
旧包 README 中的 Plugin Creator 和根目录导入流程是历史流程，当前以本文及平台 AGENTS 为准。

此次仅迁移源码和目录登记：未更新 NAS 路径、构建镜像、发布插件、调用业务写工具或改变 OAuth。
以后授权部署时，先核对现有私有目标，再将 `source_roots.dingtalk` 改为本目录，
并更新用量统计服务构建 `dingtalk-events` wheel 的源码位置到 `events/`。
保留所有生产配置、状态和凭据；不要从仓库示例覆盖私有目标。

保留了全部 23 个源文件（含两处同一官方 PNG）；当前插件的仓库展示链接更新到本目录。
这是源码快照导入，不含原仓库完整 Git 历史；原仓库及其提交历史保留，未删除或归档。
离线检查不代表 NAS 运行、OAuth 或客户端发布已经迁移。
