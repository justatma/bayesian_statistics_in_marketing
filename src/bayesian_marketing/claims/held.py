"""The held status (Brain join J7, S39): a quantity's status damped so that a drop shows at once
and a rise shows only once it has held for a full account-local day. A pure function of a run and
the client's earlier runs; never stored."""

from __future__ import annotations

ORDER = ("below_floor", "marginal", "estimable")
"""S39 (J7 (1)): less certain first."""

HeldKey = tuple[str, str, str, str, str]
"""S39 (4): (level, subject id, quantity name, conversion kind, metric). The decision status uses
("decision", "", "", conversion kind, metric)."""

HELD_REASON = "held at {held} until {raw} has held for a day"
"""S39 (8): added to a posterior entry's ``status_reasons`` when held is below raw."""


def held_status(run_id: str, *, timezone: str | None = None) -> dict[HeldKey, str]:
    """S39: the held status of every quantity present in ``run_id``, and of its decision.
    Raises when the zone can't be found, two zones are found, the run record can't be read, or a
    run file in the series can't be read (S39 (6), (7))."""
    raise NotImplementedError
