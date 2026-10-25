import { useEffect, useState } from "react";
import { addonEnabled } from "../addons/catalog";
import type { HostAdapter } from "../host/adapter";
import { pinnableTools, pinnedTools, type NativeTool } from "../host/tools";
import { builtinTools } from "./ToolIcon";
import { useDatabase } from "./useDatabase";
/** Observe only the two native menus; avoid rescanning chat when a plugin updates a tool. */
export function useTools() {
  const [, update] = useState(0);
  useEffect(() => {
    let frame = 0;
    const observer = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => update((n) => n + 1));
    });
    for (const node of document.querySelectorAll("#options,#extensionsMenu"))
      observer.observe(node, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
        attributeFilter: [
          "class",
          "style",
          "disabled",
          "aria-disabled",
          "title",
          "id",
          "data-action",
          "data-command",
        ],
      });
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);
}
const generating = ["builtin:continue", "builtin:regenerate", "builtin:impersonate"];
/**
 * The composer's tools in order (built-ins, then the user's pinned native tools) and whether each
 * can run now. The desktop row, its overflow popover and the PWA tools sheet all read this; the
 * native menus are scanned at most once per render, and only when a pinned tool is asked about.
 */
export function useComposerTools(host: HostAdapter, busy: boolean) {
  useTools();
  const database = useDatabase(host),
    prefs = host.prefs();
  const tools = [
    ...builtinTools(database.available),
    ...pinnedTools(prefs.pinnedTools).filter(
      (tool) => tool.id !== "wb:export" || addonEnabled(prefs, "record-export"),
    ),
  ];
  let native: Map<string, NativeTool> | undefined;
  const disabled = (id: string) =>
    id.startsWith("builtin:")
      ? busy && generating.includes(id)
      : id !== "wb:export" && ((native ??= pinnableTools()).get(id)?.disabled ?? true);
  return { tools, disabled };
}
