"""Deep-learning execution governance extending the ML adapter.

The immutable configuration manifest is the package-level interface.  Phase 6
L2 also provides an explicit ``deep_learning.runner`` submodule for dry-run and
tiny synthetic CPU-fixture protocol checks.  No framework integration, GPU
observation, or checkpoint I/O is claimed (ADR-0009).
"""

from .manifest import DLRunManifest

__all__ = ["DLRunManifest"]
