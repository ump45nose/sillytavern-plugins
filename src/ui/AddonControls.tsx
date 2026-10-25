import { useEffect, useLayoutEffect, useState, useRef, useSyncExternalStore, Suspense } from "react";
import { lazyChunk } from "./lazyChunk";
import { createPortal } from "react-dom";
import { ImagePlus, Pause, Play, Square, X, ListTree, Images } from "./icons";
import type { HostAdapter } from "../host/adapter";
import type { MessageTarget } from "../addons/types";
import { addonEnabled } from "../addons/catalog";
import { addonManager } from "../addons/runtime";
import { useHostSlices, withoutChat } from "./common";
import { bus } from "../host/bus";
const References = lazyChunk(() => import("../addons/image-gen/References"));
/** Persistent task controls live above the content, independently of either sidebar. */
export function AddonTasks({ host }: { host: HostAdapter }) {
  const manager = addonManager(host);
  useSyncExternalStore(manager.subscribe, manager.revision);
  const tasks = manager.tasks();
  return tasks.length ? (
    <div className="wb-addon-task-strip" aria-label="附加功能任务">
      {tasks.map((task) => (
        <div key={task.id}>
          <button title="查看任务工作区" onClick={() => manager.api(task.id).open("workspace")}>
            {task.id === "outline" ? <ListTree size={13} /> : <ImagePlus size={13} />}
            <span>{task.label}</span>
          </button>
          {task.id === "outline" && (
            <button
              aria-label={task.status === "running" ? "暂停自动写作" : "继续自动写作"}
              disabled={task.status === "pausing"}
              onClick={() =>
                void task.runtime
                  .action(task.status === "running" ? "pause" : "resume")
                  .catch((e) => host.report(e))
              }
            >
              {task.status === "running" ? <Pause size={13} /> : <Play size={13} />}
            </button>
          )}
          <button
            aria-label={`停止${task.id === "outline" ? "自动写作" : "生图"}`}
            onClick={task.runtime.stop}
          >
            <Square size={13} />
          </button>
        </div>
      ))}
    </div>
  ) : null;
}
export function beginImage(host: HostAdapter, id: number) {
  if (!addonEnabled(host.prefs(), "image-gen")) return;
  const manager = addonManager(host);
  try {
    const target = manager.bridge.target(id);
    void manager
      .ensure("image-gen")
      .then((runtime) => runtime.action("manual", target))
      .catch((e) => host.report(e));
  } catch (e) {
    host.report(e);
  }
}
/** Decorate native pencil rows; never recreate native messages, controls or media. */
export function MessageImageControls({ host }: { host: HostAdapter }) {
  const snap = useHostSlices(host, withoutChat);
  // Results persist into chat metadata, so the welcome screen (no chat file) gets no image action.
  const enabled = addonEnabled(host.prefs(), "image-gen") && !!snap.chatName,
    [slots, setSlots] = useState<
      {
        slot: HTMLElement;
        id: number;
      }[]
    >([]);
  useLayoutEffect(() => {
    if (!enabled) {
      setSlots([]);
      return;
    }
    const chat = document.getElementById("chat")!,
      owned = new Set<HTMLElement>();
    const scan = () => {
      const next = [...chat.querySelectorAll<HTMLElement>(".mes")].flatMap((message) => {
        const pencil = message.querySelector(".mes_edit");
        if (!pencil?.parentElement) return [];
        let slot = pencil.parentElement.querySelector<HTMLElement>(":scope > .wb-image-slot");
        if (!slot) {
          slot = document.createElement("span");
          slot.className = "wb-image-slot";
          pencil.after(slot);
          owned.add(slot);
        }
        return [{ slot, id: Number(message.getAttribute("mesid")) }];
      });
      setSlots((prev) =>
        prev.length === next.length && prev.every((s, i) => s.slot === next[i].slot && s.id === next[i].id)
          ? prev
          : next,
      );
    };
    scan();
    // Renumbered floors rescan too, so a slot never keeps a stale mesid.
    const off = host.chatObserver.subscribe((change) => {
      if (change.nodes || change.editing) scan();
    });
    const over = (e: DragEvent) => {
      if (
        e.dataTransfer?.types.includes("application/x-wb-image") &&
        (e.target as Element)?.closest(".mes")
      ) {
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
      }
    };
    const drop = (e: DragEvent) => {
      const message = (e.target as Element)?.closest(".mes");
      if (!message || !e.dataTransfer?.types.includes("application/x-wb-image")) return;
      e.preventDefault();
      try {
        const result = JSON.parse(e.dataTransfer.getData("application/x-wb-image")),
          manager = addonManager(host),
          target = manager.bridge.target(Number(message.getAttribute("mesid")));
        void manager
          .ensure("image-gen")
          .then((runtime) => runtime.action("insert", result.id, target))
          .catch((error) => host.report(error));
      } catch (error) {
        host.report(error);
      }
    };
    chat.addEventListener("dragover", over);
    chat.addEventListener("drop", drop);
    return () => {
      off();
      chat.removeEventListener("dragover", over);
      chat.removeEventListener("drop", drop);
      owned.forEach((slot) => slot.remove());
    };
  }, [enabled, host]);
  return (
    <>
      {enabled &&
        slots.map(({ slot, id }) =>
          createPortal(
            <button
              type="button"
              className="wb-image-message-button wb-icon"
              aria-label={`为第 ${id + 1} 层生图`}
              title="输入生图提示词"
              disabled={host.snapshot().busy}
              onClick={() => beginImage(host, id)}
            >
              <ImagePlus size={18} />
            </button>,
            slot,
          ),
        )}
    </>
  );
}
export function ImageInputMode({ host }: { host: HostAdapter }) {
  const manager = addonManager(host);
  useHostSlices(host, withoutChat);
  const [mode, setMode] = useState<{
      target: MessageTarget;
      draft: string;
      start: number;
      end: number;
    } | null>(null),
    [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  useEffect(
    () => () => {
      const mode = modeRef.current;
      if (mode?.target.chatKey === manager.bridge.key()) {
        const input = document.getElementById("send_textarea") as HTMLTextAreaElement;
        input.value = mode.draft;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.setSelectionRange(mode.start, mode.end);
      }
    },
    [manager],
  );
  useEffect(() => {
    const input = document.getElementById("send_textarea") as HTMLTextAreaElement;
    const receive = (target: MessageTarget) => {
      if (target.chatKey !== manager.bridge.key() || !addonEnabled(host.prefs(), "image-gen")) return;
      setMode((previous) =>
        previous
          ? { ...previous, target }
          : { target, draft: input.value, start: input.selectionStart, end: input.selectionEnd },
      );
      input.value = "";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      host.focusInput();
    };
    const off = bus.on("image-input", receive);
    const anchor = document.createElement("div");
    anchor.className = "wb-image-input-anchor";
    input.before(anchor);
    setAnchor(anchor);
    return () => {
      off();
      anchor.remove();
    };
  }, [host, manager]);
  const cancel = () => {
    if (mode?.target.chatKey === manager.bridge.key()) {
      const input = document.getElementById("send_textarea") as HTMLTextAreaElement;
      input.value = mode.draft;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.setSelectionRange(mode.start, mode.end);
    }
    setMode(null);
    bus.emit("image-compose-end");
  };
  useEffect(() => {
    if (mode && (mode.target.chatKey !== manager.bridge.key() || !addonEnabled(host.prefs(), "image-gen"))) {
      if (mode.target.chatKey === manager.bridge.key()) cancel();
      else setMode(null);
    }
  }, [host.revision(), mode]);
  useEffect(() => {
    if (!mode) return;
    const input = document.getElementById("send_textarea") as HTMLTextAreaElement,
      placeholder = input.placeholder;
    input.placeholder = "输入生图提示词… 可拖入或粘贴参考图";
    const sendButton = document.getElementById("send_but")!,
      previousLabel = sendButton.getAttribute("aria-label");
    sendButton.setAttribute("aria-label", "生成图片");
    document.body.classList.add("wb-image-input-mode");
    bus.emit("image-compose");
    const send = (event: Event) => {
      const target = event.target as Element;
      if (event.type === "keydown") {
        const key = event as KeyboardEvent;
        if (target !== input || key.key !== "Enter" || key.shiftKey || key.isComposing) return;
      } else if (!target.closest?.("#send_but") && !(event.type === "submit" && target.closest("#send_form")))
        return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (host.snapshot().busy) {
        host.report("请等待当前回复完成后生图。");
        return;
      }
      if (manager.get("image-gen")?.state().referencesReading) {
        host.report("参考图正在读取，请稍候。");
        return;
      }
      const prompt = input.value.trim();
      if (!prompt) {
        host.focusInput();
        return;
      }
      const captured = mode.target;
      cancel();
      void manager
        .ensure("image-gen")
        .then((runtime) => runtime.action("generate", { target: captured, prompt, insert: true }))
        .catch((e) => host.report(e));
    };
    const files = async (event: ClipboardEvent | DragEvent) => {
      if (event.target !== input) return;
      const list = event instanceof ClipboardEvent ? event.clipboardData?.files : event.dataTransfer?.files;
      if (!list?.length) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const captured = modeRef.current,
        runtime = manager.get("image-gen");
      if (!runtime) return;
      await runtime.action("references-reading", true);
      try {
        const { readReference } = await import("../addons/image-gen/reference-files");
        const loaded = await Promise.all([...list].map(readReference));
        if (modeRef.current === captured)
          await runtime.action("references", [...runtime.state().references, ...loaded]);
      } catch (error) {
        host.report(error);
      } finally {
        await runtime.action("references-reading", false);
      }
    };
    const drag = (event: DragEvent) => {
      if (event.target === input && event.dataTransfer?.types.includes("Files")) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    document.addEventListener("paste", files, true);
    document.addEventListener("drop", files, true);
    document.addEventListener("dragover", drag, true);
    document.addEventListener("click", send, true);
    document.addEventListener("keydown", send, true);
    document.addEventListener("submit", send, true);
    return () => {
      document.removeEventListener("click", send, true);
      document.removeEventListener("keydown", send, true);
      document.removeEventListener("submit", send, true);
      input.placeholder = placeholder;
      previousLabel === null
        ? sendButton.removeAttribute("aria-label")
        : sendButton.setAttribute("aria-label", previousLabel);
      document.removeEventListener("paste", files, true);
      document.removeEventListener("drop", files, true);
      document.removeEventListener("dragover", drag, true);
      document.body.classList.remove("wb-image-input-mode");
      bus.emit("image-compose-end");
    };
  }, [mode, host, manager]);
  return mode && anchor
    ? createPortal(
        <>
          <div className="wb-image-input-label" title="手动生图 · 聊天草稿已暂存，退出后恢复">
            <ImagePlus size={17} />
            <span>生图</span>
            <small>第 {mode.target.id + 1} 层</small>
          </div>
          <Suspense fallback={null}>
            {manager.get("image-gen") && <References runtime={manager.get("image-gen")!} compact />}
          </Suspense>
          <div className="wb-image-input-actions">
            <button
              aria-label="打开生图工作区"
              title="查看生图结果"
              onClick={() => manager.api("image-gen").open("workspace")}
            >
              <Images size={17} />
            </button>
            <button aria-label="取消手动生图" title="退出生图 · 恢复聊天草稿" onClick={cancel}>
              <X size={18} />
            </button>
          </div>
        </>,
        anchor,
      )
    : null;
}
