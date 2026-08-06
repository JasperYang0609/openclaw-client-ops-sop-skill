#!/usr/bin/env python3
"""Dependency-free maintainer checks for the client ops SOP skill."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True)


def record(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    if not ok and detail:
        print(detail[-1600:])
    return ok


def main() -> int:
    results: list[bool] = []
    required = [
        "SKILL.md",
        "README.md",
        "references/deployment-provenance.md",
        "scripts/deployment_provenance.py",
        "scripts/generate_issue_entry.py",
        "examples/deployment-spec.example.json",
        "examples/scheduler-inventory.example.json",
        "tests/test_deployment_provenance.py",
        ".github/workflows/ci.yml",
    ]
    results.append(record("required files", all((ROOT / item).is_file() for item in required)))

    for relative in (
        "examples/deployment-spec.example.json",
        "examples/scheduler-inventory.example.json",
    ):
        try:
            parsed = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            ok = isinstance(parsed, dict) and isinstance(parsed.get("schema"), str)
            detail = ""
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            ok, detail = False, str(exc)
        results.append(record(f"JSON parses: {relative}", ok, detail))

    compile_result = run(
        sys.executable,
        "-m",
        "py_compile",
        "scripts/deployment_provenance.py",
        "scripts/generate_issue_entry.py",
        "scripts/post_run_check.py",
    )
    results.append(record("Python compile", compile_result.returncode == 0, compile_result.stderr))

    issue = run(
        sys.executable,
        "scripts/generate_issue_entry.py",
        "--client",
        "synthetic-client",
        "--title",
        "Synthetic incident",
        "--date",
        "2026-08-06 00:00",
    )
    issue_ok = (
        issue.returncode == 0
        and "synthetic-client" in issue.stdout
        and "P2" in issue.stdout
        and "Status: open" in issue.stdout
    )
    results.append(record("issue template smoke", issue_ok, issue.stderr or issue.stdout))

    tests = run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    test_output = tests.stdout + tests.stderr
    results.append(
        record(
            "deployment provenance tests",
            tests.returncode == 0 and "Ran 12 tests" in test_output and "OK" in test_output,
            test_output,
        )
    )

    if not all(results):
        print("post-run check failed", file=sys.stderr)
        return 1
    print("post-run check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
