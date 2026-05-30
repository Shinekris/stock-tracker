"""
config.py
Central configuration for the India wealth-creation stock tracker.

Scoring focuses on the TOP 3 TIERS of direct-traceable wealth-creation
parameters, weighted by price-impact priority:

    Tier 1 (Immediate movers)   -> weight x3
    Tier 2 (Sustained drivers)  -> weight x2
    Tier 3 (Re-rating factors)  -> weight x1

Each parameter is scored 3/2/1 then multiplied by its tier weight.
"live" marks whether the collector can fetch it from free sources.
"""

# ---------------------------------------------------------------------------
# General settings
# ---------------------------------------------------------------------------
DB_PATH = "data/tracker.db"
STOCK_LIST_FILE = "stocks.csv"
INDEX_MEMBERS_FILE = "index_members.csv"   # optional: ticker,index (50 or 500)

SCREENER_DELAY = 2.5
MAX_RETRIES = 3
RETRY_BACKOFF = 5

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Scoring behaviour
# ---------------------------------------------------------------------------
# FIXED_MAX_SCORE: if True, every stock is scored out of the SAME maximum
#   (the full framework), so scores are directly comparable. Missing
#   parameters count toward the max.
# MISSING_PARAM_SCORE: points a missing parameter receives when FIXED_MAX_SCORE
#   is True. Use 0 to penalise missing data, or 2 to treat it as neutral
#   (average) so a stock isn't unfairly punished for data that doesn't exist.
FIXED_MAX_SCORE = True
MISSING_PARAM_SCORE = 2

# ---------------------------------------------------------------------------
# Tier weighting
# ---------------------------------------------------------------------------
TIER_WEIGHT = {1: 3, 2: 2, 3: 1, 4: 1}
TIER_NAME = {
    1: "Tier 1 - Immediate movers",
    2: "Tier 2 - Sustained drivers",
    3: "Tier 3 - Re-rating factors",
    4: "Tier 4 - Risk protectors",
}

# ---------------------------------------------------------------------------
# Priority parameters (top 3 tiers, direct-traceable) - ALL NOW LIVE
# key -> dict(label, tier, direction, cut3, cut2, live)
# ---------------------------------------------------------------------------
PRIORITY_PARAMS = {
    # ---- Tier 1 ----
    "revenue_growth_accel": dict(
        label="Revenue Growth Acceleration (TTM vs 3yr, pp)",
        tier=1, direction="higher", cut3=5, cut2=0, live=True),

    # ---- Tier 2 ----
    "revenue_growth": dict(
        label="Revenue Growth YoY (%)",
        tier=2, direction="higher", cut3=20, cut2=10, live=True),
    "eps_growth": dict(
        label="EPS / Profit Growth (%)",
        tier=2, direction="higher", cut3=20, cut2=10, live=True),
    "price_momentum_52w": dict(
        label="52-Week Price Momentum (%)",
        tier=2, direction="higher", cut3=30, cut2=0, live=True),
    "fcf_growth": dict(
        label="Free Cash Flow Growth (approx, %)",
        tier=2, direction="higher", cut3=20, cut2=5, live=True),
    "fii_buying": dict(
        label="FII Buying (change in holding, pp)",
        tier=2, direction="higher", cut3=0.5, cut2=-0.5, live=True),

    # ---- Tier 3 ----
    "roe": dict(
        label="ROE (%)",
        tier=3, direction="higher", cut3=20, cut2=12, live=True),
    "roce": dict(
        label="ROCE (%)",
        tier=3, direction="higher", cut3=25, cut2=15, live=True),
    "opm": dict(
        label="EBITDA / Operating Margin (%)",
        tier=3, direction="higher", cut3=20, cut2=12, live=True),
    "dividend_payout": dict(
        label="Dividend Yield / Capital Returns (%)",
        tier=3, direction="higher", cut3=1.5, cut2=0.5, live=True),
    "ocf_growth": dict(
        label="Operating Cash Flow Growth (%)",
        tier=3, direction="higher", cut3=20, cut2=5, live=True),
    "fcf_to_profit": dict(
        label="FCF to Net Profit Ratio (approx)",
        tier=3, direction="higher", cut3=0.8, cut2=0.4, live=True),
    "cfo_to_op": dict(
        label="CFO / Operating Profit (cash conversion)",
        tier=3, direction="higher", cut3=0.8, cut2=0.5, live=True),

    # ---- Tier 4 (Risk protectors) ----
    "debt_to_equity_score": dict(
        label="Debt to Equity (lower is safer)",
        tier=4, direction="lower", cut3=0.3, cut2=1.0, live=True),
    "interest_coverage": dict(
        label="Interest Coverage (EBIT / interest)",
        tier=4, direction="higher", cut3=5, cut2=2, live=True),
    "net_margin": dict(
        label="Net Profit Margin (%)",
        tier=4, direction="higher", cut3=12, cut2=6, live=True),
}

# Extra fields fetched for the Screener-filter tab (not part of the score).
EXTRA_FILTER_FIELDS = [
    "debt_to_equity", "current_ratio", "promoter_holding", "promoter_pledge",
]
