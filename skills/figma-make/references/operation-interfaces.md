# Figma Make 操作接口

## 选择入口（2026-10-12，Mac 本地实测）

| 入口 | 能力 | 验证边界 |
| --- | --- | --- |
| Browser Relay + 已登录 Chrome | DOM、点击、输入、键盘、截图、网络观察 | Make 文件、模型菜单、中文输入和清空均成功；适合 Codex／Claude Code 共用 CLI |
| 本地 Figma + `cua.getApp("Figma")` | 原生辅助功能树、点击、粘贴、截图 | 已打开 Make，模型菜单及中文粘贴成功；`typeText` 本次未生效 |
| Codex 内置浏览器 + `cua` | 按返回文档控制页面 | 选取 IAB 成功，打开 Make 超时 30 秒；未验证后续控制，不能推断所有环境不可用 |
| `codex_app.open_in_codex` | 请求在 Codex 面板打开 URL | 只打开 UI；queued 不代表完成打开，无 DOM／点击功能 |
| `https://www.figma.com/make/new#prompt=...` | 新建文件时预填提示词 | 已验证本地编码往返；不提交，不选择模型，不续改已有文件 |
| Figma MCP `whoami` | 验证 MCP OAuth 身份 | 与浏览器登录分别验证 |
| Figma MCP `get_design_context` | 获取 Make 源码上下文或资源清单 | 当前连接器已返回清单，文件正文尚未成功读取 |
| MCP `resources/read` | 读取 Make 源码资源 | 当前 App 聚合入口返回 `Unknown resource`；需要真正支持资源的 Figma 客户端 |

本次只在已有空 Make 文件填入测试文字，随后清空，模型保持 Auto；没有点击 Send，没有消耗生成 credits。当前菜单实际提供 Claude Opus 5.5；后续仍读取菜单选择，版本不写死。

### 本地 Figma 操作

`cua` 首次调用单独执行 `await cua.getApp("Figma")`，阅读返回文档后再操作。通过最新辅助功能树定位文件、模型按钮和提示词框；点击输入框后用 `app.paste(text)` 输入中文。验证树中的输入值和 Send 是否启用；本次 `typeText` 无变化，不能据调用回执判定成功。点击模型按钮打开菜单，选实际提供的 Claude Opus，再读取按钮名称确认。

原生应用可以复用现有登录。使用页面或应用实际提供的打开文件入口，不猜测桌面内部端口。官方依据：[桌面应用](https://help.figma.com/hc/en-us/articles/5601429983767-Guide-to-the-Figma-desktop-app) · [打开文件链接](https://help.figma.com/hc/en-us/articles/360039824334-Open-links-in-the-desktop-app)。

### 远程主机上的浏览器工具缺失

先前 NAS 会话的观察：Mac 桌面客户端经 codexhost 连接 NAS。Mac 配置启用了 Browser，且本地会话的 `node_repl` 服务启动成功；NAS 的已安装插件没有 Browser，`codex mcp list --json` 为空，远程会话启动日志只有 `codex_apps`，工具集合中没有 Browser 所需的执行接口。Mac 能打开标签页及提供 URL 上下文，并不能填补远程执行主机的工具缺口。本轮已切换 Mac 本地执行，不把该旧阻塞视为当前状态。

排查时分别检查客户端与执行主机：

1. 执行主机的当前技能目录、已安装插件、实际暴露的工具。Browser 控制可能通过 `node_repl`／`cua_repl` 的 `js` 加 SDK 提供，不能只按 `browser` 工具名称搜索。
2. Mac 的 Browser 插件、控制服务启动状态。`computer-use` 的启动错误不能代替 Browser 服务状态；本次独立的 `computer-use` 相对路径报 ENOENT，但本地 `node_repl` 已 ready。
3. 桌面日志中的远程 hostId、当前 threadId 及 MCP 启动记录。没有工具接入记录时，先定位主机配置和转发，不重复登录 Figma。
4. 标签页所属会话。临时会话与正式会话绑定异常可能影响标签页选择，但不能据此断言它造成工具未暴露；二者分别记录、分别验证。

本次检查到的 codexhost 代码转发原生会话请求，没有找到将 Mac Browser MCP 接入 NAS 的路径；这仍是当前安装的观察，不能推导为所有版本不支持。未进行禁用 codexhost 的对照，不能断言插件主动过滤了浏览器工具。

上游 [codexhost PR #164](https://github.com/BytePioneer-AI/codex-host/pull/164) 的验证边界也明确区分两种情况：本地 Mac 会话已验证 IAB 交互，SSH 测试会话仍未暴露对应 IAB。该修复处理 helper 启动与原生 Computer Use，不声称解决 SSH 浏览器会话匹配。因此不能仅据“Browser 修复已合并”要求用户反复更新或重登。

[OpenAI 远程连接说明](https://learn.chatgpt.com/docs/remote-connections) 明确工具、MCP、技能和浏览器访问来自所连接主机的配置；SSH 项目会话在远程主机运行。此说明支持先核对执行主机，而非假定桌面客户端配置自动共享。

短期可用路径是把浏览器操作放在 Mac 本地执行会话，源码开发仍通过已有 SSH／远程连接操作 NAS。若要求保留 NAS 执行会话，则需提供受支持的 Mac 浏览器工具转发；复制插件或扩大文件权限本身不解决主机与会话绑定。更改会话执行主机前说明工作目录影响，并验证 Browser 技能和执行接口确实出现，不能仅凭设置保存报告修复。

### Browser SDK 入口

先前读取的另一版 Browser 技能使用 `scripts/browser-client.mjs` 的 `setupBrowserRuntime()`，由技能指定的 `js` 工具执行；NAS 会话缺少执行工具，未实测该入口。本轮工具提供 `cua.getBrowser({ id: "iab" })`，应以当前工具文档为准，不混用不同版本的 SDK。

```js
const { setupBrowserRuntime } = await import("<Browser 插件绝对路径>/scripts/browser-client.mjs");
const agent = await setupBrowserRuntime();
const iab = await agent.browsers.get("iab");
nodeRepl.write(await iab.documentation());
```

使用准确的 `iab` 选择器回应用户明确的内置浏览器要求。完整读取所选浏览器文档，再使用其 `tabs`、DOM、截图和交互能力；不从源码猜测隐藏方法，不使用独立 shell 或 CDP 通道绕过 SDK。该 Browser 技能要求只有指定的 `js` 工具能控制此浏览器；工具缺失时应修复接入或报告阻塞。

Make 生成提交、模型选择和任务状态尚无可复用的直接 HTTP 契约。当前通过已验证的 Relay 接口操作页面；不要将 Design 写入工具或猜测的路径当成 Make agent 接口。已观察到的请求见下文。

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

当前用户已选择并连接 Browser Relay，配置将其设为首选。脚本运行在浏览器所在主机：NAS 的 `127.0.0.1` 不是 Mac 的 relay。默认 `http://127.0.0.1:18795`，不将本地 relay 暴露到网络。

以下接口来自本机 browser-relay 技能。tabs、navigate、snapshot、click、type、key、eval、screenshot、network 已实测；wait、scroll、download、downloads 尚未在 Figma 实测。连接后先 snapshot，再以实际页面定位元素。

| 方法、路径 | 输入 | 用途 |
| --- | --- | --- |
| GET `/api/tabs` | 无 | 取得已连接标签页的 id、title、url；空列表意味着当前没有可控标签页 |
| POST `/api/navigate` | `tabId, url` | 打开预填或已有 Make 链接 |
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
printf '%s' '{"tabId":"<tabId>","format":"text","maxLength":20000}' |
  node "<skill目录>/scripts/browser-relay.cjs" snapshot
node "<skill目录>/scripts/browser-relay.cjs" type < /private/tmp/figma-input.json
```

除 tabs、downloads 外需要显式 tabId。输入从 stdin 读取；不要把密码或令牌写入输入文件。脚本只发送一次请求，写操作超时后先观察页面，不能直接重发。网络输出在保存前还需核对脱敏效果；不要保存完整 HAR、Cookie 或私人照片请求。

### Make 页面控件

本次 snapshot 没有列出 contenteditable 输入框；通过 eval 查看 DOM 的 role、aria-label 和 disabled 属性后定位。以下选择器是本轮观察结果，使用前重新确认页面：

| 控件 | 已观察到的选择器 | 操作后确认 |
| --- | --- | --- |
| 提示词 | `[role="textbox"][aria-label="Make prompt"]` | `innerText` 与输入一致 |
| 模型按钮 | `button[aria-label^="Select model,"]` | 名称显示实际选择的模型 |
| 提交 | `button[aria-label="Send prompt"]` | `disabled` 属性；提交后读取聊天／生成状态 |

输入可用 `browser-relay type '<text>' --selector '<已确认选择器>' --tab <tabId>`，仅明确生成时加提交动作。菜单打开时，本次 Escape、点击提示词和键盘清空都未生效；再次点击模型按钮关闭菜单后，eval 调用输入框的 `.focus()`，再 `key Meta+A`、`key Backspace` 才成功清空。每步观察状态，避免把错误焦点下的按键回执当成修改成功。

### Figma 页面实际 HTTP 请求

在已登录 Make 标签页中观察，再通过同源 `fetch` 复用会话；不导出 Cookie 或授权头。内部接口没有官方稳定性承诺，本轮只验证以下一个只读调用，不重放 POST。

| 方法、路径 | 参数／结果 | 验证边界 |
| --- | --- | --- |
| GET `/api/make/make_libraries` | `file_key=<fileKey>`；200，`error=false`，`meta` 包含 `source/org/workspace/team` 数组 | 页面请求和同源 fetch 都成功；当前文件各组为空 |
| GET `/api/source/v1/make/cloud_mount_telemetry/<fileKey>` | 页面带 `guid` 返回 200；省略 `guid` 返回 400 | 只观察参数名；不是源码下载接口 |
| GET `/api/source/v1/make/environment/<fileKey>` | 页面带 `guid` 返回 403 | 当前会话未成功，不作为可用源码入口 |
| POST `/api/cortex/shared/figmake/ui_capabilities` | 页面返回 200 | 请求体未捕获，未重放，用途未确认 |
| POST `/api/make/<fileKey>/rollout_metadata` | 页面返回 200 | 请求体未捕获，未重放，用途未确认 |

在 Relay 的 eval 中可执行已验证的只读查询：

```js
(async () => {
  const fileKey = location.pathname.split("/")[2]; // 已确认当前是 /make/ 页面
  const response = await fetch("/api/make/make_libraries?" +
    new URLSearchParams({ file_key: fileKey }));
  return { status: response.status, data: await response.json() };
})()
```

`/api/network` 的响应事件不含方法时，用同一 `requestId` 的请求事件补齐。记录仅保留方法、路径模板、参数名、状态和返回结构；文件／团队 ID 替换为占位符，删除查询值、头和响应正文。Relay 不捕获请求体，路径名与 200 都不足以证明掌握生成接口。生成继续走页面，源码继续走 Figma MCP resources 或实际可用的导出入口。

## 状态判定

- **已打开**：读取到目标文件页面；不是仅取得打开请求回执。
- **已选模型**：模型控件实际显示所选 Claude 名称；提示词中的要求不是证据。
- **已提交**：聊天中出现本次消息或生成状态；输入框填好不是提交。
- **生成完成**：Make 给出完成结果，且预览能操作；取得文件链接不够。
- **接回完成**：读到所需源码正文和资源；清单不够。

续改前检查是否正在生成、已有排队消息或已有完成版本，避免重复扣 credits。验收覆盖用户的关键状态转换，再决定是否补发修正。
