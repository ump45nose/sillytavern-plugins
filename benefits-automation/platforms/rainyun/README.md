# 雨云签到

单账号、一次性 Selenium 脚本。读取每日签到状态，未签时点击一次领取，必要时用固定来源的 OpenCV 算法处理腾讯验证码，重新打开积分页读回“已完成”与余额。调度和异常通知沿用 Hermes。

不加 `--execute` 不联网、不加载浏览器依赖。`--execute --status` 只读平台状态，不点击签到。可按需读取现有 CookieCloud 的雨云会话，或使用原有用户名/密码路径；不增加同步服务。

## 依赖与来源

Linux x86_64、CPython 3.12。Python 依赖单独安装，不影响 HTTP/Epic/Rewards 环境：

```sh
uv venv --python 3.12 /absolute/private/rainyun-venv
uv pip sync --python /absolute/private/rainyun-venv/bin/python --require-hashes \
  locks/rainyun-python312-linux-x86_64.txt
```

使用 CookieCloud 时，同时安装已有的解密依赖锁，复用其已验证版本：

```sh
uv pip sync --python /absolute/private/rainyun-venv/bin/python --require-hashes \
  locks/rainyun-python312-linux-x86_64.txt locks/cookiecloud-python312-linux-x86_64.txt
```

`provider-source.json` 固定 [LeapYa/Rainyun-Qiandao](https://github.com/LeapYa/Rainyun-Qiandao) 提交 `fdefba4dbec2d7e99568e08e182eda9c3026c75f`。该提交未发现 LICENSE；完整上游保持仓库外的独立 checkout，不在本项目分发：

```sh
git clone https://github.com/LeapYa/Rainyun-Qiandao.git /absolute/external/rainyun-provider
git -C /absolute/external/rainyun-provider checkout --detach fdefba4dbec2d7e99568e08e182eda9c3026c75f
```

运行时校验 `ICR.py` 与 `stealth.min.js` 的精确 SHA256，再加载已校验的字节。只调用 ICR 算法及注入浏览器脚本，不导入上游主程序。雨云页面选择器和验证码交互参考同一提交的 `rainyun.py`；上游调度、线程池、推送、截图上传、代理发现和随机指纹不进入执行器。

## 固定浏览器与驱动

`browser-contract.json` 固定 Chrome for Testing 与 ChromeDriver **153.0.8010.12**，对应 [Google 官方版本清单](https://googlechromelabs.github.io/chrome-for-testing/153.0.8010.12.json)。可以复用同版本已有 Chrome，ChromeDriver 另装到仓库外。安装时保留下载包中的许可证及 notices。

- Chrome：[官方 Linux64 包](https://storage.googleapis.com/chrome-for-testing-public/153.0.8010.12/linux64/chrome-linux64.zip)。
- ChromeDriver：[官方 Linux64 包](https://storage.googleapis.com/chrome-for-testing-public/153.0.8010.12/linux64/chromedriver-linux64.zip)，zip SHA256：`b7d5f7c120f7827f3538b416e08b82418eb702f18b680c183f0411c8d7f2df69`。

两个可执行文件的版本必须与契约完全一致；任务不调用 Selenium Manager，不在运行时下载或切换驱动。升级时同时核对浏览器契约、驱动及相关验证。

Chromium sandbox 保留。宿主须允许非 root Chromium 使用 user namespaces；若受宿主策略阻断，明确报错，不通过 `--no-sandbox` 启动。公共运行器的 run 路径较长，Chrome 的 Unix socket 不能直接放在那里；仅浏览器子进程的临时目录使用私有短 `/tmp/rainyun-*` 路径，正常退出清理，持久 profile 仍在账号 state 内。

## 私有配置与运行

仓库外绝对路径 JSON。推荐直接引用已有 CookieCloud 配置，不在新文件复制凭据：

```json
{
  "cookiecloud_config": "/absolute/private/cookiecloud.json",
  "chromium_path": "/absolute/chrome-linux64/chrome",
  "chromedriver_path": "/absolute/chromedriver-linux64/chromedriver",
  "provider_root": "/absolute/external/rainyun-provider"
}
```

每次只读取 `app.rainyun.com` 可用 Cookie，必须包含有效的 `rain-session`、`X-CSRF-Token` 和含整数 ID 的 `user-data`；原值通过私有进程内存注入浏览器，不进入日志或结果。配置了 CookieCloud 后会话失效直接返回 `authentication_invalid`，不会悄悄改用密码登录。

新 profile 首次注入 Cookie 后先由官方首页初始化完整用户缓存，再进入受保护的积分页；缺少这一步可能在会话有效时仍被前端路由守卫跳回登录页。完整缓存只由官方页面生成，不把同步服务扩成另一套用户数据库。

也保留用户名/密码配置，用于没有 CookieCloud 时登录或恢复该账号的持久 profile：

```json
{
  "username": "your-rainyun-login",
  "password": "your-private-password",
  "chromium_path": "/absolute/chrome-linux64/chrome",
  "chromedriver_path": "/absolute/chromedriver-linux64/chromedriver",
  "provider_root": "/absolute/external/rainyun-provider"
}
```

用户名和密码必须一起提供；两种认证方式至少有一种，同时提供时优先使用 CookieCloud。含密码的文件要求 0600。只有路径引用的配置允许受控的用户/组 ACL，拒绝向其他用户开放；FnOS 会把命名管理员 ACL 映射到组权限位，应以实际执行身份验证读取权限，不能把路径引用当成保存了密码的文件。

可选 `proxy` 为现有无用户名密码的 HTTP/HTTPS 代理地址，例如 `http://127.0.0.1:7890`。浏览器和验证码图片请求使用同一显式配置；不读取环境代理，不自动改线路、抓取免费代理或在代理失败后切直连。验证码图片最多 2 MiB、请求限时 15 秒，不跟随重定向。

```sh
RAINYUN_CONFIG=/absolute/private/rainyun.json \
/absolute/private/rainyun-venv/bin/python platforms/rainyun/run.py \
  --python /absolute/private/rainyun-venv/bin/python \
  --runtime-root /absolute/existing/shared-benefits-runtime \
  --account account1 --execute --status
```

确认读取账号状态正常后，去掉 `--status` 执行签到。默认总时限 360 秒，退出码及 JSON 契约沿用公共运行器；业务部分未确认返回 3，执行失败返回 1，锁忙返回 75，总时限耗尽返回 124。所有平台使用同一既有 `--runtime-root`，共享全局浏览器租约。

profile 和 `claim.json` 位于 `state/rainyun/<account>/<身份摘要>/`；CookieCloud 模式以雨云账号 ID 绑定，令牌轮换不换身份，密码模式沿用登录名摘要。账号代号不写邮箱。配置、密码、Cookie、图片 URL 和网页正文不进入结果；浏览器自身 profile 按私有运行数据管理。

## 确认与恢复

只有每日签到行的精确“已完成”表示签到确认；空白、“加载中”或其他文本为未知，不能用“不是领取奖励”判断成功。结果包含：

- `business.checkin`：签到状态。
- `business.balance`：最近一次余额读回是否明确。
- `details.metrics.balance`：最近核实余额、执行前后余额及本次差值；结束读取失败时保留此前 current，after/delta 为 null。差值不等于全天或可归因于签到的积分。

余额通过当前官方客户端的 `https://api.v2.rainyun.com/user/?no_cache=true` 读取 `data.Points`，不解析过时的绝对 XPath。请求使用浏览器当前 Cookie 与 CSRF，传回执行器的仅为业务码、积分及核对身份所需的内部 ID；完整用户响应不进入结果或诊断。CookieCloud 模式先核对当前服务端身份与同步身份一致，再接受业务状态或提交签到；首次身份查询不可用直接报 `account_identity_unconfirmed`，同次运行核对成功后的余额读取故障仍可保留签到确认。

点击领取之前持久保存 `pending`。点击抛出异常也只重新打开积分页读回一次；后续运行发现同日 pending 时不重新领取，直到读回已完成。不能通过删除状态文件来盲目重放未确认提交。次日使用新的业务日期。

验证码每轮运行最多两次。目标数/坐标不完整时尚未提交，可以换题；只有明确失败才允许再次提交。结果未知不刷新重试。验证码通过不代表签到成功，最终仍重新读取每日签到状态。

`claim_pending_readback` 表示已有不明确提交，需核对平台实际状态；`checkin_state_unknown` 表示页面结构或状态未识别；`authentication_invalid` 表示明确登录拒绝；`captcha_*` 表示验证未确认；`browser_version_mismatch` 表示预装浏览器/驱动不符。执行正常也不一定全部业务完成。

## 验证

离线行为测试不需要账号、Selenium 或网络：

```sh
python3 -m unittest discover -s tests -p 'test_rainyun*.py' -v
```

安装固定依赖后，可验证精确外部 ICR 算法对合成图案的识别；这不代表真实验证码通过率：

```sh
RAINYUN_TEST_PROVIDER_ROOT=/absolute/external/rainyun-provider \
/absolute/private/rainyun-venv/bin/python -m unittest discover -s tests -p 'test_rainyun*.py' -v
```

浏览器/sandbox 冒烟通过同一公共租约，仅打开 `chrome://sandbox/`，不访问雨云、不登录、不签到；使用独立 `rainyun-smoke` 结果分区：

```sh
RAINYUN_CONFIG=/absolute/private/rainyun.json \
/absolute/private/rainyun-venv/bin/python tests/rainyun_browser_smoke.py \
  --python /absolute/private/rainyun-venv/bin/python \
  --runtime-root /absolute/existing/shared-benefits-runtime \
  --account rainyun-smoke --execute
```

真实验收还需用本人的账号依次确认登录、未签/已签状态、验证码、签到后重载读回、积分查询和重复运行。没有账号联调证据时不能将离线测试或浏览器启动称为签到通过。
