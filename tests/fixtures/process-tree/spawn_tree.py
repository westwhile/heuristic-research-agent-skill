"""Spawn a bounded inherited-handle process tree for containment tests."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    marker_root = Path(sys.argv[1])
    depth = int(sys.argv[2])
    mode = sys.argv[3] if len(sys.argv) > 3 else "tree"
    marker_root.mkdir(parents=True, exist_ok=True)
    (marker_root / f"depth-{depth}.pid").write_text(str(os.getpid()), encoding="ascii")
    if mode in {"orphan-parent", "orphan-inherited"}:
        if depth != 1:
            raise ValueError("orphan-parent fixture requires depth 1")
        child_marker = marker_root / "depth-0.pid"
        subprocess.Popen(
            [sys.executable, __file__, str(marker_root), "0", "orphan-child"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL if mode == "orphan-parent" else None,
            stderr=subprocess.DEVNULL if mode == "orphan-parent" else None,
        )
        deadline = time.monotonic() + 5
        while not child_marker.is_file():
            if time.monotonic() >= deadline:
                raise RuntimeError("orphan child did not publish its PID")
            time.sleep(0.01)
        return 0
    if depth > 0:
        subprocess.Popen(
            [sys.executable, __file__, str(marker_root), str(depth - 1)],
            stdin=subprocess.DEVNULL,
        )
    time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
