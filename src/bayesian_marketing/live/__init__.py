"""The live view (spec/Live_View_Specification_v0.2.md, D41 to D43).

An hourly read of each client's Meta account into an append-only SQLite store (``store``,
``poll``, ``prune``), an engine refresh after each good poll (``refresh``), and an internal page
rendered from the store on each request and served on the loopback address (``view``, ``serve``).
Reads and shows; never writes to an ad platform. Only ``cli.py`` imports this package.
"""

from bayesian_marketing.live.contracts import (
    Clock,
    LiveRow,
    PollRecord,
    RefreshRecord,
    Store,
    SystemClock,
)
from bayesian_marketing.live.registry import LiveRegistry, load_live_registry

__all__ = [
    "Clock",
    "LiveRegistry",
    "LiveRow",
    "PollRecord",
    "RefreshRecord",
    "Store",
    "SystemClock",
    "load_live_registry",
]
