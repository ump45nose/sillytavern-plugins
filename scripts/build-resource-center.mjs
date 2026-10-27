import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, "outputs/resource-center-link");
fs.mkdirSync(output, { recursive: true });
for (const [source, dest] of [
  ["resource-center-extension", "extension"],
  ["server/resource-center-link", "server"],
])
  fs.cpSync(path.join(root, source), path.join(output, dest), { recursive: true });
execFileSync("tar", [
  "-czf",
  path.join(root, "outputs/resource-center-link-2.0.0.tar.gz"),
  "-C",
  output,
  "extension",
  "server",
]);
console.log("Built outputs/resource-center-link-2.0.0.tar.gz");
