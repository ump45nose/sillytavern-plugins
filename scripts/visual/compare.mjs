// Pixel-compares two capture directories; writes diff images and a summary.
// Usage: node scripts/visual/compare.mjs <baselineDir> <currentDir> [maxDiffRatio=0.001]
import fs from "node:fs";
import path from "node:path";
import { launch } from "../browser.mjs";

const [baseDir, currentDir] = process.argv.slice(2, 4).map((p) => path.resolve(p));
const limit = Number(process.argv[4] ?? 0.001);
const diffDir = path.join(currentDir, "diff");
fs.mkdirSync(diffDir, { recursive: true });

const browser = await launch();
const page = await (await browser.newContext()).newPage();
const results = [];
for (const file of fs
  .readdirSync(baseDir)
  .filter((f) => f.endsWith(".png"))
  .sort()) {
  const current = path.join(currentDir, file);
  if (!fs.existsSync(current)) {
    results.push({ file, missing: true });
    continue;
  }
  const encode = (p) => "data:image/png;base64," + fs.readFileSync(p).toString("base64");
  const result = await page.evaluate(
    async ({ a, b }) => {
      const load = (src) =>
        new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = reject;
          img.src = src;
        });
      const [ia, ib] = await Promise.all([load(a), load(b)]);
      if (ia.width !== ib.width || ia.height !== ib.height)
        return { sizeMismatch: [ia.width, ia.height, ib.width, ib.height] };
      const canvas = (img) => {
        const c = document.createElement("canvas");
        c.width = img.width;
        c.height = img.height;
        const g = c.getContext("2d");
        g.drawImage(img, 0, 0);
        return g.getImageData(0, 0, img.width, img.height);
      };
      const da = canvas(ia),
        db = canvas(ib);
      const out = document.createElement("canvas");
      out.width = ia.width;
      out.height = ia.height;
      const og = out.getContext("2d");
      const diff = og.createImageData(ia.width, ia.height);
      let changed = 0;
      for (let i = 0; i < da.data.length; i += 4) {
        const delta = Math.max(
          Math.abs(da.data[i] - db.data[i]),
          Math.abs(da.data[i + 1] - db.data[i + 1]),
          Math.abs(da.data[i + 2] - db.data[i + 2]),
        );
        const gray = (da.data[i] + da.data[i + 1] + da.data[i + 2]) / 3;
        if (delta > 24) {
          changed++;
          diff.data.set([255, 0, 0, 255], i);
        } else diff.data.set([gray, gray, gray, 70], i);
      }
      og.putImageData(diff, 0, 0);
      return { ratio: changed / (da.data.length / 4), changed, image: out.toDataURL("image/png") };
    },
    { a: encode(path.join(baseDir, file)), b: encode(current) },
  );
  if (result.image && result.changed)
    fs.writeFileSync(path.join(diffDir, file), Buffer.from(result.image.split(",")[1], "base64"));
  delete result.image;
  results.push({ file, ...result, pass: !result.sizeMismatch && result.ratio <= limit });
}
await browser.close();
fs.writeFileSync(path.join(currentDir, "compare.json"), JSON.stringify(results, null, 2));
let failed = 0;
for (const r of results) {
  const pass = r.pass;
  if (!pass) failed++;
  console.log(
    pass ? "SAME" : "DIFF",
    r.file,
    r.missing ? "missing" : r.sizeMismatch ? "size " + r.sizeMismatch : (r.ratio * 100).toFixed(3) + "%",
  );
}
console.log(`${results.length - failed}/${results.length} within ${(limit * 100).toFixed(2)}%`);
process.exitCode = failed ? 1 : 0;
