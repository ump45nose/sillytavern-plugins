"""Check the current Git index and all Git refs without printing credential values."""
from pathlib import Path
import io
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "github_token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b",
    "api_key": rb"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b",
    "google_token": rb"\bya29\.[A-Za-z0-9_-]{25,}",
    "aws_key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "telegram_token": rb"\b[0-9]{8,12}:[A-Za-z0-9_-]{35}\b",
    "jwt": rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b",
    "credential_url": rb"(?i)(?:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]{8,}@",
    "credential_assignment": rb"(?im)\b(?:api_key|access_token|refresh_token|client_secret|password|bearer_token)\s*[=:]\s*[\"']([A-Za-z0-9_./+-]{24,})[\"']",
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    objects = {}
    problems = []
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split()
        path = raw_path.decode()
        parts = Path(path).parts
        if stage != "0" or mode == "160000":
            problems.append((path, "unmerged_or_nested_repository"))
        if mode == "120000" and not (ROOT / path).resolve().is_relative_to(ROOT):
            problems.append((path, "external_symlink"))
        if any(p in {".git", ".venv", ".build", "data", "runtime", "backups", "dist"} for p in parts):
            problems.append((path, "runtime_file"))
        if (Path(path).name.startswith(".env") and Path(path).name != ".env.example") or path.endswith((".token", ".pem", ".db", ".sqlite", ".sqlite3")):
            problems.append((path, "private_file"))
        if path in {"legacy/plaud/config.yaml", "legacy/plaud/daily-v3.yaml"}:
            problems.append((path, "device_configuration"))
        objects[oid] = path
    for line in git("rev-list", "--objects", "--all").decode().splitlines():
        oid, _, path = line.partition(" ")
        objects.setdefault(oid, path or "history")
    result = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT,
                            input=("\n".join(objects) + "\n").encode(),
                            capture_output=True, check=True)
    stream = io.BytesIO(result.stdout)
    blobs = 0
    for oid, path in objects.items():
        header = stream.readline().decode().strip().split()
        if len(header) != 3 or header[0] != oid:
            raise RuntimeError("Git object unavailable: " + path)
        size = int(header[2])
        data = stream.read(size)
        assert stream.read(1) == b"\n"
        if header[1] != "blob":
            continue
        blobs += 1
        for category, pattern in PATTERNS.items():
            if re.search(pattern, data):
                problems.append((path, category))
    for path, category in sorted(set(problems)):
        print("candidate:", path, category)
    if problems:
        raise SystemExit("publication_audit_failed: inspect candidates privately")
    print(f"publication_audit_ok blobs={blobs} index_and_all_refs=true credential_candidates=0 private_files=0")


if __name__ == "__main__":
    main()
