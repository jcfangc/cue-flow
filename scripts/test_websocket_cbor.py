#!/usr/bin/env python3
"""Compile generated CBOR adapters and exercise Rust/Python WebSocket peers."""

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

from websockets.asyncio.client import connect


REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL = REPOSITORY / "cue/testdata/websocket_nested"
RUST_TEMPLATE = REPOSITORY / "internal/backend/rust/testdata/websocket"
RUST_PEER = REPOSITORY / "internal/backend/rust/testdata/interop/websocket_cbor_peer.rs"
PYTHON_PEER = REPOSITORY / "internal/backend/python/testdata/interop/websocket_cbor_peer.py"
READY_TIMEOUT_SECONDS = 10
PROCESS_TIMEOUT_SECONDS = 30


class Language(Enum):
    RUST = "rust"
    PYTHON = "python"


class PeerRole(Enum):
    CLIENT = "client"
    SERVER = "server"
    ABNORMAL_CLIENT = "abnormal-client"
    ABNORMAL_SERVER = "abnormal-server"
    REJECT_DUPLICATE_KEYS = "reject-duplicate-keys"
    REJECT_TEXT_FRAME = "reject-text-frame"
    REJECT_MALFORMED_CBOR = "reject-malformed-cbor"


class InvalidFrame(Enum):
    DUPLICATE_KEYS = "reject-duplicate-keys"
    TEXT = "reject-text-frame"
    MALFORMED_CBOR = "reject-malformed-cbor"


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
class PeerDirection:
    client: Language
    server: Language


INVALID_FRAME_PAYLOADS: dict[InvalidFrame, bytes | str] = {
    # Valid nested Query except that the "id" key occurs twice.
    InvalidFrame.DUPLICATE_KEYS: bytes.fromhex(
        "a3 62 69 64 65 66 69 72 73 74 "
        "62 69 64 66 73 65 63 6f 6e 64 "
        "66 66 69 6c 74 65 72 a2 "
        "68 73 65 71 75 65 6e 63 65 64 41 43 47 54 "
        "65 72 61 6e 67 65 a2 64 74 6f 70 4b 05 "
        "66 61 63 74 69 76 65 f5"
    ),
    InvalidFrame.TEXT: "not a CBOR binary frame",
    InvalidFrame.MALFORMED_CBOR: b"\xa1",
}


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
) -> None:
    runtime = "tokio" if language is Language.RUST else "asyncio"
    run_command(
        [
            str(generator),
            "generate",
            language.value,
            "--input",
            str(PROTOCOL),
            "--output",
            str(output),
            "--endpoint",
            "both",
            "--runtime",
            runtime,
            "--transport",
            "websocket",
            "--codec",
            "cbor",
        ],
        f"generating {language.value} WebSocket CBOR API",
        environment,
    )


def build_generator(directory: Path, environment: dict[str, str]) -> Path:
    generator = directory / "cueflow"
    run_command(
        ["go", "build", "-o", str(generator), "./cmd/cueflow"],
        "building cueflow",
        environment,
    )
    return generator


def build_rust_peer(
    generator: Path,
    directory: Path,
    environment: dict[str, str],
) -> Path:
    project = directory / "rust-project"
    shutil.copytree(RUST_TEMPLATE, project)
    generate(generator, Language.RUST, project / "src" / "lib.rs", environment)
    peer_source = project / "src" / "bin" / "websocket_cbor_peer.rs"
    peer_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RUST_PEER, peer_source)
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
            "websocket_cbor_peer",
        ],
        "building generated Rust WebSocket CBOR peer",
        cargo_environment,
    )
    return Path(cargo_environment["CARGO_TARGET_DIR"]) / "debug" / "websocket_cbor_peer"


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
    abnormal: bool = False,
) -> None:
    peers: list[PeerProcess] = []
    try:
        server_role = PeerRole.ABNORMAL_SERVER if abnormal else PeerRole.SERVER
        client_role = PeerRole.ABNORMAL_CLIENT if abnormal else PeerRole.CLIENT
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
        server_output = await collect(server)
        expected_client = "ABNORMAL_CLOSE_REJECTED" if abnormal else "CLIENT_OK"
        expected_server = "ABNORMAL_SERVER_OK" if abnormal else "SERVER_OK"
        require_success(client, client_output, expected_client)
        require_success(server, server_output, expected_server)
    finally:
        for peer in peers:
            await stop(peer)
    mode = " abnormal-close" if abnormal else " normal-close"
    print(f"PASS {client_language.value} -> {server_language.value}{mode}")


async def run_invalid_frame_case(
    language: Language,
    invalid_frame: InvalidFrame,
    rust_peer: Path,
    python_peer: Path,
    directory: Path,
    environment: dict[str, str],
) -> None:
    role = PeerRole(invalid_frame.value)
    server = await spawn_peer(
        f"{language.value} invalid-frame server",
        peer_command(language, role, 0, rust_peer, python_peer),
        directory,
        environment,
    )
    try:
        port = await read_server_port(server)
        async with connect(f"ws://127.0.0.1:{port}") as websocket:
            await websocket.send(INVALID_FRAME_PAYLOADS[invalid_frame])
        output = await collect(server)
        require_success(server, output, "INVALID_FRAME_REJECTED")
    finally:
        await stop(server)
    print(f"PASS {language.value} rejects {invalid_frame.name.lower()}")


async def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix=".cueflow-websocket-cbor-", dir=REPOSITORY
    ) as temporary:
        directory = Path(temporary)
        environment = os.environ.copy()
        go_temp = directory / "go-tmp"
        go_temp.mkdir()
        environment["TMPDIR"] = str(directory)
        environment["GOTMPDIR"] = str(go_temp)
        environment["GOCACHE"] = str(directory / "go-cache")
        environment["PYTHONPATH"] = str(directory)

        generator = build_generator(directory, environment)
        rust_peer = build_rust_peer(generator, directory, environment)
        python_source = directory / "generated.py"
        generate(generator, Language.PYTHON, python_source, environment)
        python_peer = directory / "websocket_cbor_peer.py"
        shutil.copyfile(PYTHON_PEER, python_peer)
        run_command(
            [
                "mypy",
                "--strict",
                "--cache-dir",
                str(directory / "mypy-cache"),
                str(python_source),
                str(python_peer),
            ],
            "type-checking generated CBOR API and Python peer",
            environment,
        )

        directions = [
            PeerDirection(client=Language.PYTHON, server=Language.RUST),
            PeerDirection(client=Language.RUST, server=Language.PYTHON),
        ]
        for direction in directions:
            await run_pair(
                direction.client,
                direction.server,
                rust_peer,
                python_peer,
                directory,
                environment,
            )
            await run_pair(
                direction.client,
                direction.server,
                rust_peer,
                python_peer,
                directory,
                environment,
                abnormal=True,
            )
        for language in Language:
            for invalid_frame in InvalidFrame:
                await run_invalid_frame_case(
                    language,
                    invalid_frame,
                    rust_peer,
                    python_peer,
                    directory,
                    environment,
                )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"WebSocket CBOR checks failed: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("WebSocket CBOR checks passed")
