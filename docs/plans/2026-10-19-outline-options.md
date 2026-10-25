# 大纲作为主线指引 + 剧情选项（2026-10-19）

分支 `claude/wonderful-raman-75b0bc`（基于 63462b7）。

## 范围与关键决定

- **大纲与数据库插件不重叠。**
  - 数据库存的是事后的事实：人物、纪要、长楼层归纳。
  - 大纲是作者事先写好的意图。
  - 只有数据库的「剧情推进」也在引导下一轮。为此，大纲只提供数据：宏 `{{outline}}` 加一个默认关闭的自动注入。用户自己决定把宏写进预设、选项提示词，还是数据库剧情推进的提示词。
- **大纲按聊天保存。** 一个大纲就是一个新故事。另外可以粘贴导入，也可以从其他聊天复用；复用时保留节点树和正文，进度清零。
- **进度由作者手动推进。**
  - 在侧栏点节点，展开详情卡，在卡里「设为当前 / 标记完成」。
  - 同一时间只有一个当前节点（status = active）。
  - 标记完成后，按阅读顺序把下一个未完成的叶节点设为当前。
  - 自动写作和编辑器里的状态下拉也走同一个 `advance`。
- **`{{outline}}` 的内容：** 上级背景 + 当前节点 + 「下一节点 · 标题」。宏和注入都在 `AddonManager` 里，插件不加载也能工作。
  - 宏用 `registerMacro`，新旧两种宏引擎都适用。
  - 注入用 `setExtensionPrompt("noval_outline")`：聊天内，system 角色，深度可调。
- **选项来源按聊天选择：** 关闭 / 模型输出 / 数据库表。数据库表名也按聊天绑定。
  - 模型输出：注入提示词，让主模型在回复末尾附带 `<options>` 块；显示时隐藏，不带进历史，导出时去掉。
  - 数据库表：读数据库插件的 `exportTableAsJson`，订阅它的表格更新回调。
  - 交互：点一次展开详情，再点一次填入输入框，不发送。

## 验收

- 单元测试：
  - `tests/outline-context.test.mjs`：只有一个当前节点、手动推进、`{{outline}}` 拼接、复用时进度清零；
  - `tests/options.test.mjs`：选项块的解析与去除、表格转选项。
- verify:writing-addons：详情卡推进节点、宏展开、注入开关、粘贴导入、从其他聊天复用。
- verify:rp、verify:pwa：选项的两种来源、单击展开再点填入、历史里不含选项块、手机端。
- 全量门禁通过。

## 进度

- [x] 大纲：`advance`、`outlineContext`、`reuseOutline`，只有一个当前节点
- [x] 大纲：详情卡（设为当前 / 标记完成）、侧栏当前节点行、粘贴导入、从其他聊天复用
- [x] 大纲：`{{outline}}` 宏与主线注入（在工作区设置）
- [x] 选项：纯逻辑与单元测试
- [x] 选项：运行时（模型输出与数据库表）
- [x] 选项：界面与设置、记录导出
- [x] 验证脚本与全量门禁

### 验证结果（2026-10-19，实测）

- 单元测试 75 项通过；format / check / typecheck / build 无报错。
- 逐个通过：workbench、compat、home、resources、interactions（输入框工具按钮由 6 个增至 7 个，期望值已同步）、fidelity、migration、motion、click-motion、preferences、rp（32）、addons、utilities、writing-addons（14）、pwa（18）、edge、layout-controls、stale。
- verify:styles 未执行比对：基线 `artifacts/baseline-c6/computed` 在本机不存在，只完成了快照。

## 未验证

- 真实模型是否稳定输出 `<options>` 块（只用模拟模型验证过）。
- 真实数据库插件 `exportTableAsJson` 的表格格式（只用模拟数据验证过）。
- 数据库剧情推进的提示词会不会展开 `{{outline}}`。
