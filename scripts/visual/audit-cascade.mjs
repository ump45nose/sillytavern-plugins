// Maps the cascade between workbench CSS and native SillyTavern CSS across the visual states.
// Usage: node scripts/visual/audit-cascade.mjs [outFile=artifacts/cascade/audit.json] [stateFilter]
//
// For every workbench selector it records whether matched elements sit inside the isolated
// workbench UI ("in") or in native DOM ("out"). For every native rule it records whether it
// currently reaches workbench UI. Dynamic pseudo-classes and pseudo-elements are stripped
// before matching so hover/focus/::before rules are classified by their element.
import fs from "node:fs";
import path from "node:path";
import { launch } from "../browser.mjs";
import { states, visit } from "./states.mjs";

const out = path.resolve(process.argv[2] || "artifacts/cascade/audit.json");
const filter = process.argv[3] ? new RegExp(process.argv[3]) : null;
fs.mkdirSync(path.dirname(out), { recursive: true });

function inspect() {
  const SCOPE = "#wb-root, #wb-layout-root, .wb-ui";
  const LEASED = ".wb-native-embedded";
  const isPlugin = (sheet) => /\/workbench-probe\//.test(sheet.href || "");
  const inScope = (el) => !!el.closest(SCOPE) && !el.closest(LEASED);
  const strip = (selector) =>
    selector
      .replace(
        /::?(before|after|placeholder|selection|marker|backdrop|file-selector-button|-webkit-[\w-]+|-moz-[\w-]+)(\([^)]*\))?/g,
        "",
      )
      .replace(
        /:(hover|focus|focus-visible|focus-within|active|visited|target|checked|disabled|enabled|placeholder-shown|user-invalid|invalid|indeterminate|autofill|-webkit-autofill)(?![\w-])/g,
        "",
      )
      .replace(/:(is|where|not|has)\(\s*\)/g, "")
      .trim() || "*";
  const splitList = (text) => {
    const parts = [];
    let depth = 0,
      start = 0;
    for (let i = 0; i < text.length; i++) {
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
  };
  // Nested rules are resolved against their parent so `& div` is matched in context.
  const styleRules = (list, acc = [], parent = "") => {
    for (const rule of list) {
      let scope = parent;
      if (rule instanceof CSSStyleRule) {
        const selectors = splitList(rule.selectorText).map((s) =>
          !parent ? s : s.includes("&") ? s.replaceAll("&", `:is(${parent})`) : `:is(${parent}) ${s}`,
        );
        acc.push({ rule, selectors });
        scope = selectors.join(", ");
      }
      if (rule.cssRules && !(rule instanceof CSSKeyframesRule)) styleRules(rule.cssRules, acc, scope);
    }
    return acc;
  };
  const plugin = {};
  const native = {};
  for (const sheet of document.styleSheets) {
    let rules;
    try {
      rules = styleRules(sheet.cssRules);
    } catch {
      continue;
    }
    const mine = isPlugin(sheet);
    for (const { rule, selectors } of rules) {
      for (const selector of selectors) {
        let matched;
        try {
          matched = document.querySelectorAll(strip(selector));
        } catch {
          continue;
        }
        let inside = 0,
          outside = 0;
        for (const el of matched) inScope(el) ? inside++ : outside++;
        if (mine) plugin[selector] = { in: inside, out: outside };
        else if (inside) {
          const props = [...rule.style].filter((p) => !p.startsWith("--"));
          if (props.length)
            native[selector] = {
              in: inside,
              sheet: (sheet.href || "inline").replace(location.origin, ""),
              props: props.map((p) => p + (rule.style.getPropertyPriority(p) ? " !important" : "")),
            };
        }
      }
    }
  }
  // Native DOM that ended up inside the isolated scope without the leased marker.
  const foreign = [
    ...document.querySelectorAll(
      SCOPE.split(", ")
        .map((s) => s + " *")
        .join(","),
    ),
  ]
    .filter(
      (el) =>
        inScope(el) &&
        el.classList.length &&
        ![...el.classList].some((c) => /^(wb-|lucide|is-|has-)/.test(c)),
    )
    .map((el) => el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + "." + [...el.classList].join("."));
  // Where each class and id lives, used to classify selectors no state matched.
  const tokens = {};
  for (const el of document.body.querySelectorAll("*")) {
    const side = inScope(el) ? "in" : "out";
    for (const c of el.classList) (tokens["." + c] ??= { in: 0, out: 0 })[side]++;
    if (el.id) (tokens["#" + el.id] ??= { in: 0, out: 0 })[side]++;
  }
  return { plugin, native, tokens, foreign: [...new Set(foreign)] };
}

const browser = await launch();
const merged = { plugin: {}, native: {}, tokens: {}, foreign: {}, states: [] };
try {
  for (const state of states) {
    if (filter && !filter.test(state.name)) continue;
    try {
      const { result } = await visit(browser, state, (page) => page.evaluate(inspect));
      for (const [selector, hit] of Object.entries(result.plugin)) {
        const entry = (merged.plugin[selector] ??= { in: 0, out: 0, states: [] });
        entry.in += hit.in;
        entry.out += hit.out;
        if (hit.in || hit.out) entry.states.push(state.name);
      }
      for (const [selector, hit] of Object.entries(result.native)) {
        const entry = (merged.native[selector] ??= { ...hit, in: 0, states: [] });
        entry.in += hit.in;
        entry.states.push(state.name);
      }
      for (const [token, hit] of Object.entries(result.tokens)) {
        const entry = (merged.tokens[token] ??= { in: 0, out: 0 });
        entry.in += hit.in;
        entry.out += hit.out;
      }
      for (const item of result.foreign) (merged.foreign[item] ??= []).push(state.name);
      merged.states.push(state.name);
      console.log("OK  ", state.name);
    } catch (error) {
      console.log("FAIL", state.name, String(error.message || error).split("\n")[0]);
    }
  }
} finally {
  await browser.close();
}
fs.writeFileSync(out, JSON.stringify(merged, null, 2));
const plugin = Object.values(merged.plugin);
console.log({
  pluginSelectors: plugin.length,
  inside: plugin.filter((p) => p.in && !p.out).length,
  outside: plugin.filter((p) => p.out && !p.in).length,
  mixed: plugin.filter((p) => p.in && p.out).length,
  unmatched: plugin.filter((p) => !p.in && !p.out).length,
  nativeReachingUI: Object.keys(merged.native).length,
  foreign: Object.keys(merged.foreign).length,
});
