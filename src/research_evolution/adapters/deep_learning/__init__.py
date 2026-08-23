"""Deep-learning execution governance extending the ML adapter.

The immutable configuration manifest is the package-level interface.  Phase 6
L2/L3 also provide explicit ``deep_learning.runner`` and
``deep_learning.selection`` submodules for tiny synthetic CPU-fixture,
checkpoint/recovery, and multi-seed protocol checks.  No framework integration,
GPU observation, or external checkpoint-store I/O is claimed (ADR-0009).
"""

from .manifest import DLRunManifest

__all__ = ["DLRunManifest"]
