"""Deep-learning execution governance extending the ML adapter.

The immutable configuration manifest is the package-level interface.  Phase 6
L2-L4 also provide explicit ``deep_learning.runner``,
``deep_learning.selection``, and ``deep_learning.studies`` submodules for tiny
synthetic CPU-fixture execution, checkpoint/recovery, multi-seed selection,
and resource-fair descriptive reports.  No framework integration, GPU
observation, or external checkpoint-store I/O is claimed (ADR-0009).
"""

from .manifest import DLRunManifest

__all__ = ["DLRunManifest"]
