// Only report access state; no UI events or filenames enter diagnostics.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
const args = process.argv.slice(2);
const sourceIndex = args.indexOf("--source");
const source = sourceIndex >= 0 ? args[sourceIndex + 1] : path.join(os.homedir(),
  "Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/Library/Caches/ComputerUse/Skysight/segments");
try {
  fs.readdirSync(source);
  console.log(JSON.stringify({ readable: true }));
} catch (error) {
  const denied = ["EPERM", "EACCES"].includes(error.code);
  console.log(JSON.stringify({ readable: false, error: denied ? "authorization_required" : "activity_unavailable" }));
  process.exitCode = denied ? 2 : 1;
}
