#!/usr/bin/env python3
"""Generate and exercise the Python backend with Pydantic and mypy."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
EXAMPLE_INPUT = REPOSITORY / "cue" / "examples"
MULTIPLE_RECEIVES_INPUT = REPOSITORY / "cue" / "testdata" / "rust_backend" / "multiple_receives"
RESERVED_FIELD_INPUT = REPOSITORY / "cue" / "testdata" / "python_backend" / "reserved_field"
PYTHON_TESTDATA = REPOSITORY / "internal" / "backend" / "python" / "testdata" / "generated_check"


def run(command: list[str], cwd: Path = REPOSITORY, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)


def build_generator(output: Path) -> None:
    result = run(["go", "build", "-o", str(output), "./cmd/cueflow"])
    require_success(result, "building cueflow")


def generate_python(generator: Path, output: Path, package: Path) -> None:
    result = run(
        [str(generator), "generate", "python", "--input", str(package), "--output", str(output)]
    )
    require_success(result, "generating Python source")


def require_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed:\n{result.stdout}{result.stderr}")


def check_types(directory: Path, generated: Path) -> None:
    mypy = shutil.which("mypy")
    if mypy is None:
        raise RuntimeError("mypy is required; run this script with uv --with mypy")
    shutil.copyfile(PYTHON_TESTDATA / "valid_api.py", directory / "valid_api.py")
    shutil.copyfile(PYTHON_TESTDATA / "invalid_api.py", directory / "invalid_api.py")
    shutil.copyfile(PYTHON_TESTDATA / "mypy.ini", directory / "mypy.ini")
    valid = directory / "valid_api.py"
    invalid = directory / "invalid_api.py"
    configuration = directory / "mypy.ini"
    environment = os.environ.copy()
    environment["MYPYPATH"] = str(directory)
    cache_directory = directory / "mypy-cache"
    valid_result = run(
        [mypy, "--strict", "--config-file", str(configuration), "--cache-dir", str(cache_directory), str(generated), str(valid)],
        env=environment,
    )
    require_success(valid_result, "checking valid Python state calls")
    invalid_result = run(
        [mypy, "--strict", "--config-file", str(configuration), "--cache-dir", str(cache_directory), str(generated), str(invalid)],
        env=environment,
    )
    if invalid_result.returncode == 0 or "has no attribute \"send_result\"" not in invalid_result.stdout:
        raise RuntimeError(
            "mypy did not reject an invalid client transition:\n"
            f"{invalid_result.stdout}{invalid_result.stderr}"
        )


def run_generated_tests(directory: Path) -> None:
    test_file = directory / "api_test.py"
    shutil.copyfile(PYTHON_TESTDATA / "api_test.py", test_file)
    result = run([sys.executable, str(test_file)], cwd=directory)
    require_success(result, "running generated Python API tests")
    print(result.stdout + result.stderr, end="")


def check_multiple_receives(generator: Path, directory: Path) -> None:
    result = run(
        [str(generator), "generate", "python", "--input", str(MULTIPLE_RECEIVES_INPUT), "--output", str(directory / "invalid.py")]
    )
    expected_error = "multiple receive transitions, unsupported by the Python backend"
    if result.returncode == 0 or expected_error not in result.stderr:
        raise RuntimeError(f"Python backend did not reject multiple recv transitions:\n{result.stderr}")


def check_reserved_field(generator: Path, directory: Path) -> None:
    output = directory / "reserved_generated.py"
    generate_python(generator, output, RESERVED_FIELD_INPUT)
    compile_result = run([sys.executable, "-m", "py_compile", str(output)])
    require_success(compile_result, "compiling a Pydantic reserved-field fixture")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cueflow-python-") as temporary:
        directory = Path(temporary)
        generator = directory / "cueflow"
        generated = directory / "generated.py"
        build_generator(generator)
        generate_python(generator, generated, EXAMPLE_INPUT)
        check_reserved_field(generator, directory)
        if "Any" in generated.read_text(encoding="utf-8"):
            raise RuntimeError("generated source must not contain Any")
        compile_result = run([sys.executable, "-m", "py_compile", str(generated)])
        require_success(compile_result, "compiling generated Python source")
        check_types(directory, generated)
        run_generated_tests(directory)
        check_multiple_receives(generator, directory)
    print("Python backend checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
