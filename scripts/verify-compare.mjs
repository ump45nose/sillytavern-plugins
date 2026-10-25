// Compares two verify-all runs by what each script got through, not just its exit code: several
// scripts assert against the original dataset and fail on a fresh instance, so a regression shows up
// as a lost PASS line or a different first error rather than a changed exit code.
// Usage: node scripts/verify-compare.mjs <baseDir> <currentDir>
import fs from "node:fs";
import path from "node:path";

const [base, current] = process.argv.slice(2).map((dir) => path.resolve(dir));
const read = (dir, name) => {
  const file = path.join(dir, name);
  if (!fs.existsSync(file)) return null;
  const lines = fs.readFileSync(file, "utf8").split("\n");
  return {
    // A PASS line is keyed by its label; trailing JSON measurements vary run to run.
    passes: new Set(lines.filter((l) => l.startsWith("PASS")).map((l) => l.replace(/\s[[{].*$/, "").trim())),
    // First error line, with volatile parts (durations, ports, ids, paths) blanked.
    error:
      lines
        .find((l) => /Error|FAIL/.test(l))
        ?.replace(/\d+(\.\d+)?m?s\b/g, "#ms")
        .replace(/\b\d{3,}\b/g, "#")
        .trim() ?? null,
  };
};
let regressions = 0;
for (const name of fs.readdirSync(base).filter((f) => f.endsWith(".log"))) {
  const a = read(base, name);
  const b = read(current, name);
  const label = name.replace(/\.log$/, "");
  if (!b) {
    console.log(`MISS ${label}`);
    regressions++;
    continue;
  }
  const lost = [...a.passes].filter((p) => !b.passes.has(p));
  const gained = [...b.passes].filter((p) => !a.passes.has(p));
  const sameError = a.error === b.error;
  if (!lost.length && sameError) {
    console.log(`SAME ${label}${gained.length ? ` (+${gained.length} PASS)` : ""}`);
    continue;
  }
  if (lost.length) regressions++;
  console.log(`DIFF ${label}`);
  lost.forEach((p) => console.log(`  - ${p}`));
  gained.forEach((p) => console.log(`  + ${p}`));
  if (!sameError) console.log(`  base error: ${a.error}\n  curr error: ${b.error}`);
}
process.exit(regressions ? 1 : 0);
