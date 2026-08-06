#!/usr/bin/env python3
"""Capture Git-backed deployment provenance and verify a read-only client inventory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

SPEC_SCHEMA = "openclaw-client-deployment-spec-v1"
MANIFEST_SCHEMA = "openclaw-client-deployment-provenance-v1"
INVENTORY_SCHEMA = "openclaw-scheduler-inventory-v1"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HIGH_CONFIDENCE_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[opsu]_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]+:[^@\s/]+@"),
)


class ContractError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ContractError(f"cannot safely open deployed file: {path.name}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ContractError(f"deployed target is not a regular file: {path.name}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                digest.update(chunk)
    finally:
        os.close(fd)
    return size, digest.hexdigest()


def run_git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=text,
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() if text else "git command failed"
        raise ContractError(detail or "git command failed")
    return proc.stdout


def validate_relative(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or any(ord(ch) < 32 for ch in value)
    ):
        raise ContractError(f"invalid {label} path")
    lexical_parts = value.split("/")
    if value.startswith("/") or any(part in ("", ".", "..") for part in lexical_parts):
        raise ContractError(f"unsafe {label} path: {value}")
    if contains_high_confidence_secret(value):
        raise ContractError(f"{label} path contains a possible secret")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ContractError(f"unsafe {label} path: {value}")
    return path.as_posix()


def reject_unknown(row: dict[str, object], allowed: set[str], label: str) -> None:
    unknown = set(row) - allowed
    if unknown:
        raise ContractError(f"unknown {label} fields: {sorted(unknown)}")


def load_json_bytes(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a JSON object")
    return value


def load_json_file(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink():
        raise ContractError(f"{label} symlink is not allowed")
    try:
        return load_json_bytes(path.read_bytes(), label)
    except OSError as exc:
        raise ContractError(f"{label} is not readable: {exc}") from exc


def canonical_remote(value: str) -> str:
    value = value.strip()
    if not value or any(ch in value for ch in "\r\n\x00"):
        raise ContractError("origin remote is missing or invalid")
    if contains_high_confidence_secret(value):
        raise ContractError("origin remote must not contain credentials or secrets")
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment or not parsed.hostname:
            raise ContractError("origin remote must not contain credentials, query, or fragment")
        if parsed.scheme == "https":
            if parsed.username is not None or parsed.password is not None:
                raise ContractError("origin remote must not contain credentials, query, or fragment")
        elif parsed.scheme == "ssh":
            if parsed.username not in (None, "git") or parsed.password is not None:
                raise ContractError("origin remote must not contain credentials, query, or fragment")
        else:
            raise ContractError("origin remote must use a supported canonical URL")
        remote_path = parsed.path.lstrip("/")
    else:
        match = re.fullmatch(r"git@([A-Za-z0-9.-]+):(.+)", value)
        if not match:
            raise ContractError("origin remote must be a canonical HTTPS/SSH Git URL")
        remote_path = match.group(2)
    if not remote_path or "\\" in remote_path or any(
        part in ("", ".", "..") for part in remote_path.split("/")
    ):
        raise ContractError("origin remote path is invalid")
    return value


def contains_high_confidence_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in HIGH_CONFIDENCE_SECRET_PATTERNS)


def validate_managed_roots(raw_roots: object) -> list[str]:
    if not isinstance(raw_roots, list) or not raw_roots:
        raise ContractError("managedRoots must be a non-empty array")
    roots: list[str] = []
    for value in raw_roots:
        root = validate_relative(value, label="managed root")
        if root in roots:
            raise ContractError(f"duplicate managed root: {root}")
        roots.append(root)
    roots.sort()
    for index, root in enumerate(roots):
        root_path = PurePosixPath(root)
        for other in roots[index + 1 :]:
            if PurePosixPath(other).is_relative_to(root_path):
                raise ContractError(f"managed roots must not overlap: {root}, {other}")
    return roots


def validate_job_namespace(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or contains_high_confidence_secret(value):
        raise ContractError("jobNamespace is invalid")
    return value.strip()


def validate_spec(data: dict[str, object]) -> tuple[list[dict[str, str]], list[str], str, list[dict[str, str]]]:
    reject_unknown(data, {"schema", "managedRoots", "jobNamespace", "files", "jobs"}, "spec")
    if data.get("schema") != SPEC_SCHEMA:
        raise ContractError("unsupported deployment spec schema")
    raw_files = data.get("files")
    raw_roots = data.get("managedRoots")
    raw_jobs = data.get("jobs")
    namespace = data.get("jobNamespace")
    if not isinstance(raw_files, list) or not raw_files:
        raise ContractError("spec files must be a non-empty array")
    if not isinstance(raw_jobs, list):
        raise ContractError("spec jobs must be an array")
    roots = validate_managed_roots(raw_roots)
    namespace = validate_job_namespace(namespace)

    files: list[dict[str, str]] = []
    sources: set[str] = set()
    targets: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ContractError("spec file entry must be an object")
        reject_unknown(raw, {"source", "target"}, "file")
        source = validate_relative(raw.get("source"), label="source")
        target = validate_relative(raw.get("target"), label="target")
        if source in sources:
            raise ContractError(f"duplicate source path: {source}")
        if target in targets:
            raise ContractError(f"duplicate target path: {target}")
        if not any(PurePosixPath(target).is_relative_to(PurePosixPath(root)) for root in roots):
            raise ContractError(f"target is outside managed roots: {target}")
        sources.add(source)
        targets.add(target)
        files.append({"source": source, "target": target})

    jobs: list[dict[str, str]] = []
    names: set[str] = set()
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            raise ContractError("spec job entry must be an object")
        reject_unknown(raw, {"name", "schedule", "command"}, "job")
        name = raw.get("name")
        schedule = raw.get("schedule")
        command = raw.get("command")
        if not all(isinstance(value, str) and value.strip() for value in (name, schedule, command)):
            raise ContractError("job name, schedule, and command must be non-empty strings")
        name, schedule, command = name.strip(), schedule.strip(), command.strip()
        if not name.startswith(namespace):
            raise ContractError(f"managed job name must start with namespace {namespace}")
        if name in names:
            raise ContractError(f"duplicate job name: {name}")
        if contains_high_confidence_secret(command):
            raise ContractError(f"job command contains a possible secret: {name}")
        names.add(name)
        jobs.append({"name": name, "schedule": schedule, "command": command})
    return sorted(files, key=lambda row: row["target"]), roots, namespace, sorted(jobs, key=lambda row: row["name"])


def tracked_blob(repo: Path, relative: str) -> tuple[bytes, str]:
    tree_line = str(run_git(repo, "ls-tree", "HEAD", "--", relative)).strip()
    if not tree_line:
        raise ContractError(f"source is not tracked at HEAD: {relative}")
    mode = tree_line.split(None, 1)[0]
    if mode not in {"100644", "100755"}:
        raise ContractError(f"source must be a regular tracked file: {relative}")
    data = run_git(repo, "show", f"HEAD:{relative}", text=False)
    assert isinstance(data, bytes)
    return data, mode


def capture(repo_value: str, spec_value: str) -> dict[str, object]:
    repo_input = Path(repo_value).expanduser()
    if repo_input.is_symlink():
        raise ContractError("repository symlink is not allowed")
    try:
        repo = repo_input.resolve(strict=True)
    except OSError as exc:
        raise ContractError(f"repository is not readable: {exc}") from exc
    root = Path(str(run_git(repo, "rev-parse", "--show-toplevel")).strip()).resolve()
    if root != repo or not repo.is_dir():
        raise ContractError("--repo must be the Git repository root")
    status = str(run_git(repo, "status", "--porcelain=v1", "--untracked-files=all"))
    if status.strip():
        raise ContractError("repository must be clean; tracked and untracked changes are not allowed")
    commit = str(run_git(repo, "rev-parse", "HEAD")).strip()
    if not HEX_40.fullmatch(commit):
        raise ContractError("HEAD is not a full Git commit")
    remote = canonical_remote(str(run_git(repo, "remote", "get-url", "origin")))

    spec_path = validate_relative(spec_value, label="spec")
    spec_bytes, _ = tracked_blob(repo, spec_path)
    spec = load_json_bytes(spec_bytes, "deployment spec")
    files, roots, namespace, jobs = validate_spec(spec)

    manifest_files: list[dict[str, object]] = []
    for row in files:
        content, mode = tracked_blob(repo, row["source"])
        manifest_files.append(
            {
                "source": row["source"],
                "target": row["target"],
                "mode": mode,
                "bytes": len(content),
                "sha256": sha256_bytes(content),
            }
        )
    return {
        "schema": MANIFEST_SCHEMA,
        "source": {
            "repository": remote,
            "commit": commit,
            "specPath": spec_path,
            "specSha256": sha256_bytes(spec_bytes),
        },
        "managedRoots": roots,
        "jobNamespace": namespace,
        "files": manifest_files,
        "jobs": [
            {
                "name": row["name"],
                "schedule": row["schedule"],
                "commandSha256": sha256_bytes(row["command"].encode("utf-8")),
            }
            for row in jobs
        ],
    }


def validate_manifest(data: dict[str, object]) -> tuple[list[dict[str, object]], list[str], str, list[dict[str, str]]]:
    reject_unknown(data, {"schema", "source", "managedRoots", "jobNamespace", "files", "jobs"}, "manifest")
    if data.get("schema") != MANIFEST_SCHEMA:
        raise ContractError("unsupported provenance manifest schema")
    source = data.get("source")
    if not isinstance(source, dict):
        raise ContractError("manifest source must be an object")
    reject_unknown(source, {"repository", "commit", "specPath", "specSha256"}, "manifest source")
    repository = source.get("repository")
    commit = source.get("commit")
    spec_hash = source.get("specSha256")
    canonical_remote(repository if isinstance(repository, str) else "")
    if not isinstance(commit, str) or not HEX_40.fullmatch(commit):
        raise ContractError("manifest commit is invalid")
    validate_relative(source.get("specPath"), label="manifest spec")
    if not isinstance(spec_hash, str) or not HEX_64.fullmatch(spec_hash):
        raise ContractError("manifest spec hash is invalid")

    raw_roots = data.get("managedRoots")
    raw_namespace = data.get("jobNamespace")
    raw_files = data.get("files")
    raw_jobs = data.get("jobs")
    if not isinstance(raw_files, list) or not isinstance(raw_jobs, list):
        raise ContractError("manifest files/jobs must be arrays")
    roots = validate_managed_roots(raw_roots)
    namespace = validate_job_namespace(raw_namespace)

    files: list[dict[str, object]] = []
    sources: set[str] = set()
    targets: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            raise ContractError("manifest file entry must be an object")
        reject_unknown(raw, {"source", "target", "mode", "bytes", "sha256"}, "manifest file")
        source_path = validate_relative(raw.get("source"), label="manifest source")
        target = validate_relative(raw.get("target"), label="manifest target")
        mode, size, digest = raw.get("mode"), raw.get("bytes"), raw.get("sha256")
        if source_path in sources or target in targets:
            raise ContractError("manifest contains duplicate source or target")
        if mode not in {"100644", "100755"} or not isinstance(size, int) or size < 0:
            raise ContractError(f"manifest metadata is invalid for {target}")
        if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
            raise ContractError(f"manifest sha256 is invalid for {target}")
        if not any(PurePosixPath(target).is_relative_to(PurePosixPath(root)) for root in roots):
            raise ContractError(f"manifest target is outside managed roots: {target}")
        sources.add(source_path)
        targets.add(target)
        files.append({"source": source_path, "target": target, "mode": mode, "bytes": size, "sha256": digest})
    if not files:
        raise ContractError("manifest files must not be empty")

    jobs: list[dict[str, str]] = []
    names: set[str] = set()
    for raw in raw_jobs:
        if not isinstance(raw, dict):
            raise ContractError("manifest job entry must be an object")
        reject_unknown(raw, {"name", "schedule", "commandSha256"}, "manifest job")
        name, schedule, command_hash = raw.get("name"), raw.get("schedule"), raw.get("commandSha256")
        if not isinstance(name, str) or not name.startswith(namespace) or name in names:
            raise ContractError("manifest job name/namespace is invalid or duplicated")
        if not isinstance(schedule, str) or not schedule.strip():
            raise ContractError(f"manifest job schedule is invalid: {name}")
        if not isinstance(command_hash, str) or not HEX_64.fullmatch(command_hash):
            raise ContractError(f"manifest command hash is invalid: {name}")
        names.add(name)
        jobs.append({"name": name, "schedule": schedule.strip(), "commandSha256": command_hash})
    return sorted(files, key=lambda row: str(row["target"])), roots, namespace, sorted(jobs, key=lambda row: row["name"])


def safe_deployment_root(value: str) -> Path:
    lexical = Path(os.path.abspath(os.path.expanduser(value)))
    if lexical.is_symlink() or not lexical.is_dir():
        raise ContractError("deployment root must be a directory, not a symlink")
    return lexical.resolve(strict=True)


def assert_no_symlink_components(root: Path, relative: str) -> None:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if not os.path.lexists(current):
            return
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ContractError(f"symlink path component is not allowed: {relative}")


def inventory_managed_files(root: Path, managed_roots: list[str]) -> set[str]:
    found: set[str] = set()
    for relative_root in managed_roots:
        assert_no_symlink_components(root, relative_root)
        managed = root / Path(*PurePosixPath(relative_root).parts)
        if not managed.exists():
            continue
        if managed.is_symlink() or not managed.is_dir():
            raise ContractError(f"managed root is not a safe directory: {relative_root}")
        for current, dir_names, file_names in os.walk(managed, topdown=True, followlinks=False):
            current_path = Path(current)
            dir_names.sort()
            file_names.sort()
            for name in list(dir_names):
                child = current_path / name
                rel = child.relative_to(root).as_posix()
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    raise ContractError(f"unsafe managed directory: {rel}")
            for name in file_names:
                child = current_path / name
                rel = child.relative_to(root).as_posix()
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                    raise ContractError(f"unsafe managed file: {rel}")
                found.add(rel)
    return found


def load_scheduler_inventory(path: Path) -> list[dict[str, str]]:
    data = load_json_file(path, "scheduler inventory")
    reject_unknown(data, {"schema", "jobs"}, "scheduler inventory")
    if data.get("schema") != INVENTORY_SCHEMA or not isinstance(data.get("jobs"), list):
        raise ContractError("unsupported scheduler inventory schema")
    rows: list[dict[str, str]] = []
    for raw in data["jobs"]:
        if not isinstance(raw, dict):
            raise ContractError("scheduler job entry must be an object")
        reject_unknown(raw, {"name", "schedule", "command"}, "scheduler job")
        if not all(isinstance(raw.get(key), str) and raw[key].strip() for key in ("name", "schedule", "command")):
            raise ContractError("scheduler job fields must be non-empty strings")
        rows.append({key: raw[key].strip() for key in ("name", "schedule", "command")})
    return rows


def verify(manifest: dict[str, object], deployment_root_value: str, scheduler_inventory: str | None) -> dict[str, object]:
    files, roots, namespace, jobs = validate_manifest(manifest)
    root = safe_deployment_root(deployment_root_value)
    expected_targets = {str(row["target"]) for row in files}
    actual_targets = inventory_managed_files(root, roots)
    missing = sorted(expected_targets - actual_targets)
    extra = sorted(actual_targets - expected_targets)
    if missing or extra:
        raise ContractError(f"managed file set mismatch: missing={missing}, extra={extra}")
    for row in files:
        target = str(row["target"])
        assert_no_symlink_components(root, target)
        path = root / Path(*PurePosixPath(target).parts)
        size, digest = sha256_file(path)
        if size != row["bytes"] or digest != row["sha256"]:
            raise ContractError(f"deployed file hash mismatch: {target}")
        actual_executable = bool(path.stat().st_mode & 0o111)
        expected_executable = row["mode"] == "100755"
        if actual_executable != expected_executable:
            raise ContractError(f"deployed executable mode mismatch: {target}")

    if jobs and scheduler_inventory is None:
        raise ContractError("scheduler inventory is required for managed jobs")
    matched_jobs = 0
    if scheduler_inventory is not None:
        inventory = load_scheduler_inventory(Path(scheduler_inventory).expanduser().absolute())
        managed_inventory = [row for row in inventory if row["name"].startswith(namespace)]
        by_name: dict[str, list[dict[str, str]]] = {}
        for row in managed_inventory:
            by_name.setdefault(row["name"], []).append(row)
        expected_names = {row["name"] for row in jobs}
        extra_jobs = sorted(set(by_name) - expected_names)
        missing_jobs = sorted(expected_names - set(by_name))
        duplicates = sorted(name for name, rows in by_name.items() if len(rows) != 1)
        if missing_jobs or extra_jobs or duplicates:
            raise ContractError(
                f"managed scheduler set mismatch: missing={missing_jobs}, extra={extra_jobs}, duplicate={duplicates}"
            )
        for expected in jobs:
            actual = by_name[expected["name"]][0]
            if actual["schedule"] != expected["schedule"]:
                raise ContractError(f"scheduler schedule mismatch: {expected['name']}")
            command_hash = sha256_bytes(actual["command"].encode("utf-8"))
            if command_hash != expected["commandSha256"]:
                raise ContractError(f"scheduler command hash mismatch: {expected['name']}")
        matched_jobs = len(jobs)

    source = manifest["source"]
    assert isinstance(source, dict)
    return {
        "status": "verified",
        "repository": source["repository"],
        "commit": source["commit"],
        "files": len(files),
        "managedRoots": len(roots),
        "jobs": matched_jobs,
    }


def write_manifest(data: dict[str, object], output: str, force: bool) -> None:
    encoded = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output == "-":
        sys.stdout.write(encoded)
        return
    path = Path(output).expanduser().absolute()
    if path.is_symlink():
        raise ContractError("manifest output symlink is not allowed")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not force and os.path.lexists(path):
            raise ContractError("manifest output already exists; use --force to replace")
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if force:
                os.replace(temp_path, path)
            else:
                try:
                    os.link(temp_path, path)
                except FileExistsError as exc:
                    raise ContractError("manifest output already exists; use --force to replace") from exc
        finally:
            temp_path.unlink(missing_ok=True)
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError(f"cannot write provenance manifest: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture_cmd = sub.add_parser("capture", help="capture provenance from a clean committed Git repository")
    capture_cmd.add_argument("--repo", required=True)
    capture_cmd.add_argument("--spec", required=True, help="repository-relative deployment spec JSON")
    capture_cmd.add_argument("--output", default="-", help="manifest path or - for stdout")
    capture_cmd.add_argument("--force", action="store_true")
    verify_cmd = sub.add_parser("verify", help="read-only verification of deployed files and scheduler inventory")
    verify_cmd.add_argument("--manifest", required=True)
    verify_cmd.add_argument("--deployment-root", required=True)
    verify_cmd.add_argument("--scheduler-inventory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "capture":
            manifest = capture(args.repo, args.spec)
            write_manifest(manifest, args.output, args.force)
        else:
            manifest = load_json_file(Path(args.manifest).expanduser().absolute(), "provenance manifest")
            result = verify(manifest, args.deployment_root, args.scheduler_inventory)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (ContractError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
