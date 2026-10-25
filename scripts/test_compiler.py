#!/usr/bin/env python3
"""Exercise compiler checks and the generated Rust API."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = REPOSITORY / "cue" / "examples"
RUST_TESTDATA = REPOSITORY / "internal" / "backend" / "rust" / "testdata" / "generated_check"
RUST_FIXTURES = REPOSITORY / "cue" / "testdata" / "rust_backend"


def run(
    command: list[str],
    *,
    cwd: Path = REPOSITORY,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)


def require_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed:\n{result.stdout}{result.stderr}")


def require_failure(
    result: subprocess.CompletedProcess[str], action: str, expected_message: str | None = None
) -> None:
    output = result.stdout + result.stderr
    if result.returncode == 0:
        raise RuntimeError(f"{action} unexpectedly succeeded")
    if expected_message is not None and expected_message not in output:
        raise RuntimeError(f"{action} failed unexpectedly:\n{output}")


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} is required on PATH")


def build_generator(output: Path) -> None:
    require_success(run(["go", "build", "-o", str(output), "./cmd/cueflow"]), "building cueflow")


def check_and_generate(generator: Path, directory: Path) -> Path:
    require_success(
        run([str(generator), "check", "--input", str(EXAMPLE_INPUT)]),
        "checking the request-response protocol",
    )
    project = directory / "rust-check"
    shutil.copytree(RUST_TESTDATA, project)
    generated = project / "src" / "lib.rs"
    require_success(
        run(
            [str(generator), "generate", "rust", "--input", str(EXAMPLE_INPUT), "--output", str(generated)]
        ),
        "generating Rust source",
    )
    return project


def run_cargo_tests(project: Path, target: Path, env: dict[str, str]) -> None:
    manifest = project / "Cargo.toml"
    test_result = run(["cargo", "test", "--offline", "--manifest-path", str(manifest)], env=env)
    require_success(test_result, "testing generated Rust API")
    print(test_result.stdout + test_result.stderr, end="")

    invalid_source = RUST_TESTDATA / "invalid.rs"
    invalid_binary = project / "src" / "bin" / "invalid.rs"
    invalid_binary.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(invalid_source, invalid_binary)
    invalid_result = run(
        ["cargo", "check", "--offline", "--manifest-path", str(manifest), "--bin", "invalid"],
        env=env,
    )
    require_failure(invalid_result, "checking an invalid typestate call", "no method named `send_result`")


def check_backend_failure(
    generator: Path, directory: Path, fixture: str, expected_message: str | None
) -> None:
    package = RUST_FIXTURES / fixture
    require_success(run([str(generator), "check", "--input", str(package)]), f"checking {fixture}")
    output = directory / f"{fixture}.rs"
    result = run(
        [str(generator), "generate", "rust", "--input", str(package), "--output", str(output)]
    )
    require_failure(result, f"generating unsupported fixture {fixture}", expected_message)


def check_backend_boundaries(generator: Path, directory: Path) -> None:
    check_backend_failure(generator, directory, "unsupported_constraint", None)
    check_backend_failure(
        generator,
        directory,
        "multiple_receives",
        "state \"Ready\" has multiple receive transitions, unsupported by the Rust backend",
    )
    check_backend_failure(
        generator,
        directory,
        "invalid_identifier",
        'state ID "_" maps to invalid Rust type name "_"',
    )
    check_backend_failure(
        generator, directory, "name_collision", 'duplicate Rust name "Ready"'
    )


def main() -> int:
    require_tool("go")
    require_tool("cargo")
    with tempfile.TemporaryDirectory(prefix=".cueflow-compiler-", dir=REPOSITORY) as temporary:
        directory = Path(temporary)
        generator = directory / "cueflow"
        cargo_target = directory / "cargo-target"
        cargo_environment = os.environ.copy()
        cargo_environment["CARGO_TARGET_DIR"] = str(cargo_target)
        cargo_environment["CARGO_PROFILE_DEV_DEBUG"] = "0"
        cargo_environment["CARGO_BUILD_JOBS"] = "1"

        build_generator(generator)
        project = check_and_generate(generator, directory)
        run_cargo_tests(project, cargo_target, cargo_environment)
        check_backend_boundaries(generator, directory)
    print("compiler and generated Rust checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
