// D1 spike: rewrites the built extension/dist/index.css into the layered model.
// Usage: node scripts/visual/spike-layer.mjs [audit=artifacts/cascade/audit.json]
//
// - Workbench rules that only reach isolated UI go into @layer wb.legacy.
// - Rules that reach native DOM stay unlayered (the future native-bridge.css).
// - Mixed or unobserved rules are emitted in both places (safe under the isolation rule).
// - Native element-level globals are copied to the head of wb.legacy, keeping their specificity contest.
// - One unlayered isolation rule reverts native unlayered styles inside workbench UI.
// Declarations are copied as source text: CSSOM re-serialization drops var() shorthands.
// Throwaway: `npm run build` restores the original bundle.
import fs from "node:fs";
import path from "node:path";
import { launch } from "../browser.mjs";
import { parse, splitList } from "./css-text.mjs";

const auditFile = path.resolve(process.argv[2] || "artifacts/cascade/audit.json");
const audit = JSON.parse(fs.readFileSync(auditFile, "utf8"));
const target = path.resolve("extension/dist/index.css");
const source = fs.readFileSync(target, "utf8");
const tree = parse(source);

// Normalize selectors the way the audit saw them (CSSOM selectorText).
const pieces = new Set();
const collect = (nodes) => {
  for (const node of nodes) {
    if (node.type === "rule") splitList(node.prelude).forEach((s) => pieces.add(s));
    else if (node.children) collect(node.children);
  }
};
collect(tree);
const browser = await launch();
let normalized;
try {
  const page = await browser.newPage();
  normalized = await page.evaluate(
    (list) => {
      const out = {};
      for (const s of list) {
        const sheet = new CSSStyleSheet();
        try {
          sheet.replaceSync(`${s}{}`);
          out[s] = sheet.cssRules[0]?.selectorText ?? null;
        } catch {
          out[s] = null;
        }
      }
      return out;
    },
    [...pieces],
  );
} finally {
  await browser.close();
}

const stats = { layer: 0, bridge: 0, both: 0, focusClones: 0 };
const focus = [];
const classify = (selector) => {
  const hit = audit.plugin[normalized[selector]];
  const kind = !hit || (hit.in && hit.out) || (!hit.in && !hit.out) ? "both" : hit.in ? "layer" : "bridge";
  stats[kind]++;
  return kind;
};
const walk = (nodes, wrappers) => {
  let layered = "",
    unlayered = "";
  for (const node of nodes) {
    if (node.type === "rule") {
      const layer = [],
        bridge = [];
      for (const selector of splitList(node.prelude)) {
        const kind = classify(selector);
        if (kind !== "bridge") layer.push(selector);
        if (kind !== "layer") bridge.push(selector);
      }
      if (layer.length) {
        layered += `${layer.join(",")}{${node.body}}`;
        // Native dynamic-styles.js does not look inside @layer; keep its :hover→:focus-visible parity.
        const hover = layer.filter((s) => s.includes(":hover") && !s.includes("::"));
        if (hover.length) {
          const clone = `${hover.map((s) => s.replace(/:hover/g, ":focus-visible")).join(",")}{${node.body}}`;
          focus.push(wrappers.reduceRight((inner, w) => `${w}{${inner}}`, clone));
          stats.focusClones++;
        }
      }
      if (bridge.length) unlayered += `${bridge.join(",")}{${node.body}}`;
    } else if (node.type === "group") {
      const [l, u] = walk(node.children, [...wrappers, node.prelude]);
      if (l) layered += `${node.prelude}{${l}}`;
      if (u) unlayered += `${node.prelude}{${u}}`;
    } else unlayered += node.text; // @keyframes, @font-face, @import, comments: global and unlayered.
  }
  return [layered, unlayered];
};
const [layered, unlayered] = walk(tree, []);

// Native element-level rules (no class/id in the subject, not body/html/:root) become the reset layer.
const upstream = "upstream/SillyTavern/public/";
const reset = [];
const isGlobal = (s) => {
  const bare = s.replace(/::?[\w-]+(\([^)]*\))?/g, "").replace(/\[[^\]]*\]/g, "");
  return !/[.#&]/.test(bare) && !/\b(body|html)\b|:root/.test(s);
};
for (const file of ["style.css", "css/st-tailwind.css"]) {
  const visit = (nodes, wrappers) => {
    for (const node of nodes) {
      if (node.type === "rule" && splitList(node.prelude).some(isGlobal))
        reset.push(wrappers.reduceRight((inner, w) => `${w}{${inner}}`, `${node.prelude}{${node.body}}`));
      else if (node.type === "group") visit(node.children, [...wrappers, node.prelude]);
    }
  };
  visit(parse(fs.readFileSync(upstream + file, "utf8")), []);
}

const scope = ":is(#wb-root,#wb-layout-root,.wb-ui,#wb-x#wb-x#wb-x#wb-x#wb-x)";
const leased = ":not(.wb-native-embedded,.wb-native-embedded *)";
const css = [
  "@layer wb.legacy;",
  `@layer wb.legacy{${reset.join("\n")}\n${layered}${focus.join("")}}`,
  unlayered,
  `${scope}${leased},${scope} *${leased}{all:revert-layer}`,
].join("\n");
fs.writeFileSync(target, css);
console.log({ ...stats, resetRules: reset.length, bytes: [source.length, css.length] });
