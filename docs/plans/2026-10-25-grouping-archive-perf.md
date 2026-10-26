# 2026-10-25 整体方案：世界书分组/归档、性能、条目详情与吸收项

集成分支 `claude/worldbook-grouping-archive-8725c6`（基于 workbench b13cb93）。合并了两份输入：本轮需求（分组归档、性能、条目详情、路线图）与 [性能插件吸收规格](2026-10-25-perf-absorb-spec.md)。复杂工作包在独立 worktree 分支并行开发，简单项在集成分支直接改，最后统一合并验证、部署。

## 工作包总表

| # | 工作包 | 复杂度 | 执行 | 主要改动面 |
| --- | --- | --- | --- | --- |
| W0 | 部署脚本、路线图、性能规格入库 | 低 | 集成分支（已完成 d16858477） | scripts/deploy.mjs、docs |
| D1 | settings.json 遗留键清理 | 低 | 集成分支，生产数据操作 | 生产 settings.json |
| P-A | 前端 perf 扩展（规格工作包 A，6 模块） | 中-高 | fork F1 | 新目录 `perf-extension/`、deploy.mjs |
| P-B | workbench-sync 服务端缓存（规格工作包 B） | 中-高 | fork F2 | `server/workbench-sync/` |
| W1+W2 | 工作台内部性能 + 世界书条目详情布局 | 中 | fork F4 | `World.tsx`、虚拟化组件、`host/core`、`adapter` |
| W3 | **世界书分组 + 归档；连接归档**（本次主体） | 中-高 | fork F3 | `host/core` 偏好、`ResourcePicker`、`Resources`、`ResourceManager`、`World` 书列、`Header`、`MobileShell` |
| W5 | 占位符变量 | 中 | fork F5 | 新 host 模块、输入框、斜杠命令包装、变量管理面板 |
| W4 | 上下文裁剪 | 低-中 | 集成分支 | manifest `generate_interceptor`、楼层列表裁剪线 |
| W6 | 说话人着色 | 低 | 集成分支 | 新样式表模块、角色/persona 颜色设置 |

路线图 P1 两项（前置 AI 世界书路由、回复格式实时修复）另行立项；骰子控件取消；「世界书快捷切换」并入 W3 组级启停；备选池「渲染性能手法」由 P-A / P-B / W1 承接。

## 关键决定（已确认）

1. 归档只隐藏：工作台设置里的元数据标记，文件不动；归档项不出现在边栏、顶栏下拉、「下一个」与快捷键中，独立编辑页可恢复。
2. 在用的不能归档：世界书全局启用或绑定在角色卡 / 当前聊天 / 人设上时，归档按钮禁用并说明原因；当前连接不能归档。归档不改任何启用或绑定状态。
3. 世界书分组单层、一本书只属一个组，与现有连接分组（`prefs.groups`）同一形态；组头提供整组启停。
4. settings.json 遗留键：备份 → 清理 → 重启，不做前后计时。
5. 占位符保持原语法与指示数语义完全兼容（「👑超级菜单」22 条快速回复依赖它），变量按角色卡分组，改存工作台设置。
6. P-A 遵守规格硬性要求：独立扩展目录、`extension_settings.wbPerf` 单命名空间、版本与符号守卫、不改写用户持久化设置、不碰 BaiBai 的补丁领地与 `#show_more_messages`。

## 现状证据

- 生产 settings.json 已由你清理过 vectors_enhanced 并归一化（8.35 → 5.13 MB）。仍有已卸载/停用扩展的遗留键（LittleWhiteBox、st_bme、story_workspace、ai_worldbook_router、Amily2 等），D1 处理。
- 生产世界书 64 本 / 6028 条 / 34 MB，最大一本 3189 条 9.2 MB；角色 10、聊天 1。工作台全项目无列表虚拟化，条目表全量渲染并对整本书计 token；条目详情以内联行展开，把下方条目推出屏幕（截图问题）。
- `SETTINGS_UPDATED` 让 session / characters / resources / prefs 全部失效，所有 `withoutChat` 面板随每次设置保存重渲染。
- 连接已有单层分组（`prefs.groups[profileId]`，`ResourcePicker` 的 `grouped` 模式）；世界书无分组，两者都无归档。

## 对性能规格的修正与补充

核对 1.19.0 源码（`upstream/SillyTavern`）后：

- **P-B 的 `/api/settings/get` 失效条件不够。** 该端点（`src/endpoints/settings.js` 约 220–280 行）除 settings.json 外，还返回 NovelAI / OpenAI / TextGen / KoboldAI 四个预设目录、世界书名单、themes、movingUI、quickreplies、instruct、context、sysprompt、reasoning 的内容，而且按 `request.user` 区分（生产有 `default-user`、`yuwk-1` 两个用户）。缓存键必须含用户；有效性按 settings.json 与上述目录（含其中文件）的 mtime/size 指纹判断，并在这些资源的写端点（预设、世界书、主题、快速回复等保存/删除）以及 workbench-sync 自身写文件时立即失效。
- **P-B 的 `/api/characters/all`** 返回中含聊天统计（聊天大小、最后聊天时间），聊天保存同样要让它失效，或把聊天目录纳入指纹。
- **P-A 模块 6（gzip）** 可行：`src/server-main.js:110` 使用 `bodyParser.json({ limit: '500mb' })`，默认 `inflate: true`。保留失败回退未压缩重试。
- **P-A 模块 5（提前解遮罩）** 需验证不与工作台挂载时序冲突：遮罩提前解除后到 `APP_READY` 之间工作台尚未挂载，必须确认不会露出原生界面闪烁或可点击的半初始化状态；冲突则该模块默认关闭。
- `deploy.mjs` 增加 `perf-extension/` 的 rsync 目标（生产目录 `extensions/wb-perf/`），由 F1 完成。上线后按规格卸载 cocktail。

## 工作包要点

### W1 + W2（F4）

先在本地验证实例导入生产世界书副本测基线，再改：

- 一个共用的定高窗口化组件，用于条目表、边栏条目、角色列表、楼层列表；不引第三方库。
- token 计数只算可见与已编辑条目，整本合计按需或后台分批。
- `SETTINGS_UPDATED` 失效收窄到确有变化的分片（比较连接、预设、世界书选择等指纹）；工作台偏好写入合并防抖。
- W2：深度编辑改主从布局。条目表常驻，选中条目在右侧固定详情栏编辑（独立滚动），详情打开时收起次要列；窄窗口/手机用覆盖层；上下键切换条目。
- 验收：3189 条世界书打开、滚动、按键前后计时写入本文；选中任一条目时其余条目可见可点。

### W3 分组与归档（F3）

- 数据：`extensionSettings.workbench` 新增世界书分组映射与两类资源的归档集合，世界书以名称为键，加载时清理不存在的键，工作台内删除/改名同步更新。
- 边栏：世界书按组折叠，未分组置底，组头整组启停；归档项隐藏，底部「已归档 N」可展开。
- 顶栏下拉：同样分组、排除归档，搜索跨组；「下一个」与快捷键跳过归档。连接沿用现有分组，只加归档。
- 独立编辑页：分组新建 / 改名 / 删除 / 批量移入，批量归档 / 恢复（复用现有多选与批量栏），「全部 / 已归档」切换；在用项归档按钮禁用并写明原因。
- 手机 `MobileShell` 同步。
- 验收：归档项不出现在边栏、下拉和「下一个」，可在独立编辑页恢复；在用项无法归档；刷新与重启后保持。

### W5 占位符变量（F5）

- 兼容原脚本全部语法：`{@变量}`、`{@变量:默认}`、`{@变量:默认:提示}`、`{@变量:默认:提示:指示数}`、`{@变量=值}`、`{@变量!}` 及 `{@list}` / `{@clear}` / `{@reset}` / `{@input:toggle}`。展开写成纯函数并单测覆盖；原脚本源码在生产 settings.json `extension_settings.tavern_helper.script.scripts[3]`（只读参考）。
- 展开入口：原生 `#send_textarea` 防抖就地展开 + Tab 立即展开；包装 `/inject`。处理输入法组合输入、生成中、快速回复自动发送的时序。
- 变量按角色卡分组存工作台设置（跨设备同步），旧 localStorage 不迁移；变量管理面板（查看 / 编辑 / 删除当前角色变量）。
- 快速回复「`--------` 分隔前按钮变吸顶工具栏」样式：先核对工作台底栏是否需要，需要再做。
- 验收：「👑超级菜单」原样可用，控制菜单设定的名字在其他条目和 `/inject` 中正确展开，换浏览器后变量仍在。

### W4 上下文裁剪 / W6 说话人着色（集成分支）

- W4：manifest 注册 `generate_interceptor`，按设置截断发送的消息条数（不含示例与注入）；楼层列表标出裁剪线；不改写 ST 持久化设置。上线后停用 Extension-MessageLimit。
- W6：按消息作者给 `<q>` 对白上色，颜色来源为角色 / persona 手动颜色或头像主色（canvas 自取），按主题做对比度修正；只生成样式表，不改消息 DOM；覆盖 Noval 阅读区与 RP 舞台；迁移生产两个 persona 的颜色。上线后停用 Dialogue-Colorizer。

## 并行开发约定

- 每个 fork 在独立 git worktree 与分支上工作，只改本工作包范围内的文件；完成后提交在自己的分支，不合并、不推送、不部署。
- 运行环境（每个 worktree 各自准备）：
  - 从主检出 `/Users/yuwk/WorkSpace/Code/Github/SillyTavern` 复制 `.env`，追加各自的 `WB_PORT_OFFSET`：F1=100、F2=200、F3=300、F4=400、F5=500，集成分支=600。
  - `cp -cR <主检出>/node_modules .`；`mkdir -p upstream && cp -cR <主检出>/upstream/SillyTavern upstream/`（APFS 克隆，各自独立，因为 `npm run build` 会把服务端插件链接建在 `upstream/SillyTavern/plugins/` 下）。
  - `npm run local:prepare && npm run build && npm run local:start`；用完 `npm run local:stop`。
- 生产只读：可 `ssh nas` 读取数据做参考，不写生产、不重启容器。
- 每个 fork 完成时：`npm run check && npm test && npm run build` 通过，跑受影响的 verify，并在本文对应小节下追加实测结果与未验证项（只改自己那一节，减少合并冲突）。

## 合并与上线

1. 集成分支先完成 W4、W6、D1。
2. fork 完成后逐个合并进集成分支：P-B、P-A 与其他包无文件交集，先合；F4 与 F3 都动 `World.tsx` 和 `host/core`，先合 F4 再合 F3；F5 最后。
3. 全部合并后跑 `npm run check`、`npm test`、`npm run build` 与 `verify:workbench`、`verify:interactions`、`verify:resources`、`verify:pwa`、`verify:rp`。
4. `npm run deploy` 上生产并探活；随后在生产卸载 cocktail，停用 Extension-MessageLimit 与 Dialogue-Colorizer。
5. 集成分支合入 `workbench` 前确认主检出的改动归属：主检出当前有未提交的 README / package.json / roadmap / deploy.mjs，与本分支 W0 内容相同或更旧，合并前需要你处理它们。

## 进度

- [x] 总体计划、关键决定确认
- [x] W0 入库（d16858477）
- [x] D1 settings.json 清理（2026-10-26 生产执行，备份 `backups/settings-cleanup-20261026-002618/`）
- [x] W4 上下文裁剪（05e4dd712）
- [x] W6 说话人着色（e196e14e1）
- [x] F1 P-A 前端 perf 扩展（合并 1fb4b0624；renderDebounced 绕过补丁的问题已修，集成实例 `verify:perf` 13/13）
- [x] F2 P-B 服务端缓存（合并 a55cebc43）
- [x] F3 W3 分组与归档（合并 1a1991adf；集成实例 `verify:grouping` 10/10，`verify:workbench` 10/10，W4/W5/W6 复验通过）
- [x] F4 W1 + W2 工作台性能与条目详情（合并 a60c6ab40，无代码冲突；集成复验见下）
- [x] F5 W5 占位符变量（合并 a00f83fe3）
- [x] 合并、全量验证（2026-10-26，见「全量集成复验」）
- [x] 部署生产（2026-10-26，见「生产部署」）
- [x] 生产清理：卸载 cocktail，停用 Extension-MessageLimit、Dialogue-Colorizer（2026-10-26）
- [ ] 停用世界书切换器脚本（用户试完分组后再定）

## 实测记录

### 集成分支：D1 / W4 / W6

- D1：删除 11 个已卸载扩展的遗留键（st_bme、LittleWhiteBox、Amily2、World-Book-Assistant、story_workspace、customModels 等，约 120 KB）与 4 个已停用且路线图标为「已处置」的酒馆助手脚本（角色卡管理、自动标签检查、聊天记录导出、SoliUmbra，约 980 KB）。停容器 → 原子写回（4 空格缩进，与 ST 一致）→ 启动；settings.json 8.34 MB → 7.16 MB；重启后 32001 返回 401（Basic Auth）、workbench-sync 已加载。保留在用脚本与占位符系统源码（W5 参考）。「世界书切换器」脚本仍启用，W3 上线后可停用。
- W4（实测，本地 32612）：`verify:context-limit` 3 项通过——设置页开关与条数写入偏好；楼层列表淡化不发送的楼层，起点在倒数第 3 条未隐藏楼层；接 mock 模型生成时请求只含最近 3 条，隐藏楼层不计，聊天文件保留全部楼层。首次启动迁移 Extension-MessageLimit 设置（生产为开启、5 条、后台也限制）。
- W6（实测）：`verify:speaker-colors` 4 项通过——角色颜色只作用于该角色对白；persona 按头像匹配（名字不可靠：fixture 的 `name1` 与 persona 名不同）；`#fff700` 在纸色主题被压暗、深色主题保持明亮；清除恢复主题色；RP 布局同样生效。只用手动颜色，没有做头像取色（生产配置只用手动色，原取色已失效）。
- 合并后：`npm run check`、`npm test`（148 项）、`npm run build` 通过；`verify:speaker-colors` / `verify:context-limit` / `verify:placeholders` 全部通过。
- 本地 `.env` 注意：从主检出复制的 `WB_MOCK_API` 指向 32013，换端口偏移后要改成 32013+偏移，否则生成返回 502。
- 已知旧问题：`verify:workbench` 第 3 项「角色描述」定位到两个元素（F2、F5 在 cad6ec8c0 上复现），与本轮改动无关，待修脚本。

### F2 P-B 服务端缓存

**实现**（`server/workbench-sync/src/cache.ts`，入口 `index.ts`、`st.ts`）：

- 拦截方式：插件按同一文件 URL 导入 `src/endpoints/settings.js` 与 `characters.js`（Node 按真实路径解析，得到 server-startup 已挂载的同一模块实例），在它们导出的 Express router 栈头插入路由层。不改 ST 源文件；这两个 router 挂在 Basic Auth、登录、CSRF 中间件之后，中间件链不受影响。router 不像 1.19.0 的（找不到 `/get` / `/all` 路由）就不安装，并打日志说明。
- 缓存键为「用户 handle + 端点」。有效性用指纹判断，指纹由每个文件的名称、inode、大小和 mtime 组成：settings 取 settings.json 加上 settings/get 读取的 12 个目录；characters 取 characters 目录加上 chats 下一层。write-file-atomic 每次写入都换新 inode，同一毫秒内同样大小的重写也能识别。
- 立即失效：
  - settings router 上除 `/get`、`/get-snapshots` 外的请求，characters router 上除 `/all`、`/get`、`/chats`、`/export` 外的请求，都在请求开始和结束时各失效一次该用户的缓存。
  - 插件自身的 PUT `/file`、`/delete`、`/rename` 同样在写入前后失效。
  - 回源过程中如果发生了失效，这次回源结果不入缓存（用代际计数判断）。
  - 只缓存 200 的字符串响应。
- 命中时直接返回预压缩字节（br 质量 4 / gzip，与 compression 1.8.1 的协商偏好一致），并带 `Vary: Accept-Encoding`。已带 Content-Encoding 的响应，ST 的 compression 中间件会原样放行，所以每次刷新不再重复压缩约 5 MB。每种编码每个条目只压缩一次。
- 日志：`workbench-sync: cache hit|miss <端点> [用户] <原始大小> → <编码> <压缩后大小> in N ms · hits / misses`。`/api/plugins/workbench-sync/info` 新增 `cache: {on, hits, misses, bytes}`。
- 冷启动时缓存为空，直接回源；插件 `exit` 时移除插入的路由层。

**实测**（本地 validation 32212 带插件，baseline 32211 为官方无插件；用 probe 键把 settings.json 撑到 5.96 MB，测完已恢复）：

| 项目 | 结果 |
| --- | --- |
| settings/get 客户端总耗时（7 次中位数） | baseline 106.0 ms；validation 首次回源 116.2 ms，命中 36.0 ms |
| settings/get 服务端处理耗时（插件日志） | 回源 42–51 ms（不含压缩）；命中 2–3 ms，首次命中含一次压缩约 17 ms |
| characters/all（31 KB） | 回源 35.6 ms，命中 8.0 ms |
| 保存设置后立即 get | 拿到新值 |
| 新建 / 删除世界书后 get | `world_names` 立即反映 |
| 保存 / 删除 OpenAI 预设后 get | `openai_setting_names` 立即反映 |
| 两个会话交替保存与刷新（4 轮） | 每轮读到对方刚写的值，无脏读 |
| 新建 / 删除角色后 characters/all | 立即反映 |
| br 编码走真实 compression 中间件 | 回源与命中解码结果一致，没有二次压缩 |
| 重启实例后 | 首次回源、第二次命中，响应一致 |
| 单元测试 `tests/cache.test.mjs` | 8 项通过：指纹覆盖与排除、编码协商、命中与失效、写路由失效、回源竞态丢弃、500 不缓存、多用户隔离、安装拒绝与撤销 |
| `npm run check` / `npm test` / `npm run build` | 通过（125 项） |
| `verify:sync` | 10 PASS（插件写入路径加失效包装后 IDE 同步正常） |

**推断**：

- probe 填充内容重复度高，gzip 后只有 34 KB。真实 settings.json 的压缩率低得多，所以命中时省下的压缩开销应该比上面的测量更大；客户端总耗时的改善幅度要以真实数据为准。
- V1 格式角色卡缺少 `chat` 字段时，ST 每次 `/all` 都会用当前时间生成默认聊天名；缓存后这个值在缓存有效期内保持不变。这不影响已有聊天。
- 只要聊天文件有变化（每条消息），characters/all 的缓存就会失效，所以它主要在空闲后刷新时起作用；settings/get 是刷新的主要开销，不受聊天写入影响。

**未验证**：

- 生产 Docker 环境中按真实路径导入是否得到同一模块实例：本地已验证（命中计数增长、日志确认已安装），生产部署后请查看容器日志里的 `response cache on`，并在刷新后检查 `/info` 的 `hits` 是否增长。
- BaiBai 的 baibaoku 404 回退：本地没有安装 BaiBai。本插件不注册也不拦截该路径，按推断互不影响。
- 浏览器真实页面多标签：只用两个 HTTP 会话模拟。`verify:workbench` 在第 3 项（「角色描述」定位器同时匹配复选框和 Markdown 编辑器）失败，去掉插件后同样复现，是 Markdown 编辑器上线后验证脚本未更新的旧问题，与本工作包无关，需要另行修复脚本。
### F1 P-A 前端 perf 扩展（2026-10-26，分支 worktree-agent-a266e078f2139266b）

产出：`perf-extension/`（6 个模块，设置在 `extension_settings.wbPerf`，扩展面板「Workbench 性能优化」一个总开关 + 每模块开关），`scripts/deploy.mjs` 同步到生产 `extensions/wb-perf/` 并探活，`scripts/local-runtime.mjs` 给验证/视觉实例链接 `wb-perf`，`npm run verify:perf`。

实测（本机 1.19.0 验证实例，offset 100；`npm run check && npm test && npm run build` 通过，`verify:perf` 13 项全部通过、无页面错误）：
- 6 个模块在 1.19.0 全部安装成功（版本门禁 + 符号探测），面板列出 6 项。
- 启动预取：avatars/characters/backgrounds 三个列表加载时并行发出、各只请求一次，原生调用拿到的角色数与服务端一致。
- 提前解遮罩：工作台会挂载时不提前（APP_INITIALIZED 时遮罩仍在）；禁用工作台后在 SETTINGS_LOADED 即解除。注意 1.19.0 的启动遮罩是 `loader.show({slug:'app-init'})`，cocktail 用的 `ctx.hideLoader()` 对它无效，这里直接 hide 该句柄；工作台加载判断用 `window.workbench || window.workbenchStartup`（SETTINGS_LOADED 时工作台 bundle 可能仍在 import）。
- gzip：经局域网地址访问时 >64 KB 的 settings 保存以 `Content-Encoding: gzip` 发出、服务端完整写入并可读回，小请求不压缩；压缩请求失败时自动以未压缩重发并成功（worldinfo/edit 实测）。回环地址不压缩。
- 预设：`render(true)` 立即重绘列表，连续 3 次切换只做 1 次后台 dry-run，完成后再刷新计数；关闭后恢复原生（先 dry-run 再画）。
- 预设（修正，集成实例 offset 600 上发现）：`promptManager` 在 getSettings → changeMainAPI 里构造、早于扩展加载，实例的 `renderDebounced`（CHAT_LOADED / MESSAGE_RECEIVED / 模型切换走它）绑定的是原生 render，绕过补丁、仍先 dry-run 再画。现把它换成同样 1 s 防抖、动态派发到 `render` 的版本（卸载时还原）。`verify:perf` 增加该路径：开启时防抖结束即重绘、只 1 次 dry-run；关闭后恢复原生。offset 600（已连 mock、开着角色聊天）13 项全部通过。
- 抽屉：inline-drawer 开合用一个 WAAPI 动画、无 jQuery 高度逐帧；关闭后恢复 jQuery slideToggle。
- 正则：面板打开时单个与批量开关都不重载聊天，收起面板后重载一次；关闭模块后切换立即重载（原生）。
- 世界书拖拽：拖动中条目不动，只有影子与指示线、无 jQuery UI 占位；松手一次重排并经原生 stop 回调保存 displayIndex（服务端读回顺序一致）；关闭后 jQuery UI sortable 接管。
- 总开关关闭：document/window 上来自 wb-perf 脚本的监听器 5 → 0（CDP 检查），`PromptManager.prototype.render`、`$.fn.slideToggle`、`fetch` 均恢复原生，面板外无 `wb-perf` 元素/类。

推断（读代码得出，未在真实环境复现）：
- 生产（192.168.31.201）上 BaiBai 的 gzip 因私网地址跳过，本扩展会压缩 LAN 请求；两者同时生效时 BaiBai 先压缩的请求带 `Content-Encoding`，本扩展跳过，不会二次压缩。
- 与 BaiBai 共存：本扩展只补 `PromptManager.prototype.render`，不碰实例级 `makeDraggable` / `renderPromptManagerListItems` / `getPromptCollection`，不拦截 `#show_more_messages`。

未验证：
- 与 ST-BaiBai-Tools 实际共存（本机未安装 BaiBai）。
- 生产部署与探活（按要求未部署）；部署后需在生产卸载 cocktail，避免同类补丁叠加。
- 版本门禁上限 1.20.0（不含）以外的酒馆版本。
### F5 W5 占位符变量（分支 `worktree-agent-abccf3bbb3b7e5fe5`）

实现：`src/host/placeholders.ts`（纯函数展开）、`src/host/placeholder-runtime.ts`（输入框 / `/inject` / `/buttons` 接入与存储）、`src/ui/PlaceholderPrompt.tsx`（输入弹窗）、`src/modules/PlaceholderSettings.tsx`（用户设置 → 占位符变量）。变量存 `extensionSettings.workbench.placeholders[作用域]`，作用域为角色头像文件名 / `group:<id>` / `default`。

与原脚本（生产 settings 中 tavern_helper 脚本 #3）对照后的行为说明：

- 超级菜单不走 `/inject` 为主，而是 `/setinput {{input}}<…{@变量…}>` 写进输入框再 `/run` 菜单，展开发生在原生 `/buttons` 弹窗仍打开时。工作台弹窗用 `showModal`，叠在原生弹窗之上可正常操作，关闭后原生弹窗继续可用。
- 原脚本的 Tab 是打开变量管理器；这里 Tab 改为立即展开（管理器在用户设置里）。Enter / 发送按钮遇到未展开的完整占位符时先展开、不发送，避免把原始 `{@…}` 发出去。
- `{@toast:…}` / `{@confirm:…}` 在原脚本里被 `{@名:默认}` 先吞掉、只输出文字；这里按保留名的本意弹提示。超级菜单未使用这两个命令。
- 原脚本按 `characterId`（数组下标，下标 0 会落到 default）分组，这里改按角色头像文件名，不受角色列表顺序影响；旧 localStorage 数据不迁移。
- 快速回复工具栏样式需要：它作用于 `/buttons` 弹窗（不是输入框底栏），超级菜单 35 条里每个菜单都用 `--------` 分隔导航按钮。实现为包装 `/buttons` 命令、处理刚打开的弹窗，不用全局 MutationObserver；样式在 `native-bridge.css`。

实测：

- `npm run check`、`npm test`（130 项，新增 13 项占位符单测）、`npm run build` 通过。
- 差分对照（只在本地 artifacts 运行，不入库）：抽出原脚本 `replaceTextAsync` 加桩，与新实现在超级菜单全部 189 段含占位符文本 × 2 种变量状态 × 弹窗开 / 关 × 3 种回答（空 / 填写 / 取消）共 2268 例比较文本、变量与弹窗开关，0 差异。
- `npm run verify:placeholders`（新增，端口偏移 500 本地实例）7 项通过，合成菜单与真实「👑超级菜单」导出（`WB_QR_SET=…`）各跑一遍：`/buttons` 工具栏；控制菜单 `⚙️@角色指定` 在原生弹窗上方弹出 7 个输入、设定名字后输入框为 `<>`；`🤝男女主汇合` 展开为已存名字；`👨切换主角-男主` 的 `/inject` 注入内容已展开；Enter / Tab 立即展开且不发送；重载后变量仍在并可展开；设置面板查看 / 编辑 / 删除。
- `verify:compat` 10 项通过（本地实例补装酒馆助手、`.env` 的模拟模型端口改为偏移后端口后）。
- `verify:workbench`：在「角色描述」处因 `getByLabel('角色描述')` 同时匹配世界书条目模板的隐藏复选框与角色编辑器 Markdown 字段而失败；用改动前基线 cad6ec8c0 单独构建复跑，同一位置同样失败，属既有问题，与本工作包无关，未修。

推断 / 未验证：

- 「换浏览器后变量仍在」以「重载后从酒馆设置读回」验证，未用第二个浏览器实测；存储位置是随设置同步的 `extension_settings`，推断成立。
- 手机布局、中文输入法组合输入（compositionstart/end 期间不展开）未做自动化验证，只有代码路径。
- 切到「原生」布局时工作台卸载，占位符随之停用（原脚本不依赖布局）；未处理。
- `/buttons` 的说明文字中的 `{@男主:男主}` 与原脚本一样原样显示，未展开。
（各工作包完成后在此追加。）

### F3 W3 分组与归档

实现要点：
- 数据：`prefs.worldGroups`（书名 → 组名）、`prefs.archived.{world,connection}`；连接沿用 `prefs.groups`。`Item` 增加 `group` / `archived`，由 `buildResources` 写入。纯函数在 `src/host/organize.ts`（分组排序、列表顺序、补丁、清理），宿主方法在 `src/host/domains/organize.ts`（`resourceUsage`、`archiveResources`、`setResourceGroup`、`renameResourceGroup`、`savePreference`、`pruneOrganization`）。
- 归档与分组是显式操作，立即 `persistSettings` 并等待确认（失败回滚），不走防抖保存：运行时验证发现防抖保存在归档后立刻刷新会丢失。
- 在用判定：全局启用、任一角色卡主世界书或附加世界书、当前聊天绑定、任一人设绑定；当前连接。宿主层同样拒绝，不只是按钮禁用。
- 启动时与工作台内批量删除后清理不存在的键；启动时世界书列表为空则不清理世界书键（防止未加载时误删）。酒馆原生改名世界书后分组随旧名被清理（工作台无改名入口）。
- 界面：资源栏分组可折叠 + 组头整组启停 + 底部「已归档 N」折叠可恢复；顶栏下拉与手机 RP 选择框分组、排除归档、世界书组头整组启停，≥9 项时出现搜索；手机面板标题选择器（无资源栏）分组 + 组头启停；独立编辑页「未归档 / 已归档」切换、分组标题（选整组 / 重命名 / 解散）、批量「分组」「归档 / 恢复」，在用项禁用归档并列出原因；「下一个」与快捷键按分组顺序跳过归档项。

实测（本地 offset 300 实例，Chrome headless）：
- `npm run check`、`npm test`（124 项，含新增 `tests/organize.test.mjs` 7 项）、`npm run build`、`format:check` 通过。
- 新增 `npm run verify:grouping`（`scripts/verify-grouping.mjs`）10/10 PASS：编辑页分组移入 / 重命名 / 解散；在用（全局、角色卡）不能归档并说明原因、宿主同样拒绝；归档进入已归档；资源栏分组、隐藏归档、整组启停不波及归档书；资源栏恢复；顶栏下拉分组与整组启停；当前连接不能归档、归档连接离开下拉、Alt+Shift+N 跳过归档连接；刷新后分组与归档保持；手机面板选择器与 RP 选择框；删除世界书后键被清理。截图：`artifacts/grouping-{rail,chooser,manager,manager-archived,phone-picker,phone-chooser}.png`。
- `verify:pwa` 18/18 PASS。
- `verify:workbench`、`verify:resources`、`verify:interactions` 在本环境中途失败，失败点与本改动无关，且在基线提交 cad6ec8c0 的构建上以相同位置失败（已实测对照）：`getByLabel('角色描述')` 命中隐藏的原生 checkbox、`getByLabel('流式传输')` 命中 5 个元素、作者注释角色选项 `User` 不存在。三者在失败点之后的步骤未执行。

推断 / 未验证：
- 上述三个 verify 失败点之后的步骤（含它们对资源列表的其他覆盖）未执行；需在修好这些脚本或在主检出环境中复跑。
- 连接的分组标题操作（重命名自动按模型分组、解散恢复按模型分组）只有代码路径与单测，运行时验证只覆盖了世界书。
- 未在生产数据（64 本）上看过分组后的列表观感。

### F4 W1+W2

环境：本机 M1 Pro，本地验证实例（`WB_PORT_OFFSET=400`），无头 Chrome。数据是生产世界书只读副本（主测 `X-性癖大世界2.1`，3189 条 / 5.1 MB；另装 295 条、178 条两本），没有提交进仓库。脚本：`npm run benchmark:world`（`WB_BENCH_BOOKS=<目录>`），报告写到 `artifacts/benchmark-world-scale.json`。改动前后在同一实例、同一份数据上各跑一遍；改动前用 `cad6ec8c0` 的 src 构建。

**实测**

| 场景（3189 条） | 改动前 | 改动后 |
| --- | --- | --- |
| 深度编辑打开 | 3075 ms；渲染 3189 行 / 35252 节点；3 s 内 648 次 tokenizer 请求；长任务 2198 ms（最长 1720） | 782 ms；22 行 / 425 节点；38 次请求；无长任务 |
| 条目表滚动 240 帧 | 无法滚动（表格没有滚动容器，被 `overflow:hidden` 截住） | 帧间隔中位 16.6 / p95 17.6 / 最长 24 ms；无长任务 |
| 选中第 3 条 | 3301 ms；单次事件 904 ms | 126 ms；事件 40 ms |
| 正文输入 30 字 | 总耗时 2728 ms；事件中位 96 / p95 208 / 最长 224 ms；31 个长任务共 2348 ms | 346 ms；中位 24 / p95 32 ms；无长任务 |
| 侧栏世界书打开 | 9102 ms；3189 行 / 47929 节点；长任务 8817 ms（最长 7893） | 439 ms；16 行 / 335 节点；无长任务 |
| 设置保存 ×5（深度编辑中） | 同步 0.6 ms；分片通知 20 次 | 同步 0.2 ms；分片通知 0 次 |
| 设置保存 ×5（侧栏） | 同步 0.6 ms；分片通知 20 次 | 同步 0.4 ms；分片通知 0 次 |

设置保存的“emit→下一帧”两边都约等于一帧间隔，说明不了差别，所以不列。

验证（前后结果一致）：`npm run check`、`npm test`（118/118）、`npm run build` 通过。`verify:compat` 10、`verify:rp` 36、`verify:pwa` 18 全过。`verify:workbench`（第 120 行「角色描述」strict mode）、`verify:interactions`（第 39 行超时）、`verify:resources`（第 21 行「流式传输」strict mode）改动前后在同一处失败，属于既有问题，与本包无关。

截图：改动前桌面端的行内编辑器挡住下方条目，手机端挤压截断。改动后桌面端是条目表加右侧详情栏，次要列收起；手机端详情全屏、带返回，列表为紧凑列。截图在本地 `artifacts/f4/shots/`，未入库。

**做了什么**

- `src/ui/useWindow.ts`：定高窗口化 hook。可见区取列表与所有滚动或裁剪祖先的交集，前后用占位元素撑高度，`reveal()` 会考虑 sticky 表头。120 条以下不窗口化。用在深度编辑条目表和侧栏条目列表上。
- token：`useTokenTally` 支持只统计指定 id（可见行加打开的条目），按文本缓存。超过 120 条时整本合计按需计算，点「统计 tokens」后后台逐条补齐，期间显示进度。
- `SETTINGS_UPDATED` 改走 `revalidate`：重建已缓存的分片，与构建时的签名比较（值相同；宿主对象同一引用；角色的收藏与绑定世界书按值比较），只通知确有变化的分片。`invalidate` 的语义保持不变，`prefs → resources` 仍然无条件随之失效，F3 的归档和分组刷新依赖这条链。
- 偏好写入：`preference()` 本来就会跳过内容未变的补丁，落盘也已走酒馆的 `saveSettingsDebounced`，所以没有再加一层防抖。
- W2：深度编辑改成主从布局，条目表与右侧详情各自滚动。详情打开时收起「位置」、「深度」、「顺序」三列。容器宽度 ≤860px 时详情改为覆盖层（带返回），≤620px 时用紧凑列，手机端详情固定全屏。在表格内用 ↑/↓ 切换条目（输入框内不拦截），当前行移出渲染窗口后仍能继续切换。覆盖层模式下加载时不自动打开首条。

**推断（未实测）**

- 生产实例的 tokenizer 请求量会随之下降（本地从 648 降到 38），但生产的分词端点延迟不同，实际节省量没有测。
- 角色列表没有做窗口化：生产只有约 10 张卡，设置保存引起的重渲染已由 `revalidate` 消除，需要时可直接套用 `useWindow`。楼层列表（`Navigation` FloorList）原本已窗口化，未改。

**未验证**

- 没有在生产实例上测（按约定只读）。
- ↑/↓ 切换条目用临时脚本实测过：300 条的书，从第 2 条开始连按 200 次 ↓ 到第 202 条，再按 150 次 ↑ 回到第 52 条，渲染行数一直在 20–30 行，表格跟随滚动。这个检查没有写进 verify 脚本。
- 手机端只在 Playwright 移动视口下看过截图，没有在真机上看。

### 全量集成复验（F1–F5 全部合并后，2026-10-26）

环境：本地 offset 600 实例，无头 Chrome，`WB_HELPER_SOURCE` 指向主检出的锁定 JS-Slash-Runner（未设置时 compat / rp 会因 `TavernHelper is not defined` 中断，属环境缺失）。

实测：
- `npm run check`、`npm test`（156/156）、`npm run build`、`format:check` 通过。
- verify：grouping 10、workbench 10、speaker-colors 4、context-limit 3、placeholders 7、perf 13、compat 10、rp 36、pwa 18，全部通过。pwa 首轮在「左半屏点击翻回」处失败一次，安装助手后重跑通过，未复现。
- `benchmark:world`（合成 3189 条）：深度编辑打开 697 ms / 22 行；滚动帧中位 16.6 ms；选中 126 ms；输入 p95 32 ms；侧栏打开 326 ms / 16 行；设置保存分片通知 0；全程无长任务、无页面错误。与 F4 分支数据一致。
- 截图（`artifacts/f4-merged/`，未入库）：桌面主从布局与 F3 的「未归档 / 已归档」切换并存；表格内 ↓ 40 次从条目 3 到条目 43，表格跟随；760px 宽时详情为全屏覆盖层带返回。

未验证：`verify:resources`、`verify:interactions` 的既有定位器失败未修，未复跑。

### 生产部署（2026-10-26）

- `npm run deploy`：build、check 通过；前端扩展同步到 `extensions/workbench/`，性能扩展同步到 `extensions/wb-perf/`；服务端插件 fa92a24a → 11611338，容器已重启。
- 容器日志：`workbench-sync: response cache on for /api/settings/get and /api/characters/all`，无错误。
- 带认证探测（凭据在 NAS 上读取，不出机）：两个扩展 manifest 返回新版本（workbench 0.4.0、wb-perf）；连续三次 `/api/settings/get` 分别为 1.10 s / 0.36 s / 0.017 s（3.48 MB）；`/info` 报告 `cache: {on: true, hits: 2, misses: 1}`。
- 部署脚本修正：重启后原来固定等 4 s 就探测，服务端仍在加载插件，探测报 ECONNREFUSED；改为轮询到能连接（最多 90 s）再探测。改后的重跑走的是「插件无变化」分支，重启分支的等待未实测。
- 首次部署被本机网络挡住：Claude Code 的进程只能访问路由器和本机，访问 NAS 报 No route to host；完全退出并重开 Claude 后恢复。

生产清理（用户确认后执行）：备份 `backups/extension-cleanup-20261026-125756/`（settings.json 与整个 cocktail 目录）；停容器 → `extensions/cocktail` 移入备份目录 → `disabledExtensions` 追加 `third-party/Extension-MessageLimit`、`third-party/SillyTavern-Dialogue-Colorizer`（原子写入）→ 启动容器。两者的设置键保留，供工作台首次加载时迁移（messageLimit：开、5 条、含后台；人设颜色 2 个）。清理时工作台尚未迁移（`workbench.contextLimit` / `speakerColors` 都不存在）。cocktail-plus 原本就是停用状态，未动。

未验证：生产页面上的工作台功能（分组归档、主从布局、对白着色、上下文裁剪、占位符）没有在生产页面里实际操作，需要刷新后人工确认。

### 上线后反馈修复（2026-10-26，5e4d13fcd）

用户反馈：① 连接只能手填模型，丢失选择能力；默认按模型分组不对（大量非标准模型名）。② 世界书独立编辑页编辑条目时仍遮挡条目列表。

原因：
- ① 自定义（兼容 OpenAI）与通用文本补全来源只镜像了酒馆的「模型 ID」输入框，没有镜像旁边的可用模型下拉（`model_custom_select` / `generic_model_select`），这是本轮之前就有的缺口；分组回退到 `p.model || p.api`。
- ② 条目工作区宽度 ≤860px 时详情绝对定位盖住表格。设置页里导航与世界书列表列共占约 520px，窗口 1440 时工作区约 920px 所以截图正常，窗口再小一点就进入覆盖模式。

修复：
- 模型行同时显示可用模型下拉与 ID 输入：选中即由酒馆原生处理写入 ID；手填的 ID 不在列表中时下拉回到提示项，避免选同一项不触发。
- 连接只按用户指定的分组，未指定即未分组；相关文案改为「移出分组」「变为未分组」，资料编辑里的字段改为「分组」。生产 38 个连接都没有显式分组，上线后为平铺列表。
- 桌面端详情始终与条目表并排；工作区 ≤860px 时列表只留条目名与 tokens；窗口 <1280px 且打开条目时收起设置页的世界书列表列（关闭详情即恢复）；仅工作区 ≤520px 时覆盖。<1024px 为手机布局，详情仍全屏，未改。

实测（本地 offset 600）：临时脚本——自定义来源手填 ID 后从下拉选模型，`custom_model_id` 与 `custom_model` 都更新；连接 `group` 均为空；1280 / 1100 / 1024 宽度下详情左缘在表格右缘之外，表格宽 264 / 299 / 270 px，详情打开时仍能点选其他条目，无页面错误。`npm test` 156、`format:check`、verify grouping 10 / workbench 10 / compat 10 / rp 36 / pwa 17（缺的一项「长按最新 RP 回复」由前置聊天状态决定是否执行，与本改动无关）。已部署，生产 dist 含新代码；生产迁移已完成（`workbench.contextLimit`、`speakerColors` 存在）。

未验证：生产页面上未实际操作；手机布局（<1024px）的详情仍为全屏覆盖。

