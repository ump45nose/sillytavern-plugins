// One-off B3 migration: splits the legacy stylesheets into layered UI rules and the unlayered native bridge.
// Usage: node scripts/visual/migrate-layers.mjs [audit=artifacts/cascade/audit.json]
// Requires a fresh audit of the unmigrated build. Writes src/styles/** and prints a classification summary.
import fs from "node:fs";
import path from "node:path";
import { launch } from "../browser.mjs";
import { parse, splitList } from "./css-text.mjs";
import { createClassifier } from "./classify.mjs";

const audit = JSON.parse(
  fs.readFileSync(path.resolve(process.argv[2] || "artifacts/cascade/audit.json"), "utf8"),
);
const order = [
  "style",
  "home",
  "controls",
  "resources",
  "workspace",
  "rework",
  "polish",
  "selection",
  "preferences",
  "rp",
  "layout",
  "utility",
  "addon-shell",
  "mobile",
];
const addons = ["outline", "image-gen", "record-export"];
const sources = [
  ...order.map((name) => ({ name, file: `src/${name}.css` })),
  ...addons.map((name) => ({ name, file: `src/addons/${name}/style.css`, addon: true })),
];
const trees = sources.map((s) => ({ ...s, tree: parse(fs.readFileSync(s.file, "utf8")) }));

// The audit keys selectors by CSSOM serialization; normalize source spellings the same way.
const pieces = new Set();
const collect = (nodes) => {
  for (const node of nodes) {
    if (node.type === "rule") splitList(node.prelude).forEach((s) => pieces.add(s));
    else if (node.children) collect(node.children);
  }
};
trees.forEach((t) => collect(t.tree));
const browser = await launch();
let normalized;
try {
  normalized = await (
    await browser.newPage()
  ).evaluate(
    (list) => {
      const out = {};
      for (const s of list) {
        const sheet = new CSSStyleSheet();
        try {
          sheet.replaceSync(`${s}{}`);
          out[s] = sheet.cssRules[0]?.selectorText ?? s;
        } catch {
          out[s] = s;
        }
      }
      return out;
    },
    [...pieces],
  );
} finally {
  await browser.close();
}

const { classify } = createClassifier(audit);
const stats = {};
const indent = (text, pad) =>
  text
    .split("\n")
    .map((line) => (line.trim() ? pad + line : line))
    .join("\n");

// Explicit :focus-visible rules already present (native dynamic-styles.js skips those bases too).
const explicitFocus = new Set();
trees.forEach((t) => {
  const visit = (nodes) =>
    nodes.forEach((n) =>
      n.type === "rule"
        ? splitList(n.prelude)
            .filter((s) => s.includes(":focus-visible"))
            .forEach((s) => explicitFocus.add(s.replace(/:focus-visible/g, ":hover")))
        : n.children && visit(n.children),
    );
  visit(t.tree);
});
// Layered rules are invisible to dynamic-styles.js, so hover parity for keyboard focus is written out.
const withFocus = (selector) =>
  selector.includes(":hover") && !selector.includes("::") && !explicitFocus.has(selector)
    ? selector.replace(/(?<!:not\([^)]*):hover/g, ":is(:hover, :focus-visible)")
    : selector;

/** Returns [layered, bridge] text for a node list. */
function split(nodes, name) {
  let layered = "",
    bridge = "",
    pending = "";
  for (const node of nodes) {
    if (node.type === "raw") {
      if (node.text.startsWith("/*")) pending += node.text + "\n";
      else layered += pending + node.text + "\n"; // @keyframes and friends stay with UI rules.
      if (!node.text.startsWith("/*")) pending = "";
      continue;
    }
    if (node.type === "group") {
      const [l, b] = split(node.children, name);
      if (l.trim()) layered += `${pending}${node.prelude} {\n${indent(l.trim(), "  ")}\n}\n`;
      if (b.trim()) bridge += `${l.trim() ? "" : pending}${node.prelude} {\n${indent(b.trim(), "  ")}\n}\n`;
      pending = "";
      continue;
    }
    const layer = [],
      native = [];
    for (const selector of splitList(node.prelude)) {
      const kind = classify(normalized[selector] ?? selector);
      (stats[name] ??= { layer: 0, bridge: 0, both: 0 })[kind]++;
      if (kind !== "bridge") layer.push(withFocus(selector));
      if (kind !== "layer") native.push(selector);
    }
    const body = node.body.replace(/^\n?/, "\n").replace(/\s*$/, "\n");
    if (layer.length) layered += `${pending}${layer.join(",\n")} {${body}}\n`;
    if (native.length) bridge += `${layer.length ? "" : pending}${native.join(",\n")} {${body}}\n`;
    pending = "";
  }
  return [layered, bridge];
}

fs.mkdirSync("src/styles/legacy", { recursive: true });
let bridgeAll = "";
for (const { name, file, tree, addon } of trees) {
  const [layered, bridge] = split(tree, name);
  const header = `/* Legacy ${name} styles (0.4.0), layered. Shrinks as screens move to wb.components. */\n`;
  const out = header + `@layer wb.legacy {\n${indent(layered.trim(), "  ")}\n}\n`;
  if (addon) {
    // Addon sheets load lazily on their own; their bridge part (if any) stays in the same file.
    fs.writeFileSync(file, out + (bridge.trim() ? `\n/* Native bridge */\n${bridge}` : ""));
  } else {
    fs.writeFileSync(`src/styles/legacy/${name}.css`, out);
    if (bridge.trim()) bridgeAll += `\n/* ── from ${name}.css ── */\n${bridge}`;
  }
}

fs.writeFileSync(
  "src/styles/native-bridge.css",
  `/*
 * Native bridge: the only unlayered workbench stylesheet.
 * Restyles SillyTavern's own DOM (#sheld, #chat, #send_form, leased settings) in place, so it must
 * compete with native unlayered rules; this is the only place where !important is allowed.
 * Everything inside workbench UI lives in @layer and is shielded by the isolation rule at the end.
 */
${bridgeAll}
/*
 * Isolation: inside workbench UI, revert every unlayered (native) declaration back to the layered
 * workbench styles. The impossible #wb-x argument lifts specificity to (5,1,0) so native ID selectors
 * cannot outrank it. Leased native controls (.wb-native-embedded) keep their native styles.
 */
:is(#wb-root, #wb-layout-root, .wb-ui, #wb-x#wb-x#wb-x#wb-x#wb-x):not(.wb-native-embedded, .wb-native-embedded *),
:is(#wb-root, #wb-layout-root, .wb-ui, #wb-x#wb-x#wb-x#wb-x#wb-x) *:not(.wb-native-embedded, .wb-native-embedded *) {
  all: revert-layer;
}
`,
);

// Native element defaults that reach workbench UI today, copied verbatim so specificity contests are unchanged.
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
        reset.push(
          wrappers.reduceRight(
            (inner, w) => `${w} {\n${indent(inner, "  ")}\n}`,
            `${node.prelude} {${node.body.replace(/^\n?/, "\n").replace(/\s*$/, "\n")}}`,
          ),
        );
      else if (node.type === "group") visit(node.children, [...wrappers, node.prelude]);
    }
  };
  visit(parse(fs.readFileSync(upstream + file, "utf8")), []);
}
fs.writeFileSync(
  "src/styles/legacy/native-defaults.css",
  `/*
 * Element defaults copied verbatim from SillyTavern 1.19.0 (public/style.css, public/css/st-tailwind.css;
 * AGPL-3.0, https://github.com/SillyTavern/SillyTavern). The isolation rule shields workbench UI from
 * native globals; these copies keep today's look until wb.base takes over in the redesign, then go away.
 * They sit at the head of wb.legacy so their specificity contest with legacy rules is unchanged.
 */
@layer wb.legacy {
${indent(reset.join("\n"), "  ")}
}
`,
);

fs.writeFileSync(
  "src/styles/index.css",
  `/* Workbench stylesheet entry. Layer order is declared once, before any sheet (including lazy ones) loads. */
@layer wb.reset, wb.tokens, wb.base, wb.legacy, wb.components, wb.layouts, wb.modes;

@import "./legacy/native-defaults.css";
${order.map((n) => `@import "./legacy/${n}.css";`).join("\n")}
@import "./native-bridge.css";
`,
);
console.log(stats);
