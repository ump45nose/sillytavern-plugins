# favsync

配置驱动的轻量收藏下载器：Telegram Saved Messages 与 Bot 投递、X 书签/点赞，以及可选的 EH、小红书、Bilibili、Pixiv 收藏和 Wallabag EPUB 导出。

从新版部署起，X 书签、小红书收藏以及发给 `@yuwk_notice_bot` 的新消息在媒体完成后各生成一份独立 Markdown，正文和本地图片/视频链接位于同一文件。X/小红书点赞与 Telegram Saved Messages 的新记录只下载媒体。历史 `收藏.md` 与旧文件保持不变；来源间共享媒体的帖子只有成为书签/收藏后才生成 Markdown。

Python 3.11 调度、SQLite 状态，底层使用固定提交的完整 gallery-dl、xiaohongshu-cli、XHS-Downloader 2.8、tdl 0.20.4 和带平铺补丁的 bili-sync 2.11.1；CookieCloud 提供 Chrome Cookie 同步。

Pixiv 与 Wallabag 的部署、凭据和验收步骤见 [PIXIV_WALLABAG.md](PIXIV_WALLABAG.md)。两者复用现有 SQLite、8 小时调度、磁盘保护和执行结果记录，不增加新的队列或搜索服务。

## EH、小红书和 Bilibili

三个扩展来源默认关闭。Chrome CookieCloud 需在现有 X 域名之外同步
`xiaohongshu.com`、`e-hentai.org` 和 `exhentai.org`，凭据仍只写入 secrets。

```bash
docker compose --profile extended build favsync xhs-downloader bili-sync
docker compose --profile extended up -d xhs-downloader bili-sync
docker compose run --rm favsync --config /app/config.toml status
```

Bilibili WebUI 位于 `http://192.168.31.201:12345`。认证 token 保存在
`secrets/bili-sync-token`，可在项目目录执行 `cat secrets/bili-sync-token`
读取；不要从容器日志取 token。添加指定收藏夹，保存路径选择 `/downloads/Bilibili`。下游补丁默认每 8 小时
扫描、使用 `作者_标题` 平铺命名，只保存视频和字幕。

### B 站影视片单

`[film_watchlist]` 是独立的元数据来源，不会让 bili-sync 下载“电影”收藏夹的视频。
当前账号下该收藏夹的完整 ID 是 `4117812456`，可在配置中更换。Favsync 只读复用
bili-sync SQLite 中已维护的登录凭据，完整分页读取标题和简介；两者没有共用写入状态。
每条视频只从**标题**中的《》提取片名，简介仅用于提取明确标注的首次上映或首播日期。
同名同年作品合并，不确定日期保持 `null`。`released` 按配置时区与已记录日期计算，
代表计划日期已到，并非对实际公映的外部核实。移出收藏夹不会删除片单。

首次前台验收时暂停常驻 Favsync，再运行：

```bash
docker compose stop favsync
docker compose run --rm favsync --config /app/config.toml sync-once --source film_watchlist
docker compose run --rm favsync --config /app/config.toml status
docker compose up -d favsync favsync-api
```

片单 API 默认绑定本机；当前 NAS 配置为 `192.168.31.201:18082`。在项目的
`.env` 中设置 `FILM_API_TOKEN`（建议文件权限 `0600`），Compose 仅将它传给
`favsync-api` 容器；未设置时服务拒绝启动。令牌不写入源码或日志。调用示例：

```bash
FILM_API_TOKEN="$(sed -n 's/^FILM_API_TOKEN=//p' .env)"
curl -H "Authorization: Bearer $FILM_API_TOKEN" \
  'http://192.168.31.201:18082/v1/films?downloaded=false&limit=50'
curl -X PATCH -H "Authorization: Bearer $FILM_API_TOKEN" \
  -H 'Content-Type: application/json' -d '{"downloaded":true}' \
  'http://192.168.31.201:18082/v1/films/1/downloaded'
unset FILM_API_TOKEN
```

`GET /v1/films` 支持 `offset`、`limit`（最大 200）、`downloaded=true|false`、
`released=true|false|unknown`；`GET /v1/films/{id}` 返回单项。
`POST /v1/films` 可用相同令牌手动加入或补充片单身份，必填 `title` 与
`release_year`，可填 `release_date`（`YYYY-MM-DD`）、`country`（如 `法国`）
和 `media_type`（`movie` 或 `tv`）。同名同年重复提交返回同一条记录，不清除下载状态。
`PATCH /v1/films/{id}/downloaded` 只接受布尔值。`downloaded` 新建时为 `false`，
后续由媒体库侧写回；Favsync 重扫不会覆盖它。首版只提供接口，不自动检查 Emby。

EH 首次完整扫描只建立基线，不下载旧收藏。小红书使用受限增量模式：每轮最多读取
2 页、接纳 5 条新笔记、查询 5 条详情；遇到一整页均为已见 ID 时立即停止。它不再
自动回填整个历史列表。启用相应配置后，先以前台方式执行并检查结果：

```bash
docker compose --profile extended run --rm favsync --config /app/config.toml sync-once
docker compose --profile extended run --rm favsync --config /app/config.toml status
```

验收后再用 `docker compose --profile extended up -d --build` 启动常驻任务。低于
200 GiB 时暂停新下载，恢复到 220 GiB 后继续；远端取消收藏不会删除本地文件。

小红书的 `auth_required`、验证码、461/471、429、IP 限制、账号变化或首个空详情会
写入持久安全熔断。Cookie 更新和容器重启都不会自动解除。处理登录/验证并检查原因后，
先保持两个来源关闭，手工清除熔断，再前台启用一项做小批量验收：

```bash
docker compose run --rm favsync --config /app/config.toml xhs-resume --account personal
```

详情解析成功后会短期缓存；媒体下载失败不会在同一轮反复查询作品页面。两个来源共享
单轮详情额度和 15–30 秒随机请求间隔。`status.xhs_observations` 分别显示每来源的扫描页数、新 ID、详情请求、媒体成功数与首个错误。真实浏览器/CDP 也不能消除平台风控风险。

## 开始使用

在项目目录操作。先填写配置、完成登录，再启动常驻下载。Telegram 和书签起始日期默认留空，点赞默认关闭，避免未配置就开始扫描账号。

```bash
cp -n config.example.toml config.toml
mkdir -p state/home downloads secrets
chmod 700 state secrets
printf 'PUID=%s\nPGID=%s\n' "$(id -u)" "$(id -g)" > .env
docker compose build
```

编辑 `config.toml`：

| 配置 | 含义 |
| --- | --- |
| `telegram.start_date` | 填 `YYYY-MM-DD`；按消息进入 Saved Messages 的日期筛选 |
| `x_bookmarks.start_date` | 填 `YYYY-MM-DD`；按书签时间筛选 |
| `x.username` | 自己的 X 用户名，不含 `@`，启用点赞时必填 |
| `x_likes.enabled` | 准备好后设为 `true`；初次只建基线，不下载历史点赞 |
| `*.account` | 本地账号标签；两个 X 来源必须一致，首版只连接一个 X 账号 |
| `interval_seconds` | 列表扫描间隔，默认 28800 秒（8 小时）；重启会参考上次完成时间，不会立即额外扫一轮；上一轮未结束时不并发启动下一轮 |
| `command_timeout_seconds` | 单次导出或单个附件下载超时，默认 3600 秒；超大视频可调大 |
| `markdown_scope` | 仅供旧 `收藏.md` 历史记录恢复使用；新目标消息逐条写入同目录 Markdown |
| `telegram_notice` | 选择已有 tdl 登录账号及 Bot 用户名，只读取该账号发给 Bot、且在新版部署后出现的消息 |
| `download_dir` / `.env` 的 `DOWNLOAD_ROOT` | 全部平台共用容器 `/downloads`，本机根目录 `/vol3/1000/Picture/Downloads`；禁止另设 Telegram 独立下载根目录 |
| `proxy.url` | 统一代理地址；当前 NAS 默认 `socks5://127.0.0.1:7890` |
| `proxy.default_enabled` | 默认 `true`，以后加入的平台自动继承代理 |
| `proxy.applications.<标识>` | 每个应用一个布尔开关；`telegram`、`x` 默认代理，`cookiecloud` 默认直连 |
| `cookiecloud.url` | 已有 CookieCloud 地址或可选服务的 `http://127.0.0.1:18088` |

日期含当天，采用 `timezone`（默认 `Asia/Taipei`）。日期留空的来源显示 `awaiting_start_date`，不会开始下载。修改配置后 `docker compose restart favsync`。把 Telegram 起始日期改早会重新扫描历史并去重；改晚不会删除已有文件或已入队任务。

### Chrome Cookie 同步

1. 安装官方 [CookieCloud](https://github.com/easychen/CookieCloud) Chrome 扩展，在 Chrome 登录自己的 X、小红书和 EH/ExHentai 账号。
2. 已有 CookieCloud：将其地址填入配置。没有：运行 `docker compose --profile cookiecloud up -d cookiecloud`。
3. 扩展设为上传模式，域名关键词填 `x.com`、`twitter.com`、`xiaohongshu.com`、`e-hentai.org`、`exhentai.org`，同步间隔设为 8 小时。关闭不需要的 LocalStorage 同步；favsync 按平台拆分 Cookie，单个平台同步失败只暂停该平台。
4. 将扩展显示的用户 KEY 和加密密码写到 `secrets/cookiecloud.json`，格式参考 `cookiecloud.credentials.example.json`。在本机文件中填写，不需要发到聊天。
5. 手动同步一次扩展，然后运行一次下载器。支持 CookieCloud 的 `legacy` 和 `aes-128-cbc-fixed` 加密；只拉取密文并在下载器本地解密，不把解密密码发到服务端。

可选服务默认仅监听 NAS 的 `127.0.0.1:18088`。Chrome 在另一台电脑时，通过现有 HTTPS 反向代理访问，或在 `.env` 设置 `COOKIECLOUD_BIND` 为 NAS 的局域网/Tailscale IP；扩展填写电脑可访问的地址。favsync 使用宿主机网络，通过 `http://127.0.0.1:18088` 读取本地 CookieCloud。不要将 CookieCloud 端口无认证地开放到公网。

CookieCloud 上传端是 Chrome，下载器不会远程读取 Windows 浏览器数据库。浏览器关闭时不会产生新同步；失效后仍需在 Chrome 重新登录。同步失败保留旧 Cookie；X、小红书或 EH 单个平台认证失败时只暂停对应来源，Cookie 内容变化后自动再试。

如果临时手工导入，可将 Netscape Cookie 文件放入 `state/x-cookies.txt` 并关闭 `cookiecloud.enabled`；文件需包含 X 的 `auth_token` 和 `ct0`。账号更换时使用新的 account 标签；若 Cookie 中有 `twid`，程序会检测账号切换并阻止混用基线。

### Telegram 登录

支持多账号。原来的 `[telegram] account = "personal"` 是主账号；额外账号在配置中增加：

```toml
[[telegram.accounts]]
account = "second"
enabled = true
start_date = "2026-08-10"
```

每个账号有独立会话和 SQLite 游标；Telegram 文件在配置目录平铺，文件名中的账号和消息 ID 保证互不覆盖。任务逐个处理。额外账号省略的字段继承主账号。先在手机 Telegram 切换到想添加的账号，再扫码。

```bash
docker compose stop favsync
docker compose run --rm favsync --config /app/config.toml telegram-accounts
docker compose run --rm favsync --config /app/config.toml telegram-login --account second
# 验证码模式同样可以选择账号：
docker compose run --rm favsync --config /app/config.toml telegram-login --account second --mode code
```

登录必须在交互式终端运行，不加 `-T`、不重定向输入输出。已有会话默认不会重新登录或覆盖。如需为**同一个账号**更新会话，显式加 `--replace`；程序会在临时目录完成认证，成功后备份旧会话到 `state/session-backups/` 再原子替换，失败或取消不会改动旧会话。更换为另一个 Telegram 用户应使用新标签，避免混用历史游标。

`telegram-accounts` 中 `session_exists` 只表示会话文件存在，真实授权状态由同步请求验证。未指定 `--account` 时使用主账号。登录完成后重新启动服务。

若旧的直接 `tdl login` 容器仍运行，会占用会话数据库；先退出该登录进程，再使用以上入口。数据库占用会显示 `telegram_session_in_use`。授权失败时，该账号暂停访问 Telegram，替换会话后下轮自动恢复，其他账号和 X 不受影响。

X 使用 SOCKS5 代理时自动采用远端 DNS（`socks5h`），保留域名供代理路由；Telegram 仍使用 tdl 支持的 `socks5`。两者仍走配置中的同一代理地址。

```bash
# 如果已运行，先停止，防止两个进程同时使用会话和状态。
docker compose stop favsync
docker compose run --rm favsync --config /app/config.toml telegram-login
# 也支持验证码模式：
docker compose run --rm favsync --config /app/config.toml telegram-login --mode code
```

按 tdl 提示扫码或输入验证码/两步验证密码。会话保存在 `state/tdl`；不用 Telegram Bot Token，也不读取 Chrome Telegram Cookie。不要重复登录覆盖正在使用的会话。

Telegram 登录、扫描和附件下载都会使用统一代理配置。正常命令会自动带上代理，无需再手写 `docker run --network host`。若某个平台确实应直连，只把其应用标识设为 `false`，例如 `proxy.applications.telegram = false`。

### 执行与状态

```bash
# 前台执行一轮，便于首次检查。与常驻进程互斥。
docker compose run --rm favsync --config /app/config.toml sync-once

# 常驻运行；如需同时启动内置 CookieCloud，加 --profile cookiecloud。
docker compose up -d favsync
docker compose logs --tail 100 -f favsync
docker compose exec favsync favsync --config /app/config.toml status
```

`sync-once` 有失败返回非零；日期未填或来源关闭为正常待配置状态。`status` 展示来源扫描状态、点赞基线时间、附件状态数量、下载错误类别、待保存正文数和 Cookie 同步时间。它还展示最近 20 次内容同步及 CookieCloud 执行结果，只记录 `success` 或 `failed`；SQLite 最多保留 100 条。扫描完成不等于附件全部成功；请同时检查 `assets`、`download_errors` 和本地文件。

当前 NAS 另由 Lingjun Hermes Cron `favsync-daily-summary`（ID `d11d29184eec`）每天
09:10 将过去 24 小时的简单成功/失败和当前来源异常发送到 Telegram 运维 topic
`telegram:1766985794:11829`。它是 no-agent 任务，不调用模型，也不触发下载；只通过
`docker exec` 读取 `status` 的脱敏 JSON。部署脚本来源为
`scripts/hermes_favsync_daily_summary.py`，运行副本位于
`/home/hermes/.hermes/profiles/lingjun/scripts/favsync_daily_summary.py`。

没有启动服务时也可运行 `docker compose run --rm favsync --config /app/config.toml status`。`state/worker.lock` 防止多个写入进程并发；状态查询可与常驻进程同时执行。

## 下载规则

- Telegram 使用 Saved Messages 自身的消息 ID 和消息时间，不使用转发原文时间。照片、视频、音频、语音、文档等由 tdl 支持的文件附件均下载；相册按每条消息分别保存。投票、位置、联系人等非文件结构不归档。
- X 只保存目标帖子/回复的媒体和正文。不扩展对话、引用原帖、卡片、文章或外链，不额外抓取作者档案。接口响应附带字段仅临时解析，不持久化整份 JSON。
- 书签使用 gallery-dl 的 `date_bookmarked`，不是推文发布时间。缺失/异常的时间会显示 `bookmark_time_unknown` 并暂缓该项目，不阻塞其他已确认日期的项目。
- 点赞首次扫描正常结束后，在一个事务内建立已有 ID 基线。扫描中断/限流/导出错误不会完成基线；重试从头扫描。在基线初始化期间发生的点赞可能进入基线而不下载，实际起点是 `baseline_at`。
- 基线之后，未见过的点赞 ID 入持久化队列，`first_seen_at` 仅代表程序发现时间。取消后再次点赞同一帖子不重复下载；暂停后恢复沿用基线。
- 扫描全部接口可见列表，不因遇到已下载 ID 就提前停止。X 接口隐藏的历史、分页截断、两次扫描之间又取消的点赞均无法保证捕获；API 可见范围变化可能让旧点赞被当作首次发现。
- 列表扫描和附件重试分离。普通失败下一轮补齐；认证失败暂停相关来源，X 限流至少等待 15 分钟或一个扫描周期。不会快速循环重试。
- 已下载文件不追踪后续编辑；线上取消收藏/点赞或删除，不删除本地文件。修改起始日期也不清理本地文件。

Telegram 当前宿主机目录：`/vol3/1000/Picture/Downloads/Telegram`。文件直接平铺：

```text
yuna申有娜_精妈俱乐部_kpop_2026-09-18_personal_116.jpg
收藏.md
```

各字段用单个下划线连接；标签去掉 `#` 后直接拼接，不加空格和括号。标签和话题不存在时省略；日期按配置时区的收藏消息日期（进入 Saved Messages 的时间）。没有可确认群组来源时用“收藏夹”；有群组 ID 但无法读取群名时用“来源群组-ID”。名称清理路径字符并限制字节长度。账号和消息 ID 用于避免同群同日文件覆盖；首个附件不再追加 `_001`，仅同一消息的第二个及后续附件加 `_002` 等。

仅为命名临时读取 Saved Messages 原始字段、群名/话题名；需要确认话题时仅查询该条转发的原消息，不展开对话或下载原频道。原始导出用后删除，只存命名所需的最小字段。群名缓存及每条消息已确定的名称保持稳定。

所有平台统一使用 `.env` 的 `DOWNLOAD_ROOT=/vol3/1000/Picture/Downloads`。Telegram、Twitter、小红书、Bilibili 和 EH 分别位于其下的 `Telegram/`、`Twitter/`、`Xiaohongshu/`、`Bilibili/` 和 `EH/`；EH 子目录在容器内挂载为 `/eh-downloads`。变更根目录时先停止服务、迁移已有 Favsync 文件并核对文件，再修改挂载，执行 `docker compose up -d --force-recreate`。不要移动 NAS 中其他服务管理的目录。

Twitter 同样平铺：标签去掉井号并拼接，作者名称占群名位置，无话题则省略，日期使用推文发布时间（不是点赞时间）。文件名示例：`标签_作者_2026-09-18_personal_帖子ID.jpg`；多附件追加 `_002` 等。

```text
/vol3/1000/Picture/Downloads/
  Telegram/
    收藏.md
    yuna申有娜_精妈俱乐部_kpop_2026-09-18_personal_116.jpg
  Twitter/
    收藏.md
    标签_作者_2026-09-18_personal_帖子ID.jpg
```

上例中的两个 `收藏.md` 是旧版历史汇总，保持原样。新版新目标内容采用与媒体同目录的逐条 `.md`，图片可预览，视频是本地相对链接；正文为空则只保留媒体。旧 `save_text` 开关已移除。

只有目标消息所有附件完成后才写新版逐条 MD，失败待补齐后再写；纯文字目标消息可直接写入。文件以临时文件原子替换，并在 SQLite 中记下来源关系与导出状态。历史 `收藏.md` 仍用隐藏标记去重，请勿删除标记。已保存内容不追踪之后的编辑。

书签、点赞和评审中的同一 X 帖子共享媒体；新逐条 MD 仅在它进入书签时创建。媒体先写入平台目录下隐藏的 `.partial-账号-ID`，完成后原子移入正式路径。不要删除 `state`：其中包含点赞基线、队列、Cookie 和 Telegram 会话。

备份时先停止服务，再备份 `state/`、`secrets/`、`config.toml`、`.env` 和统一根目录下本服务管理的平台文件；使用可选 CookieCloud 时也备份其数据卷。没有要求新增 PostgreSQL、Redis 或其他共享中间件。

## 本地开发与冒烟

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[all]'
.venv/bin/python -m unittest discover -s tests -v
```

本地运行另需 tdl 0.20.4 在 PATH 中（或配置 `telegram.tdl_binary`），将路径改为本地 `state`、`downloads` 和 `secrets/cookiecloud.json`。Docker 服务使用宿主机网络，以便访问 NAS 的 `127.0.0.1:7890` 代理；本地运行也必须能访问配置中的代理地址。Docker 构建会下载官方 tdl 二进制并核对官方校验和，支持 amd64/arm64；本次只在 amd64 验证。

只使用状态/片单 API 或不需要全部来源时，可以安装基础包 `pip install .`。
X/EH/Pixiv 使用 `.[gallery]`，小红书 CLI 使用 `.[xhs]`；`.[all]` 和现有
Docker 镜像继续包含两种后端。固定上游版本不变，不要求新增后台服务。
采集事务由 `acquisition.py`/`Store.apply_scan` 负责，下载队列由
`downloads.py` 负责；`Engine` 的现有入口保持兼容，原状态和输出路径不变。

## 多账号现状

Telegram 已支持 `[telegram]` 加 `[[telegram.accounts]]` 的多账号配置；X 目前一套账号和 Cookie，不支持混用其他账号。

冒烟使用合成数据验证日期、基线事务、失败重试、跨来源去重、正文、CookieCloud 两种解密格式与凭据失效隔离，不使用真实账号。**上线验收仍需用户登录后确认照片/视频/文档实际可打开、配文正确、书签日期符合实际、点赞基线后新增能下载。**

组件升级可能改变 X 接口和导出格式；依赖固定版本。扩展平台时添加适配器的 `scan` / `download`，复用状态和文件落盘机制，不添加全文索引或上下文抓取。

实现依据：[gallery-dl](https://github.com/mikf/gallery-dl)、[tdl 导出](https://docs.iyear.me/tdl/guide/tools/export-messages/)、[tdl 下载](https://docs.iyear.me/tdl/guide/download/)、[CookieCloud 解密参考](https://github.com/easychen/CookieCloud/blob/main/examples/decrypt.py)。

## 维护入口与任务隔离

当前来源统一登记在 `favsync/sources.py`；日常任务只生成单篇 Markdown。历史大 Markdown 和旧 Telegram 布局迁移保留在独立维护模块中，正常同步不调用它们：

```bash
docker compose run --rm -T --entrypoint python favsync -m favsync.maintenance --config /app/config.toml telegram-relayout
```

此维护命令会搬迁旧布局，只在确实需要历史迁移时执行。失效的 `x-review` 入口已下线，原有评审记录、基线和文件保留。

调度器闲置期间可直接执行 `sync-once --source film_watchlist` 等单来源任务，无需停止常驻服务。实际同步或登录期间仍互斥；第二个常驻调度器也会被拒绝。重启沿用最近完整内容周期与 Cookie 周期的完成时间，不自动触发额外全量同步。

数据库连接与版本迁移分离；写入服务启动时显式升级，`status` 使用只读连接。片单 API 只校验自身配置。B 站凭据读取由 `bili_credentials.py` 封装，仅读取已有 bili-sync SQLite。

单个来源发生异常会记录失败并继续后面的来源；认证和风控异常停止同账号后续请求。小红书保留现有请求上限与熔断，已见但未完成的笔记仍可刷新访问令牌；达到页数或条目额度记录 `partial` 和具体原因。日报区分受限扫描与完整扫描，并列出 Wallabag 正文已保存但图片不完整的数量。

修复与验收记录见 [2026-09-29 repair](docs/reviews/2026-09-29-repairs.md)。

## 2026-10-08 NAS 部署说明

NAS 正式入口现为 `/vol2/1000/Docker/stacks/automation/compose.yaml`，Favsync 与 Steam ASF 共用 automation 项目。组入口直接声明正式业务定义；本仓 Compose 保留为开发与配置参考。原容器名、favsync_default 网络与 CookieCloud 卷名保留。更新仅指定受影响服务。Wallabag 的持久目录以 PHP-FPM 原生 65534:65534 写入，管理员通过受控 NAS ACL 管理。

## 陪伴作者素材

`xhs_creators` 是独立、可关闭的只采集文本来源，默认八位已选作者，允许在私有配置中以 `creators = [{id = "...", name = "..."}]` 扩充。每轮按最近扫描时间选择至多两位作者，先使用共享的两个详情名额，其余预算供收藏/点赞。复用既有小红书身份验证、15–30 秒请求间隔、缓存和持久风控熔断；不自动解除熔断。作者首页刷新与最近 90 天增量翻页交替进行，近期未处理图文优先，视频不下载、不转录。有限读取一页评论，仅导出至多五条作者自己的回复。

正文去标签后不足 80 字时，对前两张图执行 RapidOCR 3.9.2 + ONNX Runtime 1.24.3 的中文 PP-OCRv5 mobile CPU OCR，单任务、两个计算线程。检测、识别、方向模型在构建时下载固定版本并校验 SHA256，运行时只读取镜像内模型；图片哈希和 OCR 版本共同缓存，置信度低于 0.85 的文字不进入素材。OCR 失败保留正文和私有笔记缓存，后续预算轮次重试；不会重新下载视频。模型清单与校验值见 `favsync/companion_ocr.py`。

既有 API 新增 `GET /v1/companion/materials?cursor=0&limit=100`，独立 `COMPANION_MATERIALS_TOKEN` Bearer 鉴权。接口只读缓存，最大分页 100；返回正文、可信 OCR、作者回复、无签名原帖链接、作者来源、发布时间、前后更新关系与采集状态。增量 cursor 为单调修订号，不返回 Cookie、xsec_token 或访问令牌，不触发即时采集。素材令牌不能操作影视接口；影视令牌也不能读取陪伴素材。生产令牌保存 automation 的 `env/favsync-api.env`，不进入 Git。

OCR 集成在现有 Favsync worker，API 仍由 Favsync API 提供，不增加常驻容器。角色生活规划、聊天上下文及投递幂等由 `nas-cron-jobs` 负责，不在采集器生成陪伴文案。数据库 schema 增量升级后，回退使用关闭作者源与消费者的方式保留新表；不要将旧镜像直接挂载新 schema 数据库。
