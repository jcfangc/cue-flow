#!/usr/bin/env python3
"""Validate the CUE schema and its acceptance/rejection fixtures."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
CUE_MODULE = REPOSITORY / "cue"


def run_cue(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    cue = shutil.which("cue")
    if cue is None:
        raise RuntimeError("cue CLI is required on PATH")
    return subprocess.run(
        [cue, "vet", *arguments], cwd=CUE_MODULE, text=True, capture_output=True
    )


def require_success(arguments: list[str]) -> None:
    result = run_cue(arguments)
    if result.returncode != 0:
        raise RuntimeError(f"cue vet {' '.join(arguments)} failed:\n{result.stderr}")


def require_rejection(arguments: list[str], expected_message: str) -> None:
    result = run_cue(arguments)
    output = result.stdout + result.stderr
    if result.returncode == 0 or expected_message not in output:
        raise RuntimeError(
            f"cue vet {' '.join(arguments)} did not fail as expected:\n{output}"
        )


def main() -> int:
    require_success(["-c=false", "./examples/request_response.cue"])
    require_rejection(
        ["-c=false", "./testdata/schema/invalid_close.cue"], "field not allowed"
    )
    require_rejection(
        ["-c=false", "./testdata/schema/invalid_message_value.cue"], "invalid value"
    )
    require_rejection(
        ["-c", "./testdata/schema/missing_required.cue"],
        "field is required but not present",
    )
    print("CUE schema checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
