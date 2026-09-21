# favsync

配置驱动的轻量收藏下载器：Telegram Saved Messages、X 书签/点赞，以及可选的 EH、小红书和 Bilibili 下载服务。

Python 3.11 调度、SQLite 状态，底层使用固定提交的完整 gallery-dl、xiaohongshu-cli、XHS-Downloader 2.8、tdl 0.20.4 和带平铺补丁的 bili-sync 2.11.1；CookieCloud 提供 Chrome Cookie 同步。

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

EH 首次完整扫描只建立基线，不下载旧收藏。小红书首次启用会回填接口当前可见的
全部点赞或收藏。启用相应配置后，先以前台方式执行并检查结果：

```bash
docker compose --profile extended run --rm favsync --config /app/config.toml sync-once
docker compose --profile extended run --rm favsync --config /app/config.toml status
```

验收后再用 `docker compose --profile extended up -d --build` 启动常驻任务。低于
200 GiB 时暂停新下载，恢复到 220 GiB 后继续；远端取消收藏不会删除本地文件。

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
| `interval_seconds` | 列表扫描间隔，默认 28800 秒（8 小时）；上一轮未结束时不并发启动下一轮 |
| `command_timeout_seconds` | 单次导出或单个附件下载超时，默认 3600 秒；超大视频可调大 |
| `markdown_scope` | 本机设为 `platform`，各平台根目录一份 `收藏.md`，每条帖子完成后追加正文和媒体链接；不再生成独立 TXT |
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

两个 `收藏.md` 分别汇总该平台所有账号，每条消息/帖子一条列表项，包含正文、来源及日期；图片用 Markdown 预览，视频和普通附件提供本地链接。链接相对于 MD，整个平台目录一起移动后仍可使用。正文为空时显示“无正文”，不产生空 TXT。旧 `save_text` 开关已移除，文本统一进入 MD。

只有该帖子所有附件完成后才追加，失败待补齐后再写；纯文字帖子可直接追加。MD 使用隐藏的帖子 ID 完成标记去重，写入后 fsync，再提交数据库状态；重启、跨来源复用及文件写完但数据库尚未更新时不会重复追加。中断的不完整尾部可恢复。MD 是程序管理的追加文件，请另存副本做手工编辑，不要删除隐藏标记。已保存帖子不追踪之后的编辑。

书签、点赞和评审中的同一 X 帖子共享同一份文件及同一条 MD 记录。媒体先写入平台目录下隐藏的 `.partial-账号-ID`，完成后原子移入正式路径。不要删除 `state`：其中包含点赞基线、队列、Cookie 和 Telegram 会话。

备份时先停止服务，再备份 `state/`、`secrets/`、`config.toml`、`.env` 和统一根目录下本服务管理的平台文件；使用可选 CookieCloud 时也备份其数据卷。没有要求新增 PostgreSQL、Redis 或其他共享中间件。

## 本地开发与冒烟

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

本地运行另需 tdl 0.20.4 在 PATH 中（或配置 `telegram.tdl_binary`），将路径改为本地 `state`、`downloads` 和 `secrets/cookiecloud.json`。Docker 服务使用宿主机网络，以便访问 NAS 的 `127.0.0.1:7890` 代理；本地运行也必须能访问配置中的代理地址。Docker 构建会下载官方 tdl 二进制并核对官方校验和，支持 amd64/arm64；本次只在 amd64 验证。

## 多账号现状

Telegram 已支持 `[telegram]` 加 `[[telegram.accounts]]` 的多账号配置；X 目前一套账号和 Cookie，不支持混用其他账号。

冒烟使用合成数据验证日期、基线事务、失败重试、跨来源去重、正文、CookieCloud 两种解密格式与凭据失效隔离，不使用真实账号。**上线验收仍需用户登录后确认照片/视频/文档实际可打开、配文正确、书签日期符合实际、点赞基线后新增能下载。**

组件升级可能改变 X 接口和导出格式；依赖固定版本。扩展平台时添加适配器的 `scan` / `download`，复用状态和文件落盘机制，不添加全文索引或上下文抓取。

实现依据：[gallery-dl](https://github.com/mikf/gallery-dl)、[tdl 导出](https://docs.iyear.me/tdl/guide/tools/export-messages/)、[tdl 下载](https://docs.iyear.me/tdl/guide/download/)、[CookieCloud 解密参考](https://github.com/easychen/CookieCloud/blob/main/examples/decrypt.py)。

## X 有限评审批次

显式选择接口前 30 条点赞顺序下载，允许历史样本，不改变日常日期配置、点赞基线或 `first_seen_at` 含义。评审来源单独记录为 `x_review_likes`，媒体仍复用标准 X 帖子目录。

```bash
docker compose stop favsync
docker compose run --rm -T favsync --config /app/config.toml x-review --source likes --limit 30
docker compose up -d favsync
```

每条帖子完成后再处理下一条，同一帖子中的多个附件计为一条任务。状态内的 `x_review_likes:ids` 保存本次顺序；重跑命令重新选择当前前 30 条，已完成的文件不会重复下载。评审失败项需重跑评审命令补齐，日常来源不会主动下载旧点赞。

需要一次性补齐接口当前可返回的全部点赞时，将 `--limit 30` 换成 `--all`：

```bash
docker compose stop favsync
docker compose run --rm -T favsync --config /app/config.toml x-review --source likes --all
docker compose up -d favsync
```

这仍使用独立的 `x_review_likes` 来源，不重建日常点赞基线。重跑可复用已完成附件并重试未完成项；每帖全部附件落盘后才写入 `Twitter/收藏.md`。接口未返回的历史点赞不在此次补齐保证范围内。
