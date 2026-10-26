# Workbench · Perf

SillyTavern 1.19.0 前端性能扩展，Noval · Workbench 的配套扩展，也可单独使用。六个模块各自独立，可分别开关，单个模块失败不影响其他模块：

| 模块 | 作用 | 来源 |
| --- | --- | --- |
| 启动预取 + 提前解遮罩 | 扩展加载时并行预取头像、角色、背景，首屏更早可操作 | cocktail `startup-optimizer` |
| 保存请求 gzip 上行 | 设置、聊天、世界书、预设等大 JSON 保存请求压缩后上传 | ST-BaiBai-Tools `gzipHook` |
| 预设 dry-run 后台化 | 预设面板先立即重画，token 计数放到后台 | cocktail `preset-panel-optimizer` |
| 正则面板免重刷 | 开关正则脚本不再整聊重渲染 | cocktail `regex-refresh-optimizer` |
| 抽屉动画 transform 化 | 内容多的抽屉展开收起不再逐帧重排 | cocktail `ui-animation-optimizer` |
| 世界书指示线拖拽 | 拖拽排序条目时只移动影子和指示线 | cocktail `worldinfo-drag-optimizer` |

## 安装

酒馆「扩展 → 安装扩展」，填 `https://github.com/ump45nose/wb-perf`。安装目录名为 `wb-perf`。设置保存在 `extension_settings.wbPerf`，在扩展面板的「Workbench 性能优化」里开关各模块。

只适配 SillyTavern 1.19.x；版本不在此范围时不启用任何模块，并在面板里说明原因。已装 cocktail 时请先停用或卸载它，避免两套补丁同时生效。

## 来源与致谢

模块改编自 [cocktail](https://github.com/Lianues/cocktail)（作者 Limerence）与 [ST-BaiBai-Tools](https://github.com/baibai-git/ST-BaiBai-Tools)（作者 柏柏），每个模块文件头部注明了具体来源。

本仓库由 [ump45nose/SillyTavern](https://github.com/ump45nose/SillyTavern) 的 `main` 分支 `perf-extension/` 目录自动发布，请在源仓库提交修改。
