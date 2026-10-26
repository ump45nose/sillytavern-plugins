# 工作台功能吸收路线图

## P1 · 前置 AI 世界书路由（与数据库插件一起处理）

来源：ai-worldbook-router 0.3.6（已停用归档）。思路：生成前读取当前用户消息与近期上下文，
对当前角色卡/绑定世界书条目先做本地候选召回，再由前置 AI 从候选精选，仅将本轮相关内容注入
prompt。解决大世界书（三千条级）注入浪费与命中不稳的问题。

与数据库本体脚本（dataTable 表格数据库，jsdelivr 远程引入）一起处理：路由读取的"条目"可以
扩展为数据库表行，统一走一条"生成前检索-精选-注入"管线。

## P1 · 回复格式实时修复

来源：Response-Linter 1.4.4。思路：监听 MESSAGE_RECEIVED / MESSAGE_UPDATED / MESSAGE_SWIPED /
CHARACTER_MESSAGE_RENDERED 四类事件，对回复跑规则校验（残缺 XML、多余标签、格式越界），
命中后进入 auto-fix-engine 做文本级修复，修复失败可升级为重新生成（swipe/regenerate）。
解决模型输出格式坏块污染聊天的问题。工作台已有离线剥离（导出），补运行时校验-修复-重试链路。

## P2 · 上下文裁剪

来源：Extension-MessageLimit 1.0.0。限制每条 prompt 实际发送的消息条数（不含示例与注入）。
工作台楼层列表天然适合承载"可见但裁剪"的交互。

## 备选池

- 性能插件吸收（cocktail 六模块 + BaiBai gzip + workbench-sync 服务端缓存）：规格见
  `2026-10-25-perf-absorb-spec.md`，作为独立支线交由专项开发。

- 占位符/变量管理：占位符系统 v4.5（iframe 脚本 + localStorage 变量 + 拦截替换）思路可参考，
  待变量需求真实出现再立项。
- 说话人着色：Dialogue-Colorizer 的按说话人正则着色，表现层小功能，主题域即可承载。
