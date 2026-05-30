"""
database.py
SQLite storage for the India wealth-creation tracker.
Uses Python's built-in sqlite3 (no external dependencies).
Includes a small auto-migration so new columns can be added safely.
"""

import sqlite3
import os
from datetime import date

import config

# All raw value columns we store (priority params + extra filter fields).
RAW_COLUMNS = [
    "revenue_growth_accel", "revenue_growth", "eps_growth", "profit_growth",
    "price_momentum_52w", "roe", "roce", "opm", "dividend_payout",
    "ocf_growth", "fcf_growth", "fcf_to_profit", "cfo_to_op", "fii_buying",
    "index_member",
    "interest_coverage", "net_margin", "debt_to_equity_score",
    "debt_to_equity", "current_ratio", "promoter_holding", "promoter_pledge",
    "price",
]


def _connect():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    return sqlite3.connect(config.DB_PATH)


def init_db():
    """Create tables if missing, and add any new columns to existing tables."""
    con = _connect()
    cur = con.cursor()

    col_defs = ",\n".join(f"{c} REAL" for c in RAW_COLUMNS)
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS raw_data (
            date TEXT,
            ticker TEXT,
            {col_defs},
            fetch_ok INTEGER,
            PRIMARY KEY (date, ticker)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_scores (
            date TEXT,
            ticker TEXT,
            total_score INTEGER,
            max_score INTEGER,
            pct REAL,
            grade TEXT,
            PRIMARY KEY (date, ticker)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS quarterly_history (
            ticker TEXT PRIMARY KEY,
            data TEXT
        )
    """)

    # Auto-migration: add any RAW_COLUMNS missing from an older raw_data table.
    cur.execute("PRAGMA table_info(raw_data)")
    existing = {r[1] for r in cur.fetchall()}
    for c in RAW_COLUMNS:
        if c not in existing:
            try:
                cur.execute(f"ALTER TABLE raw_data ADD COLUMN {c} REAL")
            except sqlite3.OperationalError:
                pass

    con.commit()
    con.close()


def save_raw(ticker, values, fetch_ok=True, run_date=None):
    run_date = run_date or date.today().isoformat()
    con = _connect()
    cur = con.cursor()
    row = [run_date, ticker] + [values.get(c) for c in RAW_COLUMNS] + \
          [1 if fetch_ok else 0]
    placeholders = ",".join(["?"] * len(row))
    cols = "date,ticker," + ",".join(RAW_COLUMNS) + ",fetch_ok"
    cur.execute(f"INSERT OR REPLACE INTO raw_data ({cols}) VALUES ({placeholders})",
                row)
    con.commit()
    con.close()


def save_history(ticker, hist_dict):
    """Store the quarterly history JSON blob for a stock."""
    import json
    con = _connect()
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO quarterly_history (ticker, data) "
                "VALUES (?, ?)", (ticker, json.dumps(hist_dict)))
    con.commit()
    con.close()


def load_history(ticker):
    """Return the quarterly history dict for a stock, or None."""
    import json
    con = _connect()
    cur = con.cursor()
    try:
        cur.execute("SELECT data FROM quarterly_history WHERE ticker=?",
                    (ticker,))
        r = cur.fetchone()
    except sqlite3.OperationalError:
        r = None
    con.close()
    if r and r[0]:
        try:
            return json.loads(r[0])
        except Exception:
            return None
    return None


def save_score(ticker, total, max_score, run_date=None):
    run_date = run_date or date.today().isoformat()
    pct = round(100 * total / max_score, 1) if max_score else 0
    grade = _grade(pct)
    con = _connect()
    cur = con.cursor()
    cur.execute("INSERT OR REPLACE INTO daily_scores VALUES (?,?,?,?,?,?)",
                (run_date, ticker, total, max_score, pct, grade))
    con.commit()
    con.close()


def _grade(pct):
    if pct >= 90: return "A+"
    if pct >= 80: return "A"
    if pct >= 70: return "B"
    if pct >= 60: return "C"
    return "D"


def latest_leaderboard():
    con = _connect()
    cur = con.cursor()
    cur.execute("SELECT MAX(date) FROM daily_scores")
    latest = cur.fetchone()[0]
    cur.execute("""
        SELECT ticker, total_score, max_score, pct, grade
        FROM daily_scores WHERE date = ?
        ORDER BY pct DESC
    """, (latest,))
    rows = cur.fetchall()
    con.close()
    return latest, rows
