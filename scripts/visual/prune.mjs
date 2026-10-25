// Removes the selectors a redesigned component no longer uses from the frozen stylesheets.
// Usage: node scripts/visual/prune.mjs '<regex>' [--dry] [files…]
// Defaults to src/styles/legacy/*.css and native-bridge.css. A rule loses only the selectors in its
// list that match; it disappears when none remain. Text outside removed selectors is untouched.
import fs from "node:fs";
import path from "node:path";

const args = process.argv.slice(2);
const dry = args.includes("--dry");
const [pattern, ...rest] = args.filter((a) => a !== "--dry");
if (!pattern) throw new Error("usage: prune.mjs '<regex>' [--dry] [files…]");
const match = new RegExp(pattern);
const files = rest.length
  ? rest
  : [
      ...fs.readdirSync("src/styles/legacy").map((f) => path.join("src/styles/legacy", f)),
      "src/styles/native-bridge.css",
    ];

function skip(text, i) {
  if (text[i] === "/" && text[i + 1] === "*") {
    const end = text.indexOf("*/", i + 2);
    return end < 0 ? text.length : end + 2;
  }
  if (text[i] === '"' || text[i] === "'") {
    for (let j = i + 1; j < text.length; j++) {
      if (text[j] === "\\") j++;
      else if (text[j] === text[i]) return j + 1;
    }
  }
  return i;
}
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
function split(list) {
  const parts = [];
  let depth = 0,
    start = 0;
  for (let i = 0; i < list.length; i++) {
    const next = skip(list, i);
    if (next !== i) {
      i = next - 1;
      continue;
    }
    if ("([".includes(list[i])) depth++;
    else if (")]".includes(list[i])) depth--;
    else if (list[i] === "," && depth === 0) {
      parts.push(list.slice(start, i).trim());
      start = i + 1;
    }
  }
  parts.push(list.slice(start).trim());
  return parts.filter(Boolean);
}

/**
 * Narrows a matching selector by dropping only the matching alternatives inside :is()/:where()/:not().
 * An emptied :is()/:where() means the selector can never apply (null); an emptied :not() is dropped.
 */
function narrow(selector) {
  let out = selector;
  for (let guard = 0; guard < 50; guard++) {
    const flat = out.replace(/\s+/g, " ");
    if (!match.test(flat)) return out;
    const re = /:(is|where|not)\(/g;
    let changed = false,
      m;
    while ((m = re.exec(out))) {
      const open = m.index + m[0].length - 1;
      let depth = 0,
        close = -1;
      for (let i = open; i < out.length; i++) {
        if (out[i] === "(") depth++;
        else if (out[i] === ")" && --depth === 0) {
          close = i;
          break;
        }
      }
      if (close < 0) break;
      const args = split(out.slice(open + 1, close));
      const kept = args.filter((a) => !match.test(a.replace(/\s+/g, " ")));
      if (kept.length === args.length) continue;
      if (!kept.length && m[1] !== "not") return null;
      const group = kept.length ? `:${m[1]}(${kept.join(", ")})` : "";
      out = out.slice(0, m.index) + group + out.slice(close + 1);
      changed = true;
      break;
    }
    if (!changed) return null;
  }
  return null;
}

/** Returns [edits] as {from, to, text} over `text` between `lo` and `hi`. */
function walk(text, lo, hi, edits, stats) {
  let i = lo,
    start = lo;
  while (i < hi) {
    const next = skip(text, i);
    if (next !== i) {
      if (!text.slice(start, i).trim()) start = next;
      i = next;
      continue;
    }
    const c = text[i];
    if (c === ";" || c === "}") {
      i = start = i + 1;
    } else if (c === "{") {
      const end = close(text, i);
      const prelude = text.slice(start, i);
      const trimmed = prelude.trim();
      if (trimmed.startsWith("@")) {
        if (/^@(media|supports|layer|container)\b/.test(trimmed)) walk(text, i + 1, end, edits, stats);
      } else {
        const selectors = split(trimmed);
        const narrowed = selectors.map(narrow);
        const keep = narrowed.filter((s) => s !== null);
        if (narrowed.some((s, k) => s !== selectors[k])) {
          const lead = prelude.length - prelude.trimStart().length;
          const indent = (prelude.slice(0, lead).match(/[^\n]*$/) || [""])[0];
          if (!keep.length) {
            let to = end + 1;
            if (text[to] === "\n") to++;
            edits.push({ from: start + lead - indent.length, to, text: "" });
            stats.rules++;
          } else {
            edits.push({ from: start + lead, to: i, text: keep.join(",\n" + indent) + " " });
          }
          stats.selectors += selectors.length - keep.length;
        }
      }
      i = start = end + 1;
    } else i++;
  }
}

let total = { rules: 0, selectors: 0, important: 0 };
for (const file of files) {
  const text = fs.readFileSync(file, "utf8");
  const edits = [],
    stats = { rules: 0, selectors: 0 };
  walk(text, 0, text.length, edits, stats);
  if (!edits.length) continue;
  let out = text;
  for (const e of edits.sort((a, b) => b.from - a.from)) out = out.slice(0, e.from) + e.text + out.slice(e.to);
  // Drop @media/@supports groups left empty.
  out = out.replace(/\n[ \t]*@(media|supports)[^{]*\{\s*\}/g, "");
  const important = (text.match(/!important/g) || []).length - (out.match(/!important/g) || []).length;
  console.log(`${file}: -${stats.selectors} selectors, -${stats.rules} rules, -${important} !important`);
  total.rules += stats.rules;
  total.selectors += stats.selectors;
  total.important += important;
  if (!dry) fs.writeFileSync(file, out);
}
console.log(`total: -${total.selectors} selectors, -${total.rules} rules, -${total.important} !important${dry ? " (dry run)" : ""}`);
