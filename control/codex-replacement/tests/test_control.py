from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

import control


BENCHMARK_BYTES = (
    b"# Task\n\nProve the Riemann hypothesis.\n\n"
    b"The Riemann hypothesis states that every nontrivial zero of the analytically\n"
    b"continued Riemann zeta function \xce\xb6(s) has real part 1/2.\n"
)


def command(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True)


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return command("git", "-C", str(repo), *args, check=check)


class ControlTest(unittest.TestCase):
    def make_study(self, root: Path) -> control.Study:
        (root / "seed").mkdir(parents=True)
        (root / "hooks").mkdir()
        shutil.copy2(
            Path(control.__file__).parent / "seed/model_instructions.md",
            root / "seed/model_instructions.md",
        )
        shutil.copy2(Path(control.__file__).parent / "hooks/iteration_boundary.py", root / "hooks/iteration_boundary.py")
        (root / "seed/BENCHMARK.md").write_bytes(BENCHMARK_BYTES)
        fake = Path(control.__file__).parent / "tests/fake_codex.py"
        fake.chmod(0o755)
        return control.Study(root, str(fake))

    def make_auth(self, root: Path) -> tuple[Path, str]:
        auth_home = root / "auth-home"
        auth_home.mkdir()
        secret = "test-secret-token-9f2e71a8"
        auth = auth_home / "auth.json"
        auth.write_text(json.dumps({"tokens": {"access_token": secret}}), encoding="utf-8")
        auth.chmod(0o600)
        return auth_home, secret

    def initialize(self, root: Path) -> tuple[control.Study, str]:
        study = self.make_study(root / "study")
        auth_home, secret = self.make_auth(root)
        manifest = control.initialize_study(
            study,
            auth_home=auth_home,
        )
        control.verify_layout(study, control.load_json(study.study_state_path))
        self.assertIsNone(manifest["destination"]["head"])
        self.assertTrue(manifest["destination"]["unborn"])
        return study, secret

    def test_replacement_instruction_is_exact_reviewed_canonical_transformation(self) -> None:
        source_root = Path(control.__file__).resolve().parent
        canonical_path = control.canonical_bootstrap_path(source_root)
        canonical = canonical_path.read_text(encoding="utf-8")
        instruction = (source_root / "seed/model_instructions.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(len(canonical.encode("utf-8")), control.CANONICAL_BOOTSTRAP_BYTES)
        self.assertEqual(
            control.sha256_bytes(canonical.encode("utf-8")),
            control.CANONICAL_BOOTSTRAP_SHA256,
        )
        self.assertEqual(control.render_aligned_instruction(canonical), instruction)
        self.assertEqual(
            [
                "## Places",
                "## What is already there",
            ],
            [line for line in instruction.splitlines() if line.startswith("## ")],
        )
        for unavailable in (
            "spawn_child",
            "## Leaving a successor",
            "natural turn",
            "compaction",
            "session survival",
            "evaluator",
        ):
            self.assertNotIn(unavailable, instruction)
        for required in (
            "shared_workspace/BENCHMARK.md",
            "run out of room",
            "next set starts",
            "One set starting, working, and stopping is a round.",
            "Nobody has assigned you an objective.",
            "make it an assignment.",
            "same ordinary Git checkout",
            "Git commands run concurrently",
            "Staged, modified, deleted, untracked, and ignored",
            "seed_output/",
            "runtime.md",
        ):
            self.assertIn(required, instruction)
        with self.assertRaisesRegex(
            control.ControlError, "canonical bootstrap content is not the byte-pinned"
        ):
            control.render_aligned_instruction(canonical + "\nextra drift\n")
        pins = json.loads((source_root / "seed/PINS.json").read_text(encoding="utf-8"))
        self.assertEqual(
            pins["instruction_transformation"],
            {
                "version": control.INSTRUCTION_TRANSFORM_VERSION,
                "deviations": list(control.INSTRUCTION_DEVIATIONS),
                "runtime_document_format": control.RUNTIME_DOCUMENT_FORMAT,
            },
        )
        self.assertEqual(
            pins["canonical_bootstrap"]["sha256"],
            control.sha256_file(canonical_path),
        )
        self.assertEqual(
            pins["replacement_instruction"]["sha256"],
            control.sha256_file(source_root / "seed/model_instructions.md"),
        )
        self.assertEqual(
            pins["instruction_delivery"],
            {
                "additive_agents_discovery": False,
                "config_key": "model_instructions_file",
                "private_filename": "model_instructions.md",
                "project_doc_max_bytes": 0,
                "stock_builtins_retained": False,
                "unavoidable_platform_tool_protocol": True,
            },
        )

    def test_only_instruction_delivery_differs_from_additive_control(self) -> None:
        source_root = Path(control.__file__).resolve().parent
        additive_root = source_root.parent / "codex-additive"
        spec = importlib.util.spec_from_file_location(
            "additive_control_for_parity", additive_root / "control.py"
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        additive = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = additive
        spec.loader.exec_module(additive)
        self.assertEqual(control.ROLLOUT_COUNT, additive.ROLLOUT_COUNT)
        self.assertEqual(control.MODEL, additive.MODEL)
        self.assertEqual(control.REASONING_EFFORT, "high")
        self.assertEqual(control.REASONING_EFFORT, additive.REASONING_EFFORT)
        self.assertEqual(control.FRESH_PROMPT, additive.FRESH_PROMPT)
        self.assertEqual(control.CONTINUATION_INPUT, additive.CONTINUATION_INPUT)
        self.assertEqual(
            control.CAPABILITY_IDENTITY,
            "stock-codex-passive-observer-no-spawn-reasoning-high-v2",
        )
        self.assertEqual(control.CAPABILITY_IDENTITY, additive.CAPABILITY_IDENTITY)
        self.assertEqual(control.FORBIDDEN_EXPERIMENT_TOOLS, additive.FORBIDDEN_EXPERIMENT_TOOLS)
        self.assertEqual(
            (source_root / "hooks/iteration_boundary.py").read_bytes(),
            (additive_root / "hooks/iteration_boundary.py").read_bytes(),
        )
        self.assertEqual(
            (source_root / "seed/BENCHMARK.md").read_bytes(),
            (additive_root / "seed/BENCHMARK.md").read_bytes(),
        )
        self.assertEqual(
            (source_root / "seed/model_instructions.md").read_bytes(),
            (additive_root / "seed/AGENTS.md").read_bytes(),
        )
        replacement_config = control.render_config(
            source_root / "runtime/shared_workspace",
            source_root,
            Path("/pinned/codex"),
        )
        additive_config = additive.render_config(
            additive_root / "runtime/shared_workspace",
            additive_root,
            Path("/pinned/codex"),
        )

        def normalize(value: object, root: Path) -> object:
            if isinstance(value, str):
                return value.replace(str(root), "<CONTROL_ROOT>")
            if isinstance(value, list):
                return [normalize(item, root) for item in value]
            if isinstance(value, dict):
                return {
                    str(normalize(key, root)): normalize(child, root)
                    for key, child in value.items()
                }
            return value

        replacement = normalize(tomllib.loads(replacement_config), source_root)
        additive_parsed = normalize(tomllib.loads(additive_config), additive_root)
        self.assertIsInstance(replacement, dict)
        self.assertIsInstance(additive_parsed, dict)
        self.assertEqual(replacement.pop("model_instructions_file"), "model_instructions.md")
        self.assertEqual(replacement["model_reasoning_effort"], "high")
        self.assertEqual(additive_parsed["model_reasoning_effort"], "high")
        self.assertEqual(replacement.pop("project_doc_max_bytes"), 0)
        self.assertEqual(additive_parsed.pop("project_doc_max_bytes"), 32768)
        additive_workspace = additive_parsed["permissions"]["control"]["filesystem"][
            ":workspace_roots"
        ]
        self.assertEqual(additive_workspace.pop("AGENTS.md"), "read")
        self.assertEqual(replacement, additive_parsed)

        replacement_pins = json.loads(
            (source_root / "seed/PINS.json").read_text(encoding="utf-8")
        )
        additive_pins = json.loads(
            (additive_root / "seed/PINS.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            replacement_pins["control_parity"]["source_pins_sha256"],
            control.sha256_file(additive_root / "seed/PINS.json"),
        )
        for key in (
            "archive_initial_state",
            "benchmark",
            "canonical_bootstrap",
            "instruction_transformation",
            "fresh_prompt",
            "continuation_input",
            "codex",
        ):
            self.assertEqual(replacement_pins[key], additive_pins[key])
        self.assertEqual(
            replacement_pins["capability_identity"], control.CAPABILITY_IDENTITY
        )
        self.assertEqual(
            replacement_pins["capability_identity"],
            additive_pins["capability_identity"],
        )
        self.assertEqual(replacement_pins["experiment"]["reasoning_effort"], "high")
        self.assertEqual(additive_pins["experiment"]["reasoning_effort"], "high")
        for key in ("iteration_semantics", "model", "reasoning_effort", "rollout_count"):
            self.assertEqual(
                replacement_pins["experiment"][key], additive_pins["experiment"][key]
            )

    def test_init_creates_genuinely_empty_unborn_shared_archive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            snapshot = control.verify_initial_empty_repository(study.archive)
            self.assertIsNone(snapshot["head"])
            self.assertTrue(snapshot["unborn"])
            self.assertEqual(snapshot["branch"], "refs/heads/main")
            self.assertEqual(snapshot["refs"], [])
            self.assertEqual(snapshot["tracked_file_count"], 0)
            self.assertEqual(snapshot["object_counts"]["count"], 0)
            self.assertEqual(snapshot["object_counts"]["in-pack"], 0)
            self.assertEqual(git(study.archive, "remote").stdout, "")
            self.assertEqual(
                sorted(entry.name for entry in study.archive.iterdir()), [".git"]
            )
            init = control.load_json(study.runtime / "manifests/init.json")
            self.assertEqual(init["archive_seed"], control.empty_repository_pin())
            self.assertEqual(init["stock_project_trust"]["trust_level"], "trusted")
            self.assertFalse(init["stock_project_trust"]["filesystem_access_granted"])
            for index in range(8):
                rollout = study.rollout_dir(index)
                self.assertFalse((rollout / "TASK.md").exists())
                self.assertFalse((rollout / "TASK.md").is_symlink())
                self.assertEqual(
                    (rollout / "shared_workspace/BENCHMARK.md").read_bytes(),
                    BENCHMARK_BYTES,
                )
                self.assertEqual(
                    (rollout / "runtime.md").read_text(encoding="utf-8"),
                    control.render_runtime_document(study, index),
                )
                self.assertTrue((rollout / "seed_output").is_dir())
                self.assertEqual(list((rollout / "seed_output").iterdir()), [])
                for directory in (rollout, study.codex_home(index)):
                    self.assertFalse((directory / "AGENTS.md").exists())
                    self.assertFalse((directory / "AGENTS.override.md").exists())
                replacement = study.codex_home(index) / "model_instructions.md"
                self.assertEqual(
                    replacement.read_bytes(),
                    (Path(control.__file__).parent / "seed/model_instructions.md").read_bytes(),
                )
                self.assertEqual(replacement.stat().st_mode & 0o777, 0o444)
            state = control.load_json(study.study_state_path)
            self.assertEqual(state["next_slot_session_ids"], [None] * 8)
            self.assertEqual(state["seen_fresh_session_ids"], [])
            self.assertEqual(state["compaction_counts"], [0] * 8)
            with self.assertRaisesRegex(control.ControlError, "runtime already exists"):
                control.initialize_study(
                    study,
                    auth_home=Path(raw) / "auth-home",
                )

    def test_exact_stock_project_trust_is_preseeded_and_other_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            expected_project = str(control.stock_project_root(study.root))
            expected_hash = control.load_json(study.study_state_path)["config_sha256"]
            for index in range(8):
                config_path = study.codex_home(index) / "config.toml"
                config_text = config_path.read_text(encoding="utf-8")
                self.assertEqual(
                    control.configured_project_trust(config_text, study.root),
                    {
                        "project_root": expected_project,
                        "trust_level": "trusted",
                        "filesystem_access_granted": False,
                    },
                )
                self.assertEqual(control.sha256_file(config_path), expected_hash)
                parsed = tomllib.loads(config_text)
                self.assertEqual(parsed["model_instructions_file"], "model_instructions.md")
                self.assertEqual(parsed["project_doc_max_bytes"], 0)
                self.assertNotIn("[permissions.control.workspace_roots]", config_text)
                self.assertIn("BENCHMARK.md", config_text)
                self.assertNotIn("TASK.md", config_text)
                self.assertNotIn('"AGENTS.md" = "read"', config_text)
            command, _ = control.build_codex_command(
                study, 0, resume=False, session_id=None
            )
            self.assertIn('model_reasoning_effort="high"', command)
            self.assertNotIn('model_reasoning_effort="low"', command)
            self.assertNotIn("--dangerously-bypass-hook-trust", command)
            with (study.codex_home(7) / "config.toml").open("a", encoding="utf-8") as stream:
                stream.write('\n[projects."/unexpected"]\ntrust_level = "trusted"\n')
            with self.assertRaisesRegex(control.ControlError, "config changed"):
                control.verify_layout(study, control.load_json(study.study_state_path))

    def test_v1_state_identity_cannot_resume_as_v2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            state = control.load_json(study.study_state_path)
            state["format"] = "stock-codex-replacement-instructions-control-state"
            state["version"] = 1
            state.pop("treatment_version")
            state.pop("capability_identity")
            control.atomic_json(study.study_state_path, state)
            with self.assertRaisesRegex(control.ControlError, "not a resumable"):
                control.status_record(study)

    def test_preflight_rematerializes_exact_benchmark_after_batch_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            benchmark = study.shared_workspace / "BENCHMARK.md"
            benchmark.unlink()
            self.assertFalse(benchmark.exists())
            result = control.run_preflight(study, real_cli=False)
            self.assertFalse(result["provider_call"])
            self.assertEqual(benchmark.read_bytes(), BENCHMARK_BYTES)
            self.assertEqual(benchmark.stat().st_mode & 0o777, 0o444)

    def test_no_stop_hook_and_passive_auto_postcompact_observer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            state = Path(raw)
            control.atomic_json(state / "compaction_counter.json", {"count": 0})
            environment = os.environ.copy() | {"CONTROL_ROLLOUT_STATE_DIR": str(state)}
            hook = Path(control.__file__).parent / "hooks/iteration_boundary.py"
            configured = control.render_hooks(Path(control.__file__).parent, state)
            self.assertEqual(set(configured["hooks"]), {"PostCompact"})
            self.assertFalse(
                control.configured_hook_controls(configured)["stop_hook"]
            )
            post = command_hook(
                hook,
                {
                    "hook_event_name": "PostCompact",
                    "trigger": "auto",
                    "session_id": "s",
                    "turn_id": "t",
                },
                environment,
            )
            self.assertEqual(post, {})
            self.assertEqual(control.read_compaction_count(state), 1)
            events = (state / "hook_events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(events), 1)
            recorded = json.loads(events[0])
            self.assertEqual(recorded["event"], "PostCompact")
            self.assertEqual(recorded["count_after"], 1)
            self.assertFalse(
                {"continue", "decision", "reason", "stopReason"} & set(post)
            )
            second_post = command_hook(
                hook,
                {
                    "hook_event_name": "PostCompact",
                    "trigger": "auto",
                    "session_id": "s",
                    "turn_id": "t",
                },
                environment,
            )
            self.assertEqual(second_post, {})
            self.assertEqual(control.read_compaction_count(state), 2)
            stop_attempt = subprocess.run(
                [os.fspath(Path(os.sys.executable)), str(hook)],
                input=json.dumps(
                    {"hook_event_name": "Stop", "session_id": "s", "turn_id": "t"}
                ).encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
            )
            self.assertEqual(stop_attempt.returncode, 0)
            self.assertEqual(json.loads(stop_attempt.stdout), {})
            self.assertEqual(control.read_compaction_count(state), 2)

    def test_natural_fanout_mixed_survivor_refill_identity_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, secret = self.initialize(Path(raw))
            preflight = control.run_preflight(study, real_cli=False)
            self.assertFalse(preflight["tool_controls"]["features.multi_agent"])
            self.assertTrue(
                preflight["tool_controls"]["replacement_model_instructions_file"]
            )
            self.assertFalse(preflight["tool_controls"]["additive_agents_discovery"])
            self.assertEqual(
                preflight["replacement_occurrences_in_additive_prompt_input"], 0
            )
            self.assertEqual(
                preflight["configured_effective_base_instruction_sha256"],
                control.sha256_file(
                    Path(control.__file__).parent / "seed/model_instructions.md"
                ),
            )
            self.assertFalse(preflight["hook_controls"]["stop_hook"])
            for index in range(8):
                (study.rollout_dir(index) / "seed_output/stale.txt").write_text(
                    "discard before round\n", encoding="utf-8"
                )
            with mock.patch.dict(
                os.environ,
                {
                    "FAKE_PRINT_AUTH": "1",
                    "FAKE_CODEX_DELAY": "0.08",
                    "FAKE_COMPACTION_COUNTS": "0,1,0,1,1,2,0,0",
                },
                clear=False,
            ):
                first = control.run_iteration(
                    study, resume=False, preflight=True, real_cli=False
                )
            self.assertEqual(first["status"], "complete")
            self.assertTrue(first["all_natural_turns_succeeded"])
            self.assertEqual(first["compaction_counts_after"], [0, 1, 0, 1, 1, 2, 0, 0])
            self.assertEqual(first["compaction_deltas"], [0, 1, 0, 1, 1, 2, 0, 0])
            self.assertEqual(len(set(first["session_ids"])), 8)
            self.assertTrue(
                all(
                    item["removed_entries"] == ["stale.txt"] and item["empty"]
                    for item in first["private_seed_output_reset"]
                )
            )
            self.assertTrue(all(item["prompt"] == control.FRESH_PROMPT for item in first["rollouts"]))
            self.assertTrue(
                all(item["stream"]["turn_completed_count"] == 1 for item in first["rollouts"])
            )
            self.assertTrue(
                all(item["stream"]["final_message"] is not None for item in first["rollouts"])
            )
            latest_start = max(item["started_at"] for item in first["rollouts"])
            earliest_end = min(item["ended_at"] for item in first["rollouts"])
            self.assertLess(latest_start, earliest_end)
            shared_paths = {
                event_value(item["stdout"]["path"], "fake.invocation")["shared_realpath"]
                for item in first["rollouts"]
            }
            archive_inodes = {
                (
                    event_value(item["stdout"]["path"], "fake.invocation")["archive_device"],
                    event_value(item["stdout"]["path"], "fake.invocation")["archive_inode"],
                )
                for item in first["rollouts"]
            }
            self.assertEqual(shared_paths, {str(study.shared_workspace.resolve())})
            self.assertEqual(len(archive_inodes), 1)
            for item in first["rollouts"]:
                invocation = event_value(item["stdout"]["path"], "fake.invocation")
                self.assertTrue(invocation["runtime_document_format_present"])
                self.assertTrue(invocation["runtime_current_program_present"])
                self.assertEqual(invocation["seed_output_entries_at_turn_start"], [])
                self.assertEqual(invocation["project_doc_max_bytes"], 0)
                self.assertEqual(invocation["additive_agents_files"], [])
                self.assertEqual(
                    invocation["replacement_instruction_bytes"],
                    (Path(control.__file__).parent / "seed/model_instructions.md").stat().st_size,
                )
                saved = Path(item["stdout"]["path"]).read_text(encoding="utf-8")
                stderr = Path(item["stderr"]["path"]).read_text(encoding="utf-8")
                self.assertNotIn(secret, saved)
                self.assertNotIn(secret, stderr)
                self.assertGreater(item["stdout"]["redaction_count"], 0)
                self.assertIn("agents.enabled=false", item["command"])
                self.assertEqual(item["command"].count("multi_agent"), 1)
                self.assertEqual(item["command"].count("multi_agent_v2"), 1)
                self.assertFalse(item["stream"]["forbidden_collaboration_tools"])
                self.assertFalse(item["stream"]["forbidden_experiment_tools"])
                self.assertNotIn('"type": "fake.stop_hook"', saved)
            self.assertEqual(control.shared_non_archive_entries(study), [])
            expected_config_hash = control.load_json(study.study_state_path)["config_sha256"]
            self.assertTrue(
                all(
                    control.sha256_file(study.codex_home(index) / "config.toml")
                    == expected_config_hash
                    for index in range(8)
                )
            )

            expected_first_next = [
                first["session_ids"][index] if index in {1, 3, 4, 5} else None
                for index in range(8)
            ]
            self.assertEqual(first["next_slot_session_ids"], expected_first_next)
            first_state = control.load_json(study.study_state_path)
            self.assertEqual(first_state["next_slot_session_ids"], expected_first_next)

            with mock.patch.dict(
                os.environ,
                {"FAKE_COMPACTION_COUNTS": "1,1,0,0,0,0,1,0"},
                clear=False,
            ):
                second = control.run_iteration(
                    study, resume=True, preflight=True, real_cli=False
                )
            self.assertEqual(second["status"], "complete")
            self.assertEqual(second["compaction_counts_after"], [1, 2, 0, 1, 1, 2, 1, 0])
            resumed_slots = {1, 3, 4, 5}
            for item in second["rollouts"]:
                index = item["rollout_index"]
                if index in resumed_slots:
                    self.assertEqual(item["prompt"], control.CONTINUATION_INPUT)
                    self.assertEqual(item["command"][1:3], ["exec", "resume"])
                    self.assertEqual(second["session_ids"][index], first["session_ids"][index])
                else:
                    self.assertEqual(item["prompt"], control.FRESH_PROMPT)
                    self.assertNotEqual(item["command"][1:3], ["exec", "resume"])
                    self.assertNotEqual(second["session_ids"][index], first["session_ids"][index])
            expected_second_next = [
                second["session_ids"][index] if index in {0, 1, 6} else None
                for index in range(8)
            ]
            self.assertEqual(second["next_slot_session_ids"], expected_second_next)
            second_state = control.load_json(study.study_state_path)
            self.assertEqual(second_state["next_slot_session_ids"], expected_second_next)
            self.assertEqual(len(second_state["seen_fresh_session_ids"]), 12)

    def test_incomplete_rollout_does_not_cleanup_retry_or_advance_next_slots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            with mock.patch.dict(os.environ, {"FAKE_FAIL_ROLLOUT": "3"}, clear=False):
                with self.assertRaisesRegex(control.ControlError, "iteration incomplete"):
                    control.run_iteration(
                        study, resume=False, preflight=True, real_cli=False
                    )
            state = control.load_json(study.study_state_path)
            self.assertEqual(state["status"], "blocked_incomplete")
            self.assertEqual(state["completed_iterations"], 0)
            self.assertEqual(state["compaction_counts"][3], 0)
            self.assertEqual(sum(state["compaction_counts"]), 7)
            self.assertEqual(state["next_slot_session_ids"], [None] * 8)
            self.assertEqual(state["seen_fresh_session_ids"], [])
            self.assertTrue((study.shared_workspace / "BENCHMARK.md").exists())
            manifest = control.load_json(Path(state["last_iteration_manifest"]))
            self.assertFalse(manifest["all_natural_turns_succeeded"])
            self.assertIsNone(manifest["candidate_next_slot_session_ids"])
            self.assertIsNone(manifest["cleanup"])
            with self.assertRaisesRegex(control.ControlError, "not runnable"):
                control.run_iteration(study, resume=True, preflight=False, real_cli=False)

    def test_cleanup_handles_unborn_head_and_removes_every_dirty_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            repo = study.archive
            git(repo, "config", "user.name", "test")
            git(repo, "config", "user.email", "test@invalid")
            git(repo, "checkout", "--orphan", "preserved")
            (repo / "preserved.txt").write_text("committed\n", encoding="utf-8")
            git(repo, "add", "preserved.txt")
            git(repo, "commit", "-m", "preserved ref")
            preserved_commit = git(repo, "rev-parse", "refs/heads/preserved").stdout
            git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
            (repo / ".git/info/exclude").write_text("*.tmp\n", encoding="utf-8")
            (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
            git(repo, "add", "staged.txt")
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            (repo / "ignored.tmp").write_text("ignored\n", encoding="utf-8")
            nested = repo / "nested"
            command("git", "init", "-b", "main", str(nested))
            (study.shared_workspace / "batch-local").mkdir()
            (study.shared_workspace / "batch-local/file").write_text(
                "local\n", encoding="utf-8"
            )
            before = control.git_snapshot(repo)
            before_refs = control.git_refs_bytes(repo)
            self.assertIsNone(before["head"])
            self.assertTrue(before["unborn"])
            result = control.clean_shared_workspace(
                study,
                control.load_json(study.study_state_path)["archive_identity"],
            )
            after = control.git_snapshot(repo)
            self.assertEqual(result["cleanup_mode"], "unborn-read-tree-empty")
            self.assertIsNone(after["head"])
            self.assertTrue(after["unborn"])
            self.assertEqual(after["branch"], "refs/heads/main")
            self.assertEqual(control.git_refs_bytes(repo), before_refs)
            self.assertEqual(
                git(repo, "rev-parse", "refs/heads/preserved").stdout,
                preserved_commit,
            )
            self.assertEqual(after["tracked_file_count"], 0)
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored").stdout, "")
            self.assertEqual(
                sorted(entry.name for entry in repo.iterdir()), [".git"]
            )
            self.assertEqual(control.shared_non_archive_entries(study), [])

    def test_cleanup_preserves_head_branch_refs_and_deletes_every_dirty_kind(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            study, _ = self.initialize(Path(raw))
            repo = study.archive
            git(repo, "config", "user.name", "test")
            git(repo, "config", "user.email", "test@invalid")
            (repo / "WORLD.md").write_text("base\n", encoding="utf-8")
            git(repo, "add", "WORLD.md")
            git(repo, "commit", "-m", "base")
            git(repo, "checkout", "-b", "side")
            (repo / "WORLD.md").write_text("side\n", encoding="utf-8")
            git(repo, "commit", "-am", "side")
            git(repo, "checkout", "main")
            (repo / "WORLD.md").write_text("main\n", encoding="utf-8")
            git(repo, "commit", "-am", "main")
            conflict = git(repo, "merge", "side", check=False)
            self.assertNotEqual(conflict.returncode, 0)
            (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
            (repo / "ignored.tmp").write_text("ignored\n", encoding="utf-8")
            (study.shared_workspace / "batch-local").mkdir()
            (study.shared_workspace / "batch-local/file").write_text("local\n", encoding="utf-8")
            before_head = git(repo, "rev-parse", "HEAD").stdout
            before_branch = git(repo, "symbolic-ref", "HEAD").stdout
            before_refs = control.git_refs_bytes(repo)
            result = control.clean_shared_workspace(
                study,
                control.load_json(study.study_state_path)["archive_identity"],
            )
            self.assertEqual(result["operation_state_cleared"], "merge")
            self.assertEqual(git(repo, "rev-parse", "HEAD").stdout, before_head)
            self.assertEqual(git(repo, "symbolic-ref", "HEAD").stdout, before_branch)
            self.assertEqual(control.git_refs_bytes(repo), before_refs)
            self.assertEqual(git(repo, "status", "--porcelain", "--ignored").stdout, "")
            self.assertEqual(control.shared_non_archive_entries(study), [])
            (repo / ".git/BISECT_START").write_text("HEAD\n", encoding="utf-8")
            with self.assertRaisesRegex(control.ControlError, "bisect"):
                control.clean_shared_workspace(
                    study,
                    control.load_json(study.study_state_path)["archive_identity"],
                )


def command_hook(hook: Path, event: dict[str, object], environment: dict[str, str]) -> dict[str, object]:
    result = subprocess.run(
        [os.fspath(Path(os.sys.executable)), str(hook)],
        input=json.dumps(event).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        check=True,
    )
    return json.loads(result.stdout)


def event_value(path: str, event_type: str) -> dict[str, object]:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("type") == event_type:
            return event
    raise AssertionError(f"event {event_type} not found in {path}")


if __name__ == "__main__":
    unittest.main()
