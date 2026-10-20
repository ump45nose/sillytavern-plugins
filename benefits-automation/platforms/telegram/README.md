# Telegram 机器人签到

用账号自己的 Telegram Web K（`web.telegram.org/k`）登录会话，按配置给指定机器人发送签到命令、读取回复，可选点击一次内联按钮。不使用 MTProto 库、`api_id` / `api_hash` 或 session 字符串；Telegram 看到的是官方网页客户端。调度和通知由调用方负责。

## 依赖

Python 3.12 标准库、Node 24、Playwright Firefox 1.63.0（与 Laowang 同版本，复用同一浏览器缓存中的 Firefox revision 1543）：

```sh
cd platforms/telegram
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
npx playwright install firefox   # 已有共享 --browser-cache 时不需要
```

持久 profile、固定版本依赖校验和终端登录使用 `common/persistent_browser.cjs`；结果、明细与私有文件检查使用 `common/result.cjs`、`common/details.cjs`、`common/private_file.cjs`。平台只写 Telegram 业务逻辑；页面结构假设集中在 `selectors.cjs`。

## 配置

`TELEGRAM_CONFIG` 指向仓库外的绝对 JSON 路径，权限要求与其他私有配置相同（当前运行身份所有，0600；兼容所属组 0640/0660）。按 `--account` 代号分账号，示例见 [config.example.json](config.example.json)：

```json
{
  "spacing_seconds": [5, 20],
  "accounts": {
    "tg-ai": {"bots": [{"id": "checkin", "username": "ExampleCheckinBot", "command": "/checkin",
      "success": ["签到成功"], "already": ["已签到"], "failure": ["签到失败"]}]},
    "tg-nsfw": {"spacing_seconds": [10, 30], "bots": [{"id": "menu", "username": "ExampleMenuBot",
      "command": "/start", "button": {"text": "签到"}, "success": ["签到成功"], "already": ["今日已签到"]}]}
  }
}
```

- `username`：机器人用户名，不带 `@`；必须以 `bot` 结尾，避免把命令误发给真人。每账号最多 20 个机器人，`id` 为结果和 journal 使用的短代号。
- `command`：单行文本，原样发送一次。
- `success` / `already` / `failure`：回复中出现的子串（不区分大小写、NFKC 归一）。判断顺序 already → failure → success；`success` 必填。只看本次命令之后的回复，先到的公告或“正在签到，请稍后”不会提前结束等待。“人机验证 / 请先加入频道”这类入群门槛建议写进 `failure`，报告 `bot_rejected`（需要手动加入后再签），而不是等到 `reply_timeout`。`already` 避免只写“已经”：不少机器人的成功回复含“您已经获得 1 积分”。确定命令时先看 Web K 输入 `/` 弹出的命令菜单和机器人简介，不要逐个试发。
- `button`：可选。回复中带有包含该文字的内联按钮时点击一次；此时只认可点击后新出现或内容改变的消息，以及按钮回调弹出的提示，菜单本身的文字不能确认签到。
- `points`：可选 `{"pattern": "积分为:?\\s*(\\d+)", "unit": "points"}`。正则只能有一个捕获组（数字），与其他模式一样匹配 NFKC 归一、不区分大小写的回复（全角冒号视为 `:`）；`unit` 为 points / coins / beans，默认 points。确认签到时取最近一条匹配回复的数字，写入 `details.metrics.points_<id>`（`id` 中的 `-` 换成 `_`）的 `current`；没有匹配或当天已由 journal 确认、未打开对话时为 null。只保存数字，不保存回复文本。
- `reply_timeout_seconds`：5–120，默认 30。`enabled: false` 跳过且报告 `not_applicable`。
- `spacing_seconds`：两个需要访问的机器人之间的随机间隔，默认 5–20 秒，可按账号覆盖。

可选 `TELEGRAM_PROXY`（例如 NAS 现有的 `http://127.0.0.1:7890`）只用于本浏览器 context。

## 登录、查询与执行

每个 Telegram 账号使用不同账号代号，profile 位于 `state/telegram/<account>/browser/`，仓库外、0700，等同于登录凭据。

```sh
export TELEGRAM_CONFIG=/absolute/private/telegram.json
export TELEGRAM_PROXY=http://127.0.0.1:7890
R=/absolute/private/benefits-data
C=/absolute/browser-cache

# 一次性扫码登录（需要交互终端，例如 ssh -t）；无界面浏览器，不需要 DISPLAY
python3 platforms/telegram/run.py --runtime-root $R --browser-cache $C --account tg-ai --execute --login
# 只读：确认已登录并列出当日 journal，不打开机器人对话
python3 platforms/telegram/run.py --runtime-root $R --browser-cache $C --account tg-ai --execute --status
# 签到
python3 platforms/telegram/run.py --runtime-root $R --browser-cache $C --account tg-ai --execute
```

`--login` 在终端提示：手机 Telegram → 设置 → 设备 → 连接桌面设备，扫描运行目录中自动刷新的 `telegram-login-qr.png`（0600，路径显示在终端；登录结束后删除）。账号开启两步验证时，终端会要求输入密码，不回显、不写日志或文件。密码只填入 Web K 真正的密码框（跳过页面自带的隐藏 `.stealthy` 诱饵框），确认填入长度一致后提交，再等待 Telegram 的明确结果：只有网页把密码框标红（Telegram 拒绝）才计为一次错误，连续 3 次返回 `password_not_accepted`；提交后页面毫无反应返回 `password_submit_unconfirmed`，校验超时返回 `password_check_timeout`，填入不完整返回 `password_input_unconfirmed`，空输入返回 `password_not_entered`，这些情况都不会再次提示输入。最长等待 600 秒（便于把二维码转发到另一设备扫描）；`--login` 的运行超时自动不低于 900 秒；按 Enter 提前结束。结果 `login_verified` 表示网页已进入聊天列表。提示写到终端，运行日志仍只收 stdout。

不加 `--execute` 不读配置、不启动浏览器。`--execute --status` 与签到在没有 profile 时直接返回 `not_logged_in`，不启动浏览器；页面显示登录卡片时同样返回 `not_logged_in`，不发送任何消息。两个账号由全局浏览器锁串行执行。

## 执行与恢复

1. 打开 Web K，确认已登录；逐个打开 `web.telegram.org/k/#@<username>`。NAS 代理到 web.telegram.org 偶尔断开一两分钟：打开页面（只读）失败时每 30 秒重试，最多约 180 秒，仍失败返回 `telegram_app_unavailable`；发送命令从不重试，由 journal 保证当天只发一次。
2. 当日 journal（`state/telegram/<account>/telegram-journal.json`）为 confirmed 的机器人直接报告完成，不打开对话。
3. 未开始过的机器人（只显示 START）返回 `bot_not_started`，不代按 START；请先在手机上手动开始一次。
4. 命令写入输入框并核对后，先在 journal 记 sent，再点击发送按钮（不按 Enter，避免选中命令建议）。之后当天只读回：找到本次命令之后的回复并匹配，确认后记 confirmed。
5. 已 sent 但未确认的机器人（例如上次超时或进程中断）不会重发，只读历史；仍无法确认时报告 `previous_send_unconfirmed`。按钮同样只点击一次。

journal 只保存阶段、消息编号和按钮消息文本的 16 位 hash，不保存命令、回复或任何消息文本；回复文本只在进程内存中匹配，不进入结果或日志。

## 结果

`business.checkin`：全部启用的机器人确认后为 complete；`details.items` 每个机器人一项（`id`、`@username`、`https://t.me/<username>`、状态、原因），`details.metrics.bots` 为确认数/启用数，配置了 `points` 的机器人另有 `points_<id>`。原因包括 `checkin_confirmed`、`already_checked_in`、`bot_rejected`、`reply_timeout`、`reply_unrecognized`、`button_not_found`、`command_not_visible`、`previous_send_unconfirmed`、`bot_not_started`、`chat_unavailable`、`input_unconfirmed`、`send_control_unavailable`、`bot_disabled`。整体失败原因：`not_logged_in`、`configuration_missing`、`configuration_invalid`、`account_not_configured`、`private_file_invalid`、`journal_invalid`、`state_save_failed`、`selector_broken`、`telegram_app_unavailable`、`browser_or_network_error`、`dependency_unavailable_or_incompatible`。

## 生产调度

与其他签到任务相同，由 `nas-cron-jobs` 的 Hermes 无 agent 作业 `benefits-telegram-ai`、`benefits-telegram-nsfw` 经 `benefits_native_runner.py` 调用（`--execute`，不加 `--status`），部署配置中作业键为 `telegram-ai` / `telegram-nsfw`、`platform: telegram`。每次尝试保存 `runs/<run_id>/result.json`、`results/telegram/<account>/latest.json` 和 `delivery/<作业键>.json`；成功不通知，中午的福利异常日报列出未确认的机器人和原因（`bot_rejected` 显示为需人工处理）。时间在台北 01:00 之后：部分机器人的“一天”晚于台北零点切换。

## 测试

```sh
node --test tests/telegram.test.cjs tests/persistent-browser.test.cjs
python3 -m unittest tests.test_telegram
# 可选：真实 Firefox 只渲染本地合成页面，拦截全部网络
PLAYWRIGHT_BROWSERS_PATH=/absolute/browser-cache node tests/telegram_browser_smoke.cjs
```

合成页面按 morethanwords/tweb 579e559（2026-10-16）的稳定标记编写，不含真实账号页面；Telegram 改版导致选择器失效时返回 `selector_broken`，只需更新 `selectors.cjs`。真实签到需用户登录后验收；离线测试通过不代表已经签到。

## 风险

使用官方网页客户端和账号本人的会话，每天每个机器人只发一条命令并随机间隔；不批量私聊、不加群、不处理验证码或数学题（遇到时报告未确认）。profile 即登录状态，泄露等同账号被登录，可在 Telegram → 设置 → 设备中随时终止该网页会话。
