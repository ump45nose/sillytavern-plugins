import { build } from "esbuild";
import { mkdir, readdir, writeFile, unlink } from "node:fs/promises";
import path from "node:path";
const directory = path.resolve("extension/dist");
const result = await build({
  entryPoints: {
    index: "src/index.tsx",
    "addons/outline/index": "src/addons/outline/index.tsx",
    "addons/image-gen/index": "src/addons/image-gen/index.tsx",
    "addons/record-export/index": "src/addons/record-export/index.tsx",
    "addons/record-export/export-worker": "src/addons/record-export/export-worker.ts",
  },
  outdir: directory,
  bundle: true,
  splitting: true,
  format: "esm",
  target: "es2022",
  minify: true,
  sourcemap: true,
  legalComments: "eof",
  write: false,
});
await mkdir(directory, { recursive: true });
for (const file of result.outputFiles) {
  await mkdir(path.dirname(file.path), { recursive: true });
  await writeFile(file.path, file.contents);
}
const current = new Set(
  result.outputFiles.map((file) => path.relative(directory, file.path)),
);
async function clean(folder) {
  for (const entry of await readdir(folder, { withFileTypes: true })) {
    const filename = path.join(folder, entry.name);
    if (entry.isDirectory()) await clean(filename);
    else if (!current.has(path.relative(directory, filename)) && /\.(js|css)(\.map)?$/.test(entry.name)) await unlink(filename);
  }
}
await clean(directory);
console.log(`Built ${result.outputFiles.length} assets into extension/dist`);
