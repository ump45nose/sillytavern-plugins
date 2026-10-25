// Runs every verify:* script sequentially and writes one log per script plus a summary.
// Usage: node scripts/verify-all.mjs <outDir> [nameFilter]
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const out = path.resolve(process.argv[2] || "artifacts/verify/current");
const filter = process.argv[3] ? new RegExp(process.argv[3]) : null;
const scripts = Object.keys(JSON.parse(fs.readFileSync("package.json", "utf8")).scripts).filter(
  (name) =>
    (name === "verify" || name.startsWith("verify:")) &&
    name !== "verify:styles" &&
    (!filter || filter.test(name)),
);
fs.mkdirSync(out, { recursive: true });
const summary = [];
for (const name of scripts) {
  const started = Date.now();
  const run = spawnSync("npm", ["run", "-s", name], { encoding: "utf8", timeout: 15 * 60_000 });
  const seconds = Math.round((Date.now() - started) / 1000);
  fs.writeFileSync(path.join(out, name + ".log"), (run.stdout || "") + (run.stderr || ""));
  const line = `${name} exit=${run.status ?? "timeout"} ${seconds}s`;
  summary.push(line);
  console.log(line);
}
fs.writeFileSync(path.join(out, "summary.txt"), summary.join("\n") + "\n");
