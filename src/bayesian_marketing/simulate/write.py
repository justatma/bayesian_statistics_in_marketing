"""Write the drawn world as platform exports, an orders CSV, economics, a synthetic
DatasetManifest and ground truth (§9.1, §4.12, D17, D20).

Column headers are the canonical (first-listed) header per field in ``registries/channels.yaml``,
read through ``core.registries`` so P1's readers and this writer share one source (D20).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from bayesian_marketing.core import (
    ClientEconomics,
    DatasetManifest,
    ManifestFile,
    Money,
    make_id,
    registries,
)
from bayesian_marketing.simulate.draw import CENTS, SECONDS_PER_DAY, Conversion, World
from bayesian_marketing.simulate.scenario import PlatformSpec, Scenario

CURRENCY_SLOT = "{currency}"
CLICK_WINDOW = re.compile(r"^(\d+)d_click")


def channel(platform: str) -> dict[str, Any]:
    return registries.load("channels")["channels"][platform]


def canonical_headers(platform: str) -> dict[str, str]:
    """field -> first-listed header for that field (D20)."""
    out: dict[str, str] = {}
    for header, fld in channel(platform)["export_map"].items():
        out.setdefault(fld, header)
    return out


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}{c // CENTS}.{c % CENTS:02d}"


def _amount(x: float) -> str:
    return _money(round(x * CENTS))


def _tz(offset: str) -> timezone:
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", offset)
    if not m:
        raise ValueError(f"utc_offset must look like -05:00, got {offset!r}")
    sign = -1 if m.group(1) == "-" else 1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def _stamp(day: date, second: int, tz: timezone) -> str:
    return (
        datetime(day.year, day.month, day.day, tzinfo=tz) + timedelta(seconds=second)
    ).isoformat()


def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode()


def _windows(spec: PlatformSpec, platform: str, n_days: int) -> list[tuple[str, int]]:
    """(window code, click window in days) for each day index."""

    def click_days(code: str, explicit: int | None) -> int:
        if explicit is not None:
            return explicit
        m = CLICK_WINDOW.match(code)
        if not m:
            raise ValueError(f"{platform}: window {code!r} needs click_window_days in the scenario")
        return int(m.group(1))

    code = spec.attribution_window or channel(platform)["default_attribution_window"]
    current = (code, click_days(code, spec.click_window_days))
    changes = {c.from_day: c for c in spec.window_changes}
    out = []
    for d in range(n_days):
        if d in changes:
            c = changes[d]
            current = (c.window, click_days(c.window, c.click_window_days))
        out.append(current)
    return out


def base_window(spec: PlatformSpec, platform: str) -> str:
    return spec.attribution_window or channel(platform)["default_attribution_window"]


def _attributed(c: Conversion, n_days: int, windows: list[tuple[str, int]]) -> bool:
    observed = c.click_day + c.lag_days < n_days
    return observed and c.elapsed_seconds <= windows[c.click_day][1] * SECONDS_PER_DAY


def _write(out_dir: Path, name: str, data: bytes) -> str:
    (out_dir / name).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def write_exports(
    sc: Scenario, world: World, out_dir: Path, rng_credit: Any
) -> tuple[list[ManifestFile], dict[str, str]]:
    """One export per (platform, account). Returns files and the attribution window per platform."""
    days = [sc.start_date + timedelta(days=d) for d in range(sc.n_days)]
    files: list[ManifestFile] = []
    windows_out: dict[str, str] = {}
    for platform, spec in sc.platforms.items():
        idx = [i for i, a in enumerate(world.ads) if a.platform == platform]
        if not idx:
            continue
        windows = _windows(spec, platform, sc.n_days)
        windows_out[platform] = base_window(spec, platform)
        heads = canonical_headers(platform)
        fields = list(heads)
        header = [heads[f].replace(CURRENCY_SLOT, sc.currency) for f in fields]
        # reported conversions and revenue per (ad, click day)
        conv: dict[tuple[int, int], float] = {}
        rev: dict[tuple[int, int], float] = {}
        for i in idx:
            for c in world.days[i].conversions:
                if not _attributed(c, sc.n_days, windows):
                    continue
                if spec.fractional_credit is not None:
                    fc = spec.fractional_credit
                    c.credit = float(rng_credit.beta(fc.beta_a, fc.beta_b))
                key = (i, c.click_day)
                conv[key] = conv.get(key, 0.0) + c.credit
                rev[key] = rev.get(key, 0.0) + c.value * c.credit
        accounts: dict[str, list[int]] = {}
        for i in idx:
            accounts.setdefault(world.ads[i].account.id, []).append(i)
        for acc_id, ad_idx in accounts.items():
            rows = []
            for d, day in enumerate(days):
                for i in ad_idx:
                    a, ad_days = world.ads[i], world.days[i]
                    n_conv = conv.get((i, d), 0.0)
                    if spec.fractional_credit is not None:
                        conv_s = f"{n_conv:.{spec.fractional_credit.decimals}f}"
                    else:
                        conv_s = str(round(n_conv))
                    values = {
                        "date": day.isoformat(),
                        "entity_ids.account": a.account.id,
                        "entity_ids.account_name": a.account.name,
                        "entity_ids.campaign": a.campaign.id,
                        "entity_ids.campaign_name": a.campaign.name,
                        "entity_ids.ad_set": a.ad_set.id,
                        "entity_ids.ad_set_name": a.ad_set.name,
                        "entity_ids.ad": a.ad.id,
                        "entity_ids.ad_name": a.ad.name,
                        "impressions": str(ad_days.impressions[d]),
                        "clicks": str(ad_days.clicks[d]),
                        "spend": _money(ad_days.spend_cents[d]),
                        "currency": sc.currency,
                        "conversions_reported": conv_s,
                        "revenue_reported": _amount(rev.get((i, d), 0.0)),
                        "attribution_window": windows[d][0],
                    }
                    missing = [f for f in fields if f not in values]
                    if missing:
                        raise KeyError(f"{platform}: no simulated value for fields {missing}")
                    rows.append([values[f] for f in fields])
            name = f"{platform}_{acc_id}.csv"
            sha = _write(out_dir, name, _csv(header, rows))
            files.append(
                ManifestFile(path=name, platform=platform, sha256=sha, export_kind="export")
            )
    return files, windows_out


def write_orders(sc: Scenario, world: World, out_dir: Path) -> ManifestFile:
    """Every order that has happened by the end of the window, joinable through utm (§5.1 C7)
    unless the platform says otherwise."""
    tz = _tz(sc.utc_offset)
    events = []
    for days in world.days:
        for c in days.conversions:
            if c.click_day + c.lag_days < sc.n_days:
                events.append(c)
    events.sort(key=lambda c: (c.click_day + c.lag_days, c.order_second, c.ad_index))
    heads = canonical_headers("orders")
    fields = list(heads)
    width = len(str(len(events)))
    rows = []
    for n, c in enumerate(events, start=1):
        a = world.ads[c.ad_index]
        spec = sc.platforms[a.platform]  # type: ignore[index]
        click_day = sc.start_date + timedelta(days=c.click_day)
        order_day = click_day + timedelta(days=c.lag_days)
        join = spec.orders_joinable
        values = {
            "order_id": f"o{n:0{width}d}",
            "ordered_at": _stamp(order_day, c.order_second, tz),
            "value": _amount(c.value),
            "currency": sc.currency,
            "refunded": _money(0),
            "utm.source": spec.utm_source if join else "",
            "utm.medium": spec.utm_medium if join else "",
            "utm.campaign": a.utm_campaign if join else "",
            "utm.content": a.ad.id if join else "",
            "click_id": "",
            "first_click_at": _stamp(click_day, c.click_second, tz),
        }
        rows.append([values[f] for f in fields])
    sha = _write(out_dir, "orders.csv", _csv([heads[f] for f in fields], rows))
    return ManifestFile(path="orders.csv", platform="orders", sha256=sha, export_kind="export")


def economics(sc: Scenario) -> ClientEconomics:
    e = sc.economics

    def m(x: Decimal | None) -> Money | None:
        return None if x is None else Money(amount=x, currency=sc.currency)

    body = e.model_dump(mode="json")
    return ClientEconomics(
        economics_id=make_id("econ_", {"client": sc.client_id, **body}),
        client_id=sc.client_id,
        currency=sc.currency,
        variable_cost_per_order=m(e.variable_cost_per_order),  # type: ignore[arg-type]
        price_source=e.price_source,
        fixed_price=m(e.fixed_price),
        loss_tolerance=m(e.loss_tolerance),
        survival_floor=m(e.survival_floor),
        test_budget=m(e.test_budget),
        source=e.source,
        approved_by=e.approved_by,
        approved_at=datetime.fromisoformat(e.approved_at) if e.approved_at else None,
    )


def write_economics(econ: ClientEconomics, out_dir: Path) -> None:
    """``<manifest_dir>/economics/<id>.json``, where core.load_economics looks first (D22)."""
    d = out_dir / "economics"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{econ.economics_id}.json").write_text(econ.model_dump_json(indent=2) + "\n")


def manifest(
    sc: Scenario,
    world: World,
    files: list[ManifestFile],
    windows: dict[str, str],
    econ: ClientEconomics,
    seed: int,
) -> DatasetManifest:
    windows = {**windows, "orders": channel("orders")["default_attribution_window"]}
    entity_map = {a.variant: {a.platform: a.ad.id} for a in world.ads}
    utm_map = {
        a.utm_campaign: {a.platform: a.ad.id}
        for a in world.ads
        if sc.platforms[a.platform].orders_joinable  # type: ignore[index]
    }
    return DatasetManifest(
        manifest_id=make_id(
            "ds_", {"scenario": sc.scenario, "seed": seed, "files": [f.sha256 for f in files]}
        ),
        client_id=sc.client_id,
        economics_id=econ.economics_id,
        files=files,
        attribution_window=windows,  # type: ignore[arg-type]
        entity_map=entity_map,
        utm_map=utm_map or None,
        synthetic=True,
        currency=sc.currency,
    )
