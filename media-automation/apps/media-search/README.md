# Media Search · 寻片

独立的聚合查询网页，前端 Vue 3，API 为 Python/FastAPI。支持 M-Team、Mini4K，
媒体消歧、分站结果、分页、三种策略和指定资源下载。只负责下载提交及回执。
公共边界、安装前提与下载规则见 [获取能力设计](../../docs/media-acquisition.md)。
MoviePilot 只需安装共享包 0.4.0 和 MediaCapabilities 0.1.3 并启用公共宿主；
无需安装或更新 FilmWatchlist。站点、浏览器和 115 设置均在公共宿主中配置。

Mini4K 使用 NAS 持久浏览器。首次登录或会话失效后，在 NAS 终端运行
`docker exec -it moviepilot /opt/venv/bin/python -m media_capabilities.acquisition.mini4k_login`。
密码隐藏输入且不保存；追加 `--verify-only` 可只检查已保存会话。
登录失败会显示 `AUTH_REQUIRED` 和具体原因，不需要新增页面或保持桌面浏览器打开。

## 本地启动

在仓库根目录操作：

```sh
python3 -m venv .venv
.venv/bin/pip wheel --no-deps --wheel-dir .build/wheels ./packages/media-capabilities
.venv/bin/pip install --find-links .build/wheels -r apps/media-search/requirements.lock
cd apps/media-search/frontend
npm ci
npm run build
cd ../../..
.venv/bin/pip install --no-deps -e ./apps/media-search
```

在项目目录复制 `config.example.json` 为 `config.json`。设置可访问的 MoviePilot 地址，
并把 MoviePilot API 令牌和本服务独立访问令牌分别保存为只读挂载的 `0600` 文件。
它们不是片单 API 令牌。令牌文件不能进入 Git；访问令牌不保存在浏览器存储中。

```sh
.venv/bin/media-search --config apps/media-search/config.json
```

默认端口 8090。打开页面输入本服务访问令牌建立 HttpOnly 会话。
收藏 `http://localhost:8090/?q=片名`，或把浏览器自定义搜索模板设为
`http://localhost:8090/?q=%s`。下载前可明确选择电影/剧集、年份和剧集范围。
“自动选源下载”应用所选策略，“下载此资源”核实并提交指定候选。
页面显示逐站状态、字幕证据和下载回执，已有作品也可再次选择不同资源下载。

## 容器

构建上下文为仓库根目录，Compose 已配置：

```sh
docker compose -f apps/media-search/compose.yaml up -d --build
```

实际配置和令牌可放在仓库外，通过 `MEDIA_SEARCH_RUNTIME_DIR` 指定运行目录。
NAS 部署使用仓库根目录 Compose 加私有覆盖配置，网页仅发布到已选择的局域网地址；
更新时只操作 `media-search` 服务，保留其他业务容器。

Compose 默认只把 8090 发布到本机。容器内配置通常使用 `host=0.0.0.0`；
MoviePilot 地址需要通过实际容器网络或宿主地址可达，不会自动加入其网络。
将允许的域名/IP 加入 `public_hosts`；通过 HTTPS 反代时使用 `secure_cookie=true`。
反代应保留同源请求的 Host，并设置与请求上限匹配的读取超时。公网网关不由本项目配置。

网页 API：`POST /api/session` 登录，`POST /api/search` 查询，
`GET /api/search/{session_id}` 续查，`POST /api/search/{session_id}/more` 分页，
`POST /api/download` 提交，`GET /api/download/{task_id}` 读取回执。
API 也接受本服务的 `Authorization: Bearer ...`；Cookie 写请求需同源及 `X-Media-Request: 1`。
`GET /health` 只返回入口服务存活状态，不代表站点或下载器健康。
