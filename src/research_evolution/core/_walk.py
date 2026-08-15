"""Shared iterative traversal for strict-JSON-shaped trees.

Both pre-validation walkers (the strict parser's post-parse checks and the
canonicalizer's input-domain check) traverse through here, so the nesting
budget is enforced as data and never consumes the interpreter call stack:
the same in-budget document is accepted at any caller recursion limit, and
an over-budget document always fails with :class:`StrictJsonError`.
"""

from __future__ import annotations

from typing import Any, Callable

from ._errors import StrictJsonError
from ._limits import MAX_WALK_DEPTH


def walk_json_tree(root: Any, visit: Callable[[Any, str, int], None]) -> None:
    """Iterative pre-order walk calling ``visit(node, path, depth)`` per node.

    ``path`` uses ``$.key`` / ``$[index]`` notation for error messages.
    A node deeper than ``MAX_WALK_DEPTH`` raises :class:`StrictJsonError`.
    Dict keys are not visited as nodes; callbacks that constrain keys
    inspect them from the dict node itself.
    """
    stack: list[tuple[Any, str, int]] = [(root, "$", 0)]
    while stack:
        node, path, depth = stack.pop()
        if depth > MAX_WALK_DEPTH:
            raise StrictJsonError("value nesting exceeds the safety limit")
        visit(node, path, depth)
        if isinstance(node, dict):
            for key, child in node.items():
                stack.append((child, f"{path}.{key}", depth + 1))
        elif isinstance(node, list):
            for index, child in enumerate(node):
                stack.append((child, f"{path}[{index}]", depth + 1))
