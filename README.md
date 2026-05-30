# India Wealth-Creation Stock Tracker

A free system that scores Indian (NSE) stocks on wealth-creation parameters and
ranks them daily. Built for retail investors. No paid subscriptions required.

## What this starter includes

| File | Purpose |
|------|---------|
| `config.py` | Scoring thresholds and settings — tune these to your taste |
| `database.py` | SQLite storage (raw values + daily scores) |
| `collector.py` | Fetches data from yfinance + Screener.in with rate limiting |
| `scorer.py` | Converts raw values into 1/2/3 scores and a total |
| `stocks.csv` | Your list of tickers (start small, grow to 100) |
| `requirements.txt` | Python dependencies |

> This is the data + scoring layer. The Streamlit dashboard (`app.py`) and
> GitHub Actions scheduler (`.github/workflows/daily.yml`) are the next steps.

## Setup

```bash
pip install -r requirements.txt
```

## Test it on 5 stocks first

Always test small before scaling to 100 — it confirms scraping works and
won't get you rate-limited.

```bash
python collector.py --test 5
```

You should see a leaderboard printed at the end like:

```
=== Leaderboard (2026-05-29) ===
  1. HAL             82.9%  (A)
  2. BAJAJ-AUTO      80.0%  (A)
  ...
```

## Run the full list

```bash
python collector.py
```

## Important notes

- Run on your own machine or GitHub Actions — it needs internet access.
- Screener.in ticker format is the NSE symbol (e.g. `HAL`, `TCS`, `INFY`).
  Some stocks use special symbols (e.g. `BAJAJ-AUTO`).
- The scraper reads Screener's public "top ratios" box. If Screener changes
  its HTML, update the selectors in `collector.py -> fetch_screener()`.
- Keep the politeness delays in `config.py`. Lowering them risks an IP block.
- Free tools occasionally fail. The `fetch_ok` flag marks stocks whose data
  didn't load so you can spot stale entries.

## Scoring scale

Each parameter scores 3 (strong), 2 (average), or 1 (weak). Total is summed and
shown as a percentage and grade. Thresholds live in `config.py` — adjust them to
match your own investing style.

## Next steps

1. Confirm the collector works on 5 stocks.
2. Grow `stocks.csv` to your full 100.
3. Add `app.py` (Streamlit dashboard with leaderboard, screener, portfolio).
4. Add `.github/workflows/daily.yml` for free daily automation.

> Not financial advice. For research and educational use only. Always consult a
> SEBI-registered advisor before investing.
