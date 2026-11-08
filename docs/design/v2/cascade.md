# 级联方案验证（B1 spike）

日期：2026-10-11 · 环境：本机 1.19.0 visual 实例（32014），30 个截图状态

## 结论

D1 方案可行，并在原方案上做了两处修正。插件 UI 内的样式全部放进 `@layer`，再加一条不分层的隔离规则：

```css
:is(#wb-root, #wb-layout-root, .wb-ui, #wb-x#wb-x#wb-x#wb-x#wb-x):not(.wb-native-embedded, .wb-native-embedded *),
:is(#wb-root, #wb-layout-root, .wb-ui, #wb-x#wb-x#wb-x#wb-x#wb-x) *:not(.wb-native-embedded, .wb-native-embedded *) {
  all: revert-layer;
}
```

相对原方案的修正：

| 项目 | 原方案 | 实际 |
| --- | --- | --- |
| 豁免标记 | `.wb-native-slot` | `.wb-native-embedded`：`leaseNative` 和 `leaseConnection` 都会给租借节点加上这个类，覆盖面更准 |
| 选择器权重 | `(1,1,0)` | `(5,1,0)`：在 `:is()` 里放一个不会命中任何元素的 `#wb-x×5` 参数，把权重抬到能压过任何不分层的原生普通规则（比如 `#sheld button` 这类带 ID 的选择器） |
| 隔离范围 | 只作用于后代 | 后代和根节点本身都隔离 |

## 验证结果

1. **截图**：一次性 spike 脚本（`bdc5372` 中的 `scripts/visual/spike-layer.mjs`，结论落定后已删除）把构建产物改写成分层结构后，30 个状态与 `artifacts/baseline-0.4/screens` 逐像素一致，差异为 0 个像素。
1. **计算样式**：用 `scripts/visual/computed.mjs` 采集每个状态下所有已渲染元素及其 `::before` / `::after` 的全部计算属性和几何尺寸，逐项对比，30/30 无差异。这个工具比截图更严格，会作为 B 阶段的验收门槛。基线在 `artifacts/baseline-0.4/computed/`。
2. **注入恶意的原生全局规则**：插入 `button{letter-spacing:9px}` 和 `p{color:…}` 后，插件 UI 内都没有生效。
3. **租借的原生控件**：`#rm_api_block` 里的 `select` 仍然接收原生规则（注入的 5px 字间距生效了）。
4. **主题变量**：自定义属性不受 `all` 影响。改一个 `--wb-ink`，有 840 个元素随之变化。

## 级联审计（`scripts/visual/audit-cascade.mjs`）

审计方法：逐条检查插件的 1941 个选择器，看它们命中的元素在隔离范围内还是范围外。动态伪类和伪元素先剥掉再匹配，嵌套规则按父级展开。

| 分类 | 数量 | 去向 |
| --- | --- | --- |
| 只命中范围内 | 828 | 分层 |
| 只命中原生 DOM | 263 | `native-bridge.css`（不分层） |
| 两边都命中 | 62 | 主要是 `.wb-ui button/input/select` 这类通用控件规则，同时命中了租借控件。两边各放一份，B3 再把租借部分改写成明确的 bridge 规则 |
| 30 个状态里都没命中 | 788 | 按选择器文本分类（规则见 B3），并用已命中的那部分规则校验分类准确率 |

当前会作用到插件 UI 上的原生规则，全是元素级全局样式：`*`、`button`、`input`、`select`、`option`、`textarea`、checkbox、range、`small`、`p`、`h2`–`h4`、`br`、`kbd`。

B 阶段把这些规则原样复制到 `wb.legacy` 层的**最前面**，不单独放一个前置的 reset 层。原因是有些原生规则原本靠选择器权重赢过插件规则，例如 `input[type=checkbox]:disabled` 的灰色。只有放在同一层、并保持「原生在前」的顺序，权重竞争才和现在完全一样；放进前置层的话，计算样式比对会出现差异。D 阶段由 `base.css` 接管之后，这部分副本就删掉。

## 实施时必须处理的事项

- **焦点样式**：酒馆的 `dynamic-styles.js` 会把样式表里的 `:hover` 规则克隆成 `:focus-visible`，但不会进入 `@layer`。分层之后，插件需要自己写 `:focus-visible`。spike 用机械克隆证明了等价；B3 改成在源码里写 `:is(:hover, :focus-visible)`。
- **原生 `!important` 仍会穿透**：例如 `body.noShadows *`、`body.no-blur *`、`textarea::placeholder`。这是用户偏好，保留；需要时用分层内的 `!important` 覆盖。
- **内联 `style` 属性**不受隔离影响。
- **工具链只能基于源码文本**：CSSOM 重新序列化时，会把「含 `var()`、又被局部覆盖」的简写属性丢掉。例如 `border: 1px solid var(--x) !important; border-top: 0 !important` 序列化后变成一串空值。B3 的迁移工具因此只切分规则文本、不改写声明（一次性脚本，迁移完成后已删除）；现存的 `scripts/visual/prune.mjs` 也按同样方式只删选择器、不动声明。
- `World.tsx` 用了原生的 `green` / `blue` / `purple` 颜色类，隔离后改由插件自己定义（截图里看不出差别，因为插件已经覆盖了这几个类）。

## B 阶段结果（2026-10-11）

| 提交 | 内容 | 验证 |
| --- | --- | --- |
| `58d8efd` | 14 个旧文件拆成 `src/styles/legacy/*.css`（`@layer wb.legacy`）和 `native-bridge.css`（不分层，末尾是隔离规则）；附加插件样式同样分层 | 30/30 像素一致，计算样式一致 |
| `b120d53` | 删除 26 个无人使用的类的规则：58 个选择器、54 条规则。只删 `:is()` 中失效的参数，保留选择器权重 | 计算样式一致 |
| `16186e9` | `tokens.css`：颜色、字号、间距、圆角、控件高度、阴影、动效、层级、布局尺寸各成阶梯；先读 `--wb-theme-*`；预留暗色；旧变量名改为别名 | 计算样式一致；主题钩子和暗色变量实测生效 |

新增的验收命令是 `npm run verify:styles`：构建，采集 `scripts/visual/states.mjs` 里全部状态的计算样式，再与基线对比，有任何差异就失败。B 阶段时是 30 个状态、以 0.4 为基线；现在是 86 个状态（桌面 52、手机 34），默认基线是 `artifacts/baseline-c6/computed`（C7、C6 先后更换，见 [C 阶段记录](architecture.md)），可用 `WB_STYLE_BASELINE` 指定其他目录。

### 在新机器上建立基线

`artifacts/` 不进入 Git，新机器上没有基线目录，`verify:styles` 会在比对时报错。visual 实例（32014）只由本地运行时提供（compose 里没有）。先在要对照的提交上采一份基线：

```bash
npm run build                                 # 播种要挂载当前构建
node scripts/local-runtime.mjs reset-visual   # 重建并启动 visual 实例，缺上游或 .env 时先准备
npm run visual:seed                           # 写入确定性的合成数据
git switch --detach <基线提交>                 # 通常是改动前的提交；先提交或暂存改动
npm run build
node scripts/visual/computed.mjs snap artifacts/baseline-c6/computed
git switch -                                  # 回到当前提交
npm run verify:styles                         # 构建、采样到 artifacts/visual/check，再与基线比对
```

- snap 使用基线提交里的 `states.mjs`：基线有、当前没有的状态记为 MISS；当前新增的状态不参与比对。
- 快照放在别的目录时，用 `WB_STYLE_BASELINE=<目录> npm run verify:styles` 比对。
- 任一状态采样失败时 snap 以 1 退出，`verify:styles` 不会进入比对；需要时单独运行 `node scripts/visual/computed.mjs diff <基线目录> artifacts/visual/check`。
- 验证会话总是加载运行脚本那份检出的 `extension/`，所以也可以在临时 worktree 里构建并 snap，不切换当前检出；worktree 需要自己的 `.env` 和 `node_modules`。

### 对原定验收标准的调整

- **`!important` 总数**：从 675 降到 741。增加的部分来自分类不确定、两边各放一份的规则。原定「≤ 50 且只出现在 bridge」做不到零变化：实测把分层内的 230 处全部去掉后，30 个状态全都出现差异，说明它们在解决旧规则之间的冲突，要逐屏重写才能去掉。调整后的标准：
  - 新的 `wb.base`、`wb.components`、`wb.layouts`、`wb.modes` 层里禁止出现 `!important`，现存例外见下文「新层里保留的 `!important`」；
  - 不分层的只有原生桥接规则，共三处：`native-bridge.css`，以及 `components/message-actions.css`、`components/image-insertion.css` 中 `@layer` 块之外的 `#chat` 楼层规则（它们要和原生的不分层样式竞争，随功能留在各自文件里）；除 `legacy` 存量外，`!important` 只允许出现在这些不分层规则里；
  - `legacy` 和 `native-bridge.css` 冻结成存量，在 E 阶段逐屏迁移时清零或收缩；
  - 每次迁移都报告数量变化。
- **体积**：gzip 后 38.1 KB → 40.6 KB，主要来自 `native-defaults.css` 和两边各放一份的规则。旧样式会随 E 阶段的迁移整块删除，体积在那时下降。
- **CSS 按需加载（B4）**：推迟到 E 阶段（C5 时重新评估后决定）。RP、PWA 的样式目前都在 `wb.legacy` 层里，同层规则在权重相同时按出现顺序决胜；改成按需注入会改变它们和其余旧规则的先后，无法保证计算样式一致。这些旧样式在 E 阶段逐屏重写时整块替换，届时新样式按组件分文件，再按模式拆包，不再受顺序影响。

### 新层里保留的 `!important`

2026-11-06 清理了新层里的 13 处 `!important`（`components/md-editor.css` 8 处，`layouts/rp.css` 5 处），计算样式不变。数量：`md-editor.css` 8 → 4，`layouts/rp.css` 5 → 2，新层合计 13 → 6。

去掉的 7 处：它们的对手在同层或更低层，或者没有对手。

- `.wb-md[hidden]` 的 `display`：对手只有同层零权重的 `:where(.wb-md)`。
- `#send_textarea[data-wb-md]` 及其 `::placeholder` 的 `-webkit-text-fill-color`、`::selection` 的 `background`：没有其他规则设置这些属性。
- `#rightSendForm > .wb-rp-tools` 的 `min-width`：原生规则不设它。
- RP 桌面边缘箭头的 `color`，以及打开历史面板时角落按钮和边缘箭头的 `color`：这两条只在彼此之间竞争，其余对手在 `wb.legacy` 层，或者是已被隔离规则还原的不分层规则；历史面板那条权重更高，去掉 `!important` 后照样胜出。

保留的 6 处：对手都是不分层的样式，分层规则不加 `!important` 赢不了。

| 规则 | 属性 | 对手 | 去掉的办法 |
| --- | --- | --- | --- |
| `#send_textarea[data-wb-md]` | `caret-color` | `native-bridge.css` 给 RP 桌面输入框的强调色光标：`body.wb-rp:not(.wb-mobile) #send_textarea` | 把这条光标声明从 bridge 删掉，改写进 `layouts/rp.css`，选择器加上 `:not([data-wb-md])` |
| `.wb-composer-md .cm-placeholder`，以及手机、RP 各一条 | `color` | 编辑器运行时注入的不分层主题：`.ͼ1 .cm-placeholder`（基础主题）、`.ͼo .cm-placeholder`（`src/ui/md/editor.ts`） | 让编辑器主题从一个 CSS 变量取占位符颜色，由 `md-editor.css` 按模式设置这个变量；要改组件 |
| `#rightSendForm > .wb-rp-tools` | `width`、`height` | 酒馆 `style.css` 的 `#rightSendForm>div:not(.mes_stop)`，它把这一行的每个 `div` 都设成一个图标大小 | RP 工具栏挂进这一行时不用 `div` 作容器；要改组件，而且同一条里被原生规则压住的 `margin`、`opacity` 也会随之生效，外观会变，要先定设计 |

这几处都不挪进 `native-bridge.css`：bridge 已冻结，只能删规则、不能加规则；在各自文件里另开不分层的块，又会突破上文「不分层的只有三处」的约定。占位符那三条的对手是插件自己的编辑器，不是酒馆原生样式，本来也不属于 bridge。

### 留给 D/E 阶段

- CSS 按需加载（见上文 B4）。

- `--SmartTheme*` 目前仍在 `body.wb-active` 上全局改写，原生弹窗也会跟着变色。缩小作用范围会改变原生界面的外观，因此和暗色模式一起放到设计稿里定。
- `native-defaults.css` 在 `base.css` 接管后删除。
