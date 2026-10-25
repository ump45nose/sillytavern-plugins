export type ExportRole = "user" | "assistant" | "system";
export interface ExportMessage {
  id: number;
  name: string;
  role: ExportRole;
  text: string;
}
export interface XmlBlock {
  name: string;
  start: number;
  innerStart: number;
  innerEnd: number;
  end: number;
  parent: number | null;
  depth: number;
  closed: boolean;
  selfClosing: boolean;
}
export interface XmlWarning {
  offset: number;
  message: string;
}
export interface ParsedMessage extends ExportMessage {
  blocks: XmlBlock[];
  warnings: XmlWarning[];
}
export interface ExportOptions {
  mode: "all" | "include" | "exclude";
  tags: string[];
  excludeTags?: string[];
  keepTags: boolean;
  roles: ExportRole[];
  from: number;
  to: number;
  keyword: string;
}
export interface TagStat {
  name: string;
  path: string;
  depth: number;
  count: number;
  floors: number;
  characters: number;
}
export interface ExportSummary {
  total: number;
  matched: number;
  characters: number;
  preview: ExportMessage[];
  warnings: { id: number; message: string }[];
}
const xmlName = /^\/?([\p{L}_][\p{L}\p{N}_.:\-]*)(?=[\s/>]|$)/u;
const htmlVoid = new Set([
  "area",
  "base",
  "br",
  "col",
  "embed",
  "hr",
  "img",
  "input",
  "link",
  "meta",
  "param",
  "source",
  "track",
  "wbr",
]);
/** Parse mixed Markdown/XML by offsets. No DOM, entity expansion or markup execution. */
export function scanXml(text: string): { blocks: XmlBlock[]; warnings: XmlWarning[] } {
  const blocks: XmlBlock[] = [],
    warnings: XmlWarning[] = [],
    stack: number[] = [];
  let position = 0;
  while (position < text.length) {
    const start = text.indexOf("<", position);
    if (start < 0) break;
    if (
      text.startsWith("<!--", start) ||
      text.startsWith("<![CDATA[", start) ||
      text.startsWith("<?", start)
    ) {
      const marker = text.startsWith("<!--", start)
        ? "-->"
        : text.startsWith("<![CDATA[", start)
          ? "]]>"
          : "?>";
      const end = text.indexOf(marker, start + 2);
      position = end < 0 ? text.length : end + marker.length;
      continue;
    }
    const match = text.slice(start + 1).match(xmlName);
    if (!match) {
      position = start + 1;
      continue;
    }
    let end = start + 1 + match[0].length,
      quote = "";
    for (; end < text.length; end++) {
      const character = text[end];
      if (quote) {
        if (character === quote) quote = "";
      } else if (character === '"' || character === "'") quote = character;
      else if (character === ">" || character === "<") break;
    }
    if (text[end] !== ">") {
      if (text[start + 1] !== "/") {
        blocks.push({
          name: match[1],
          start,
          innerStart: Math.min(end, text.length),
          innerEnd: text.length,
          end: text.length,
          parent: stack.at(-1) ?? null,
          depth: stack.length,
          closed: false,
          selfClosing: false,
        });
        warnings.push({ offset: start, message: `<${match[1]}> 开头不完整；排除时屏蔽到消息末尾` });
      }
      position = Math.max(start + 1, end);
      continue;
    }
    position = end + 1;
    const name = match[1],
      closing = text[start + 1] === "/";
    if (closing) {
      if (text.slice(start + 2 + name.length, end).trim()) continue;
      let index = stack.length - 1;
      while (index >= 0 && blocks[stack[index]].name !== name) index--;
      if (index < 0) {
        warnings.push({ offset: start, message: `孤立结束标签 </${name}>` });
        continue;
      }
      for (let i = stack.length - 1; i > index; i--)
        warnings.push({
          offset: blocks[stack[i]].start,
          message: `<${blocks[stack[i]].name}> 标签错配；排除时屏蔽到消息末尾`,
        });
      const block = blocks[stack[index]];
      block.innerEnd = start;
      block.end = end + 1;
      block.closed = true;
      stack.length = index;
      continue;
    }
    const selfClosing = /\/\s*$/.test(text.slice(start + 1, end)) || htmlVoid.has(name.toLowerCase());
    blocks.push({
      name,
      start,
      innerStart: end + 1,
      innerEnd: selfClosing ? end + 1 : text.length,
      end: selfClosing ? end + 1 : text.length,
      parent: stack.at(-1) ?? null,
      depth: stack.length,
      closed: selfClosing,
      selfClosing,
    });
    if (!selfClosing) stack.push(blocks.length - 1);
  }
  for (const index of stack)
    warnings.push({
      offset: blocks[index].start,
      message: `<${blocks[index].name}> 未闭合；排除时屏蔽到消息末尾`,
    });
  return { blocks, warnings };
}
export function parseMessage(message: ExportMessage): ParsedMessage {
  return { ...message, ...scanXml(message.text) };
}
export function tagStatistics(messages: ParsedMessage[]): TagStat[] {
  const stats = new Map<string, TagStat & { messageIds: Set<number> }>();
  for (const message of messages) {
    const paths: string[] = [];
    message.blocks.forEach((block, index) => {
      const path = block.parent === null ? block.name : `${paths[block.parent]} / ${block.name}`;
      paths[index] = path;
      const stat = stats.get(path) || {
        name: block.name,
        path,
        depth: block.depth,
        count: 0,
        floors: 0,
        characters: 0,
        messageIds: new Set<number>(),
      };
      stat.count++;
      stat.characters += Math.max(0, block.innerEnd - block.innerStart);
      stat.messageIds.add(message.id);
      stats.set(path, stat);
    });
  }
  return [...stats.values()]
    .map(({ messageIds, ...stat }) => ({ ...stat, floors: messageIds.size }))
    .sort((a, b) => a.path.localeCompare(b.path));
}
/** Merge ranges before extraction/removal, so selected parents and children never duplicate text. */
function mergeRanges(ranges: [number, number][]): [number, number][] {
  const output: [number, number][] = [];
  for (const range of ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1])) {
    const previous = output.at(-1);
    if (previous && range[0] <= previous[1]) previous[1] = Math.max(previous[1], range[1]);
    else output.push([...range]);
  }
  return output;
}
export function filterContent(
  message: ParsedMessage,
  options: Pick<ExportOptions, "mode" | "tags" | "excludeTags" | "keepTags">,
): string {
  const tags = new Set(options.tags),
    matches = message.blocks.filter((block) => tags.has(block.name));
  const excluded = new Set(options.excludeTags || []);
  if (options.mode === "exclude") options.tags.forEach((tag) => excluded.add(tag));
  const removed = mergeRanges(
    message.blocks.filter((block) => excluded.has(block.name)).map((block) => [block.start, block.end]),
  );
  if (options.mode === "include") {
    const parents: XmlBlock[] = [];
    for (const block of matches.filter((b) => b.closed))
      if (!parents.some((parent) => parent.start <= block.start && parent.end >= block.end))
        parents.push(block);
    return parents
      .map((block) => {
        const start = options.keepTags ? block.start : block.innerStart,
          end = options.keepTags ? block.end : block.innerEnd;
        const wrappers: [number, number][] = options.keepTags
          ? []
          : matches
              .filter((child) => child.closed && child.start >= start && child.end <= end)
              .flatMap(
                (child) =>
                  [
                    [child.start - start, child.innerStart - start],
                    [child.innerEnd - start, child.end - start],
                  ] as [number, number][],
              );
        for (const [a, b] of removed)
          if (a < end && b > start) wrappers.push([Math.max(start, a) - start, Math.min(end, b) - start]);
        return removeRanges(message.text.slice(start, end), wrappers);
      })
      .filter(Boolean)
      .join("\n\n");
  }
  return removeRanges(message.text, removed);
}
function removeRanges(text: string, input: [number, number][]): string {
  const ranges = mergeRanges(input);
  let cursor = 0,
    output = "";
  for (const [start, end] of ranges) {
    output += text.slice(cursor, start);
    cursor = end;
  }
  return output + text.slice(cursor);
}
export function filterMessage(message: ParsedMessage, options: ExportOptions): ExportMessage | null {
  if (message.id + 1 < options.from || message.id + 1 > options.to || !options.roles.includes(message.role))
    return null;
  const text = filterContent(message, options);
  if (
    !text.trim() ||
    (options.keyword && !text.toLocaleLowerCase().includes(options.keyword.toLocaleLowerCase()))
  )
    return null;
  return { id: message.id, name: message.name, role: message.role, text };
}
export function exportParts(messages: ExportMessage[], format: "txt" | "md", metadata: boolean): string[] {
  return messages.flatMap((message) => {
    const name = format === "md" ? message.name.replace(/[\\`*_{}[\]<>#\n\r]/g, "\\$&") : message.name;
    return [
      metadata
        ? format === "md"
          ? `## ${message.id + 1} 层 · ${name}\n\n`
          : `${message.id + 1} 层 · ${name}\n\n`
        : "",
      message.text,
      "\n\n",
      metadata ? "---\n\n" : "",
    ];
  });
}
