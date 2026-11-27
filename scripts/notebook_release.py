"""Verify an account notebook release (spec/notebook_format.md).

    python -I scripts/notebook_release.py verify notebook/<client_id>/releases/<release_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bayesian_marketing.notebook.release import source, verify, write_release

__all__ = ["source", "verify", "write_release"]

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "verify":
        sys.exit(__doc__)
    print(verify(Path(sys.argv[2])))
