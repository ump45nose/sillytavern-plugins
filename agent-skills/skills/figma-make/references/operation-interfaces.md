# Figma Make 操作接口

## 选择入口

| 入口 | 能力 | 验证边界 |
| --- | --- | --- |
| 本机 Playwright 专用会话 | 已登录并操作 Make 的模型、提示词和提交 | 已接通页面控制；生成业务状态需独立确认 |
| 当前环境的浏览器控制工具 | 读取页面、点击、输入、模型菜单、聊天及预览 | 按实际工具声明调用；工具未暴露时不能用环境 URL 代替 |
| `codex_app.open_in_codex` | 请求在 Codex 面板打开 URL | 只打开 UI；queued 不代表完成打开，无 DOM／点击功能 |
| `https://www.figma.com/make/new#prompt=...` | 新建文件时预填提示词 | 已验证本地编码往返；不提交，不选择模型，不续改已有文件 |
| Figma MCP `whoami` | 验证 MCP OAuth 身份 | 与浏览器登录分别验证 |
| Figma MCP `get_design_context` | 获取 Make 源码上下文或资源清单 | 当前连接器已返回清单，文件正文尚未成功读取 |
| MCP `resources/read` | 读取 Make 源码资源 | 当前 App 聚合入口返回 `Unknown resource`；需要真正支持资源的 Figma 客户端 |
| 已有 Browser Relay | 操作已连接浏览器标签页 | 本次 `/api/tabs` 返回 200，列表为空；其他路由依据本机 browser-relay 技能，尚未在 Figma 实测 |

### 当前主机的 Playwright 会话

2026-10-12 已在 NAS 复用已有 Chromium 缓存，用配套 Playwright 运行专用会话，完成 Figma 登录、读取已有 Make 文件、选择 Claude Opus 5.5、输入需求和点击提交。无头浏览器默认 User-Agent 导致 Make 初始化和提交返回 CloudFront 403；保持账号和美国代理不变，改为同版本标准 Chrome User-Agent 后初始化恢复 200。生成提交也已返回 200，聊天中出现用户请求和 Make 的开发操作；生成已完成，已操作预览的导航、锁定、恢复自动、扫描、设置和窄屏布局，并导出源码 ZIP；“可操作页面”和“生成完成”分别判定。内置浏览器的 URL 上下文没有点击能力，当前方案不依赖 Mac 浏览器转发。

复用依赖前读取 Playwright core 的 `browsers.json`，将配套浏览器 revision/version 与现有 Chromium 对齐；页面能打开并不能证明下载兼容。本次旧 SDK 1.58.2 配套 Chromium 145 / revision 1208，而缓存浏览器是 Chromium 153 / revision 1243。已找到 1.63.0 正好配套 revision 1243，并将此运行时放在专用数据区，未改原业务项目依赖。对齐 SDK 后，完整 Chromium 153 的下载仍使浏览器以 SIGTRAP 退出，因此未确认 SDK 不匹配就是原生崩溃的原因。最终复用同 revision 的 Chromium Headless Shell，保留原登录目录，已验证 Make 源码 ZIP、基线 JPEG 与历史快照都保存成功。当前 NAS 方案使用 Playwright 1.63.0 + Headless Shell revision 1243；其他环境按实际浏览器配套版本选择。

启动时传入本机实际依赖路径，路径不写死到脚本：

```sh
FIGMA_PLAYWRIGHT_MODULE="<已有 playwright 模块绝对路径>" \
FIGMA_CHROMIUM_PATH="<已有 Chromium 可执行文件>" \
node "<skill目录>/scripts/playwright-session.cjs" serve
```

`serve` 是持续运行的进程，保持对应终端会话或在当前主机后台启动。操作中断后复用同一数据目录；若 socket 返回 `ECONNREFUSED`，先确认该专用进程已退出，再移除其遗留 socket 并重新启动，保留 profile。默认数据目录 `~/.local/share/figma-make/browser`，可用 `FIGMA_BROWSER_STATE_DIR` 改到现有私有数据区。持久登录态、截图、下载都放这里；控制仅使用该目录的 Unix socket，不开放 TCP 端口。无头模式默认用当前 Chromium 自身版本的标准 Chrome User-Agent，避免本次复现的 `HeadlessChrome` 403；可以用 `FIGMA_BROWSER_USER_AGENT` 显式指定。可选 `FIGMA_BROWSER_HEADLESS=false`；只有当前浏览器出站需要已有代理时设置 `FIGMA_BROWSER_PROXY`。

```sh
printf '%s' '{"op":"snapshot"}' | node "<skill目录>/scripts/playwright-session.cjs" call
```

| op | 参数 | 用途 |
| --- | --- | --- |
| goto | url | 打开已有 Make 文件或预填链接 |
| snapshot | frame? | URL 与页面无障碍树；先观察后定位 |
| click | selector, frame? | 点击观察到的元素 |
| hover | selector, frame? | 触发真实鼠标悬停，检查候选卡操作和 hover 状态 |
| fill | selector, text, frame? | 填入需求或表单 |
| upload | selector, paths, frame? | 向实际文件 input 添加本机参考截图或用户指定附件 |
| press | selector, key, frame? | 键盘操作 |
| viewport | width, height | 调整浏览器宽高，最终验收窄屏布局 |
| frames | 无 | 预览 iframe 的索引和地址 |
| evaluate | expression, frame? | 读取可见 DOM 或预览状态；字符串表达式中的函数需要显式调用，例如 `(() => ({title:document.title}))()` |
| screenshot | filename?, fullPage? | 截图保存到私有目录 |
| network | offset? | 请求的方法、origin、路径、类型、响应状态或失败原因；不记录查询值、请求体或授权头 |
| login | email, password, emailSelector, passwordSelector, submitSelector | 内存凭据填表，不打印密码 |
| downloads | 无 | 查询导出的 saving/saved/failed 状态、路径和字节数；保存完成后再离开页面 |
| close | 无 | 关闭会话和本地 socket |

当前 Make 空白文件实际控件：`[role="textbox"][aria-label="Make prompt"]`、`button[aria-label="Select model, Auto"]`、`[role="menuitemradio"]`、`button[aria-label="Send prompt"]`。进入已有聊天后输入框为 `[role="textbox"][aria-label="Prompt for AI agent"]`，发送按钮为 `button[aria-label="Send"]`。这些是本次观察，页面变化时重新 snapshot，不盲用旧选择器。模型菜单实际出现 Claude Opus 5.5 与 Sonnet 5.5，已选择 Opus 5.5；未来按菜单最高可用 Claude Opus 选择。

定位时区分按钮的可见文字与 `aria-label`：图标按钮在 snapshot 中有名称，DOM 可能没有文本；例如关闭操作应使用实际的 `button[aria-label="关闭"]`，不能将名称直接套进 `:has-text()`。

### 参考图附件入口

Make 的 `Add context` 菜单提供 `Upload files`，页面有支持 multiple 的隐藏 `input[type="file"]`。先读取 input 的 accept 和数量，再使用 `upload`；本次 accept 包含 PNG/JPEG/GIF，未列 WebP。参考网页截图用 PNG；原图格式不在 accept 内时，可用浏览器显示该公开参考图并截成 PNG。`screenshot` 的 `fullPage:false` 用于视口截图，避免把整篇营销页面当成布局参考。

本次已上传三张 PNG 参考图，确认三个缩略图已加载且 Send 可用后，成功提交同文件的视觉改稿。上传完成后检查附件缩略图、文件名和生成按钮状态，再填需求并提交。图片来自设计参考，不是用户图库；公共技能仅记录操作方法，参考素材和运行提示词保存在私有工作目录。外观验收需实际查看最终页面截图，分别检查构图、图片比例、层级、间距、控件和状态；功能通过不能代替视觉完成。

### 源码导出入口

本次在已有 Make 文件中，点击 `input[type="radio"][value="code"]` 进入 Code 面板，实际出现 Files 树和 `button[aria-label="Download code"]`。等待生成完成后点击此按钮，专用会话会将下载保存到数据目录的 `downloads/`。随后读 `downloads`，只有当前导出记录变成 `saved` 才切换视图或导航并读取压缩包；`saving` 时保持该页面。读取压缩包内源码正文后才算接回；不要在生成中途导出并当成最终版本。已复现导出回调 `download.saveAs: Target page, context or browser has been closed`；未处理的异步错误会结束控制进程。此错误也可能是浏览器原生崩溃的结果；本次已记录到完整 Chromium 的 SIGTRAP，不能仅凭 saveAs 报错认定页面切换或保存函数造成崩溃。脚本将实际保存失败记录为 `failed` 并保留控制连接，不自动重试。旧 ZIP 仍存在不代表这次导出成功；核对本次记录和源码内容，避免把上个版本当成改稿成果。本次已成功下载 ZIP，读取了 App.tsx、数据适配层和三个页面的源码正文。点击“下载”不等于已保存：以浏览器 download 事件与实际文件为证据；跨域图片的 `a[download]` 可能只打开图片，原型验收也应检查下载结果。

主菜单的 File 子菜单另有 `Save local copy…`、`Save to version history…`、`Show version history`；尚未验证这些入口的下载格式，不能把 local copy 自动当成源码 ZIP。不要为导出创建新 Make 文件或复制项目。

### Make 提交的连接错误

本次 `POST /api/cortex/shared/figmake` 返回 HTTP 403、`text/html`，CloudFront 页面写明 `Request blocked`；Make UI 仅显示 `Couldn’t connect to Figma`。这不等于账号 credits 不足，也不是没有点击权限。先观察请求状态并区分 CDN 拒绝与 Make 的业务错误。Chromium 不自动继承 shell 的 `HTTP_PROXY`；当前主机已有代理时用 `FIGMA_BROWSER_PROXY` 指定浏览器出站，保留登录目录。同一代理、同一账号下，标准 Chrome User-Agent 使 `ui_capabilities` 从 403 恢复 200；不能据此推导所有 403 都是这个原因。脚本默认处理这个已复现的浏览器兼容问题。失败的聊天未开始生成时才重试，不自动循环提交。

### 内置浏览器工具缺失的已知边界

Mac 桌面客户端经 codexhost 连接 NAS 时，本次 Mac 有本地 Browser 执行服务，NAS 当前会话未暴露所需的 Browser 执行接口。URL 可见不代表远程会话可点击，也不能据此断言 codexhost 主动过滤工具。[codexhost PR #164](https://github.com/BytePioneer-AI/codex-host/pull/164) 的验证记录区分本地 Mac 与 SSH 会话，不能仅凭本地修复要求用户反复重登。用户允许替代时优先使用当前主机已有可控浏览器，不继续搭转发或切换开发主机。

### Browser SDK 入口

Mac 内置 Browser 技能的标准入口是 `scripts/browser-client.mjs` 的 `setupBrowserRuntime()`，由技能指定的 `js` 工具执行。下列初始化来自已读取的完整 Browser 技能；本次 NAS 会话缺少执行工具，因此尚未实测。

```js
const { setupBrowserRuntime } = await import("<Browser 插件绝对路径>/scripts/browser-client.mjs");
const agent = await setupBrowserRuntime();
const iab = await agent.browsers.get("iab");
nodeRepl.write(await iab.documentation());
```

使用准确的 `iab` 选择器回应用户明确的内置浏览器要求。完整读取所选浏览器文档，再使用其 `tabs`、DOM、截图和交互能力；不从源码猜测隐藏方法，不使用独立 shell 或 CDP 通道绕过 SDK。该 Browser 技能要求只有指定的 `js` 工具能控制此浏览器；工具缺失时应修复接入或报告阻塞。

实际观察到的 Make 请求（仅用于排障及后续接口研究）：

| 方法、路径 | 页面用途 | 本次结果 |
| --- | --- | --- |
| POST `/api/cortex/shared/figmake/ui_capabilities` | Make 初始化能力 | 调整 User-Agent 后 200；初始化期间也出现 202 |
| POST `/api/cortex/shared/figmake` | 提交生成任务、接收输出 | 200，聊天开始开发 |
| POST `/api/cortex/shared/figmake/generate_title` | 自动生成文件标题 | 200，文件标题实际更新 |
| POST `/api/cortex/shared/figmake/generate_description` | 生成描述 | 200 |
| POST `/api/cortex/shared/figmake/detect_platform` | 识别目标平台 | 200 |
| GET `/api/source/v1/make/environment/<fileKey>` | 读取 Make 环境 | 初始化期间观察到 403，不能当成可靠的源码下载接口 |
| GET `/api/source/v1/make/cloud_mount_telemetry/<fileKey>` | 环境遥测 | 200 |

这些是页面网络观察，未实现独立 HTTP 客户端；不保存授权头、请求体或会话凭据，不猜测参数，不直接重放收费请求。模型选择和生成状态由网页控件确认；不要将 Design 写入工具或猜测的 `/api/...` 路径当成 Make agent 接口，也不将未经文档确认的桌面内部监听端口收录为可用接口。

## Figma MCP

连接地址：`https://mcp.figma.com/mcp`，复用已有 OAuth。提供者名称以当前客户端注册信息为准，不能将 App 聚合提供者名当成原生 Figma 资源服务器名。

读取 Make 前先加载 `figma-design-to-code`，按其要求传 `skillNames`。工具明确支持 Make 时：

```json
{
  "fileKey": "<从 /make/URL 提取>",
  "nodeId": "0:1",
  "clientFrameworks": "unknown",
  "clientLanguages": "unknown",
  "skillNames": "figma-design-to-code"
}
```

只在用户明确要求时设置 `forceCode`。不要将 `0:1` 扩展为其他 Figma 工具的通用 Make 节点。

返回的资源链接示例：

```text
file://figma/make/source/<fileKey>/src/App.tsx
file://figma/make/source/<fileKey>/package.json
```

这是 MCP 资源 URI，不是本地文件路径或可直接 HTTP 下载的地址。先读取 App.tsx 和 package.json，再按导入关系读取所需文件，保留资源清单以便补取。

### 资源读取阻塞

实际错误：`resources/read ... -32002 Unknown resource`。若 `get_design_context` 已成功返回清单，优先检查客户端资源转发及提供者路由；这个错误本身不能证明文件不存在或 Figma 无权限。

- 检查当前客户端是否真正暴露 Figma `resources/read`，使用注册的提供者及返回的 URI，不反复重试同一聚合入口。
- 若有独立且已认证的 Figma MCP 客户端，可以用其资源入口读取；不复制 OAuth 令牌到脚本、提示词或日志。
- 若资源能力不可用，但已有可控制的文件页面，可使用页面实际提供的源码导出功能；先观察，不猜测内部下载接口。
- 两条路径都不可用时保留 Make 链接、清单和原始错误，说明“清单已取得，源码正文未接回”。

官方文档明确此功能要求客户端支持 MCP resources：[Resources (Make → MCP)](https://developers.figma.com/docs/figma-mcp-server/bringing-make-context-to-your-agent/)。

## 已有 Browser Relay

只在用户选择此替代连接，且扩展与浏览器会话已经存在时使用。脚本必须运行在浏览器所在主机：NAS 的 `127.0.0.1` 不是 Mac 的 relay。默认 `http://127.0.0.1:18795`，不将本地 relay 暴露到网络。

以下接口来自本机 browser-relay 技能。除了 `/api/tabs`，本次未验证执行效果；连接后先 snapshot，再以实际页面定位元素，不保存可能变化的 Figma CSS 选择器。

| 方法、路径 | 输入 | 用途 |
| --- | --- | --- |
| GET `/api/tabs` | 无 | 取得已连接标签页的 id、title、url；空列表意味着当前没有可控标签页 |
| GET `/api/snapshot` | `tabId, format=text|html, maxLength` | 读取页面，定位模型菜单、聊天输入框和状态 |
| POST `/api/wait` | `tabId, selector, state=attached|visible, timeoutMs<=20000, pollMs` | 等待元素；之后读取聊天确认状态 |
| POST `/api/click` | `tabId, selector, doubleClick?` | 点击实际观察到的控件 |
| POST `/api/type` | `tabId, text, selector?, clear?, submit?` | 输入；是否提交必须显式决定 |
| POST `/api/key` | `tabId, key? / combo?` | 键盘操作 |
| POST `/api/scroll` | `tabId, direction, amount?` | 页面滚动 |
| POST `/api/eval` | `tabId, expression` | 读取 DOM 或验证预览状态；不读取凭据或会话存储 |
| GET `/api/screenshot` | `tabId, fullPage?` | 获取截图；返回格式按实际 relay 版本确认 |
| GET `/api/network` | `tabId, type?, status?, limit?, clear?` | 观察实际请求路径；relay 文档称敏感授权头会脱敏，不返回请求体 |
| POST `/api/download` | `tabId, selector` | 点击源码导出并捕获下载 |
| GET `/api/downloads` | 无 | 查询下载 |

提供可复用 JSON 调用脚本 [browser-relay.cjs](../scripts/browser-relay.cjs)：

```sh
node "<skill目录>/scripts/browser-relay.cjs" tabs
printf '%s' '{"tabId":123,"format":"text","maxLength":20000}' |
  node "<skill目录>/scripts/browser-relay.cjs" snapshot
node "<skill目录>/scripts/browser-relay.cjs" type < /private/tmp/figma-input.json
```

除 tabs、downloads 外需要显式 tabId。输入从 stdin 读取；不要把密码或令牌写入输入文件。脚本只发送一次请求，写操作超时后先观察页面，不能直接重发。网络输出在保存前还需核对脱敏效果；不要保存完整 HAR、Cookie 或私人照片请求。

## 状态判定

- **已打开**：读取到目标文件页面；不是仅取得打开请求回执。
- **已选模型**：模型控件实际显示所选 Claude 名称；提示词中的要求不是证据。
- **已提交**：聊天中出现本次消息或生成状态；输入框填好不是提交。
- **生成完成**：Make 给出完成结果，且预览能操作；取得文件链接不够。
- **接回完成**：读到所需源码正文和资源；清单不够。

续改前检查是否正在生成、已有排队消息或已有完成版本，避免重复扣 credits。验收覆盖用户的关键状态转换，再决定是否补发修正。

独立 Make 预览域名只作为当前运行入口。本次重新连接后旧地址返回 `{"error":"not found"}`；重新打开原 Make 文件并枚举当前 frames 后取得了有效入口。复用稳定 Make 文件链接，不长期缓存临时预览地址。
