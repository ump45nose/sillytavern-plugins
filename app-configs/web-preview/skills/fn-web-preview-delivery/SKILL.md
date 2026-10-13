---
name: fn-web-preview-delivery
description: "将 HTML 网页、设计稿、布局方案或交互原型交付到 fn 的固定局域网预览入口。用户要求可打开的网址、远程查看 HTML、网页预览交付、刷新查看 AI 修改时使用；已有 fn 项目的独立 HTML 产物交付也使用。普通网站业务开发、酒馆运行功能验证或生产发布不属于此 skill。"
---

# fn 网页预览交付

固定入口：`http://192.168.31.201:33080/`。这是局域网入口；沿用用户现有的 fn 访问方式，不要求 Tailnet、不改公网入口。交付时给出实际 HTTP 链接，不能只给远程文件地址。

## 更新与交付

1. 读取 `/home/yuwk/code/app-configs/web-preview/README.md`，核对实际容器和路由；入口失效时排查，不默认新建服务。
2. 已登记项目直接更新原目录，保留稳定路径。酒馆设计目录为 `/home/yuwk/code/sillytavern-workbench/docs/design/`，映射到 `/sillytavern/`；RP 网址为 `http://192.168.31.201:33080/sillytavern/rp-desktop/`。
3. 若源文件是 fragment，运行项目导出脚本生成独立 HTML；RP 使用 `python3 /home/yuwk/code/sillytavern-workbench/scripts/render-rp-preview.py`。目录默认打开 `index.html`，其次 `preview.html`。
4. 新方案在已挂载目录下建子目录或独立 HTML，更新 `/home/yuwk/code/app-configs/web-preview/public/index.html` 的链接。新项目复用此服务，按 README 增加专用交付目录的只读挂载；禁止挂载整个源码根目录或带秘密的目录。
5. 用最终 HTTP 地址验证页面可打开、资源路径正确、核心交互和用户实际视口。核对 `Cache-Control: no-store`；页面更新应刷新生效，无需重启。仅修改服务器代码或挂载才操作服务。
6. 最终回复给出方案的固定网址，简述修改与验证；按用户要求提交对应 Git 文件，保留无关改动。明确这是设计预览，避免把它当作实际酒馆功能验收。

## 基础设施边界

服务 `fn-web-preview` 属于 `utilities`，唯一正式定义为 `/vol2/1000/Docker/stacks/utilities/compose.yaml`，源码和 skill 在 `app-configs/web-preview/`。不为每次交付新增容器、临时端口、HTML 副本或部署定义。

需要调整基础设施时，先读取 fn 的 AGENTS.md、`/vol2/1000/Docker/STACKS.md`、`/vol2/1000/Docker/stacks/README.md` 和目标仓库约束，核对实际 Compose 与容器。仅更新受影响服务，并同步文档、启动计划和运行 `python3 /home/yuwk/cron/scripts/container-boot.py --check`。日常网页交付不触发重新部署，也不额外要求用户确认已有授权。

Skill 的 Git 来源为 `/home/yuwk/code/app-configs/web-preview/skills/fn-web-preview-delivery/`，安装目录为 `/home/yuwk/.codex/skills/fn-web-preview-delivery/`；修改 skill 后同步两者并用 skill-creator 的 `quick_validate.py` 校验。
