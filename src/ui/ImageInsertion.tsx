import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { HostAdapter } from "../host/adapter";
import type { MessageTarget } from "../addons/types";
import type { ImageResult } from "../addons/image-gen/runtime";
import { addonManager } from "../addons/runtime";
import { bus } from "../host/bus";
import { Copy, Images, Upload } from "./icons";
import { Popover } from "./Popover";

export function beginImageInsert(host: HostAdapter, id: number, anchor: HTMLElement) {
  try {
    bus.emit("image-insert", { target: addonManager(host).bridge.target(id), anchor });
  } catch (error) {
    host.report(error);
  }
}

/** Capture the floor before lazy loading or opening a file/clipboard picker. */
export async function insertImageFiles(host: HostAdapter, target: MessageTarget, files: File[]) {
  const manager = addonManager(host),
    runtime = await manager.ensure("image-gen");
  if (!manager.bridge.valid(target)) throw new Error("目标楼层已改变，请重新选择插入位置。");
  await runtime.action("import", files, target);
}

export function clipboardImages(data: DataTransfer | null) {
  return [...(data?.files || [])].filter((file) => file.type.startsWith("image/"));
}

export function ImageInsertion({ host }: { host: HostAdapter }) {
  const manager = addonManager(host);
  useSyncExternalStore(manager.subscribe, manager.revision);
  const [selection, setSelection] = useState<{ target: MessageTarget; anchor: HTMLElement } | null>(null),
    [error, setError] = useState(""),
    [working, setWorking] = useState(false),
    [dragging, setDragging] = useState(false),
    file = useRef<HTMLInputElement>(null),
    pasteArea = useRef<HTMLDivElement>(null),
    current = useRef(selection);
  current.current = selection;
  useEffect(
    () =>
      bus.on("image-insert", (next) => {
        setError("");
        setDragging(false);
        setSelection(next);
        void manager.ensure("image-gen").catch((error) => {
          if (current.current === next) setError(error.message);
        });
      }),
    [manager],
  );
  useEffect(() => {
    if (selection && selection.target.chatKey !== manager.bridge.key()) setSelection(null);
  }, [selection, manager, host.revision()]);
  if (!selection) return null;
  const captured = selection,
    runtime = manager.get("image-gen"),
    task = runtime?.task(),
    disabled = working || host.snapshot().busy || task?.status === "running";
  const run = async (action: () => Promise<unknown>) => {
    if (disabled) return;
    setError("");
    setWorking(true);
    try {
      await action();
    } catch (error) {
      if (current.current === captured) setError(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  };
  const insertFiles = (files: File[]) => run(() => insertImageFiles(host, captured.target, files));
  return (
    <Popover
      anchor={selection.anchor}
      title={`在第 ${selection.target.id + 1} 层后插入图片`}
      className="wb-image-insert-menu"
      onClose={() => setSelection(null)}
    >
      <div className="wb-image-insert-body" aria-busy={disabled}>
        <div className="wb-image-insert-actions">
          <button disabled={disabled} onClick={() => file.current?.click()}>
            <Upload size={16} />
            选择图片
          </button>
          <button
            disabled={disabled}
            onClick={() =>
              void run(async () => {
                if (!navigator.clipboard?.read) {
                  pasteArea.current?.focus();
                  throw new Error("请在下方粘贴区按 Ctrl+V 或 ⌘+V 粘贴图片。");
                }
                let items: ClipboardItem[];
                try {
                  items = await navigator.clipboard.read();
                } catch {
                  pasteArea.current?.focus();
                  throw new Error("请在下方粘贴区按 Ctrl+V 或 ⌘+V，或选择本地图片。");
                }
                const files: File[] = [];
                for (const item of items) {
                  const type = item.types.find((type) =>
                    ["image/png", "image/jpeg", "image/webp"].includes(type),
                  );
                  if (type) files.push(new File([await item.getType(type)], "粘贴图片", { type }));
                }
                if (!files.length) throw new Error("剪贴板里没有图片。");
                await insertImageFiles(host, captured.target, files);
              })
            }
          >
            <Copy size={16} />
            粘贴图片
          </button>
          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            hidden
            aria-label="选择插入图片"
            onChange={(event) => {
              const files = [...(event.currentTarget.files || [])];
              event.currentTarget.value = "";
              if (files.length) void insertFiles(files);
            }}
          />
        </div>
        <div
          ref={pasteArea}
          className={`wb-image-paste-area ${dragging && !disabled ? "is-dragging" : ""}`}
          tabIndex={0}
          role="group"
          aria-label="粘贴或拖入图片"
          aria-disabled={disabled}
          onClick={() => pasteArea.current?.focus()}
          onPaste={(event) => {
            const files = clipboardImages(event.clipboardData);
            if (!files.length) return;
            event.preventDefault();
            event.stopPropagation();
            void insertFiles(files);
          }}
          onDragOver={(event) => {
            if (event.dataTransfer.types.some((type) => ["Files", "application/x-wb-image"].includes(type))) {
              event.preventDefault();
              event.dataTransfer.dropEffect = disabled ? "none" : "copy";
              setDragging(!disabled);
            }
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
          }}
          onDrop={(event) => {
            setDragging(false);
            const files = clipboardImages(event.dataTransfer),
              result = event.dataTransfer.getData("application/x-wb-image");
            if (!files.length && !result) return;
            event.preventDefault();
            event.stopPropagation();
            if (files.length) void insertFiles(files);
            else
              void run(async () => {
                const runtime = await manager.ensure("image-gen");
                await runtime.action("insert", JSON.parse(result).id, captured.target);
              });
          }}
        >
          <Images size={22} />
          <span>在此粘贴或拖入图片</span>
          <small className="wb-image-paste-shortcut">Ctrl + V / ⌘ + V</small>
          <small>PNG、JPEG、WebP · 每张不超过 8 MB</small>
        </div>
        {!!runtime?.state().results.length && (
          <section className="wb-image-insert-library" aria-label="已有图片">
            <h3>
              已有图片 <span>{runtime.state().results.length}</span>
            </h3>
            <div className="wb-image-insert-results" aria-label="已有图片">
              {(runtime.state().results as ImageResult[]).map((result) => (
                <button
                  key={result.id}
                  disabled={disabled}
                  title={result.name || result.positive || "图片"}
                  aria-label={`插入${result.name || "已有图片"}`}
                  onClick={() => void run(() => runtime.action("insert", result.id, captured.target))}
                >
                  <img src={result.url} alt={result.name || result.positive.slice(0, 100)} loading="lazy" />
                </button>
              ))}
            </div>
          </section>
        )}
        {error && (
          <p className="wb-image-insert-error" role="alert">
            {error}
          </p>
        )}
        {task?.label && (
          <p className="wb-image-insert-status" role="status">
            {task.label}
          </p>
        )}
      </div>
    </Popover>
  );
}
