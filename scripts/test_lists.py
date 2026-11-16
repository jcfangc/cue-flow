#!/usr/bin/env python3
"""Check CUE oracle and generated Rust/Python string-list semantics."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
CUE_ROOT = REPOSITORY / "cue"
FIXTURE = CUE_ROOT / "testdata/schema_conformance/string_list"
RUST_TEMPLATE = REPOSITORY / "internal/backend/rust/testdata/list_check"
PYTHON_TEST = REPOSITORY / "internal/backend/python/testdata/list_check/api_test.py"


@dataclass(frozen=True)
class UnsupportedList:
    fixture: Path
    expected_error: str


UNSUPPORTED_LISTS = [
    UnsupportedList(FIXTURE / "tuple", "not supported yet"),
    UnsupportedList(FIXTURE / "heterogeneous_tuple", "not supported yet"),
    UnsupportedList(FIXTURE / "list_integer", "only supports string items yet"),
    UnsupportedList(FIXTURE / "list_object", "only supports string items yet"),
]


def run(
    command: list[str],
    action: str,
    *,
    cwd: Path = REPOSITORY,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed:\n{result.stdout}{result.stderr}")
    return result


def check_cue_oracle(environment: dict[str, str]) -> None:
    cue = shutil.which("cue")
    if cue is None:
        raise RuntimeError("cue CLI is required for the list semantic oracle")
    protocol = str(FIXTURE / "protocol.cue")
    valid = run(
        [cue, "vet", "-c=false", protocol, str(FIXTURE / "samples/valid.cue")],
        "validating the accepted list sample with CUE",
        cwd=CUE_ROOT,
        environment=environment,
    )
    del valid
    invalid = subprocess.run(
        [cue, "vet", "-c=false", protocol, str(FIXTURE / "samples/invalid.cue")],
        cwd=CUE_ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    if invalid.returncode == 0:
        raise RuntimeError("CUE unexpectedly accepted an invalid list element")


def build_generator(directory: Path, environment: dict[str, str]) -> Path:
    generator = directory / "cueflow"
    run(
        ["go", "build", "-o", str(generator), "./cmd/cueflow"],
        "building cueflow",
        environment=environment,
    )
    return generator


def generate(generator: Path, language: str, output: Path, environment: dict[str, str]) -> None:
    run(
        [
            str(generator), "generate", language, "--input", str(FIXTURE),
            "--output", str(output),
        ],
        f"generating {language} list API",
        environment=environment,
    )


def test_rust(generator: Path, directory: Path, environment: dict[str, str]) -> None:
    project = directory / "rust-project"
    shutil.copytree(RUST_TEMPLATE, project)
    generate(generator, "rust", project / "src/lib.rs", environment)
    cargo_environment = environment.copy()
    cargo_environment["CARGO_TARGET_DIR"] = str(directory / "cargo-target")
    cargo_environment["CARGO_PROFILE_DEV_DEBUG"] = "0"
    cargo_environment["CARGO_BUILD_JOBS"] = "1"
    run(
        ["cargo", "test", "--offline", "--manifest-path", str(project / "Cargo.toml")],
        "testing generated Rust list API",
        environment=cargo_environment,
    )


def test_python(generator: Path, directory: Path, environment: dict[str, str]) -> None:
    generated = directory / "generated.py"
    generate(generator, "python", generated, environment)
    test_file = directory / "api_test.py"
    shutil.copyfile(PYTHON_TEST, test_file)
    python_environment = environment.copy()
    python_environment["PYTHONPATH"] = str(directory)
    run(
        ["mypy", "--strict", "--cache-dir", str(directory / "mypy-cache"), str(generated)],
        "type-checking generated Python list API",
        environment=python_environment,
    )
    run(
        [sys.executable, str(test_file)],
        "testing generated Python list API",
        cwd=directory,
        environment=python_environment,
    )


def test_unsupported_lists(generator: Path, directory: Path, environment: dict[str, str]) -> None:
    for unsupported in UNSUPPORTED_LISTS:
        check_unsupported_list(generator, directory, environment, unsupported)


def check_unsupported_list(
    generator: Path,
    directory: Path,
    environment: dict[str, str],
    unsupported: UnsupportedList,
) -> None:
    for language in ["rust", "python"]:
        result = subprocess.run(
            [
                str(generator), "generate", language, "--input", str(unsupported.fixture),
                "--output", str(directory / f"{unsupported.fixture.name}-{language}.out"),
            ],
            cwd=REPOSITORY,
            env=environment,
            text=True,
            capture_output=True,
        )
        output = result.stdout + result.stderr
        if result.returncode == 0 or unsupported.expected_error not in output:
            raise RuntimeError(
                f"{language} backend did not clearly reject {unsupported.fixture.name}:\n{output}"
            )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix=".cueflow-lists-", dir=REPOSITORY) as temporary:
        directory = Path(temporary)
        go_temp = directory / "go-tmp"
        go_temp.mkdir()
        environment = os.environ.copy()
        environment["TMPDIR"] = str(directory)
        environment["GOTMPDIR"] = str(go_temp)
        environment["GOCACHE"] = str(directory / "go-cache")
        check_cue_oracle(environment)
        generator = build_generator(directory, environment)
        test_rust(generator, directory, environment)
        test_python(generator, directory, environment)
        test_unsupported_lists(generator, directory, environment)
    print("String-list semantic checks passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"List checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
