import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dry = process.argv.includes("--dry"),
  target = process.env.ARC_TAVERN_ROOT || "/vol2/1000/Docker/sillytavern";
const stamp = new Date().toISOString().replace(/[:.]/g, "-"),
  backup = process.env.ARC_DEPLOY_BACKUP || path.join(root, "outputs", `resource-center-deployment-${stamp}`);
const steps = [
  ["resource-center-extension", "extensions/resource-center-link"],
  ["server/resource-center-link", "plugins/resource-center-link"],
];
if (fs.existsSync(path.join(target, "extensions/workbench")))
  steps.push(["extension", "extensions/workbench"]);
if (dry) {
  console.log(JSON.stringify({ target, backup, copy: steps, restart: "sillytavern" }, null, 2));
  process.exit(0);
}
for (;;) {
  const sockets = execFileSync(
    "docker",
    ["exec", process.env.ARC_TAVERN_CONTAINER || "sillytavern", "cat", "/proc/net/tcp", "/proc/net/tcp6"],
    { encoding: "utf8" },
  );
  const active = sockets.split("\n").some((line) => {
    const fields = line.trim().split(/\s+/);
    return (
      fields[3] === "01" &&
      parseInt(fields[1]?.split(":").at(-1), 16) !== 8000 &&
      parseInt(fields[2]?.split(":").at(-1), 16) !== 18323
    );
  });
  if (!active) break;
  console.log("等待酒馆当前出站请求结束后再重启");
  await new Promise((resolve) => setTimeout(resolve, 5000));
}
fs.mkdirSync(backup, { recursive: true, mode: 0o700 });
for (const [source, relative] of steps) {
  const dest = path.join(target, relative);
  if (fs.existsSync(dest)) fs.cpSync(dest, path.join(backup, relative), { recursive: true });
  fs.mkdirSync(dest, { recursive: true });
  fs.cpSync(path.join(root, source), dest, { recursive: true });
}
for (const user of fs
  .readdirSync(path.join(target, "data"), { withFileTypes: true })
  .filter((x) => x.isDirectory())) {
  const settings = path.join(target, "data", user.name, "settings.json");
  if (!fs.existsSync(settings)) continue;
  fs.copyFileSync(settings, path.join(backup, `${user.name}-settings.json`));
  const value = JSON.parse(fs.readFileSync(settings, "utf8")),
    e = value.extension_settings;
  if (!e) continue;
  e.disabledExtensions ??= [];
  if (!e.disabledExtensions.includes("third-party/ai-resource-center"))
    e.disabledExtensions.push("third-party/ai-resource-center");
  fs.writeFileSync(settings, JSON.stringify(value, null, 2));
}
execFileSync("docker", ["restart", process.env.ARC_TAVERN_CONTAINER || "sillytavern"], { stdio: "inherit" });
console.log(`Installed resource-center-link; rollback files: ${backup}`);
