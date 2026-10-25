# 工作台按需附加插件

记录导出采用工作台附加插件形式，随工作台完整目录交付，不依赖酒馆助手脚本，不增加酒馆启动时加载的独立扩展。现有右栏、XML 行内保留／排除、预览和下载行为沿用。

## 使用

「扩展 → 工作台附加功能」可启停。默认启用以兼容已有工具栏配置；启用本身不会下载或分析任何聊天。首次点击输入工具栏或右栏分类中的「记录导出」，才读取插件清单并加载入口 JS、独立 CSS 和分析 Worker。

停用隐藏工具栏及右栏入口，保留常用工具的顺序和选择。重新启用后恢复。开关随酒馆用户设置保存，刷新后有效。常用工具页中仍可查看、移除停用插件的已选入口。

关闭右栏、切换其他工作区、停用附加插件或退出工作台，会卸载导出组件、终止 Worker 并移除该工作区的 CSS。加载过程中关闭不会启动迟到的分析任务。已加载的 ESM 模块由浏览器缓存，重新打开复用代码并创建新的快照；浏览器不支持从模块缓存卸载 JavaScript，刷新网页后会重新按需加载。

## 边界与目录

| 对象 | 位置 | 作用 |
| --- | --- | --- |
| 元数据目录 | `src/addons/catalog.ts` | 入口名称、开关和已交付版本，不导入功能代码 |
| 通用协议与加载器 | `src/addons/types.ts`、`src/addons/loader.ts` | API v1、清单校验、动态加载、样式生命周期 |
| 工作区容器 | `src/ui/AddonWorkspace.tsx` | 异步载入、关闭处理、局部错误与重试 |
| 记录导出源码 | `src/addons/record-export/` | UI、XML 解析、样式、Worker 与插件入口 |
| 插件清单 | `extension/addons/record-export/manifest.json` | ID、协议、版本、JS／CSS 相对路径、按需加载声明 |
| 构建结果 | `extension/dist/addons/record-export/` | `index.js`、`index.css`、`export-worker.js` 与 source maps |

核心通过清单 URL 动态 import，不再静态引用 ChatExport。同一构建共享 React 与公共控件，避免重复 React 导致 Hooks 不兼容。导出 CSS 从核心 CSS 移出；XML 解析只进入 Worker。入口本身没有聊天读取或自动分析副作用。

插件获得冻结的能力对象：订阅状态、读取聊天标识及忙碌状态、取得文本快照、定位原楼层、下载文件、调用既有 JSONL 备份。没有工作台配置、聊天编辑、模型生成或凭据接口。JSONL 备份仍沿用酒馆现有行为（原接口会先保存当前聊天），XML 筛选与 TXT／Markdown 下载不修改聊天原文。

清单和模块都校验 ID、API 版本，资源路径限制在同源工作台扩展目录。资源缺失、加载失败或插件渲染错误只显示在该临时工作区，不卸载主工作台；加载失败提供重试。未来更新插件资源时同步更新清单版本和目录中的版本标记，资源请求携带插件版本以避免旧缓存。

## 构建和交付

执行 `npm run build` 同时生成主入口与附加插件入口。交付整个 `extension/`，包括清单和所有共享 chunks，不能只复制插件的 `index.js`。附加插件不是单独注册到 SillyTavern 扩展列表的脚本；由工作台的附加功能页管理，不要在酒馆助手中重复安装。

源码、服务配置与聊天数据继续分离。本次不修改 Compose、持久卷、原生核心或启动顺序。

## 验证

- `npm run check`、`npm test`：类型、语法与现有解析／保留数据用例。
- `npm run verify:addons`：真实酒馆中的零启动请求、启停保存、迟到加载处理、Worker 和 CSS 释放、缓存复用及缺失文件重试。
- `npm run verify:utilities`：142 条聊天、组合 XML 规则、下载内容、手动标签、聊天切换、取消任务与 Noval／RP 布局。

网页验证回放设置及聊天写入，不改共享账号。检查图和机器报告位于忽略入库的 `artifacts/addons/`、`artifacts/utility-tools/`。

## API v2：大纲与生图

记录导出保持 API v1。新模块使用 v2，增加 Sidebar/Workspace/完整编辑视图、createRuntime 和独立任务生命周期。`src/addons/runtime.ts` 的轻量管理器和 `src/host/addon-api.ts` 的完成事件桥随主界面加载，不导入业务模块。任务运行对象按 HostAdapter/当前聊天缓存，关闭 UI 只释放 CSS 和 UI 订阅；聊天切换、停用或退出工作台释放运行对象并取消任务。

数据以 `chatMetadata.workbench_addons[id]` 隔离；生图配置存 `extensionSettings.workbench.addonSettings[id]`。宿主能力是冻结对象，提供按插件命名空间的保存、独立连接请求、原输入/续写及原生图片附件；不暴露上下文或密钥仓库。聊天保存串行、使用当前最新元数据/消息，生成期间等待空闲；保存成功前不推进写作轮数。图片目标捕获聊天、消息对象标识和回复签名，附件写入前后再次验证。HTTP 局域网使用 getRandomValues 生成标识，不依赖仅安全上下文可用的 randomUUID。

生图引擎仅导入固定提交的 QIG 库，无上游自动初始化/界面。已有原生 OpenAI/NovelAI 服务转发可选复用，其余自定义后端浏览器直连。ComfyUI 不使用全局 interrupt。数据库总结保留 `summary()` 只读接口，当前返回 null。

完整操作、后端要求及验证见 [大纲与生图](../workbench-writing-addons.md)。
