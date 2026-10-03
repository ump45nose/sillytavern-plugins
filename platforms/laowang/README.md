# Laowang 签到

独立 Firefox 脚本，打开签到页、读取当前 formhash、访问 qiandao、自动处理 tncode 滑块、提交一次并重新查询签到状态。2026-10-03 NAS 已通过真实账号完整流程。

## 安装和运行

需要 Python 3.12、Node、Playwright Firefox 及浏览器二进制：

```sh
cd platforms/laowang
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm ci --ignore-scripts
npx playwright install firefox
```

从仓库根目录调用，使用持久账号 profile 或已有 CookieCloud 的站点 Cookie：

```sh
COOKIECLOUD_CONFIG=/absolute/private/cookiecloud.json \
LAOWANG_PROXY=http://your-existing-proxy:7890 \
python3 platforms/laowang/run.py --runtime-root /absolute/private/runtime \
  --execute --browser-cache /absolute/browser-cache
```

CookieCloud 的格式、可选 crypto 依赖见 [公共凭据说明](../../docs/CREDENTIALS.md)。需要该 Python 环境时加 `--python /absolute/venv/bin/python`。CookieCloud 只把 laowang.vip 的 Cookie 注入本次 context，不读取其他站点数据，不增加服务。

`--execute --status` 只读查询；`--execute --login` 是可选的交互登录入口，需要 TTY 和 DISPLAY。profile 位于 `state/laowang/<account>/browser/`，均在仓库外。返回通用 JSON，`checkin=complete` 仅在站点读回已签到时产生。

## 验证码与恢复

tncode 算法按需加载，图片仅在浏览器内分析，不落盘。最多两次拖动，跨进程保留尝试数。响应必须来自站点 `/captcha/check.php`，2xx 且符合实际的有界 `_ok` token；明确 `error_*` 拒绝才允许刷新后重试。不明响应不重复拖动。

公开 `--execute` 已绑定本平台普通登录会话下签到验证码的操作范围，无需 Hermes 再提供审批通道。新 formhash 每次从当前页面取得，不能把旧 URL 的 hash 写死。

`sign-intent.json` 区分请求、验证码、最终提交。验证码成功后先查业务，再点击唯一提交控件一次；最终提交不明确时只读恢复。日状态只存账号代号和动作事实。奖励/连续天数等数字写本次 `laowang-status.json`，不把无法读取的奖励额误判为签到失败。

来源为 [laowang-checkin](../../upstream/laowang-checkin/)，MIT；具体回收与结果协议使用 `common/`，没有其他平台依赖。
