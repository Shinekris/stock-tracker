"""
save_combined_snapshot.py
Computes the Combined ranking (fundamental % + research adjustment) for the
latest data and saves it to archive/combined_YYYY-MM-DD.csv.

Combined = Fundamental % + research total (capped at +/- 10).

Run from the portfolio folder. Used by the weekly automation, but can also be
run manually.
"""
import csv
import os
import sqlite3
from datetime import date

import config

RESEARCH_FILE = "research_notes.csv"


def load_research_avgs():
    """Return {ticker: (total, count, average)} from research_notes.csv."""
    agg = {}
    if not os.path.exists(RESEARCH_FILE):
        return agg
    try:
        with open(RESEARCH_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").strip().upper()
                try:
                    s = int(row.get("score"))
                except (TypeError, ValueError):
                    continue
                if t:
                    tot, cnt = agg.get(t, (0, 0))
                    agg[t] = (tot + s, cnt + 1)
    except Exception:
        pass
    # convert to total, count, average
    return {t: (tot, cnt, round(tot / cnt, 2) if cnt else 0)
            for t, (tot, cnt) in agg.items()}


def main():
    con = sqlite3.connect(config.DB_PATH)
    try:
        latest = con.execute(
            "SELECT MAX(date) FROM daily_scores").fetchone()[0]
        if latest is None:
            print("No data found. Run collector.py first.")
            return
        rows = con.execute(
            "SELECT ticker, pct, grade FROM daily_scores WHERE date = ?",
            (latest,)).fetchall()
    finally:
        con.close()

    research = load_research_avgs()
    stamp = date.today().strftime("%Y-%m-%d")
    os.makedirs("archive", exist_ok=True)
    out_path = os.path.join("archive", f"combined_{stamp}.csv")

    results = []
    for ticker, pct, grade in rows:
        fund = float(pct)
        tot, cnt, avg = research.get((ticker or "").upper(), (0, 0, 0))
        # adjustment = average factor score (-3..+3) mapped to -10..+10
        adj = round(avg * (10.0 / 3.0), 1) if cnt else 0.0
        combined = round(fund + adj, 1)
        results.append((ticker, combined, round(fund, 1), avg, adj, cnt, grade))

    results.sort(key=lambda x: -x[1])
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "combined", "fundamental", "avg_factor",
                    "adj_applied", "factors", "grade"])
        for r in results:
            w.writerow(r)

    print(f"Saved combined snapshot ({len(results)} stocks, "
          f"data date {latest}) to {out_path}")


if __name__ == "__main__":
    main()
