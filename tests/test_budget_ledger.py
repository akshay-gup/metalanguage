from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from utils.budget_ledger import append_budget_event, budget_projection_path, read_budget_status


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


class BudgetLedgerPermissionsTests(unittest.TestCase):
    def test_creation_is_private_independent_of_umask(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "logs" / "budget_ledger.jsonl"
            previous = os.umask(0o002)
            try:
                append_budget_event(
                    events,
                    event_type="instance_created",
                    instance_uuid="fixture",
                    metadata={"rollout_token_budget_tokens": 100},
                )
            finally:
                os.umask(previous)

            self.assertEqual(_mode(events), 0o600)
            self.assertEqual(_mode(events.with_suffix(".jsonl.lock")), 0o600)
            self.assertEqual(_mode(budget_projection_path(events)), 0o600)
            self.assertEqual(read_budget_status(events, "fixture")["tokens_remaining"], 100)

    def test_existing_group_writable_files_are_hardened_on_read_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "budget_ledger.jsonl"
            lock = events.with_suffix(".jsonl.lock")
            projection = budget_projection_path(events)
            events.write_text(
                json.dumps(
                    {
                        "event_type": "instance_created",
                        "instance_uuid": "fixture",
                        "amount_tokens": 0,
                        "metadata": {"rollout_token_budget_tokens": 50},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            lock.touch()
            projection.write_text("{}\n", encoding="utf-8")
            for path in (events, lock, projection):
                path.chmod(0o664)

            self.assertEqual(read_budget_status(events, "fixture")["tokens_remaining"], 50)
            for path in (events, lock, projection):
                self.assertEqual(_mode(path), 0o600)

            for path in (events, lock, projection):
                path.chmod(0o664)
            append_budget_event(
                events,
                event_type="token_usage",
                instance_uuid="fixture",
                amount_tokens=5,
                metadata={"submitted_answer": "private fixture"},
            )
            for path in (events, lock, projection):
                self.assertEqual(_mode(path), 0o600)
            self.assertIn("private fixture", events.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
