import {
  Binary,
  Bookmark,
  Braces,
  Captions,
  ChevronRight,
  Database,
  FileOutput,
  Image,
  Languages,
  Lightbulb,
  MessagesSquare,
  NotebookPen,
  Paperclip,
  Play,
  Puzzle,
  RotateCcw,
  Table2,
  ScrollText,
  SlidersHorizontal,
  TextSearch,
  UserRoundPen,
  Volume2,
} from "./icons";
import { actionLabels } from "../host/labels";
export const composerTools = [
  { id: "builtin:continue", label: actionLabels.continue },
  { id: "builtin:regenerate", label: actionLabels.regenerate },
  { id: "builtin:quick", label: "快速回复" },
  { id: "builtin:impersonate", label: actionLabels.impersonate },
  { id: "builtin:attachment", label: "附件" },
  { id: "builtin:options", label: "剧情选项" },
  { id: "builtin:database", label: "数据库" },
];
/** The built-in tools on screen: 数据库 only while its plug-in is installed. */
export const builtinTools = (database: boolean) =>
  composerTools.filter((tool) => tool.id !== "builtin:database" || database);
export function toolIcon(id: string, label = "") {
  if (id === "builtin:continue") return Play;
  if (id === "builtin:regenerate") return RotateCcw;
  if (id === "builtin:quick") return MessagesSquare;
  if (id === "builtin:impersonate") return UserRoundPen;
  if (id === "builtin:options") return Lightbulb;
  if (id === "builtin:database") return Table2;
  if (id === "wb:export") return FileOutput;
  const key = (id + " " + label).toLowerCase();
  if (/bank|manageattachments/.test(key)) return Database;
  return /toggle_an|作者注释/.test(key)
    ? NotebookPen
    : /cfg|logprobs/.test(key)
      ? SlidersHorizontal
      : /new_bookmark/.test(key)
        ? Bookmark
        : /back_to_main/.test(key)
          ? ChevronRight
          : /attach|file/.test(key)
            ? Paperclip
            : /caption/.test(key)
              ? Captions
              : /sd_gen|image|gallery/.test(key)
                ? Image
                : /tts|narrate/.test(key)
                  ? Volume2
                  : /translate/.test(key)
                    ? Languages
                    : /token/.test(key)
                      ? Binary
                      : /prompt|提示词/.test(key)
                        ? TextSearch
                        : /variable|变量/.test(key)
                          ? Braces
                          : /日志|log/.test(key)
                            ? ScrollText
                            : Puzzle;
}
