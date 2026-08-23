"""Deep-learning execution governance extending the ML adapter.

Only the immutable configuration manifest is implemented in the first Phase 6
slice.  No runner, framework integration, GPU observation, or checkpoint I/O
is claimed yet (ADR-0009).
"""

from .manifest import DLRunManifest

__all__ = ["DLRunManifest"]
