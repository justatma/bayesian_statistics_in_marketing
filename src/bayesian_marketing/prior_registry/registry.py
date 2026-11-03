"""§5.3 prior registry functions.

Store: ``<BAYES_DATA_DIR>/priors/records/<prior_id>.json`` holds each record's current form
(pending, then approved), and ``<BAYES_DATA_DIR>/priors/events.jsonl`` is an append-only log of
propose, approve, refuse and import events, whose order decides which proposal is latest.

A client prior names its client in ``resolution_path[0]`` as ``client:<id>``; an imported vertical
prior is stored with ``vertical:<promotion_id>`` there. ``resolve`` walks client, then vertical,
then default and records every hop:

- client: the latest proposal for (client, path). Unapproved (pending or refused) raises G8.
- vertical: no client-to-vertical mapping exists in core or the registries yet (open question),
  so this hop is recorded as unmapped and skipped. Imported vertical priors are stored and kept.
- default: ``registries/priors/default.yaml``. ``records`` are approved by the file's elicitation
  (C7); ``pending_records`` (D22) come back unapproved, and the fit refuses them on client data
  (G8, D23 item 2 allows them on synthetic data).

``approve`` runs the prior predictive check (C6): for a path with a plausibility ceiling
(``bounds/plausibility/ceiling_q99``, keyed by the last segment of the path), the prior must be a
Beta and its 99th percentile, computed exactly from the Beta quantile function rather than from
draws, must not exceed the ceiling. A path without a ceiling records the prior's quantiles and
passes.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scipy import stats

from bayesian_marketing.core import (
    ElicitationRecord,
    GateFailure,
    GateResult,
    PriorRecord,
    inputs_hash,
    make_id,
    registries,
    utcnow,
)
from bayesian_marketing.core.registries import RegistryError

DEFAULT_DATA_DIR = "data/generated"
Q99 = 0.99  # the percentile named by bounds/plausibility/ceiling_q99
CLIENT_PREFIX = "client:"
VERTICAL_PREFIX = "vertical:"


class PriorRefused(ValueError):
    """approve refused a prior: its predictive check failed (C6)."""


# --- store -----------------------------------------------------------------------------------


def _root() -> Path:
    return Path(os.environ.get("BAYES_DATA_DIR", DEFAULT_DATA_DIR)) / "priors"


def _record_path(prior_id: str) -> Path:
    if not prior_id.startswith("pr_") or "/" in prior_id or "\\" in prior_id:
        raise ValueError(f"bad prior_id {prior_id!r}")
    return _root() / "records" / f"{prior_id}.json"


def _write_record(rec: PriorRecord) -> None:
    path = _record_path(rec.prior_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(rec.model_dump_json())
    os.replace(tmp, path)


def _read_record(prior_id: str) -> PriorRecord:
    path = _record_path(prior_id)
    if not path.exists():
        raise KeyError(f"no prior {prior_id!r} under {_root()}")
    return PriorRecord.model_validate_json(path.read_text())


def _log(event: str, prior_id: str, **extra: Any) -> None:
    path = _root() / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"event": event, "prior_id": prior_id, "at": utcnow().isoformat(), **extra}
    with path.open("a") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def _events() -> list[dict[str, Any]]:
    path = _root() / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def _rebuild(rec: PriorRecord, **update: Any) -> PriorRecord:
    """A validated copy (model_copy skips validation)."""
    return PriorRecord.model_validate({**rec.model_dump(), **update})


# --- ids -------------------------------------------------------------------------------------


def _content_id(rec: PriorRecord, owner: str) -> str:
    payload = {
        "path": rec.parameter_path,
        "family": rec.family,
        "params": rec.params,
        "owner": owner,
        "version": rec.version,
        "rationale": rec.elicitation.rationale,
        "source": rec.elicitation.source,
        "promotion_id": rec.elicitation.promotion_id,
    }
    return make_id("pr_", payload)


def _client_of(rec: PriorRecord) -> str:
    hop = rec.resolution_path[0] if rec.resolution_path else ""
    if not hop.startswith(CLIENT_PREFIX) or not hop[len(CLIENT_PREFIX) :]:
        raise ValueError(
            "a proposed prior names its client in resolution_path[0] as 'client:<id>'; "
            f"got {rec.resolution_path!r}"
        )
    return hop


# --- public API ------------------------------------------------------------------------------


def propose(record: PriorRecord) -> str:
    """Store a pending prior. Returns ``pr_<sha8>``.

    Any approval on the incoming record is dropped: approval happens only through ``approve``
    (I10). Re-proposing identical content returns the same id and keeps the stored record.
    """
    owner = _client_of(record)
    pid = _content_id(record, owner)
    if not _record_path(pid).exists():
        elic = record.elicitation.model_dump()
        elic.update(approved_by=None, approved_at=None)
        _write_record(
            _rebuild(
                record,
                prior_id=pid,
                elicitation=elic,
                resolution_path=[owner],
                predictive_check=None,
            )
        )
    _log("propose", pid, owner=owner, parameter_path=record.parameter_path)
    return pid


def _ceiling(parameter_path: str) -> float | None:
    key = parameter_path.split(".")[-1]
    ceilings = registries.resolve("bounds/plausibility/ceiling_q99@v1")
    return float(ceilings[key]) if key in ceilings else None


def _frozen_dist(family: str, params: dict[str, float]) -> Any:
    if family == "beta":
        return stats.beta(params["a"], params["b"])
    if family == "gamma":
        return stats.gamma(params["shape"], scale=1.0 / params["rate"])
    if family == "normal":
        return stats.norm(params["loc"], params["scale"])
    if family == "halfnormal":
        return stats.halfnorm(scale=params["scale"])
    return None


def predictive_check(record: PriorRecord) -> dict[str, float]:
    """C6. Raises PriorRefused when the prior's 99th percentile exceeds the path's ceiling."""
    ceiling = _ceiling(record.parameter_path)
    if ceiling is not None and record.family != "beta":
        raise PriorRefused(
            f"{record.parameter_path!r} is a rate with a plausibility ceiling; "
            f"family {record.family!r} cannot be checked against it"
        )
    try:
        dist = _frozen_dist(record.family, record.params)
        q50, q99 = (float(dist.ppf(0.5)), float(dist.ppf(Q99))) if dist is not None else (0, 0)
    except (KeyError, ValueError, ZeroDivisionError) as exc:
        raise PriorRefused(f"prior params {record.params!r} do not fit {record.family!r}") from exc
    if dist is None:
        return {"ceiling_applies": 0.0}
    if q50 != q50 or q99 != q99:  # NaN: scipy's answer to invalid shape parameters
        raise PriorRefused(f"prior params {record.params!r} are invalid for {record.family!r}")
    out = {"q50": q50, "q99": q99}
    if ceiling is None:
        out["ceiling_applies"] = 0.0
        return out
    out.update({"ceiling_applies": 1.0, "ceiling": ceiling, "passed": float(q99 <= ceiling)})
    if q99 > ceiling:
        raise PriorRefused(
            f"prior predictive check failed for {record.parameter_path!r}: 99th percentile "
            f"{q99:.4f} exceeds the plausibility ceiling {ceiling}"
        )
    return out


def approve(prior_id: str, approver: str) -> PriorRecord:
    """Approve after the prior predictive check (C6). Called by atmaos.approve_prior only."""
    if not approver:
        raise ValueError("approve needs an approver")
    rec = _read_record(prior_id)
    if rec.approved:
        return rec
    try:
        check = predictive_check(rec)
    except PriorRefused as exc:
        _log("refuse", prior_id, approver=approver, reason=str(exc))
        raise
    elic = rec.elicitation.model_dump()
    elic.update(approved_by=approver, approved_at=utcnow())
    approved = _rebuild(rec, elicitation=elic, predictive_check=check)
    _write_record(approved)
    _log("approve", prior_id, approver=approver)
    return approved


def import_promoted(record: dict, promotion_id: str) -> str:
    """Vertical prior from AtmaOS, carrying its promotion id (C4).

    The record is checked like a proposal (C6, refused when implausible) and stored unapproved:
    AtmaOS promotion is not local approval, so the owner approves it here through ``approve``.
    """
    if not isinstance(promotion_id, str) or not promotion_id.strip():
        raise ValueError("import_promoted requires an AtmaOS promotion id")
    promotion_id = promotion_id.strip()
    rec = PriorRecord.model_validate(record)
    carried = rec.elicitation.promotion_id
    if carried is not None and carried != promotion_id:
        raise ValueError(f"record carries promotion id {carried!r}, not {promotion_id!r}")
    predictive_check(rec)  # raises PriorRefused
    owner = f"{VERTICAL_PREFIX}{promotion_id}"
    elic = rec.elicitation.model_dump()
    elic.update(source="promoted", promotion_id=promotion_id, approved_by=None, approved_at=None)
    rec = _rebuild(rec, elicitation=elic, predictive_check=None)
    pid = _content_id(rec, owner)
    if not _record_path(pid).exists():
        _write_record(_rebuild(rec, prior_id=pid, resolution_path=[owner]))
    _log("import", pid, owner=owner, parameter_path=rec.parameter_path)
    return pid


def _latest_client_prior(
    parameter_path: str, client_id: str, as_of: datetime
) -> PriorRecord | None:
    """The latest proposal for (client, path) whose elicitation was created by ``as_of``."""
    owner = f"{CLIENT_PREFIX}{client_id}"
    latest: PriorRecord | None = None
    for ev in _events():
        same = ev.get("owner") == owner and ev.get("parameter_path") == parameter_path
        if ev["event"] == "propose" and same:
            rec = _read_record(ev["prior_id"])
            if rec.elicitation.created_at <= as_of:
                latest = rec
    return latest


def _as_dt(v: Any) -> datetime:
    d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _default_prior(parameter_path: str) -> PriorRecord | None:
    reg = registries.load("priors/default")
    version = str(reg["version"])
    for table, elic_key in (("records", "elicitation"), ("pending_records", "pending_elicitation")):
        spec = (reg.get(table) or {}).get(parameter_path)
        if spec is None:
            continue
        e = spec.get("elicitation") or reg[elic_key]  # per-record override (D32)
        ref = f"priors/default/{table}/{parameter_path}@{version}"
        approved_at = _as_dt(e["approved_at"]) if e.get("approved_at") else None
        elic = ElicitationRecord(
            source=e["source"],
            rationale=e["rationale"],
            evidence_refs=[ref],
            author=e["author"],
            # the file carries no creation time; its approval time, or the epoch, stands in
            created_at=approved_at or datetime(1970, 1, 1, tzinfo=UTC),
            approved_by=e.get("approved_by"),
            approved_at=approved_at,
        )
        params = {k: float(v) for k, v in spec["params"].items()}
        return PriorRecord(
            prior_id=make_id("pr_", {"default": parameter_path, "params": params}),
            parameter_path=parameter_path,
            family=spec["family"],
            params=params,
            elicitation=elic,
            version=version,
            resolution_path=[f"default:{ref}"],
        )
    return None


def _g8(parameter_path: str, client_id: str, as_of: datetime, reason: str) -> GateFailure:
    res = GateResult(
        gate="G8",
        passed=False,
        blocking=True,
        reasons=[reason],
        inputs_hash=inputs_hash({"path": parameter_path, "client": client_id, "as_of": as_of}),
        checked_at=utcnow(),
    )
    return GateFailure(res)


def resolve(parameter_path: str, client_id: str, as_of: datetime) -> PriorRecord:
    """Client, then vertical, then default; every hop recorded (C2). Unapproved fails G8.

    Proposals whose elicitation was created after ``as_of`` are invisible. Approval time is not
    filtered: the frozen acceptance test approves at wall-clock time and resolves at an earlier
    ``as_of`` (open question in the P7 manifest).
    """
    client = _latest_client_prior(parameter_path, client_id, _as_dt(as_of))
    if client is not None:
        if not client.approved:
            raise _g8(
                parameter_path,
                client_id,
                as_of,
                f"client prior {client.prior_id} for {parameter_path!r} is not approved (I10)",
            )
        return _rebuild(client, resolution_path=[f"client:{client_id}:{client.prior_id}"])
    hops = [f"client:{client_id}:none", "vertical:unmapped"]
    default = _default_prior(parameter_path)
    if default is None:
        raise RegistryError(f"no prior for {parameter_path!r}: no client, vertical or default")
    return _rebuild(default, resolution_path=[*hops, default.resolution_path[0]])


def prior_from_cohorts(rates: list[float], discount: float) -> tuple[float, float]:
    """Method of moments with n-1 variance and a disclosed discount (C5). Returns (a, b).

    kappa = m(1 - m)/s^2 - 1 with s^2 the n-1 sample variance; the discount scales both a and b,
    keeping the mean and dividing the prior's weight (discount 1.0 means none).
    """
    n = len(rates)
    if n < 2:
        raise ValueError("prior_from_cohorts needs at least two cohort rates")
    if not 0 < discount <= 1:
        raise ValueError(f"discount must be in (0, 1], got {discount}")
    if any(not 0 < r < 1 for r in rates):
        raise ValueError("cohort rates must lie strictly between 0 and 1")
    m = sum(rates) / n
    s2 = sum((r - m) ** 2 for r in rates) / (n - 1)
    if s2 <= 0:
        raise ValueError("cohort rates have no spread; method of moments is undefined")
    kappa = m * (1 - m) / s2 - 1
    if kappa <= 0:
        raise ValueError("cohort spread exceeds a Beta's; method of moments gives kappa <= 0")
    return discount * m * kappa, discount * (1 - m) * kappa
