#!/usr/bin/env python3
"""Generate Rust/Python APIs and check recursive CUE object semantics."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL = REPOSITORY / "cue/testdata/schema_conformance/nested_object"
RUST_TEMPLATE = REPOSITORY / "internal/backend/rust/testdata/nested_check"
PYTHON_TESTDATA = REPOSITORY / "internal/backend/python/testdata/nested_check"


def run_command(
    command: list[str],
    action: str,
    directory: Path,
    environment: dict[str, str],
) -> None:
    result = subprocess.run(
        command,
        cwd=directory,
        env=environment,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed:\n{result.stdout}{result.stderr}")
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)


def build_generator(directory: Path, environment: dict[str, str]) -> Path:
    generator = directory / "cueflow"
    run_command(
        ["go", "build", "-o", str(generator), "./cmd/cueflow"],
        "building cueflow",
        REPOSITORY,
        environment,
    )
    return generator


def generate(
    generator: Path,
    language: str,
    output: Path,
    environment: dict[str, str],
) -> None:
    run_command(
        [
            str(generator),
            "generate",
            language,
            "--input",
            str(PROTOCOL),
            "--output",
            str(output),
        ],
        f"generating {language} nested-object API",
        REPOSITORY,
        environment,
    )


def test_rust(
    generator: Path,
    directory: Path,
    environment: dict[str, str],
) -> None:
    project = directory / "rust-project"
    shutil.copytree(RUST_TEMPLATE, project)
    generate(generator, "rust", project / "src/lib.rs", environment)
    cargo_environment = environment.copy()
    cargo_environment["CARGO_TARGET_DIR"] = str(directory / "cargo-target")
    cargo_environment["CARGO_PROFILE_DEV_DEBUG"] = "0"
    cargo_environment["CARGO_BUILD_JOBS"] = "1"
    run_command(
        ["cargo", "test", "--offline", "--manifest-path", str(project / "Cargo.toml")],
        "testing generated Rust nested-object API",
        REPOSITORY,
        cargo_environment,
    )


def test_python(
    generator: Path,
    directory: Path,
    environment: dict[str, str],
) -> None:
    generated = directory / "generated.py"
    generate(generator, "python", generated, environment)
    test_file = directory / "api_test.py"
    valid_api = directory / "valid_api.py"
    shutil.copyfile(PYTHON_TESTDATA / "api_test.py", test_file)
    shutil.copyfile(PYTHON_TESTDATA / "valid_api.py", valid_api)
    python_environment = environment.copy()
    python_environment["PYTHONPATH"] = str(directory)
    run_command(
        [
            "mypy",
            "--strict",
            "--cache-dir",
            str(directory / "mypy-cache"),
            str(generated),
            str(valid_api),
        ],
        "type-checking generated Python nested-object API",
        REPOSITORY,
        python_environment,
    )
    run_command(
        [sys.executable, str(test_file)],
        "testing generated Python nested-object API",
        directory,
        python_environment,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix=".cueflow-nested-", dir=REPOSITORY) as temporary:
        directory = Path(temporary)
        go_temp = directory / "go-tmp"
        go_temp.mkdir()
        environment = os.environ.copy()
        environment["TMPDIR"] = str(directory)
        environment["GOTMPDIR"] = str(go_temp)
        environment["GOCACHE"] = str(directory / "go-cache")
        generator = build_generator(directory, environment)
        test_rust(generator, directory, environment)
        test_python(generator, directory, environment)
    print("Nested-object semantic checks passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Nested-object checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
