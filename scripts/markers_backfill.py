"""Write the hand-off markers a run or a release is missing (Brain join J3, S35).

    BAYES_DATA_DIR=... python -I scripts/markers_backfill.py

Idempotent: a second run writes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bayesian_marketing.live import markers


def main() -> int:
    counts = markers.backfill()
    for kind, n in counts.items():
        print(f"{kind}: {n} written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
