"""
diagnose.py
Reports how many stocks have data for each priority parameter, so you can
see exactly which parameters are failing to fetch.

Run with:
    python diagnose.py
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
        print("No data in database yet. Run collector.py first.")
        return

    cur.execute("SELECT * FROM raw_data WHERE date = ?", (latest,))
    rows = [dict(r) for r in cur.fetchall()]
    con.close()

    total = len(rows)
    print(f"Data date: {latest}   |   Stocks: {total}\n")
    print(f"{'Parameter':<40}{'Have data':>10}{'Missing':>10}{'Coverage':>10}")
    print("-" * 70)

    # Check each priority parameter
    for key, p in config.PRIORITY_PARAMS.items():
        have = sum(1 for r in rows if r.get(key) is not None)
        missing = total - have
        pct = round(100 * have / total) if total else 0
        flag = "  <-- PROBLEM" if pct < 50 else ""
        print(f"{key:<40}{have:>10}{missing:>10}{pct:>9}%{flag}")

    print("-" * 70)

    # Per-stock coverage summary
    live = [k for k, p in config.PRIORITY_PARAMS.items() if p.get("live")]
    print(f"\nPer-stock coverage (parameters with data / {len(live)}):")
    for r in sorted(rows, key=lambda x: x["ticker"]):
        cov = sum(1 for k in live if r.get(k) is not None)
        bar = "#" * cov + "." * (len(live) - cov)
        note = "  (low data)" if cov < len(live) * 0.5 else ""
        print(f"  {r['ticker']:<14} {cov:>2}/{len(live)}  [{bar}]{note}")

    # List stocks that failed entirely
    failed = [r["ticker"] for r in rows if not r.get("fetch_ok")]
    if failed:
        print(f"\nStocks that failed to fetch fundamentals: {', '.join(failed)}")


if __name__ == "__main__":
    main()
