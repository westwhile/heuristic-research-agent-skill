"""``python -m research_evolution``: the read-only CLI (ADR-0004)."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
