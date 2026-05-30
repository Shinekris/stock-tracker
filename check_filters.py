"""
check_filters.py
Inspects the filter columns (roe, debt_to_equity, promoter_pledge) used by the
Screener tab, to see whether they're populated and numeric.

Run with:
    python check_filters.py
"""

import sqlite3
import config


def main():
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT MAX(date) FROM raw_data")
    latest = cur.fetchone()[0]
    if not latest:
        print("No data. Run collector.py first.")
        return

    cur.execute("SELECT ticker, roe, debt_to_equity, promoter_pledge, "
                "promoter_holding, current_ratio FROM raw_data WHERE date=?",
                (latest,))
    rows = cur.fetchall()
    con.close()

    print(f"Data date: {latest}\n")
    print(f"{'Ticker':<14}{'roe':>10}{'D/E':>10}{'pledge':>10}"
          f"{'prom_hold':>12}{'curr_ratio':>12}")
    print("-" * 68)
    for r in rows[:10]:   # first 10 as a sample
        def show(v):
            if v is None:
                return "None"
            return f"{v} ({type(v).__name__})"
        print(f"{r['ticker']:<14}{show(r['roe']):>10}{show(r['debt_to_equity']):>10}"
              f"{show(r['promoter_pledge']):>10}{show(r['promoter_holding']):>12}"
              f"{show(r['current_ratio']):>12}")

    # Summary: how many have each filter column populated and numeric
    def count_numeric(col):
        n = 0
        for r in rows:
            v = r[col]
            if isinstance(v, (int, float)):
                n += 1
        return n

    print("\nNumeric (usable) counts out of", len(rows), "stocks:")
    for col in ("roe", "debt_to_equity", "promoter_pledge",
                "promoter_holding", "current_ratio"):
        print(f"  {col:<18}{count_numeric(col)}")


if __name__ == "__main__":
    main()
