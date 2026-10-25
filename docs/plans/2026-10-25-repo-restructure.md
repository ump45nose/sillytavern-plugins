# 2026-10-25 仓库形态重构：开发仓与发布仓分离

## 背景

工作台项目曾存在三条互不同步的副本（fork `workbench` 线、旧项目仓库 `ump45nose/sillytavern-workbench` 的 resource-center 线、聚合仓库 subtree 镜像），且版本号同为 0.4.0 但内容分叉，导致过一次按旧线产物部署生产的事故。本次重构收敛为：**本地 fork 只做开发调试，插件产物进独立发布仓，聚合仓库只作镜像**。

## 仓库角色

| 仓库 / 分支 | 角色 | 说明 |
| --- | --- | --- |
| `ump45nose/SillyTavern` @ `workbench`（本地 `/Users/yuwk/WorkSpace/Code/Github/SillyTavern`） | 唯一开发分支 | 上游基线 1.19.0 + 153 自有提交（S1 左栏 / S2 Markdown 编辑器 / S3 剧情选项 / S4 IDE 同步 / PWA 等）。`ci.yml` 只做门禁（check + 单测），不再发布。 |
| `ump45nose/noval-workbench` @ `main` | 前端扩展发布仓 | 根目录即安装目录（manifest.json / index.js / dist / addons）。由 publish workflow 自动跟进。 |
| `ump45nose/workbench-sync` @ `main` | 服务端插件发布仓 | 仅 `index.mjs`（esbuild 自包含 bundle）+ README + `.source-sha`。 |
| `ump45nose/sillytavern-workbench` | 已废弃 | 旧 resource-center 线残留（main = d60b9bf），无任何引用，可整仓删除。 |
| 聚合仓库 `/Volumes/Code`（与 fn `/home/yuwk/code` 为同一仓库的两种挂载视图） | 镜像 | `sillytavern-workbench/` subtree 与 fork `workbench` tree 完全一致；`projects.json` 来源已指向 fork。 |

已删除：fork 上的 `release` 分支、7 个 `claude/*` 分支、GitHub 上 12 个 fork 快照残留分支（默认分支已设为 `workbench`）。

## 发布机制

两个发布仓各有 `.github/workflows/publish.yml`：每 4 小时定时（或手动 Run workflow）用 `git ls-remote` 取开发仓 `workbench` 分支 SHA，与仓内 `.source-sha` 比对；有变化才拉源码 → `npm ci`（`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`）→ 构建（前端 `node scripts/build.mjs`；插件 `node scripts/build-sync.mjs`）→ 产物提交并推送，同时更新 `.source-sha`。无需跨仓库令牌。

- 前端安装（酒馆原生流程）：扩展 → 安装扩展 → 填 `https://github.com/ump45nose/noval-workbench`（默认分支即产物，无需填分支；安装目录名 = 仓库名）。已装扩展可用「切换分支」入口拉更新；manifest `auto_update: false` 不会自动更新。
- 服务端插件安装：`git clone https://github.com/ump45nose/workbench-sync.git plugins/workbench-sync`（或仅下载 index.mjs），确认 `config.yaml` 的 `enableServerPlugins: true`，重启酒馆。ST 1.19 加载 `plugins/*/index.{js,cjs,mjs}`，元数据来自 `info` 导出，无需 manifest。
- `npm run release`（生成 release 分支）已不是发布面；VS Code 扩展 vsix（`ide/vscode/dist/`，`build-sync.mjs` 顺带构建）目前仅在本地构建，未入发布仓。

## 开发流程（后续 agent 从这里开始）

```bash
cd /Users/yuwk/WorkSpace/Code/Github/SillyTavern
npm ci                # PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 可跳过浏览器下载
npm run build         # 前端 extension/dist + 服务端 workbench-sync/dist
npm run local:start   # 本地验证实例（32012 验证 / 32014 visual，凭据读 .env）
npm run check && npm test   # 与 CI 同门禁
npm run verify:*      # 各运行时回归（需实例）
git push origin workbench   # CI 过门禁后，发布仓 ≤4h 自动跟进（急可手动触发 publish）
```

`extension/dist` 不进 workbench 分支 Git，产物只存在于发布仓；改 `src/` 后必须重新 build 才能在挂载实例上生效。

## 生产部署现状（fn 192.168.31.201）

- 32001 容器 `sillytavern`：官方 1.19.0 镜像（digest 见 compose），compose 栈 `/vol2/1000/Docker/stacks/ai/compose.yaml`；数据卷 `/vol2/1000/Docker/sillytavern/{config,data,extensions,plugins,backups,public/avatar}` 全部保留。
- 前端扩展：`extensions/workbench/`（手动拷贝自 a6af249c8 构建，与发布仓同源）。若改为 URL 安装，必须先删除该目录，避免两份扩展同时挂载。
- 服务端插件：`plugins/workbench-sync/index.mjs`；`enableServerPlugins: true`；服务启动时加载，更新后需 `docker restart sillytavern`。
- 旧「纸本 story-workspace」v0.1.0 仍在 extensions 目录但已列入 `disabledExtensions`（新工作台检测到它会拒绝挂载）；settings 备份在 `/vol2/1000/Docker/sillytavern/backups/workbench-deploy-20261024-010602/`。
- 验证手段：`curl -u <basicAuth> http://192.168.31.201:32001/api/plugins/workbench-sync/info` 应 200；页面加载后存在 `#wb-root` 且 `window.storyWorkspace` 为假。basic auth 凭据在 fn 的 `config/config.yaml`，不要写入文档。

## 注意事项

- 聚合仓库同步（工作区常有其他项目脏文件，`project.py pull` 的 subtree 可能拒绝执行）：
  `git fetch sillytavern-workbench && git merge -X subtree=sillytavern-workbench sillytavern-workbench/workbench`
  同步后可用 `git rev-parse HEAD:sillytavern-workbench` 与 `git -C <fork> rev-parse workbench^{tree}` 比对校验一致。
- 上游 `SillyTavern/SillyTavern`：最新 release 仍为 1.19.0（2026-09-14）；`upstream/release` 仅多 1 个无关 workflow 提交，`staging` 持续推进。跟进新版本时从 fork 的 `upstream` remote 拉取合并。
- 酒馆安装弹窗支持「URL + 分支名（可选）」两个输入；目录名取 URL 仓库名。
- 生产页面有一个既有的 `$(...) is not a function` 报错，来源是某个 iframe 内脚本（about:srcdoc），与本项目扩展无关，不影响挂载。
