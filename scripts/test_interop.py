#!/usr/bin/env python3
"""Test Rust/Python Query and Result cardinalities over a temporary transport."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY / "cue" / "testdata" / "interop"
RUST_TESTDATA = REPOSITORY / "internal/backend/rust/testdata/generated_check"
RUST_PEERS = REPOSITORY / "internal/backend/rust/testdata/interop"
PYTHON_PEERS = REPOSITORY / "internal/backend/python/testdata/interop"
PROCESS_TIMEOUT_SECONDS = 30
READY_TIMEOUT_SECONDS = 10


class Language(Enum):
    RUST = "rust"
    PYTHON = "python"


@dataclass(frozen=True)
class CardinalityCase:
    name: str
    fixture_name: str
    rust_peer_name: str
    python_peer_name: str


@dataclass(frozen=True)
class ProcessOutput:
    return_code: int
    stdout: str
    stderr: str


@dataclass
class PeerProcess:
    language: Language
    process: asyncio.subprocess.Process
    label: str


@dataclass
class BoundServer:
    peer: PeerProcess
    port: int


CASES = [
    CardinalityCase("1:1", "one_to_one", "one_to_one.rs", "one_to_one.py"),
    CardinalityCase("1:N", "one_to_many", "one_to_many.rs", "one_to_many.py"),
    CardinalityCase("N:1", "many_to_one", "many_to_one.rs", "many_to_one.py"),
    CardinalityCase("N:N", "many_to_many", "many_to_many.rs", "many_to_many.py"),
]
LANGUAGES = [Language.RUST, Language.PYTHON]


def run_command(command: list[str], action: str, env: dict[str, str]) -> None:
    result = subprocess.run(
        command, cwd=REPOSITORY, env=env, text=True, capture_output=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"{action} failed:\n{result.stdout}{result.stderr}")


def build_generator(directory: Path, env: dict[str, str]) -> Path:
    output = directory / "cueflow"
    run_command(
        ["go", "build", "-o", str(output), "./cmd/cueflow"],
        "building cueflow",
        env,
    )
    return output


def generate_module(
    generator: Path, language: Language, fixture: Path, output: Path, env: dict[str, str]
) -> None:
    run_command(
        [
            str(generator),
            "generate",
            language.value,
            "--input",
            str(fixture),
            "--output",
            str(output),
        ],
        f"generating {language.value} API for {fixture.name}",
        env,
    )


def prepare_rust_peer(
    case: CardinalityCase,
    generator: Path,
    project: Path,
    target: Path,
    env: dict[str, str],
) -> Path:
    fixture = FIXTURE_ROOT / case.fixture_name
    generate_module(generator, Language.RUST, fixture, project / "src" / "lib.rs", env)
    peer_source = project / "src" / "bin" / "interop_peer.rs"
    peer_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUST_PEERS / case.rust_peer_name, peer_source)
    common_module = peer_source.parent / "interop_common" / "mod.rs"
    common_module.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUST_PEERS / "common.rs", common_module)
    cargo_environment = env.copy()
    cargo_environment["CARGO_TARGET_DIR"] = str(target)
    cargo_environment["CARGO_PROFILE_DEV_DEBUG"] = "0"
    cargo_environment["CARGO_BUILD_JOBS"] = "1"
    run_command(
        [
            "cargo",
            "build",
            "--offline",
            "--manifest-path",
            str(project / "Cargo.toml"),
            "--bin",
            "interop_peer",
        ],
        f"building Rust {case.name} peer",
        cargo_environment,
    )
    return target / "debug" / "interop_peer"


def peer_command(
    language: Language,
    role: str,
    port: int,
    rust_peer: Path,
    python_peer: Path,
) -> list[str]:
    if language is Language.RUST:
        return [str(rust_peer), role, str(port)]
    return [sys.executable, str(python_peer), role, str(port)]


async def spawn_peer(
    language: Language,
    role: str,
    port: int,
    rust_peer: Path,
    python_peer: Path,
    directory: Path,
    env: dict[str, str],
    tracked_peers: list[PeerProcess],
) -> PeerProcess:
    process = await asyncio.create_subprocess_exec(
        *peer_command(language, role, port, rust_peer, python_peer),
        cwd=directory,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    peer = PeerProcess(language, process, f"{language.value} {role}")
    tracked_peers.append(peer)
    return peer


async def start_server(
    language: Language,
    rust_peer: Path,
    python_peer: Path,
    directory: Path,
    env: dict[str, str],
    tracked_peers: list[PeerProcess],
) -> BoundServer:
    peer = await spawn_peer(
        language, "server", 0, rust_peer, python_peer, directory, env, tracked_peers
    )
    if peer.process.stdout is None:
        raise RuntimeError(f"{peer.label} has no stdout pipe")
    try:
        ready_line = await asyncio.wait_for(
            peer.process.stdout.readline(), timeout=READY_TIMEOUT_SECONDS
        )
    except TimeoutError as error:
        raise RuntimeError(f"{peer.label} did not become ready") from error
    ready = ready_line.decode("utf-8").strip().split()
    if len(ready) != 2 or ready[0] != "READY":
        output = await collect_process(peer, PROCESS_TIMEOUT_SECONDS)
        raise RuntimeError(
            f"{peer.label} failed to bind:\n{ready_line.decode()}{output.stderr}"
        )
    return BoundServer(peer=peer, port=int(ready[1]))


async def collect_process(peer: PeerProcess, timeout: int) -> ProcessOutput:
    try:
        # asyncio subprocess communicate() exposes stdout and stderr as a pair;
        # convert the required standard-library result into the named DTO below.
        output = await asyncio.wait_for(peer.process.communicate(), timeout=timeout)
    except TimeoutError as error:
        await stop_peer(peer)
        raise RuntimeError(f"{peer.label} timed out") from error
    return ProcessOutput(
        return_code=peer.process.returncode or 0,
        stdout=output[0].decode("utf-8"),
        stderr=output[1].decode("utf-8"),
    )


def require_process_success(peer: PeerProcess, output: ProcessOutput, marker: str) -> None:
    if output.return_code != 0 or marker not in output.stdout:
        raise RuntimeError(
            f"{peer.label} failed (exit {output.return_code})\n"
            f"stdout:\n{output.stdout}\nstderr:\n{output.stderr}"
        )


async def run_pair(
    case: CardinalityCase,
    client_language: Language,
    server_language: Language,
    rust_peer: Path,
    python_peer: Path,
    directory: Path,
    env: dict[str, str],
) -> None:
    peers: list[PeerProcess] = []
    try:
        server = await start_server(
            server_language, rust_peer, python_peer, directory, env, peers
        )
        client = await spawn_peer(
            client_language,
            "client",
            server.port,
            rust_peer,
            python_peer,
            directory,
            env,
            peers,
        )
        client_output = await collect_process(client, PROCESS_TIMEOUT_SECONDS)
        require_process_success(client, client_output, "CLIENT_OK")
        server_output = await collect_process(server.peer, PROCESS_TIMEOUT_SECONDS)
        require_process_success(server.peer, server_output, "SERVER_OK")
    except Exception:
        await stop_peers(peers)
        raise
    print(f"PASS {case.name} {client_language.value} -> {server_language.value}")


async def stop_peer(peer: PeerProcess) -> None:
    if peer.process.returncode is None:
        peer.process.kill()
    try:
        await asyncio.wait_for(peer.process.communicate(), timeout=5)
    except TimeoutError:
        pass


async def stop_peers(peers: list[PeerProcess]) -> None:
    for peer in peers:
        await stop_peer(peer)


def case_environment(directory: Path) -> dict[str, str]:
    environment = os.environ.copy()
    go_temp = directory / "go-tmp"
    go_temp.mkdir(exist_ok=True)
    environment["TMPDIR"] = str(directory)
    environment["GOTMPDIR"] = str(go_temp)
    python_paths = [str(directory)]
    existing_path = environment.get("PYTHONPATH")
    if existing_path:
        python_paths.append(existing_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    return environment


async def run_case(
    case: CardinalityCase,
    generator: Path,
    project: Path,
    target: Path,
    directory: Path,
) -> None:
    env = case_environment(directory)
    python_peer = directory / "python-peer" / case.python_peer_name
    generate_module(
        generator,
        Language.PYTHON,
        FIXTURE_ROOT / case.fixture_name,
        directory / "generated.py",
        env,
    )
    rust_peer = prepare_rust_peer(case, generator, project, target, env)
    for client_language in LANGUAGES:
        for server_language in LANGUAGES:
            await run_pair(
                case,
                client_language,
                server_language,
                rust_peer,
                python_peer,
                directory,
                env,
            )


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(
            prefix=".cueflow-interop-", dir=REPOSITORY
        ) as temporary:
            directory = Path(temporary)
            shutil.copytree(PYTHON_PEERS, directory / "python-peer")
            env = case_environment(directory)
            generator = build_generator(directory, env)
            project = directory / "rust-peer"
            shutil.copytree(RUST_TESTDATA, project)
            target = directory / "cargo-target"
            for case in CASES:
                asyncio.run(run_case(case, generator, project, target, directory))
    except Exception as error:
        print(f"interop tests failed: {error}", file=sys.stderr)
        return 1
    print("All 16 Query/Result cardinality and language combinations passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
