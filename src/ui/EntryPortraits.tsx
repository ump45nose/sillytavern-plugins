import { useEffect, useRef, useState } from "react";
import { ImagePlus, LoaderCircle, RefreshCw, Trash2, X } from "./icons";
import type { HostAdapter } from "../host/adapter";
import { EXPRESSIONS, isPathSafe, stagedNotes, suggestLabel, type Sprite } from "../host/cast";

interface Staged {
  id: number;
  file: File;
  url: string;
  label: string;
}

const NOTES: Record<string, string> = {
  invalid: "需要小写英文表情名",
  repeat: "同批里重名",
  replace: "将替换",
  custom: "自定义",
};

const stemOf = (sprite: Sprite) =>
  decodeURIComponent(sprite.path.split("?")[0].split("/").pop()!).replace(/\.[^.]+$/, "");

/** Every image file under what was dropped, folders included. */
async function droppedFiles(items: DataTransferItemList) {
  const files: File[] = [];
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile)
      files.push(await new Promise<File>((ok, fail) => (entry as FileSystemFileEntry).file(ok, fail)));
    else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // A directory reader hands its entries over in batches until one comes back empty.
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((ok, fail) => reader.readEntries(ok, fail));
        if (!batch.length) break;
        for (const child of batch) await walk(child);
      }
    }
  };
  // Entries and files have to be taken while the drop event lasts; the walk can finish later.
  const pending = [...items].map((item) => {
    const entry = item.webkitGetAsEntry?.();
    if (entry) return walk(entry);
    const file = item.getAsFile();
    if (file) files.push(file);
  });
  await Promise.all(pending);
  return files.filter((file) => file.type.startsWith("image/"));
}

/**
 * The 立绘 tab of a world-book entry: the images in `characters/<book>/<entry>/`, named by
 * expression. New images wait in a list where their labels can be corrected before they go in.
 */
export function EntryPortraits({
  host,
  book,
  title,
  draftTitle,
}: {
  host: HostAdapter;
  book: string;
  /** The saved title: the folder's name. Empty while the entry is unsaved. */
  title: string;
  draftTitle: string;
}) {
  const [sprites, setSprites] = useState<Sprite[] | null>(null),
    [staged, setStaged] = useState<Staged[]>([]),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [over, setOver] = useState(false),
    [preview, setPreview] = useState<Sprite | null>(null),
    [removing, setRemoving] = useState(""),
    [relabel, setRelabel] = useState<{ path: string; label: string } | null>(null),
    next = useRef(0);
  const safe = isPathSafe(title);
  const reload = () => {
    if (!safe) return setSprites([]);
    let live = true;
    host.cast
      .sprites(book, title)
      .then((list) => live && setSprites(list))
      .catch((e) => live && setError(e.message));
    return () => {
      live = false;
    };
  };
  useEffect(() => {
    setSprites(null);
    setError("");
    setRemoving("");
    setRelabel(null);
    return reload();
  }, [book, title]);
  useEffect(() => () => staged.forEach((item) => URL.revokeObjectURL(item.url)), []);
  useEffect(() => {
    if (!preview) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setPreview(null);
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [preview]);
  const work = async (label: string, job: () => Promise<unknown>) => {
    setBusy(label);
    setError("");
    try {
      await job();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
      reload();
    }
  };
  const stage = (files: File[]) => {
    if (!files.length) return;
    setStaged((old) => [
      ...old,
      ...files.map((file) => ({
        id: next.current++,
        file,
        url: URL.createObjectURL(file),
        label: suggestLabel(file.name),
      })),
    ]);
  };
  const unstage = (id: number) =>
    setStaged((old) => {
      const item = old.find((x) => x.id === id);
      if (item) URL.revokeObjectURL(item.url);
      return old.filter((x) => x.id !== id);
    });

  if (!title) return <p className="wb-portraits-note">先保存这个条目，再为它添加立绘。</p>;
  if (!safe)
    return (
      <p className="wb-portraits-note is-warning">
        标题「{title}」含 / \ : * ? " &lt; &gt; |
        或首尾的点、空格，不能作为立绘文件夹名。改名并保存后即可添加。
      </p>
    );

  const notes = stagedNotes(
      staged.map((item) => item.label),
      (sprites ?? []).map(stemOf),
    ),
    blocked = notes.some((note) => note === "invalid" || note === "repeat"),
    labels = new Set((sprites ?? []).map((sprite) => sprite.label));
  const upload = () =>
    work("upload", async () => {
      // One at a time, so each that went in leaves the list and a failure names its file.
      for (const [i, item] of [...staged].entries()) {
        setBusy(`upload:${i + 1}/${staged.length}`);
        await host.cast.upload(book, title, [
          { file: item.file, fileName: item.file.name, label: item.label },
        ]);
        unstage(item.id);
      }
    });
  return (
    <div
      className={`wb-portraits ${over ? "is-over" : ""}`}
      onDragOver={(e) => {
        if (![...e.dataTransfer.types].includes("Files")) return;
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        void droppedFiles(e.dataTransfer.items).then(stage);
      }}
    >
      <p className="wb-portraits-note">
        {sprites === null
          ? "正在读取立绘…"
          : !sprites.length
            ? "还没有立绘。文件名就是表情：joy.png、anger.webp；可以多选，也可以把整个文件夹拖进来。"
            : `${sprites.length} 张 · ${labels.has("neutral") ? "有 neutral" : "没有 neutral：没标表情的段落会用第一张"}`}
        {draftTitle.trim() !== title && (
          <strong> 保存后，立绘会随条目改名移到「{draftTitle.trim() || "新名称"}」。</strong>
        )}
      </p>
      {error && <p className="wb-portraits-note is-error">{error}</p>}
      <ul className="wb-portraits-grid" aria-label="立绘">
        {(sprites ?? []).map((sprite) => {
          const stem = stemOf(sprite),
            editing = relabel?.path === sprite.path;
          return (
            <li key={sprite.path}>
              <button
                className="wb-portraits-thumb"
                aria-label={`预览 ${stem}`}
                onClick={() => setPreview(sprite)}
              >
                <img src={sprite.path} alt="" loading="lazy" />
              </button>
              {editing && relabel ? (
                <input
                  className="wb-portraits-label"
                  aria-label={`${stem} 的新表情名`}
                  autoFocus
                  value={relabel.label}
                  onChange={(e) => setRelabel({ path: sprite.path, label: e.target.value.toLowerCase() })}
                  onBlur={() => setRelabel(null)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setRelabel(null);
                    if (e.key !== "Enter" || e.nativeEvent.isComposing) return;
                    e.preventDefault();
                    const label = relabel.label.trim();
                    setRelabel(null);
                    if (label && label !== sprite.label)
                      void work(sprite.path, () => host.cast.relabel(book, title, sprite, label));
                  }}
                />
              ) : (
                <button
                  className="wb-portraits-label"
                  aria-label={`改 ${stem} 的表情名`}
                  title="改表情名"
                  onClick={() => setRelabel({ path: sprite.path, label: sprite.label })}
                >
                  {stem}
                </button>
              )}
              <div className="wb-portraits-actions">
                <label className="wb-portraits-icon" title="替换图片">
                  <input
                    type="file"
                    accept="image/*"
                    hidden
                    aria-label={`替换 ${stem}`}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = "";
                      if (file)
                        void work(sprite.path, () =>
                          host.cast.upload(book, title, [
                            { file, fileName: file.name, label: sprite.label, stem },
                          ]),
                        );
                    }}
                  />
                  <RefreshCw size={12} />
                </label>
                <button
                  className={`wb-portraits-icon ${removing === sprite.path ? "is-confirm" : ""}`}
                  aria-label={removing === sprite.path ? `确认删除 ${stem}` : `删除 ${stem}`}
                  title={removing === sprite.path ? "再点一次删除" : "删除"}
                  onBlur={() => setRemoving("")}
                  onClick={() =>
                    removing === sprite.path
                      ? void work(sprite.path, () => host.cast.remove(book, title, sprite))
                      : setRemoving(sprite.path)
                  }
                >
                  {removing === sprite.path ? <span>删除</span> : <Trash2 size={13} />}
                </button>
              </div>
              {busy === sprite.path && <LoaderCircle className="wb-portraits-spin" size={16} />}
            </li>
          );
        })}
        <li className="wb-portraits-add">
          <label>
            <input
              type="file"
              accept="image/*"
              multiple
              hidden
              aria-label="添加立绘"
              onChange={(e) => {
                const files = [...(e.target.files || [])];
                e.target.value = "";
                stage(files);
              }}
            />
            <ImagePlus size={18} />
            <span>添加</span>
          </label>
        </li>
      </ul>
      {!!staged.length && (
        <section className="wb-portraits-staged" aria-label="待上传">
          <ul>
            {staged.map((item, i) => (
              <li key={item.id} className={notes[i] ? `is-${notes[i]}` : ""}>
                <img src={item.url} alt="" />
                <span className="wb-portraits-file" title={item.file.name}>
                  {item.file.name}
                </span>
                <input
                  aria-label={`${item.file.name} 的表情名`}
                  value={item.label}
                  list="wb-portraits-expressions"
                  onChange={(e) =>
                    setStaged((old) =>
                      old.map((x) =>
                        x.id === item.id ? { ...x, label: e.target.value.trim().toLowerCase() } : x,
                      ),
                    )
                  }
                />
                <small>{NOTES[notes[i]] ?? ""}</small>
                <button
                  className="wb-portraits-icon"
                  aria-label={`移出 ${item.file.name}`}
                  onClick={() => unstage(item.id)}
                >
                  <X size={12} />
                </button>
              </li>
            ))}
          </ul>
          <footer>
            <button
              onClick={() => {
                staged.forEach((item) => URL.revokeObjectURL(item.url));
                setStaged([]);
              }}
              disabled={!!busy}
            >
              清空
            </button>
            <button className="is-primary" disabled={blocked || !!busy} onClick={() => void upload()}>
              {busy.startsWith("upload:") ? `上传中 ${busy.slice(7)}` : `上传 ${staged.length} 张`}
            </button>
          </footer>
        </section>
      )}
      <datalist id="wb-portraits-expressions">
        {EXPRESSIONS.map((label) => (
          <option key={label} value={label} />
        ))}
      </datalist>
      {over && <div className="wb-portraits-drop">松开以添加立绘</div>}
      {preview && (
        <div
          className="wb-portraits-preview"
          role="dialog"
          aria-label={`立绘 ${stemOf(preview)}`}
          onClick={() => setPreview(null)}
        >
          <img src={preview.path} alt="" />
          <span>{stemOf(preview)}</span>
        </div>
      )}
    </div>
  );
}
