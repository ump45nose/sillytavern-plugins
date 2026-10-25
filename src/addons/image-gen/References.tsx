import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ImagePlus, X } from "../../ui/icons";
import type { AddonRuntime } from "../types";
import { readReference, referenceLimit, type ImageReference } from "./reference-files";
export default function References({
  runtime,
  compact = false,
}: {
  runtime: AddonRuntime;
  compact?: boolean;
}) {
  useSyncExternalStore(runtime.subscribe, runtime.revision);
  const refs = runtime.state().references as ImageReference[],
    [error, setError] = useState(""),
    [reading, setReading] = useState(false),
    input = useRef<HTMLInputElement>(null),
    alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const add = async (files: File[]) => {
    if (reading) return;
    setError("");
    setReading(true);
    await runtime.action("references-reading", true);
    try {
      if (runtime.state().references.length + files.length > referenceLimit)
        throw new Error("最多插入 4 张参考图。");
      const loaded = await Promise.all(files.map(readReference));
      if (alive.current) await runtime.action("references", [...runtime.state().references, ...loaded]);
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      await runtime.action("references-reading", false);
      if (alive.current) setReading(false);
    }
  };
  return (
    <div
      className={`wb-image-references ${compact ? "is-compact" : ""}`}
      aria-label="生图参考图"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) e.preventDefault();
      }}
      onDrop={(e) => {
        if (e.dataTransfer.files.length) {
          e.preventDefault();
          e.stopPropagation();
          void add([...e.dataTransfer.files]);
        }
      }}
      onPaste={(e) => {
        const files = [...e.clipboardData.files].filter((f) => f.type.startsWith("image/"));
        if (files.length) {
          e.preventDefault();
          e.stopPropagation();
          void add(files);
        }
      }}
    >
      <input
        ref={input}
        hidden
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        aria-label="选择生图参考图"
        disabled={reading}
        onChange={(e) => {
          void add([...(e.target.files || [])]);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        aria-label="插入参考图"
        title={reading ? "正在读取参考图…" : "插入参考图 · 也可拖入或粘贴"}
        disabled={reading || refs.length >= referenceLimit}
        onClick={() => input.current?.click()}
      >
        <ImagePlus size={compact ? 17 : 15} />
        {!compact && (reading ? "读取中…" : "插入参考图")}
      </button>
      {!compact && !refs.length && <small>可拖入或粘贴图片</small>}
      <div className="wb-image-reference-list">
        {refs.map((ref, i) => (
          <figure key={ref.id}>
            <img src={ref.dataUrl} alt={`参考图 ${i + 1}：${ref.name}`} />
            <button
              type="button"
              aria-label={`移除参考图 ${i + 1}`}
              onClick={() =>
                void runtime.action(
                  "references",
                  refs.filter((r) => r.id !== ref.id),
                )
              }
            >
              <X size={12} />
            </button>
          </figure>
        ))}
      </div>
      {!!error && <p role="alert">{error}</p>}
    </div>
  );
}
