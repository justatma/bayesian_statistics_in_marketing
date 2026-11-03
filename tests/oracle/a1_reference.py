"""Frozen-value reference for test_P5_A1_roas_wider_with_modeled_value (§5.2 C2, §15).

A ROAS computed from a fixed revenue per conversion fails A1. The reference "fixed revenue per
conversion" for each ad of ``tests.fakes.synth.a1_ads()`` is that ad's mean order value, frozen
here (recomputed 2026-11-03 from the seeded generator). Clicks 2,000 and spend $2,500 per ad.
"""

FIXED_REVENUE_PER_CONVERSION = {
    "ad_0": 33.829687,
    "ad_1": 64.240455,
    "ad_2": 55.502222,
    "ad_3": 56.065522,
    "ad_4": 61.664023,
    "ad_5": 72.872222,
    "ad_6": 66.368068,
    "ad_7": 48.800588,
}
CONVERSIONS = {
    "ad_0": 32,
    "ad_1": 44,
    "ad_2": 45,
    "ad_3": 67,
    "ad_4": 87,
    "ad_5": 81,
    "ad_6": 88,
    "ad_7": 102,
}
CLICKS = 2000
SPEND = 2500.0
MIN_WIDTH_RATIO = 1.1
