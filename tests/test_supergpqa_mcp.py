from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from utils.budget_ledger import append_budget_event
from utils.codex_runner import supergpqa_mcp_server_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTEXT_ENV = "METALANGUAGE_SUPERGPQA_CONTEXT"


def _fixture(root: Path, name: str, expected_answer: str = "B") -> tuple[Path, Path]:
    private_path = root / f"{name}-private.json"
    private_path.write_text(
        json.dumps(
            {
                "id": f"task-{name}",
                "answer": expected_answer,
                "answer_letter": expected_answer,
                "options": ["alpha", "beta", "gamma"],
            }
        ),
        encoding="utf-8",
    )
    ledger_path = root / f"{name}-ledger.jsonl"
    instance_uuid = f"instance-{name}"
    append_budget_event(
        ledger_path,
        event_type="instance_created",
        instance_uuid=instance_uuid,
        metadata={"rollout_token_budget_tokens": 100},
    )
    context_path = root / f"{name}-context.json"
    context_path.write_text(
        json.dumps(
            {
                "instance_uuid": instance_uuid,
                "budget_ledger_events": str(ledger_path),
                "solve_reward_token_credit_tokens": 50,
                "generation": 0,
                "seed": 42,
                "task_index": 0,
                "rollout_index": 0,
                "rollout_username": name,
                "problem_pool_records": [
                    {
                        "task_index": 0,
                        "task_id": f"task-{name}",
                        "problem_uid": f"problem-{name}",
                        "task_markdown": f"Question for {name}",
                        "private_problem_path": str(private_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return context_path, ledger_path


def _server_parameters(context_path: Path) -> StdioServerParameters:
    env = os.environ.copy()
    env[CONTEXT_ENV] = str(context_path)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "utils.supergpqa_mcp"],
        cwd=str(PROJECT_ROOT),
        env=env,
    )


def _result_payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    for content in result.content:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload
    raise AssertionError("MCP result contained no JSON object")


class SuperGpqaMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocol_scoring_duplicate_credit_and_secrecy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_path, ledger_path = _fixture(root, "one")
            async with stdio_client(_server_parameters(context_path)) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual([tool.name for tool in tools.tools], ["submit_solution"])
                    schema_text = json.dumps(tools.tools[0].inputSchema, sort_keys=True)
                    self.assertNotIn(str(context_path), schema_text)
                    self.assertNotIn("one-private", schema_text)

                    incorrect = _result_payload(
                        await session.call_tool(
                            "submit_solution", {"uuid": "problem-one", "answer": "A"}
                        )
                    )
                    correct = _result_payload(
                        await session.call_tool(
                            "submit_solution", {"uuid": "problem-one", "answer": "B"}
                        )
                    )
                    duplicate = _result_payload(
                        await session.call_tool(
                            "submit_solution", {"uuid": "problem-one", "answer": "B"}
                        )
                    )

            self.assertFalse(incorrect["correct"])
            self.assertEqual(incorrect["credited_tokens"], 0)
            self.assertTrue(correct["correct"])
            self.assertEqual(correct["credited_tokens"], 50)
            self.assertTrue(correct["reward_credit_claimed"])
            self.assertEqual(correct["budget_status"]["tokens_transferred_in"], 50)
            self.assertTrue(duplicate["correct"])
            self.assertEqual(duplicate["credited_tokens"], 0)
            self.assertFalse(duplicate["reward_credit_claimed"])
            self.assertEqual(duplicate["total_credited_tokens"], 50)
            public_text = json.dumps([incorrect, correct, duplicate], sort_keys=True)
            self.assertNotIn(str(context_path), public_text)
            self.assertNotIn(str(root / "one-private.json"), public_text)
            events = [json.loads(line) for line in ledger_path.read_text().splitlines()]
            self.assertEqual(
                sum(event["event_type"] == "solution_scored" for event in events), 3
            )
            self.assertEqual(
                sum(event["event_type"] == "solve_reward_credit" for event in events), 1
            )

    async def test_two_server_processes_keep_contexts_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            context_a, ledger_a = _fixture(root, "a", "B")
            context_b, ledger_b = _fixture(root, "b", "C")
            async with stdio_client(_server_parameters(context_a)) as streams_a:
                async with ClientSession(*streams_a) as session_a:
                    await session_a.initialize()
                    result_a = _result_payload(
                        await session_a.call_tool(
                            "submit_solution", {"uuid": "problem-a", "answer": "B"}
                        )
                    )
            async with stdio_client(_server_parameters(context_b)) as streams_b:
                async with ClientSession(*streams_b) as session_b:
                    await session_b.initialize()
                    result_b = _result_payload(
                        await session_b.call_tool(
                            "submit_solution", {"uuid": "problem-b", "answer": "B"}
                        )
                    )
            self.assertTrue(result_a["correct"])
            self.assertFalse(result_b["correct"])
            self.assertIn("problem-a", ledger_a.read_text())
            self.assertNotIn("problem-b", ledger_a.read_text())
            self.assertIn("problem-b", ledger_b.read_text())
            self.assertNotIn("problem-a", ledger_b.read_text())

    def test_runner_config_is_private_required_and_per_rollout(self) -> None:
        context = Path("/private/rollout/context.json")
        config = supergpqa_mcp_server_config(context)
        self.assertEqual(set(config), {"supergpqa"})
        server = config["supergpqa"]
        self.assertTrue(server["required"])
        self.assertEqual(server["enabled_tools"], ["submit_solution"])
        self.assertEqual(server["default_tools_approval_mode"], "approve")
        self.assertEqual(server["args"], ["-m", "utils.supergpqa_mcp"])
        self.assertNotIn(str(context), server["args"])
        self.assertEqual(
            server["env"][CONTEXT_ENV], str(context.resolve())
        )

    def test_missing_context_fails_startup_without_leaking_environment(self) -> None:
        env = os.environ.copy()
        env.pop(CONTEXT_ENV, None)
        result = subprocess.run(
            [sys.executable, "-m", "utils.supergpqa_mcp"],
            cwd=PROJECT_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("ARC_API_KEY", result.stderr)


if __name__ == "__main__":
    unittest.main()
