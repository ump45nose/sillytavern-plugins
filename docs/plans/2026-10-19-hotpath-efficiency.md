# 高频与批量路径的低效写法（2026-10-19）

分支 `claude/exciting-shamir-bb7232`（基于 workbench a37f0ce）。改动横跨 host（HostCore、各 domain、adapter、addon 运行时）和 modules（World、Resources、Characters、Database、outline、Navigation），所以记录计划。

## 范围

1. **粗粒度刷新**：`refresh()` 让全部分片失效，包括要用正则遍历整个 `ctx().chat` 重建的聊天索引，还会唤醒所有订阅聊天的组件。逐个调用点核对实际改动了哪些分片，换成 `invalidate(...)`；SillyTavern 事件（adapter 事件表）一定会覆盖的就删掉手动刷新。`batchResource` 改为结束时失效一次。NativeSelect / HostControl 的 onChange 不再刷新。
2. **角色批量打标签**：每个角色只 POST 一次 merge-attributes，最后统一 `getCharacters()`，并发一次 `CHARACTER_EDITED`。`saveCharacter` 保存后不再重新读取角色。
3. **世界书编辑器按键开销**：只对被编辑的条目做写时复制；dirty 按引用比较，只在引用不同时才做深比较；草稿缓存存引用，不再克隆；保存后 dirty 变为 false 时不再读一次书。
4. **预设编辑器**：每次渲染只算一次 livePreset / presetData / presetChanges，结果复用。
5. **useDraft**：不在每次渲染时对 base/draft 做 JSON.stringify，也不在每次变更时克隆两份；rebase 和冲突语义不变。
6. **离开保护**：useDraft、World、Characters、Database、outline 各自写的「dirty → guards.add + beforeunload」合并成一个 `useLeaveGuard`；adapter 里检查同一份草稿缓存的 beforeunload 也并进来。各处现有的提示文案不变。
7. **Navigation** 不再在 `#chat` 上另建 subtree MutationObserver，改为订阅 `host.chatObserver`。
8. **AddonManager**：每个运行时的 `runtime.subscribe` 退订函数在 `reset()` 时执行，不再累积到 `cleanups`。

## 关键决定

- **SETTINGS_UPDATED 不再让聊天索引失效。** 酒馆每次保存设置（包括 debounce 的保存）都会发这个事件；设置不会改动 `ctx().chat`，聊天索引只包含名字、发送方、时间和预览。
- **只有在调用路径上确定会发出事件时才删掉手动刷新**，事件来源以 SillyTavern 1.19.0 源码为准，比如 `openCharacterChat` / `doNewChat` 一定发 `CHAT_CHANGED`，`persistSettings()` 成功就意味着已经收到 `SETTINGS_UPDATED`。其余调用点按实际改动的状态，失效对应的分片：
  - 角色列表 → `characters`（session 会随它失效）；
  - 资源列表 → `resources`；
  - 忙碌标志、当前选择、聊天列表版本 → `session`；
  - 只读宿主状态、不在任何分片里的（人设锁、世界书绑定、扩展状态、群组）→ 失效该界面所订阅的最小分片。工作台面板都订阅 `withoutChat`，所以失效哪一个非聊天分片都能让面板重新渲染，而且不会重建聊天索引。
- **`refresh()` 保留在 HostCore 里**，供 verify 脚本和 init 使用；产品代码不再调用。逐点结果：
  - 删除（事件或 `persistSettings` 已覆盖）：openChat、renameChat、newChat、deleteChat、selectCharacter、saveCharacter、savePersona、personaPreference、saveBook、createResource（世界书）、toggleCharacterBook、saveProfile、setGroupMedia、openGroup、扩展的启用/更新/安装（设置页自己会重读扩展列表）。
  - 删除（没有分片变化）：saveGroupOverrides（只改本聊天的 metadata，编辑器自己接收保存结果）、HostControl 与 NativeSelect 的 onChange（控件和设置页都会监听原生节点的 input/change 并自行重绘，数据变化由原生事件覆盖）。
  - `characters`：创建、导入、换头像、复制、删除角色（`getCharacters()` 不发事件）。
  - `session`：select / batchResource 开始（忙碌标志）、importChat（聊天列表版本）、saveGroup / deleteGroup（群组名在 session 里）、聊天级世界书绑定、setConnectionControl、插件保存 metadata。
  - `resources`：人设锁、人设或连接保存失败后的回滚、updatePreset / revertPreset / savePreset。
  - `resources` + `session`：toggleBook（原生 change 处理里的事件不被 await，调用方会立刻读取）、createPreset、deletePreset、batchResource 结束。
  - 插件把图片插入某层消息之后，改为 `updateMessage(id)`：只重建这一层的索引，并通知订阅聊天的组件。
- **batchResource 逐项不再失效**：删除预设改走不失效的 `removePreset`，整批结束时失效一次。复制世界书、复制/删除连接时，酒馆自己的 `WORLDINFO_UPDATED` / `CONNECTION_PROFILE_*` 事件仍会逐项触发，这些只让 resources 和 session 失效，不会重建聊天索引。
- **打标签以内存中的标签为准**：其他标签页在这期间改了同一个角色的标签，可能会被覆盖。这是按要求去掉逐个 GET 的代价；单个角色编辑器保存时仍然先读最新数据做三方合并。
- **世界书列表行改为 memo 组件**：写时复制以后，没改动的条目引用不变，侧栏列表和深度编辑表格只重新渲染被编辑的那一行。深度编辑的 token 计数只计算文本有变化的条目，不再每停顿一次就把整本书重新计一遍。
- **Navigation 的阅读层**：改为订阅 ChatObserver 的 `nodes` 变化（层的增删和重新编号），加上 RPStage 在当前行变化或舞台关闭时发出的 `rp-line` 总线事件。只有流式输出的正文变化不触发重读。
- **useDraft 的 `saved()` 仍然复制一份**：每次保存复制一次，宿主之后修改自己的对象时不会影响编辑器。每次按键不再复制。
- **saveCharacter 的返回值**：不再 GET，而是在内存中按服务器 `deepMerge` 的语义（普通对象递归合并，其他类型直接替换）把补丁合进保存前读到的最新数据。saveCharacter 本来就要先读最新数据来做三方合并，所以每次保存从 3 次 GET 减为 1 次。
- **打标签**：从内存中的角色列表读取现有标签（浅加载模式下也包含 `data.tags`），不再逐个 GET。服务器的批量模式会用同一个数组覆盖所有角色，没法按角色取并集，所以仍然每个角色发一次 POST。
- **世界书 dirty**：draft 只在编辑时换引用，所以 `base === draft` 就表示没有改动。引用不同时再做一次深比较（把改动又改回原样的情况）。深比较只在 draft 或 base 变化时做一次（useMemo），不在每次渲染时做。
- **草稿缓存存引用**：base/draft 在组件里从不就地修改（写时复制），所以缓存里可以直接存引用。`saveDrafts` 和 `batchResource` 读缓存时本来就会 clone。

## 验收标准

- `npm run check`、`npm test`、`npm run build` 通过。
- 修复前后各跑一次 `verify:workbench`、`verify:interactions`、`verify:compat`、`verify:rp`，全部通过。
- `scripts/benchmark-hotpaths.mjs` 计时对比，数据如下。

## 实测

环境：M1 Pro，本地 validation 实例（端口偏移 300），无头 Chromium。脚本：`npm run benchmark:hotpaths`（`scripts/benchmark-hotpaths.mjs`），结果写入 `artifacts/benchmark-hotpaths.json`。修复前跑了两次（结果一致，取第二次），修复后用最终提交的构建跑了一次。

| 项目 | 修复前 | 修复后 |
| --- | --- | --- |
| 世界书 600 条目，正文每次按键的同步更新耗时（60 次，中位数 / p95） | 39.3 ms / 42.6 ms | 3.8 ms / 5.6 ms |
| 世界书保存时请求 `/api/worldinfo/get` 的次数 | 2 | 1（只剩保存前读最新数据做合并的那一次） |
| 给 8 个角色打标签：请求数 / 耗时 | 40 次（24 get + 8 merge + 8 all）/ 1534 ms | 9 次（8 merge + 1 all）/ 868 ms |
| 9 次资源操作和设置保存（开关世界书 ×6、saveSettings ×3）引起的聊天索引失效，聊天 400 条消息 | 9 次，共 712 ms | 0 次，共 258 ms |
| 预设编辑器每次渲染调用 presetData / livePreset 的次数 | 6 / 3 | 1 / 0 |

- 重建一次聊天索引（400 条消息）约 0.85 ms，这项改动本身前后一样。省下来的主要是失效以后订阅聊天的组件（Reading、RPStage、Navigation）跟着重新渲染的开销。
- 预设编辑器每次渲染耗时约 9–10 ms，测量时每次渲染都要等一帧，所以这个数主要反映帧间隔，不是渲染本身的耗时；调用次数才是这项的证据。

## 验证

| 检查 | 修复前 | 修复后（最终提交） |
| --- | --- | --- |
| `npm run check` | 通过 | 通过 |
| `npm test` | 通过 | 通过（87 项，新增 sameData、deepMerge、guards.hold 测试） |
| `npm run build` | 通过 | 通过 |
| `verify:workbench` | 10 PASS | 10 PASS |
| `verify:interactions` | 15 PASS | 15 PASS |
| `verify:compat` | 10 PASS | 10 PASS |
| `verify:rp` | 36 PASS | 36 PASS |

未单独验证：离开保护的浏览器原生提示（beforeunload）没有自动化测试，这一项只有单元测试（listener 的注册和移除）和代码检查；HostControl / NativeSelect 去掉刷新后的表现，由 interactions 和 compat 中的设置页流程覆盖。

## 进度

- [x] 基线：check / test / build 和四个 verify 全部通过；计时基线已记录
- [x] 1 粗粒度刷新（3e536c4）
- [x] 2 角色批量操作（e03d0b0）
- [x] 3 世界书编辑器、4 预设编辑器、5 useDraft（db4aac9）
- [x] 6 useLeaveGuard（f6f6874）
- [x] 7 Navigation 观察器（784d4f5）
- [x] 8 AddonManager 退订（5e18330）
- [x] 修复后验证与计时

## 未纳入本次范围（发现的同类问题）

- 角色卡编辑器（Characters.tsx `CharacterEditor`）仍然在每次渲染时对 base/draft 做 JSON.stringify，并在每次变更时把两者克隆进 `host.drafts`；保存后 dirty 变为 false 时也会再读一次角色。单张卡的数据量小，不在高频大数据路径上，可以按世界书的做法再改。
- `favorite` 先 GET 一次角色，saveCharacter 内部又 GET 一次最新数据，共 2 次。
