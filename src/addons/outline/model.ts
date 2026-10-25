import { randomId } from "../../host/ids";
export type Status = "todo" | "active" | "done";
export interface OutlineNode {
  id: string;
  parent: string | null;
  title: string;
  content: string;
  status: Status;
  rounds: number;
  completed: number;
}
export interface OutlineData {
  version: 1;
  nodes: OutlineNode[];
  selected: string;
  settings: {
    mode: "replace" | "caret";
    send: boolean;
    /** Whether the current node also goes into every prompt, `depth` messages from the end. */
    inject: { enabled: boolean; depth: number };
  };
  job?: {
    queue: string[];
    index: number;
  };
}
export const emptyOutline = (): OutlineData => ({
  version: 1,
  nodes: [],
  selected: "",
  settings: { mode: "caret", send: false, inject: { enabled: false, depth: 4 } },
});
export function normalizeOutline(value: any): OutlineData {
  if (!value || !Array.isArray(value.nodes)) return emptyOutline();
  if (value.nodes.length > 2000) throw new Error("大纲最多支持 2000 个节点。");
  const ids = new Set<string>();
  const nodes: OutlineNode[] = value.nodes.map((node: any) => {
    const id = String(node.id || "");
    if (!id || ids.has(id)) throw new Error("节点标识为空或重复。");
    ids.add(id);
    return {
      id,
      parent: node.parent == null ? null : String(node.parent),
      title: String(node.title || "未命名节点").slice(0, 300),
      content: String(node.content || "").slice(0, 100000),
      status: ["todo", "active", "done"].includes(node.status) ? node.status : "todo",
      rounds: Math.max(1, Math.min(100, Math.floor(Number(node.rounds) || 1))),
      completed: Math.max(0, Math.min(100, Math.floor(Number(node.completed) || 0))),
    };
  });
  // One node is the current one at a time; older data may hold several.
  let current = false;
  for (const node of nodes)
    if (node.status === "active") {
      if (current) node.status = "todo";
      current = true;
    }
  for (const node of nodes) {
    let next = node.parent,
      depth = 0;
    const seen = new Set([node.id]);
    while (next) {
      if (!ids.has(next) || seen.has(next) || ++depth > 32) throw new Error("大纲层级无效或包含循环。");
      seen.add(next);
      next = nodes.find((n) => n.id === next)!.parent;
    }
  }
  return {
    version: 1,
    nodes,
    selected: ids.has(value.selected) ? value.selected : nodes[0]?.id || "",
    settings: {
      mode: value.settings?.mode === "replace" ? "replace" : "caret",
      send: value.settings?.send === true,
      inject: {
        enabled: value.settings?.inject?.enabled === true,
        depth: Math.max(0, Math.min(100, Math.floor(Number(value.settings?.inject?.depth ?? 4) || 0))),
      },
    },
    job:
      value.job && Array.isArray(value.job.queue)
        ? {
            queue: value.job.queue.filter((id: string) => ids.has(id)),
            index: Math.max(0, Number(value.job.index) || 0),
          }
        : undefined,
  };
}
export function orderedNodes(data: OutlineData, parent: string | null = null): OutlineNode[] {
  return data.nodes
    .filter((n) => n.parent === parent)
    .flatMap((node) => [node, ...orderedNodes(data, node.id)]);
}
export function descendants(data: OutlineData, id: string): OutlineNode[] {
  return orderedNodes(data, id);
}
export function writingQueue(data: OutlineData, selected: string, subtree = false) {
  const ordered = orderedNodes(data);
  const eligible = (node: OutlineNode) =>
    !data.nodes.some((n) => n.parent === node.id) && node.content.trim() && node.status !== "done";
  const start = ordered.findIndex((n) => n.id === selected);
  return (
    subtree
      ? ordered.filter((n) => n.id === selected || descendants(data, selected).some((d) => d.id === n.id))
      : ordered.slice(Math.max(0, start))
  )
    .filter(eligible)
    .map((n) => n.id);
}
function backgrounds(data: OutlineData, node: OutlineNode) {
  const parents: OutlineNode[] = [];
  let parent = node.parent;
  while (parent) {
    const n = data.nodes.find((n) => n.id === parent)!;
    parents.unshift(n);
    parent = n.parent;
  }
  return parents.filter((n) => n.content.trim()).map((n) => `背景 · ${n.title}\n${n.content}`);
}
export function instruction(data: OutlineData, id: string) {
  const node = data.nodes.find((n) => n.id === id)!;
  return [...backgrounds(data, node), `写作节点 · ${node.title}\n${node.content}`].join("\n\n");
}
const isLeaf = (data: OutlineData, node: OutlineNode) => !data.nodes.some((n) => n.parent === node.id);
/**
 * The author moves the story along by hand. Making a node current returns the previous one to
 * todo; finishing a node makes the next unfinished leaf, in reading order, the current one.
 */
export function advance(data: OutlineData, id: string, to: Status): OutlineData {
  if (!data.nodes.some((n) => n.id === id)) return data;
  let nodes = data.nodes.map((n) =>
    n.id === id
      ? { ...n, status: to, completed: to === "todo" ? 0 : n.completed }
      : to === "active" && n.status === "active"
        ? { ...n, status: "todo" as const }
        : n,
  );
  if (to === "done" && !nodes.some((n) => n.status === "active")) {
    const next = { ...data, nodes },
      ordered = orderedNodes(next),
      from = ordered.findIndex((n) => n.id === id),
      following = [...ordered.slice(from + 1), ...ordered.slice(0, from)].find(
        (n) => n.status !== "done" && isLeaf(next, n),
      );
    if (following) nodes = nodes.map((n) => (n.id === following.id ? { ...n, status: "active" } : n));
  }
  return { ...data, nodes };
}
/** What `{{outline}}` stands for: the current node with its chapters' background, and what comes next. */
export function outlineContext(data: OutlineData) {
  const node = data.nodes.find((n) => n.status === "active");
  if (!node) return "";
  const ordered = orderedNodes(data),
    next = ordered.slice(ordered.indexOf(node) + 1).find((n) => n.status !== "done" && isLeaf(data, n));
  return [
    ...backgrounds(data, node),
    `当前节点 · ${node.title}${node.content.trim() ? `\n${node.content}` : ""}`,
    ...(next ? [`下一节点 · ${next.title}`] : []),
  ].join("\n\n");
}
/** Another chat's outline as the start of a new story: the tree and its text, none of the progress. */
export function reuseOutline(data: OutlineData): OutlineData {
  return normalizeOutline({
    ...emptyOutline(),
    nodes: data.nodes.map((n) => ({ ...n, status: "todo", completed: 0 })),
    selected: data.selected,
  });
}
export function moveNode(data: OutlineData, id: string, target: string, inside: boolean): OutlineData {
  const node = data.nodes.find((n) => n.id === id),
    destination = data.nodes.find((n) => n.id === target);
  if (!node || !destination || id === target || descendants(data, id).some((n) => n.id === target))
    throw new Error("无法移入自己的子节点。");
  const block = [node, ...descendants(data, id)],
    ids = new Set(block.map((n) => n.id));
  const nodes = data.nodes.filter((n) => !ids.has(n.id));
  node.parent = inside ? target : destination.parent;
  const index = nodes.findIndex((n) => n.id === target);
  nodes.splice(index + (inside ? 1 : 0), 0, ...block);
  return normalizeOutline({ ...data, nodes });
}
export function markdownExport(data: OutlineData) {
  const depth = (n: OutlineNode): number =>
    n.parent ? depth(data.nodes.find((p) => p.id === n.parent)!) + 1 : 1;
  return (
    orderedNodes(data)
      .map((n) => `${"#".repeat(depth(n))} ${n.title}\n\n${n.content}`)
      .join("\n\n") + "\n"
  );
}
export function markdownImport(text: string): OutlineData {
  const data = emptyOutline(),
    stack: OutlineNode[] = [];
  let current: OutlineNode | undefined;
  let fenced = false;
  for (const line of text.split(/\r?\n/)) {
    if (/^\s*```/.test(line)) fenced = !fenced;
    const match = !fenced ? line.match(/^(#{1,32})\s+(.+)$/) : null;
    if (match) {
      while (stack.length && stack.length >= match[1].length) stack.pop();
      current = {
        id: randomId(),
        parent: stack.at(-1)?.id || null,
        title: match[2],
        content: "",
        status: "todo",
        rounds: 1,
        completed: 0,
      };
      data.nodes.push(current);
      stack.push(current);
    } else if (current) current.content += (current.content ? "\n" : "") + line;
  }
  data.nodes.forEach((n) => (n.content = n.content.trim()));
  if (!data.nodes.length) throw new Error("Markdown 中需要至少一个标题。");
  data.selected = data.nodes[0].id;
  return normalizeOutline(data);
}
export function parseImport(text: string) {
  if (text.length > 4000000) throw new Error("导入文件过大。");
  return text.trim().startsWith("{") ? normalizeOutline(JSON.parse(text)) : markdownImport(text);
}
export function mergeOutline(current: OutlineData, incoming: OutlineData) {
  const map = new Map(incoming.nodes.map((n) => [n.id, randomId()]));
  return normalizeOutline({
    ...current,
    nodes: [
      ...current.nodes,
      ...incoming.nodes.map((n) => ({
        ...n,
        id: map.get(n.id),
        parent: n.parent ? map.get(n.parent) : null,
      })),
    ],
  });
}
