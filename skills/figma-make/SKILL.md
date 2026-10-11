---
name: figma-make
description: Figma Make：整理需求，通过 Browser Relay、内置浏览器或桌面应用提交预填提示词，再经 Figma MCP 接回代码和资源。用于生成原型或继续实现已有 Make 文件。
---

# Figma Make

## 环境与登录

读取 [config.json](config.json) 中的账号、钥匙串引用和浏览器偏好。当前配置优先复用已登录 Chrome 的 Browser Relay，Mac 本地 Figma 应用作为后备；用户指定内置浏览器时先验证该入口。读取所用 browser-relay／Browser 技能及工具文档，再按实际接口操作。开始前核对能否读取页面、点击、输入及观察状态；环境 URL 或 `open_in_codex` 的 queued 回执不足以证明已打开、已提交。各入口的实测结果和调用方式见 [接口参考](references/operation-interfaces.md)。

Mac 客户端连接 NAS 等远程执行主机时，先按 [远程主机排查](references/operation-interfaces.md#远程主机上的浏览器工具缺失) 核对工具安装和执行位置。Mac 上启用 Browser 不代表远程会话已有 Browser SDK 执行接口；不要把 Mac 可执行文件路径直接加入 Linux 配置。

入口缺少控制能力或打开超时时，说明实际阻塞，再使用已配置的可用入口。Browser Relay 已连接即可复用；不自动安装扩展或更改系统权限。CLI 调用成功后仍需读取页面确认变化，尤其是模型菜单、输入框和 Send 的状态。

页面提供密码登录时，调用 [readLogin()](scripts/read-login.cjs) 在内存读取凭据，按浏览器工具支持的方式填表。凭据保存在 macOS 钥匙串，skill、提示词和 Git 中只存引用。登录后核对配置账号；MCP 用 `whoami` 核对同一身份，其 OAuth 会话与网页登录分别验证。

## 流程

已有 `/make/<fileKey>/...` 链接时，按意图分流：只读取或落地已有成果进入第 3 步；继续改稿则先读取当前聊天、生成状态和预览，在同一文件执行第 2 步，避免另建文件或重复提交。

1. **预填**：把需求收敛为目标、页面、交互、视觉、响应式与验收条件；只追问影响结果的缺项。将纯文本提示词写入临时文件，运行：
   ```sh
   node "<skill目录>/scripts/make-url.cjs" < "<提示词文件>"
   ```
   脚本按官方格式生成 `https://www.figma.com/make/new#prompt=...`，使用 `LZString.compressToEncodedURIComponent`；原文最多 50,000 UTF-16 码元。完成条件：链接可打开，输入框内容与需求一致。图片、设计引用等附件在浏览器中添加。
2. **生成或续改**：打开目标文件，核对账号、当前状态和提示词。默认选择页面上当前可用的最强 Claude 模型：读取模型菜单，优先最高版本的 Claude Opus；如页面不提供或不能确认选择，记录实际模型或说明未能确认，不以提示词中的模型要求代替选择。用户要求生成即授权提交本次需求；简短告知会消耗 Figma AI credits，再点击页面上的 Submit／Send。仅要求整理或预览链接时停在预填。提交结果不明时先查聊天状态，确认未提交才重试；后续改稿按用户要求提交。完成条件：Make 结束生成、出现可交互预览，并取得实际 `/make/` 文件链接；先把该链接回传聊天。用浏览器检查关键交互及窄屏布局，失败则在同一聊天提出具体修正并复查。
3. **接回**：检查已认证的 Figma remote MCP 实际暴露的工具与资源能力。原生 MCP 客户端支持 resources 时列出 Make 文件并读取所需代码与资源；App 连接器则使用其实际暴露的入口，不额外用通用资源枚举探测 Apps。若插件通过 `get_design_context` 支持 Make，先加载可用的 `figma-design-to-code` 指引，按工具声明传入 `fileKey`，仅其声明支持 Make 时使用 `nodeId="0:1"`。返回 `resource_link` 只代表源码清单；必须实际读取文件正文才算接回。`Unknown resource` 等问题按 [阻塞处理](references/operation-interfaces.md#资源读取阻塞) 定位。按返回说明获取本地资源，适配现有组件、技术栈与数据接口。完成条件：所需源码和资源读取成功；用户要求落地时，完成实现、运行项目检查并对照 Make 预览验收。

Make 的截图及交互证据由浏览器获得。Figma Design 专用的 `get_screenshot`、`use_figma`、`get_metadata` 不能因名字相似而用于 Make；先核对工具声明。

浏览器不可用、无法向登录工具传递凭据、权限或 credits 不足时，报告具体阻塞并保留预填／Make 链接；生成或 MCP 读取失败时保留文件链接与错误。明确说明停在哪一步。

用户要求完善技能时，将已复现的阻塞、有效接口及验证边界写入接口参考；区分实际成功调用、仅有文档的接口和不可用能力。当前文件链接、提示词、源码清单等运行材料放私有工作目录，不写入公共技能仓库。接口记录不包含 Cookie、授权头、密码或会话令牌；未观察到的 Make 内部接口不靠猜测补齐。

官方依据：[预填链接](https://help.figma.com/hc/en-us/articles/43637422653719-Open-Figma-Make-with-a-prefilled-prompt) · [Make 资源接回](https://developers.figma.com/docs/figma-mcp-server/bringing-make-context-to-your-agent/) · [生成与 credits](https://help.figma.com/hc/en-us/articles/31304485164695-Create-a-Figma-Make-file)
