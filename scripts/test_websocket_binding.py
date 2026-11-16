#!/usr/bin/env python3
"""Compile generated WebSocket adapters and run both Rust/Python directions."""

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
PROTOCOL = REPOSITORY / "cue/testdata/websocket_nested"
AMBIGUOUS_SENDS = REPOSITORY / "cue/testdata/endpoint_backend/multiple_sends"
RUST_TEMPLATE = REPOSITORY / "internal/backend/rust/testdata/websocket"
RUST_PEER = REPOSITORY / "internal/backend/rust/testdata/interop/websocket_peer.rs"
PYTHON_PEER = REPOSITORY / "internal/backend/python/testdata/interop/websocket_peer.py"
READY_TIMEOUT_SECONDS = 10
PROCESS_TIMEOUT_SECONDS = 30


class Language(Enum):
    RUST = "rust"
    PYTHON = "python"


class Endpoint(Enum):
    CLIENT = "client"
    SERVER = "server"
    BOTH = "both"


class Runtime(Enum):
    TOKIO = "tokio"
    ASYNCIO = "asyncio"


class Transport(Enum):
    WEBSOCKET = "websocket"


class Codec(Enum):
    JSON = "json"


class PeerRole(Enum):
    CLIENT = "client"
    SERVER = "server"
    ABNORMAL_CLIENT = "abnormal-client"
    ABNORMAL_SERVER = "abnormal-server"


@dataclass
class PeerProcess:
    label: str
    process: asyncio.subprocess.Process


@dataclass(frozen=True)
class ProcessOutput:
    return_code: int
    stdout: str
    stderr: str


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


def generate(
    generator: Path,
    language: Language,
    output: Path,
    environment: dict[str, str],
    endpoint: Endpoint = Endpoint.BOTH,
) -> None:
    command = [
        str(generator),
        "generate",
        language.value,
        "--input",
        str(PROTOCOL),
        "--output",
        str(output),
        "--endpoint",
        endpoint.value,
    ]
    runtime = Runtime.TOKIO if language is Language.RUST else Runtime.ASYNCIO
    command.extend(
        [
            "--runtime",
            runtime.value,
            "--transport",
            Transport.WEBSOCKET.value,
            "--codec",
            Codec.JSON.value,
        ]
    )
    run_command(command, f"generating {language} WebSocket API", environment)


def build_generator(directory: Path, environment: dict[str, str]) -> Path:
    generator = directory / "cueflow"
    run_command(
        ["go", "build", "-o", str(generator), "./cmd/cueflow"],
        "building cueflow",
        environment,
    )
    return generator


def check_options(generator: Path, directory: Path, environment: dict[str, str]) -> None:
    server_source = directory / "server_only.rs"
    generate(generator, Language.RUST, server_source, environment, endpoint=Endpoint.SERVER)
    source = server_source.read_text(encoding="utf-8")
    if "pub mod server" not in source or "pub mod client" in source:
        raise RuntimeError("--endpoint server did not select only the server API")

    client_source = directory / "client_only.py"
    generate(generator, Language.PYTHON, client_source, environment, endpoint=Endpoint.CLIENT)
    python_source = client_source.read_text(encoding="utf-8")
    if "class ClientReady" not in python_source or "class ServerReady" in python_source:
        raise RuntimeError("--endpoint client did not select only the client API")

    invalid = subprocess.run(
        [
            str(generator),
            "generate",
            "rust",
            "--input",
            str(PROTOCOL),
            "--runtime",
            "tokio",
            "--transport",
            "websocket",
        ],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        capture_output=True,
    )
    if invalid.returncode == 0 or "must be selected together" not in invalid.stderr:
        raise RuntimeError("incomplete binding axes were not rejected clearly")

    check_ambiguous_websocket_binding(generator, directory, environment)


def check_ambiguous_websocket_binding(
    generator: Path, directory: Path, environment: dict[str, str]
) -> None:
    expected_error = (
        'multiple server send transitions, ambiguous for endpoint "client"'
    )
    for language in Language:
        runtime = Runtime.TOKIO if language is Language.RUST else Runtime.ASYNCIO
        result = subprocess.run(
            [
                str(generator),
                "generate",
                language.value,
                "--input",
                str(AMBIGUOUS_SENDS),
                "--output",
                str(directory / f"ambiguous-{language.value}.out"),
                "--endpoint",
                Endpoint.CLIENT.value,
                "--runtime",
                runtime.value,
                "--transport",
                Transport.WEBSOCKET.value,
                "--codec",
                Codec.JSON.value,
            ],
            cwd=REPOSITORY,
            env=environment,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0 or expected_error not in result.stderr:
            raise RuntimeError(
                f"{language.value} WebSocket client did not reject ambiguous sends:\n"
                f"{result.stdout}{result.stderr}"
            )
        print(f"PASS reject ambiguous WebSocket sends for {language.value} client")


def build_rust_peer(
    generator: Path,
    directory: Path,
    environment: dict[str, str],
) -> Path:
    project = directory / "rust-project"
    shutil.copytree(RUST_TEMPLATE, project)
    generate(generator, Language.RUST, project / "src" / "lib.rs", environment)
    source = project / "src" / "bin" / "websocket_peer.rs"
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
            "websocket_peer",
        ],
        "building generated Rust WebSocket peer",
        cargo_environment,
    )
    run_command(
        [
            "cargo",
            "test",
            "--offline",
            "--manifest-path",
            str(project / "Cargo.toml"),
            "--test",
            "close_timeout",
        ],
        "testing Rust WebSocket close timeouts",
        cargo_environment,
    )
    print("PASS Rust WebSocket Close timeout cases")
    return Path(cargo_environment["CARGO_TARGET_DIR"]) / "debug" / "websocket_peer"


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
        line = await asyncio.wait_for(peer.process.stdout.readline(), READY_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise RuntimeError(f"{peer.label} did not become ready") from error
    values = line.decode("utf-8").strip().split()
    if len(values) != 2 or values[0] != "READY":
        output = await collect(peer)
        raise RuntimeError(f"{peer.label} failed to bind:\n{output.stderr}")
    return int(values[1])


async def collect(peer: PeerProcess) -> ProcessOutput:
    try:
        stdout, stderr = await asyncio.wait_for(
            peer.process.communicate(), PROCESS_TIMEOUT_SECONDS
        )
    except TimeoutError as error:
        await stop(peer)
        raise RuntimeError(f"{peer.label} timed out") from error
    return ProcessOutput(
        return_code=peer.process.returncode or 0,
        stdout=stdout.decode("utf-8"),
        stderr=stderr.decode("utf-8"),
    )


def require_success(peer: PeerProcess, output: ProcessOutput, marker: str) -> None:
    if output.return_code != 0 or marker not in output.stdout:
        raise RuntimeError(
            f"{peer.label} failed (exit {output.return_code})\n"
            f"stdout:\n{output.stdout}\nstderr:\n{output.stderr}"
        )


async def stop(peer: PeerProcess) -> None:
    if peer.process.returncode is None:
        peer.process.kill()
    await peer.process.communicate()


def peer_command(
    language: Language,
    role: PeerRole,
    port: int,
    rust_peer: Path,
    python_peer: Path,
) -> list[str]:
    if language is Language.RUST:
        return [str(rust_peer), role.value, str(port)]
    return [sys.executable, str(python_peer), role.value, str(port)]


async def run_pair(
    client_language: Language,
    server_language: Language,
    rust_peer: Path,
    python_peer: Path,
    directory: Path,
    environment: dict[str, str],
    client_role: PeerRole = PeerRole.CLIENT,
    server_role: PeerRole = PeerRole.SERVER,
    client_marker: str = "CLIENT_OK",
    server_marker: str = "SERVER_OK",
) -> None:
    peers: list[PeerProcess] = []
    try:
        server = await spawn_peer(
            f"{server_language.value} server",
            peer_command(server_language, server_role, 0, rust_peer, python_peer),
            directory,
            environment,
        )
        peers.append(server)
        port = await read_server_port(server)
        client = await spawn_peer(
            f"{client_language.value} client",
            peer_command(client_language, client_role, port, rust_peer, python_peer),
            directory,
            environment,
        )
        peers.append(client)
        client_output = await collect(client)
        require_success(client, client_output, client_marker)
        server_output = await collect(server)
        require_success(server, server_output, server_marker)
    finally:
        for peer in peers:
            await stop(peer)
    print(
        f"PASS {client_language.value} client -> {server_language.value} server"
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix=".cueflow-websocket-", dir=REPOSITORY) as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        go_temp = directory / "go-tmp"
        go_temp.mkdir()
        environment["TMPDIR"] = str(directory)
        environment["GOTMPDIR"] = str(go_temp)
        environment["GOCACHE"] = str(directory / "go-cache")
        environment["PYTHONPATH"] = str(directory)
        generator = build_generator(directory, environment)
        check_options(generator, directory, environment)
        python_module = directory / "generated.py"
        generate(generator, Language.PYTHON, python_module, environment)
        python_peer = directory / "websocket_peer.py"
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
            "type-checking generated Python WebSocket API",
            environment,
        )
        rust_peer = build_rust_peer(generator, directory, environment)
        await run_pair(
            Language.PYTHON,
            Language.RUST,
            rust_peer,
            python_peer,
            directory,
            environment,
        )
        await run_pair(
            Language.RUST,
            Language.PYTHON,
            rust_peer,
            python_peer,
            directory,
            environment,
        )
        await run_pair(
            Language.RUST,
            Language.PYTHON,
            rust_peer,
            python_peer,
            directory,
            environment,
            client_role=PeerRole.ABNORMAL_CLIENT,
            server_role=PeerRole.ABNORMAL_SERVER,
            client_marker="ABNORMAL_CLOSE_REJECTED",
            server_marker="ABNORMAL_SERVER_OK",
        )
        await run_pair(
            Language.PYTHON,
            Language.RUST,
            rust_peer,
            python_peer,
            directory,
            environment,
            client_role=PeerRole.ABNORMAL_CLIENT,
            server_role=PeerRole.ABNORMAL_SERVER,
            client_marker="ABNORMAL_CLOSE_REJECTED",
            server_marker="ABNORMAL_SERVER_OK",
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"WebSocket binding checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("WebSocket JSON binding checks passed")
