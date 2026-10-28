import { useEffect, useState } from "react";
import { Check, Ellipsis, PencilLine, Trash2, X } from "./icons";
import type { HostAdapter } from "../host/adapter";
import { ctx } from "../host/internals";
import { Popover } from "./Popover";
import { beginImageInsert } from "./ImageInsertion";
import {
  describeMessageAction,
  messageActionDisabled,
  messageActions,
  messageControl,
  messageMenuControls,
  invokeMessageAction,
  type MessageAction,
} from "./message-actions";

const commonActions: MessageAction[][] = [
  ["wb-image-message-button", "sd_message_gen"],
  ["mes_copy"],
  ["wb-image-insert-button"],
  ["mes_embed"],
];
const primaryActions = new Set<MessageAction>([...commonActions.flat(), "mes_edit", "mes_edit_delete"]);

/** Keep the compact toolbar on the native floor; delegate data changes to ST. */
export function MessageActions({
  host,
  node,
  editing,
  busy,
}: {
  host: HostAdapter;
  node: HTMLElement;
  editing: boolean;
  busy: boolean;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [deleting, setDeleting] = useState(false);
  const getControls = () =>
    commonActions.map(
      (actions) =>
        actions
          .map((action) => messageControl(node, action))
          .find((control) => control && !control.hidden && getComputedStyle(control).display !== "none") ??
        null,
    );
  const [controls, setControls] = useState(getControls);
  const id = Number(node.getAttribute("mesid")) + 1;
  const locked = busy || deleting;
  const editor = node.closest("#chat")?.querySelector(".edit_textarea");
  const anotherEditor = !!editor && !node.contains(editor);
  const click = (action: MessageAction) => {
    setAnchor(null);
    invokeMessageAction(node, action);
  };
  useEffect(() => setAnchor(null), [editing, node]);
  useEffect(() => {
    const update = () => {
      const next = getControls();
      setControls((old) => (old.every((control, index) => control === next[index]) ? old : next));
    };
    update();
    return host.chatObserver.subscribe((change) => {
      if (change.nodes || change.editing || change.content.has(Number(node.getAttribute("mesid")))) update();
    });
  }, [host, node]);
  const remove = async () => {
    if (locked || anotherEditor) return;
    setAnchor(null);
    setDeleting(true);
    try {
      // The native confirmation deletes this floor, without opening or saving its editor.
      await ctx().deleteMessage(Number(node.getAttribute("mesid")), undefined, true);
    } catch (error) {
      host.report(error);
    } finally {
      setDeleting(false);
    }
  };
  const extra = anchor
    ? messageMenuControls(node, editing).filter((control) => {
        const { id } = describeMessageAction(control);
        return !id || !primaryActions.has(id);
      })
    : [];
  return (
    <div
      className={`wb-message-actions ${editing ? "is-editing" : ""}`}
      role="group"
      aria-label={`第 ${id} 层${editing ? "编辑" : "常用"}操作`}
    >
      {editing ? (
        <span className="wb-message-edit-caption">
          <PencilLine size={13} />
          编辑中
        </span>
      ) : (
        commonActions.map((actions, index) => {
          const control = controls[index];
          const action = actions.find((action) => control?.classList.contains(action)) || actions[0];
          const [Icon, label] = messageActions[action];
          return (
            <button
              key={actions[0]}
              type="button"
              className="wb-message-common"
              aria-label={label}
              title={label}
              disabled={messageActionDisabled(control, locked)}
              onClick={(event) => {
                setAnchor(null);
                if (action === "wb-image-insert-button")
                  beginImageInsert(host, Number(node.getAttribute("mesid")), event.currentTarget);
                else invokeMessageAction(node, action);
              }}
            >
              <Icon size={12} />
            </button>
          );
        })
      )}
      <button
        type="button"
        className="wb-message-delete"
        aria-label={`删除第 ${id} 层消息`}
        title={anotherEditor ? "请先保存或取消正在编辑的消息" : "删除消息"}
        disabled={locked || anotherEditor}
        onClick={() => void remove()}
      >
        <Trash2 size={editing ? 16 : 12} />
      </button>
      {!editing && (
        <button
          type="button"
          className="wb-message-edit"
          aria-label={`编辑第 ${id} 层`}
          title="编辑消息"
          disabled={locked}
          onClick={() => click("mes_edit")}
        >
          <PencilLine size={12} />
        </button>
      )}
      <button
        type="button"
        className="wb-message-more"
        aria-label={editing ? "更多编辑操作" : `第 ${id} 层更多操作`}
        title={editing ? "更多编辑操作" : "更多消息操作"}
        aria-haspopup="dialog"
        aria-expanded={!!anchor}
        onClick={(event) => setAnchor(anchor ? null : event.currentTarget)}
      >
        <Ellipsis size={editing ? 16 : 12} />
      </button>
      {editing && (
        <>
          <span className="wb-message-divider" aria-hidden="true" />
          <button
            type="button"
            className="wb-message-cancel"
            aria-label={`取消编辑第 ${id} 层`}
            title="取消编辑 · Esc"
            onClick={() => click("mes_edit_cancel")}
          >
            <X size={17} />
          </button>
          <button
            type="button"
            className="wb-message-save"
            aria-label={`保存第 ${id} 层`}
            title="保存编辑 · Ctrl / ⌘ + Enter"
            disabled={locked}
            onClick={() => click("mes_edit_done")}
          >
            <Check size={18} />
          </button>
        </>
      )}
      {anchor && (
        <Popover
          anchor={anchor}
          title={`第 ${id} 层${editing ? "编辑" : "消息"}操作`}
          onClose={() => setAnchor(null)}
          className="wb-message-menu"
        >
          <div className="wb-message-menu-rows">
            {extra.map((control, index) => {
              const { icon: Icon, label } = describeMessageAction(control);
              return (
                <button
                  key={index}
                  disabled={messageActionDisabled(control, locked)}
                  onClick={() => {
                    setAnchor(null);
                    control.click();
                  }}
                >
                  <Icon size={17} />
                  <span>{label}</span>
                </button>
              );
            })}
            {!extra.length && <p>当前没有可用操作</p>}
          </div>
        </Popover>
      )}
    </div>
  );
}
