#!/usr/bin/env python3
"""Verify Close methods remain available after both endpoints enter terminal state."""

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
PROTOCOL = REPOSITORY / "cue/testdata/websocket_terminal"
RUST_TEMPLATE = REPOSITORY / "internal/backend/rust/testdata/websocket"
RUST_PEER = REPOSITORY / "internal/backend/rust/testdata/interop/terminal_websocket_peer.rs"
PYTHON_PEER = REPOSITORY / "internal/backend/python/testdata/interop/terminal_websocket_peer.py"
READY_TIMEOUT_SECONDS = 10
PROCESS_TIMEOUT_SECONDS = 30


class Language(Enum):
    RUST = "rust"
    PYTHON = "python"


class Role(Enum):
    CLIENT = "client"
    SERVER = "server"


@dataclass
class PeerProcess:
    label: str
    process: asyncio.subprocess.Process


@dataclass(frozen=True)
class ProcessOutput:
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class LanguagePair:
    client: Language
    server: Language


@dataclass
class RunningPair:
    server: PeerProcess
    client: PeerProcess


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


def generation_command(
    generator: Path, language: Language, protocol: Path, output: Path
) -> list[str]:
    runtime = "tokio" if language is Language.RUST else "asyncio"
    return [
        str(generator),
        "generate",
        language.value,
        "--input",
        str(protocol),
        "--output",
        str(output),
        "--endpoint",
        "both",
        "--runtime",
        runtime,
        "--transport",
        "websocket",
        "--codec",
        "json",
    ]


def build_generator(directory: Path, environment: dict[str, str]) -> Path:
    generator = directory / "cueflow"
    run_command(
        ["go", "build", "-o", str(generator), "./cmd/cueflow"],
        "building cueflow",
        environment,
    )
    return generator


def build_rust_peer(
    generator: Path, directory: Path, environment: dict[str, str]
) -> Path:
    project = directory / "rust-project"
    shutil.copytree(RUST_TEMPLATE, project)
    run_command(
        generation_command(generator, Language.RUST, PROTOCOL, project / "src/lib.rs"),
        "generating terminal Rust API",
        environment,
    )
    source = project / "src/bin/terminal_websocket_peer.rs"
    source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUST_PEER, source)
    cargo_environment = environment.copy()
    cargo_environment["CARGO_TARGET_DIR"] = str(directory / "cargo-target")
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
            "terminal_websocket_peer",
        ],
        "building terminal Rust WebSocket peer",
        cargo_environment,
    )
    return Path(cargo_environment["CARGO_TARGET_DIR"]) / "debug/terminal_websocket_peer"


async def spawn_peer(
    label: str,
    command: list[str],
    directory: Path,
    environment: dict[str, str],
) -> PeerProcess:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=directory,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return PeerProcess(label, process)


async def read_server_port(peer: PeerProcess) -> int:
    if peer.process.stdout is None:
        raise RuntimeError(f"{peer.label} has no stdout pipe")
    try:
        line = await asyncio.wait_for(
            peer.process.stdout.readline(), READY_TIMEOUT_SECONDS
        )
    except TimeoutError as error:
        raise RuntimeError(f"{peer.label} did not become ready") from error
    fields = line.decode("utf-8").strip().split()
    if len(fields) != 2 or fields[0] != "READY":
        output = await collect(peer)
        raise RuntimeError(f"{peer.label} failed to bind:\n{output.stderr}")
    return int(fields[1])


async def collect(peer: PeerProcess) -> ProcessOutput:
    try:
        stdout, stderr = await asyncio.wait_for(
            peer.process.communicate(), PROCESS_TIMEOUT_SECONDS
        )
    except TimeoutError as error:
        await stop(peer)
        raise RuntimeError(f"{peer.label} timed out") from error
    return ProcessOutput(
        peer.process.returncode or 0,
        stdout.decode("utf-8"),
        stderr.decode("utf-8"),
    )


async def stop(peer: PeerProcess) -> None:
    if peer.process.returncode is None:
        peer.process.kill()
    await peer.process.communicate()


def peer_command(
    language: Language,
    role: Role,
    port: int,
    rust_peer: Path,
    python_peer: Path,
) -> list[str]:
    if language is Language.RUST:
        return [str(rust_peer), role.value, str(port)]
    return [sys.executable, str(python_peer), role.value, str(port)]


async def spawn_pair(
    client_language: Language,
    server_language: Language,
    rust_peer: Path,
    python_peer: Path,
    directory: Path,
    environment: dict[str, str],
) -> RunningPair:
    server = await spawn_peer(
        f"{server_language.value} server",
        peer_command(server_language, Role.SERVER, 0, rust_peer, python_peer),
        directory,
        environment,
    )
    try:
        port = await read_server_port(server)
        client = await spawn_peer(
            f"{client_language.value} client",
            peer_command(client_language, Role.CLIENT, port, rust_peer, python_peer),
            directory,
            environment,
        )
    except Exception:
        await stop(server)
        raise
    return RunningPair(server, client)


async def check_pair(pair: RunningPair) -> None:
    try:
        client_output = await collect(pair.client)
        server_output = await collect(pair.server)
        if client_output.return_code != 0 or "TERMINAL_CLIENT_OK" not in client_output.stdout:
            raise RuntimeError(
                f"{pair.client.label} failed:\n{client_output.stdout}{client_output.stderr}"
            )
        if server_output.return_code != 0 or "TERMINAL_SERVER_OK" not in server_output.stdout:
            raise RuntimeError(
                f"{pair.server.label} failed:\n{server_output.stdout}{server_output.stderr}"
            )
    finally:
        await stop(pair.client)
        await stop(pair.server)


async def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".cueflow-terminal-websocket-", dir=REPOSITORY
    ) as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        environment["GOCACHE"] = str(directory / "go-cache")
        generator = build_generator(directory, environment)
        python_module = directory / "generated_terminal.py"
        run_command(
            generation_command(
                generator, Language.PYTHON, PROTOCOL, python_module
            ),
            "generating terminal Python API",
            environment,
        )
        python_peer = directory / "terminal_websocket_peer.py"
        shutil.copyfile(PYTHON_PEER, python_peer)
        run_command(
            [
                "mypy",
                "--strict",
                "--cache-dir",
                str(directory / "mypy-cache"),
                str(python_module),
                str(python_peer),
            ],
            "type-checking terminal Python WebSocket peer",
            environment,
        )
        rust_peer = build_rust_peer(generator, directory, environment)
        environment["PYTHONPATH"] = str(directory)
        for languages in [
            LanguagePair(Language.PYTHON, Language.RUST),
            LanguagePair(Language.RUST, Language.PYTHON),
        ]:
            pair = await spawn_pair(
                languages.client,
                languages.server,
                rust_peer,
                python_peer,
                directory,
                environment,
            )
            await check_pair(pair)
            print(
                f"PASS terminal Close {languages.client.value} client -> "
                f"{languages.server.value} server"
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"Terminal WebSocket checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
