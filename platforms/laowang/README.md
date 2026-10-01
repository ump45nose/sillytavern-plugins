# Laowang 原生任务与 tncode 恢复

来源是保留在 upstream/laowang-checkin/sign.cjs 的 MIT 代码。当前入口是 run.py，经共享账号锁、浏览器锁、总360秒初始预算、进程组清理后执行独立 Firefox 脚本。--status只读，--login为受监督的人工TTY入口。

## 已实现的具体恢复代码

- tncode.cjs 保留原三层图片像素差匹配、至少50个有效样本、相邻5像素外第二候选、置信度比率1.08、28步滑动加4步回调轨迹
- 图片宽高/滑块及像素数量有上限；图片仅在浏览器内分析，不写截图、原图或完整网页
- challenge.cjs 在可信调用方授权当前阶段/图片后才按需加载solver。打开、刷新、拖动前后重新读取证据；已加载图片以像素SHA256指纹绑定，未加载时使用本页nonce，不能跨会话复用旧批准
- 最多两次尝试。只有服务器明确拒绝才刷新并重新授权；响应丢失、不明或图片低置信度停止，不能盲目重放
- 响应必须来自HTTPS laowang.vip/captcha/check.php，且为有界明确的 _ok；不再用“任意文本包含_ok”当成功。未提供可验证小响应长度时保持unknown，实际响应格式需现场验收
- CAPTCHA通过不等于签到完成。先只读核验是否已签到；仍未确认时，只点击唯一 #submit-btn 一次，再最多三次只读确认 .qdleft .btnvisted
- sign-intent.json在qiandao请求、最终submit前记下意图。同业务日区分request_attempted、challenge_pending、captcha_attempted/rejected/accepted、submit_attempted；不确定拖动/提交只读核验，不能自动再次提交；最多两次拖动的预算跨重启保留；一个文件按明确业务日更新，不无限追加历史
- reward/streak/days恢复为有界数字或null的只读结果，写入本次run的laowang-status.json；奖励值展示不自动等同已领取收益

## 可信宿主边界与未完成项

默认CLI没有自动授权器。遇到tncode会生成共同协议的待处理checkpoint并停止；不从JSON、环境变量或本地文件读取“同意”标记。common/interventions负责请求范围/有效期检查，但普通JSON本身不能证明真实用户授权。

宿主可调用 run(firefox, profile, {intent, authorize, challengeOptions})。authorize(observation)必须由已经验证主人身份与当次或事先明确授权的范围的宿主实现，只有精确范围及当前图片证据匹配才返回null；其他返回值表示等待授权。真实操作需要针对具体挑战或事先明确授权的范围的批准，刷新后的新图片必须重新验证覆盖。intent应由createIntent提供该账号/业务日的持久实例。直接API缺少intent不允许签到写操作。

这已经是具体的像素匹配、鼠标与服务器响应绑定，不只是空的solver接口；但CLI到可信宿主的授权传递仍未接通，普通跨进程恢复没有真实来源证明。原源码在qiandao响应页面处理验证码，而新一轮首先读取base sign页面；不能假设该base页面仍展示原挑战。实现只保留一个条件性恢复路径：已记录正常challenge_pending/明确拒绝，且新鲜base页面实际展示同源挑战和唯一submit控件时，经重新授权才继续，不重复qiandao。假页面测试证明此条件契约，不证明真实网站会保留该页面。否则只读等待核验；旧拖动或最终提交不确定也不能重放，不通过删除intent自动绕过。

本轮只用了合成图片、假页面与假响应，没有访问Laowang、登录或解决真实验证码。真实页面字段、Cookie有效性、响应格式和完整业务还没有端到端验收。浏览器本机启动情况见 ../../docs/RESOURCE_CHECK.md，不能替代业务验收。

## 来源障碍分支对照

| 原代码分支 | 保留/整合方式 | 回归 |
|---|---|---|
| 已签到/只读status | 未授权也可读取，零提交 | adapters.test.cjs |
| formhash缺失/过期 | 明确authentication_unconfirmed，不猜测登录 | 原适配器流程 |
| qiandao导航超时 | 记录意图后只读reconcile，未知不重发 | intent及假流程 |
| 图片加载失败 | 有界等待，最多一次经授权刷新 | challenge.solve上限 |
| 像素不足/低置信度 | 同算法阈值、显式失败原因 | laowang-challenge.test.cjs合成图 |
| slider不存在/多个 | 拒绝猜测；鼠标退出时释放 | 具体drag绑定 |
| captcha拒绝 | 明确拒绝才可再授权/一次重试 | rejected→accepted |
| captcha响应丢失 | unknown、零重复拖动 | uncertain response |
| captcha已过但签到未证实 | 先读业务，再唯一submit，再只读确认 | auto-signed/submit timeout |
| 浏览器/会话中断 | finally关闭；持久意图防重放 | 关闭、跨实例意图 |
| 保存state与截图 | 持久profile保留会话；不另复制凭据/原图 | 敏感数据与输出界限 |

完整真实恢复链路、认证恢复和跨进程批准传递仍属于待完成能力，没有被当作“为了轻量而删除”。
