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

1. **截图**：`scripts/visual/spike-layer.mjs` 把构建产物改写成分层结构后，30 个状态与 `artifacts/baseline-0.4/screens` 逐像素一致，差异为 0 个像素。
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
- **工具链只能基于源码文本**：CSSOM 重新序列化时，会把「含 `var()`、又被局部覆盖」的简写属性丢掉。例如 `border: 1px solid var(--x) !important; border-top: 0 !important` 序列化后变成一串空值。`scripts/visual/css-text.mjs` 只切分规则，不改写声明。
- `World.tsx` 用了原生的 `green` / `blue` / `purple` 颜色类，隔离后改由插件自己定义（截图里看不出差别，因为插件已经覆盖了这几个类）。

## B 阶段结果（2026-10-11）

| 提交 | 内容 | 验证 |
| --- | --- | --- |
| `58d8efd` | 14 个旧文件拆成 `src/styles/legacy/*.css`（`@layer wb.legacy`）和 `native-bridge.css`（不分层，末尾是隔离规则）；附加插件样式同样分层 | 30/30 像素一致，计算样式一致 |
| `b120d53` | 删除 26 个无人使用的类的规则：58 个选择器、54 条规则。只删 `:is()` 中失效的参数，保留选择器权重 | 计算样式一致 |
| `16186e9` | `tokens.css`：颜色、字号、间距、圆角、控件高度、阴影、动效、层级、布局尺寸各成阶梯；先读 `--wb-theme-*`；预留暗色；旧变量名改为别名 | 计算样式一致；主题钩子和暗色变量实测生效 |

新增的验收命令是 `npm run verify:styles`：构建、采集 30 个状态的计算样式，再与 0.4 基线对比，有任何差异就失败。

### 对原定验收标准的调整

- **`!important` 总数**：从 675 降到 741。增加的部分来自分类不确定、两边各放一份的规则。原定「≤ 50 且只出现在 bridge」做不到零变化：实测把分层内的 230 处全部去掉后，30 个状态全都出现差异，说明它们在解决旧规则之间的冲突，要逐屏重写才能去掉。调整后的标准：
  - 新的 `wb.base`、`wb.components`、`wb.layouts`、`wb.modes` 层里禁止出现 `!important`；
  - `legacy` 和 `bridge` 冻结成存量，在 E 阶段逐屏迁移时清零或收缩；
  - 每次迁移都报告数量变化。
- **体积**：gzip 后 38.1 KB → 40.6 KB，主要来自 `native-defaults.css` 和两边各放一份的规则。旧样式会随 E 阶段的迁移整块删除，体积在那时下降。
- **CSS 按需加载（B4）**：推迟到 E 阶段（C5 时重新评估后决定）。RP、PWA 的样式目前都在 `wb.legacy` 层里，同层规则在权重相同时按出现顺序决胜；改成按需注入会改变它们和其余旧规则的先后，无法保证计算样式一致。这些旧样式在 E 阶段逐屏重写时整块替换，届时新样式按组件分文件，再按模式拆包，不再受顺序影响。

### 留给 D/E 阶段

- CSS 按需加载（见上文 B4）。

- `--SmartTheme*` 目前仍在 `body.wb-active` 上全局改写，原生弹窗也会跟着变色。缩小作用范围会改变原生界面的外观，因此和暗色模式一起放到设计稿里定。
- `native-defaults.css` 在 `base.css` 接管后删除。
