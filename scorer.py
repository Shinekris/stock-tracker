"""
scorer.py
Tier-weighted scoring for the priority wealth-creation parameters.

Each live parameter is scored 1/2/3, then multiplied by its tier weight
(Tier 1 x3, Tier 2 x2, Tier 3 x1). Non-live parameters are skipped until
their data source is added.
"""

import sqlite3
import config
import database


def score_value(key, value):
    """Return 1/2/3 for a single parameter value, or None if unscorable."""
    if value is None:
        return None
    p = config.PRIORITY_PARAMS.get(key)
    if not p:
        return None
    if p["direction"] == "higher":
        if value >= p["cut3"]: return 3
        if value >= p["cut2"]: return 2
        return 1
    else:  # lower is better
        if value <= p["cut3"]: return 3
        if value <= p["cut2"]: return 2
        return 1


def score_stock(row):
    """row = dict of raw values. Returns (weighted_total, weighted_max).

    Behaviour is controlled by two settings in config.py:
      FIXED_MAX_SCORE = True  -> every stock has the same max (full framework),
                                 and missing parameters count toward the max.
      MISSING_PARAM_SCORE     -> points a missing parameter receives when
                                 FIXED_MAX_SCORE is True (e.g. 0 to penalise,
                                 2 to treat as neutral/average).
    """
    fixed = getattr(config, "FIXED_MAX_SCORE", False)
    missing_score = getattr(config, "MISSING_PARAM_SCORE", 0)

    weighted_total = 0
    weighted_max = 0
    for key, p in config.PRIORITY_PARAMS.items():
        if not p.get("live"):
            continue
        w = config.TIER_WEIGHT[p["tier"]]
        s = score_value(key, row.get(key))

        if s is None:
            if fixed:
                # Missing data still counts toward the max (same denominator
                # for every stock); it earns MISSING_PARAM_SCORE points.
                weighted_total += missing_score * w
                weighted_max += 3 * w
            # else: skip entirely (variable max, the old behaviour)
            continue

        weighted_total += s * w
        weighted_max += 3 * w
    return weighted_total, weighted_max


def score_all(tickers, run_date=None):
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("SELECT MAX(date) FROM raw_data")
    latest = run_date or cur.fetchone()[0]

    for t in tickers:
        cur.execute("SELECT * FROM raw_data WHERE date=? AND ticker=?",
                    (latest, t))
        r = cur.fetchone()
        if not r:
            continue
        total, max_possible = score_stock(dict(r))
        if max_possible == 0:
            continue
        database.save_score(t, total, max_possible, run_date=latest)

    con.close()
