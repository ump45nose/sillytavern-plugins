import { Binary, Bookmark, Braces, Captions, ChevronRight, Database, FileOutput, Image, Languages, MessagesSquare, NotebookPen, Paperclip, Play, Puzzle, RotateCcw, ScrollText, SlidersHorizontal, TextSearch, UserRoundPen, Volume2 } from "lucide-react";
export const composerTools = [
  { id: "builtin:continue", label: "续写" }, { id: "builtin:regenerate", label: "重生成" },
  { id: "builtin:quick", label: "快速回复" }, { id: "builtin:impersonate", label: "AI 帮答" }, { id: "builtin:attachment", label: "附件" },
];
export function toolIcon(id: string, label = "") {
  if (id === "builtin:continue") return Play;
  if (id === "builtin:regenerate") return RotateCcw;
  if (id === "builtin:quick") return MessagesSquare;
  if (id === "builtin:impersonate") return UserRoundPen;
  if (id === "wb:export") return FileOutput;
  const key = (id + " " + label).toLowerCase();
  if (/bank|manageattachments/.test(key)) return Database;
  return /toggle_an|作者注释/.test(key) ? NotebookPen : /cfg|logprobs/.test(key) ? SlidersHorizontal : /new_bookmark/.test(key) ? Bookmark : /back_to_main/.test(key) ? ChevronRight :
    /attach|file/.test(key) ? Paperclip : /caption/.test(key) ? Captions : /sd_gen|image|gallery/.test(key) ? Image : /tts|narrate/.test(key) ? Volume2 :
    /translate/.test(key) ? Languages : /token/.test(key) ? Binary : /prompt|提示词/.test(key) ? TextSearch : /variable|变量/.test(key) ? Braces : /日志|log/.test(key) ? ScrollText : Puzzle;
}
