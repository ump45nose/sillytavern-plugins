import { useEffect, useLayoutEffect, useRef } from "react";
import type { HostAdapter } from "../host/adapter";
import type { HostSnapshot } from "../host/types";
import { speakerCss, speakerKey } from "./speakerColors";

/** Keeps one stylesheet in sync with the speaker colors and the names they apply to. */
export function useSpeakerColors(host: HostAdapter, snap: HostSnapshot) {
  const colors = host.prefs().speakerColors;
  const css = colors ? speakerCss(colors, snap.characters, snap.resources.persona) : "";
  useLayoutEffect(() => {
    if (!css) return;
    const style = document.createElement("style");
    style.id = "wb-speaker-colors";
    style.textContent = css;
    document.head.append(style);
    return () => style.remove();
  }, [css]);
}

/** A speaker's dialogue color; saved at once as a workbench preference, apart from the card or persona draft. */
export function SpeakerColor({
  host,
  kind,
  id,
}: {
  host: HostAdapter;
  kind: "character" | "persona";
  id: string;
}) {
  const key = speakerKey(kind, id),
    colors = host.prefs().speakerColors ?? {},
    value = colors[key];
  const set = (color?: string) => {
    const next = { ...colors };
    if (color) next[key] = color;
    else delete next[key];
    host.preference({ speakerColors: next });
  };
  // The picker reports every drag step as input; only its closing change is saved.
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const node = input.current!,
      commit = () => set(node.value);
    node.addEventListener("change", commit);
    return () => node.removeEventListener("change", commit);
  });
  return (
    <span className="wb-speaker-color">
      <input
        ref={input}
        key={value ?? ""}
        type="color"
        aria-label="对白颜色"
        defaultValue={value ?? "#8a6d3b"}
      />
      {value ? (
        <button type="button" onClick={() => set()}>
          清除
        </button>
      ) : (
        <small>跟随主题</small>
      )}
    </span>
  );
}
