# 第一轮原生实现检查点

## 已完成并离线验证

共享标准库 runner、六个独立目录/入口、环境白名单、同账号 flock、跨平台 browser flock、总超时/中断进程组清理、流式有界日志、精确凭据脱敏、严格结果身份/大小/schema、原子发布、独立签到确认缓存和未知收益退出码。

SMZDM：复用原签名/请求顺序；已签到、验证码、风控、查询失败分别表示。写请求不自动重试。签到后读回失败仍保留签到确认，奖励标记 unknown。

V2EX：从 MIT 的 dailycheckin 25.12.9 单独提取 V2ex.sign，保留原许可证和 wheel/module hash；避免其 __init__ 全平台 eager import。假 Session 与原函数对照验证已签到、新签到、无效 cookie 三条路径。旧 provider 会传 verify=False，新 BoundedSession 强制证书验证。日期判定保留 Asia/Shanghai。最小 HTTP 依赖锁固定 requests 2.32.5 和传递依赖，独立 venv 安装；不再依赖整个 dailycheckin/RSA/PyCryptodome。

Aliyun：外部 daily.py 取自 WillpowerJin/ql-scripts，候选提交 37f42204a8eea3a489e67e866a2b356bed4b9b22；SHA256 286563810a780f06edaa0eea2dd0633480b403d6634ab3357d0890df77b696c3。完整源码未再发布（该来源无明确 LICENSE）。仅验证字节后导入，cookie 登录、签到、明确资格的领取、积分读回；不调用上游 main/run、通知、清理、视频或场景互动。ALIYUN_UPSTREAM_PATH、ALIYUN_COOKIE、ALIYUN_PROXY 是入口环境变量。未验证真实 API。

Laowang：原签到读回、持久 profile、只读 status；人工 login 支持受监督 TTY stdin 并持有双锁。已尝试本地真实 Firefox smoke：官方 fallback 下载成功，Firefox155/revision1543 启动后报 Could not find profile folder，在 /tmp、共享目录与独立 HOME 均复现；未通过浏览器验收。未执行 GUI 登录。验证码自动求解已从活跃路径移除，默认停止交给人工。

## Epic 的具体阻塞

已有确切上游源码候选与文件 hash；原生 preflight 不导入未知应用、不启动服务器。已有 AST 必需方法检查、零价/购物车纯函数测试。

执行前仍须解决：

1. settings.py 导入模型配置及补丁，默认创建源目录 volumes；统一外部账号 state/evidence 路径
2. browser_context 默认录屏且支持 Camoufox→Firefox 后备及虚拟 Xvfb；需关闭默认录屏，证明上下文/Xvfb 全生命周期和本地页面 smoke
3. 上游认证/订单路径能自动触发 CAPTCHA、条款和 SSO 页面动作；需审查全部调用链并默认 human_required，不能只补丁三个方法就宣称覆盖
4. 完整 uv.lock 安装、Python/native/browser 版本和有许可证的上游组合确认
5. 订单提交、全部零价路径、已有购物车保护、最终所有权读回的完整 mocked integration

当前入口明确返回 native_paths_challenge_and_checkout_audit_required。不会领取、登录、支付、解验证码或调用模型。

## Rewards 的具体阻塞

已取得官方 v4.3.2 候选 f61f4e982bbb435f37133bed0dc5b4c582ed1e73（GPL-3.0+），这不能证明它与旧 NAS local image 内容完全相同。官方要求 Node >=24。已有 package/source hash 和资源配置验证器，严格区分 null/0/未知资格/真实空清单。

执行前仍须解决：

1. 证明旧私有适配器与候选上游的 ReactFunc、audit 类/方法及 sessions SQLite schema 完整相容
2. 固定依赖安装+构建 dist，禁止运行时猜测缺失模块
3. 账号明确单选；clusters=1、searchSettings.parallelSearching=false、clusterSearch=false、headless=true、workers.doDailySet=false 的完整运行配置验证；关闭外部 webhook/通知
4. 将旧 before→daily→extra→upstream→after 顺序迁到一次性脚本，全部 state/evidence 路径外置，并逐段确认前一浏览器退出
5. 原 snapshot/daily/extra 对完整 body/HTML、长日志、history 的无界写入需要替换；summary 纯函数不能冒充完整任务
6. 本地 SQLite/schema/React fixture、浏览器 smoke 和 upstream 内部并发测量

默认 full 入口明确返回 session_schema_build_and_browser_serialization_audit_required，不会运行完整上游。新增显式 --mode activities：独立单浏览器每日活动卡片流程，读取每账号 storage-state.json，null 进度停止、卡片/循环有界、一次点击后只读回、关闭 popup/context/browser、Chromium sandbox 开启。8 项假浏览器/SQLite/计数测试通过。不会搜索、extra、通知；daily complete 仅表示每日活动，不表示完整 Rewards。尚未真实浏览器/账号验证。

## 尚未完成的公共验收

- cgroup 硬限制、脱离进程组的 child containment、launcher SIGKILL 后自动全树回收：未实现，不能作保证
- 总历史/日志保留数量、每日汇总、CookieCloud 原生同步：未实现；不会擅自删旧数据
- 真实浏览器/账号、峰值 RSS/PSS、长时残留、NAS 架构及代理路径：未验收
- 调度安装、旧容器停用、会话/凭据迁移：本轮未执行
