---
name: figma-make
description: Figma Make：整理需求，用当前可控浏览器操作 Make agent，再经网页导出或 Figma MCP 接回代码和资源。用于要求 Make 生成原型，或继续实现已有 Make 文件。
---

# Figma Make

## 环境与登录

读取 [config.json](config.json) 中的账号与钥匙串引用。优先使用当前 Codex／Claude Code 提供的内置浏览器，按其工具文档操作并复用登录会话。有 Browser 技能时先读取完整技能，用其要求的执行接口和 SDK 操作，不假设一定存在单独的 click 工具。开始前核对实际工具是否能读取页面、点击、输入及观察生成状态；浏览器环境上下文中的 URL 或 `open_in_codex` 只证明有页面入口，不证明有控制能力。后者返回 queued 时也不能声称页面已打开或已提交。

内置浏览器没有执行接口时，不为 Make 开发另建跨主机浏览器转发。核对当前主机已有的 Playwright 与 Chromium；用户允许替代浏览器时直接复用它们，用 [playwright-session.cjs](scripts/playwright-session.cjs) 在当前主机启动专用会话。配置、启动命令与操作参数见 [接口参考](references/operation-interfaces.md#当前主机的-playwright-会话)。登录态放私有数据目录，源码放技能目录；不复制其他浏览器的 Cookie 或登录数据库。用户明确只允许内置浏览器时，说明缺少哪项执行接口并等待该能力恢复。

页面提供密码登录时，调用 [readLogin()](scripts/read-login.cjs) 在内存读取凭据，按浏览器工具支持的方式填表。凭据保存在 macOS 钥匙串，skill、提示词和 Git 中只存引用。钥匙串与浏览器不在同一主机时，可经已有认证 SSH 将内存中的凭据通过 stdin 传给登录操作，不建立浏览器转发，不写明文凭据文件。登录后核对配置账号；MCP 用 `whoami` 核对同一身份，其 OAuth 会话与网页登录分别验证。

## 流程

已有 `/make/<fileKey>/...` 链接时，按意图分流：只读取或落地已有成果进入第 3 步；继续改稿则先读取当前聊天、生成状态和预览，在同一文件执行第 2 步，避免另建文件或重复提交。

1. **预填**：把需求收敛为目标、页面、交互、视觉、响应式与验收条件；只追问影响结果的缺项。将纯文本提示词写入临时文件，运行：
   ```sh
   node "<skill目录>/scripts/make-url.cjs" < "<提示词文件>"
   ```
   脚本按官方格式生成 `https://www.figma.com/make/new#prompt=...`，使用 `LZString.compressToEncodedURIComponent`；原文最多 50,000 UTF-16 码元。完成条件：链接可打开，输入框内容与需求一致。图片、设计引用等附件在浏览器中添加。
2. **生成或续改**：打开目标文件，核对账号、当前状态和提示词。用户要求改善外观时，先收集 2–3 个贴近产品类型的优秀设计实图，说明各自用于布局、图片呈现或信息层级，作为附件交给 Make；提出具体构图与视觉验收条件，不仅列产品名或要求“美化”。默认选择页面上当前可用的最强 Claude 模型：读取模型菜单，优先最高版本的 Claude Opus；如页面不提供或不能确认选择，记录实际模型或说明未能确认，不以提示词中的模型要求代替选择。用户要求生成即授权提交本次需求；简短告知会消耗 Figma AI credits，再点击页面上的 Submit／Send。仅要求整理或预览链接时停在预填。提交结果不明时先查聊天状态，确认未提交才重试；后续改稿按用户要求提交。完成条件：Make 结束生成、出现可交互预览，并取得实际 `/make/` 文件链接；先把该链接回传聊天。用浏览器检查关键交互及窄屏布局，失败则在同一聊天提出具体修正并复查。
3. **接回**：网页实际提供源码下载时可直接导出，读取下载文件正文。需要 MCP 时检查已认证的 Figma remote MCP 实际暴露的工具与资源能力。原生 MCP 客户端支持 resources 时列出 Make 文件并读取所需代码与资源；App 连接器则使用其实际暴露的入口，不额外用通用资源枚举探测 Apps。若插件通过 `get_design_context` 支持 Make，先加载可用的 `figma-design-to-code` 指引，按工具声明传入 `fileKey`，仅其声明支持 Make 时使用 `nodeId="0:1"`。返回 `resource_link` 只代表源码清单；必须实际读取文件正文才算接回。`Unknown resource` 等问题按 [阻塞处理](references/operation-interfaces.md#资源读取阻塞) 定位。按返回说明获取本地资源，适配现有组件、技术栈与数据接口。完成条件：所需源码和资源读取成功；用户要求落地时，完成实现、运行项目检查并对照 Make 预览验收。

Make 的截图及交互证据由浏览器获得。Figma Design 专用的 `get_screenshot`、`use_figma`、`get_metadata` 不能因名字相似而用于 Make；先核对工具声明。

未登录的 Make 页面可能显示文件不可用；登录后重新打开原链接再判断是否删除。提交失败时保留实际错误与请求 ID，先确认聊天是否已有任务；出现“Couldn’t connect to Figma”不能直接归因于 credits。浏览器不可用、无法向登录工具传递凭据、权限或 credits 不足时，报告具体阻塞并保留预填／Make 链接；生成或 MCP 读取失败时保留文件链接与错误。明确说明停在哪一步。

用户要求完善技能时，将已复现的阻塞、有效接口及验证边界写入接口参考；区分实际成功调用、仅有文档的接口和不可用能力。当前文件链接、提示词、源码清单等运行材料放私有工作目录，不写入公共技能仓库。接口记录不包含 Cookie、授权头、密码或会话令牌；未观察到的 Make 内部接口不靠猜测补齐。

官方依据：[预填链接](https://help.figma.com/hc/en-us/articles/43637422653719-Open-Figma-Make-with-a-prefilled-prompt) · [Make 资源接回](https://developers.figma.com/docs/figma-mcp-server/bringing-make-context-to-your-agent/) · [生成与 credits](https://help.figma.com/hc/en-us/articles/31304485164695-Create-a-Figma-Make-file)
