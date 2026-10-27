# SillyTavern Workbench · Novel / RP · 桌面与 PWA

基于官方 SillyTavern 1.19.0 的前端工作台扩展。首版采用已确认的暖纸布局，保留原生聊天、输入节点、模型调用与数据格式。

## 当前可用入口

| 实例 | 地址 | 用途 |
| --- | --- | --- |
| 官方基线 | http://192.168.31.201:32011 | 官方运行时与性能对照 |
| 工作台验证版 | http://192.168.31.201:32012 | Novel / RP 桌面和手机工作台、酒馆助手与合成测试数据 |

使用现有测试账号；凭据保存在项目 `.env`，不纳入 Git。生产实例 `32001` 的部署见下方「部署到生产」。验证实例内不要保存需要保留的真实聊天，测试会修改明确命名的合成角色、世界书、预设等数据。

默认挂载工作台：1024px 及以上使用桌面布局，更窄窗口使用已确认的 PWA 布局。桌面右上控件、手机顶栏三点菜单可切换 Novel / RP / 原生；原生页面保留工作台切换入口。检测到 `storyWorkspace` 时停止挂载，避免两个布局插件同时接管页面。移动操作见 [PWA 使用说明](docs/workbench-pwa.md)。

## 首版功能

- 角色头像、连接 / 预设 / 世界书 / Persona 快捷选择与下一个；左侧大纲、楼层、最近对话；默认收起的右侧资源栏。
- 原生 Markdown 原文输入、顶部横线拖动增高、续写、重生成、快速回复、附件和扩展工具。消息、输入、助手 iframe 不搬移或重建。
- 世界书双列表和独立四区编辑，列表上切换激活方式；全局启用、关键词 / 常驻 / 向量化分别操作。JSON 编辑保留扩展字段。
- 收藏角色、全部 / 当前角色、角色字段编辑、独立管理、筛选、批量标签、PNG 导出及删除。批量删除保留聊天文件，当前角色须先切换再删除。
- 连接标题弹出按模型分组的配置列表；表头新建、记录、删除，API 模型和连接／测试在最前。完整原生 API 表单直接嵌入右栏，保持服务商专属选项、凭据管理和保存链路，不另建凭据存储。
- 预设标题弹出选择，主体显示完整宽度的提示词启停列表和原文编辑器；流式／思维链常驻，数值输入紧凑，常用参数可配置，其他参数和文件管理收纳。支持独立深度编辑、原始 JSON 辅助视图和连接／模型绑定；连接绑定优先。
- Persona 右栏直接管理名称、描述、注入位置／深度／角色、世界书绑定、默认／锁定关系和全局偏好；表头提供头像、新建、复制，保留统计、名称同步和备份恢复等入口。
- Trace 展示浏览器实际生成请求、组装事件快照和真实世界书激活事件。最近 20 条，仅内存，正文快照上限 128 KiB；导出前过滤认证字段。
- 按需加载的「记录导出」附加插件在右边栏扫描完整当前聊天的 XML 结构，支持按标签提取／排除、楼层和消息类型筛选、关键词搜索、预览与 TXT／Markdown 下载。分析在后台 Worker 运行，仅处理导出副本。

世界书是多选资源，“下一个”浏览下一本详情，不会清空其他已启用世界书。正文编辑默认收纳，双击条目或点击右侧编辑图标展开。编辑冲突或保存失败保留草稿；未保存关闭时提醒。大纲和生图以按需附加功能交付，见 [使用说明](docs/workbench-writing-addons.md)。大纲在左栏；手动生图入口位于正文铅笔旁，不增加输入框底部入口。

## 主题与快捷键

[Noval · Paper 主题](themes/noval-paper.json) 可从酒馆原生 UI 主题入口导入；也可将 [主题 CSS](themes/noval-paper.css) 放入自定义 CSS。插件自带默认样式，因此不导入也可使用。主题只负责表现，布局与行为由插件负责。主题变量用 `--wb-theme-*` 命名，可独立调整颜色和正文字体。

左下「快捷键」可录入工作台操作的组合键、清除绑定、关闭快捷键或恢复默认；重复绑定会提示冲突。以下为默认组合，角色侧栏默认不绑定：

| 默认快捷键 | 操作 |
| --- | --- |
| Alt + Shift + 1 / 2 / 3 / 4 | 连接 / 预设 / 世界书 / 用户设定 |
| Alt + Shift + N | 下一个连接 |
| Alt + Shift + L | 收纳左栏 |
| Alt + Shift + T | Trace |
| Alt + Shift + F | 进入／退出专注 |

发送与 Markdown 编辑快捷键沿用酒馆设置，不覆盖中文输入法组合输入。

阅读区右上「T」可调字体、字号、行距和正文左右留白。留白默认左右各 64px，可在 24–128px 间调整；窄阅读区会限制有效留白以保留正文宽度。配置随酒馆用户设置保存，独立用户设置的阅读排版区同步使用。

「用户设置 → 常用工具」可搜索、勾选和排序聊天菜单／魔法棒中的工具，选定入口直接显示在原生输入框底栏，Noval 与 RP 共用。空间不足时自动放入「更多工具」，停用插件的入口保留但禁用。默认固定「记录导出」；也可从右栏分类菜单进入导出工作区。「扩展 → 工作台附加功能」可启停；启用不触发加载，首次点击入口才载入插件 JS、CSS 和 Worker。关闭工作区释放 Worker 与样式，工具栏配置保留。无需安装酒馆助手脚本，详见 [附加插件说明](docs/architecture/workbench-addons.md)。

「用户设置 → 加载诊断」显示当前浏览器的导航、资源请求、酒馆就绪和工作台挂载耗时，保存本标签页最近五次记录并可下载报告。此功能用于定位等待阶段，不会提前解除加载遮罩。使用范围见 [临时工具工作区](docs/architecture/utility-workspace.md)，调查结果见 [启动加载诊断](docs/architecture/startup-diagnostics.md)。

## 构建与运行

资源中心联动是独立扩展：`resource-center-extension/` 安装到酒馆扩展目录，
`server/resource-center-link/` 安装到 `plugins/resource-center-link/`，开启服务端插件后重启。
支持酒馆 1.19.0 和 Node.js 22 以上，不依赖工作台。
`npm run build:resource-center` 生成独立安装包；`npm run deploy:resource-center -- --dry` 查看本机部署目标。
扩展设置使用中心 `/api/v2/access` 签发的两种凭据：`rp`（`rpRegistration=true`）与
`connector`（`target=sillytavern`），两者绑定同一 `sourceId/rpInstanceId/rpUserId`。
配置及待发事件保存在酒馆用户数据目录的加密日志，保存同步不访问模型上游。
关闭页面时只补交已有事件，中心下发等待开页应用；真实调用仅上传元数据。
工作台安装时支持归档原因联动；恢复显示不会恢复连接可用性。

```bash
npm ci
npm run build
npm run prepare:baseline
npm run start
```

官方 release、镜像 digest 和酒馆助手资产快照由 `baseline.lock.json` 固定。准备脚本检查版本，不初始化覆盖现有数据；需要本机已有锁定镜像，可按 lock 中的 reference 获取。`WB_HELPER_SOURCE` 可指定另一台机器上的同版本酒馆助手资产。

验证实例继续使用 `third-party/workbench-probe` 扩展目录标识，将原探针升级为工作台，避免重复加载。部署文件是 `extension/` 整个目录，修改 `src/` 后必须重新 `npm run build`。`extension/dist` 不进入工作分支。本仓库是开发与本地调试环境，不直接对外安装。发布产物在三个独立仓库，由 GitHub Actions 每 4 小时自动跟随本仓库 `main` 分支构建（也可在发布仓手动运行 publish）：

- 前端扩展 [ump45nose/noval-workbench](https://github.com/ump45nose/noval-workbench)：酒馆「扩展 → 安装扩展」直接填该地址。
- 性能扩展 [ump45nose/wb-perf](https://github.com/ump45nose/wb-perf)：同样按地址安装，来自 `perf-extension/`，无构建步骤；替代 cocktail，二者不要同时启用。
- 服务端插件 [ump45nose/workbench-sync](https://github.com/ump45nose/workbench-sync)：克隆到酒馆 `plugins/` 目录，开启 `enableServerPlugins` 后重启；提供 IDE 同步与设置 / 角色列表响应缓存。

三者都不修改酒馆源码；工作台不依赖另外两个也能运行。没有核心补丁或额外数据库。

## 部署到生产（fn 192.168.31.201）

生产实例 http://192.168.31.201:32001（容器 `sillytavern`，官方 1.19.0 镜像，编排 `/vol2/1000/Docker/stacks/ai/compose.yaml`）。数据卷 `/vol2/1000/Docker/sillytavern/{config,data,extensions,plugins,backups}` 与本仓库分离，部署不触碰数据与凭据。

```bash
npm run deploy             # 构建 → check 门禁 → 两个前端扩展 rsync → 插件按内容更新（变更则重启容器）→ 探活
npm run deploy -- --dry    # 只打印将执行的命令
npm run deploy -- --skip-build --skip-check   # 产物已就绪时跳过构建与门禁
npm run deploy -- --no-restart                # 插件更新但不重启（下次容器重启生效）
```

- 前端扩展部署到 `extensions/workbench/`，性能扩展 `perf-extension/` 部署到 `extensions/wb-perf/`（静态副本，刷新页面生效；验证实例 32012 走 Git 检出挂载，不经此脚本）。
- 服务端插件部署 `server/workbench-sync/dist/index.mjs` 到 `plugins/workbench-sync/`，sha256 有变化才同步并 `docker restart sillytavern`。
- 探活：等服务端可连接后，两个扩展的 manifest 返回 200/401、`/api/plugins/workbench-sync/info` 非 404、容器 running。
- 覆盖目标用环境变量：`WB_DEPLOY_SSH`（默认 `nas`）、`WB_DEPLOY_ROOT`、`WB_DEPLOY_CONTAINER`、`WB_DEPLOY_URL`。
- 清理归档与历史备份在 `/vol2/1000/Docker/sillytavern/{archive,backups}`；回滚 = 归档目录搬回 + `git checkout` 旧产物重跑 deploy。


```bash
npm run check              # TypeScript、观察器与测试模型语法
npm test                   # 保存冲突 / 数据保留 / Trace 单元测试
npm run verify             # 原生生成、助手、回退、停用与手机挂载回归
npm run verify:workbench    # 工作台配置、编辑、布局与 Trace
npm run verify:compat      # 批量角色、快捷回复、STscript、附件、正则与保存失败
npm run verify:interactions # 菜单、阅读、九类设置、批量资源、聊天文件与草稿恢复
npm run verify:fidelity    # 1496×817 主尺寸、原组件迁移、管理密度与四种桌面尺寸
npm run verify:motion      # 输入展开中间帧、固定标题与背景单行工具栏
npm run verify:click-motion # 真实酒馆鼠标点击：开合、勾选、编辑与页面切换，并录制视频
npm run verify:preferences  # 两侧留白、选中样式和自定义快捷键的真实页面／刷新验证
npm run verify:rp           # RP 原生发送、流式、翻段、iframe、显隐与阅读模式回归
npm run verify:addons       # 按需加载、启停保存、关闭释放、缺失文件与重试；不写账号数据
npm run verify:utilities    # 常用工具、右栏 XML 导出、RP 共用与加载诊断；不写账号数据
npm run benchmark:startup   # 保留 HTTP 缓存的打开／刷新测量；不写账号数据
npm run benchmark          # 冷 / 热启动对照；结束恢复隔离实例设置
npm run benchmark:chat     # 400 条内存合成消息的渲染与滚动对照
npm run stop               # 停止隔离实例，保留数据
```

没有 Docker 的机器（如 macOS 开发机）可用 `npm run local:start` 直接以 node 运行锁定的官方 release：基线、验证实例和确定性模型分别监听 `127.0.0.1:32011/32012/32013`，数据位于 `runtime/`，凭据写入本地 `.env`。`.env` 设 `WB_BIND_ADDRESS=0.0.0.0` 时验证实例 32012 与视觉实例 32014 监听全部网卡（tailnet / 局域网经 Basic Auth 访问），基线仍只监听本机。监听地址与 `WB_USERNAME` / `WB_PASSWORD` 每次启动从 `.env` 写回各实例配置，改后 `npm run local:stop` 再 `local:start` 生效。工作台以用户级扩展挂载本目录的 `extension/`；酒馆助手需设置 `WB_HELPER_SOURCE` 指向锁定版本的资产，否则相关检查跳过。`npm run local:stop` 停止。把数据库插件（龙血玄黄·数据库）装进 `runtime/validation` 的用户扩展后，可用 `npm run verify:database-real` 做真实插件联调；其余验证会话默认不加载该插件。

浏览器使用已有 Chromium，可用 `WB_CHROMIUM` 指定路径。上述集成验证只访问两个隔离实例及本地确定性测试模型，不读取生产聊天或调用真实模型。请串行运行集成测试和性能测试，以免同时修改同一个隔离账号。

## 源码与维护

- `src/host/`：状态、命令、版本相关接口、保存与冲突检查；所有宿主访问集中在这里。
- `src/ui/` 与 `src/App.tsx`：公共组件及桌面 / 手机布局；`src/modules/`：按需加载的世界书、角色、资源编辑和 Trace。
- `extension/addons/`：附加插件清单；`extension/dist/addons/`：独立入口与 Worker，由主插件按需加载。
- `extension/trace.js`：已验证的请求观察器；`extension/dist/`：可直接部署的构建产物。
- `extension/startup.js`：只读加载诊断；`src/addons/record-export/`：记录导出附加插件（UI、样式和分析 Worker）。
- `themes/`：原生主题产物；`docs/design/`：确认稿与资源编辑补充设计。
- `upstream/`、`runtime/`、`artifacts/`：官方 checkout、隔离运行数据、检查结果，均忽略入库。

[总体架构](docs/architecture/overall-architecture.md) · [第一阶段验证](docs/stage-1-report.md) · [横屏 Noval 实现报告](docs/stage-2-report.md)

新官方 release 先更新隔离基线并运行回归，再迁移生产；官方文件、工作台、助手版本分别维护。真实供应商差异、其他第三方插件、生产规模负载和安装后的真机键盘与系统手势仍需独立验证。独立生图编排、图片文件导出和目录同步属于后续模块。

## 横屏 Noval 主页重做

已按确认预览接入正式主页：居中配置、正文工具栏、专注、侧栏收纳、原生输入拖动、圆形发送与统一控件动效。访问验证实例后刷新即可加载。详细范围与验收结果见 [主页重做记录](docs/design/novel-desktop/rework/implementation.md)。

`npm run verify:home` 检查正式页面布局与交互。Trace 和资源右栏已进一步接入，使用 `npm run verify:resources` 检查。九类独立设置、纸张弹出菜单、聊天管理与小说阅读区已按确认稿接入，使用 `npm run verify:interactions` 验证。见 [本轮接入记录](docs/design/novel-desktop/rework/interactions-implementation.md)。

连接、预设、用户设定的新右栏已按确认稿接入；模型／连接／测试前置，滚动条统一为暖灰细条，资源行只绘制一层悬浮和选中反馈。见 [资源右栏修订与验证](docs/design/novel-desktop/rework/resources-redesign.md)。中间阅读区的增量需求保存在 [阅读区队列](docs/design/novel-desktop/rework/reading-queue.md)。

2026-10-08 的尺寸校准与组件迁移已接入：一级资源列外展 180px，角色／身份管理紧凑化，低频页面保留完整原组件和局部操作。实际尺寸、功能验证与检查图见 [此次修复记录](docs/design/novel-desktop/rework/migration-implementation-2026-10-08.md)。

## 横屏 RP 主页

右上角切换器两侧箭头切换上／下一个工作台，中间模式图标展开 Noval／RP／原生菜单。RP 对白工具栏的书本图标也可返回阅读布局；Noval 正文工具栏不再重复显示模式入口。模式与外观按酒馆用户保存；每次进入 RP 时两个边栏默认收起。RP 与 Noval 通过两侧无背景贴边箭头展开／收纳边栏，箭头跟随实际侧栏边界移动。资源选择、180px 一级列表、深度编辑、设置页、快捷键和原生输入控件复用现有工作台。

RP 中央舞台使用酒馆当前背景和表情扩展的立绘；没有立绘时使用原角色画像，可在「T · RP 外观」关闭。支持原生 Markdown 分段显示、左右翻段、消息编辑、记录查看、原生输入展开、发送与停止生成。右上眼睛按钮在同一位置隐藏／恢复界面，图钉可启用顶部悬浮显示。

设计中的示例背景、人物、天气和建议回复不写入聊天。场景信息没有专门元数据时显示当前角色和消息时间；建议回应仅来自已启用快速回复，点击填入原输入框。长段落、图片和酒馆助手 iframe 保留原节点并允许滚动。

范围、真实网页验证与设计对照见 [RP 主页接入记录](docs/design/rp-desktop/implementation.md)。
