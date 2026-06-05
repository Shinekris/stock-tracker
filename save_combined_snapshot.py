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
RESEARCH_CAP = 10


def load_research_totals():
    """Return {ticker: total_score} from research_notes.csv."""
    totals = {}
    if not os.path.exists(RESEARCH_FILE):
        return totals
    try:
        with open(RESEARCH_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").strip().upper()
                try:
                    s = int(row.get("score"))
                except (TypeError, ValueError):
                    continue
                if t:
                    totals[t] = totals.get(t, 0) + s
    except Exception:
        pass
    return totals


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

    research = load_research_totals()
    stamp = date.today().strftime("%Y-%m-%d")
    os.makedirs("archive", exist_ok=True)
    out_path = os.path.join("archive", f"combined_{stamp}.csv")

    results = []
    for ticker, pct, grade in rows:
        fund = float(pct)
        rtotal = research.get((ticker or "").upper(), 0)
        adj = max(-RESEARCH_CAP, min(RESEARCH_CAP, rtotal))
        combined = round(fund + adj, 1)
        results.append((ticker, combined, round(fund, 1), rtotal, grade))

    results.sort(key=lambda x: -x[1])
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "combined", "fundamental", "research_pts",
                    "grade"])
        for r in results:
            w.writerow(r)

    print(f"Saved combined snapshot ({len(results)} stocks, "
          f"data date {latest}) to {out_path}")


if __name__ == "__main__":
    main()
