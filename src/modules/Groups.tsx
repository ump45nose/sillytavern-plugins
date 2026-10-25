import { useLayoutEffect, useState } from "react";
import { ArrowDown, ArrowUp, Image, MessageSquare, Plus, Trash2, UsersRound } from "../ui/icons";
import type { HostAdapter } from "../host/adapter";
import type { Data } from "../host/types";
import { Field, IconButton, Notice, SearchBox, useTask, useHostSlices, withoutChat } from "../ui/common";
import { Check, Fold, SaveBar, useDraft } from "../ui/ResourceControls";
import { BoundControl } from "../ui/HostControl";
import { Select } from "../ui/Select";
export default function Groups({ host }: { host: HostAdapter }) {
  // Subscribed for the re-render: the groups below are read from the host on each render.
  useHostSlices(host, withoutChat);
  const task = useTask(),
    groups = host.groups(),
    [id, setId] = useState(groups[0]?.id || ""),
    [creating, setCreating] = useState(false),
    [query, setQuery] = useState("");
  return (
    <div className="wb-designed-settings">
      <header className="wb-designed-page-head">
        <div>
          <h2>群组管理</h2>
          <small>成员、发言顺序与群聊规则</small>
        </div>
        <button
          onClick={() => {
            setCreating(true);
            setId("");
          }}
        >
          <Plus size={15} />
          新建群组
        </button>
      </header>
      <Notice error={task.error} />
      <div className="wb-group-layout">
        <aside>
          <SearchBox value={query} onChange={setQuery} placeholder="搜索群组" />
          {groups
            .filter((g: Data) => g.name.toLowerCase().includes(query.toLowerCase()))
            .map((g: Data) => (
              <button
                className="wb-group-choice"
                key={g.id}
                aria-pressed={id === g.id && !creating}
                onClick={() => {
                  setCreating(false);
                  setId(g.id);
                }}
              >
                <UsersRound size={18} />
                <span>
                  <strong>{g.name}</strong>
                  <small>
                    {g.members.length} 位成员 · {g.chats?.length || 0} 个对话
                  </small>
                </span>
              </button>
            ))}
        </aside>
        {id || creating ? (
          <GroupEditor
            key={id || "new"}
            host={host}
            id={id}
            done={(next) => {
              setCreating(false);
              setId(next);
            }}
          />
        ) : (
          <p className="wb-note">创建一个群组，开始多人故事。</p>
        )}
      </div>
    </div>
  );
}
function GroupEditor({ host, id, done }: { host: HostAdapter; id: string; done: (id: string) => void }) {
  const snap = useHostSlices(host, withoutChat),
    task = useTask(),
    edit = useDraft(
      () =>
        host.groups().find((g: Data) => g.id === id) || {
          name: "新群组",
          members: [],
          disabled_members: [],
          activation_strategy: 0,
          generation_mode: 0,
          auto_mode_delay: 5,
          allow_self_responses: false,
          hideMutedSprites: false,
        },
      host.revision(),
      { host, key: "group:" + (id || "new") },
    ),
    [search, setSearch] = useState("");
  const { draft, change } = edit;
  const move = (avatar: string, dir: number) => {
    const members = [...draft.members],
      index = members.indexOf(avatar);
    [members[index], members[index + dir]] = [members[index + dir], members[index]];
    change("members", members);
  };
  const avatarControls = (
    <div className="wb-group-avatar-tools">
      {draft.avatar_url && <img src={draft.avatar_url} alt="群组头像" />}
      <label className="wb-import-character">
        <Image size={15} />
        更换头像
        <input
          type="file"
          aria-label="上传群组头像"
          accept="image/*"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) task.run(async () => change("avatar_url", await host.groupAvatar(file, id)));
          }}
        />
      </label>
      <button disabled={!draft.avatar_url} onClick={() => change("avatar_url", "")}>
        使用成员拼图
      </button>
    </div>
  );
  return (
    <fieldset disabled={task.busy} className="wb-group-editor">
      <Notice error={task.error} />
      <section className="wb-designed-section">
        <h3>群组信息</h3>
        {avatarControls}
        <div className="wb-designed-fields">
          <Field label="群组名称">
            <input value={draft.name} onChange={(e) => change("name", e.target.value)} />
          </Field>
          <Field label="成员发言方式">
            <Select
              value={draft.activation_strategy}
              onChange={(e) => change("activation_strategy", Number(e.target.value))}
            >
              <option value={0}>自然顺序</option>
              <option value={1}>列表顺序</option>
              <option value={2}>手动选择</option>
              <option value={3}>轮询发言</option>
            </Select>
          </Field>
          <Field label="生成模式">
            <Select
              value={draft.generation_mode}
              onChange={(e) => change("generation_mode", Number(e.target.value))}
            >
              <option value={0}>轮换角色卡</option>
              <option value={1}>合并角色卡 · 排除静音成员</option>
              <option value={2}>合并角色卡 · 包含静音成员</option>
            </Select>
          </Field>
          <Field label="自动模式间隔（秒）">
            <input
              type="number"
              min={1}
              value={draft.auto_mode_delay}
              onChange={(e) => change("auto_mode_delay", Number(e.target.value))}
            />
          </Field>
          <Check
            label="允许连续发言"
            checked={!!draft.allow_self_responses}
            onChange={(v) => change("allow_self_responses", v)}
          />
          <Check
            label="隐藏静音成员立绘"
            checked={!!draft.hideMutedSprites}
            onChange={(v) => change("hideMutedSprites", v)}
          />
          <Check label="收藏群组" checked={!!draft.fav} onChange={(v) => change("fav", v)} />
          <Field label="合并角色卡前缀">
            <textarea
              value={draft.generation_mode_join_prefix || ""}
              onChange={(e) => change("generation_mode_join_prefix", e.target.value)}
            />
          </Field>
          <Field label="合并角色卡后缀">
            <textarea
              value={draft.generation_mode_join_suffix || ""}
              onChange={(e) => change("generation_mode_join_suffix", e.target.value)}
            />
          </Field>
        </div>
      </section>
      <section className="wb-designed-section">
        <h3>当前成员 · {draft.members.length}</h3>
        {draft.members.map((avatar: string, i: number) => {
          const c = snap.characters.find((x) => x.id === avatar);
          return (
            <div className="wb-group-member" key={avatar}>
              <img src={c?.image} alt="" />
              <strong>{c?.name || avatar}</strong>
              <Check
                label="参与发言"
                checked={!draft.disabled_members.includes(avatar)}
                onChange={(v) =>
                  change(
                    "disabled_members",
                    v
                      ? draft.disabled_members.filter((a: string) => a !== avatar)
                      : [...draft.disabled_members, avatar],
                  )
                }
              />
              {[-1, 1].map((dir) => (
                <IconButton
                  key={dir}
                  title={dir < 0 ? "上移成员" : "下移成员"}
                  disabled={i + dir < 0 || i + dir >= draft.members.length}
                  onClick={() => move(avatar, dir)}
                >
                  {dir < 0 ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
                </IconButton>
              ))}
              <IconButton
                title={`移除成员 ${c?.name || avatar}`}
                onClick={() => {
                  change(
                    "members",
                    draft.members.filter((a: string) => a !== avatar),
                  );
                  change(
                    "disabled_members",
                    draft.disabled_members.filter((a: string) => a !== avatar),
                  );
                }}
              >
                <Trash2 size={14} />
              </IconButton>
            </div>
          );
        })}
        <SearchBox value={search} onChange={setSearch} placeholder="搜索并添加角色" />
        <div className="wb-group-candidates">
          {snap.characters
            .filter(
              (c) => !draft.members.includes(c.id) && c.name.toLowerCase().includes(search.toLowerCase()),
            )
            .map((c) => (
              <button key={c.id} onClick={() => change("members", [...draft.members, c.id])}>
                <img src={c.image} alt="" />
                {c.name}
                <Plus size={13} />
              </button>
            ))}
        </div>
      </section>
      {id && (
        <Fold title="群组偏好与当前对话">
          <div className="wb-designed-fields">
            <Field label="外部媒体">
              <Select
                value={host.groupMedia(id)}
                onChange={(e) => task.run(() => host.setGroupMedia(id, e.target.value))}
              >
                <option value="global">沿用全局设置</option>
                <option value="allow">允许外部媒体</option>
                <option value="forbid">禁止外部媒体</option>
              </Select>
            </Field>
            {snap.groupId === id && (
              <label className="wb-check">
                <BoundControl host={host} id="rm_group_automode" label="当前群聊自动发言" />
                当前群聊自动发言
              </label>
            )}
          </div>
          {snap.groupId === id ? (
            <GroupOverrides key={snap.chatName} host={host} id={id} />
          ) : (
            <small>开始此群聊后，可编辑当前对话的情景、示例和系统提示词覆盖。</small>
          )}
        </Fold>
      )}
      <SaveBar
        {...edit}
        busy={task.busy}
        label="保存群组"
        save={() =>
          task.run(async () => {
            const groups = await host.saveGroup(id ? edit.base : null, draft);
            const g = groups.find((g: Data) => (id ? g.id === id : g.name === draft.name));
            if (g) {
              edit.saved(g);
              if (!id) host.drafts.delete("group:new");
              done(g.id);
            }
          })
        }
      />
      {id && (
        <footer className="wb-editor-footer">
          <span className="wb-grow" />
          <>
            <button disabled={edit.dirty} onClick={() => task.run(() => host.openGroup(id))}>
              <MessageSquare size={15} />
              开始群聊
            </button>
            <button
              onClick={() => {
                if (confirm("删除此群组及其聊天文件？"))
                  task.run(async () => {
                    await host.deleteGroup(id);
                    host.drafts.delete("group:" + id);
                    done(host.groups()[0]?.id || "");
                  });
              }}
            >
              <Trash2 size={15} />
              删除群组
            </button>
          </>
        </footer>
      )}
    </fieldset>
  );
}

function GroupOverrides({ host, id }: { host: HostAdapter; id: string }) {
  const snap = useHostSlices(host, withoutChat),
    chatId = host.groupChatId(),
    key = "group-overrides:" + id + ":" + chatId,
    task = useTask(),
    edit = useDraft(() => host.groupOverrides(), host.revision(), { host, key });
  useLayoutEffect(() => {
    const draft = host.drafts.get(key);
    if (draft) draft.extra = { groupId: id, chatId };
  }, [host, key, edit.base, edit.draft]);
  return (
    <section className="wb-designed-section">
      <h3>当前群聊覆盖</h3>
      <Notice error={task.error} />
      <div className="wb-designed-fields">
        {[
          ["scenario", "情景覆盖"],
          ["mes_example", "示例对话覆盖"],
          ["system_prompt", "系统提示词覆盖"],
        ].map(([key, label]) => (
          <Field key={key} label={label}>
            <textarea value={edit.draft[key]} onChange={(e) => edit.change(key, e.target.value)} />
          </Field>
        ))}
      </div>
      <SaveBar
        {...edit}
        busy={task.busy || snap.busy}
        label="保存对话覆盖"
        save={() =>
          task.run(async () => edit.saved(await host.saveGroupOverrides(id, chatId, edit.base, edit.draft)))
        }
      />
      <div className="wb-designed-actions">
        <button
          onClick={() => {
            for (const key of ["scenario", "mes_example", "system_prompt"]) edit.change(key, "");
          }}
        >
          清空覆盖
        </button>
      </div>
    </section>
  );
}
