---
name: figma-make
description: Figma Make：整理需求，用内置浏览器提交预填提示词，再经 Figma MCP 接回代码和资源。用于要求 Make 生成原型，或继续实现已有 Make 文件。
---

# Figma Make

## 环境与登录

读取 [config.json](config.json) 中的账号与钥匙串引用。只使用当前 Codex／Claude Code 提供的内置浏览器，按其工具文档操作并复用登录会话。

页面提供密码登录时，调用 [readLogin()](scripts/read-login.cjs) 在内存读取凭据，按浏览器工具支持的方式填表。凭据保存在 macOS 钥匙串，skill、提示词和 Git 中只存引用。登录后核对配置账号；MCP 用 `whoami` 核对同一身份，其 OAuth 会话与网页登录分别验证。

## 流程

已有 `/make/<fileKey>/...` 链接时，从第 3 步接回。

1. **预填**：把需求收敛为目标、页面、交互、视觉、响应式与验收条件；只追问影响结果的缺项。将纯文本提示词写入临时文件，运行：
   ```sh
   node "<skill目录>/scripts/make-url.cjs" < "<提示词文件>"
   ```
   脚本按官方格式生成 `https://www.figma.com/make/new#prompt=...`，使用 `LZString.compressToEncodedURIComponent`；原文最多 50,000 UTF-16 码元。完成条件：链接可打开，输入框内容与需求一致。图片、设计引用等附件在浏览器中添加。
2. **生成**：内置浏览器打开链接，核对账号和提示词。用户要求生成即授权提交本次需求；简短告知会消耗 Figma AI credits，再点击页面上的 Submit／Send。仅要求整理或预览链接时停在预填。提交结果不明时先查聊天状态，确认未提交才重试；后续改稿按用户要求提交。完成条件：Make 结束生成、出现可交互预览，并取得实际 `/make/` 文件链接；先把该链接回传聊天。
3. **接回**：检查已认证的 Figma remote MCP 实际暴露的工具与资源能力。支持 resources 时先列出 Make 文件，再读取所需代码与资源；若插件通过 `get_design_context` 支持 Make，先加载可用的 `figma-design-to-code` 指引，按工具声明传入 `fileKey`，仅其声明支持 Make 时使用 `nodeId="0:1"`。两种入口均不可用时报告阻塞。按返回说明获取本地资源，适配现有组件、技术栈与数据接口。完成条件：所需源码和资源读取成功；用户要求落地时，完成实现、运行项目检查并对照 Make 预览验收。

浏览器不可用、无法向登录工具传递凭据、权限或 credits 不足时，报告具体阻塞并保留预填／Make 链接；生成或 MCP 读取失败时保留文件链接与错误。明确说明停在哪一步。

官方依据：[预填链接](https://help.figma.com/hc/en-us/articles/43637422653719-Open-Figma-Make-with-a-prefilled-prompt) · [Make 资源接回](https://developers.figma.com/docs/figma-mcp-server/bringing-make-context-to-your-agent/) · [生成与 credits](https://help.figma.com/hc/en-us/articles/31304485164695-Create-a-Figma-Make-file)
