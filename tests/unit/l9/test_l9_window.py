"""L9 unit checks beyond the frozen tests: a two-click code makes ``lag_notices`` say "no click
window" without raising (A13), the generator reads Meta's code inside a window change and refuses
a two-click code, and the parser takes ASCII digits only."""

from __future__ import annotations

import pytest

from bayesian_marketing.lag import model as lag
from bayesian_marketing.simulate import write
from bayesian_marketing.simulate.scenario import PlatformSpec, WindowChange

META_CODE = "1d_view_7d_click_1d_ev"
NAMES_NO_WINDOW = "names no click window"


def test_lag_notices_two_click_code_does_not_raise() -> None:
    base = lag.lag_model("meta", "7d_click", None, None)
    notices = lag.lag_notices(base.model_copy(update={"attribution_window": "7d_click_28d_click"}))
    assert any(NAMES_NO_WINDOW in n for n in notices)


def test_lag_model_two_click_code_raises() -> None:
    with pytest.raises(ValueError):
        lag.lag_model("meta", "7d_click_28d_click", None, None)


@pytest.mark.parametrize("code", ["", "_", "click", "d_click", "7_click", "7d__click", "7D_click"])
def test_click_window_days_odd_codes_name_none(code: str) -> None:
    assert lag.click_window_days(code) is None


def test_click_window_days_ascii_digits_only() -> None:
    assert lag.click_window_days(chr(0x0667) + "d_click") is None  # Arabic-Indic seven


def test_click_window_days_leading_zero() -> None:
    assert lag.click_window_days("07d_click") == 7


def test_generator_window_change_to_meta_code() -> None:
    spec = PlatformSpec(
        attribution_window="28d_click",
        window_changes=[WindowChange(from_day=1, window=META_CODE)],
        utm_source="fb",
        utm_medium="paid",
    )
    assert write._windows(spec, "meta", 3) == [("28d_click", 28), (META_CODE, 7), (META_CODE, 7)]


def test_generator_refuses_two_click_code() -> None:
    spec = PlatformSpec(attribution_window="7d_click_28d_click", utm_source="fb", utm_medium="paid")
    with pytest.raises(ValueError):
        write._windows(spec, "meta", 1)
