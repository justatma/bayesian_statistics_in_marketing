"""Live view contracts (spec v0.2 §4). Laid down by L0; the builders implement against these."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal, Protocol, runtime_checkable

from bayesian_marketing.core import Money
from bayesian_marketing.core.base import Frozen, Platform

PollStatus = Literal["ok", "error", "interrupted"]
RefreshStatus = Literal["ran", "skipped", "failed"]


class PollRecord(Frozen):
    """One poll. ``status="interrupted"`` is never written: it is how a polls row with no
    outcome row reads back."""

    poll_id: str  # poll_<sha8> of client_id|platform|started_at.isoformat() (§2)
    client_id: str
    platform: Platform
    account_id: str
    started_at: datetime
    finished_at: datetime | None
    window: tuple[date, date]  # account-local dates read, inclusive
    status: PollStatus
    error: str | None
    pull_id: str | None
    n_rows: int
    n_quarantined: int
    empty_account: bool
    timezone: str | None
    currency: str | None
    account: dict[str, str]  # §3.3 fields as the API returned them, as text
    recording_dir: str | None


class LiveRow(Frozen):
    """One ``PerformanceRow`` as stored, with the poll it came from."""

    poll_id: str
    client_id: str
    platform: Platform
    entity_ids: dict[str, str]  # account, campaign, ad_set, ad
    entity_names: dict[str, str]  # same keys (B4)
    objective: str | None
    date: date
    impressions: int
    clicks: int
    spend: Money
    conversions_reported: float | None
    conversions_observed: int | None
    revenue_reported: Money | None
    attribution_window: str


class RefreshRecord(Frozen):
    refresh_id: str  # lv_<sha8> of poll_id|at.isoformat()
    poll_id: str
    client_id: str
    at: datetime
    status: RefreshStatus
    reason: str | None
    run_id: str | None  # the pipeline run when status == "ran"


@runtime_checkable
class Store(Protocol):
    """Append-only (§4.1). Implemented by ``live.store.SqliteStore`` and ``tests.fakes.live``."""

    def begin_poll(self, rec: PollRecord) -> None:
        """Insert the polls row. Outcome fields of ``rec`` are ignored."""
        ...

    def finish_poll(self, rec: PollRecord, rows: list[LiveRow]) -> None:
        """Insert the outcome row and every row, in one transaction. ``rec.status`` is ok or
        error; an error poll has no rows."""
        ...

    def latest_poll(self, client_id: str, *, ok_only: bool = True) -> PollRecord | None:
        """Newest by ``started_at``. ``ok_only`` skips error and interrupted polls."""
        ...

    def rows(self, poll_id: str) -> list[LiveRow]: ...

    def polls(self, client_id: str, *, limit: int) -> list[PollRecord]:
        """Newest first."""
        ...

    def add_refresh(self, rec: RefreshRecord) -> None: ...

    def latest_refresh(self, client_id: str) -> RefreshRecord | None: ...

    def clients(self) -> list[str]:
        """Every client with at least one poll, sorted."""
        ...


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """UTC, tz-aware."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
