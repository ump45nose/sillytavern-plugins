# fn 固定网页预览

局域网入口：<http://192.168.31.201:33080/>，当前 RP：<http://192.168.31.201:33080/sillytavern/rp-desktop/>。

服务 `fn-web-preview` 属于既有 `utilities` 组。唯一正式 Compose 为 `/vol2/1000/Docker/stacks/utilities/compose.yaml`，这里不存第二份部署定义。服务使用 Python 标准库，无额外依赖；端口只绑定 fn 局域网 IP，不依赖 Tailnet，不新增公网反代。

## 日常交付

- 目录首页：本目录 `public/index.html`，增加方案时补充链接。
- 酒馆路径 `/sillytavern/`：只读挂载 `/home/yuwk/code/sillytavern-workbench/docs/design/`，目录访问优先 `index.html`，其次 `preview.html`。
- 修改 HTML、CSS 和图片直接刷新生效，不需要复制或重启；页面响应使用 `Cache-Control: no-store`。
- 如果设计使用 fragment 源文件，先运行该项目的导出脚本。例如 RP：`python3 /home/yuwk/code/sillytavern-workbench/scripts/render-rp-preview.py`。服务展示生成的 `preview.html`。
- 新项目使用已有服务：在正式 Compose 增加其专用交付目录的只读挂载到 `/app/public/<project>/`，更新首页；只重建 `fn-web-preview`。不要挂载整个 Code 根目录。
- 不交付秘密、运行数据和完整仓库。服务禁止隐藏路径、目录列表、目录越界及非预览文件类型。

## 维护与验证

服务以 `1000:1001` 运行，根文件系统只读、capabilities 全部移除，禁止提权。服务代码与入口目录都按目录挂载，原子替换文件也可立即看到。修改 `server.py` 才需要重启进程；仅改页面无需重启。

```sh
docker compose -p utilities -f /vol2/1000/Docker/stacks/utilities/compose.yaml up -d --no-deps fn-web-preview
curl -fsS http://192.168.31.201:33080/healthz
python3 /home/yuwk/cron/scripts/container-boot.py --check
```

容器启动登记在 `/home/yuwk/code/nas-cron-jobs/nas-container-boot/container-boot-order.txt`，部署副本在 `/home/yuwk/cron/scripts/container-boot-order.txt`。基础设施调整前遵循 fn 的 AGENTS.md，并读取 STACKS.md 与 stacks/README.md。

Skill 源码：`skills/fn-web-preview-delivery/`。复制到 `~/.codex/skills/fn-web-preview-delivery/` 即可供后续 HTML 交付任务自动匹配。

2026-10-09 验证：目录页 10 个方案链接均返回 200；RP 在局域网 HTTP 页面通过 19 项检查、8 种视口；HTML 原子替换立即生效。3 项标准库测试覆盖私有路径与符号链接边界、目录预览与禁止列表、缓存和 HEAD 行为（运行 `python3 -m unittest -v test_server.py`）。Dockge 原版 utilities 页面可见新服务，容器健康；启动检查 missing、active_unplanned、stopped_planned 均为空。交付 skill 已安装并通过 quick_validate.py。

2026-10-09 新增大纲与生图交互预览，固定路径 `/sillytavern/addons/`。首页补充右栏、完整大纲和生图配置入口；源目录仍在既有设计挂载中，不改服务或部署定义。目录 14 个链接均返回 200 和 `no-store`。该页面是设计审阅，尚未接入酒馆运行功能。

2026-10-12 新增 `/fiqa-xiaoyu/` 模型选片对照。生成页面位于 `/vol2/1000/Docker/face-baseline/previews/fiqa-xiaoyu/`，专用目录只读挂载，不提供图库、数据库、权重或实验环境。生成源码在 face-baseline/scripts/compare-fiqa.py 和 fiqa-comparison.html；改页面直接刷新，无需重启。

新增嵌套只读挂载前，先在父挂载的源码 `public/<project>/` 建空目录占位（如 `.gitkeep`）；否则只读父挂载无法在容器启动时创建新挂载点。实际预览文件仍放独立交付目录。
