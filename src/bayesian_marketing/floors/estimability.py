"""§6.1 rate basis (D10) and decision basis (D9).

Every threshold comes from ``bounds.yaml`` through ``core.registries`` (C1, I6). The research
section of ``bounds.yaml`` is never read here (C3, D1).
"""

from __future__ import annotations

from bayesian_marketing.core import (
    ClientEconomics,
    Comparison,
    Feasibility,
    PrecisionTarget,
    Quantity,
    registries,
    utcnow,
)
from bayesian_marketing.core.scope import STATUS_ORDER

RATE_KEY = "bounds/estimability/posterior_width"
DECISION_KEY = "bounds/estimability/decision_loss"

SIGNED_QUANTITIES: frozenset[str] = frozenset({"contribution", "contribution_per_click", "lift"})
"""Signed money quantities carry no precision status of their own (D10): basis 'inherited'."""

REGIME_NOTICE_KEYS: tuple[str, ...] = ("lag_approx", "too_few_ads", "joint_failed")  # D26
"""phrasing.yaml notices for the §6.1 regime mismatches "lag-adjusted approximation" and "funnel
link not estimated". Each downgrades the status one level. "Attribution change in window" has no
phrasing key yet (open question in spec/manifests/P4.md)."""

NO_TOLERANCE_REASON = "no loss tolerance set"  # D16, verbatim

_QUANTILES = {0.90: ("q05", "q95"), 0.95: ("q025", "q975")}
_BY_RANK = {v: k for k, v in STATUS_ORDER.items()}


def _ref(key: str) -> str:
    version = registries.load("bounds")["version"]
    ref = f"{key}@{version}"
    registries.resolve(ref)  # C1: the bound must exist
    return ref


def _regime_notices() -> dict[str, str]:
    """Notice text -> reason for each regime-mismatch notice in the phrasing registry."""
    notices = registries.load("phrasing")["notices"]
    return {
        notices[k]: f"regime mismatch: {notices[k]}" for k in REGIME_NOTICE_KEYS if k in notices
    }


def _downgrade(status: str, steps: int) -> str:
    return _BY_RANK[max(0, STATUS_ORDER[status] - steps)]


def registry_target() -> PrecisionTarget:
    """The rate target as the registry states it (C1)."""
    pw = registries.resolve(_ref(RATE_KEY))
    return PrecisionTarget(
        rel_half_width=float(pw["rel_half_width"]),
        level=float(pw["level"]),
        caveat_rel_half_width=float(pw["caveat_rel_half_width"]),
    )


def quantity_feasibility(q: Quantity, target: PrecisionTarget) -> Feasibility:
    """Rate basis (D10): w = (q_hi - q_lo) / (2 * q50) at the registry's level.

    Thresholds come from the registry (C1). A ``target`` that differs from the registry is refused
    rather than reported under the registry's bound_ref.
    """
    if q.name in SIGNED_QUANTITIES:
        # D10: a signed quantity's status is the worst of its inputs, set where it is derived.
        return q.feasibility.model_copy(update={"basis": "inherited"})

    reg = registry_target()
    if target != reg:
        raise ValueError(f"precision target {target} differs from the registry's {reg}")
    if reg.level not in _QUANTILES:
        raise ValueError(f"precision level {reg.level} unsupported; summary carries 0.90, 0.95")
    lo_key, hi_key = _QUANTILES[reg.level]
    s = q.estimate.summary
    q50 = s["q50"]
    edge, caveat = reg.rel_half_width, reg.caveat_rel_half_width
    reasons: list[str] = []

    if q50 <= 0:
        w = float("inf")
        width_status = "below_floor"
        reasons.append("median is not positive, so the relative half-width is undefined")
    else:
        w = (s[hi_key] - s[lo_key]) / (2.0 * q50)
        if w <= edge:
            width_status = "estimable"
        elif w <= caveat:
            width_status = "marginal"
            reasons.append(
                f"{reg.level:.0%} relative half-width {w:.4f} exceeds {edge:g} "
                f"(within caveat edge {caveat:g})"
            )
        else:
            width_status = "below_floor"
            reasons.append(
                f"{reg.level:.0%} relative half-width {w:.4f} exceeds caveat edge {caveat:g}"
            )

    regime = _regime_notices()
    mismatches = [regime[n] for n in q.notices if n in regime]
    status = _downgrade(width_status, len(mismatches))
    reasons.extend(mismatches)

    # available and required are both event counts (D22 item 5). Feasibility.available is a
    # float in core, so an unknown count is recorded as 0.0 with a reason (open question).
    required: float | None = None
    if q.n_events is None:
        available = 0.0
        if status != "estimable":
            reasons.append("event count unknown: available recorded as 0, required not projected")
    else:
        available = float(q.n_events)
        if width_status != "estimable" and w != float("inf") and available > 0:
            required = available * (w / edge) ** 2
            reasons.append(
                f"approximate: about {required:.0f} events needed for width {edge:g} "
                "(projected from w proportional to n^-1/2)"
            )
        elif status != "estimable":
            reasons.append(
                "required events not projected: the width meets the target, the status is "
                "limited by a regime mismatch"
                if width_status == "estimable"
                else "required events not projected: no positive event count or width"
            )

    return Feasibility(
        status=status,
        basis="quantity_precision",
        bound_ref=_ref(RATE_KEY),
        available=available,
        required=required,
        target=edge,
        reasons=reasons,
        checked_at=utcnow(),
    )


def decision_feasibility(c: Comparison, econ: ClientEconomics) -> Feasibility:
    """Decision basis (D9): L, the expected loss of the best option against the loss tolerance.

    Rate statuses are not consulted (D9 C2). With no tolerance the decision is below floor with
    the reason "no loss tolerance set" (D16); G9 itself belongs to compare.
    """
    if c.economics_id != econ.economics_id:
        raise ValueError(
            f"comparison uses economics {c.economics_id!r}, given {econ.economics_id!r}"
        )
    if not c.expected_loss:
        raise ValueError("comparison has no expected losses")
    best = min(c.expected_loss, key=lambda o: c.expected_loss[o].amount)
    loss = c.expected_loss[best]
    bound_ref = _ref(DECISION_KEY)
    multiplier = float(registries.resolve(bound_ref)["marginal_multiplier"])
    loss_amt = float(loss.amount)

    tol_money = econ.loss_tolerance
    if tol_money is None:
        return Feasibility(
            status="below_floor",
            basis="decision_loss",
            bound_ref=bound_ref,
            available=loss_amt,
            required=None,
            target=0.0,
            reasons=[NO_TOLERANCE_REASON],
            checked_at=utcnow(),
        )
    if tol_money.currency != loss.currency:
        raise ValueError(f"expected loss in {loss.currency}, tolerance in {tol_money.currency}")
    tol = float(tol_money.amount)

    reasons: list[str] = []
    if loss_amt <= tol:
        status = "estimable"
    elif loss_amt <= multiplier * tol:
        status = "marginal"
        reasons.append(
            f"expected loss {loss_amt:g} of {best} exceeds tolerance {tol:g} "
            f"(within {multiplier:g} x tolerance)"
        )
    else:
        status = "below_floor"
        reasons.append(
            f"expected loss {loss_amt:g} of {best} exceeds {multiplier:g} x tolerance {tol:g}"
        )
    if status != "estimable":
        reasons.append("additional volume to reach tolerance not projected from a Comparison")

    return Feasibility(
        status=status,
        basis="decision_loss",
        bound_ref=bound_ref,
        available=loss_amt,
        required=None,
        target=tol,
        reasons=reasons,
        checked_at=utcnow(),
    )
