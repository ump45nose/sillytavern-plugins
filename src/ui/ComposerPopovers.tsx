import { Suspense, useEffect, useState } from "react";
import { lazyChunk } from "./lazyChunk";
import {
  Download,
  FileText,
  ListMinus,
  MessageSquareX,
  PencilLine,
  Search,
  Trash2,
  Upload,
  UsersRound,
} from "./icons";
import type { HostAdapter } from "../host/adapter";
import type { Data, SettingsPage } from "../host/types";
import { Popover } from "./Popover";
import { Empty, Loading, Notice, useTask, useHostSlices } from "./common";
import { toolIcon } from "./ToolIcon";
import { useComposerTools } from "./useTools";
const NativeSettings = lazyChunk(() => import("../modules/NativeSettings"));
export type ComposerPopup = {
  kind: "menu" | "tools" | "quick" | "chat" | "files" | "rename" | "pinned" | "tool";
  anchor: HTMLElement;
  toolId?: string;
  toolIds?: string[];
};
export function ComposerPopovers({
  host,
  popup,
  close,
  settings,
  activate,
  exiting,
}: {
  host: HostAdapter;
  popup: ComposerPopup;
  close: () => void;
  settings: (page: SettingsPage, group?: string) => void;
  activate: (id: string, anchor: HTMLElement) => void;
  exiting?: boolean;
}) {
  const [nativeEditor, setNativeEditor] = useState<"note" | "cfg" | null>(
    popup.kind === "tool" ? (popup.toolId?.endsWith(":option_toggle_AN") ? "note" : "cfg") : null,
  );
  const snap = useHostSlices(host, ["session", "chat", "prefs"]),
    task = useTask(),
    [query, setQuery] = useState(""),
    [group, setGroup] = useState(""),
    [files, setFiles] = useState<Data[]>([]),
    [name, setName] = useState(snap.chatName),
    [renaming, setRenaming] = useState<string | null>(popup.kind === "rename" ? snap.chatName : null);
  const toolRow = useComposerTools(host, snap.busy);
  useEffect(() => {
    if (popup.kind === "files") task.run(async () => setFiles(await host.recentChats()));
  }, [popup.kind, snap.chatName, snap.groupId]);
  const native = (selector: string) => {
    close();
    try {
      host.click(selector);
    } catch (e) {
      host.report(e);
    }
  };
  const replies = [...new Map(host.quickReplies().map((x: any) => [x.key, x])).values()] as any[],
    groups = [...new Set(replies.map((x) => x.set))],
    selected = groups.includes(group) ? group : groups[0];
  const heading = nativeEditor
    ? nativeEditor === "note"
      ? "作者注释"
      : "CFG 引导"
    : renaming
      ? "重命名对话"
      : {
          menu: "聊天菜单",
          tools: "扩展工具",
          quick: "快速回复",
          chat: "聊天管理",
          files: "聊天文件",
          rename: "重命名对话",
          pinned: "更多工具",
          tool: "聊天工具",
        }[popup.kind];
  return (
    <Popover
      anchor={popup.anchor}
      title={heading}
      onClose={close}
      exiting={exiting}
      tools={
        nativeEditor && popup.kind !== "tool" ? (
          <button onClick={() => setNativeEditor(null)}>返回菜单</button>
        ) : popup.kind === "menu" || popup.kind === "tools" || popup.kind === "pinned" ? (
          <button
            onClick={() => {
              close();
              settings("settings", "常用工具");
            }}
          >
            常用入口
          </button>
        ) : popup.kind === "quick" ? (
          <button
            onClick={() => {
              close();
              settings("extensions", "快捷回复");
            }}
          >
            管理
          </button>
        ) : undefined
      }
    >
      <Notice error={task.error} />
      {nativeEditor ? (
        <Suspense fallback={<Loading />}>
          <NativeSettings host={host} page={nativeEditor} group={heading} />
        </Suspense>
      ) : renaming !== null ? (
        <form
          className="wb-pop-form"
          onSubmit={(e) => {
            e.preventDefault();
            task.run(async () => {
              await host.renameChat(renaming, name);
              close();
            });
          }}
        >
          <label className="wb-field">
            对话名称
            <input aria-label="对话名称" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button className="wb-primary" disabled={task.busy || !name.trim()}>
            保存名称
          </button>
        </form>
      ) : popup.kind === "menu" || popup.kind === "tools" ? (
        <div className="wb-pop-list">
          {host.menuItems(popup.kind).map((item, index) => {
            const Icon = toolIcon(item.id, item.label);
            return (
              <button
                className="wb-pop-row"
                key={item.id + ":" + index}
                disabled={item.disabled}
                onClick={() => {
                  if (item.node.id === "option_toggle_AN" || item.node.id === "option_toggle_CFG") {
                    setNativeEditor(item.node.id === "option_toggle_AN" ? "note" : "cfg");
                  } else {
                    close();
                    try {
                      item.node.click();
                    } catch (e) {
                      host.report(e);
                    }
                  }
                }}
              >
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            );
          })}
          {!host.menuItems(popup.kind).length && <Empty>当前没有可用工具</Empty>}
        </div>
      ) : popup.kind === "pinned" ? (
        <div className="wb-pop-list">
          {toolRow.tools
            .filter((tool) => popup.toolIds?.includes(tool.id))
            .map((tool) => {
              const Icon = toolIcon(tool.id, tool.label),
                disabled = toolRow.disabled(tool.id);
              return (
                <button
                  className="wb-pop-row"
                  key={tool.id}
                  disabled={disabled}
                  onClick={(e) => activate(tool.id, e.currentTarget)}
                >
                  <Icon size={17} />
                  <span>
                    {tool.label}
                    {disabled && !snap.busy && <small>当前不可用</small>}
                  </span>
                </button>
              );
            })}
        </div>
      ) : popup.kind === "quick" ? (
        <>
          <label className="wb-pop-search">
            <Search size={15} />
            <input
              aria-label="搜索快速回复"
              placeholder="搜索名称或内容"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="wb-pop-tabs">
            {groups.map((g) => (
              <button key={g} aria-pressed={g === selected} onClick={() => setGroup(g)}>
                {g}
              </button>
            ))}
          </div>
          <div className="wb-pop-list">
            {replies
              .filter(
                (x) =>
                  x.set === selected &&
                  (!query || (x.label + x.message).toLowerCase().includes(query.toLowerCase())),
              )
              .map((qr) => (
                <div key={qr.key} className="wb-quick-row">
                  <button
                    aria-label={qr.label || qr.message?.slice(0, 40) || "未命名回复"}
                    onClick={() => {
                      close();
                      Promise.resolve()
                        .then(qr.execute)
                        .catch((e) => host.report(e));
                    }}
                  >
                    <span>
                      {qr.label || qr.message?.slice(0, 40) || "未命名回复"}
                      <small>{qr.insertOnly ? "插入" : "按原配置运行"}</small>
                    </span>
                  </button>
                  <button
                    className="wb-icon"
                    aria-label={`编辑后使用 ${qr.label}`}
                    onClick={() => {
                      host.setInput(qr.message || "");
                      close();
                    }}
                  >
                    <PencilLine size={15} />
                  </button>
                </div>
              ))}
            {!replies.length && <Empty>没有启用的快速回复</Empty>}
          </div>
        </>
      ) : popup.kind === "chat" ? (
        <div className="wb-pop-list">
          <button
            className="wb-pop-row"
            disabled={snap.busy}
            onClick={() => native("#option_convert_to_group")}
          >
            <UsersRound size={17} />
            转换为群聊
          </button>
          <button
            className="wb-pop-row"
            disabled={snap.busy || !snap.messages.length}
            onClick={() => native("#option_delete_mes")}
          >
            <ListMinus size={17} />
            删除消息
          </button>
          <hr />
          <button className="wb-pop-row" disabled={snap.busy} onClick={() => native("#option_close_chat")}>
            <MessageSquareX size={17} />
            关闭当前对话
          </button>
          <button
            className="wb-pop-row"
            onClick={() => {
              close();
              settings("character", "群组");
            }}
          >
            <UsersRound size={17} />
            群组管理
          </button>
        </div>
      ) : (
        <>
          <label className="wb-pop-search">
            <Search size={15} />
            <input
              aria-label="搜索聊天文件"
              placeholder="搜索聊天文件"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <div className="wb-pop-list">
            {files
              .filter((c) => String(c.file_name).includes(query))
              .map((c) => {
                const id = String(c.file_name),
                  title = id.replace(/\.jsonl$/, "");
                return (
                  <div className={`wb-chat-file ${title === snap.chatName ? "is-active" : ""}`} key={id}>
                    <FileText size={16} />
                    <button
                      disabled={snap.busy || task.busy}
                      onClick={() =>
                        task.run(async () => {
                          await host.openChat(id);
                          close();
                        })
                      }
                    >
                      <strong>{title}</strong>
                      <small>
                        {title === snap.chatName ? "当前对话 · " : ""}
                        {c.chat_items ?? c.mes ?? ""} 层
                      </small>
                    </button>
                    <button
                      className="wb-icon"
                      aria-label={`导出 ${title}`}
                      disabled={task.busy}
                      onClick={() => task.run(() => host.exportChat(id))}
                    >
                      <Download size={15} />
                    </button>
                    <button
                      className="wb-icon"
                      aria-label={`重命名 ${title}`}
                      disabled={snap.busy || task.busy}
                      onClick={() => {
                        setRenaming(title);
                        setName(title);
                      }}
                    >
                      <PencilLine size={15} />
                    </button>
                    <button
                      className="wb-icon"
                      aria-label={`删除 ${title}`}
                      disabled={snap.busy || task.busy}
                      onClick={() => {
                        if (confirm(`删除聊天文件「${title}」？此操作会删除记录。`))
                          task.run(async () => {
                            await host.deleteChat(id);
                            setFiles(await host.recentChats());
                          });
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                );
              })}
            {!files.length && <Empty>{task.busy ? "正在读取…" : "还没有聊天文件"}</Empty>}
          </div>
          <footer className="wb-pop-footer">
            <label className="wb-upload-button">
              <Upload size={15} />
              导入
              <input
                type="file"
                accept=".jsonl,.json"
                aria-label="导入聊天文件"
                disabled={snap.busy || task.busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file)
                    task.run(async () => {
                      await host.importChat(file);
                      setFiles(await host.recentChats());
                    });
                  e.target.value = "";
                }}
              />
            </label>
            <button
              onClick={() => {
                setRenaming(snap.chatName);
                setName(snap.chatName);
              }}
              disabled={!snap.chatName || snap.busy || task.busy}
            >
              <PencilLine size={15} />
              重命名当前
            </button>
          </footer>
        </>
      )}
    </Popover>
  );
}
