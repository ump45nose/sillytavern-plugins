"""用临时 Git 仓库验证跨仓任务的隔离与收尾，不修改真实工程。"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "max-git.py"


class MaxGitFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="max-git-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Max"
        self.root.mkdir()
        self.init(self.root)
        (self.root / "scripts").mkdir()
        shutil.copyfile(SCRIPT, self.root / "scripts/max-git.py")
        (self.root / ".gitignore").write_text("/.worktrees/\n")
        for name in ["orca", "magic-link"]:
            repo = self.root / name
            repo.mkdir()
            self.init(repo)
            (repo / "code.txt").write_text(f"{name} base\n")
            self.git(repo, "add", "code.txt")
            self.git(repo, "commit", "-m", "base")
            self.git(self.root, "config", "-f", ".gitmodules", f"submodule.{name}.path", name)
            self.git(self.root, "config", "-f", ".gitmodules", f"submodule.{name}.url", str(repo))
            head = self.head(repo)
            self.git(self.root, "update-index", "--add", "--cacheinfo", f"160000,{head},{name}")
        self.git(self.root, "add", ".gitignore", ".gitmodules", "scripts/max-git.py")
        self.git(self.root, "commit", "-m", "workspace")

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def init(self, repo):
        self.git(repo, "init", "-b", "main")
        for key, value in [("user.name", "Max Git Test"), ("user.email", "test@example.invalid"),
                           ("commit.gpgSign", "false"), ("core.hooksPath", "/dev/null")]:
            self.git(repo, "config", key, value)

    def head(self, repo):
        return self.git(repo, "rev-parse", "HEAD")

    def command(self, root, *args, success=True):
        result = subprocess.run([sys.executable, str(root / "scripts/max-git.py"), *args],
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def start(self):
        self.command(self.root, "start", "sample", "orca", "magic-link")
        return self.root / ".worktrees/sample"

    def change_and_commit(self, task):
        for name in ["orca", "magic-link"]:
            (task / name / "code.txt").write_text(f"{name} task\n")
        self.command(task, "commit", "-m", "task change")

    def test_isolate_diff_commit_merge_and_clean(self):
        original = {name: self.head(self.root / name) for name in ["orca", "magic-link"]}
        parent_index = self.git(self.root, "ls-files", "--stage")
        task = self.start()
        (task / "orca/code.txt").rename(task / "orca/renamed.txt")
        (task / "magic-link/code.txt").write_text("changed\n")
        (task / "magic-link/new.txt").write_text("new file\n")
        (task / "magic-link/binary.dat").write_bytes(bytes(range(256)))
        output = self.command(task, "diff").stdout
        for value in ["=== orca", "=== magic-link", "renamed.txt", "new file", "GIT binary patch"]:
            self.assertIn(value, output)
        for name in original:
            self.assertEqual(self.head(self.root / name), original[name])
            self.assertEqual((self.root / name / "code.txt").read_text(), f"{name} base\n")
        self.command(task, "commit", "-m", "cross-repository change")
        self.assertIn("changed", self.command(task, "diff").stdout)
        self.assertIn("任务提交：1", self.command(task, "status").stdout)
        self.command(task, "merge")
        self.assertEqual((self.root / "magic-link/new.txt").read_text(), "new file\n")
        self.assertTrue((self.root / "orca/renamed.txt").exists())
        self.assertEqual(self.git(self.root, "ls-files", "--stage"), parent_index)
        self.command(task, "clean")
        self.assertFalse(task.exists())
        for name in original:
            self.assertEqual(len(self.git(self.root / name, "worktree", "list").splitlines()), 1)
            self.git(self.root / name, "rev-parse", "refs/heads/codex/max/sample")

    def test_dirty_original_is_not_copied_or_partially_merged(self):
        before = self.head(self.root / "magic-link")
        (self.root / "orca/code.txt").write_text("pending original\n")
        task = self.start()
        self.assertEqual((task / "orca/code.txt").read_text(), "orca base\n")
        self.change_and_commit(task)
        result = self.command(task, "merge", "magic-link", "orca", success=False)
        self.assertIn("原工作区有未提交改动", result.stderr)
        self.assertEqual(self.head(self.root / "magic-link"), before)
        self.assertEqual((self.root / "orca/code.txt").read_text(), "pending original\n")
        self.command(task, "clean", success=False)
        self.assertTrue((task / "magic-link/.git").exists())

    def test_cleanup_keeps_all_uncommitted_worktrees(self):
        task = self.start()
        (task / "magic-link/new.txt").write_text("unfinished\n")
        self.command(task, "cleanup", success=False)
        for name in ["orca", "magic-link"]:
            self.assertTrue((task / name / ".git").exists())
        self.assertEqual((task / "magic-link/new.txt").read_text(), "unfinished\n")

    def test_codex_setup_cleanup_and_restore(self):
        task = Path(self.temp.name) / "Native"
        self.git(self.root, "worktree", "add", "--detach", str(task), "HEAD")
        self.command(task, "setup")
        self.command(task, "setup")
        for name in ["orca", "magic-link"]:
            self.assertEqual(len(self.git(self.root / name, "worktree", "list").splitlines()), 2)
        self.change_and_commit(task)
        branch = self.git(task / "orca", "branch", "--show-current")
        commit = self.head(task / "orca")
        self.command(task, "cleanup")
        self.assertTrue(task.exists())
        self.assertEqual(self.git(self.root / "orca", "rev-parse", branch), commit)
        self.command(task, "setup")
        self.assertEqual(self.head(task / "orca"), commit)
        self.command(task, "merge")
        self.command(task, "clean")
        self.assertTrue(task.exists())
        self.assertFalse((task / "orca").exists())

    def test_diverged_original_requires_explicit_resolution(self):
        task = self.start()
        self.change_and_commit(task)
        (self.root / "orca/other.txt").write_text("another task\n")
        self.git(self.root / "orca", "add", "other.txt")
        self.git(self.root / "orca", "commit", "-m", "other change")
        result = self.command(task, "merge", success=False)
        self.assertIn("分支分歧", result.stderr)
        self.assertEqual((self.root / "orca/code.txt").read_text(), "orca base\n")

    def test_changed_original_branch_requires_return_to_target(self):
        task = self.start()
        self.change_and_commit(task)
        self.git(self.root / "orca", "switch", "-c", "other")
        result = self.command(task, "merge", success=False)
        self.assertIn("切回任务启动时的分支 main", result.stderr)

    def test_parent_notes_survive_cleanup_refusal(self):
        task = self.start()
        (task / "notes.md").write_text("keep this note\n")
        result = self.command(task, "clean", success=False)
        self.assertIn("Max 父仓有未提交文件", result.stderr)
        self.assertEqual((task / "notes.md").read_text(), "keep this note\n")

    def test_status_lists_existing_and_managed_worktrees(self):
        native = Path(self.temp.name) / "ExistingCodexWorktree"
        self.git(self.root, "worktree", "add", "--detach", str(native), "HEAD")
        task = self.start()
        output = self.command(self.root, "status").stdout
        self.assertIn(str(native), output)
        self.assertIn(str(task / "orca"), output)
        self.assertIn("codex/max/sample", output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
