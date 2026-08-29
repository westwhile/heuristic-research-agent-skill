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
    marker_root.mkdir(parents=True, exist_ok=True)
    (marker_root / f"depth-{depth}.pid").write_text(str(os.getpid()), encoding="ascii")
    if depth > 0:
        subprocess.Popen(
            [sys.executable, __file__, str(marker_root), str(depth - 1)],
            stdin=subprocess.DEVNULL,
        )
    time.sleep(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
