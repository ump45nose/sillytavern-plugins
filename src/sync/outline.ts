import {
  normalizeOutline,
  orderedNodes,
  type OutlineData,
  type OutlineNode,
  type Status,
} from "../addons/outline/model";
import { randomId } from "../host/ids";
import { SyncError } from "./text";

const statuses: [Status, string][] = [
  ["todo", "待写"],
  ["active", "当前"],
  ["done", "完成"],
];
const heading = /^(#{1,32}) (.*)$/,
  /** Body lines that would read as headings get one more leading backslash. */
  headingLike = /^\\*#{1,32} /,
  attributes = /^<!--(.*)-->$/;

/**
 * An outline as Markdown: heading depth is the tree, the line under each heading holds the node's
 * id and progress, and the text below is the node content. Settings, selection and the running job
 * are not in the file and keep their values.
 */
export const outlineCodec = {
  render(data: OutlineData) {
    const depth = (n: OutlineNode): number =>
      n.parent ? depth(data.nodes.find((p) => p.id === n.parent)!) + 1 : 1;
    return orderedNodes(data)
      .map((n) => {
        const status = statuses.find(([s]) => s === n.status)![1],
          head = `${"#".repeat(depth(n))} ${n.title.replace(/\n/g, " ")}\n<!-- id: ${n.id} · 状态: ${status} · 轮数: ${n.rounds} · 已完成: ${n.completed} -->`,
          body = n.content
            .split("\n")
            .map((line) => (headingLike.test(line) ? "\\" + line : line))
            .join("\n");
        return n.content ? `${head}\n${body}` : head;
      })
      .map((block, i, all) => (i < all.length - 1 ? block + "\n\n" : block + "\n"))
      .join("");
  },
  parse(base: OutlineData, text: string): OutlineData {
    const lines = text.replace(/\r\n/g, "\n").split("\n");
    if (lines.at(-1) === "") lines.pop();
    const nodes: OutlineNode[] = [],
      stack: OutlineNode[] = [],
      ids = new Set<string>();
    let body: string[] | null = null;
    const close = (last: boolean) => {
      const node = nodes.at(-1);
      if (!node || !body) return;
      // Blocks are separated by one blank line, which is not content.
      if (!last && body.at(-1) === "") body.pop();
      node.content = body.map((line) => (/^\\+#{1,32} /.test(line) ? line.slice(1) : line)).join("\n");
    };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i],
        match = line.match(heading);
      if (!match) {
        if (body) body.push(line);
        else if (line.trim()) throw new SyncError("第一个标题之前不能有正文。", i + 1);
        continue;
      }
      close(false);
      const level = match[1].length;
      if (level > stack.length + 1) throw new SyncError(`标题层级跳级：上一级是 ${stack.length} 级。`, i + 1);
      stack.length = level - 1;
      const node: OutlineNode = {
        id: "",
        parent: stack.at(-1)?.id ?? null,
        title: match[2],
        content: "",
        status: "todo",
        rounds: 1,
        completed: 0,
      };
      const attr = lines[i + 1]?.match(attributes);
      if (attr) {
        i++;
        for (const part of attr[1].split("·")) {
          const [key, ...rest] = part.split(":"),
            name = key.trim(),
            value = rest.join(":").trim();
          if (!name) continue;
          if (name === "id") node.id = value;
          else if (name === "状态") {
            const status = statuses.find(([, label]) => label === value)?.[0];
            if (!status)
              throw new SyncError(`状态应为 ${statuses.map(([, l]) => l).join(" / ")} 之一。`, i + 1);
            node.status = status;
          } else if (name === "轮数" || name === "已完成") {
            const n = Number(value);
            if (!Number.isInteger(n) || n < 0) throw new SyncError(`「${name}」应为非负整数。`, i + 1);
            name === "轮数" ? (node.rounds = n) : (node.completed = n);
          } else throw new SyncError(`未知的节点属性「${name}」。`, i + 1);
        }
      }
      if (!node.id) node.id = randomId();
      if (ids.has(node.id)) throw new SyncError(`节点 id ${node.id} 重复；复制节点时请删去 id。`, i + 1);
      ids.add(node.id);
      nodes.push(node);
      stack.push(node);
      body = [];
    }
    close(true);
    try {
      return normalizeOutline({ ...base, nodes });
    } catch (error) {
      throw new SyncError(error instanceof Error ? error.message : String(error));
    }
  },
};
