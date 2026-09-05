"""Shared Codex event semantics through both consumer interfaces; no model calls."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_evolution.evaluation import Envelope
from research_evolution.evolution import AgentForwardExecutionRequest, CodexCliAgentAdapter
from research_evolution.evolution._codex_jsonl import parse_codex_trace
from research_evolution.evolution._process_containment import ContainedProcessResult
from research_evolution.evolution.collaboration_window import run_collaboration_window
from tests.unit import test_collaboration_window as collaboration_tests


START = b'{"type":"thread.started","thread_id":"private-fixture-session"}\n'
DONE = b'{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":8}}\n'


def _completed(trace: bytes) -> ContainedProcessResult:
    return ContainedProcessResult(0, trace, b"private-fixture-stderr", True,
                                  "completed", "not_required", True)


def _agent(trace: bytes):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        launcher = root / "codex-cli.ps1"
        launcher.write_text("# deterministic mock only", encoding="utf-8")
        final = root / "final.json"
        final.write_text('{"answer":42}', encoding="utf-8")
        request = AgentForwardExecutionRequest(
            trial_id="event-contract", arm="baseline", workspace=root,
            prompt="synthetic", output_schema_path=root / "schema.json",
            final_output_path=final, skill_name="fixture", skill_md_sha256="a" * 64,
            candidate_bundle_sha256="b" * 64, axes_sha256="c" * 64,
        )
        adapter = CodexCliAgentAdapter(
            launcher, powershell=Path(sys.executable), cli_version="fixture",
            model="fixture", reasoning_effort="xhigh",
        )
        with patch("research_evolution.evolution.agent_forward_trial.run_process_contained",
                   return_value=_completed(trace)):
            return adapter.execute(request, Envelope(timeout_ms=1000, max_output_bytes=1024))


def _collaboration(trace: bytes):
    adapter = collaboration_tests.CollaborationWindowTests()._process_adapter("deterministic-fake-model")

    def fake_run(command, **kwargs):
        root = kwargs["cwd"]
        ticket = json.loads((root / "collaboration-request.json").read_text(encoding="utf-8"))
        # The same contract applies to the first ticket; rejection must stop later dispatch.
        output = {
            "route_id": ticket["route_id"], "role": ticket["role"], "status": "bounded_negative",
            "work_product": {"approach": "Synthetic", "result": "Bounded", "verification": "Checked"},
            "substantive_method_changes": [], "opportunity_chain": [],
            "future_route_proposal": {"present": False, "proposed_target": "", "reason": "",
                                      "evidence_sha256": ""},
            "cannot_imply": ["No research claim"], "reopen_conditions": ["New evidence"],
        }
        (root / "worker-output.json").write_text(json.dumps(output), encoding="utf-8")
        return _completed(trace)

    with patch("research_evolution.evolution.collaboration_window.run_process_contained",
               side_effect=fake_run):
        return run_collaboration_window(collaboration_tests._plan(), adapter)


class CodexEventConsumerTest(unittest.TestCase):
    def test_malformed_or_contradictory_trace_never_becomes_success(self) -> None:
        for suffix in (
            b'{"type":"turn.failed","error":{"message":"private-fixture-error"}}\n',
            b'{"type":', b'[]\n', DONE,
            b'{"type":"turn.started"}\n',
            b'{"type":"metadata","type":"ignored"}\n',
        ):
            with self.subTest(suffix=suffix):
                trace = START + DONE + suffix
                observed = _agent(trace)
                self.assertFalse(observed.replay.ok)
                self.assertFalse(observed.agent_turn_completed)
                self.assertTrue(observed.launcher_process_started)
                self.assertTrue(observed.process_tree_cleanup_verified)
                self.assertNotIn("private-fixture-error", str(observed))
                outcome = _collaboration(trace)
                self.assertEqual(outcome.status, "failed_closed")
                self.assertEqual(len(outcome.worker_outcomes), 1)
                record = outcome.worker_outcomes[0]
                self.assertFalse(record.data["execution"]["agent_turn_completed"])
                self.assertTrue(record.data["execution"]["workspace_cleanup_verified"])
                self.assertNotIn(b"private-fixture", record.canonical_bytes)

    def test_normal_extension_event_remains_compatible(self) -> None:
        trace = START + b'{"type":"metadata","future_field":{"x":1}}\n' + DONE
        self.assertTrue(_agent(trace).replay.ok)
        self.assertEqual(_collaboration(trace).status, "window_completed")


class CodexTraceContractTest(unittest.TestCase):
    def parse(self, trace: bytes):
        return parse_codex_trace(trace, max_bytes=4 << 20)

    def test_required_event_deletion_and_identity_mutation(self) -> None:
        for trace, code in (
            (b"", "session_or_turn_incomplete"),
            (START, "session_or_turn_incomplete"),
            (DONE, "session_or_turn_incomplete"),
            (START + START + DONE, "session_conflict"),
            (b'{"type":"thread.started","thread_id":" "}\n', "invalid_session_identity"),
            (START + b'{"type":"turn.future_terminal"}\n', "unknown_critical_event"),
            (START + b'{"type":"turn.failed","message":"private-error"}\n', "turn_failed"),
            (START + b'{"type":"error","message":"private-error"}\n', "codex_error"),
        ):
            with self.subTest(code=code, trace=trace):
                facts = self.parse(trace)
                self.assertEqual(facts.error_code, code)
                self.assertFalse(facts.turn_completed)
                self.assertEqual(facts.usage, {})
                self.assertNotIn("private-error", str(facts))

    def test_usage_closes_only_nonoverlapping_integer_counters(self) -> None:
        good = {"input_tokens": 12, "output_tokens": 8, "cached_input_tokens": 10,
                "total_tokens": 20, "reasoning_output_tokens": 3}
        facts = self.parse(START + json.dumps({"type": "turn.completed", "usage": good}).encode())
        self.assertTrue(facts.turn_completed)
        self.assertEqual(facts.usage["total_tokens"], 20)
        self.assertNotIn("reasoning_output_tokens", facts.usage)
        for usage in (None, {}, {"input_tokens": 12},
                      {**good, "input_tokens": True}, {**good, "output_tokens": -1},
                      {**good, "cached_input_tokens": 13}, {**good, "total_tokens": 30},
                      {**good, "output_tokens": 8.0}):
            with self.subTest(usage=usage):
                trace = START + json.dumps({"type": "turn.completed", "usage": usage}).encode()
                facts = self.parse(trace)
                self.assertEqual(facts.error_code, "usage_incomplete_or_inconsistent")
                self.assertEqual(facts.usage, {})

    def test_strict_json_and_explicit_resource_bounds(self) -> None:
        for trace in (b'\xff', b'[]', b'{"type":"a","type":"b"}',
                      b'{"type":"metadata","x":NaN}', b'{"type":', b'null'):
            with self.subTest(trace=trace):
                self.assertEqual(self.parse(trace).error_code, "invalid_jsonl_event")
        trace = START + DONE
        self.assertIsNone(parse_codex_trace(trace, max_bytes=len(trace)).error_code)
        self.assertEqual(parse_codex_trace(trace, max_bytes=len(trace) - 1).error_code,
                         "trace_limit_exceeded")
        self.assertEqual(self.parse(b" " * ((1 << 20) + 1)).error_code,
                         "trace_line_limit_exceeded")
        self.assertEqual(self.parse(b"\n" * 10_001).error_code, "trace_event_limit_exceeded")
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                parse_codex_trace(trace, max_bytes=limit)

    def test_tool_lifecycle_is_counted_once_and_terminal_is_last_critical_event(self) -> None:
        item = {"id": "synthetic-tool", "type": "command_execution"}
        events = b"".join(json.dumps({"type": kind, "item": item}).encode() + b"\n"
                          for kind in ("item.started", "item.updated", "item.completed"))
        facts = self.parse(START + events + DONE)
        self.assertTrue(facts.turn_completed)
        self.assertEqual(facts.tool_calls, 1)
        end = json.dumps({"type": "item.completed", "item": item}).encode() + b"\n"
        self.assertEqual(self.parse(START + events + end + DONE).error_code,
                         "duplicate_tool_completion")
        self.assertEqual(self.parse(START + DONE + end).error_code, "invalid_event_order")
        self.assertEqual(self.parse(START + b'{"type":"item.completed"}\n' + DONE).error_code,
                         "invalid_item_event")


if __name__ == "__main__":
    unittest.main()
