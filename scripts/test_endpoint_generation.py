#!/usr/bin/env python3
"""Check endpoint-aware receive-branch limits and compile selected APIs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
RUST_TEMPLATE = REPOSITORY / "internal/backend/rust/testdata/generated_check"
MULTIPLE_RECEIVES = REPOSITORY / "cue/testdata/rust_backend/multiple_receives"
MULTIPLE_SENDS = REPOSITORY / "cue/testdata/endpoint_backend/multiple_sends"


class Language(Enum):
    RUST = "rust"
    PYTHON = "python"


class Endpoint(Enum):
    CLIENT = "client"
    SERVER = "server"
    BOTH = "both"


@dataclass(frozen=True)
class EndpointCase:
    language: Language
    endpoint: Endpoint
    input_path: Path
    expected_error: str | None


def run_command(command: list[str], action: str, environment: dict[str, str]) -> None:
    result = subprocess.run(
        command,
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed:\n{result.stdout}{result.stderr}")


def build_generator(directory: Path, environment: dict[str, str]) -> Path:
    generator = directory / "cueflow"
    run_command(
        ["go", "build", "-o", str(generator), "./cmd/cueflow"],
        "building cueflow",
        environment,
    )
    return generator


def generation_command(
    generator: Path,
    language: Language,
    endpoint: Endpoint,
    input_path: Path,
    output: Path,
) -> list[str]:
    return [
        str(generator),
        "generate",
        language.value,
        "--input",
        str(input_path),
        "--output",
        str(output),
        "--endpoint",
        endpoint.value,
    ]


def check_case(
    generator: Path,
    directory: Path,
    environment: dict[str, str],
    case: EndpointCase,
) -> Path | None:
    extension = ".rs" if case.language is Language.RUST else ".py"
    output = directory / f"{case.language.value}-{case.endpoint.value}{extension}"
    command = generation_command(
        generator, case.language, case.endpoint, case.input_path, output
    )
    result = subprocess.run(
        command,
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
    )
    if case.expected_error is None:
        if result.returncode != 0:
            raise RuntimeError(f"expected generation to succeed:\n{result.stderr}")
        print(f"PASS {case.language.value} {case.endpoint.value} {case.input_path.parent.name}")
        return output
    if result.returncode == 0 or case.expected_error not in result.stderr:
        raise RuntimeError(
            f"expected generation error {case.expected_error!r}, got:\n{result.stderr}"
        )
    print(f"PASS reject {case.language.value} {case.endpoint.value} {case.input_path.parent.name}")
    return None


def accepted_cases() -> list[EndpointCase]:
    cases: list[EndpointCase] = []
    for language in Language:
        cases.append(
            EndpointCase(language, Endpoint.CLIENT, MULTIPLE_RECEIVES, None)
        )
        cases.append(EndpointCase(language, Endpoint.SERVER, MULTIPLE_SENDS, None))
    return cases


def rejected_cases() -> list[EndpointCase]:
    cases: list[EndpointCase] = []
    for language in Language:
        cases.extend(
            [
                EndpointCase(
                    language,
                    Endpoint.SERVER,
                    MULTIPLE_RECEIVES,
                    'multiple server receive transitions, ambiguous for endpoint "server"',
                ),
                EndpointCase(
                    language,
                    Endpoint.CLIENT,
                    MULTIPLE_SENDS,
                    'multiple server send transitions, ambiguous for endpoint "client"',
                ),
                EndpointCase(
                    language,
                    Endpoint.BOTH,
                    MULTIPLE_RECEIVES,
                    'multiple server receive transitions, ambiguous for endpoint "both"',
                ),
                EndpointCase(
                    language,
                    Endpoint.BOTH,
                    MULTIPLE_SENDS,
                    'multiple server send transitions, ambiguous for endpoint "both"',
                ),
            ]
        )
    return cases


def check_python_types(
    outputs: list[Path], cache_directory: Path, environment: dict[str, str]
) -> None:
    run_command(
        ["mypy", "--strict", "--cache-dir", str(cache_directory), *map(str, outputs)],
        "checking selected Python endpoints",
        environment,
    )


def check_rust_compile(
    generator: Path,
    directory: Path,
    target: Path,
    environment: dict[str, str],
) -> None:
    project = directory / "rust-project"
    shutil.copytree(RUST_TEMPLATE, project)
    cargo_environment = environment.copy()
    cargo_environment["CARGO_TARGET_DIR"] = str(target)
    for endpoint in [Endpoint.CLIENT, Endpoint.SERVER]:
        source = project / "src" / "lib.rs"
        run_command(
            generation_command(generator, Language.RUST, endpoint, MULTIPLE_RECEIVES if endpoint is Endpoint.CLIENT else MULTIPLE_SENDS, source),
            f"generating Rust {endpoint.value} API",
            environment,
        )
        run_command(
            ["cargo", "check", "--offline", "--manifest-path", str(project / "Cargo.toml"), "--lib"],
            f"compiling selected Rust {endpoint.value} API",
            cargo_environment,
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix=".cueflow-endpoints-") as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        environment["GOCACHE"] = str(directory / "go-cache")
        generator = build_generator(directory, environment)
        generated_python: list[Path] = []
        for case in accepted_cases():
            output = check_case(generator, directory, environment, case)
            if case.language is Language.PYTHON and output is not None:
                generated_python.append(output)
        for case in rejected_cases():
            check_case(generator, directory, environment, case)
        check_python_types(generated_python, directory / "mypy-cache", environment)
        check_rust_compile(generator, directory, directory / "cargo-target", environment)


if __name__ == "__main__":
    main()
    print("Endpoint-aware generation checks passed")
