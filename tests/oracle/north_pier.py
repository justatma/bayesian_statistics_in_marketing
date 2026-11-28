"""North Pier answer key (spec v0.3 §9.2). Source of truth for the P3, P4, P7 and P9 oracle tests.

Each constant is the value recomputed on 2026-11-03 with scipy 1.18.1 (scratch script outside the
repo); the §9.2 table value it reproduces is in the comment. Tolerance: half a unit in the 4th
significant figure (`sig4`), unless stated (expected loss: ±$0.01).
"""

from __future__ import annotations

import math


def sig4(x: float) -> float:
    """Half a unit in the 4th significant figure of x."""
    return 0.5 * 10 ** (math.floor(math.log10(abs(x))) - 3)


def close4(got: float, want: float) -> bool:
    return abs(float(got) - want) <= sig4(want)


# --- CTR day two: prior Beta(2,98); A 40/2,000, B 34/2,000 -------------------------------------
CTR_POST_A = (42, 2058)
CTR_POST_B = (36, 2064)
CTR_MEAN_A = 0.02  # table 2.000%
CTR_MEAN_B = 0.017142857142857144  # table 1.714%
CTR_CI95_A = (0.01445823, 0.02640636)  # table 1.446%-2.641%
CTR_CI95_B = (0.01204054, 0.02311465)  # table 1.204%-2.311%
CTR_P_A_GT_B = 0.7548183084712957  # table 0.7548

# --- CVR day fourteen: prior Beta(1,49); A 8/400, B 18/340 --------------------------------------
CVR_POST_A = (9, 441)
CVR_POST_B = (19, 371)
CVR_MEAN_A = 0.02  # table 2.000%
CVR_MEAN_B = 0.04871794871794872  # table 4.872%
CVR_CI95_A = (0.00920562, 0.03480433)  # table 0.9206%-3.480%
CVR_CI95_B = (0.02965945, 0.07214645)  # table 2.966%-7.215%
CVR_P_B_GT_A = 0.9906520839547941  # table 0.9907

# --- Floors at D10 -------------------------------------------------------------------------------
# DISCREPANCY (not frozen): the table's widths CTR A 0.251, B 0.271, CVR A 0.536, B 0.366 match
# (q95-q05)/(2*mean): 0.2505, 0.2709, 0.5356, 0.3657. The §6.1 definition divides by q50 and gives
# 0.2525, 0.2733, 0.5552, 0.3716. Only the statuses agree under both, so only they are frozen.
FLOOR_STATUS = {
    "ctr_a": "marginal",
    "ctr_b": "marginal",
    "cvr_a": "below_floor",
    "cvr_b": "marginal",
}

# --- Money rows: $32 contribution per order ($80 price - $48 variable cost); horizon 1,000 clicks;
# CPC A $1.25 (spend $500 / 400 clicks), B $500/340 -----------------------------------------------
PRICE = 80
VARIABLE_COST = 48
CONTRIBUTION_PER_ORDER = 32
HORIZON_CLICKS = 1000
EV_A = -610.0  # table -$610.00
EV_B = 88.38612368024124  # table +$88.39
P_B_HIGHER = 0.9623790353559915  # table 0.9624
LOSS_A = 704.210862278652  # table $704.21 (±$0.01)
LOSS_B = 5.824738598410345  # table $5.82 (±$0.01)
LOSS_TOL = 0.01
BREAK_EVEN_CVR_A = 0.0390625  # table 3.906%
BREAK_EVEN_CVR_B = 0.04595588235294118  # table 4.596%
P_A_CLEARS = 0.008265278459668344  # table 0.008265
P_B_CLEARS = 0.5740626136098655  # table 0.5741

# --- Economics: $80 price, $48 -> $56 variable cost ----------------------------------------------
BREAK_EVEN_CPA = 32  # table $32
BREAK_EVEN_ROAS = 2.5  # table 2.5
VARIABLE_COST_HIGH = 56
BREAK_EVEN_ROAS_HIGH = 3.3333333333333335  # table 3.333
# Consequence used by the P3 economics test (recomputed, not in the table): with $24 contribution
# the CVR break-even thresholds are 1.25/24 and (500/340)/24, and
P_A_CLEARS_HIGH = 0.00017247978199433649
P_B_CLEARS_HIGH = 0.12734574594575285

# --- EVPI, EVSI: 40% chance of +$2,000, else -$1,000; signal sensitivity 75%, false positive 25% --
EV_NOW = 200.0  # table $200
EVPI = 600.0  # table $600
P_POSITIVE = 0.45  # table 0.45 (not reachable through the §6.3 interface; see manifest)
POST_GIVEN_POS = 0.6666666666666666  # table 0.6667 (same)
POST_GIVEN_NEG = 0.18181818181818185  # table 0.1818 (same)
EVSI = 250.0  # table $250

# --- Sample size: 3% vs 4%, alpha 0.05 two-sided, power 0.8 -------------------------------------
SAMPLE_SIZE_PER_ARM = 5300.739171069874  # table 5,300.74
SAMPLE_SIZE_TOL = 0.01

# --- Prior from cohorts: rates below, discount 0.25, then 10/200 ----------------------------------
COHORT_RATES = [0.013, 0.017, 0.019, 0.021, 0.023, 0.027]
COHORT_DISCOUNT = 0.25
COHORT_KAPPA = 829.5084745762713  # table 829.51
COHORT_AB = (16.590169491525426, 812.9183050847458)  # table Beta(16.59, 812.92)
COHORT_AB_DISCOUNTED = (4.1475423728813565, 203.22957627118646)  # table Beta(4.148, 203.23)
COHORT_UPDATE = (10, 200)
COHORT_POST_MEAN = 0.034728367709926045  # table 3.473%

# --- Dependence: (ctr, cvr) = (4%, 1%) or (1%, 5%); 10,000 imps for $200; $80 per order -----------
DEP_PAIRS = [(0.04, 0.01), (0.01, 0.05)]
DEP_IMPRESSIONS = 10_000
DEP_SPEND = 200
DEP_AOV = 80
DEP_PAIRED_ROAS = (1.6, 2.0)  # table 1.6, 2.0
DEP_PAIRED_MEAN = 1.8  # table 1.8
DEP_INDEPENDENT_MEAN = 3.0  # table 3.0 (from 0.4, 1.6, 2.0, 8.0)

# --- Delivery mix: 800/200 -> 300/700 clicks at 5% / 1% ------------------------------------------
MIX_BEFORE = 42.0  # table 42 orders per 1,000 clicks
MIX_AFTER = 22.0  # table 22

# --- Hold: keep $1,000; switch 0.7 x $1,500 + 0.3 x $400; switching cost $250 ---------------------
HOLD_KEEP = 1000
HOLD_SWITCH_EV = 1170.0  # 0.7*1500 + 0.3*400
HOLD_SWITCH_COST = 250
HOLD_NET = 920.0  # table $920 < $1,000 -> hold
