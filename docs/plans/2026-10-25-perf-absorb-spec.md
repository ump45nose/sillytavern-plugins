# 性能优化插件吸收 · 开发规格

承接 2026-10-25 扩展审计结论：生产保留 ST-BaiBai-Tools 运行；cocktail 待卸载（其独有模块由本规格吸收）；
cocktail-plus 服务端插件不安装（改写 ST 源文件，思路由本规格重新实现）。
settings.json 已清理 vectors_enhanced 死配置并归一化格式（8.35MB → 5.13MB，2026-10-25）。

## 环境

- 生产：fn NAS `192.168.31.201:32001`（ssh 别名 `nas`），SillyTavern **1.19.0**，数据卷
  `/vol2/1000/Docker/sillytavern/`。
- 本仓库 `upstream/SillyTavern/` 即 1.19.0 基线源码，所有钩子点已按它验证（下表 file:line 均出自它）。
- 版本锁定见 `baseline.lock.json`；不得改动 `upstream/` 与 `baseline.lock.json`。

## 来源仓库

| 仓库 | 链接 | 用途 |
| --- | --- | --- |
| cocktail（鸡尾酒） | https://github.com/Lianues/cocktail | 工作包 A 模块 1–5 |
| cocktail-plus（鸡尾酒+） | https://github.com/Lianues/cocktail-plus | 工作包 B 思路参考（**勿照搬** source-patches） |
| ST-BaiBai-Tools（柏宝箱） | https://github.com/baibai-git/ST-BaiBai-Tools | 工作包 A 模块 6 |
| SillyTavern | https://github.com/SillyTavern/SillyTavern （tag 1.19.0） | 钩子点对照基线 |

生产上的参考副本（只读，勿改勿删）：`nas:/vol2/1000/Docker/sillytavern/extensions/{cocktail,cocktail-plus,ST-BaiBai-Tools}`。
克隆源仓库看对应版本即可，不必依赖生产副本。

## 工作包 A · 前端 perf 扩展

在仓库新建扩展目录（建议 `perf-extension/`，与 `extension/` 平级；`deploy.mjs` 增加 rsync 目标或先手动部署）。

### 模块清单

| # | 模块 | 来源文件 | 目标行为 | ST 1.19.0 钩子点（已验证） |
| --- | --- | --- | --- | --- |
| 1 | 预设 dry-run 后台化 | cocktail `modules/preset-panel-optimizer.js` | `render(true)` 先渲染 UI，token 计数防抖后台跑 | `PromptManager.prototype.render`（`public/scripts/PromptManager.js:872` 先 tryGenerate 后渲染） |
| 2 | regex 面板免重刷 | cocktail `modules/regex-refresh-optimizer.js` | 面板展开期间拦截 toggle 不触发整聊重渲，收起时统一刷一次 | regex 扩展 toggle→`reloadCurrentChat()`（`public/scripts/extensions/regex/index.js` 1623/1646/1667/1822/1846/1897 六处） |
| 3 | UI 动画 transform 化 | cocktail `modules/ui-animation-optimizer.js` | 抽屉/inline-drawer 的 height 动画改 transform/opacity | `public/script.js:12203` `slideToggle` |
| 4 | 世界书指示线拖拽 | cocktail `modules/worldinfo-drag-optimizer.js` | 拖拽期间不重排条目，仅移动指示线，松手一次性落位 | `public/scripts/world-info.js:2656` `sortable` |
| 5 | 启动预取+提前解遮罩 | cocktail `modules/startup-optimizer.js` | 预取三端点复用响应；SETTINGS_LOADED 后提前 hideLoader | `POST /api/characters/all`（script.js:1295）、`/api/avatars/get`（personas.js:276）、`/api/backgrounds/all`（backgrounds.js:709）、`ctx.hideLoader`（loader.js，经 st-context 暴露） |
| 6 | gzip 保存请求 | BaiBai `index.js` `installSaveRequestGzipFetchHook`（约 15472–15740 行） | 大 POST 体 gzip 压缩上行 | 包装 `fetch` + `Content-Encoding: gzip`；ST 服务端 body-parser 默认 `inflate:true` 可解压。**必须保留其失败/非 200 自动回退未压缩重试** |

### 硬性要求

1. ES modules + `manifest.json`；每个模块独立 `enabled` 开关，统一存 `extension_settings.wbPerf` 单命名空间。
2. 版本守卫：加载前从 `/script.js` 取 `displayVersion`，且目标符号（prototype 方法、sortable 等）存在性探测；
   缺失则该模块自动禁用 + `console.warn`，不得抛错阻塞其他模块。
3. **禁止改写 ST 持久化用户设置**。反面教材：cocktail `applyChatTruncation` 劫持 `power_user.chat_truncation`，
   该模块（chat-render-optimizer）整体不移植。
4. 不移植：cocktail 的 auto-update-checker、cocktail-plus-installer、html-render-cache、chat-saving-unblocker；
   BaiBai 的其余功能（长聊天虚拟化、预设深补丁等由 BaiBai 本体继续承担）。
5. 与 ST-BaiBai-Tools 共存规则：只补 `PromptManager.prototype.render`，**不得触碰实例级**
   `makeDraggable / renderPromptManagerListItems / getPromptCollection`（BaiBai 的补丁领地）；
   **不得拦截 `#show_more_messages` 事件**（1.19.0 原生绑定是 click，`public/script.js:12579`；聊天渲染归 BaiBai）。
6. 砍掉原插件的设置 UI，硬编码合理默认值，只留一个总开关面板。
7. 每个模块头部注释注明来源仓库链接与原作者（cocktail by Limerence；BaiBai by 柏柏）。

### 验收

- ST 1.19.0 上逐模块验证开关生效；模块 1 打开预设面板开关条目无计数卡顿，关闭后恢复原生行为。
- 全部关闭+卸载扩展后，行为与 vanilla 完全一致（无残留事件、无残留 CSS 类）。
- 与 BaiBai 同开无互踩：预设拖拽仍为 BaiBai 实现，regex 面板操作无双重保存。

## 工作包 B · workbench-sync 服务端缓存

在 `server/workbench-sync/`（现有 TypeScript server 插件，`src/index.ts` 为入口）新增缓存模块
（如 `src/cache.ts`）。参考 cocktail-plus `server-plugins/cocktail-plus/src/endpoints/*.ts` 的思路，但：

- **禁止** source-patches 式改写 ST 源文件；只允许 express 路由级包装/覆写。

### 功能

1. `/api/settings/get` 缓存：空 body 的引导请求 → 缓存序列化响应体（当前 settings.json 约 5.1MB，
   是刷新最大开销）。失效条件：settings.json `mtime+size` 变化，或收到任何 `/api/settings/save`。
2. `/api/characters/all` 缓存：同法；`/api/characters/*` 变更类端点（edit/import/delete/rename 等）一律失效。
3. （可选，最后做）`/api/chats/save` 高频小写入合并。

### 要求

- 任何写端点必须**立刻**失效对应缓存（宁失效不脏读，多标签页安全）。
- 命中/未命中计数 + 字节数打日志（沿用插件现有日志风格）。
- 冷启动（容器重启）安全，无缓存时直接回源。
- 不影响 Basic Auth、CSRF 等现有中间件链。

### 验收

- 热刷新二次加载命中缓存，`/api/settings/get` 响应时间显著下降；保存设置后立即 get 拿到新值。
- 容器重启后行为正常；浏览器多标签页交替保存/刷新无脏读。
- 与前端 BaiBai 的 baibaoku 404 回退互不影响。

## 交付

- PR 至本仓库；两个工作包可分 PR 交付（A 先 B 后，或并行）。
- 相关路线图：`docs/plans/2026-10-25-absorb-roadmap.md`（本规格为其"性能"支线，互不冲突）。
