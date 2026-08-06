from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deployment_provenance.py"


def run(*args: str, cwd: Path | None = None):
    return subprocess.run(args, cwd=cwd or ROOT, text=True, capture_output=True)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(path.relative_to(root).as_posix().encode())
        info = path.lstat()
        digest.update(str(stat.S_IMODE(info.st_mode)).encode())
        if path.is_file() and not path.is_symlink():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class DeploymentProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.repo = base / "repo"
        self.deploy = base / "deploy"
        self.manifest = base / "provenance.json"
        self.inventory = base / "scheduler.json"
        self.repo.mkdir()
        self.deploy.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Provenance Tests")
        self.git("remote", "add", "origin", "https://github.com/example/client-ops.git")
        (self.repo / "scripts").mkdir()
        source = self.repo / "scripts" / "worker.py"
        source.write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
        source.chmod(0o755)
        (self.repo / "deployment").mkdir()
        self.spec = {
            "schema": "openclaw-client-deployment-spec-v1",
            "managedRoots": ["installed/ansai"],
            "jobNamespace": "ansai:test:",
            "files": [{"source": "scripts/worker.py", "target": "installed/ansai/worker.py"}],
            "jobs": [
                {
                    "name": "ansai:test:worker",
                    "schedule": "15 5 * * *",
                    "command": "python3 installed/ansai/worker.py",
                }
            ],
        }
        self.write_spec_and_commit("initial")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args: str):
        proc = run("git", "-C", str(self.repo), *args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def write_spec_and_commit(self, message: str):
        (self.repo / "deployment/spec.json").write_text(
            json.dumps(self.spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.git("add", "-A")
        self.git("commit", "-m", message)

    def capture(self, *, output: Path | str | None = None):
        output_value = str(output if output is not None else self.manifest)
        return run(
            sys.executable,
            str(SCRIPT),
            "capture",
            "--repo",
            str(self.repo),
            "--spec",
            "deployment/spec.json",
            "--output",
            output_value,
        )

    def create_deployment(self):
        target = self.deploy / "installed/ansai/worker.py"
        target.parent.mkdir(parents=True)
        shutil.copyfile(self.repo / "scripts/worker.py", target)
        target.chmod(0o755)
        self.inventory.write_text(
            json.dumps(
                {
                    "schema": "openclaw-scheduler-inventory-v1",
                    "jobs": self.spec["jobs"],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def verify(self, *, inventory: Path | None = None):
        return run(
            sys.executable,
            str(SCRIPT),
            "verify",
            "--manifest",
            str(self.manifest),
            "--deployment-root",
            str(self.deploy),
            "--scheduler-inventory",
            str(inventory or self.inventory),
        )

    def test_capture_is_deterministic_and_omits_raw_commands_and_local_paths(self):
        first = self.capture(output="-")
        second = self.capture(output="-")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        data = json.loads(first.stdout)
        self.assertEqual(data["schema"], "openclaw-client-deployment-provenance-v1")
        self.assertEqual(len(data["source"]["commit"]), 40)
        self.assertEqual(data["source"]["repository"], "https://github.com/example/client-ops.git")
        self.assertNotIn(self.spec["jobs"][0]["command"], first.stdout)
        self.assertNotIn(str(self.repo), first.stdout)
        self.assertRegex(data["jobs"][0]["commandSha256"], r"^[0-9a-f]{64}$")

    def test_verify_passes_without_mutating_deployment_or_inventory(self):
        self.assertEqual(self.capture().returncode, 0)
        self.create_deployment()
        before_deploy = tree_digest(self.deploy)
        before_inventory = self.inventory.read_bytes()
        proc = self.verify()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["jobs"], 1)
        self.assertEqual(tree_digest(self.deploy), before_deploy)
        self.assertEqual(self.inventory.read_bytes(), before_inventory)

    def test_file_missing_extra_tamper_and_mode_mismatch_fail_closed(self):
        self.assertEqual(self.capture().returncode, 0)
        cases = ("missing", "extra", "tamper", "mode")
        for case in cases:
            with self.subTest(case=case):
                shutil.rmtree(self.deploy)
                self.deploy.mkdir()
                self.create_deployment()
                target = self.deploy / "installed/ansai/worker.py"
                if case == "missing":
                    target.unlink()
                elif case == "extra":
                    (target.parent / "extra.py").write_text("extra\n", encoding="utf-8")
                elif case == "tamper":
                    target.write_text("tampered\n", encoding="utf-8")
                else:
                    target.chmod(0o644)
                proc = self.verify()
                self.assertEqual(proc.returncode, 2)
                self.assertRegex(proc.stderr, "mismatch")

    def test_scheduler_missing_extra_duplicate_schedule_and_command_fail_closed(self):
        self.assertEqual(self.capture().returncode, 0)
        self.create_deployment()
        base_job = dict(self.spec["jobs"][0])
        cases = {
            "missing": [],
            "extra": [base_job, {**base_job, "name": "ansai:test:orphan"}],
            "duplicate": [base_job, base_job],
            "schedule": [{**base_job, "schedule": "0 0 * * *"}],
            "command": [{**base_job, "command": "python3 other.py"}],
        }
        for name, jobs in cases.items():
            with self.subTest(case=name):
                self.inventory.write_text(
                    json.dumps({"schema": "openclaw-scheduler-inventory-v1", "jobs": jobs}),
                    encoding="utf-8",
                )
                proc = self.verify()
                self.assertEqual(proc.returncode, 2)
                self.assertIn("scheduler", proc.stderr)
                self.assertNotIn(base_job["command"], proc.stderr)

    def test_dirty_and_untracked_repository_are_blocked(self):
        (self.repo / "scripts/worker.py").write_text("dirty\n", encoding="utf-8")
        dirty = self.capture(output="-")
        self.assertEqual(dirty.returncode, 2)
        self.assertIn("must be clean", dirty.stderr)
        self.git("checkout", "--", "scripts/worker.py")
        (self.repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
        untracked = self.capture(output="-")
        self.assertEqual(untracked.returncode, 2)
        self.assertIn("must be clean", untracked.stderr)

    def test_unsafe_spec_paths_and_secret_commands_are_blocked(self):
        self.spec["files"][0]["target"] = "../escape.py"
        self.write_spec_and_commit("unsafe path")
        unsafe = self.capture(output="-")
        self.assertEqual(unsafe.returncode, 2)
        self.assertIn("unsafe target path", unsafe.stderr)

        self.spec["files"][0]["target"] = "installed/ansai/worker.py"
        self.spec["jobs"][0]["command"] = "worker --key sk-" + "A" * 30
        self.write_spec_and_commit("unsafe command")
        secret = self.capture(output="-")
        self.assertEqual(secret.returncode, 2)
        self.assertIn("possible secret", secret.stderr)
        self.assertNotIn("sk-", secret.stderr)

    def test_credential_bearing_remote_is_blocked_without_echoing_it(self):
        credential_remote = "https://" + "placeholder-user" + ":" + "placeholder-pass" + "@example.invalid/repo.git"
        self.git("remote", "set-url", "origin", credential_remote)
        proc = self.capture(output="-")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must not contain credentials", proc.stderr)
        self.assertNotIn("placeholder-pass", proc.stderr)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_managed_parent_is_blocked(self):
        self.assertEqual(self.capture().returncode, 0)
        external = Path(self.temp.name) / "external"
        (external / "ansai").mkdir(parents=True)
        self.deploy.joinpath("installed").symlink_to(external, target_is_directory=True)
        self.inventory.write_text(
            json.dumps({"schema": "openclaw-scheduler-inventory-v1", "jobs": self.spec["jobs"]}),
            encoding="utf-8",
        )
        proc = self.verify()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("symlink path component", proc.stderr)


    def test_unrelated_scheduler_jobs_are_ignored_and_standard_ssh_remote_is_allowed(self):
        self.git("remote", "set-url", "origin", "ssh://git@github.com/example/client-ops.git")
        captured = self.capture()
        self.assertEqual(captured.returncode, 0, captured.stderr)
        self.create_deployment()
        inventory = json.loads(self.inventory.read_text(encoding="utf-8"))
        inventory["jobs"].append(
            {"name": "other-team:daily", "schedule": "0 1 * * *", "command": "other-tool --run"}
        )
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        verified = self.verify()
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout)["jobs"], 1)

    def test_tracked_symlink_source_and_ambiguous_paths_are_blocked(self):
        self.git("rm", "scripts/worker.py")
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "scripts/real.py").write_text("print('real')\n", encoding="utf-8")
        (self.repo / "scripts/worker.py").symlink_to("real.py")
        self.git("add", "-A")
        self.git("commit", "-m", "tracked symlink")
        symlinked = self.capture(output="-")
        self.assertEqual(symlinked.returncode, 2)
        self.assertIn("regular tracked file", symlinked.stderr)

        self.git("rm", "scripts/worker.py")
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "scripts/worker.py").write_text("print('regular')\n", encoding="utf-8")
        self.spec["files"][0]["target"] = "installed//ansai/worker.py"
        self.write_spec_and_commit("ambiguous target")
        ambiguous = self.capture(output="-")
        self.assertEqual(ambiguous.returncode, 2)
        self.assertIn("unsafe target path", ambiguous.stderr)

    def test_manifest_rejects_raw_command_field(self):
        self.assertEqual(self.capture().returncode, 0)
        self.create_deployment()
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["jobs"][0]["command"] = self.spec["jobs"][0]["command"]
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = self.verify()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown manifest job fields", proc.stderr)

    def test_capture_refuses_to_overwrite_manifest_without_force(self):
        first = self.capture()
        self.assertEqual(first.returncode, 0, first.stderr)
        before = self.manifest.read_bytes()
        second = self.capture()
        self.assertEqual(second.returncode, 2)
        self.assertIn("already exists", second.stderr)
        self.assertEqual(self.manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
