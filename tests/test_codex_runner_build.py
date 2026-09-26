from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import codex_bundle
from utils import codex_runner


class CodexRunnerBuildTests(unittest.TestCase):
    def test_release_build_produces_locked_adjacent_runner_and_host(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target_dir = Path(temporary) / "target"
            release_dir = target_dir / "release"
            release_dir.mkdir(parents=True)
            runner = release_dir / "metalanguage-codex-runner"
            host = release_dir / codex_runner.CODE_MODE_HOST_FILENAME
            for binary in (runner, host):
                binary.write_bytes(b"test")
                binary.chmod(0o755)

            v8_env = {
                "RUSTY_V8_ARCHIVE": "/verified/archive",
                "RUSTY_V8_SRC_BINDING_PATH": "/verified/binding",
            }

            def emit_build_output(command: list[str], **kwargs: object) -> None:
                binary = host if "--package" in command else runner
                self.assertFalse(binary.exists())
                binary.write_bytes(b"new build")
                binary.chmod(0o755)

            with (
                patch.dict(os.environ, {"CARGO_TARGET_DIR": str(target_dir)}),
                patch.object(
                    codex_runner,
                    "_official_codex_v8_cargo_env",
                    return_value=v8_env,
                ),
                patch.object(codex_runner.subprocess, "run", side_effect=emit_build_output) as run,
                patch.object(
                    codex_runner, "_codex_bundle_source_fingerprint", return_value={"source": "a"}
                ),
            ):
                result = codex_runner.ensure_codex_runner_built(release=True)
                codex_bundle.validate_manifest(runner, host, {"source": "a"}, release=True)

            self.assertEqual(result, runner)
            self.assertEqual(run.call_count, 2)
            runner_call, host_call = run.call_args_list
            self.assertEqual(
                runner_call.args[0],
                [
                    "cargo",
                    "build",
                    "--locked",
                    "--manifest-path",
                    str(codex_runner.RUNNER_MANIFEST),
                    "--release",
                ],
            )
            self.assertEqual(
                host_call.args[0],
                [
                    "cargo",
                    "build",
                    "--locked",
                    "--manifest-path",
                    str(codex_runner.CODEX_RS_MANIFEST),
                    "--package",
                    "codex-code-mode-host",
                    "--bin",
                    "codex-code-mode-host",
                    "--release",
                ],
            )
            self.assertEqual(runner_call.kwargs["env"]["CARGO_TARGET_DIR"], str(target_dir))
            self.assertEqual(host_call.kwargs["env"]["CARGO_TARGET_DIR"], str(target_dir))
            self.assertEqual(
                {key: host_call.kwargs["env"][key] for key in v8_env},
                v8_env,
            )

    def test_failed_host_build_invalidates_previous_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = Path(temporary) / "debug" / "metalanguage-codex-runner"
            runner.parent.mkdir()
            manifest = codex_bundle.manifest_path(runner)
            manifest.write_text("old manifest", encoding="utf-8")
            with (
                patch.dict(os.environ, {"CARGO_TARGET_DIR": temporary}),
                patch.object(
                    codex_runner, "_codex_bundle_source_fingerprint", return_value={"source": "a"}
                ),
                patch.object(codex_runner, "_official_codex_v8_cargo_env", return_value={}),
                patch.object(
                    codex_runner.subprocess, "run",
                    side_effect=[None, subprocess.CalledProcessError(1, ["cargo", "build"])],
                ),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    codex_runner.ensure_codex_runner_built()
            self.assertFalse(manifest.exists())

    def test_success_without_expected_build_outputs_cannot_certify_old_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"CARGO_TARGET_DIR": temporary}):
                runner = codex_runner.runner_binary_path()
                runner.parent.mkdir()
                host = runner.with_name(codex_runner.CODE_MODE_HOST_FILENAME)
                for binary in (runner, host):
                    binary.write_bytes(b"old binary")
                    binary.chmod(0o755)
                with (
                    patch.object(codex_runner, "_codex_bundle_source_fingerprint", return_value={}),
                    patch.object(codex_runner, "_official_codex_v8_cargo_env", return_value={}),
                    patch.object(codex_runner.subprocess, "run"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "did not produce an executable"):
                        codex_runner.ensure_codex_runner_built()
                self.assertFalse(codex_bundle.manifest_path(runner).exists())

    def test_source_change_during_build_does_not_publish_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.dict(os.environ, {"CARGO_TARGET_DIR": temporary}),
                patch.object(
                    codex_runner, "_codex_bundle_source_fingerprint",
                    side_effect=[{"source": "before"}, {"source": "after"}],
                ),
                patch.object(codex_runner, "_build_codex_runner_and_host"),
            ):
                with self.assertRaisesRegex(RuntimeError, "sources changed during the build"):
                    codex_runner.ensure_codex_runner_built()
                manifest = codex_bundle.manifest_path(codex_runner.runner_binary_path())
                self.assertFalse(manifest.exists())

    def test_concurrent_build_cannot_invalidate_active_builder_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"CARGO_TARGET_DIR": temporary}):
                runner = codex_runner.runner_binary_path()
                runner.parent.mkdir()
                manifest = codex_bundle.manifest_path(runner)
                manifest.write_text("existing", encoding="utf-8")
                with (
                    codex_runner.FileLock(str(manifest) + ".lock"),
                    patch.object(codex_runner, "_build_codex_runner_and_host") as build,
                ):
                    with self.assertRaisesRegex(RuntimeError, "build is in progress"):
                        codex_runner.ensure_codex_runner_built()
                    build.assert_not_called()
                self.assertEqual(manifest.read_text(encoding="utf-8"), "existing")

    def test_explicit_legacy_runner_cannot_bypass_manifest_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runner = Path(temporary) / "custom-runner"
            runner.write_bytes(b"old runner")
            with patch.object(codex_runner, "_codex_bundle_source_fingerprint", return_value={}):
                with self.assertRaisesRegex(RuntimeError, "--codex-build-runner"):
                    codex_runner.resolve_codex_runner_bin(runner)


if __name__ == "__main__":
    unittest.main()
