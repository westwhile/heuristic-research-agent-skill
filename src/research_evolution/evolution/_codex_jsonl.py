"""Bounded, single-turn Codex facts shared by local-process consumers.

This is a repository acceptance policy, not a claim that all future CLI event
versions share this grammar. Unknown non-critical events remain compatible.
Raw event text and parser exceptions never become diagnostic messages.
"""

from __future__ import annotations

from dataclasses import dataclass

from research_evolution.core import CoreError, load_strict_json

_MAX_LINE_BYTES = 1 << 20
_MAX_EVENTS = 10_000
_USAGE_FIELDS = frozenset({"input_tokens", "output_tokens", "cached_input_tokens", "total_tokens"})
_TOOL_TYPES = frozenset({"command_execution", "mcp_tool_call", "web_search"})


@dataclass(frozen=True)
class CodexTraceFacts:
    """Only trusted session identity, completion, counters and a stable code."""

    session_id: str | None
    turn_completed: bool
    usage: dict[str, int]
    tool_calls: int
    error_code: str | None


def parse_codex_trace(trace: bytes, *, max_bytes: int) -> CodexTraceFacts:
    """Validate a bounded single-thread/single-turn trace without external I/O.

    Completion requires one session, one completed terminal, no conflicting or
    malformed events, and non-overlapping input/output usage. turn.started is
    optional for compatibility with existing minimal traces, but cannot repeat.
    Core supplies strict UTF-8/object/duplicate-key/nesting/numeric validation.
    """

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    if not isinstance(trace, bytes):
        raise TypeError("trace must be bytes")
    session: str | None = None
    completed = False
    turn_started = False
    usage: dict[str, int] = {}
    tools: set[str] = set()

    def rejected(code: str) -> CodexTraceFacts:
        # Conflicting/truncated traces cannot close resource accounting.
        return CodexTraceFacts(session, False, {}, len(tools), code)

    if len(trace) > max_bytes:
        return rejected("trace_limit_exceeded")
    offset = 0
    events = 0
    while offset < len(trace):
        end = trace.find(b"\n", offset)
        if end < 0:
            end = len(trace)
        if end - offset > _MAX_LINE_BYTES:
            return rejected("trace_line_limit_exceeded")
        raw = trace[offset:end]
        offset = end + 1
        events += 1
        if events > _MAX_EVENTS:
            return rejected("trace_event_limit_exceeded")
        if not raw.strip():
            continue
        try:
            event = load_strict_json(raw)
        except CoreError:
            return rejected("invalid_jsonl_event")
        kind = event.get("type")
        if not isinstance(kind, str) or not kind or len(kind) > 128:
            return rejected("invalid_event_type")
        if kind == "thread.started":
            thread = event.get("thread_id")
            if session is not None or completed or turn_started:
                return rejected("session_conflict")
            if not isinstance(thread, str) or not thread.strip() or len(thread) > 256:
                return rejected("invalid_session_identity")
            session = thread.strip()
        elif kind == "turn.started":
            if completed or turn_started:
                return rejected("terminal_conflict")
            if session is None:
                return rejected("session_or_turn_incomplete")
            turn_started = True
        elif kind in {"turn.failed", "error"}:
            return rejected("terminal_conflict" if completed else
                            "turn_failed" if kind == "turn.failed" else "codex_error")
        elif kind == "turn.completed":
            if completed:
                return rejected("terminal_conflict")
            if session is None:
                return rejected("session_or_turn_incomplete")
            raw_usage = event.get("usage")
            if not isinstance(raw_usage, dict):
                return rejected("usage_incomplete_or_inconsistent")
            for key in _USAGE_FIELDS & raw_usage.keys():
                value = raw_usage[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    return rejected("usage_incomplete_or_inconsistent")
                usage[key] = value
            if not {"input_tokens", "output_tokens"}.issubset(usage):
                return rejected("usage_incomplete_or_inconsistent")
            total = usage["input_tokens"] + usage["output_tokens"]
            if (usage.get("total_tokens", total) != total or
                    usage.get("cached_input_tokens", 0) > usage["input_tokens"]):
                return rejected("usage_incomplete_or_inconsistent")
            completed = True
        elif kind.startswith(("thread.", "turn.")):
            return rejected("unknown_critical_event")
        elif kind in {"item.started", "item.updated", "item.completed"}:
            if completed or session is None:
                return rejected("invalid_event_order")
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                return rejected("invalid_item_event")
            if kind == "item.completed" and item["type"] in _TOOL_TYPES:
                identity = item.get("id")
                if not isinstance(identity, str) or not identity or len(identity) > 256:
                    return rejected("invalid_tool_event")
                if identity in tools:
                    return rejected("duplicate_tool_completion")
                tools.add(identity)
    if session is None or not completed:
        return rejected("session_or_turn_incomplete")
    return CodexTraceFacts(session, True, usage, len(tools), None)
