from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            with (
                patch.dict(os.environ, {"CARGO_TARGET_DIR": str(target_dir)}),
                patch.object(
                    codex_runner,
                    "_official_codex_v8_cargo_env",
                    return_value=v8_env,
                ),
                patch.object(codex_runner.subprocess, "run") as run,
            ):
                result = codex_runner.ensure_codex_runner_built(release=True)

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


if __name__ == "__main__":
    unittest.main()
