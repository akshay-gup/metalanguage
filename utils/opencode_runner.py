"""Thin Python adapter for the Metalanguage-owned TypeScript/Bun OpenCode worker."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from utils.private_inbox import PrivateInboxConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_WORKER_SCRIPT = PROJECT_ROOT / "workers" / "opencode" / "worker.ts"
SOURCE_AUDITED_OPENCODE_VERSIONS = ("1.18.29",)
SOURCE_AUDITED_BUN_VERSIONS = ("1.3.14",)
DEFAULT_BUBBLEWRAP_BIN = Path("/usr/bin/bwrap")
# OpenCode 1.18.29's worker-facing SDK, permission, HTTP, plugin, MCP, CLI, and
# runtime-flag seams were checked against the vendored 1.18.21 source. Both
# entries remain bundled, so this closed allowlist prevents Npm.add() installs.
SUPPORTED_CUSTOM_PROVIDER_NPM = {
    "@ai-sdk/openai-compatible": "chat_completions",
    "@ai-sdk/openai": "responses",
}
MAX_CUSTOM_PROVIDER_URL_LENGTH = 2048
MAX_CUSTOM_PROVIDER_NAME_LENGTH = 128
MAX_CUSTOM_PROVIDER_LIMIT = 100_000_000
_CUSTOM_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_CUSTOM_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}\Z")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}\Z")
_UNSAFE_CUSTOM_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

_BASE_ENVIRONMENT_NAMES = {
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "NO_COLOR",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "TERM",
    "TZ",
}

_PATH_ENVIRONMENT_KINDS = {
    "AWS_CONFIG_FILE": "file",
    "AWS_SHARED_CREDENTIALS_FILE": "file",
    "AZURE_AUTH_LOCATION": "file",
    "CURL_CA_BUNDLE": "file",
    "GOOGLE_APPLICATION_CREDENTIALS": "file",
    "REQUESTS_CA_BUNDLE": "file",
    "SSL_CERT_DIR": "directory",
    "SSL_CERT_FILE": "file",
}
_CREDENTIAL_MOUNT_ROOT = Path("/run/metalanguage/credentials")
MAX_CREDENTIAL_FILES = 4096
MAX_CREDENTIAL_BYTES = 64 * 1024 * 1024
MAX_CREDENTIAL_DEPTH = 16
_DURABLE_ERROR_CODES = {
    "APIError",
    "MessageAbortedError",
    "MessageOutputLengthError",
    "ProviderAuthError",
    "UnknownError",
    "invalid_mcp_configuration",
    "invalid_custom_provider",
    "invalid_model",
    "invalid_sandbox_mount",
    "invalid_working_directory",
    "benchmark_mcp_bridge_failed",
    "benchmark_mcp_bridge_requires_sandbox",
    "benchmark_mcp_bridge_timeout",
    "benchmark_mcp_proxy_unavailable",
    "malformed_opencode_event",
    "malformed_opencode_response",
    "malformed_runner_output",
    "opencode_event_closed",
    "opencode_event_connect_failed",
    "opencode_event_protocol",
    "opencode_event_timeout",
    "opencode_http_error",
    "opencode_http_timeout",
    "opencode_prompt_failed",
    "opencode_prompt_submit_failed",
    "opencode_prompt_submit_timeout",
    "opencode_prompt_timeout",
    "opencode_session_error",
    "opencode_start_failed",
    "opencode_start_timeout",
    "opencode_version_failed",
    "opencode_version_timeout",
    "opencode_worker_failed",
    "permission_requested",
    "required_mcp_server_unavailable",
    "state_isolation_failed",
    "test_provider_forbidden",
    "unsupported_bun_version",
    "unsupported_opencode_version",
    "unsupported_sandbox_network_mode",
    "worker_cancelled",
    "worker_timeout",
}
_PROVIDER_ENVIRONMENT = {
    "anthropic": {"ANTHROPIC_API_KEY"},
    "cerebras": {"CEREBRAS_API_KEY"},
    "deepseek": {"DEEPSEEK_API_KEY"},
    "google": {"GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"},
    "google-vertex": {
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
    },
    "groq": {"GROQ_API_KEY"},
    "mistral": {"MISTRAL_API_KEY"},
    "openai": {"OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"},
    "openrouter": {"OPENROUTER_API_KEY"},
    "xai": {"XAI_API_KEY"},
}


def _validate_provider_environment_name(name: str) -> str:
    if not _ENVIRONMENT_NAME.fullmatch(name):
        raise ValueError(f"invalid OpenCode provider environment variable name: {name!r}")
    if name in {"HOME", "PATH", "TMPDIR"} or name.startswith(
        ("XDG_", "OPENCODE_", "METALANGUAGE_")
    ):
        raise ValueError(f"OpenCode provider environment variable is reserved: {name}")
    return name


def _validate_custom_secret_environment_name(name: str) -> str:
    validated = _validate_provider_environment_name(name)
    if validated in _PATH_ENVIRONMENT_KINDS or validated in _BASE_ENVIRONMENT_NAMES:
        raise ValueError(
            f"custom OpenCode provider secret environment variable is transport-reserved: {validated}"
        )
    return validated


def _custom_provider_base_url(value: str) -> str:
    if not value or len(value) > MAX_CUSTOM_PROVIDER_URL_LENGTH:
        raise ValueError("--opencode-custom-provider-base-url has an invalid length")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("--opencode-custom-provider-base-url is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--opencode-custom-provider-base-url must use HTTP or HTTPS with a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("--opencode-custom-provider-base-url must not include user information")
    if parsed.query or parsed.fragment:
        raise ValueError("--opencode-custom-provider-base-url must not include a query or fragment")
    hostname = parsed.hostname.rstrip(".").lower()
    loopback = hostname == "localhost"
    try:
        address = ipaddress.ip_address(hostname)
        loopback = loopback or address.is_loopback
    except ValueError:
        labels = hostname.split(".")
        if (
            len(hostname) > 253
            or any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise ValueError("--opencode-custom-provider-base-url has an invalid host") from None
    if parsed.scheme == "http" and not loopback:
        raise ValueError(
            "--opencode-custom-provider-base-url requires HTTPS for non-loopback endpoints"
        )
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port is not None else host
    path = parsed.path.rstrip("/") or ""
    return urlunsplit((parsed.scheme, netloc, path, "", ""))


def custom_provider_configuration(
    *,
    model: str,
    provider_id: str | None,
    name: str | None,
    npm: str | None,
    base_url: str | None,
    api_key_env: str | None,
    header_env: tuple[str, ...] = (),
    context_limit: int | None = None,
    output_limit: int | None = None,
) -> dict[str, Any] | None:
    values = (provider_id, name, npm, base_url, api_key_env)
    configured = any(value is not None for value in values) or bool(header_env) or any(
        value is not None for value in (context_limit, output_limit)
    )
    if not configured:
        return None
    required = {
        "--opencode-custom-provider-id": provider_id,
        "--opencode-custom-provider-name": name,
        "--opencode-custom-provider-npm": npm,
        "--opencode-custom-provider-base-url": base_url,
        "--opencode-custom-provider-api-key-env": api_key_env,
    }
    missing = [flag for flag, value in required.items() if value is None or not str(value).strip()]
    if missing:
        raise ValueError(f"custom OpenCode provider configuration is incomplete: missing {', '.join(missing)}")
    assert provider_id is not None and name is not None and npm is not None
    assert base_url is not None and api_key_env is not None
    if not _CUSTOM_PROVIDER_ID.fullmatch(provider_id):
        raise ValueError("--opencode-custom-provider-id must be a lowercase safe identifier")
    model_parts = model.split("/", 1)
    if len(model_parts) != 2 or not model_parts[0] or not model_parts[1]:
        raise ValueError("--model must use provider/model syntax for a custom OpenCode provider")
    model_provider, model_id = model_parts
    if model_provider != provider_id:
        raise ValueError("--model provider ID must match --opencode-custom-provider-id")
    if not _CUSTOM_MODEL_ID.fullmatch(model_id):
        raise ValueError("custom OpenCode model ID contains unsupported characters or length")
    if npm not in SUPPORTED_CUSTOM_PROVIDER_NPM:
        supported = ", ".join(sorted(SUPPORTED_CUSTOM_PROVIDER_NPM))
        raise ValueError(f"unsupported custom OpenCode provider package {npm!r}; supported: {supported}")
    display_name = name.strip()
    if (
        not display_name
        or len(display_name) > MAX_CUSTOM_PROVIDER_NAME_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in display_name)
    ):
        raise ValueError("--opencode-custom-provider-name contains invalid characters or length")
    api_key_name = _validate_custom_secret_environment_name(api_key_env)
    headers: dict[str, str] = {}
    normalized_headers: set[str] = set()
    for item in header_env:
        if "=" not in item:
            raise ValueError("--opencode-custom-provider-header-env must use HEADER=ENV_VAR")
        header, environment_name = item.split("=", 1)
        if not _HEADER_NAME.fullmatch(header):
            raise ValueError(f"invalid custom provider header name: {header!r}")
        lowered = header.lower()
        if lowered in _UNSAFE_CUSTOM_HEADERS:
            raise ValueError(f"custom provider header is transport-controlled: {header}")
        if lowered in normalized_headers:
            raise ValueError(f"duplicate custom provider header: {header}")
        normalized_headers.add(lowered)
        headers[header] = _validate_custom_secret_environment_name(environment_name)
    if (context_limit is None) != (output_limit is None):
        raise ValueError("custom OpenCode context and output limits must be configured together")
    limits: dict[str, int] | None = None
    if context_limit is not None and output_limit is not None:
        for flag, value in (
            ("--opencode-custom-provider-context-limit", context_limit),
            ("--opencode-custom-provider-output-limit", output_limit),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_CUSTOM_PROVIDER_LIMIT:
                raise ValueError(f"{flag} must be a positive integer no greater than {MAX_CUSTOM_PROVIDER_LIMIT}")
        limits = {"context": context_limit, "output": output_limit}
    return {
        "provider_id": provider_id,
        "provider_name": display_name,
        "npm": npm,
        "api_mode": SUPPORTED_CUSTOM_PROVIDER_NPM[npm],
        "base_url": _custom_provider_base_url(base_url),
        "api_key_env": api_key_name,
        "headers": dict(sorted(headers.items(), key=lambda item: item[0].lower())),
        "model_id": model_id,
        "limits": limits,
    }


def custom_provider_fingerprint(configuration: dict[str, Any] | None) -> str | None:
    if configuration is None:
        return None
    payload = json.dumps(configuration, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def custom_provider_environment_names(configuration: dict[str, Any] | None) -> tuple[str, ...]:
    if configuration is None:
        return ()
    names = {str(configuration["api_key_env"])}
    names.update(str(value) for value in configuration.get("headers", {}).values())
    return tuple(sorted(names))


def opencode_worker_script_path() -> Path:
    return OPENCODE_WORKER_SCRIPT


def resolve_opencode_worker_script(worker_script: Path | None) -> Path:
    path = worker_script if worker_script is not None else opencode_worker_script_path()
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"OpenCode TypeScript worker does not exist: {path}")
    return path


def resolve_bun_bin(value: Path | None) -> Path:
    if value is None:
        resolved = shutil.which("bun")
        if resolved is None:
            fallback = Path.home() / ".bun" / "bin" / "bun"
            if fallback.is_file() and os.access(fallback, os.X_OK):
                resolved = str(fallback)
        if resolved is None:
            raise FileNotFoundError(
                "Bun was not found in PATH or ~/.bun/bin/bun; it is required by the OpenCode worker"
            )
        value = Path(resolved)
    path = value.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"Bun executable is not executable: {path}")
    return path


def resolve_opencode_bin(value: Path | None) -> Path:
    if value is None:
        resolved = shutil.which("opencode")
        if resolved is None:
            fallback = Path.home() / ".opencode" / "bin" / "opencode"
            if fallback.is_file() and os.access(fallback, os.X_OK):
                resolved = str(fallback)
        if resolved is None:
            raise FileNotFoundError("opencode was not found in PATH")
        value = Path(resolved)
    path = value.expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"OpenCode executable is not executable: {path}")
    return path


def resolve_bubblewrap_bin(value: Path | None) -> Path:
    path = (value or DEFAULT_BUBBLEWRAP_BIN).expanduser().resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise FileNotFoundError(f"bubblewrap executable is not executable: {path}")
    return path


def validate_opencode_host_primitives(bubblewrap_bin: Path) -> None:
    if sys.platform != "linux":
        raise RuntimeError("OpenCode bubblewrap containment requires Linux")
    proc_status = Path("/proc/self/status")
    if not proc_status.is_file() or not os.access(proc_status, os.R_OK):
        raise RuntimeError("OpenCode containment requires a readable procfs")
    try:
        completed = subprocess.run(
            [
                str(bubblewrap_bin.resolve()),
                "--die-with-parent",
                "--new-session",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-uts",
                "--unshare-cgroup-try",
                "--ro-bind",
                "/",
                "/",
                "--proc",
                "/proc",
                "--",
                "/usr/bin/bash",
                "-c",
                "test -r /proc/1/status",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("OpenCode bubblewrap/proc containment primitives are unavailable") from exc
    if completed.returncode != 0:
        raise RuntimeError("OpenCode bubblewrap/proc containment primitives are unavailable")


def executable_version(path: Path) -> str:
    completed = subprocess.run(
        [str(path.resolve()), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"},
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{path} --version exited {completed.returncode}")
    return completed.stdout.strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def opencode_worker_fingerprint(worker_script: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(worker_script.parent.glob("*.ts")):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for name in ("package.json", "bun.lock", "tsconfig.json"):
        path = worker_script.parent / name
        if path.is_file():
            digest.update(name.encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def opencode_python_fingerprint(main_loop_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (Path(__file__).resolve(), main_loop_path.resolve()):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def text_sha256(value: str | None) -> str:
    return hashlib.sha256((value or "").encode()).hexdigest()


def _path_content_fingerprint(path: Path, kind: str) -> str:
    digest = hashlib.sha256()
    if kind == "file":
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CREDENTIAL_BYTES:
            raise ValueError("OpenCode credential file exceeds the bounded byte limit")
        digest.update(b"file\0")
        read_bytes = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                read_bytes += len(chunk)
                if read_bytes > MAX_CREDENTIAL_BYTES:
                    raise ValueError("OpenCode credential file exceeds the bounded byte limit")
                digest.update(chunk)
        return digest.hexdigest()
    digest.update(b"directory\0")
    file_count = 0
    total_bytes = 0

    def visit(directory: Path, relative_parent: Path, depth: int) -> None:
        nonlocal file_count, total_bytes
        if depth > MAX_CREDENTIAL_DEPTH:
            raise ValueError("OpenCode credential directory exceeds the bounded depth limit")
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise ValueError("OpenCode credential directory is unreadable") from exc
        for entry in entries:
            relative = relative_parent / entry.name
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ValueError("OpenCode credential directory changed during inspection") from exc
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"OpenCode credential directory contains a symlink: {entry.path}")
            if stat.S_ISDIR(info.st_mode):
                digest.update(b"dir\0")
                digest.update(str(relative).encode())
                digest.update(b"\0")
                visit(Path(entry.path), relative, depth + 1)
                continue
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"OpenCode credential directory contains a non-file entry: {entry.path}")
            file_count += 1
            total_bytes += info.st_size
            if file_count > MAX_CREDENTIAL_FILES:
                raise ValueError("OpenCode credential directory exceeds the bounded file limit")
            if total_bytes > MAX_CREDENTIAL_BYTES:
                raise ValueError("OpenCode credential directory exceeds the bounded byte limit")
            digest.update(b"file\0")
            digest.update(str(relative).encode())
            digest.update(b"\0")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(entry.path, flags)
                with os.fdopen(descriptor, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("OpenCode credential directory changed during inspection")
                    observed = 0
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        observed += len(chunk)
                        if total_bytes - info.st_size + observed > MAX_CREDENTIAL_BYTES:
                            raise ValueError("OpenCode credential directory exceeds the bounded byte limit")
                        digest.update(chunk)
            except OSError as exc:
                raise ValueError("OpenCode credential directory changed during inspection") from exc
            digest.update(b"\0")

    visit(path, Path(), 1)
    return digest.hexdigest()


def prepare_provider_environment(
    names: tuple[str, ...],
    *,
    sandbox_mode: str,
) -> tuple[dict[str, str], tuple[tuple[Path, Path], ...]]:
    environment = {
        name: value
        for name in names
        if (value := os.environ.get(name)) is not None
    }
    path_names = (set(names) & _PATH_ENVIRONMENT_KINDS.keys()) | (
        _BASE_ENVIRONMENT_NAMES & _PATH_ENVIRONMENT_KINDS.keys()
    )
    for name in path_names:
        value = os.environ.get(name)
        if value is not None:
            environment[name] = value
    mounts: list[tuple[Path, Path]] = []
    for name in sorted(path_names):
        kind = _PATH_ENVIRONMENT_KINDS[name]
        value = environment.get(name)
        if value is None:
            continue
        source = Path(value).expanduser()
        if not source.is_absolute():
            raise ValueError(f"OpenCode path environment variable {name} must be absolute")
        try:
            source = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"OpenCode path environment variable {name} does not resolve to an existing path"
            ) from exc
        if kind == "file" and not source.is_file():
            raise ValueError(f"OpenCode path environment variable {name} must name a file")
        if kind == "directory" and not source.is_dir():
            raise ValueError(f"OpenCode path environment variable {name} must name a directory")
        _path_content_fingerprint(source, kind)
        if sandbox_mode == "bubblewrap":
            target = _CREDENTIAL_MOUNT_ROOT / name
            environment[name] = str(target)
            mounts.append((source, target))
    return environment, tuple(mounts)


def provider_environment_fingerprint(
    names: tuple[str, ...],
    *,
    sandbox_mode: str = "bubblewrap",
) -> str:
    environment, mounts = prepare_provider_environment(names, sandbox_mode=sandbox_mode)
    mounted = {target.name: source for source, target in mounts}
    digest = hashlib.sha256()
    path_names = (set(names) & _PATH_ENVIRONMENT_KINDS.keys()) | (
        _BASE_ENVIRONMENT_NAMES & _PATH_ENVIRONMENT_KINDS.keys()
    )
    for name in sorted(set(names) | path_names):
        digest.update(name.encode())
        digest.update(b"\0")
        value = os.environ.get(name)
        digest.update(b"present\0" if value is not None else b"absent\0")
        if value is not None:
            kind = _PATH_ENVIRONMENT_KINDS.get(name)
            if kind is None:
                digest.update(value.encode())
            else:
                source = mounted.get(name)
                if source is None:
                    source = Path(value).expanduser().resolve(strict=True)
                    digest.update(str(source).encode())
                    digest.update(b"\0")
                else:
                    digest.update(environment[name].encode())
                    digest.update(b"\0")
                digest.update(_path_content_fingerprint(source, kind).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def provider_environment_names(model: str, explicit: tuple[str, ...] = ()) -> tuple[str, ...]:
    provider = model.split("/", 1)[0].strip().lower()
    names = set(_PROVIDER_ENVIRONMENT.get(provider, set()))
    for name in explicit:
        names.add(_validate_provider_environment_name(name))
    return tuple(sorted(names))


def _rollout_environment(
    *,
    bun_bin: Path,
    opencode_bin: Path,
    provider_env_names: tuple[str, ...],
    provider_environment: dict[str, str] | None = None,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    env = {
        name: value
        for name in _BASE_ENVIRONMENT_NAMES
        if (value := os.environ.get(name)) is not None
    }
    env["PATH"] = os.pathsep.join(
        dict.fromkeys(
            [str(bun_bin.parent), str(opencode_bin.parent), "/usr/local/bin", "/usr/bin", "/bin"]
        )
    )
    if provider_environment is None:
        provider_environment, _ = prepare_provider_environment(
            provider_env_names,
            sandbox_mode="unsafe-none",
        )
    env.update(provider_environment)
    if extra_environment:
        env.update(extra_environment)
    env.setdefault("LANG", "C.UTF-8")
    return env


def _terminate_process_group(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = 3.0,
) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
    process.wait()


def _kill_runtime_process_group(pid: object) -> None:
    if not isinstance(pid, int) or pid <= 1:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _private_runtime_root(worker_state_dir: Path) -> Path:
    worker_state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(worker_state_dir, 0o700)
    root = worker_state_dir / "opencode_runtime"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(mode=0o700)
    if root.parent.resolve() != worker_state_dir.resolve():
        raise RuntimeError("OpenCode runtime root escaped the rollout state directory")
    return root


def _cleanup_host_mcp_roots(worker_state_dir: Path) -> None:
    for path in worker_state_dir.glob(".opencode-mcp-host-*"):
        if path.parent.resolve() != worker_state_dir.resolve():
            raise RuntimeError("OpenCode MCP host root escaped the rollout state directory")
        shutil.rmtree(path, ignore_errors=True)


def _durable_request(request: dict[str, Any]) -> dict[str, Any]:
    """Return diagnostic request metadata without MCP credentials/arguments."""
    durable = json.loads(json.dumps(request))
    for server in durable.get("mcp_servers", {}).values():
        if not isinstance(server, dict):
            continue
        args = server.get("args")
        if isinstance(args, list) and args:
            server["args"] = {"redacted": True, "count": len(args)}
        env = server.get("env")
        if isinstance(env, dict):
            server["env"] = {key: {"redacted": True} for key in env}
    if "auth_file" in durable:
        durable["auth_file"] = {"configured": True}
    if "spawn_child_handler_command" in durable:
        durable["spawn_child_handler_command"] = {"configured": True}
    sandbox = durable.get("sandbox")
    if isinstance(sandbox, dict) and "read_only_mounts" in sandbox:
        sandbox["read_only_mounts"] = [
            {"target": mount.get("target"), "source": {"redacted": True}}
            for mount in sandbox["read_only_mounts"]
            if isinstance(mount, dict)
        ]
    if "test_provider_config" in durable:
        durable["test_provider_config"] = {"configured": True, "redacted": True}
    return durable


def _scrub_durable_value(value: Any, *, preserve_text: bool = False) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if re.search(
                r"authorization|token|api.?key|password|secret|credential|cookie|private.?key",
                lowered,
            ):
                output[key] = {"redacted": True}
            else:
                output[key] = _scrub_durable_value(item, preserve_text=preserve_text)
        return output
    if isinstance(value, list):
        return [_scrub_durable_value(item, preserve_text=preserve_text) for item in value]
    if isinstance(value, str) and not preserve_text:
        if len(value) > 4096 or re.search(
            r"(?:^|[\s=:])(sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._~-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
            value,
            re.IGNORECASE,
        ):
            return {"redacted": True, "characters": len(value)}
    return value


def _durable_event(event: dict[str, Any]) -> dict[str, Any]:
    name = event.get("event")
    if name == "error":
        code = normalize_error_code(event.get("error_code"))
        return {
            **{
                key: value
                for key, value in event.items()
                if key not in {"error_code", "error_message"}
            },
            "error_code": code,
            "error_message": f"OpenCode request failed ({code})",
        }
    if name in {"agent_message", "turn_complete"}:
        return _scrub_durable_value(event, preserve_text=True)
    return _scrub_durable_value(event)


def normalize_error_code(value: object) -> str:
    raw = value if isinstance(value, str) else str(value) if isinstance(value, int) else ""
    if raw in _DURABLE_ERROR_CODES:
        return raw
    return "unknown"


def run_opencode_rollout(
    *,
    worker_script: Path,
    bun_bin: Path,
    opencode_bin: Path,
    model: str,
    workdir: Path,
    control_dir: Path,
    worker_state_dir: Path,
    timeout_seconds: int,
    initial_user_text: str,
    system_instructions: str | None = None,
    continuation_context_path: Path | None = None,
    benchmark_mcp_servers: dict[str, Any] | None = None,
    sensitive_mcp_tools: tuple[tuple[str, str], ...] = (),
    auth_file: Path | None = None,
    agent: str | None = None,
    variant: str | None = None,
    allowed_versions: tuple[str, ...] = SOURCE_AUDITED_OPENCODE_VERSIONS,
    allowed_bun_versions: tuple[str, ...] = SOURCE_AUDITED_BUN_VERSIONS,
    startup_timeout_seconds: int = 15,
    provider_env_names: tuple[str, ...] = (),
    provider_environment: dict[str, str] | None = None,
    custom_provider: dict[str, Any] | None = None,
    sandbox_mode: str = "bubblewrap",
    sandbox_network: str = "allow",
    bubblewrap_bin: Path | None = None,
    sandbox_read_only_roots: tuple[Path, ...] = (),
    sandbox_read_only_mounts: tuple[tuple[Path, Path], ...] = (),
    sandbox_writable_roots: tuple[Path, ...] = (),
    sandbox_masked_paths: tuple[Path, ...] = (),
    sandbox_masked_directories: tuple[Path, ...] = (),
    extra_environment: dict[str, str] | None = None,
    test_provider_config: dict[str, Any] | None = None,
    progress_callback: Callable[..., None] | None = None,
    private_inbox: PrivateInboxConfig | None = None,
) -> dict[str, Any]:
    unsupported_versions = sorted(
        set(allowed_versions) - set(SOURCE_AUDITED_OPENCODE_VERSIONS)
    )
    if not allowed_versions or unsupported_versions:
        raise ValueError("OpenCode allowed versions must be source-audited")
    unsupported_bun_versions = sorted(
        set(allowed_bun_versions) - set(SOURCE_AUDITED_BUN_VERSIONS)
    )
    if not allowed_bun_versions or unsupported_bun_versions:
        raise ValueError("Bun allowed versions must be source-audited")
    if private_inbox is not None:
        if sandbox_mode != "bubblewrap":
            raise ValueError("private inbox requires the OpenCode bubblewrap sandbox")
        if (
            private_inbox.own_inbox != workdir / "messages"
            or private_inbox.own_inbox.is_symlink()
            or not private_inbox.own_inbox.is_dir()
        ):
            raise ValueError("OpenCode private inbox is not rooted in its rollout workspace")
        sibling_workdirs: list[Path] = []
        sibling_inboxes: list[Path] = []
        for inbox in private_inbox.recipient_inboxes.values():
            if (
                inbox.name != "messages"
                or not inbox.is_absolute()
                or inbox.is_symlink()
                or not inbox.is_dir()
            ):
                raise ValueError("OpenCode recipient inbox path is invalid")
            sibling_workdir = inbox.parent
            if (
                sibling_workdir == workdir
                or sibling_workdir.is_symlink()
                or not sibling_workdir.is_dir()
            ):
                raise ValueError("OpenCode sibling rollout workspace is invalid")
            sibling_workdirs.append(sibling_workdir)
            sibling_inboxes.append(inbox)
        visible_roots = (
            workdir,
            *sandbox_read_only_roots,
            *sandbox_writable_roots,
            *sibling_workdirs,
        )
        for protected in (
            control_dir,
            worker_state_dir,
            private_inbox.state_path,
            *private_inbox.protected_read_paths,
            *((continuation_context_path,) if continuation_context_path is not None else ()),
            *((auth_file,) if auth_file is not None else ()),
        ):
            resolved_protected = protected.resolve()
            if any(
                resolved_protected == root.resolve()
                or resolved_protected.is_relative_to(root.resolve())
                for root in visible_roots
            ):
                raise ValueError("OpenCode protected private-inbox state overlaps a sandbox root")
        sandbox_read_only_roots = (
            *sandbox_read_only_roots,
            private_inbox.own_inbox,
            *sibling_workdirs,
        )
        sandbox_masked_directories = (
            *sandbox_masked_directories,
            *sibling_inboxes,
        )
    runtime_root = _private_runtime_root(worker_state_dir)
    if sandbox_mode == "bubblewrap":
        resolved_bubblewrap = resolve_bubblewrap_bin(bubblewrap_bin)
        validate_opencode_host_primitives(resolved_bubblewrap)
    else:
        resolved_bubblewrap = None
    if provider_environment is None:
        provider_environment, inferred_mounts = prepare_provider_environment(
            provider_env_names,
            sandbox_mode=sandbox_mode,
        )
        sandbox_read_only_mounts = (*sandbox_read_only_mounts, *inferred_mounts)
    else:
        unexpected_provider_environment = sorted(
            set(provider_environment) - set(provider_env_names)
        )
        if unexpected_provider_environment:
            raise ValueError(
                "OpenCode provider environment contains variables outside the named allowlist: "
                + ", ".join(unexpected_provider_environment)
            )
    custom_secret_names = custom_provider_environment_names(custom_provider)
    missing_custom_allowlist = sorted(set(custom_secret_names) - set(provider_env_names))
    if missing_custom_allowlist:
        raise ValueError(
            "custom OpenCode provider variables are missing from the named allowlist: "
            + ", ".join(missing_custom_allowlist)
        )
    missing_custom_values = [
        name for name in custom_secret_names if name not in provider_environment
    ]
    if missing_custom_values:
        raise ValueError(
            "custom OpenCode provider environment variables are unset: "
            + ", ".join(missing_custom_values)
        )
    control_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(control_dir, 0o700)
    request_path = control_dir / "opencode_runner.request.json"
    stderr_path = control_dir / "opencode_runner.stderr.log"
    events_path = control_dir / "opencode_runner.events.jsonl"
    request: dict[str, Any] = {
        "opencode_bin": str(opencode_bin.resolve()),
        "allowed_versions": list(allowed_versions),
        "allowed_bun_versions": list(allowed_bun_versions),
        "model": model,
        "cwd": str(workdir.resolve()),
        "state_root": str(runtime_root),
        "initial_user_text": initial_user_text,
        "timeout_seconds": timeout_seconds,
        "startup_timeout_seconds": startup_timeout_seconds,
        "provider_env_names": list(provider_env_names),
        "custom_provider": custom_provider,
        "mcp_servers": benchmark_mcp_servers or {},
        "sensitive_mcp_tools": [
            {"server": server, "tool": tool} for server, tool in sensitive_mcp_tools
        ],
        "sandbox": {
            "mode": sandbox_mode,
            "network": sandbox_network,
            "bubblewrap_bin": (
                str(resolved_bubblewrap)
                if sandbox_mode == "bubblewrap"
                else None
            ),
            "read_only_roots": [str(path.expanduser().resolve()) for path in sandbox_read_only_roots],
            "read_only_mounts": [
                {
                    "source": str(source.expanduser().resolve()),
                    "target": str(target),
                }
                for source, target in sandbox_read_only_mounts
            ],
            "writable_roots": [str(path.expanduser().resolve()) for path in sandbox_writable_roots],
            "masked_paths": [
                str(path.expanduser().resolve())
                for path in dict.fromkeys(
                    (
                        *((PROJECT_ROOT / ".env",) if (PROJECT_ROOT / ".env").is_file() else ()),
                        *sandbox_masked_paths,
                    )
                )
            ],
            "masked_directories": [
                str(path.expanduser().resolve())
                for path in dict.fromkeys(sandbox_masked_directories)
            ],
        },
    }
    if test_provider_config is not None:
        request["test_provider_config"] = test_provider_config
    if system_instructions is not None and system_instructions.strip():
        request["system_instructions"] = system_instructions
    if continuation_context_path is not None:
        request["spawn_child_handler_command"] = [
            sys.executable,
            str(PROJECT_ROOT / "main_loop.py"),
            "--child-tool-handler",
            str(continuation_context_path),
        ]
    if private_inbox is not None:
        if continuation_context_path is None:
            raise ValueError("private inbox requires the central dynamic-tool callback")
        request["private_inbox"] = {
            "capability_identity": private_inbox.capability_identity,
            "sender": private_inbox.sender,
            "recipients": list(private_inbox.recipient_inboxes),
        }
    if auth_file is not None:
        request["auth_file"] = str(auth_file.resolve())
    if agent:
        request["agent"] = agent
    if variant:
        request["variant"] = variant
    request_path.write_text(
        json.dumps(_durable_request(request), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.chmod(request_path, 0o600)

    state: dict[str, Any] = {
        "final_text": "",
        "thread_id": "",
        "session_id": "",
        "turn_count": 0,
        "tool_call_count": 0,
        "spawn_child_tool_call_count": 0,
        "send_message_tool_call_count": 0,
        "turn_completed": False,
        "provider_step_count": 0,
        "usage_input_tokens": 0,
        "usage_output_tokens": 0,
        "usage_reasoning_tokens": 0,
        "usage_cache_read_tokens": 0,
        "usage_cache_write_tokens": 0,
        "usage_cost": 0.0,
        "patch_count": 0,
        "patched_files": set(),
        "error_code": "",
        "error_message": "",
        "runtime_version": "",
        "bun_version": "",
        "runtime_process_pid": None,
        "mcp_process_pids": [],
        "malformed_output": False,
    }
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    timed_out = False
    return_code = -1
    try:
        with stderr_path.open("w", encoding="utf-8") as stderr_stream, events_path.open(
            "w", encoding="utf-8"
        ) as events_stream:
            os.chmod(stderr_path, 0o600)
            os.chmod(events_path, 0o600)
            process = subprocess.Popen(
                [str(bun_bin.resolve()), str(worker_script.resolve())],
                cwd=PROJECT_ROOT,
                env=_rollout_environment(
                    bun_bin=bun_bin,
                    opencode_bin=opencode_bin,
                    provider_env_names=provider_env_names,
                    provider_environment=provider_environment,
                    extra_environment=extra_environment,
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_stream,
                text=True,
                encoding="utf-8",
                bufsize=1,
                start_new_session=True,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json.dumps(request))
            process.stdin.close()
            deadline = started_at + timeout_seconds + startup_timeout_seconds + 15

            while True:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    for raw_line in remaining.splitlines():
                        _handle_runner_line(
                            raw_line,
                            events_stream=events_stream,
                            progress_callback=progress_callback,
                            state=state,
                        )
                    break
                if time.monotonic() > deadline:
                    timed_out = True
                    _terminate_process_group(process)
                    remaining = process.stdout.read()
                    for raw_line in remaining.splitlines():
                        _handle_runner_line(
                            raw_line,
                            events_stream=events_stream,
                            progress_callback=progress_callback,
                            state=state,
                        )
                    break
                ready, _, _ = select.select([process.stdout], [], [], 0.5)
                if not ready:
                    continue
                raw_line = process.stdout.readline()
                if raw_line:
                    _handle_runner_line(
                        raw_line,
                        events_stream=events_stream,
                        progress_callback=progress_callback,
                        state=state,
                    )
            return_code = process.wait()
    except BaseException:
        if process is not None:
            _terminate_process_group(process)
        raise
    finally:
        if process is not None and process.stdout is not None:
            process.stdout.close()
        _kill_runtime_process_group(state["runtime_process_pid"])
        for pid in state.get("mcp_process_pids", []):
            _kill_runtime_process_group(pid)
        _cleanup_host_mcp_roots(worker_state_dir)
        if runtime_root.parent.resolve() == worker_state_dir.resolve():
            shutil.rmtree(runtime_root, ignore_errors=True)

    metadata = {
        "thread_id": state["thread_id"] or None,
        "session_id": state["session_id"] or None,
        "runtime_version": state["runtime_version"] or None,
        "bun_version": state["bun_version"] or None,
        "request_path": str(request_path),
        "stderr_path": str(stderr_path),
        "events_path": str(events_path),
        "turn_count": state["turn_count"],
        "tool_call_count": state["tool_call_count"],
        "spawn_child_tool_call_count": state["spawn_child_tool_call_count"],
        "send_message_tool_call_count": state["send_message_tool_call_count"],
        "turn_completed": state["turn_completed"],
        "provider_step_count": state["provider_step_count"],
        "usage_input_tokens": state["usage_input_tokens"],
        "usage_output_tokens": state["usage_output_tokens"],
        "usage_reasoning_tokens": state["usage_reasoning_tokens"],
        "usage_cache_read_tokens": state["usage_cache_read_tokens"],
        "usage_cache_write_tokens": state["usage_cache_write_tokens"],
        "usage_cost": state["usage_cost"],
        "patch_count": state["patch_count"],
        "patched_files": sorted(state["patched_files"]),
        "isolated_state_cleaned": not runtime_root.exists(),
        "mcp_process_pids": list(state["mcp_process_pids"]),
    }
    if timed_out:
        return {
            "final_text": state["final_text"],
            "status": "timeout",
            "stop_reason": "worker_timeout",
            "error_code": "worker_timeout",
            "error_message": f"OpenCode runner exceeded {timeout_seconds} seconds.",
            **metadata,
        }
    if state["error_code"] == "worker_timeout":
        return {
            "final_text": state["final_text"],
            "status": "timeout",
            "stop_reason": "worker_timeout",
            "error_code": "worker_timeout",
            "error_message": state["error_message"],
            **metadata,
        }
    if return_code != 0 or state["malformed_output"]:
        return {
            "final_text": state["final_text"],
            "status": "error",
            "stop_reason": "opencode_runner_exit",
            "error_code": state["error_code"] or return_code,
            "error_message": (
                state["error_message"]
                or f"OpenCode runner exited nonzero ({return_code}); see {stderr_path}"
            ),
            **metadata,
        }
    return {
        "final_text": state["final_text"],
        "status": "completed",
        "stop_reason": "final_message",
        "error_code": None,
        "error_message": None,
        **metadata,
    }


def _handle_runner_line(
    raw_line: str,
    *,
    events_stream: Any,
    progress_callback: Callable[..., None] | None,
    state: dict[str, Any],
) -> dict[str, Any] | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        state["malformed_output"] = True
        state["error_code"] = state["error_code"] or "malformed_runner_output"
        state["error_message"] = (
            state["error_message"] or "OpenCode runner emitted malformed non-JSON output."
        )
        sanitized = {"event": "malformed_runner_output", "line_characters": len(line)}
        events_stream.write(json.dumps(sanitized, sort_keys=True) + "\n")
        events_stream.flush()
        return None
    if not isinstance(event, dict):
        state["malformed_output"] = True
        return None
    event = _durable_event(event)
    events_stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    events_stream.flush()
    name = event.get("event")
    if name == "runtime_verified":
        if event.get("runtime") == "bun":
            state["bun_version"] = str(event.get("version") or "")
        elif event.get("runtime") == "opencode":
            state["runtime_version"] = str(event.get("version") or "")
    elif name == "runtime_process_started":
        pid = event.get("pid")
        state["runtime_process_pid"] = pid if isinstance(pid, int) else None
    elif name == "mcp_process_started":
        pid = event.get("pid")
        if isinstance(pid, int) and pid > 1:
            state.setdefault("mcp_process_pids", []).append(pid)
    elif name == "thread_started":
        state["thread_id"] = str(event.get("thread_id") or "")
        state["session_id"] = str(event.get("session_id") or "")
    elif name == "turn_started":
        state["turn_count"] += 1
    elif name == "tool_begin":
        state["tool_call_count"] += 1
        if event.get("tool") == "spawn_child":
            state["spawn_child_tool_call_count"] += 1
        elif event.get("tool") == "send_message":
            state["send_message_tool_call_count"] += 1
    elif name == "turn_usage":
        state["provider_step_count"] += 1
        for key in (
            "usage_input_tokens",
            "usage_output_tokens",
            "usage_reasoning_tokens",
            "usage_cache_read_tokens",
            "usage_cache_write_tokens",
        ):
            value = event.get(key)
            if isinstance(value, int) and value >= 0:
                state[key] += value
        cost = event.get("usage_cost")
        if isinstance(cost, (int, float)) and cost >= 0:
            state["usage_cost"] += cost
    elif name == "patch":
        state["patch_count"] += 1
        files = event.get("files")
        if isinstance(files, list):
            state["patched_files"].update(
                path for path in files if isinstance(path, str)
            )
    elif name in {"agent_message", "turn_complete"}:
        text = str(event.get("final_text") or event.get("text") or "")
        if text:
            state["final_text"] = text
        if name == "turn_complete":
            state["turn_completed"] = True
    elif name == "error":
        state["error_code"] = str(event.get("error_code") or "")
        state["error_message"] = str(event.get("error_message") or "")

    if progress_callback is not None:
        if name == "thread_started":
            progress_callback(
                "opencode_session_started",
                thread_id=event.get("thread_id"),
                session_id=event.get("session_id"),
                model=event.get("model"),
            )
        elif name == "turn_started":
            progress_callback("worker_turn_started", backend="opencode")
        elif name == "tool_begin" and event.get("tool") != "send_message":
            progress_callback(
                "worker_tool_started",
                tool=event.get("tool"),
                call_id=event.get("call_id"),
                command=event.get("command"),
            )
        elif name == "tool_end" and event.get("tool") != "send_message":
            progress_callback(
                "worker_tool_completed",
                tool=event.get("tool"),
                call_id=event.get("call_id"),
                status=event.get("status"),
                duration_ms=event.get("duration_ms"),
            )
        elif name == "turn_usage":
            progress_callback(
                "worker_turn_usage",
                reason=event.get("reason"),
                usage_input_tokens=event.get("usage_input_tokens"),
                usage_output_tokens=event.get("usage_output_tokens"),
                usage_reasoning_tokens=event.get("usage_reasoning_tokens"),
                usage_cache_read_tokens=event.get("usage_cache_read_tokens"),
                usage_cache_write_tokens=event.get("usage_cache_write_tokens"),
                usage_cost=event.get("usage_cost"),
            )
        elif name == "patch":
            progress_callback(
                "worker_patch",
                files=event.get("files"),
                file_count=event.get("file_count"),
            )
        elif name == "warning":
            progress_callback(
                "worker_warning",
                warning_code=event.get("warning_code"),
                attempt=event.get("attempt"),
                next_retry_at_ms=event.get("next_retry_at_ms"),
            )
        elif name == "turn_complete":
            progress_callback("worker_turn_completed", response_status="completed")
        elif name == "error":
            progress_callback(
                "worker_error",
                error_code=event.get("error_code"),
                error_message=event.get("error_message"),
            )
    return event
