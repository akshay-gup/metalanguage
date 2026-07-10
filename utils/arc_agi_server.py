"""Launch and supervise the official ARC-AGI HTTP server."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO

from utils.arc_agi_env import PROJECT_ROOT, load_arc_agi_modules, load_env_file


LOOPBACK_HOST = "127.0.0.1"
OPERATION_MODES = ("normal", "online", "offline", "competition")


class ArcAgiServerError(RuntimeError):
    """Raised when the ARC server cannot be started or made ready."""


class ArcAgiServerExited(ArcAgiServerError):
    """Raised when the ARC server process exits before becoming ready."""


@dataclass
class ArcAgiServerProcess:
    """An owned official ARC server subprocess."""

    host: str
    port: int
    base_url: str
    process: subprocess.Popen[bytes]

    def wait_ready(
        self,
        timeout: float = 30.0,
        *,
        request_timeout: float = 0.5,
        poll_interval: float = 0.1,
    ) -> None:
        """Wait until ``GET /api/games`` returns a JSON list."""

        deadline = time.monotonic() + timeout
        endpoint = f"{self.base_url}/api/games"
        while True:
            returncode = self.process.poll()
            if returncode is not None:
                raise ArcAgiServerExited(
                    f"ARC server exited before readiness (exit code {returncode})"
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ArcAgiServerError(
                    f"ARC server was not ready at {self.base_url} within {timeout:g}s"
                )
            try:
                with urllib.request.urlopen(
                    endpoint, timeout=min(request_timeout, remaining)
                ) as response:
                    if response.status == 200 and isinstance(
                        json.load(response), list
                    ):
                        return
            except (
                OSError,
                TimeoutError,
                ValueError,
                urllib.error.URLError,
            ):
                pass
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    def terminate(self, timeout: float = 5.0) -> int:
        """Stop the child, escalating from terminate to kill after ``timeout``."""

        returncode = self.process.poll()
        if returncode is not None:
            return returncode
        self.process.terminate()
        try:
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            return self.process.wait(timeout=timeout)

    cleanup = terminate

    def __enter__(self) -> ArcAgiServerProcess:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.terminate()


def _select_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK_HOST, 0))
        return int(sock.getsockname()[1])


def _open_log(path: str | os.PathLike[str] | None) -> BinaryIO | int:
    if path is None:
        return subprocess.DEVNULL
    return open(path, "ab", buffering=0)


def launch_arc_agi_server(
    *,
    port: int | None = None,
    readiness_timeout: float = 30.0,
    startup_attempts: int = 3,
    stdout_log: str | os.PathLike[str] | None = None,
    stderr_log: str | os.PathLike[str] | None = None,
    operation_mode: str = "normal",
    competition_mode: bool = False,
    save_all_recordings: bool = False,
    include_frame_data: bool = True,
    scorecard_timeout: int | None = None,
) -> ArcAgiServerProcess:
    """Start the official server on loopback and wait for readiness.

    When ``port`` is omitted, a free port is selected before spawning. There is
    an unavoidable small race before the child binds it; early child exits are
    retried with a fresh port up to ``startup_attempts`` times.

    The child inherits the current environment. In particular, credentials are
    never placed in argv or wrapper-generated output.
    """

    if port is not None and not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if startup_attempts < 1:
        raise ValueError("startup_attempts must be at least 1")
    if operation_mode not in OPERATION_MODES:
        raise ValueError(f"operation_mode must be one of {OPERATION_MODES}")

    load_env_file()
    ephemeral = port is None
    attempts = startup_attempts if ephemeral else 1
    last_error: ArcAgiServerError | None = None
    for _attempt in range(attempts):
        selected_port = _select_ephemeral_port() if ephemeral else port
        assert selected_port is not None
        command = [
            sys.executable,
            "-m",
            "utils.arc_agi_server",
            "serve",
            "--port",
            str(selected_port),
            "--operation-mode",
            operation_mode,
        ]
        if competition_mode:
            command.append("--competition-mode")
        if save_all_recordings:
            command.append("--save-all-recordings")
        if not include_frame_data:
            command.append("--no-frame-data")
        if scorecard_timeout is not None:
            command.extend(("--scorecard-timeout", str(scorecard_timeout)))

        stdout = _open_log(stdout_log)
        try:
            stderr = _open_log(stderr_log)
            try:
                process = subprocess.Popen(
                    command,
                    cwd=PROJECT_ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                )
            finally:
                if hasattr(stderr, "close"):
                    stderr.close()
        finally:
            if hasattr(stdout, "close"):
                stdout.close()

        server = ArcAgiServerProcess(
            host=LOOPBACK_HOST,
            port=selected_port,
            base_url=f"http://{LOOPBACK_HOST}:{selected_port}",
            process=process,
        )
        try:
            server.wait_ready(readiness_timeout)
            return server
        except ArcAgiServerExited as exc:
            last_error = exc
            server.terminate()
            if not ephemeral:
                raise
        except Exception:
            server.terminate()
            raise

    raise last_error or ArcAgiServerError("ARC server failed to start")


def serve(
    *,
    port: int,
    operation_mode: str = "normal",
    competition_mode: bool = False,
    save_all_recordings: bool = False,
    include_frame_data: bool = True,
    scorecard_timeout: int | None = None,
) -> None:
    """Blocking child entry point for the official ARC server."""

    load_env_file()
    modules = load_arc_agi_modules()
    mode = modules.arc_agi.OperationMode(operation_mode)
    os.environ["OPERATION_MODE"] = mode.value
    arcade = modules.arc_agi.Arcade(operation_mode=mode)
    arcade.listen_and_serve(
        host=LOOPBACK_HOST,
        port=port,
        competition_mode=competition_mode,
        save_all_recordings=save_all_recordings,
        include_frame_data=include_frame_data,
        scorecard_timeout=scorecard_timeout,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve_parser = subparsers.add_parser(
        "serve", help="Run the official server (blocking)."
    )
    serve_parser.add_argument("--port", type=int, required=True)
    serve_parser.add_argument(
        "--operation-mode",
        choices=OPERATION_MODES,
        default="normal",
    )
    serve_parser.add_argument("--competition-mode", action="store_true")
    serve_parser.add_argument("--save-all-recordings", action="store_true")
    serve_parser.add_argument("--no-frame-data", action="store_true")
    serve_parser.add_argument("--scorecard-timeout", type=int)
    args = parser.parse_args()
    if args.command == "serve":
        serve(
            port=args.port,
            operation_mode=args.operation_mode,
            competition_mode=args.competition_mode,
            save_all_recordings=args.save_all_recordings,
            include_frame_data=not args.no_frame_data,
            scorecard_timeout=args.scorecard_timeout,
        )


if __name__ == "__main__":
    main()
