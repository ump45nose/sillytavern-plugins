# 第二轮 S1：左栏自适应（2026-10-20）

分支 `claude/friendly-hamilton-04ad17`（基于 `workbench` bdef9d291）。总计划第 1 节；S2–S4 在其他会话并行，本分支不碰 Composer、World、Characters、Persona。

## 范围与关键决定

- **条数不再写死。** 历史对话显示全部；楼层显示全部，删除「只看最近 5 层 / 显示全部」切换及 `.wb-nav-more`。
- **楼层窗口化。** 固定 30px 行高（手机抽屉 44px），只渲染可见行和上下各 8 行；`<ol>` 高度等于全部楼层。
  - 打开楼层区（或切换聊天）时，正在阅读的楼层出现在可见区顶部往下第 4 行；接近末尾时停在底部。
  - 之后列表「钉」在阅读楼层上：新楼层、聊天滚动都会跟随，直到用户把该行滚出视野；滚回来后重新跟随。
  - `.wb-ui button` 的通用 `min-height: 34px` 原本把导航行撑到 34px，现在导航行按声明的 30px 显示（历史对话同样变矮）。
- **高度分配：纯函数 `planSections()`（`src/ui/navLayout.ts`）。**
  - 展开区自然高度之和放得下：全部按自然高度。
  - 只有一个展开区：占满剩余高度，区内滚动。
  - 多个展开区放不下：每区先限到栏高的 45%，剩余空间按顺序还给被限的区（与焦点无关，悬停不会引起跳动）。
  - 仍然放不下：只保留焦点区（占满剩余高度），其余展开区自动收成标题行（`is-auto-folded`，标题行末有强调色小圆点和提示）。焦点区收起后，它们恢复展开。
  - 焦点：最近展开、悬停或键盘聚焦过的**已显示**区。不用 scroll 事件：区收起时 scrollTop 被夹紧也会触发 scroll，会让焦点来回跳。
  - 点击自动收起的区：让它成为焦点，用户自己的展开状态不变。
- **测量。** 一个 `ResizeObserver` 观察 `.wb-nav-sections` 和各区 `.wb-nav-body`（内容包装层，量自然高度）；区内滚动层 `.wb-nav-scroll` 通过 `--wb-nav-max` 限高。
- **手机抽屉不参与分配。** 抽屉整体滚动（pwa.css 原有规则），只做窗口化。
- **大纲。** 删除 `.is-outline-expanded` 特例和侧栏树自己的高度上限，侧栏里只有区这一层滚动。大纲区仍然初始折叠，附加功能保持懒加载。自动收起不会卸载大纲（`active` 跟随用户展开状态），否则自然高度归零会造成反复折叠。
- **测试基础设施（跨模块）。** 本地 validation / visual 实例的 `workbench-probe` 软链指向主工作区，工作树跑 verify 实际测的是主工作区的构建。`scripts/browser.mjs` 的 `session()` 现在把 probe 的文件路由到当前检出的 `extension/`，各工作树共用实例也能验证自己的代码。

## 验收

- `tests/nav-layout.test.mjs`：自然高度、单区占满、45% 与剩余空间、只保留焦点、焦点收起后恢复、间距与未测量。
- verify:home / verify:interactions：楼层断言改为「全部楼层（窗口化）」。
- 截图检查 1366 / 1440 / 1920：一个区很长时其他区自动收起，收起该区后其他区恢复；阅读楼层在可见区内；滚到顶部渲染第 1 层。
- 全量门禁：check、test、format:check、build；verify:workbench、home、addons、writing-addons、pwa、interactions、rp、styles。

## 进度

- [x] `planSections` 与单元测试
- [x] Navigation：全部条目、楼层窗口化、自动收纳、焦点
- [x] CSS：desk.css、outline/style.css；验证脚本断言
- [x] browser.mjs 路由当前检出的构建
- [x] 门禁与 verify:*、三种宽度截图

## 验证记录

- check、test（93 通过）、format:check、build 通过。
- verify:workbench、home、addons、writing-addons、pwa、interactions、rp 全部通过（共用 32012，串行）。
- verify:styles：本机没有 `artifacts/baseline-c6`，改为在临时工作树按 bdef9d291 快照基线（32014）再比对。
  - `panel-world-entry`、`m-panel-image-scene` 两个状态在基线和本分支都点击超时，与本改动无关，所以 snap 步骤以 1 退出；比对单独执行。
  - 差异只在左栏：折叠的区不再带着内层 6px 底部留白（桌面 42→36px，手机 50→44px），以及新增的包装层。均为预期。
- 截图脚本（1366 / 1440 / 1920，240 层 + 40 条历史）：楼层区单独展开时阅读楼层可见；展开历史后楼层自动收起并带标记；点楼层标题后互换；收起楼层后历史恢复；滚到顶部渲染第 1 层；大纲（空）+ 楼层同时展开时都显示。
