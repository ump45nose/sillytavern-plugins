// Minimal source-preserving CSS reader for build tooling: splits a stylesheet into
// style rules, conditional groups and opaque at-rules without re-serializing declarations.
const GROUPS = /^@(media|supports|container|layer|scope|document)\b/i;

/** Index just past the string or comment starting at `i`, or `i` when there is none. */
function skip(text, i) {
  const c = text[i];
  if (c === "/" && text[i + 1] === "*") {
    const end = text.indexOf("*/", i + 2);
    return end < 0 ? text.length : end + 2;
  }
  if (c === '"' || c === "'") {
    for (let j = i + 1; j < text.length; j++) {
      if (text[j] === "\\") j++;
      else if (text[j] === c) return j + 1;
    }
    return text.length;
  }
  return i;
}

/** Index of the `}` matching the `{` at `open`. */
function close(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; ) {
    const next = skip(text, i);
    if (next !== i) {
      i = next;
      continue;
    }
    if (text[i] === "{") depth++;
    else if (text[i] === "}" && --depth === 0) return i;
    i++;
  }
  throw new Error("Unbalanced braces at " + open);
}

/**
 * @returns {Array<{type:"rule",prelude:string,body:string}|{type:"group",prelude:string,children:any[]}|{type:"raw",text:string}>}
 */
export function parse(text) {
  const nodes = [];
  let i = 0,
    start = 0;
  while (i < text.length) {
    if (text[i] === "/" && text[i + 1] === "*" && !text.slice(start, i).trim()) {
      const end = skip(text, i);
      nodes.push({ type: "raw", text: text.slice(i, end) });
      i = start = end;
      continue;
    }
    const next = skip(text, i);
    if (next !== i) {
      i = next;
      continue;
    }
    const c = text[i];
    if (c === ";") {
      const statement = text.slice(start, i + 1).trim();
      if (statement !== ";") nodes.push({ type: "raw", text: statement });
      i = start = i + 1;
    } else if (c === "{") {
      const end = close(text, i);
      const prelude = text.slice(start, i).trim();
      const body = text.slice(i + 1, end);
      if (prelude.startsWith("@"))
        nodes.push(
          GROUPS.test(prelude)
            ? { type: "group", prelude, children: parse(body) }
            : { type: "raw", text: text.slice(start, end + 1).trim() },
        );
      else nodes.push({ type: "rule", prelude, body });
      i = start = end + 1;
    } else if (c === "}") throw new Error("Unexpected } at " + i);
    else i++;
  }
  return nodes;
}

/** Splits a selector list on top-level commas. */
export function splitList(text) {
  const parts = [];
  let depth = 0,
    start = 0;
  for (let i = 0; i < text.length; i++) {
    const next = skip(text, i);
    if (next !== i) {
      i = next - 1;
      continue;
    }
    const c = text[i];
    if (c === "(" || c === "[") depth++;
    else if (c === ")" || c === "]") depth--;
    else if (c === "," && depth === 0) {
      parts.push(text.slice(start, i).trim());
      start = i + 1;
    }
  }
  parts.push(text.slice(start).trim());
  return parts.filter(Boolean);
}
