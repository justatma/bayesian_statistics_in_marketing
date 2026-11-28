"""D34: the CVR predictive check leaves out reported conversions above clicks."""

from __future__ import annotations

from tests.fakes import builders as B

from bayesian_marketing.diagnostics import run


def test_cvr_check_skips_reported_above_clicks() -> None:
    data = B.funnel_data({"a": {"impressions": 1000, "clicks": 3, "spend": 10.0, "conv_rep": 9.0}})
    assert run._cvr_conversions(data, 0, 0) is None
    ok = B.funnel_data({"a": {"impressions": 1000, "clicks": 30, "spend": 10.0, "conv_rep": 9.0}})
    assert run._cvr_conversions(ok, 0, 0) == 9.0
