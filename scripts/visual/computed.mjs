// Snapshots computed styles of every rendered element (and its ::before/::after) per visual state.
// Usage:
//   node scripts/visual/computed.mjs snap <outDir> [stateFilter]
//   node scripts/visual/computed.mjs diff <baseDir> <currentDir> [stateFilter]
// Stricter than pixels: catches hover-only, off-screen and sub-pixel changes in the captured states.
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { launch } from "../browser.mjs";
import { states, visit } from "./states.mjs";

const [command, a, b, pattern] = process.argv.slice(2);
const filter = (command === "diff" ? pattern : b) ? new RegExp(command === "diff" ? pattern : b) : null;

function dump() {
  document.getAnimations().forEach((animation) => {
    try {
      animation.finish();
    } catch {
      animation.cancel();
    }
  });
  const key = (el) => {
    const parts = [];
    for (; el && el !== document.documentElement; el = el.parentElement) {
      const index = el.parentElement ? [...el.parentElement.children].indexOf(el) : 0;
      // React useId values (_r_o_, :r1:) differ per load and are not part of the key.
      const id = el.id && !/^(_r_\w*_|:r\w*:)$/.test(el.id) ? "#" + el.id : "";
      parts.unshift(
        `${el.tagName.toLowerCase()}${id}${el.classList[0] ? "." + el.classList[0] : ""}:${index}`,
      );
    }
    return parts.join(">");
  };
  const read = (style) => {
    const out = {};
    for (const p of style) if (!p.startsWith("--")) out[p] = style.getPropertyValue(p);
    return out;
  };
  const result = {};
  for (const el of document.body.querySelectorAll("*")) {
    if (!el.getClientRects().length) continue;
    const k = key(el);
    const r = el.getBoundingClientRect();
    result[k] = {
      ...read(getComputedStyle(el)),
      __rect: [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 4) / 4).join(","),
    };
    for (const pseudo of ["::before", "::after"]) {
      const style = getComputedStyle(el, pseudo);
      if (style.content && style.content !== "none" && style.content !== "normal")
        result[k + pseudo] = read(style);
    }
  }
  return result;
}

if (command === "snap") {
  const out = path.resolve(a);
  // A partial filter run keeps other states; a full run starts clean so stale files cannot pass.
  if (!filter) fs.rmSync(out, { recursive: true, force: true });
  fs.mkdirSync(out, { recursive: true });
  let failures = 0;
  const browser = await launch();
  try {
    for (const state of states) {
      if (filter && !filter.test(state.name)) continue;
      try {
        const { result } = await visit(browser, state, (page) => page.evaluate(dump));
        fs.writeFileSync(path.join(out, state.name + ".json.gz"), zlib.gzipSync(JSON.stringify(result)));
        console.log("OK  ", state.name, Object.keys(result).length);
      } catch (error) {
        failures++;
        console.log("FAIL", state.name, String(error.message || error).split("\n")[0]);
      }
    }
  } finally {
    await browser.close();
  }
  process.exitCode = failures ? 1 : 0;
} else if (command === "diff") {
  const load = (dir, file) => JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(dir, file))));
  let failed = 0;
  const report = {};
  for (const file of fs
    .readdirSync(a)
    .filter((f) => f.endsWith(".json.gz"))
    .sort()) {
    const name = file.replace(".json.gz", "");
    if (filter && !filter.test(name)) continue;
    if (!fs.existsSync(path.join(b, file))) {
      if (!filter) {
        failed++;
        console.log("MISS", name);
      }
      continue;
    }
    const [x, y] = [load(a, file), load(b, file)];
    const changes = [];
    for (const k of new Set([...Object.keys(x), ...Object.keys(y)])) {
      if (!x[k] || !y[k]) {
        changes.push([k, x[k] ? "removed" : "added"]);
        continue;
      }
      for (const p of Object.keys(x[k])) if (x[k][p] !== y[k][p]) changes.push([k, p, x[k][p], y[k][p]]);
    }
    report[name] = changes;
    if (changes.length) failed++;
    console.log(changes.length ? "DIFF" : "SAME", name, changes.length || "");
    for (const c of changes.slice(0, 12))
      console.log(
        "     ",
        c[0].slice(-100),
        c
          .slice(1)
          .map((v) => String(v).slice(0, 70))
          .join(" | "),
      );
  }
  fs.writeFileSync(path.join(b, "computed-diff.json"), JSON.stringify(report, null, 1));
  process.exitCode = failed ? 1 : 0;
} else {
  console.log("usage: computed.mjs snap <outDir> [filter] | diff <baseDir> <currentDir> [filter]");
  process.exitCode = 2;
}
