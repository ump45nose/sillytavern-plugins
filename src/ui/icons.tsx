// The workbench icon set (design boards "Noval 工作台 v2"): 24-unit outline drawings with a 1.7
// stroke and round joins. Each export keeps the lucide name it replaces, so call sites keep their
// props (size, strokeWidth, className, aria-*). Icons the boards do not draw stay lucide, thinned
// to the same stroke so the set reads as one family.
import React, { forwardRef } from "react";
import * as Lucide from "lucide-react";
import type { LucideProps } from "lucide-react";

type IconProps = LucideProps;
const drawn = (name: string, d: string) => {
  const Icon = forwardRef<SVGSVGElement, IconProps>(
    (
      { size = 24, strokeWidth = 1.7, color = "currentColor", className, absoluteStrokeWidth, ...rest },
      ref,
    ) => (
      <svg
        ref={ref}
        xmlns="http://www.w3.org/2000/svg"
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke={color}
        strokeWidth={absoluteStrokeWidth ? (Number(strokeWidth) * 24) / Number(size) : strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden={rest["aria-label"] ? undefined : true}
        className={`wb-i wb-i-${name}${className ? " " + className : ""}`}
        {...rest}
      >
        <path d={d} />
      </svg>
    ),
  );
  Icon.displayName = name;
  return Icon;
};
const thin = (name: string, Base: React.ComponentType<IconProps>) => {
  const Icon = forwardRef<SVGSVGElement, IconProps>(({ strokeWidth = 1.7, ...rest }, ref) => (
    <Base ref={ref as never} strokeWidth={strokeWidth} {...rest} />
  ));
  Icon.displayName = name;
  return Icon;
};

const paths = {
  aihelp: "M10 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM3 21a7 7 0 0 1 9.5-6.5M17.5 13.5l3 3-5 5h-3v-3z",
  arrowR: "M5 12h14M13 6l6 6-6 6",
  book: "M2 5h7a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H2zM22 5h-7a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h8z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  clip: "M20.5 11.5l-8.2 8.2a5 5 0 0 1-7-7l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  dl: "M12 3v12M7 10l5 5 5-5M4 17v3h16v-3",
  down: "M6 9l6 6 6-6",
  expand: "M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7",
  exportf: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M9 15h6M12 12l3 3-3 3",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  eyeoff:
    "M3 3l18 18M10.6 6.1A10 10 0 0 1 12 6c6 0 9.5 6 9.5 6a16 16 0 0 1-2.8 3.4M6.6 6.6A16 16 0 0 0 2.5 12s3.5 6 9.5 6a9.6 9.6 0 0 0 4.4-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2",
  focus: "M4 9V5h4M16 5h4v4M20 15v4h-4M8 19H4v-4",
  folder:
    "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2.5v3M12 18.5v3M4.6 4.6l2.1 2.1M17.3 17.3l2.1 2.1M2.5 12h3M18.5 12h3M4.6 19.4l2.1-2.1M17.3 6.7l2.1-2.1",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  grip: "M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
  image: "M4 5h16v14H4zM4 16l5-5 5 5M14 14l2-2 4 4M15.5 9h.01",
  importf: "M12 3v12M7 10l5 5 5-5M4 17v3h16v-3",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
  key: "M15 7a4 4 0 1 1-3.9 4.9L4 19v2h3v-2h2v-2h2l1.1-1.1A4 4 0 0 1 15 7zM16 9.5h.01",
  keyboard: "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M17 10h.01M7 14h10",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  left: "M15 6l-6 6 6 6",
  mask: "M4 4h16v7a8 8 0 0 1-16 0zM9 9.5h.01M15 9.5h.01M9.5 14.5a3.5 2.5 0 0 0 5 0",
  menu: "M4 6h16M4 12h16M4 18h16",
  drawer: "M4 7h16M4 12h10M4 17h16",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  native: "M3 4h18v16H3zM9 4v16",
  layout: "M3 4h18v16H3zM3 14h18",
  newchat: "M20 11.5a8 8 0 0 1-11.8 7L3 20l1.5-5A8 8 0 1 1 20 11.5zM12 8.5v6M9 11.5h6",
  outline: "M4 5h7M8 12h7M8 19h7M4 5v14M4 12h4M4 19h4",
  pause: "M8 5v14M16 5v14",
  pencil: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  persona: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 21a7.5 7.5 0 0 1 15 0",
  pin: "M12 17v5M9 3h6l-1 5 3 4H7l3-4z",
  pin2: "M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11zM12 12a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  play: "M7 4.5l12 7.5-12 7.5z",
  plug: "M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5",
  plus: "M12 5v14M5 12h14",
  puzzle: "M10 4a2 2 0 1 1 4 0v2h4v4h-2a2 2 0 1 0 0 4h2v4h-4v-2a2 2 0 1 0-4 0v2H6v-4h2a2 2 0 1 0 0-4H6V6h4z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  reply: "M21 14.5a2 2 0 0 1-2 2H8l-5 4v-15a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 12.5h5",
  right: "M9 6l6 6-6 6",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM20 20l-4-4",
  sliders: "M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1M15 4v4M9 10v4M17 16v4",
  spark:
    "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  spin: "M12 3a9 9 0 1 0 9 9",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
  stop: "M6 6h12v12H6z",
  sun: "M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  trace: "M3 12h4l3-8 4 16 3-8h4",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  type: "M5 7V5h14v2M12 5v14M9 19h6",
  up: "M12 19V5M5 12l7-7 7 7",
  users:
    "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M16 3.3a4 4 0 0 1 0 7.4M18 14.2A7 7 0 0 1 22 21",
  voice: "M12 3v18M8 7v10M4 10v4M16 7v10M20 10v4",
  wand: "M15 4V2M15 10V8M11 6h2M17 6h2M3 21l12-12M18.5 12.5l1 1M20 10l1.5-.5",
  world: "M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5zM5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3M9 7h6",
  x: "M6 6l12 12M18 6L6 18",
} as const;

export const Activity = drawn("trace", paths.trace);
export const ArrowRight = drawn("arrowR", paths.arrowR);
export const ArrowUp = drawn("up", paths.up);
export const BookMarked = drawn("world", paths.world);
export const BookOpen = drawn("book", paths.book);
export const Check = drawn("check", paths.check);
export const ChevronDown = drawn("down", paths.down);
export const ChevronLeft = drawn("left", paths.left);
export const ChevronRight = drawn("right", paths.right);
export const CloudSun = drawn("sun", paths.sun);
export const Copy = drawn("copy", paths.copy);
export const Download = drawn("dl", paths.dl);
export const Ellipsis = drawn("more", paths.more);
export const Expand = drawn("expand", paths.expand);
export const Eye = drawn("eye", paths.eye);
export const EyeOff = drawn("eyeoff", paths.eyeoff);
export const FileOutput = drawn("exportf", paths.exportf);
export const Folder = drawn("folder", paths.folder);
export const FolderOpen = drawn("folder", paths.folder);
export const Grid2X2 = drawn("grid", paths.grid);
export const GripVertical = drawn("grip", paths.grip);
export const History = drawn("history", paths.history);
export const Image = drawn("image", paths.image);
export const ImagePlus = drawn("image", paths.image);
export const Info = drawn("info", paths.info);
export const KeyRound = drawn("key", paths.key);
export const Keyboard = drawn("keyboard", paths.keyboard);
export const Layers = drawn("layers", paths.layers);
export const ListTree = drawn("outline", paths.outline);
export const LoaderCircle = drawn("spin", paths.spin);
export const MapPin = drawn("pin2", paths.pin2);
export const Maximize2 = drawn("expand", paths.expand);
export const Menu = drawn("menu", paths.menu);
export const MenuDrawer = drawn("drawer", paths.drawer);
export const MessageSquarePlus = drawn("newchat", paths.newchat);
export const MessagesSquare = drawn("reply", paths.reply);
export const MoreHorizontal = drawn("more", paths.more);
export const PanelBottom = drawn("layout", paths.layout);
export const PanelsTopLeft = drawn("native", paths.native);
export const Paperclip = drawn("clip", paths.clip);
export const Pause = drawn("pause", paths.pause);
export const PencilLine = drawn("pencil", paths.pencil);
export const Pin = drawn("pin", paths.pin);
export const Play = drawn("play", paths.play);
export const Plug = drawn("plug", paths.plug);
export const PlugZap = drawn("plug", paths.plug);
export const Plus = drawn("plus", paths.plus);
export const Puzzle = drawn("puzzle", paths.puzzle);
export const RefreshCw = drawn("refresh", paths.refresh);
export const RotateCcw = drawn("refresh", paths.refresh);
export const ScanLine = drawn("focus", paths.focus);
export const Search = drawn("search", paths.search);
export const Settings = drawn("gear", paths.gear);
export const SlidersHorizontal = drawn("sliders", paths.sliders);
export const Sparkles = drawn("spark", paths.spark);
export const Square = drawn("stop", paths.stop);
export const Star = drawn("star", paths.star);
export const Theater = drawn("mask", paths.mask);
export const Trash2 = drawn("trash", paths.trash);
export const Type = drawn("type", paths.type);
export const Upload = drawn("importf", paths.importf);
export const UserRound = drawn("persona", paths.persona);
export const UserRoundPen = drawn("aihelp", paths.aihelp);
export const Users = drawn("users", paths.users);
export const UsersRound = drawn("users", paths.users);
export const Volume2 = drawn("voice", paths.voice);
export const WandSparkles = drawn("wand", paths.wand);
export const X = drawn("x", paths.x);

export const ArrowDown = thin("ArrowDown", Lucide.ArrowDown);
export const ArrowDownToLine = thin("ArrowDownToLine", Lucide.ArrowDownToLine);
export const ArrowLeft = thin("ArrowLeft", Lucide.ArrowLeft);
export const ArrowRightLeft = thin("ArrowRightLeft", Lucide.ArrowRightLeft);
export const ArrowUpRight = thin("ArrowUpRight", Lucide.ArrowUpRight);
export const Binary = thin("Binary", Lucide.Binary);
export const Bookmark = thin("Bookmark", Lucide.Bookmark);
export const BookmarkPlus = thin("BookmarkPlus", Lucide.BookmarkPlus);
export const Braces = thin("Braces", Lucide.Braces);
export const Captions = thin("Captions", Lucide.Captions);
export const ChartNoAxesColumn = thin("ChartNoAxesColumn", Lucide.ChartNoAxesColumn);
export const CornerDownRight = thin("CornerDownRight", Lucide.CornerDownRight);
export const Database = thin("Database", Lucide.Database);
export const FilePlus = thin("FilePlus", Lucide.FilePlus);
export const FileText = thin("FileText", Lucide.FileText);
export const Flag = thin("Flag", Lucide.Flag);
export const FlaskConical = thin("FlaskConical", Lucide.FlaskConical);
export const FolderPlus = thin("FolderPlus", Lucide.FolderPlus);
export const GitBranch = thin("GitBranch", Lucide.GitBranch);
export const Images = thin("Images", Lucide.Images);
export const Languages = thin("Languages", Lucide.Languages);
export const Paintbrush = thin("Paintbrush", Lucide.Paintbrush);
export const FastForward = thin("FastForward", Lucide.FastForward);
export const Lightbulb = thin("Lightbulb", Lucide.Lightbulb);
export const Link = thin("Link", Lucide.Link);
export const ListMinus = thin("ListMinus", Lucide.ListMinus);
export const Lock = thin("Lock", Lucide.Lock);
export const LockOpen = thin("LockOpen", Lucide.LockOpen);
export const MessageSquare = thin("MessageSquare", Lucide.MessageSquare);
export const MessageSquareX = thin("MessageSquareX", Lucide.MessageSquareX);
export const Minimize2 = thin("Minimize2", Lucide.Minimize2);
export const Minus = thin("Minus", Lucide.Minus);
export const NotebookPen = thin("NotebookPen", Lucide.NotebookPen);
export const PanelLeftClose = thin("PanelLeftClose", Lucide.PanelLeftClose);
export const PanelLeftOpen = thin("PanelLeftOpen", Lucide.PanelLeftOpen);
export const PanelRightClose = thin("PanelRightClose", Lucide.PanelRightClose);
export const PinOff = thin("PinOff", Lucide.PinOff);
export const RotateCw = thin("RotateCw", Lucide.RotateCw);
export const Save = thin("Save", Lucide.Save);
export const Scissors = thin("Scissors", Lucide.Scissors);
export const ScrollText = thin("ScrollText", Lucide.ScrollText);
export const Send = thin("Send", Lucide.Send);
export const Settings2 = thin("Settings2", Lucide.Settings2);
export const SquareArrowOutUpRight = thin("SquareArrowOutUpRight", Lucide.SquareArrowOutUpRight);
export const Tag = thin("Tag", Lucide.Tag);
export const TextCursorInput = thin("TextCursorInput", Lucide.TextCursorInput);
export const TextSearch = thin("TextSearch", Lucide.TextSearch);
export const Table2 = thin("Table2", Lucide.Table2);

export type { LucideIcon, LucideProps } from "lucide-react";
