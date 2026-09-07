from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.codex_runner import run_codex_rollout
from utils.opencode_runner import run_opencode_rollout


class ContextExhaustionAdapterTests(unittest.TestCase):
    @staticmethod
    def _executable(path: Path, source: str) -> Path:
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_codex_context_boundary_is_a_normal_persisted_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner = self._executable(
                root / "fake-codex-runner",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.load(sys.stdin)\n"
                "print(json.dumps({'event':'thread_started','thread_id':'thr','session_id':'ses'}), flush=True)\n"
                "print(json.dumps({'event':'turn_started','turn_id':'turn'}), flush=True)\n"
                "print(json.dumps({'event':'agent_message','text':'useful partial answer'}), flush=True)\n"
                "print(json.dumps({'event':'context_exhausted','stop_reason':'context_exhausted','boundary_source':'managed_pre_compact_hook','final_text':'useful partial answer','turn_id':'turn','turn_abort_reason':'Interrupted','automatic_compaction_limit_cap_fraction':0.9}), flush=True)\n"
                "print(json.dumps({'event':'rollout_persisted','rollout_path':'/archive/rollout.jsonl'}), flush=True)\n",
            )
            directories = {
                name: root / name
                for name in ("work", "control", "state", "codex", "seed", "archives", "shared")
            }
            for path in directories.values():
                path.mkdir()

            result = run_codex_rollout(
                runner_bin=runner,
                model="fixture-model",
                workdir=directories["work"],
                control_dir=directories["control"],
                worker_state_dir=directories["state"],
                codex_home=directories["codex"],
                seed_output_dir=directories["seed"],
                shared_archives_root=directories["archives"],
                shared_workspace_dir=directories["shared"],
                rollout_username="fixture",
                timeout_seconds=10,
                persist_session=True,
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["stop_reason"], "context_exhausted")
            self.assertEqual(result["final_text"], "useful partial answer")
            self.assertEqual(result["rollout_path"], "/archive/rollout.jsonl")
            self.assertEqual(result["context_boundary_source"], "managed_pre_compact_hook")
            self.assertEqual(result["automatic_compaction_limit_cap_fraction"], 0.9)
            self.assertTrue(result["turn_completed"])
            self.assertIsNone(result["error_code"])

    def test_opencode_context_boundary_is_normal_and_diagnostics_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bun = self._executable(
                root / "fake-bun",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.load(sys.stdin)\n"
                "print(json.dumps({'event':'runtime_verified','runtime':'bun','version':'1.3.14'}), flush=True)\n"
                "print(json.dumps({'event':'runtime_verified','runtime':'opencode','version':'1.18.29'}), flush=True)\n"
                "print(json.dumps({'event':'thread_started','thread_id':'thr','session_id':'ses'}), flush=True)\n"
                "print(json.dumps({'event':'turn_started'}), flush=True)\n"
                "print(json.dumps({'event':'context_exhausted','stop_reason':'context_exhausted','boundary_source':'provider_context_window_exceeded','final_text':'useful partial answer','context_provider_error_code':'ContextOverflowError','context_provider_error_message':'overflow sk-PRIVATE-KEY','context_provider_error_http_status':413,'context_provider_error_retryable':False}), flush=True)\n",
            )
            worker_script = root / "worker.ts"
            worker_script.write_text("", encoding="utf-8")
            opencode = self._executable(root / "opencode", "#!/bin/sh\nexit 0\n")
            work = root / "work"
            control = root / "control"
            state = root / "state"
            for path in (work, state):
                path.mkdir()

            result = run_opencode_rollout(
                worker_script=worker_script,
                bun_bin=bun,
                opencode_bin=opencode,
                model="fixture/model",
                workdir=work,
                control_dir=control,
                worker_state_dir=state,
                timeout_seconds=10,
                initial_user_text="test",
                provider_environment={},
                sandbox_mode="none",
            )

            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["stop_reason"], "context_exhausted")
            self.assertEqual(result["final_text"], "useful partial answer")
            self.assertEqual(result["context_provider_error_code"], "ContextOverflowError")
            self.assertEqual(
                result["context_provider_error_message"], "overflow [REDACTED]"
            )
            self.assertEqual(result["context_provider_error_http_status"], 413)
            self.assertFalse(result["context_provider_error_retryable"])
            self.assertTrue(result["turn_completed"])
            self.assertIsNone(result["error_code"])

    def test_mixed_backend_wrappers_preserve_the_same_stop_contract(self) -> None:
        from main_loop import run_codex_worker, run_opencode_worker

        codex_result = {
            "final_text": "codex partial",
            "status": "completed",
            "stop_reason": "context_exhausted",
            "error_code": None,
            "error_message": None,
            "context_boundary_source": "managed_pre_compact_hook",
            "automatic_compaction_limit_cap_fraction": 0.9,
        }
        opencode_result = {
            "final_text": "opencode partial",
            "status": "completed",
            "stop_reason": "context_exhausted",
            "error_code": None,
            "error_message": None,
            "error_http_status": None,
            "error_retryable": None,
            "context_boundary_source": "provider_context_window_exceeded",
            "context_provider_error_code": "ContextOverflowError",
        }
        placeholder = Path("/fixture")
        with patch("main_loop.run_codex_rollout", return_value=codex_result):
            codex = run_codex_worker(
                runner_bin=placeholder,
                model="gpt-5.6-sol",
                workdir=placeholder,
                control_dir=placeholder,
                worker_state_dir=placeholder,
                codex_home=placeholder,
                seed_output_dir=placeholder,
                shared_archives_root=placeholder,
                shared_workspace_dir=placeholder,
                rollout_username="codex",
                timeout_seconds=10,
                sandbox_mode="workspace-write",
                initial_user_text="test",
            )
        with patch("main_loop.run_opencode_rollout", return_value=opencode_result):
            opencode = run_opencode_worker(
                worker_script=placeholder,
                bun_bin=placeholder,
                opencode_bin=placeholder,
                model="anthropic/claude-sonnet-4-5",
                workdir=placeholder,
                control_dir=placeholder,
                worker_state_dir=placeholder,
                timeout_seconds=10,
                initial_user_text="test",
            )

        for result in (codex, opencode):
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.stop_reason, "context_exhausted")
            self.assertIsNone(result.error_code)
        self.assertEqual(
            codex.metadata["context_boundary_source"], "managed_pre_compact_hook"
        )
        self.assertEqual(
            opencode.metadata["context_provider_error_code"], "ContextOverflowError"
        )


if __name__ == "__main__":
    unittest.main()
