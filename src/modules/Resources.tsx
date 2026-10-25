import { Select } from "../ui/Select";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  GripVertical,
  Copy,
  Download,
  Plus,
  Trash2,
  BookmarkPlus,
  X,
  RefreshCw,
  ChartNoAxesColumn,
  Upload,
  Lock,
  MessageSquare,
  Star,
  UserRound,
} from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import type { Resource, Data } from "../host/types";
import { clone, validatePreset } from "../host/model";
import { useTask, Notice, Empty, Field, IconButton, useHostSlices, withoutChat } from "../ui/common";
import { useTokenCounts } from "../ui/tokens";
import { Check, Fold, SaveBar, Switch, useDraft } from "../ui/ResourceControls";
import { actionLabels, resourceLabels } from "../host/labels";
import { ResourcePicker, type RailExtras } from "../ui/ResourcePicker";
import { ConnectionRuntime } from "./Connection";
import { bus, guards } from "../host/bus";
import { MdField } from "../ui/md/MdField";
const safeToLeave = () => guards.check();
export default function Resources({
  host,
  kind,
  initial,
  deep,
  onSelection,
  view,
}: {
  host: HostAdapter;
  kind: Exclude<Resource, "world">;
  initial?: string;
  deep?: boolean;
  onSelection?: (id: string) => void;
  view?: "prompts";
}) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask();
  const [id, setId] = useState(initial || snap.current[kind] || snap.resources[kind][0]?.id || "");
  const pendingCreation = useRef<Set<string> | null>(null);
  useEffect(() => {
    onSelection?.(id);
  }, [id]);
  useEffect(() => {
    // Native create/delete actions can change the collection while this editor is open.
    const created =
      pendingCreation.current && snap.resources[kind].find((x) => !pendingCreation.current!.has(x.id));
    if (created) {
      pendingCreation.current = null;
      setId(created.id);
      return;
    }
    if (id && !snap.resources[kind].some((x) => x.id === id))
      setId(snap.current[kind] || snap.resources[kind][0]?.id || "");
  }, [snap.resources[kind], id, kind]);
  const current = snap.resources[kind].find((x) => x.id === id);
  const choose = (next: string) => {
    if (deep ? guards.check({ preserveDrafts: true }) : safeToLeave()) {
      pendingCreation.current = null;
      setId(next);
    }
  };
  const apply = (next: string) => {
    if (safeToLeave())
      task.run(async () => {
        pendingCreation.current = null;
        await host.select(kind, next);
        setId(next);
      });
  };
  const nativeAction = (selector: string) => {
    if (safeToLeave())
      task.run(async () => {
        pendingCreation.current = /create_|duplicate/.test(selector)
          ? new Set(snap.resources[kind].map((x) => x.id))
          : null;
        if (kind === "persona" && !/create_/.test(selector) && current && snap.current.persona !== id)
          await host.select("persona", id);
        host.click(selector);
      });
  };
  const rail: Record<typeof kind, RailExtras> = {
    preset: {
      plain: true,
      create: {
        label: "新建预设",
        run: () => {
          const name = prompt("新预设名称");
          if (name) task.run(async () => setId(await host.createPreset(name)));
        },
      },
    },
    connection: {
      grouped: true,
      create: { label: "新建连接配置", run: () => nativeAction("#create_connection_profile") },
    },
    persona: {
      avatars: true,
      create: { label: "新建用户设定", run: () => nativeAction("#create_dummy_persona") },
    },
  };
  return (
    <div className={`wb-resources wb-resource-v3 kind-${kind} ${deep ? "is-deep" : ""}`}>
      <header className="wb-panel-heading">
        {kind === "persona" && current && !deep && (
          <button
            className="wb-panel-avatar"
            aria-label="更换头像"
            title="更换头像"
            disabled={snap.busy || task.busy}
            onClick={() => nativeAction("#persona_set_image_button")}
          >
            {current.image ? <img src={current.image} alt="" /> : current.name.slice(0, 1)}
          </button>
        )}
        <div className="wb-panel-heading-copy">
          <div className="wb-panel-heading-line">
            <ResourcePicker
              label={resourceLabels[kind]}
              items={snap.resources[kind]}
              id={id}
              active={snap.current[kind]}
              choose={choose}
              use={apply}
              sortable={kind === "persona"}
              disabled={snap.busy || task.busy}
              extras={rail[kind]}
            />
            {current && snap.current[kind] === id && (
              <span className={`wb-status-chip ${kind === "connection" && !snap.online ? "is-off" : ""}`}>
                {kind === "connection"
                  ? snap.online
                    ? "已连接"
                    : "未连接"
                  : kind === "preset"
                    ? "运行中"
                    : "使用中"}
              </span>
            )}
          </div>
          {current?.detail && kind !== "preset" && <p className="wb-panel-sub">{current.detail}</p>}
        </div>
        <div className="wb-panel-heading-actions">
          {current && snap.current[kind] !== id && (
            <button
              className="wb-panel-action"
              aria-label={`使用此${resourceLabels[kind]}`}
              title={`使用此${resourceLabels[kind]}`}
              disabled={snap.busy || task.busy}
              onClick={() => apply(id)}
            >
              使用
            </button>
          )}
          {kind === "connection" &&
            (
              [
                ["update_connection_profile", "记录", "把当前连接设置记录到此配置", BookmarkPlus],
                ["delete_connection_profile", "删除", "删除此连接配置", Trash2],
              ] as const
            ).map(([selector, text, title, Icon]) => (
              <button
                key={selector}
                className="wb-panel-icon"
                aria-label={text}
                title={snap.current.connection !== id ? "使用此连接后可操作" : title}
                disabled={snap.busy || task.busy || !current || snap.current.connection !== id}
                onClick={() => nativeAction(`#${selector}`)}
              >
                <Icon size={15} />
              </button>
            ))}
          {kind === "persona" && current && (
            <button
              className="wb-panel-icon"
              aria-label="复制"
              title="复制此用户设定"
              disabled={snap.busy || task.busy}
              onClick={() => nativeAction("#persona_duplicate_button")}
            >
              <Copy size={15} />
            </button>
          )}
        </div>
      </header>
      <Notice error={task.error} />
      {kind === "preset" ? (
        current ? (
          <PresetEditor key={id} host={host} id={id} deep={deep} view={view} onSelect={setId} />
        ) : (
          <>
            <Empty>暂无预设</Empty>
            <button
              onClick={() => {
                const name = prompt("新预设名称");
                if (name) task.run(async () => setId(await host.createPreset(name)));
              }}
            >
              创建预设
            </button>
          </>
        )
      ) : kind === "connection" ? (
        <div className="wb-resource-detail wb-connection-detail">
          <ConnectionRuntime host={host} />
          {current && <ProfileEditor key={id} host={host} id={id} />}
        </div>
      ) : current ? (
        <PersonaEditor key={id} host={host} id={id} deep={deep} />
      ) : (
        <div className="wb-fields">
          <Empty>选择用户身份，或创建一个新身份</Empty>
          <button onClick={() => host.click("#create_dummy_persona")}>创建用户设定</button>
        </div>
      )}
    </div>
  );
}
function ProfileEditor({ host, id }: { host: HostAdapter; id: string }) {
  const task = useTask(),
    edit = useDraft(
      () => clone(host.snapshot().resources.connection.find((x) => x.id === id)?.data || {}),
      host.resourceVersions.connection,
      { host, key: "connection:" + id },
    );
  const { draft, change } = edit;
  return (
    <fieldset disabled={task.busy} className="wb-profile-editor">
      <Notice error={task.error} />
      <Fold title={`${actionLabels.connectionProfile}与绑定`} hint={draft.preset || "未绑定预设"}>
        <div className="wb-form-pair">
          <Field label="连接名称">
            <input value={draft.name || ""} onChange={(e) => change("name", e.target.value)} />
          </Field>
          <Field label="记录模型">
            <input value={draft.model || ""} onChange={(e) => change("model", e.target.value)} />
          </Field>
        </div>
        <button disabled={edit.dirty} onClick={() => task.run(() => host.select("connection", id))}>
          应用此{actionLabels.connectionProfile}
        </button>
        <Field label="模型分组">
          <input
            value={host.prefs().groups[id] || ""}
            placeholder="按模型自动分组"
            onChange={(e) => host.preference({ groups: { ...host.prefs().groups, [id]: e.target.value } })}
          />
        </Field>
        <Field label="绑定预设">
          <Select value={draft.preset || ""} onChange={(e) => change("preset", e.target.value)}>
            <option value="">不绑定</option>
            {host.snapshot().resources.preset.map((p) => (
              <option key={p.id}>{p.name}</option>
            ))}
          </Select>
        </Field>
        <Fold title="连接配置记录">
          <Field label="记录接口类型">
            <Select value={draft.mode || "cc"} onChange={(e) => change("mode", e.target.value)}>
              <option value="cc">Chat Completion</option>
              <option value="tc">Text Completion</option>
            </Select>
          </Field>
          {[
            ["api", "服务类型"],
            ["api-url", "服务地址"],
            ["proxy", "代理配置"],
            ["secret-id", "凭据引用"],
            ["reasoning-template", "思考模板"],
            ["prompt-post-processing", "提示词后处理"],
            ["regex-preset", "正则预设"],
            ["stop-strings", "停止字符串"],
            ["start-reply-with", "回复前缀"],
            ...(draft.mode === "tc"
              ? [
                  ["sysprompt", "系统提示词"],
                  ["context", "上下文模板"],
                  ["instruct", "指令模板"],
                  ["tokenizer", "分词器"],
                ]
              : []),
          ].map(([key, label]) => (
            <Field key={key} label={label}>
              <input value={draft[key] ?? ""} onChange={(e) => change(key, e.target.value)} />
            </Field>
          ))}
          <Field label="应用时跳过的字段（每行一个）">
            <textarea
              value={(draft.exclude || []).join("\n")}
              onChange={(e) => change("exclude", e.target.value.split("\n").filter(Boolean))}
            />
          </Field>
        </Fold>
      </Fold>
      <SaveBar
        {...edit}
        busy={task.busy}
        label={actionLabels.updateConnectionProfile}
        title={`${actionLabels.connectionProfile}有未写入的修改`}
        detail={profileChanges(edit.base, draft)}
        pending
        save={() =>
          task.run(async () => {
            await host.saveProfile(id, edit.base, draft);
            edit.saved(clone(host.snapshot().resources.connection.find((x) => x.id === id)!.data!));
          })
        }
      />
    </fieldset>
  );
}
/** "模型 a → b", or a count when several recorded fields changed. */
function profileChanges(base: Record<string, any>, draft: Record<string, any>) {
  const keys = [...new Set([...Object.keys(base), ...Object.keys(draft)])].filter(
    (k) => JSON.stringify(base[k] ?? "") !== JSON.stringify(draft[k] ?? ""),
  );
  if (!keys.length) return undefined;
  const names: Record<string, string> = { name: "名称", model: "模型", preset: "绑定预设", api: "服务类型" };
  const first = keys.find((k) => names[k]);
  if (!first) return `${keys.length} 项记录字段`;
  const head = `${names[first]} ${base[first] || "空"} → ${draft[first] || "空"}`;
  return keys.length > 1 ? `${head} 等 ${keys.length} 项` : head;
}
function PersonaEditor({ host, id, deep }: { host: HostAdapter; id: string; deep?: boolean }) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    edit = useDraft(() => host.personaData(id), host.resourceVersions.persona, {
      host,
      key: "persona:" + id,
    });
  const { draft, change } = edit,
    options = host.personaOptions(id),
    tokens = useTokenCounts(host, deep ? [["description", draft.description ?? ""]] : []);
  const action = (selector: string) =>
    task.run(async () => {
      if (id !== snap.current.persona) await host.select("persona", id);
      host.click(selector);
    });
  const exportPersona = () =>
    host.download(
      new Blob(
        [
          JSON.stringify(
            {
              name: draft.name,
              description: draft.description,
              position: draft.position,
              depth: draft.depth,
              role: draft.role,
              lorebook: draft.lorebook,
              title: draft.title,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
      `${draft.name || "persona"}.json`,
    );
  const roleSelect = (
    <Select
      aria-label="注入角色"
      value={draft.role ?? 0}
      onChange={(e) => change("role", Number(e.target.value))}
    >
      <option value={0}>System</option>
      <option value={1}>User</option>
      <option value={2}>Assistant</option>
    </Select>
  );
  const save = (
    <SaveBar
      {...edit}
      busy={task.busy}
      save={() => task.run(async () => edit.saved(await host.savePersona(id, edit.base, draft)))}
    />
  );
  const positionSelect = (
    <Select value={draft.position ?? 0} onChange={(e) => change("position", Number(e.target.value))}>
      {[
        [0, "提示词 / 故事模板"],
        [2, "作者注释之前"],
        [3, "作者注释之后"],
        [4, "指定深度"],
        [9, "停用"],
      ].map(([v, n]) => (
        <option key={v} value={v}>
          {n}
        </option>
      ))}
    </Select>
  );
  // The panel's fold and the settings page's side column offer the same persona actions.
  const manage = (
    <>
      <button disabled={edit.dirty} onClick={exportPersona}>
        <Download size={14} />
        导出
      </button>
      <button disabled={edit.dirty} onClick={() => action("#sync_name_button")}>
        <RefreshCw size={14} />
        同步名称
      </button>
      <button disabled={edit.dirty} onClick={() => action("#PersonaManagement .user_stats_button")}>
        <ChartNoAxesColumn size={14} />
        统计
      </button>
      <button onClick={() => action("#personas_backup")}>
        <Download size={14} />
        备份全部身份
      </button>
      <button onClick={() => action("#personas_restore")}>
        <Upload size={14} />
        恢复备份
      </button>
      <button className="is-danger" disabled={edit.dirty} onClick={() => action("#persona_delete_button")}>
        <Trash2 size={14} />
        删除
      </button>
    </>
  );
  if (!deep) {
    // Board "PanelPersona": who uses this persona first (applies at once), then what it says, then the rest.
    const locks = [
      ["chat", "锁定当前对话", "此对话始终使用这个身份", MessageSquare],
      ["character", "锁定当前角色", "与当前角色的所有对话", UserRound],
      ["default", "默认身份", "新对话未锁定时使用", Star],
    ] as const;
    const scopeRow = (
      key: string,
      label: string,
      hint: string,
      Icon: typeof Star,
      checked: boolean,
      onChange: (v: boolean) => void,
      disabled = false,
    ) => (
      <div key={key} className={`wb-card-row wb-scope-row ${checked ? "is-on" : ""}`}>
        <Icon size={16} aria-hidden="true" />
        <span className="wb-scope-copy">
          <span>{label}</span>
          <small>{hint}</small>
        </span>
        <Switch label={label} checked={checked} disabled={disabled} onChange={onChange} />
      </div>
    );
    return (
      <fieldset className="wb-persona-editor wb-persona-panel" disabled={task.busy}>
        <Notice error={task.error} />
        <div className="wb-resource-detail wb-persona-body">
          <section className="wb-card wb-persona-scope" aria-label="使用范围">
            <p className="wb-card-caption">
              {options.current ? "使用范围 · 立即生效" : "使用范围 · 切换到此身份后可调整"}
            </p>
            {locks.map(([key, label, hint, Icon]) =>
              scopeRow(
                key,
                label,
                hint,
                Icon,
                !!options.locks[key],
                (v) => task.run(() => host.personaLock(key, v)),
                !options.current || edit.dirty,
              ),
            )}
            {scopeRow(
              "auto",
              "自动锁定到当前对话",
              "发送消息时把正在用的身份锁到对话",
              Lock,
              !!options.preferences.persona_auto_lock,
              (v) => task.run(() => host.personaPreference("persona_auto_lock", v)),
            )}
          </section>
          <section className="wb-persona-content" aria-label="设定内容">
            <div className="wb-persona-content-head">
              <span>用户描述</span>
              <small>{(draft.description ?? "").length} 字</small>
            </div>
            <MdField
              className="wb-persona-text"
              label="用户描述"
              rows={6}
              value={draft.description ?? ""}
              onChange={(value) => change("description", value)}
            />
          </section>
          <section className="wb-card wb-persona-fields-card" aria-label="名称与注入">
            <div className="wb-card-row">
              <span className="wb-card-label">用户名称</span>
              <input
                aria-label="用户名称"
                value={draft.name ?? ""}
                onChange={(e) => change("name", e.target.value)}
              />
            </div>
            <div className="wb-card-row">
              <span className="wb-card-label">说明标题</span>
              <input
                aria-label="说明标题"
                placeholder="列表中名称下方的一行"
                value={draft.title ?? ""}
                onChange={(e) => change("title", e.target.value)}
              />
            </div>
            <div className="wb-card-row">
              <span className="wb-card-label">注入位置</span>
              {React.cloneElement(positionSelect, { "aria-label": "注入位置" })}
            </div>
            {draft.position === 4 && (
              <div className="wb-card-row wb-card-pair">
                <span className="wb-card-label">深度</span>
                <input
                  aria-label="深度"
                  type="number"
                  min={0}
                  max={9999}
                  value={draft.depth ?? 2}
                  onChange={(e) => change("depth", Number(e.target.value))}
                />
                <span className="wb-card-label is-inline">角色</span>
                {roleSelect}
              </div>
            )}
            <div className="wb-card-row">
              <span className="wb-card-label">绑定世界书</span>
              <Select
                aria-label="绑定世界书"
                value={draft.lorebook || ""}
                onChange={(e) => change("lorebook", e.target.value)}
              >
                <option value="">不绑定</option>
                {snap.resources.world.map((w) => (
                  <option key={w.id}>{w.name}</option>
                ))}
              </Select>
            </div>
          </section>
          <Fold title="管理与偏好" hint="导出 · 统计 · 删除">
            <div className="wb-persona-manage">{manage}</div>
            {[
              ["persona_show_notifications", "切换身份时显示通知"],
              ["persona_allow_multi_connections", "允许角色关联多个身份"],
            ].map(([key, label]) => (
              <div key={key} className="wb-card-row wb-fold-switch">
                <span>{label}</span>
                <Switch
                  label={label}
                  checked={!!options.preferences[key]}
                  onChange={(v) => task.run(() => host.personaPreference(key, v))}
                />
              </div>
            ))}
          </Fold>
        </div>
        {save}
      </fieldset>
    );
  }
  // Board "WsPersona": the face and who uses it on the left, what it says on the right.
  const image = snap.resources.persona.find((x) => x.id === id)?.image;
  const locks = [
    ["chat", "锁定当前对话"],
    ["character", "锁定当前角色"],
    ["default", "默认身份"],
  ] as const;
  return (
    <fieldset className="wb-persona-editor wb-persona-desk" disabled={task.busy}>
      <Notice error={task.error} />
      <div className="wb-persona-desk-grid">
        <div className="wb-persona-side">
          <section className="wb-persona-portrait" aria-label="头像">
            <span className="wb-persona-face">
              {image ? <img src={image} alt="" /> : (draft.name || "?").slice(0, 1)}
            </span>
            <button onClick={() => action("#persona_set_image_button")}>更换头像</button>
          </section>
          <section className="wb-persona-card" aria-label="使用范围">
            <p className="wb-persona-card-title">
              {options.current ? "使用范围 · 立即生效" : "使用范围 · 切换到此身份后可调整"}
            </p>
            {locks.map(([key, label]) => (
              <div key={key} className="wb-persona-card-row">
                <span>{label}</span>
                <Switch
                  label={label}
                  checked={!!options.locks[key]}
                  disabled={!options.current || edit.dirty}
                  onChange={(v) => task.run(() => host.personaLock(key, v))}
                />
              </div>
            ))}
          </section>
          <section className="wb-persona-card" aria-label="注入与绑定">
            <p className="wb-persona-card-title">注入与绑定</p>
            <label className="wb-persona-card-row">
              <span>注入位置</span>
              {React.cloneElement(positionSelect, { "aria-label": "注入位置" })}
            </label>
            {draft.position === 4 && (
              <>
                <label className="wb-persona-card-row">
                  <span>深度</span>
                  <input
                    aria-label="深度"
                    type="number"
                    min={0}
                    max={9999}
                    value={draft.depth ?? 2}
                    onChange={(e) => change("depth", Number(e.target.value))}
                  />
                </label>
                <label className="wb-persona-card-row">
                  <span>注入角色</span>
                  {roleSelect}
                </label>
              </>
            )}
            <label className="wb-persona-card-row">
              <span>绑定世界书</span>
              <Select
                aria-label="绑定世界书"
                value={draft.lorebook || ""}
                onChange={(e) => change("lorebook", e.target.value)}
              >
                <option value="">不绑定</option>
                {snap.resources.world.map((w) => (
                  <option key={w.id}>{w.name}</option>
                ))}
              </Select>
            </label>
          </section>
          <div className="wb-persona-tools">{manage}</div>
        </div>
        <div className="wb-persona-main">
          <label className="wb-persona-line">
            <span>用户名称</span>
            <input value={draft.name ?? ""} onChange={(e) => change("name", e.target.value)} />
          </label>
          <label className="wb-persona-line">
            <span>说明标题</span>
            <input
              placeholder="列表中名称下方的一行"
              value={draft.title ?? ""}
              onChange={(e) => change("title", e.target.value)}
            />
          </label>
          <MdField
            className="wb-persona-desc"
            label="用户描述"
            placeholder="写下你在故事里是谁：身份、性格、说话方式……"
            value={draft.description ?? ""}
            onChange={(value) => change("description", value)}
          />
          <small className="wb-persona-count">
            {(draft.description ?? "").length} 字
            {tokens.description !== undefined && ` · ${tokens.description} tokens`}
          </small>
        </div>
      </div>
      {save}
    </fieldset>
  );
}
const parameterNames: Record<string, string> = {
  temperature: "温度",
  top_p: "Top P",
  top_k: "Top K",
  top_a: "Top A",
  min_p: "Min P",
  frequency_penalty: "频率惩罚",
  presence_penalty: "存在惩罚",
  repetition_penalty: "重复惩罚",
  openai_max_tokens: "最大回复 Token",
  openai_max_context: "上下文 Token 上限",
  stream_openai: "流式传输",
  show_thoughts: "请求思维链",
  reasoning_effort: "思考强度",
  seed: "随机种子",
  n: "回复数量",
};
/** Parameters that read best as a slider beside their number: [min, max, step]. */
const sliders: Record<string, [number, number, number]> = {
  temperature: [0, 2, 0.01],
  top_p: [0, 1, 0.01],
  frequency_penalty: [-2, 2, 0.01],
  presence_penalty: [-2, 2, 0.01],
  repetition_penalty: [1, 2, 0.01],
  top_k: [0, 200, 1],
  top_a: [0, 1, 0.01],
  min_p: [0, 1, 0.01],
  openai_max_tokens: [16, 8192, 16],
  openai_max_context: [1024, 131072, 1024],
};
/** The deep page's sampling card, in reading order; everything else waits in a fold. */
const sampling = [
  "temperature",
  "top_p",
  "top_k",
  "top_a",
  "min_p",
  "frequency_penalty",
  "presence_penalty",
  "repetition_penalty",
  "openai_max_tokens",
  "openai_max_context",
  "seed",
  "n",
  "reasoning_effort",
];
const roleNames: Record<string, string> = { system: "系统", user: "用户", assistant: "助手" };
const triggerNames = [
  ["normal", "普通"],
  ["continue", "继续"],
  ["impersonate", "AI 帮答"],
  ["swipe", "滑动"],
  ["regenerate", "重新生成"],
  ["quiet", "静默"],
] as const;
/** The prompt a click on the parameters page asks the prompts tab to open. */
let studioFocus = "";
const shown = (value: unknown) =>
  typeof value === "number" ? String(value) : typeof value === "boolean" ? (value ? "开" : "关") : "已改";
function PresetEditor({
  host,
  id,
  deep,
  onSelect,
  view,
}: {
  host: HostAdapter;
  id: string;
  deep?: boolean;
  onSelect: (id: string) => void;
  view?: "prompts";
}) {
  const task = useTask(),
    edit = useDraft(
      () => host.livePreset(id) ?? host.presetData(id),
      host.resourceVersions.preset,
      { host, key: "preset:" + id },
      true,
    );
  // The running preset follows SillyTavern: parameters, toggles and order apply at once; prompt
  // text stays a draft until saved. "更新预设" then writes the running state into the file.
  // One read of the preset per render: the running settings, the file and where they differ.
  const live = host.runningPreset(id),
    running = !!live,
    changed = live ? host.presetChanges(id, live) : [],
    pending = changed.length > 0;
  const { draft, change } = edit,
    [entry, setEntry] = useState(() => {
      const focus = studioFocus;
      studioFocus = "";
      return focus;
    }),
    [editorOpen, setEditorOpen] = useState(false),
    [scope, setScope] = useState(0),
    [pinsOpen, setPinsOpen] = useState(false),
    [dragging, setDragging] = useState<number | null>(null),
    [advanced, setAdvanced] = useState(host.drafts.get("preset:" + id)?.extra?.advanced ?? "");
  useLayoutEffect(() => {
    const cached = host.drafts.get("preset:" + id);
    if (cached) cached.extra = { ...cached.extra, advanced };
  }, [advanced, edit.base, draft]);
  const prompts: Data[] = draft.prompts || [],
    scopes: Data[] = draft.prompt_order || [],
    order: Data[] = scopes[scope]?.order || [];
  const rows: Data[] = order.length
    ? order
    : prompts.map((p) => ({ identifier: p.identifier, enabled: true }));
  const selected =
    prompts.find((p) => p.identifier === entry) ||
    prompts.find((p) => p.identifier === order[0]?.identifier) ||
    prompts[0];
  /** Applies a field to the running preset, or to the draft when editing a preset file. */
  const apply = (key: string, base: any, value = base) => {
    if (!running) return change(key, value);
    host.applyPreset({ [key]: base });
    edit.patch(key, base, value);
  };
  const setOrder = (value: Data[]) => {
    const next = clone(scopes);
    if (!next[scope]) next[scope] = { character_id: 100000, order: [] };
    next[scope].order = value;
    apply("prompt_order", next);
  };
  const updatePrompt = (patch: Data) =>
    change(
      "prompts",
      prompts.map((p) => (p.identifier === selected.identifier ? { ...p, ...patch } : p)),
    );
  const pins = host.prefs().presetPins ?? ["temperature", "openai_max_tokens"];
  const always = ["stream_openai", "show_thoughts"];
  const fileData = changed.length ? live!.file : null;
  const pendingDetail = fileData
    ? `${parameterNames[changed[0]] || changed[0]} ${shown(fileData[changed[0]])} → ${shown(draft[changed[0]])}` +
      (changed.length > 1 ? ` 等 ${changed.length} 项` : "")
    : "";
  /** One row of the common-parameter card: a switch, or a number with a slider where it helps. */
  const field = (key: string) => {
    const label = parameterNames[key] || key,
      differs = changed.includes(key) && <span className="wb-diff-dot" title="与预设文件不同" />;
    if (typeof draft[key] === "boolean" || always.includes(key))
      return (
        <div className="wb-preset-row" key={key}>
          <span className="wb-preset-label">
            {label}
            {differs}
          </span>
          <Switch label={label} checked={!!draft[key]} onChange={(v) => apply(key, v)} />
        </div>
      );
    const numeric = typeof draft[key] === "number",
      range = numeric ? sliders[key] : undefined,
      value = (v: string) => apply(key, numeric ? Number(v) : v);
    return (
      <div className={`wb-preset-row ${range ? "has-slider" : ""}`} key={key}>
        <span className="wb-preset-label">
          {label}
          {differs}
        </span>
        {range && (
          <input
            type="range"
            className="wb-slider"
            aria-label={`${label}滑块`}
            tabIndex={-1}
            min={range[0]}
            max={range[1]}
            step={range[2]}
            value={draft[key]}
            style={
              {
                "--wb-fill": `${((draft[key] - range[0]) / (range[1] - range[0])) * 100}%`,
              } as React.CSSProperties
            }
            onChange={(e) => value(e.target.value)}
          />
        )}
        <input
          className="wb-preset-value"
          aria-label={label}
          type={numeric ? "number" : "text"}
          step="any"
          value={draft[key] ?? ""}
          onChange={(e) => value(e.target.value)}
        />
      </div>
    );
  };
  const parameters = Object.keys(draft).filter(
    (k) => ["number", "boolean"].includes(typeof draft[k]) || k === "reasoning_effort",
  );
  // The settings page lays parameters and prompt order side by side (board WsPreset); the
  // prompts tab is the list beside one open prompt.
  const desk = !!deep && view !== "prompts",
    studio = !!deep && view === "prompts";
  const promptTokens = useTokenCounts(
    host,
    deep
      ? prompts
          .filter((p) => !p.marker)
          .map((p) => [p.identifier, String(p.content ?? "")] as [string, string])
      : [],
  );
  const promptHead = (
    <div className="wb-prompts-head">
      <span>
        提示词
        <small>
          {rows.filter((r) => r.enabled !== false).length} / {rows.length} 启用
        </small>
      </span>
      {scopes.length > 1 && (
        <Select aria-label="提示词作用范围" value={scope} onChange={(e) => setScope(Number(e.target.value))}>
          {scopes.map((s, i) => (
            <option key={i} value={i}>
              {s.character_id === 100000 ? "全局" : `角色 ${s.character_id}`}
            </option>
          ))}
        </Select>
      )}
      <button
        className="wb-panel-icon"
        aria-label="新增提示词"
        title="新增提示词"
        onClick={() => {
          const identifier = crypto.randomUUID?.() || `wb-${Date.now()}`,
            prompt = { identifier, name: "新提示词", role: "system", content: "" };
          apply("prompts", [...(edit.base.prompts || []), prompt], [...prompts, prompt]);
          setOrder([...order, { identifier, enabled: true }]);
          setEntry(identifier);
          setEditorOpen(true);
        }}
      >
        <Plus size={16} />
      </button>
    </div>
  );
  const promptList = (
    <ul className="wb-prompts" aria-label="提示词顺序">
      {rows.map((item, i) => {
        const p = prompts.find((p) => p.identifier === item.identifier),
          name = p?.name || item.identifier,
          active = (studio || editorOpen) && selected?.identifier === item.identifier;
        return (
          <li
            className={`wb-prompt ${active ? "is-active" : ""} ${item.enabled === false ? "is-off" : ""} ${p?.marker ? "is-marker" : ""} ${dragging === i ? "is-dragging" : ""}`}
            key={`${item.identifier}-${i}`}
            draggable={!!order.length}
            onDragStart={(e) => {
              setDragging(i);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => {
              if (dragging === null || dragging === i) return;
              e.preventDefault();
              const next = [...rows];
              next.splice(i, 0, next.splice(dragging, 1)[0]);
              setDragging(i);
              setOrder(next);
            }}
            onDragEnd={() => setDragging(null)}
          >
            <GripVertical className="wb-prompt-grip" size={14} aria-hidden="true" />
            <input
              type="checkbox"
              aria-label={`启用提示词 ${name}`}
              checked={item.enabled !== false}
              onChange={(e) =>
                setOrder(rows.map((v, j) => (j === i ? { ...v, enabled: e.target.checked } : v)))
              }
            />
            <button
              className="wb-prompt-open"
              aria-label={`编辑提示词 ${name}`}
              aria-expanded={active}
              onClick={() => {
                if (desk) {
                  studioFocus = item.identifier;
                  bus.emit("settings-group", { group: "提示词" });
                } else if (studio) setEntry(item.identifier);
                else if (active) setEditorOpen(false);
                else {
                  setEntry(item.identifier);
                  setEditorOpen(true);
                }
              }}
            >
              <span>{name}</span>
            </button>
            <span className="wb-prompt-role">
              {p?.marker ? "标记" : roleNames[p?.role || "system"] || p?.role}
            </span>
            {deep && (
              <span className="wb-prompt-tokens">
                {p?.marker ? "—" : (promptTokens[item.identifier] ?? "")}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
  const remove = () => {
    if (confirm("删除这个提示词？")) {
      const keep = (p: Data) => p.identifier !== selected.identifier;
      apply("prompts", (edit.base.prompts || []).filter(keep), prompts.filter(keep));
      setOrder(order.filter((p) => p.identifier !== selected.identifier));
      setEntry("");
    }
  };
  const heading = selected && (
    <div className="wb-editor-heading">
      <input
        aria-label="提示词名称"
        value={selected.name || ""}
        onChange={(e) => updatePrompt({ name: e.target.value })}
      />
      <Select
        aria-label="提示词角色"
        value={selected.role || "system"}
        onChange={(e) => updatePrompt({ role: e.target.value })}
      >
        <option>system</option>
        <option>user</option>
        <option>assistant</option>
      </Select>
      {[-1, 1].map((dir) => (
        <IconButton
          key={dir}
          title={dir < 0 ? "上移提示词" : "下移提示词"}
          disabled={
            !order.length ||
            order.findIndex((p) => p.identifier === selected.identifier) + dir < 0 ||
            order.findIndex((p) => p.identifier === selected.identifier) + dir >= order.length
          }
          onClick={() => {
            const next = clone(order),
              i = next.findIndex((p) => p.identifier === selected.identifier);
            [next[i], next[i + dir]] = [next[i + dir], next[i]];
            setOrder(next);
          }}
        >
          {dir < 0 ? <ArrowUp size={15} /> : <ArrowDown size={15} />}
        </IconButton>
      ))}
    </div>
  );
  const body = (
    <textarea
      aria-label="提示词正文"
      className="wb-prompt-body"
      value={selected?.content || ""}
      onChange={(e) => updatePrompt({ content: e.target.value })}
    />
  );
  const triggers: string[] = selected?.injection_trigger || [];
  /** Where and when a prompt goes: list order or a chat depth, and the generation types it joins. */
  const injection = selected && !selected.marker && (
    <div className="wb-prompt-inject">
      <div className="wb-prompt-inject-row">
        <Field label="提示词注入位置">
          <Select
            value={selected.injection_position ?? 0}
            onChange={(e) => updatePrompt({ injection_position: Number(e.target.value) })}
          >
            <option value={0}>按列表顺序</option>
            <option value={1}>指定聊天深度</option>
          </Select>
        </Field>
        {selected.injection_position === 1 && (
          <>
            <Field label="提示词深度">
              <input
                type="number"
                min={0}
                value={selected.injection_depth ?? 4}
                onChange={(e) => updatePrompt({ injection_depth: Number(e.target.value) })}
              />
            </Field>
            <Field label="提示词顺序">
              <input
                type="number"
                value={selected.injection_order ?? 100}
                onChange={(e) => updatePrompt({ injection_order: Number(e.target.value) })}
              />
            </Field>
          </>
        )}
        <Check
          label="禁止角色覆盖"
          checked={!!selected.forbid_overrides}
          onChange={(v) => updatePrompt({ forbid_overrides: v })}
        />
      </div>
      <div className="wb-prompt-triggers" role="group" aria-label="生成类型">
        <span>生成类型</span>
        {triggerNames.map(([value, label]) => (
          <button
            key={value}
            aria-pressed={triggers.includes(value)}
            onClick={() =>
              updatePrompt({
                injection_trigger: triggers.includes(value)
                  ? triggers.filter((t) => t !== value)
                  : [...triggers, value],
              })
            }
          >
            {label}
          </button>
        ))}
        <small>{triggers.length ? "" : "未选择时全部生效"}</small>
      </div>
    </div>
  );
  const promptSheet = selected ? (
    <div className={`wb-fold-body wb-prompt-sheet ${editorOpen ? "is-open" : ""}`} inert={!editorOpen}>
      <div>
        <section className="wb-prompt-card" aria-label="编辑提示词">
          <IconButton title="收起提示词编辑" onClick={() => setEditorOpen(false)}>
            <X size={15} />
          </IconButton>
          {heading}
          {selected.marker ? <p className="wb-note">此项由酒馆动态组装，可在上方控制启用与顺序。</p> : body}
        </section>
      </div>
    </div>
  ) : (
    <Empty>此类预设没有提示词子条目</Empty>
  );
  const json = (
    <Field label="预设 JSON">
      <textarea
        className="wb-code"
        value={advanced || JSON.stringify(draft, null, 2)}
        onChange={(e) => {
          setAdvanced(e.target.value);
          try {
            const value = JSON.parse(e.target.value);
            validatePreset(value);
            edit.setDraft(value);
            setAdvanced("");
          } catch {
            /* retain invalid input */
          }
        }}
      />
    </Field>
  );
  const bindingChecks = (
    <>
      {(["connection", "model"] as const).map((scope) => (
        <Check
          key={scope}
          label={`绑定当前${scope === "connection" ? "连接" : "模型"}`}
          disabled={scope === "connection" && !host.snapshot().current.connection}
          checked={host.prefs().bindings[host.bindingKey(scope)] === id}
          onChange={(v) => {
            const bindings = { ...host.prefs().bindings };
            if (v) bindings[host.bindingKey(scope)] = id;
            else delete bindings[host.bindingKey(scope)];
            host.preference({ bindings });
          }}
        />
      ))}
    </>
  );
  return (
    <fieldset
      disabled={task.busy}
      className={`wb-preset-editor ${desk ? "is-desk" : ""} ${studio ? "is-studio" : ""}`}
    >
      <Notice error={task.error} />
      {desk ? (
        <>
          <div className="wb-preset-desk">
            <section className="wb-preset-params" aria-label="采样参数">
              <h3>采样参数</h3>
              {sampling.filter((k) => k in draft).map(field)}
              {always.filter((k) => k in draft).map(field)}
            </section>
            <section className="wb-preset-order">
              {promptHead}
              {promptList}
            </section>
          </div>
          <section className="wb-preset-file" aria-label="预设文件">
            <h3>预设文件</h3>
            <div className="wb-preset-file-row">
              {bindingChecks}
              <span className="wb-grow" />
              <button
                onClick={() => {
                  const name = prompt("副本名称", `${id} 副本`);
                  if (name)
                    task.run(async () => {
                      const next = await host.createPreset(name, draft);
                      edit.saved(draft);
                      onSelect(next);
                    });
                }}
              >
                <Copy size={15} />
                另存为
              </button>
              <button
                onClick={() =>
                  host.download(
                    new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }),
                    `${id}.json`,
                  )
                }
              >
                <Download size={15} />
                导出
              </button>
              <label className="wb-upload-button">
                <Upload size={15} />
                导入到草稿
                <input
                  type="file"
                  accept=".json,application/json"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file)
                      task.run(async () => {
                        const value = JSON.parse(await file.text());
                        validatePreset(value);
                        edit.setDraft(value);
                      });
                  }}
                />
              </label>
            </div>
            <Fold title="编辑 JSON" initial={!!advanced}>
              {json}
            </Fold>
          </section>
        </>
      ) : studio ? (
        <div className="wb-prompt-studio">
          <section className="wb-prompt-studio-list">
            {promptHead}
            {promptList}
          </section>
          {selected ? (
            <section className="wb-prompt-studio-editor" aria-label="编辑提示词">
              {heading}
              {selected.marker ? (
                <p className="wb-note">此项由酒馆动态组装，只能调整启用与顺序。</p>
              ) : (
                <>
                  {injection}
                  {body}
                  <footer>
                    <span>{promptTokens[selected.identifier] ?? "—"} tokens</span>
                    <button className="wb-link is-danger" onClick={remove}>
                      <Trash2 size={14} />
                      删除提示词
                    </button>
                  </footer>
                </>
              )}
            </section>
          ) : (
            <Empty>此类预设没有提示词子条目</Empty>
          )}
        </div>
      ) : (
        <>
          <section className="wb-preset-card" aria-label="常用参数">
            {always.map(field)}
            {pins.filter((k) => k in draft && !always.includes(k)).map(field)}
          </section>
          <button
            className="wb-preset-pins-toggle"
            aria-expanded={pinsOpen}
            onClick={() => setPinsOpen(!pinsOpen)}
          >
            自定义常用项
          </button>
          <div
            className={`wb-fold-body ${pinsOpen ? "is-open" : ""}`}
            aria-hidden={!pinsOpen}
            inert={!pinsOpen}
          >
            <div>
              <div className="wb-preset-pins">
                {parameters
                  .filter((k) => !always.includes(k))
                  .map((k) => (
                    <Check
                      key={k}
                      label={parameterNames[k] || k}
                      checked={pins.includes(k)}
                      onChange={(v) =>
                        host.preference({ presetPins: v ? [...pins, k] : pins.filter((p) => p !== k) })
                      }
                    />
                  ))}
              </div>
            </div>
          </div>
          {promptHead}
          {promptList}
          <div className={`wb-preset-more ${editorOpen ? "is-editor-open" : ""}`}>
            {promptSheet}
            <Fold title="更多预设设置">
              {injection && <Fold title="注入与触发">{injection}</Fold>}
              {selected && !selected.marker && (
                <button className="wb-link" onClick={remove}>
                  <Trash2 size={14} />
                  删除提示词
                </button>
              )}
              <Fold title="其他生成参数">
                {parameters.filter((k) => !pins.includes(k) && !always.includes(k)).map(field)}
              </Fold>
              <Fold title="提示格式">
                {[
                  ["impersonation_prompt", "AI 帮答指令"],
                  ["new_chat_prompt", "新对话提示"],
                  ["new_group_chat_prompt", "新群聊提示"],
                  ["new_example_chat_prompt", "对话示例提示"],
                  ["continue_nudge_prompt", "续写提示"],
                  ["send_if_empty", "空输入替代文本"],
                  ["wi_format", "世界书格式"],
                  ["scenario_format", "场景格式"],
                  ["personality_format", "性格格式"],
                ]
                  .filter(([key]) => key in draft)
                  .map(([key, label]) => (
                    <Field key={key} label={label}>
                      <textarea value={draft[key] || ""} onChange={(e) => change(key, e.target.value)} />
                    </Field>
                  ))}
              </Fold>
              <Fold title="模型 / 连接绑定">{bindingChecks}</Fold>
              <Fold title="文件与高级编辑">
                <div className="wb-persona-actions">
                  <button
                    onClick={() => {
                      const name = prompt("新预设名称");
                      if (name) task.run(async () => onSelect(await host.createPreset(name)));
                    }}
                  >
                    <Plus size={15} />
                    新建预设
                  </button>
                  <button
                    onClick={() => {
                      const name = prompt("副本名称", `${id} 副本`);
                      if (name)
                        task.run(async () => {
                          const next = await host.createPreset(name, draft);
                          edit.saved(draft);
                          onSelect(next);
                        });
                    }}
                  >
                    <Copy size={15} />
                    另存为
                  </button>
                  <button
                    onClick={() => {
                      if (confirm(`删除预设「${id}」？`))
                        task.run(async () => {
                          await host.deletePreset(id);
                          onSelect(host.snapshot().current.preset);
                        });
                    }}
                  >
                    <Trash2 size={15} />
                    删除预设
                  </button>
                </div>
                <button
                  onClick={() =>
                    host.download(
                      new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }),
                      `${id}.json`,
                    )
                  }
                >
                  <Download size={15} />
                  导出预设
                </button>
                <Field label="导入预设到草稿">
                  <input
                    type="file"
                    accept=".json,application/json"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file)
                        task.run(async () => {
                          const value = JSON.parse(await file.text());
                          validatePreset(value);
                          edit.setDraft(value);
                        });
                    }}
                  />
                </Field>
                {json}
              </Fold>
            </Fold>
          </div>
        </>
      )}
      <SaveBar
        dirty={edit.dirty || !!advanced}
        busy={task.busy}
        message={edit.message}
        label={running ? "保存" : actionLabels.updatePreset}
        reset={() => {
          setAdvanced("");
          edit.reset();
        }}
        save={() =>
          task.run(async () => {
            if (advanced) throw new Error("JSON 无法解析，请先修正。");
            edit.saved(
              running
                ? host.applyPresetDraft(id, edit.base, draft)
                : await host.savePreset(id, edit.base, draft),
            );
          })
        }
      />
      {pending && (
        <footer className="wb-savebar is-pending" aria-label="预设有未写入的修改">
          <span className="wb-savebar-dot" aria-hidden="true" />
          <span className="wb-savebar-copy">
            <span role="status">预设有未写入的修改</span>
            {pendingDetail && <small>{pendingDetail}</small>}
          </span>
          <button
            className="wb-savebar-revert"
            aria-label="还原为预设文件"
            disabled={task.busy}
            onClick={() => task.run(() => host.revertPreset())}
          >
            还原
          </button>
          <button
            className="wb-savebar-save"
            aria-label={actionLabels.updatePreset}
            disabled={task.busy}
            onClick={() => task.run(() => host.updatePreset(id))}
          >
            {actionLabels.updatePreset}
          </button>
        </footer>
      )}
    </fieldset>
  );
}
