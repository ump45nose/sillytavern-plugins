// Captures named UI states from the seeded visual instance for pixel comparison.
// Usage: node scripts/visual/capture.mjs <outDir> [stateNameFilter]
// Sessions intercept settings saves (helper:false), so capturing never mutates the seeded data.
import fs from "node:fs";
import path from "node:path";
import { launch } from "../browser.mjs";
import { states, visit } from "./states.mjs";

const out = path.resolve(process.argv[2] || "artifacts/visual/current");
const filter = process.argv[3] ? new RegExp(process.argv[3]) : null;
fs.mkdirSync(out, { recursive: true });

const browser = await launch();
const report = [];
try {
  for (const state of states) {
    if (filter && !filter.test(state.name)) continue;
    try {
      const { errors } = await visit(browser, state, (page) =>
        page.screenshot({ path: path.join(out, state.name + ".png"), animations: "disabled", caret: "hide" }),
      );
      report.push({ name: state.name, ok: true, errors });
    } catch (error) {
      report.push({ name: state.name, ok: false, error: String(error.message || error).split("\n")[0] });
    }
  }
} finally {
  await browser.close();
}
fs.writeFileSync(path.join(out, "report.json"), JSON.stringify(report, null, 2));
for (const r of report)
  console.log(r.ok ? "OK  " : "FAIL", r.name, r.ok ? (r.errors.length ? r.errors : "") : r.error);
