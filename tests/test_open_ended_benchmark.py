from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import threading
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from main_loop import (
    CANONICAL_BOOTSTRAP_README_SHA256,
    DEFAULT_BOOTSTRAP_INITIAL_PROMPT,
    ROLLOUT_SYSTEM_INSTRUCTIONS_FINGERPRINT,
    ROLLOUT_SYSTEM_INSTRUCTIONS_MODE,
    ROLLOUT_SYSTEM_INSTRUCTIONS_VERSION,
    _validate_opencode_containment,
    _create_benchmark_driver,
    _format_runtime_markdown,
    _rollout_prompt_resume_compatible,
    _runtime_benchmark,
    _run_main,
    _spawn_child_continuation,
    _worker_backend_resume_compatible,
    WorkerResult,
    canonical_rollout_system_instructions,
    parse_args,
)
from utils.open_ended_benchmark import (
    OpenEndedBenchmarkDriver,
    OpenEndedConfig,
    resolve_open_ended_task,
)
from utils.opencode_runner import custom_provider_configuration, custom_provider_fingerprint


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
        self.assertEqual(
            args.opencode_base_instructions_mode,
            ROLLOUT_SYSTEM_INSTRUCTIONS_MODE,
        )
        self.assertEqual(args.opencode_initial_prompt, DEFAULT_BOOTSTRAP_INITIAL_PROMPT)
        self.assertEqual(
            args.codex_base_instructions_mode,
            ROLLOUT_SYSTEM_INSTRUCTIONS_MODE,
        )
        self.assertEqual(args.codex_initial_prompt, DEFAULT_BOOTSTRAP_INITIAL_PROMPT)
        self.assertEqual(args.opencode_allowed_versions, "1.18.21")
        self.assertEqual(args.opencode_allowed_bun_versions, "1.3.14")
        self.assertEqual(args.opencode_sandbox_mode, "bubblewrap")
        self.assertEqual(args.opencode_network_mode, "allow")
        self.assertEqual(args.opencode_provider_env, [])
        self.assertIsNone(args.opencode_custom_provider_id)
        self.assertIsNone(args.opencode_custom_provider_npm)
        self.assertEqual(args.opencode_custom_provider_header_env, [])
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

    def test_actual_main_loop_forwards_custom_provider_without_persisting_secrets(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=documents) as temp:
            root = Path(temp)
            runtime = root / "runtime"
            task = root / "task.md"
            task.write_text("# Custom provider dispatch\n")
            fake_opencode = root / "opencode"
            shutil.copyfile(Path(__file__).parent / "fixtures/fake_opencode.py", fake_opencode)
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
                "fixture/model-one",
                "--num-rollouts",
                "8",
                "--step",
                "--opencode-bin",
                str(fake_opencode),
                "--opencode-custom-provider-id",
                "fixture",
                "--opencode-custom-provider-name",
                "Fixture Provider",
                "--opencode-custom-provider-npm",
                "@ai-sdk/openai-compatible",
                "--opencode-custom-provider-base-url",
                "http://127.0.0.1:18080/v1",
                "--opencode-custom-provider-api-key-env",
                "CUSTOM_API_KEY",
                "--opencode-custom-provider-header-env",
                "X-Custom=CUSTOM_HEADER",
                "--opencode-custom-provider-context-limit",
                "8192",
                "--opencode-custom-provider-output-limit",
                "1024",
            ]
            calls: list[dict[str, object]] = []

            def worker(**kwargs: object) -> WorkerResult:
                calls.append(kwargs)
                return WorkerResult("offline", "completed", "final_message")

            with patch.dict(
                "os.environ",
                {
                    "CUSTOM_API_KEY": "sk-DISPATCH-PRIVATE",
                    "CUSTOM_HEADER": "header-DISPATCH-PRIVATE",
                },
            ), patch("sys.argv", argv), patch(
                "main_loop.run_opencode_worker", side_effect=worker
            ):
                _run_main([])
            self.assertEqual(len(calls), 8)
            configuration = calls[0]["custom_provider"]
            self.assertEqual(configuration["provider_id"], "fixture")
            self.assertEqual(configuration["model_id"], "model-one")
            self.assertEqual(configuration["limits"], {"context": 8192, "output": 1024})
            self.assertEqual(
                calls[0]["provider_env_names"],
                ("CUSTOM_API_KEY", "CUSTOM_HEADER"),
            )
            run_log = (runtime / "logs/runs.jsonl").read_text()
            self.assertNotIn("DISPATCH-PRIVATE", run_log)
            records = [json.loads(line) for line in run_log.splitlines()]
            self.assertEqual(len(records), 8)
            record = records[0]
            self.assertEqual(record["opencode_custom_provider"], configuration)
            self.assertTrue(record["opencode_custom_provider_sha256"])
            self.assertTrue(record["peer_communication_enabled"])
            self.assertFalse(record["rollout_independence"])
            self.assertEqual(len(record["peer_name_mapping"]), 8)
            self.assertEqual(
                len({entry["name"] for entry in record["peer_name_mapping"]}),
                8,
            )
            self.assertEqual(len(record["peer_name_roster"]), 8)
            peer_log = (
                runtime
                / "logs/peer_communication/task_000000"
                / f"batch_{record['peer_communication_batch_id']}"
            )
            self.assertTrue((peer_log / "manifest.json").is_file())
            self.assertEqual(list((peer_log / "messages").glob("*.json")), [])

    def test_codex_and_openrouter_separate_system_and_inherited_user_prompts(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        canonical_instructions = canonical_rollout_system_instructions()
        for backend in ("codex", "openrouter"):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory(dir=documents) as temp:
                root = Path(temp)
                task = root / "task.md"
                task.write_text(f"# {backend} regression\n")
                argv = [
                    "main_loop.py",
                    "--benchmark",
                    "open-ended",
                    "--task-file",
                    str(task),
                    "--runtime-root",
                    str(root / "runtime"),
                    "--worker-backend",
                    backend,
                    "--model",
                    "fixture/model",
                    "--num-rollouts",
                    "8",
                    "--step",
                ]
                if backend == "codex":
                    argv.extend(["--codex-runner-bin", "/bin/true", "--codex-home", str(root / "codex-home")])
                codex_calls: list[dict[str, object]] = []
                openrouter_calls: list[dict[str, object]] = []
                spawn_lock = threading.Lock()
                spawned = False

                def maybe_spawn(kwargs: dict[str, object]) -> None:
                    nonlocal spawned
                    with spawn_lock:
                        if spawned:
                            return
                        spawned = True
                    workdir = Path(str(kwargs["workdir"]))
                    seed = workdir / "child-seed"
                    seed.mkdir()
                    (seed / "README.md").write_text("# Distinct inherited handoff\n")
                    if backend == "codex":
                        context = json.loads(
                            Path(str(kwargs["continuation_context_path"])).read_text()
                        )
                    else:
                        context = dict(kwargs["continuation_context"])
                    child = _spawn_child_continuation(
                        context=context,
                        args={
                            "prompt": "INHERITED USER PROMPT",
                            "workspace_dir": "child-seed",
                        },
                    )
                    self.assertTrue(child["child_spawned"])

                def codex_worker(**kwargs: object) -> WorkerResult:
                    codex_calls.append(kwargs)
                    maybe_spawn(kwargs)
                    return WorkerResult("offline", "completed", "final_message")

                def openrouter_worker(**kwargs: object) -> WorkerResult:
                    openrouter_calls.append(kwargs)
                    maybe_spawn(kwargs)
                    return WorkerResult("offline", "completed", "final_message")

                for _ in range(2):
                    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-only-key"}), patch(
                        "sys.argv", argv
                    ), patch("main_loop.run_codex_worker", side_effect=codex_worker), patch(
                        "main_loop.run_worker", side_effect=openrouter_worker
                    ), patch(
                        "main_loop.run_opencode_worker",
                        side_effect=AssertionError("OpenCode dispatch must remain inactive"),
                    ):
                        _run_main([])
                calls = codex_calls if backend == "codex" else openrouter_calls
                self.assertEqual(len(calls), 16)
                self.assertEqual(
                    [call["initial_user_text"] for call in calls].count(
                        "INHERITED USER PROMPT"
                    ),
                    1,
                )
                self.assertEqual(
                    [call["initial_user_text"] for call in calls].count(
                        DEFAULT_BOOTSTRAP_INITIAL_PROMPT
                    ),
                    15,
                )
                instruction_key = (
                    "base_instructions" if backend == "codex" else "instructions"
                )
                self.assertTrue(
                    all(
                        call[instruction_key] == canonical_instructions
                        for call in calls
                    )
                )
                records = [
                    json.loads(line)
                    for line in (root / "runtime/logs/runs.jsonl").read_text().splitlines()
                ]
                self.assertEqual(len(records), 16)
                self.assertTrue(
                    all(
                        record["rollout_system_instructions_sha256"]
                        == CANONICAL_BOOTSTRAP_README_SHA256
                        for record in records
                    )
                )

    def test_opencode_resume_requires_matching_backend_configuration(self) -> None:
        custom_provider = custom_provider_configuration(
            model="fixture/model-one",
            provider_id="fixture",
            name="Fixture Provider",
            npm="@ai-sdk/openai-compatible",
            base_url="https://provider.example/v1",
            api_key_env="CUSTOM_API_KEY",
            header_env=("X-Custom=CUSTOM_HEADER",),
            context_limit=8192,
            output_limit=1024,
        )
        custom_provider_sha256 = custom_provider_fingerprint(custom_provider)
        args = Namespace(
            worker_backend="opencode",
            opencode_initial_prompt=DEFAULT_BOOTSTRAP_INITIAL_PROMPT,
            opencode_agent="build",
            opencode_variant=None,
            opencode_server_startup_timeout_seconds=15,
            worker_timeout_seconds=3600,
            opencode_sandbox_mode="bubblewrap",
            opencode_network_mode="allow",
            _opencode_runtime_version="1.18.21",
            _opencode_bin_sha256="opencode-sha",
            _opencode_bun_version="1.3.14",
            _opencode_bun_sha256="bun-sha",
            _opencode_worker_sha256="worker-sha",
            _opencode_python_sha256="python-sha",
            _opencode_auth_sha256=None,
            _opencode_provider_env_names=("OPENAI_API_KEY",),
            _opencode_provider_env_sha256="provider-env-sha",
            _opencode_custom_provider_sha256=custom_provider_sha256,
            _opencode_custom_provider=custom_provider,
            _opencode_allowed_bun_versions=("1.3.14",),
            _opencode_bubblewrap_bin="/usr/bin/bwrap",
            _opencode_bubblewrap_version="bubblewrap 0.11.0",
            _opencode_bubblewrap_sha256="bwrap-sha",
        )
        record = {
            "worker_backend": "opencode",
            "opencode_agent": "build",
            "opencode_variant": None,
            "opencode_runtime_version": "1.18.21",
            "opencode_bin_sha256": "opencode-sha",
            "opencode_bun_version": "1.3.14",
            "opencode_bun_sha256": "bun-sha",
            "opencode_worker_sha256": "worker-sha",
            "opencode_python_sha256": "python-sha",
            "opencode_auth_sha256": None,
            "opencode_provider_env_sha256": "provider-env-sha",
            "opencode_custom_provider": custom_provider,
            "opencode_custom_provider_sha256": custom_provider_sha256,
            "opencode_allowed_bun_versions": ["1.3.14"],
            "opencode_server_startup_timeout_seconds": 15,
            "opencode_worker_timeout_seconds": 3600,
            "opencode_sandbox_mode": "bubblewrap",
            "opencode_network_mode": "allow",
            "opencode_bubblewrap_bin": "/usr/bin/bwrap",
            "opencode_bubblewrap_version": "bubblewrap 0.11.0",
            "opencode_bubblewrap_sha256": "bwrap-sha",
            "rollout_system_instructions_version": ROLLOUT_SYSTEM_INSTRUCTIONS_VERSION,
            "rollout_system_instructions_fingerprint": ROLLOUT_SYSTEM_INSTRUCTIONS_FINGERPRINT,
            "rollout_system_instructions_mode": ROLLOUT_SYSTEM_INSTRUCTIONS_MODE,
            "rollout_system_instructions_sha256": CANONICAL_BOOTSTRAP_README_SHA256,
            "rollout_effective_initial_prompt_sha256": hashlib.sha256(
                DEFAULT_BOOTSTRAP_INITIAL_PROMPT.encode()
            ).hexdigest(),
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
                {**record, "opencode_server_startup_timeout_seconds": 99}, args
            )
        )
        self.assertFalse(
            _worker_backend_resume_compatible(
                {**record, "opencode_provider_env_sha256": "changed"}, args
            )
        )
        custom_variants = (
            {
                "model": "other/model-one",
                "provider_id": "other",
            },
            {"npm": "@ai-sdk/openai"},
            {"base_url": "https://other.example/v1"},
            {"model": "fixture/model-two"},
            {"context_limit": 16384},
            {"header_env": ("X-Other=CUSTOM_HEADER",)},
        )
        base_custom = {
            "model": "fixture/model-one",
            "provider_id": "fixture",
            "name": "Fixture Provider",
            "npm": "@ai-sdk/openai-compatible",
            "base_url": "https://provider.example/v1",
            "api_key_env": "CUSTOM_API_KEY",
            "header_env": ("X-Custom=CUSTOM_HEADER",),
            "context_limit": 8192,
            "output_limit": 1024,
        }
        for overrides in custom_variants:
            with self.subTest(custom_provider_overrides=overrides):
                values = {**base_custom, **overrides}
                changed = custom_provider_configuration(**values)
                self.assertFalse(
                    _worker_backend_resume_compatible(
                        {
                            **record,
                            "opencode_custom_provider": changed,
                            "opencode_custom_provider_sha256": custom_provider_fingerprint(changed),
                        },
                        args,
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
        inherited = {
            **record,
            "bootstrap_seed_used": False,
            "rollout_effective_initial_prompt_sha256": hashlib.sha256(
                b"inherited child prompt"
            ).hexdigest(),
        }
        self.assertTrue(
            _rollout_prompt_resume_compatible(
                inherited,
                args,
                effective_initial_prompt="inherited child prompt",
            )
        )
        self.assertFalse(
            _rollout_prompt_resume_compatible(
                inherited,
                args,
                effective_initial_prompt="changed child prompt",
            )
        )
        self.assertFalse(
            _rollout_prompt_resume_compatible(
                {**inherited, "rollout_system_instructions_sha256": "legacy"},
                args,
                effective_initial_prompt="inherited child prompt",
            )
        )
        self.assertFalse(
            _rollout_prompt_resume_compatible(
                {
                    "worker_backend": "opencode",
                    "bootstrap_seed_used": True,
                    "rollout_effective_initial_prompt_sha256": hashlib.sha256(
                        DEFAULT_BOOTSTRAP_INITIAL_PROMPT.encode()
                    ).hexdigest(),
                },
                args,
                effective_initial_prompt=None,
            )
        )

    def test_completed_legacy_system_prompt_history_is_kept_but_partial_is_rejected(self) -> None:
        documents = Path.home() / "Documents"
        documents.mkdir(exist_ok=True)
        for partial in (False, True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory(
                dir=documents
            ) as temp:
                root = Path(temp)
                runtime = root / "runtime"
                task = root / "task.md"
                task.write_text("# Resume identity fixture\n")
                argv = [
                    "main_loop.py",
                    "--benchmark",
                    "open-ended",
                    "--task-file",
                    str(task),
                    "--runtime-root",
                    str(runtime),
                    "--worker-backend",
                    "openrouter",
                    "--model",
                    "fixture/model",
                    "--num-rollouts",
                    "8",
                    "--step",
                ]
                calls: list[dict[str, object]] = []

                def worker(**kwargs: object) -> WorkerResult:
                    calls.append(kwargs)
                    return WorkerResult("offline", "completed", "final_message")

                with patch.dict(
                    "os.environ", {"OPENROUTER_API_KEY": "test-only-key"}
                ), patch("sys.argv", argv), patch(
                    "main_loop.run_worker", side_effect=worker
                ):
                    _run_main([])

                runs_path = runtime / "logs/runs.jsonl"
                records = [
                    json.loads(line) for line in runs_path.read_text().splitlines()
                ]
                if partial:
                    records = records[:7]
                for record in records:
                    for field in (
                        "rollout_system_instructions_version",
                        "rollout_system_instructions_fingerprint",
                        "rollout_system_instructions_mode",
                        "rollout_system_instructions_chars",
                        "rollout_system_instructions_sha256",
                        "rollout_effective_initial_prompt_sha256",
                        "bootstrap_readme_system_instructions",
                    ):
                        record.pop(field, None)
                runs_path.write_text(
                    "".join(json.dumps(record) + "\n" for record in records)
                )
                identity_path = runtime / "runtime_benchmark.json"
                identity = json.loads(identity_path.read_text())
                identity["capabilities"].pop(
                    "rollout_system_instructions", None
                )
                identity_path.write_text(json.dumps(identity))

                if partial:
                    with patch.dict(
                        "os.environ", {"OPENROUTER_API_KEY": "test-only-key"}
                    ), patch("sys.argv", argv), patch(
                        "main_loop.run_worker", side_effect=worker
                    ), self.assertRaisesRegex(
                        RuntimeError, "rollout system instructions or initial prompt"
                    ):
                        _run_main([])
                    self.assertEqual(len(calls), 8)
                else:
                    with patch.dict(
                        "os.environ", {"OPENROUTER_API_KEY": "test-only-key"}
                    ), patch("sys.argv", argv), patch(
                        "main_loop.run_worker", side_effect=worker
                    ):
                        _run_main([])
                    self.assertEqual(len(calls), 16)
                    self.assertEqual(
                        {call["task_index"] for call in calls[:8]}, {0}
                    )
                    self.assertEqual(
                        {call["task_index"] for call in calls[8:]}, {1}
                    )

    def test_actual_opencode_orchestration_separates_system_and_user_prompts(self) -> None:
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
                "8",
                "--step",
                "--opencode-bin",
                str(fake_opencode),
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
            self.assertEqual(len(calls), 24)
            inherited_indices = [
                index
                for index, call in enumerate(calls)
                if call["initial_user_text"] == "INHERITED CHILD PROMPT"
            ]
            self.assertEqual(len(inherited_indices), 1)
            inherited_index = inherited_indices[0]
            self.assertIn(inherited_index, range(8, 16))
            self.assertTrue(
                all(
                    call["initial_user_text"] == DEFAULT_BOOTSTRAP_INITIAL_PROMPT
                    for index, call in enumerate(calls)
                    if index != inherited_index
                )
            )
            canonical_instructions = canonical_rollout_system_instructions()
            self.assertTrue(
                all(
                    call["system_instructions"] == canonical_instructions
                    for call in calls
                )
            )
            self.assertNotIn(
                str(runtime / "logs/rollout_control"),
                [str(path) for path in calls[0]["sandbox_writable_roots"]],
            )
            self.assertNotIn(
                str(Path(__file__).resolve().parents[1]),
                [str(path) for path in calls[0]["sandbox_read_only_roots"]],
            )
            self.assertNotIn(
                str(runtime / "logs/task_store"),
                [str(path) for path in calls[0]["sandbox_read_only_roots"]],
            )
            self.assertFalse(
                any("benchmark_events" in str(path) or "arc_agi" in str(path) for path in calls[0]["sandbox_writable_roots"])
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
            self.assertEqual(len(records), 24)
            prompt_hashes = [
                record["opencode_effective_initial_prompt_sha256"]
                for record in records
            ]
            self.assertEqual(len(set(prompt_hashes)), 2)
            self.assertEqual(sorted(prompt_hashes.count(value) for value in set(prompt_hashes)), [1, 23])
            self.assertEqual(
                records[0]["opencode_system_instructions_sha256"],
                CANONICAL_BOOTSTRAP_README_SHA256,
            )
            self.assertTrue(
                all(
                    record["rollout_system_instructions_sha256"]
                    == CANONICAL_BOOTSTRAP_README_SHA256
                    for record in records
                )
            )
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
            peer_section = "## Peer Identity" + runtime_text.split("## Peer Identity", 1)[1]
            self.assertEqual(
                [line for line in peer_section.splitlines() if line],
                [
                    "## Peer Identity",
                    "- your name: unavailable",
                    "- other peer names: unavailable",
                ],
            )
            self.assertNotIn("send_message", peer_section)
            bootstrap = (
                Path(__file__).resolve().parents[1] / "seeds/bootstrap/README.md"
            ).read_text(encoding="utf-8")
            bootstrap_words = " ".join(bootstrap.split())
            self.assertIn("Nobody has assigned you an objective.", bootstrap_words)
            self.assertIn(
                "`runtime.md` lists how many there are and what they are called.",
                bootstrap_words,
            )
            self.assertIn('send_message(message="...", receiver="...")', bootstrap)
            self.assertIn(
                "`receiver` must exactly match one of the names in `runtime.md`.",
                bootstrap_words,
            )
            self.assertIn("`seed_output/` is local writable empty directory", bootstrap_words)
            self.assertIn(
                "`shared_workspace/` is visible to all programs running alongside you. "
                "It is erased at the end of the round.",
                bootstrap_words,
            )
            self.assertIn("`archive/` is durable and shared across rounds.", bootstrap_words)
            self.assertIn(
                "Material committed there can remain available to programs that arrive later.",
                bootstrap_words,
            )
            self.assertIn("Uncommitted changes there are discarded when you stop.", bootstrap_words)

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
