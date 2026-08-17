from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from main_loop import (
    _claim_spawn_slot,
    _configure_runtime_environment,
    _create_benchmark_driver,
    _validate_benchmark_backend,
)
from utils.arc_agi_benchmark import ARC_TOOL_NAMES, ArcAgiBenchmarkDriver, ArcAgiConfig
from utils.arc_agi_mcp import DRIVER_CONTEXT_VERSION, ArcCommandService, load_context
from utils.arc_agi_rollout import ArcAgiCommandResult, ArcAgiSessionSnapshot
from utils.arc_agi_tasks import arc_task_uuid
from utils.benchmark_driver import (
    BenchmarkDriver,
    BenchmarkItemRef,
    BenchmarkOutcome,
    active_benchmark_item,
)
from utils.benchmark_events import append_benchmark_event


def _records(count: int = 6) -> list[dict[str, object]]:
    return [
        {
            "uuid": f"arc-uuid-{index}",
            "game_id": f"game-{index}",
            "title": f"Game {index}",
            "tags": [],
        }
        for index in range(count)
    ]


class _FakeServer:
    def __init__(self) -> None:
        self.base_url = "http://127.0.0.1:43210"
        self.terminate_calls = 0

    def terminate(self) -> int:
        self.terminate_calls += 1
        return 0


class _Launcher:
    def __init__(self) -> None:
        self.calls = 0
        self.servers: list[_FakeServer] = []

    def __call__(self, **_kwargs: object) -> _FakeServer:
        self.calls += 1
        server = _FakeServer()
        self.servers.append(server)
        return server


class _ScorecardClient:
    def __init__(self, _base_url: str) -> None:
        pass

    def get_scorecard(self, _card_id: str, game_id: str) -> dict[str, object]:
        return {
            "won": 0,
            "played": 1,
            "total_actions": 3,
            "levels_completed": 2,
            "cards": {
                game_id: {
                    "game_id": game_id,
                    "total_plays": 1,
                    "guids": ["must-not-leak"],
                    "levels_completed": [2],
                    "states": ["NOT_FINISHED"],
                    "actions": [3],
                    "resets": [1],
                    "total_actions": 3,
                }
            },
        }


def _supervisor_context(root: Path, name: str) -> dict[str, object]:
    control = root / name / "control"
    state = root / name / "state"
    workdir = root / name / "workdir"
    for directory in (control, state, workdir):
        directory.mkdir(parents=True, mode=0o700)
        directory.chmod(0o700)
    events = root / name / "benchmark_events.jsonl"
    events.touch(mode=0o600)
    events.chmod(0o600)
    return {
        "instance_uuid": name,
        "continuation_context_path": str(control / "continuation_context.json"),
        "rollout_state_dir": str(state),
        "workdir": str(workdir),
        "benchmark_events_path": str(events),
    }


class ArcAgiBenchmarkTests(unittest.TestCase):
    def _driver(
        self,
        root: Path,
        *,
        cap: int | None = 3,
        launcher: _Launcher | None = None,
        snapshot=None,
        closer=None,
    ) -> tuple[ArcAgiBenchmarkDriver, _Launcher]:
        owned_launcher = launcher or _Launcher()
        kwargs = {}
        if snapshot is not None:
            kwargs["snapshot_reader"] = snapshot
        if closer is not None:
            kwargs["rollout_closer"] = closer
        return (
            ArcAgiBenchmarkDriver(
                ArcAgiConfig(
                    state_path=root / "arc-benchmark-state.json",
                    seed=17,
                    problem_pool_size=cap,
                    render_scale=2,
                ),
                records_loader=lambda: _records(),
                server_launcher=owned_launcher,
                client_factory=_ScorecardClient,
                **kwargs,
            ),
            owned_launcher,
        )

    def test_protocol_deterministic_pool_server_ownership_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, launcher = self._driver(root)
            self.assertIsInstance(first, BenchmarkDriver)
            batch = first.prepare_batch(4, root / "shared-a")
            self.assertEqual(batch.item_count, 3)
            self.assertEqual(launcher.calls, 1)
            sampled = json.loads((root / "shared-a/problem_pool.json").read_text())
            with self.assertRaisesRegex(RuntimeError, "active batch"):
                first.prepare_batch(5, root / "shared-b")

            second, _ = self._driver(root)
            second_batch = second.prepare_batch(4, root / "shared-c")
            repeated = json.loads((root / "shared-c/problem_pool.json").read_text())
            self.assertEqual([row["uuid"] for row in sampled], [row["uuid"] for row in repeated])
            self.assertEqual(second_batch.item_count, 3)

            uncapped, _ = self._driver(root / "uncapped", cap=None)
            self.assertEqual(uncapped.prepare_batch(4, root / "shared-d").item_count, 6)

            duplicate_launcher = _Launcher()
            duplicate = ArcAgiBenchmarkDriver(
                ArcAgiConfig(state_path=root / "duplicate-state.json"),
                records_loader=lambda: [*_records(2), {**_records(1)[0], "game_id": "other"}],
                server_launcher=duplicate_launcher,
            )
            with self.assertRaisesRegex(ValueError, "duplicate uuid"):
                duplicate.prepare_batch(0, root / "bad")
            self.assertEqual(duplicate_launcher.calls, 0)
            duplicate_game = ArcAgiBenchmarkDriver(
                ArcAgiConfig(state_path=root / "duplicate-game-state.json"),
                records_loader=lambda: [*_records(2), {**_records(1)[0], "uuid": "other"}],
                server_launcher=duplicate_launcher,
            )
            with self.assertRaisesRegex(ValueError, "duplicate game_id"):
                duplicate_game.prepare_batch(0, root / "bad-game")
            self.assertEqual(duplicate_launcher.calls, 0)
            first.close()
            second.close()
            uncapped.close()

    def test_main_loop_selects_arc_driver_without_supergpqa_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = Namespace(
                benchmark="arc-agi",
                seed=23,
                problem_pool_size=4,
            )
            queue = root / "must-not-exist/problem_queue.json"
            task_store = root / "must-not-exist/task_store"
            dataset_cache = root / "must-not-exist/dataset_cache"
            driver = _create_benchmark_driver(
                args,
                arc_benchmark_state_path=root / "arc/state.json",
                problem_queue_path=queue,
                task_store_dir=task_store,
                dataset_cache_dir=dataset_cache,
                existing_records=[],
            )
            self.assertIsInstance(driver, ArcAgiBenchmarkDriver)
            self.assertEqual(driver.config.seed, 23)
            self.assertEqual(driver.config.problem_pool_size, 4)
            self.assertFalse(queue.parent.exists())
            self.assertFalse(task_store.exists())
            self.assertFalse(dataset_cache.exists())
            driver.close()

            with self.assertRaisesRegex(SystemExit, "requires --worker-backend codex"):
                _validate_benchmark_backend("arc-agi", "openrouter")
            _validate_benchmark_backend("arc-agi", "codex")

            environment = {
                key: value
                for key, value in os.environ.items()
                if key not in {"XDG_CACHE_HOME", "TMPDIR", "HF_HOME", "HF_DATASETS_CACHE"}
            }
            with patch.dict(os.environ, environment, clear=True):
                _configure_runtime_environment(root / "runtime", include_huggingface=False)
                self.assertNotIn("HF_HOME", os.environ)
                self.assertNotIn("HF_DATASETS_CACHE", os.environ)
                self.assertFalse((root / "runtime/cache/huggingface").exists())
                self.assertFalse((root / "runtime/cache/huggingface_datasets").exists())

    def test_launch_install_failure_terminates_server(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            driver, launcher = self._driver(Path(temp))
            with patch("utils.arc_agi_benchmark.os.replace", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    driver.prepare_batch(0, Path(temp) / "shared")
            self.assertEqual(launcher.calls, 1)
            self.assertEqual(launcher.servers[0].terminate_calls, 1)
            driver.close()

    def test_private_rollout_context_exact_mcp_config_and_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, _ = self._driver(root)
            batch = driver.prepare_batch(2, root / "shared")
            context_a = _supervisor_context(root, "rollout-a")
            context_b = _supervisor_context(root, "rollout-b")
            rollout_a = driver.prepare_rollout(batch, backend="codex", context=context_a)
            rollout_b = driver.prepare_rollout(batch, backend="codex", context=context_b)

            config = rollout_a.mcp_servers["arc_agi"]
            self.assertEqual(config["command"], sys.executable)
            self.assertEqual(config["args"], ["-m", "utils.arc_agi_mcp"])
            self.assertTrue(config["required"])
            self.assertEqual(config["enabled_tools"], list(ARC_TOOL_NAMES))
            self.assertEqual(config["default_tools_approval_mode"], "approve")
            self.assertEqual(config["startup_timeout_sec"], 10)
            self.assertEqual(config["tool_timeout_sec"], 60)
            self.assertEqual(set(config["env"]), {"METALANGUAGE_ARC_CONTEXT"})
            self.assertNotIn(config["env"]["METALANGUAGE_ARC_CONTEXT"], config["args"])
            self.assertFalse(rollout_a.sensitive_mcp_tools)

            path_a = Path(config["env"]["METALANGUAGE_ARC_CONTEXT"])
            path_b = Path(rollout_b.mcp_servers["arc_agi"]["env"]["METALANGUAGE_ARC_CONTEXT"])
            self.assertNotEqual(path_a, path_b)
            loaded_a = load_context(path_a)
            loaded_b = load_context(path_b)
            private_payload = json.loads(path_a.read_text())
            self.assertEqual(private_payload["version"], DRIVER_CONTEXT_VERSION)
            self.assertEqual(private_payload["instance_uuid"], "rollout-a")
            self.assertEqual(
                set(private_payload["benchmark_items"]),
                set(private_payload["allowed_game_ids"]),
            )
            expected_games = tuple(row["game_id"] for row in json.loads((root / "shared/problem_pool.json").read_text()))
            self.assertEqual(loaded_a.allowed_game_ids, expected_games)
            self.assertEqual(loaded_b.allowed_game_ids, expected_games)
            self.assertNotEqual(loaded_a.state_path, loaded_b.state_path)
            self.assertNotEqual(loaded_a.artifact_root, loaded_b.artifact_root)
            self.assertEqual(path_a.stat().st_mode & 0o777, 0o600)
            self.assertEqual(loaded_a.state_root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(loaded_a.rollout_root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(loaded_a.state_path.with_name("arc_session.json.lock").stat().st_mode & 0o777, 0o600)

            public = json.dumps(rollout_a.model_metadata, sort_keys=True)
            for private in (
                str(path_a),
                str(loaded_a.state_path),
                str(context_a["benchmark_events_path"]),
                loaded_a.base_url,
                "guid",
                "card_id",
                "ARC_API_KEY",
                "reasoning",
                "thought",
            ):
                self.assertNotIn(private, public)
            self.assertNotIn("instructions", rollout_a.model_metadata)
            self.assertIn("benchmark_readme", rollout_a.model_metadata)
            self.assertIn("mcp__arc_agi__RESET", public)
            self.assertIn("available_actions", public)
            with self.assertRaisesRegex(RuntimeError, "paths are not isolated"):
                driver.prepare_rollout(
                    batch,
                    backend="codex",
                    context={**context_a, "instance_uuid": "rollout-c"},
                )
            self.assertTrue(path_a.is_file())
            driver.close()

    def test_command_events_are_immediate_and_rollout_local(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, _ = self._driver(root)
            batch = driver.prepare_batch(4, root / "shared")
            rollouts = [
                driver.prepare_rollout(
                    batch,
                    backend="codex",
                    context=_supervisor_context(root, instance),
                )
                for instance in ("winner-a", "winner-b")
            ]
            selected_game = load_context(
                Path(
                    rollouts[0].mcp_servers["arc_agi"]["env"][
                        "METALANGUAGE_ARC_CONTEXT"
                    ]
                )
            ).allowed_game_ids[0]

            for rollout in rollouts:
                events_path = Path(rollout.context["benchmark_events_path"])
                instance_uuid = str(rollout.context["instance_uuid"])
                next_step = 0

                def result(
                    operation: str,
                    state: str,
                    levels_completed: int = 0,
                ) -> ArcAgiCommandResult:
                    nonlocal next_step
                    step_index = next_step
                    next_step += 1
                    return ArcAgiCommandResult(
                        {},
                        {
                            "game_id": selected_game,
                            "state": state,
                            "levels_completed": levels_completed,
                            "win_levels": 2,
                            "step_index": step_index,
                            "operation": operation,
                        },
                        (),
                    )

                def initialize(
                    state_path: str | Path,
                    *_args: object,
                    **_kwargs: object,
                ) -> ArcAgiCommandResult:
                    path = Path(state_path)
                    path.write_text("{}", encoding="utf-8")
                    path.chmod(0o600)
                    return result("reset", "NOT_FINISHED")

                action_results = iter(
                    (("NOT_FINISHED", 1), ("WIN", 2), ("WIN", 2))
                )
                service = ArcCommandService(
                    load_context(
                        Path(
                            rollout.mcp_servers["arc_agi"]["env"][
                                "METALANGUAGE_ARC_CONTEXT"
                            ]
                        )
                    ),
                    initialize=initialize,
                    step=lambda *_args, **_kwargs: result(
                        "action1", *next(action_results)
                    ),
                    selected_game=lambda _path: selected_game,
                )
                service.reset(selected_game)
                service.action("ACTION1")
                service.action("ACTION1")
                service.action("ACTION1")
                events = [
                    json.loads(line) for line in events_path.read_text().splitlines()
                ]
                commands = [
                    event
                    for event in events
                    if event["event_type"] == "benchmark_command_completed"
                    and event["instance_uuid"] == instance_uuid
                ]
                self.assertEqual(len(commands), 4)
                self.assertNotIn("guid", json.dumps(commands))
                self.assertNotIn("card", json.dumps(commands))
            driver.close()

    def test_reset_selection_event_is_idempotent_and_drives_spawn_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, _ = self._driver(root)
            batch = driver.prepare_batch(7, root / "shared")
            contexts = [
                _supervisor_context(root, "selection-a"),
                _supervisor_context(root, "selection-b"),
            ]
            contexts[1]["benchmark_events_path"] = contexts[0][
                "benchmark_events_path"
            ]
            rollouts = [
                driver.prepare_rollout(batch, backend="codex", context=context)
                for context in contexts
            ]
            selected_game = load_context(
                Path(
                    rollouts[0].mcp_servers["arc_agi"]["env"][
                        "METALANGUAGE_ARC_CONTEXT"
                    ]
                )
            ).allowed_game_ids[0]
            next_steps: dict[str, int] = {}

            def command_result(state_path: str | Path, operation: str) -> ArcAgiCommandResult:
                key = str(state_path)
                step_index = next_steps.get(key, -1) + 1
                next_steps[key] = step_index
                return ArcAgiCommandResult(
                    {},
                    {
                        "game_id": selected_game,
                        "state": "NOT_FINISHED",
                        "levels_completed": 0,
                        "win_levels": 1,
                        "step_index": step_index,
                        "operation": operation,
                    },
                    (),
                )

            def initialize(
                state_path: str | Path,
                *_args: object,
                **_kwargs: object,
            ) -> ArcAgiCommandResult:
                path = Path(state_path)
                path.write_text("{}", encoding="utf-8")
                path.chmod(0o600)
                return command_result(state_path, "reset")

            def reset(state_path: str | Path) -> ArcAgiCommandResult:
                return command_result(state_path, "reset")

            def step(
                state_path: str | Path,
                action: str,
                **_kwargs: object,
            ) -> ArcAgiCommandResult:
                return command_result(state_path, action.lower())

            services = [
                ArcCommandService(
                    load_context(
                        Path(
                            rollout.mcp_servers["arc_agi"]["env"][
                                "METALANGUAGE_ARC_CONTEXT"
                            ]
                        )
                    ),
                    initialize=initialize,
                    reset=reset,
                    step=step,
                    selected_game=lambda _path: selected_game,
                )
                for rollout in rollouts
            ]
            with self.assertRaisesRegex(Exception, "assigned ARC pool"):
                services[0].reset("not-allowed")
            def fail_selection(*args: object, **kwargs: object):
                if kwargs.get("event_type") == "benchmark_item_selected":
                    raise OSError("fixture")
                return append_benchmark_event(*args, **kwargs)

            with patch("utils.arc_agi_mcp.append_benchmark_event", side_effect=fail_selection):
                with self.assertRaisesRegex(Exception, "provenance"):
                    services[0].reset(selected_game)
            services[0].reset(selected_game)
            services[0].reset(selected_game)
            services[0].action("ACTION1")
            other_game = next(
                game
                for game in services[0].context.allowed_game_ids
                if game != selected_game
            )
            with self.assertRaisesRegex(Exception, "cannot change"):
                services[0].reset(other_game)
            services[1].reset(selected_game)

            expected_refs: list[BenchmarkItemRef] = []
            for rollout in rollouts:
                events_path = Path(rollout.context["benchmark_events_path"])
                events = [json.loads(line) for line in events_path.read_text().splitlines()]
                selected_events = [
                    event
                    for event in events
                    if event.get("event_type") == "benchmark_item_selected"
                    and event.get("instance_uuid")
                    == rollout.context["instance_uuid"]
                ]
                self.assertEqual(len(selected_events), 1)
                self.assertEqual(
                    selected_events[0]["instance_uuid"], rollout.context["instance_uuid"]
                )
                ref = active_benchmark_item(rollout.context)
                self.assertIsInstance(ref, BenchmarkItemRef)
                self.assertEqual(ref.source_id, selected_game)
                self.assertEqual(ref.iteration_index, 7)
                expected_refs.append(ref)
                command_events = [
                    event
                    for event in events
                    if event.get("event_type") == "benchmark_command_completed"
                    and event.get("instance_uuid")
                    == rollout.context["instance_uuid"]
                ]
                self.assertEqual(len(command_events), 4 if rollout is rollouts[0] else 1)
                command_text = json.dumps(command_events, sort_keys=True)
                self.assertNotIn("private", command_text)
                self.assertNotIn("guid", command_text)
                self.assertNotIn("card", command_text)
            self.assertEqual(expected_refs[0], expected_refs[1])

            spawn_context = {
                **rollouts[0].context,
                "task_id": "arc-scheduler",
                "task_index": 7,
                "rollout_username": "selection-a",
                "rollout_index": 0,
                "spawn_slots_path": str(root / "spawn-slots.json"),
                "spawn_slots_dir": str(root / "spawn-slots"),
                "child_slot_cap": 1,
            }
            claimed = _claim_spawn_slot(
                context=spawn_context,
                child_instance_uuid="arc-child",
                child_prompt="continue",
                source_workspace_dir=None,
            )
            self.assertTrue(claimed["slot_claimed"])
            manifest = json.loads(
                (
                    root
                    / "spawn-slots/slot_000_arc-chil/slot_manifest.json"
                ).read_text()
            )
            self.assertEqual(
                manifest["source_benchmark_item"], expected_refs[0].to_metadata()
            )
            self.assertFalse(
                {"base_url", "card_id", "guid", "state_path"}
                & set(manifest["source_benchmark_item"])
            )
            driver.close()

    def test_partial_rollout_failure_removes_private_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, _ = self._driver(root)
            batch = driver.prepare_batch(0, root / "shared")
            context = _supervisor_context(root, "partial")
            control = Path(context["continuation_context_path"]).parent
            state_root = Path(context["rollout_state_dir"]) / "arc_agi"
            rollout_root = Path(context["workdir"]) / "arc_agi_rollout"
            with patch(
                "utils.arc_agi_benchmark.load_context",
                side_effect=RuntimeError("fixture"),
            ):
                with self.assertRaisesRegex(RuntimeError, "fixture"):
                    driver.prepare_rollout(batch, backend="codex", context=context)
            self.assertFalse((control / "arc_mcp_context.json").exists())
            self.assertFalse(state_root.exists())
            self.assertFalse(rollout_root.exists())
            driver.close()

    def test_win_retirement_is_deduplicated_and_applies_next_iteration(self) -> None:
        snapshots: dict[str, ArcAgiSessionSnapshot] = {}

        def read_snapshot(path: str | Path) -> ArcAgiSessionSnapshot:
            return snapshots[str(path)]

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, launcher = self._driver(root, cap=None, snapshot=read_snapshot)
            batch = driver.prepare_batch(5, root / "shared-current")
            current_pool_path = root / "shared-current/problem_pool.json"
            current_pool_bytes = current_pool_path.read_bytes()
            current_pool = json.loads(current_pool_bytes)
            won_game = current_pool[0]["game_id"]
            won_uuid = current_pool[0]["uuid"]
            partial_game = current_pool[1]["game_id"]
            partial_uuid = current_pool[1]["uuid"]

            outcomes = []
            for instance, game_id, official_state in (
                ("winner-a", won_game, "WIN"),
                ("winner-b", won_game, "WIN"),
                ("partial", partial_game, "NOT_FINISHED"),
            ):
                rollout = driver.prepare_rollout(
                    batch,
                    backend="codex",
                    context=_supervisor_context(root, instance),
                )
                state_path = Path(rollout.context["arc_state_path"])
                state_path.write_text("{}", encoding="utf-8")
                state_path.chmod(0o600)
                snapshots[str(state_path)] = ArcAgiSessionSnapshot(
                    game_id=game_id,
                    state=official_state,
                    levels_completed=4 if official_state == "WIN" else 1,
                    win_levels=4,
                    available_actions=(),
                    step_index=2,
                    operation="action1",
                    closed=False,
                    base_url="http://127.0.0.1:43210",
                    card_id="private-card",
                    guid="private-guid",
                )
                outcomes.append(
                    driver.collect_outcome(
                        batch, instance_uuid=instance, context=rollout.context
                    )
                )

            self.assertTrue(outcomes[0].solved)
            self.assertEqual(outcomes[0].reward, 1)
            self.assertTrue(outcomes[1].solved)
            self.assertFalse(outcomes[2].solved)
            summary = driver.finalize_batch(batch, outcomes)
            self.assertEqual(summary["newly_solved_item_ids"], [won_uuid])
            self.assertEqual(summary["already_solved_item_ids"], [])
            self.assertEqual(summary["total_solved_item_ids"], [won_uuid])
            self.assertEqual(summary["solved_count"], 1)
            self.assertEqual(current_pool_path.read_bytes(), current_pool_bytes)
            self.assertIs(driver.finalize_batch(batch, outcomes), summary)
            self.assertEqual(launcher.servers[0].terminate_calls, 1)

            state_path = root / "arc-benchmark-state.json"
            persisted = json.loads(state_path.read_text())
            self.assertEqual(persisted["schema"], "metalanguage.arc_benchmark_state")
            self.assertEqual(persisted["version"], 1)
            self.assertEqual(persisted["solved_items"], [
                {"game_id": won_game, "item_id": won_uuid}
            ])
            self.assertEqual(state_path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                state_path.with_name("arc-benchmark-state.json.lock").stat().st_mode
                & 0o777,
                0o600,
            )

            driver.close()
            resumed, resumed_launcher = self._driver(
                root, cap=None, snapshot=read_snapshot
            )
            next_batch = resumed.prepare_batch(6, root / "shared-next")
            next_pool = json.loads((root / "shared-next/problem_pool.json").read_text())
            next_uuids = {row["uuid"] for row in next_pool}
            self.assertNotIn(won_uuid, next_uuids)
            self.assertIn(partial_uuid, next_uuids)
            child_a = resumed.prepare_rollout(
                next_batch,
                backend="codex",
                context=_supervisor_context(root, "next-child-a"),
            )
            child_b = resumed.prepare_rollout(
                next_batch,
                backend="codex",
                context=_supervisor_context(root, "next-child-b"),
            )
            allowed_a = load_context(
                Path(child_a.mcp_servers["arc_agi"]["env"]["METALANGUAGE_ARC_CONTEXT"])
            ).allowed_game_ids
            allowed_b = load_context(
                Path(child_b.mcp_servers["arc_agi"]["env"]["METALANGUAGE_ARC_CONTEXT"])
            ).allowed_game_ids
            self.assertEqual(allowed_a, allowed_b)
            self.assertNotIn(won_game, allowed_a)
            self.assertFalse(Path(child_a.context["arc_state_path"]).exists())
            self.assertFalse(Path(child_b.context["arc_state_path"]).exists())
            resumed.finalize_batch(next_batch, [])
            resumed.close()
            self.assertEqual(launcher.calls, 1)
            self.assertEqual(resumed_launcher.calls, 1)
            self.assertEqual(resumed_launcher.servers[0].terminate_calls, 1)
            incompatible, incompatible_launcher = self._driver(root, cap=3)
            with self.assertRaisesRegex(RuntimeError, "state is incompatible"):
                incompatible.prepare_batch(7, root / "shared-incompatible")
            self.assertEqual(incompatible_launcher.calls, 0)
            incompatible.close()

    def test_outcomes_finalization_neutrality_and_cleanup(self) -> None:
        snapshots: dict[str, ArcAgiSessionSnapshot] = {}
        closed: list[str] = []

        def read_snapshot(path: str | Path) -> ArcAgiSessionSnapshot:
            return snapshots[str(path)]

        def close_rollout(path: str | Path) -> dict[str, object]:
            closed.append(str(path))
            if len(closed) == 1:
                raise RuntimeError("private failure")
            return {"closed": True}

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver, launcher = self._driver(
                root, snapshot=read_snapshot, closer=close_rollout
            )
            batch = driver.prepare_batch(3, root / "shared")
            pool_hash = hashlib.sha256((root / "shared/problem_pool.json").read_bytes()).hexdigest()
            context_a = _supervisor_context(root, "a")
            context_b = _supervisor_context(root, "b")
            rollout_a = driver.prepare_rollout(batch, backend="codex", context=context_a)
            rollout_b = driver.prepare_rollout(batch, backend="codex", context=context_b)

            before = driver.collect_outcome(
                batch, instance_uuid="a", context=rollout_a.context
            )
            self.assertFalse(before.attempted)
            self.assertFalse(before.solved)
            self.assertEqual(before.reward, 0)

            selected_game = load_context(
                Path(rollout_a.mcp_servers["arc_agi"]["env"]["METALANGUAGE_ARC_CONTEXT"])
            ).allowed_game_ids[0]
            selected_row = next(
                row
                for row in json.loads((root / "shared/problem_pool.json").read_text())
                if row["game_id"] == selected_game
            )
            selected_index = next(
                index
                for index, row in enumerate(
                    json.loads((root / "shared/problem_pool.json").read_text())
                )
                if row["game_id"] == selected_game
            )
            selected_ref = BenchmarkItemRef(
                selected_row["uuid"], selected_game, selected_index, 3
            )
            for rollout in (rollout_a, rollout_b):
                path = Path(rollout.context["arc_state_path"])
                path.write_text("{}", encoding="utf-8")
                path.chmod(0o600)
                snapshots[str(path)] = ArcAgiSessionSnapshot(
                    game_id=selected_game,
                    state="GAME_OVER" if rollout is rollout_a else "NOT_FINISHED",
                    levels_completed=2,
                    win_levels=4,
                    available_actions=(1, 6, 7),
                    step_index=3,
                    operation="action1",
                    closed=False,
                    base_url="http://127.0.0.1:43210",
                    card_id="private-card",
                    guid="private-guid",
                )
                for step_index in range(1, 4):
                    append_benchmark_event(
                        Path(rollout.context["benchmark_events_path"]),
                        event_type="benchmark_command_completed",
                        instance_uuid=str(rollout.context["instance_uuid"]),
                        metadata={
                            "benchmark": "arc-agi",
                            "benchmark_item": selected_ref.to_metadata(),
                            "game_id": selected_game,
                            "command": "ACTION1",
                            "step_index": step_index,
                            "state": (
                                "WIN"
                                if rollout is rollout_b and step_index == 2
                                else "NOT_FINISHED"
                            ),
                            "levels_completed": 2,
                            "win_levels": 4,
                        },
                    )

            outcome_a = driver.collect_outcome(
                batch, instance_uuid="a", context=rollout_a.context
            )
            outcome_b = driver.collect_outcome(
                batch, instance_uuid="b", context=rollout_b.context
            )
            self.assertTrue(outcome_a.attempted)
            self.assertFalse(outcome_a.solved)
            self.assertEqual(outcome_a.reward, 0)
            self.assertEqual(outcome_a.item_ref, outcome_b.item_ref)
            self.assertIsInstance(outcome_a.item_ref, BenchmarkItemRef)
            self.assertEqual(outcome_a.item_ref.source_id, selected_game)
            self.assertEqual(outcome_a.metadata["scorecard_total_actions"], 3)
            self.assertEqual(outcome_a.metadata["accounted_action_count"], 3)
            self.assertTrue(outcome_a.metadata["action_accounting_consistent"])
            self.assertEqual(outcome_a.metadata["game_total_plays"], 1)
            safe = json.dumps([outcome_a.metadata, outcome_a.run_record], sort_keys=True)
            self.assertNotIn("private-card", safe)
            self.assertNotIn("private-guid", safe)
            self.assertNotIn("must-not-leak", safe)
            self.assertFalse(outcome_a.metadata["fitness_pending"])

            path_b = Path(rollout_b.context["arc_state_path"])
            snapshots[str(path_b)] = ArcAgiSessionSnapshot(
                **{
                    **snapshots[str(path_b)].__dict__,
                    "closed": True,
                    "state": "NOT_FINISHED",
                }
            )
            closed_outcome = driver.collect_outcome(
                batch, instance_uuid="b", context=rollout_b.context
            )
            self.assertTrue(closed_outcome.metadata["closed"])
            self.assertEqual(closed_outcome.metadata["state"], "NOT_FINISHED")
            self.assertTrue(closed_outcome.metadata["official_win_observed"])
            self.assertTrue(closed_outcome.solved)
            self.assertFalse(closed_outcome.metadata["scorecard_available"])

            summary = driver.finalize_batch(batch, [outcome_a, closed_outcome])
            self.assertEqual(summary["attempted_count"], 2)
            self.assertEqual(summary["selected_item_count"], 1)
            self.assertEqual(summary["solved_count"], 1)
            self.assertEqual(summary["reward_total"], 1)
            self.assertEqual(summary["total_actions"], 3)
            self.assertEqual(summary["total_accounted_actions"], 6)
            self.assertEqual(summary["action_accounting_mismatch_count"], 1)
            self.assertEqual(
                hashlib.sha256((root / "shared/problem_pool.json").read_bytes()).hexdigest(),
                pool_hash,
            )

            driver.close()
            self.assertEqual(driver.cleanup_summary["initialized_rollout_count"], 2)
            self.assertEqual(driver.cleanup_summary["closed_rollout_count"], 1)
            self.assertEqual(driver.cleanup_summary["cleanup_errors"], ["scorecard_close_failed"])
            self.assertEqual(launcher.servers[0].terminate_calls, 1)
            driver.close()
            self.assertEqual(launcher.servers[0].terminate_calls, 1)
            with self.assertRaisesRegex(RuntimeError, "closed"):
                driver.collect_outcome(batch, instance_uuid="a", context=rollout_a.context)


class ArcAgiBenchmarkLiveTests(unittest.TestCase):
    def test_live_server_reset_action_outcome_and_close(self) -> None:
        game_id = "ls20-9607627b"
        record = {
            "uuid": arc_task_uuid(game_id),
            "game_id": game_id,
            "title": "Live fixture",
            "tags": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            driver = ArcAgiBenchmarkDriver(
                ArcAgiConfig(
                    state_path=root / "arc-benchmark-state.json",
                    problem_pool_size=1,
                    render_scale=2,
                ),
                records_loader=lambda: [record],
            )
            server = None
            try:
                batch = driver.prepare_batch(0, root / "shared")
                server = batch.private.server
                supervisor = _supervisor_context(root, "live")
                rollout = driver.prepare_rollout(
                    batch, backend="codex", context=supervisor
                )
                private_context = load_context(
                    Path(
                        rollout.mcp_servers["arc_agi"]["env"][
                            "METALANGUAGE_ARC_CONTEXT"
                        ]
                    )
                )
                service = ArcCommandService(private_context)
                reset = service.reset(game_id)
                action_id = next(
                    action
                    for action in reset.observation["available_actions"]
                    if action in {1, 2, 3, 4, 5, 7}
                )
                service.action(f"ACTION{action_id}")
                outcome = driver.collect_outcome(
                    batch, instance_uuid="live", context=rollout.context
                )
                self.assertTrue(outcome.attempted)
                self.assertEqual(outcome.item_ref.item_id, record["uuid"])
                self.assertEqual(outcome.item_ref.source_id, game_id)
                self.assertGreaterEqual(outcome.metadata["scorecard_total_actions"], 1)
                self.assertFalse(outcome.solved)
                self.assertEqual(outcome.reward, 0)
            finally:
                driver.close()
            self.assertIsNotNone(server)
            self.assertIsNotNone(driver.cleanup_summary)
            self.assertEqual(driver.cleanup_summary["cleanup_error_count"], 0)
            self.assertEqual(driver.cleanup_summary["closed_rollout_count"], 1)
            self.assertIsNotNone(server.process.poll())
            with socket.socket() as sock:
                sock.settimeout(0.5)
                self.assertNotEqual(sock.connect_ex((server.host, server.port)), 0)


if __name__ == "__main__":
    unittest.main()
