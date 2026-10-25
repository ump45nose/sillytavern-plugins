// Builds the extension and commits it to the `release` branch, whose root is the installable
// extension directory (manifest.json at the top). Working branches do not track extension/dist.
// Does not push; prints the command instead.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const branch = process.env.WB_RELEASE_BRANCH || "release";
const git = (args, options = {}) => execFileSync("git", args, { encoding: "utf8", ...options }).trim();
const run = (command, args) => execFileSync(command, args, { stdio: "inherit" });

if (git(["status", "--porcelain", "--untracked-files=no"])) {
  console.error("Commit or set aside tracked changes first: the release must match a commit.");
  process.exit(1);
}
run("npm", ["run", "check"]);
run("npm", ["test"]);
run("npm", ["run", "build"]);

const source = git(["rev-parse", "--short", "HEAD"]);
const { version } = JSON.parse(fs.readFileSync("extension/manifest.json", "utf8"));
// Tracked extension files plus the fresh build; nothing stray (.DS_Store, editor files).
const files = [
  ...git(["ls-files", "extension"]).split("\n").filter(Boolean),
  ...fs
    .readdirSync("extension/dist", { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && /\.(js|css)(\.map)?$/.test(entry.name))
    .map((entry) => path.relative(".", path.join(entry.parentPath, entry.name))),
];

const tree = fs.mkdtempSync(path.join(os.tmpdir(), "wb-release-"));
const exists = git(["branch", "--list", branch]) !== "";
try {
  if (exists) git(["worktree", "add", tree, branch]);
  else {
    git(["worktree", "add", "--detach", tree]);
    git(["checkout", "--orphan", branch], { cwd: tree });
  }
  for (const entry of fs.readdirSync(tree)) if (entry !== ".git") fs.rmSync(path.join(tree, entry), { recursive: true });
  for (const file of files) {
    const target = path.join(tree, path.relative("extension", file));
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(file, target);
  }
  git(["add", "-A"], { cwd: tree });
  if (!git(["status", "--porcelain"], { cwd: tree })) console.log(`${branch} already matches ${source}.`);
  else {
    git(["commit", "-q", "-m", `release ${version} (${source})`], { cwd: tree });
    console.log(`Committed ${files.length} files to ${branch}: release ${version} (${source}).`);
    console.log(`Push when ready: git push origin ${branch}`);
  }
} finally {
  git(["worktree", "remove", "--force", tree]);
}
