from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from main_loop import (
    _validate_opencode_containment,
    _create_benchmark_driver,
    _format_runtime_markdown,
    _runtime_benchmark,
    _run_main,
    _spawn_child_continuation,
    _worker_backend_resume_compatible,
    WorkerResult,
    parse_args,
)
from utils.open_ended_benchmark import (
    OpenEndedBenchmarkDriver,
    OpenEndedConfig,
    resolve_open_ended_task,
)


class OpenEndedBenchmarkTests(unittest.TestCase):
    def test_cli_accepts_open_ended_task_file(self) -> None:
        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                "task.md",
            ],
        ):
            args = parse_args()
        self.assertEqual(args.benchmark, "open-ended")
        self.assertEqual(args.task_file, "task.md")

    def test_opencode_containment_modes_fail_closed_for_benchmarks(self) -> None:
        _validate_opencode_containment("open-ended", "unsafe-none", "allow")
        _validate_opencode_containment("supergpqa", "bubblewrap", "allow")
        with self.assertRaisesRegex(RuntimeError, "require.*bubblewrap"):
            _validate_opencode_containment("supergpqa", "unsafe-none", "allow")
        with self.assertRaisesRegex(RuntimeError, "fail-closed"):
            _validate_opencode_containment("open-ended", "bubblewrap", "none")

    def test_cli_accepts_opencode_backend_and_protocol_defaults(self) -> None:
        with patch(
            "sys.argv",
            ["main_loop.py", "--worker-backend", "opencode"],
        ):
            args = parse_args()
        self.assertEqual(args.worker_backend, "opencode")
        self.assertEqual(args.opencode_base_instructions_mode, "read-readme")
        self.assertEqual(args.opencode_allowed_versions, "1.18.19")
        self.assertEqual(args.opencode_allowed_bun_versions, "1.3.14")
        self.assertEqual(args.opencode_sandbox_mode, "bubblewrap")
        self.assertEqual(args.opencode_network_mode, "allow")
        self.assertEqual(args.opencode_provider_env, [])
        self.assertIsNone(args.opencode_worker_script)
        self.assertIsNone(args.opencode_bun_bin)

        with patch(
            "sys.argv",
            [
                "main_loop.py",
                "--worker-backend",
                "opencode",
                "--opencode-runner-bin",
                "/tmp/legacy-worker.ts",
            ],
        ):
            compatible = parse_args()
        self.assertEqual(compatible.opencode_worker_script, "/tmp/legacy-worker.ts")

    def test_opencode_resume_requires_matching_backend_configuration(self) -> None:
        args = Namespace(
            worker_backend="opencode",
            opencode_base_instructions_mode="read-readme",
            opencode_agent="build",
            opencode_variant=None,
            opencode_server_startup_timeout_seconds=15,
            worker_timeout_seconds=3600,
            opencode_sandbox_mode="bubblewrap",
            opencode_network_mode="allow",
            _opencode_runtime_version="1.18.19",
            _opencode_bin_sha256="opencode-sha",
            _opencode_bun_version="1.3.14",
            _opencode_bun_sha256="bun-sha",
            _opencode_worker_sha256="worker-sha",
            _opencode_python_sha256="python-sha",
            _opencode_auth_sha256=None,
            _opencode_provider_env_names=("OPENAI_API_KEY",),
            _opencode_provider_env_sha256="provider-env-sha",
            _opencode_allowed_bun_versions=("1.3.14",),
            _opencode_bubblewrap_bin="/usr/bin/bwrap",
            _opencode_bubblewrap_version="bubblewrap 0.11.0",
            _opencode_bubblewrap_sha256="bwrap-sha",
            _opencode_system_instructions_sha256="system-sha",
            _opencode_configured_initial_prompt_sha256="prompt-sha",
        )
        record = {
            "worker_backend": "opencode",
            "opencode_base_instructions_mode": "read-readme",
            "opencode_agent": "build",
            "opencode_variant": None,
            "opencode_runtime_version": "1.18.19",
            "opencode_bin_sha256": "opencode-sha",
            "opencode_bun_version": "1.3.14",
            "opencode_bun_sha256": "bun-sha",
            "opencode_worker_sha256": "worker-sha",
            "opencode_python_sha256": "python-sha",
            "opencode_auth_sha256": None,
            "opencode_provider_env_sha256": "provider-env-sha",
            "opencode_allowed_bun_versions": ["1.3.14"],
            "opencode_server_startup_timeout_seconds": 15,
            "opencode_worker_timeout_seconds": 3600,
            "opencode_sandbox_mode": "bubblewrap",
            "opencode_network_mode": "allow",
            "opencode_bubblewrap_bin": "/usr/bin/bwrap",
            "opencode_bubblewrap_version": "bubblewrap 0.11.0",
            "opencode_bubblewrap_sha256": "bwrap-sha",
            "opencode_system_instructions_sha256": "system-sha",
            "opencode_configured_initial_prompt_sha256": "prompt-sha",
            "opencode_effective_initial_prompt_sha256": "prompt-sha",
            "bootstrap_seed_used": True,
            "opencode_provider_env_names": ["OPENAI_API_KEY"],
        }
        self.assertTrue(_worker_backend_resume_compatible(record, args))
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_variant": "high"}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_worker_sha256": "changed"}, args
            )
        )
        for field in (
            "opencode_python_sha256",
            "opencode_bubblewrap_bin",
            "opencode_bubblewrap_version",
            "opencode_bubblewrap_sha256",
            "opencode_system_instructions_sha256",
            "opencode_configured_initial_prompt_sha256",
            "opencode_worker_timeout_seconds",
        ):
            with self.subTest(field=field):
                self.assertFalse(
                    _worker_backend_resume_compatible(
                        {**record, field: "changed"}, args
                    )
                )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {
                    **record,
                    "opencode_effective_initial_prompt_sha256": "changed",
                },
                args,
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_server_startup_timeout_seconds": 99}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_provider_env_sha256": "changed"}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_allowed_bun_versions": ["1.3.13"]}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "worker_backend": "codex"}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_allowed_versions": ["9.9.9"]}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_worker_script": "/tmp/other-worker.ts"}, args
            )
        )

    def test_actual_opencode_orchestration_uses_custom_bootstrap_prompt(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=documents) as temp:
            root = Path(temp)
            runtime = root / "runtime"
            task = root / "task.md"
            task.write_text("# Offline orchestration task\n")
            fake_opencode = root / "opencode"
            shutil.copyfile(
                Path(__file__).parent / "fixtures/fake_opencode.py",
                fake_opencode,
            )
            fake_opencode.chmod(0o755)
            argv = [
                "main_loop.py",
                "--benchmark",
                "open-ended",
                "--task-file",
                str(task),
                "--runtime-root",
                str(runtime),
                "--worker-backend",
                "opencode",
                "--model",
                "fixture/model",
                "--num-rollouts",
                "1",
                "--step",
                "--opencode-bin",
                str(fake_opencode),
                "--opencode-initial-prompt",
                "CUSTOM OPENCODE BOOTSTRAP",
            ]
            calls: list[dict[str, object]] = []

            def worker(**kwargs: object) -> WorkerResult:
                calls.append(kwargs)
                if len(calls) == 2:
                    workdir = Path(str(kwargs["workdir"]))
                    seed = workdir / "child-seed"
                    seed.mkdir()
                    (seed / "README.md").write_text("# Inherited child\n")
                    context = json.loads(
                        Path(str(kwargs["continuation_context_path"])).read_text()
                    )
                    spawned = _spawn_child_continuation(
                        context=context,
                        args={
                            "prompt": "INHERITED CHILD PROMPT",
                            "workspace_dir": "child-seed",
                        },
                    )
                    self.assertTrue(spawned["child_spawned"])
                return WorkerResult("offline", "completed", "final_message")

            for _ in range(3):
                with patch("sys.argv", argv), patch(
                    "main_loop.run_opencode_worker", side_effect=worker
                ):
                    _run_main([])
            self.assertEqual(len(calls), 3)
            self.assertEqual(
                [call["initial_user_text"] for call in calls],
                [
                    "CUSTOM OPENCODE BOOTSTRAP",
                    "CUSTOM OPENCODE BOOTSTRAP",
                    "INHERITED CHILD PROMPT",
                ],
            )
            self.assertNotIn(
                str(runtime / "logs/rollout_control"),
                [str(path) for path in calls[0]["sandbox_writable_roots"]],
            )
            handler_context = Path(str(calls[0]["continuation_context_path"]))
            mounted_sources = {
                str(source)
                for source, _target in calls[0]["sandbox_read_only_mounts"]
            }
            self.assertNotIn(str(handler_context), mounted_sources)
            records = [
                json.loads(line)
                for line in (runtime / "logs/runs.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(records), 3)
            self.assertEqual(
                records[0]["opencode_effective_initial_prompt_sha256"],
                records[1]["opencode_effective_initial_prompt_sha256"],
            )
            self.assertNotEqual(
                records[1]["opencode_effective_initial_prompt_sha256"],
                records[2]["opencode_effective_initial_prompt_sha256"],
            )
            self.assertTrue(records[0]["opencode_system_instructions_sha256"])
            self.assertTrue(records[0]["opencode_python_sha256"])
            self.assertTrue(records[0]["opencode_bubblewrap_sha256"])

    def test_exact_task_materialization_has_no_pool_tools_or_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "human-task.md"
            task_bytes = "# Human task\r\n\r\nDo the open-ended work. 🛠️\r\n".encode()
            source.write_bytes(task_bytes)
            state_dir = root / "runtime/logs/open_ended_task"
            task = resolve_open_ended_task(state_dir, source)
            self.assertFalse(state_dir.exists())
            driver = OpenEndedBenchmarkDriver(
                OpenEndedConfig(task=task, state_dir=state_dir)
            )

            shared = root / "shared"
            batch = driver.prepare_batch(4, shared)
            self.assertEqual(batch.benchmark, "open-ended")
            self.assertEqual(batch.item_count, 0)
            self.assertFalse(batch.metadata["has_problem_pool"])
            self.assertEqual(batch.metadata["evaluation"], "unconfigured")
            self.assertEqual((shared / "BENCHMARK.md").read_bytes(), task_bytes)
            self.assertEqual((state_dir / "task.md").read_bytes(), task_bytes)
            self.assertFalse((shared / "problem_pool.json").exists())
            self.assertFalse((shared / "problem_pool.md").exists())

            metadata = json.loads((state_dir / "task.json").read_text())
            self.assertEqual(metadata["sha256"], task.sha256)
            self.assertEqual(metadata["evaluation"], "unconfigured")
            rollout = driver.prepare_rollout(
                batch,
                backend="codex",
                context={"instance_uuid": "fixture"},
            )
            self.assertEqual(rollout.mcp_servers, {})
            self.assertEqual(rollout.sensitive_mcp_tools, ())
            self.assertEqual(rollout.model_metadata["tools"], [])
            self.assertEqual(rollout.context["evaluation"], "unconfigured")
            opencode_rollout = driver.prepare_rollout(
                batch,
                backend="opencode",
                context={"instance_uuid": "fixture-opencode"},
            )
            self.assertEqual(opencode_rollout.mcp_servers, {})
            self.assertIsNone(
                driver.collect_outcome(
                    batch,
                    instance_uuid="fixture",
                    context=rollout.context,
                )
            )
            self.assertEqual(driver.finalize_batch(batch, []), {})
            driver.close()

    def test_runtime_copy_supports_resume_and_rejects_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "task.md"
            source.write_text("# Stable task\n", encoding="utf-8")
            state_dir = root / "runtime/logs/open_ended_task"
            initial = resolve_open_ended_task(state_dir, source)
            driver = OpenEndedBenchmarkDriver(
                OpenEndedConfig(task=initial, state_dir=state_dir)
            )
            driver.prepare_batch(0, root / "shared")
            driver.close()

            source.unlink()
            resumed = resolve_open_ended_task(state_dir, None)
            self.assertEqual(resumed.content, b"# Stable task\n")
            self.assertEqual(resumed.sha256, initial.sha256)

            replacement = root / "replacement.md"
            replacement.write_text("# Different task\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                resolve_open_ended_task(state_dir, replacement)

    def test_new_runtime_requires_a_nonblank_utf8_task(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "required"):
                resolve_open_ended_task(root / "state", None)

            blank = root / "blank.md"
            blank.write_text("  \n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must not be blank"):
                resolve_open_ended_task(root / "state", blank)

            invalid = root / "invalid.md"
            invalid.write_bytes(b"\xff")
            with self.assertRaisesRegex(ValueError, "UTF-8"):
                resolve_open_ended_task(root / "state", invalid)

    def test_main_loop_driver_and_runtime_projection_are_explicitly_unscored(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "task.md"
            source.write_text("# Task\n", encoding="utf-8")
            task = resolve_open_ended_task(root / "state", source)
            driver = _create_benchmark_driver(
                Namespace(benchmark="open-ended"),
                arc_benchmark_state_path=root / "arc.json",
                problem_queue_path=root / "queue.json",
                task_store_dir=root / "tasks",
                dataset_cache_dir=root / "cache",
                existing_records=[],
                open_ended_task=task,
                open_ended_state_dir=root / "state",
            )
            self.assertIsInstance(driver, OpenEndedBenchmarkDriver)
            driver.close()

            runtime_text = _format_runtime_markdown(
                instance_uuid="fixture",
                has_problem_pool=False,
            )
            self.assertIn("evaluation: unconfigured", runtime_text)
            self.assertIn("no evaluator, score, reward, solved status, or ranking", runtime_text)
            self.assertNotIn("problem_pool", runtime_text)
            self.assertNotIn("Benchmark Pool Semantics", runtime_text)
            bootstrap = (
                Path(__file__).resolve().parents[1] / "seeds/bootstrap/README.md"
            ).read_text(encoding="utf-8")
            bootstrap_words = " ".join(bootstrap.split())
            self.assertIn("current human-authored task", bootstrap)
            self.assertIn("explicitly unevaluated", bootstrap_words)
            self.assertIn("an unevaluated profile can provide none", bootstrap)

            identity_root = root / "identity"
            identity_root.mkdir()
            (identity_root / "runtime_benchmark.json").write_text(
                json.dumps(
                    {
                        "format": "metalanguage-runtime-benchmark",
                        "version": 1,
                        "benchmark": "open-ended",
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(_runtime_benchmark(identity_root), "open-ended")


if __name__ == "__main__":
    unittest.main()
