"""
collector.py
Batch data collector for the India wealth-creation tracker.

Fetches the LIVE priority parameters from free sources:
  - yfinance     -> price + 52-week momentum
  - Screener.in  -> ROE, ROCE, revenue growth, profit/EPS growth,
                    revenue growth acceleration, operating margin (OPM),
                    dividend yield, plus filter fields (D/E, pledge, etc.)

Usage:
    python collector.py            # all stocks in stocks.csv
    python collector.py --test 5   # first 5 stocks only (for testing)
"""

import sys
import csv
import time
import re

import requests
from bs4 import BeautifulSoup

try:
    import yfinance as yf
except ImportError:
    yf = None

import config
import database
import scorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_tickers():
    """Return a list of (yahoo_ticker, screener_symbol) tuples.

    stocks.csv may include an optional 'screener_symbol' column for stocks
    where Screener.in uses a different symbol than Yahoo (e.g. a numeric BSE
    code). If blank or absent, the Yahoo ticker is used for Screener too.
    """
    rows = []
    with open(config.STOCK_LIST_FILE, newline="") as f:
        for row in csv.DictReader(f):
            t = (row.get("ticker") or "").strip().upper()
            if not t:
                continue
            override = (row.get("screener_symbol") or "").strip()
            rows.append((t, override or t))
    return rows


# Index membership: 2 = Nifty 50, 1 = Nifty 500, absent = neither.
# Loaded once from an optional index_members.csv (columns: ticker,index).
_INDEX_CACHE = None


def load_index_members():
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    members = {}
    try:
        with open(config.INDEX_MEMBERS_FILE, newline="") as f:
            for row in csv.DictReader(f):
                t = (row.get("ticker") or "").strip().upper()
                idx = (row.get("index") or "").strip()
                if not t:
                    continue
                members[t] = 2 if idx == "50" else 1
    except FileNotFoundError:
        pass  # No index file -> index_member stays None (skipped, not penalised)
    _INDEX_CACHE = members
    return members


class NotFound(Exception):
    """Raised when a ticker page genuinely does not exist (HTTP 404).
    These are permanent errors, so we never retry them."""
    pass


def _retry(fn, *args, **kwargs):
    last_err = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except NotFound as e:
            # Permanent: wrong/unknown ticker. Skip immediately, no retries.
            print(f"    not found on Screener (check ticker symbol): {e}")
            return None
        except Exception as e:
            last_err = e
            wait = config.RETRY_BACKOFF * attempt
            print(f"    retry {attempt}/{config.MAX_RETRIES}: {e} (wait {wait}s)")
            time.sleep(wait)
    print(f"    giving up: {last_err}")
    return None


def _num(text):
    if not text:
        return None
    m = re.search(r"-?[\d,]+\.?\d*", text.replace(",", ""))
    return float(m.group()) if m else None


# ---------------------------------------------------------------------------
# yfinance: price + 52-week momentum
# ---------------------------------------------------------------------------
def fetch_price_data(yahoo_tickers):
    out = {}
    if yf is None:
        print("yfinance not installed - skipping price data")
        return out
    yf_tickers = [f"{t}.NS" for t in yahoo_tickers]
    print(f"Fetching 1y price history for {len(yf_tickers)} stocks...")
    data = _retry(yf.download, yf_tickers, period="1y",
                  group_by="ticker", progress=False, threads=True)
    if data is None:
        return out
    for t in yahoo_tickers:
        try:
            df = data[f"{t}.NS"] if len(yahoo_tickers) > 1 else data
            closes = df["Close"].dropna()
            if len(closes) < 2:
                continue
            first, last = closes.iloc[0], closes.iloc[-1]
            out[t] = {
                "price": round(float(last), 2),
                "price_momentum_52w": round(100 * (last - first) / first, 1),
            }
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Screener.in parsing
# ---------------------------------------------------------------------------
def _parse_top_ratios(soup):
    out = {}
    for li in soup.select("ul#top-ratios li"):
        name_el = li.select_one(".name")
        val_el = li.select_one(".value")
        if not name_el or not val_el:
            continue
        name = name_el.get_text(strip=True).lower()
        val = _num(val_el.get_text(strip=True))
        out[name] = val
    return out


def _parse_ranges(soup):
    """Parse Screener's compounded-growth ranges tables."""
    out = {}
    for table in soup.select("table.ranges-table"):
        head = table.select_one("th")
        if not head:
            continue
        htext = head.get_text(strip=True).lower()
        rows = {}
        for tr in table.select("tr"):
            tds = tr.select("td")
            if len(tds) == 2:
                label = tds[0].get_text(strip=True).lower().rstrip(":")
                rows[label] = _num(tds[1].get_text(strip=True))
        if "sales growth" in htext:
            out["sales_ttm"] = rows.get("ttm")
            out["sales_3y"] = rows.get("3 years")
        elif "profit growth" in htext:
            out["profit_ttm"] = rows.get("ttm")
            out["profit_3y"] = rows.get("3 years")
    return out


def _parse_opm(soup):
    """Find the most recent OPM % from the P&L data tables."""
    for table in soup.select("table.data-table"):
        for tr in table.select("tr"):
            cells = tr.select("td")
            if not cells:
                continue
            label = cells[0].get_text(strip=True).lower()
            if label.startswith("opm"):
                vals = [_num(c.get_text(strip=True)) for c in cells[1:]]
                vals = [v for v in vals if v is not None]
                if vals:
                    return vals[-1]
    return None


def _parse_section_rows(soup, section_id):
    """Return {row_label: [yearly values]} for a Screener section table."""
    sec = soup.select_one(f"section#{section_id}")
    if not sec:
        return {}
    table = sec.select_one("table.data-table")
    if not table:
        return {}
    rows = {}
    for tr in table.select("tbody tr"):
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).lower().rstrip("+").strip()
        vals = [_num(c.get_text(strip=True)) for c in cells[1:]]
        rows[label] = [v for v in vals if v is not None]
    return rows


def _section_headers(soup, section_id):
    """Return the year/period column labels for a Screener section table."""
    sec = soup.select_one(f"section#{section_id}")
    if not sec:
        return []
    table = sec.select_one("table.data-table")
    if not table:
        return []
    heads = [th.get_text(strip=True) for th in table.select("thead th")]
    return heads[1:] if len(heads) > 1 else []


def _parse_annual_history(soup, n=4):
    """Compute the last n years of the ratios that Screener only publishes
    annually: ROE, ROCE, D/E, OCF, FCF, CFO/OP, FCF/Net-Profit (plus annual
    OPM and Net Margin). Computed from the annual P&L, balance-sheet and
    cash-flow tables so the definitions stay consistent."""
    pl = _parse_section_rows(soup, "profit-loss")
    bs = _parse_section_rows(soup, "balance-sheet")
    cf = _parse_section_rows(soup, "cash-flow")
    labels = _section_headers(soup, "profit-loss")

    sales = pl.get("sales") or pl.get("revenue") or []
    op = pl.get("operating profit") or []
    net = pl.get("net profit") or []
    eqcap = bs.get("equity capital") or []
    reserves = bs.get("reserves") or []
    borrow = bs.get("borrowings") or []
    cfo = cf.get("cash from operating activity") or []
    cfi = cf.get("cash from investing activity") or []

    # The P&L table usually carries a trailing "TTM" column that the balance
    # sheet and cash-flow tables do not. Detect it from the headers and drop
    # the last P&L value column so all tables align on the same fiscal years.
    if labels and labels[-1].strip().upper() == "TTM":
        labels = labels[:-1]
        sales = sales[:-1] if sales else sales
        op = op[:-1] if op else op
        net = net[:-1] if net else net

    # P&L often has a trailing TTM column that the balance sheet lacks.
    # Align everything to the shortest length, counting from the END.
    series_list = [sales, op, net, eqcap, reserves, borrow, cfo, cfi]
    present = [s for s in series_list if s]
    if not present:
        return {}
    L = min(len(s) for s in present)
    if L == 0:
        return {}

    def tail(s):
        return s[-L:] if len(s) >= L else [None] * (L - len(s)) + s

    sales, op, net = tail(sales), tail(op), tail(net)
    eqcap, reserves, borrow = tail(eqcap), tail(reserves), tail(borrow)
    cfo, cfi = tail(cfo), tail(cfi)
    year_labels = labels[-L:] if len(labels) >= L else labels

    def safe_div(a, b, mult=1.0, nd=1):
        out = []
        for i in range(L):
            try:
                num, den = a[i], b[i]
                if num is None or den in (None, 0):
                    out.append(None)
                else:
                    out.append(round(mult * num / den, nd))
            except (IndexError, TypeError):
                out.append(None)
        return out

    equity = [(eqcap[i] or 0) + (reserves[i] or 0) for i in range(L)]
    capital_employed = [equity[i] + (borrow[i] or 0) for i in range(L)]
    fcf = [((cfo[i] or 0) + (cfi[i] or 0)) if (cfo[i] is not None
            and cfi[i] is not None) else None for i in range(L)]

    out = {
        "labels": year_labels[-n:],
        "ROE %": safe_div(net, equity, 100)[-n:],
        "ROCE %": safe_div(op, capital_employed, 100)[-n:],
        "D/E": safe_div(borrow, equity, 1, 2)[-n:],
        "OCF": [round(v) if v is not None else None for v in cfo][-n:],
        "FCF": [round(v) if v is not None else None for v in fcf][-n:],
        "CFO/OP": safe_div(cfo, op, 1, 2)[-n:],
        "FCF/Net Profit": safe_div(fcf, net, 1, 2)[-n:],
        "OPM %": safe_div(op, sales, 100)[-n:],
        "Net Margin %": safe_div(net, sales, 100)[-n:],
    }
    return out


def labels_ok(a, b):
    """Both lists non-empty and same length (for safe element-wise math)."""
    return bool(a) and bool(b) and len(a) == len(b)


def _parse_checklist_data(soup):
    """Attempt to scrape the harder 'research checklist' data points from
    Screener. Many will be blank (the data isn't on Screener) — expected and
    honest. Returns whatever could be found."""
    out = {}
    bs = _parse_section_rows(soup, "balance-sheet")
    sh = _parse_section_rows(soup, "shareholding")
    pl = _parse_section_rows(soup, "profit-loss")

    # Cash position (financial health)
    cash = None
    for key in ("cash equivalents", "cash & bank", "cash and bank",
                "cash and cash equivalents"):
        if key in bs and bs[key]:
            cash = bs[key][-1]
            break
    out["cash_equivalents"] = cash

    # Promoter / insider activity
    prom = None
    for label, vals in sh.items():
        if "promoter" in label and vals:
            prom = vals
            break
    if prom:
        out["promoter_holding_latest"] = prom[-1]
        out["promoter_holding_change"] = (round(prom[-1] - prom[-2], 2)
                                          if len(prom) >= 2 else None)

    # Margin trends (direction over available years)
    sales = pl.get("sales") or pl.get("revenue") or []
    op = pl.get("operating profit") or []
    net = pl.get("net profit") or []
    if labels_ok(op, sales):
        s = [100 * op[i] / sales[i] for i in range(len(sales)) if sales[i]]
        if len(s) >= 2:
            out["opm_trend"] = ("improving" if s[-1] > s[0]
                                else "declining" if s[-1] < s[0] else "flat")
    if labels_ok(net, sales):
        s = [100 * net[i] / sales[i] for i in range(len(sales)) if sales[i]]
        if len(s) >= 2:
            out["net_margin_trend"] = ("improving" if s[-1] > s[0]
                                       else "declining" if s[-1] < s[0] else "flat")

    # Pros & Cons text (Screener sometimes flags risks)
    pros_box = soup.select_one("div.pros")
    cons_box = soup.select_one("div.cons")
    out["pros"] = ([li.get_text(strip=True) for li in pros_box.select("li")]
                   if pros_box else [])
    out["cons"] = ([li.get_text(strip=True) for li in cons_box.select("li")]
                   if cons_box else [])
    blob = " ".join(out["cons"]).lower()
    out["contingent_flag"] = next(
        ("Flagged in Screener cons — verify in annual report"
         for kw in ("contingent", "litigation", "dispute", "default")
         if kw in blob), None)

    return out


def _parse_quarterly_history(soup, n=4):
    """Capture the last n quarters of P&L metrics that Screener reports
    quarterly: Sales, OPM %, Net Profit — plus computed Net Margin.
    Returns a dict with quarter labels and each series (oldest->newest)."""
    sec = soup.select_one("section#quarters")
    if not sec:
        return {}
    table = sec.select_one("table.data-table")
    if not table:
        return {}

    # Quarter labels from the header row (skip the first blank cell)
    heads = [th.get_text(strip=True) for th in table.select("thead th")]
    labels = heads[1:] if len(heads) > 1 else []

    rows = {}
    for tr in table.select("tbody tr"):
        cells = tr.select("td")
        if len(cells) < 2:
            continue
        lbl = cells[0].get_text(strip=True).lower().rstrip("+").strip()
        rows[lbl] = [_num(c.get_text(strip=True)) for c in cells[1:]]

    sales = rows.get("sales") or rows.get("revenue") or []
    opm = rows.get("opm %") or rows.get("opm") or []
    net = rows.get("net profit") or []

    # Net margin per quarter = net profit / sales * 100
    net_margin = []
    for i in range(min(len(sales), len(net))):
        if sales[i]:
            net_margin.append(round(100 * net[i] / sales[i], 1))
        else:
            net_margin.append(None)

    def tail(series):
        return series[-n:] if series else []

    return {
        "labels": labels[-n:] if labels else [],
        "Sales": tail(sales),
        "OPM %": tail(opm),
        "Net Profit": tail(net),
        "Net Margin %": tail(net_margin),
    }


def _growth(series):
    """Year-over-year % growth from the last two values of a series."""
    if not series or len(series) < 2:
        return None
    prev, last = series[-2], series[-1]
    if prev is None or last is None or prev == 0:
        return None
    return round(100 * (last - prev) / abs(prev), 1)


def _parse_cashflow(soup):
    """Return OCF growth, approx FCF growth, approx FCF/net-profit, and
    CFO/Operating-Profit (cash conversion of the core operating engine)."""
    cf = _parse_section_rows(soup, "cash-flow")
    pl = _parse_section_rows(soup, "profit-loss")

    cfo = cf.get("cash from operating activity")
    cfi = cf.get("cash from investing activity")
    net_profit = pl.get("net profit")
    operating_profit = pl.get("operating profit")

    out = {"ocf_growth": _growth(cfo)}

    # Approximate FCF = operating cash flow + investing cash flow
    # (investing is mostly capex and is negative). This is a rough proxy
    # because Screener lumps capex with other investing items.
    fcf_series = None
    if cfo and cfi:
        n = min(len(cfo), len(cfi))
        fcf_series = [cfo[-n + i] + cfi[-n + i] for i in range(n)]
    out["fcf_growth"] = _growth(fcf_series)

    if fcf_series and net_profit and net_profit[-1] not in (None, 0):
        out["fcf_to_profit"] = round(fcf_series[-1] / net_profit[-1], 2)
    else:
        out["fcf_to_profit"] = None

    # CFO / Operating Profit: how well operating profit converts to cash.
    # Uses the latest year of each. This is a clean ratio (no approximation),
    # since both figures come directly from Screener's tables.
    if cfo and operating_profit and operating_profit[-1] not in (None, 0):
        out["cfo_to_op"] = round(cfo[-1] / operating_profit[-1], 2)
    else:
        out["cfo_to_op"] = None

    return out


def _parse_risk_metrics(soup):
    """Tier-4 risk metrics from the P&L: interest coverage and net margin."""
    pl = _parse_section_rows(soup, "profit-loss")

    operating_profit = pl.get("operating profit")
    interest = pl.get("interest")
    net_profit = pl.get("net profit")
    sales = pl.get("sales") or pl.get("revenue")

    out = {"interest_coverage": None, "net_margin": None}

    # Interest Coverage = Operating Profit (EBIT proxy) / Interest expense
    if operating_profit and interest and interest[-1] not in (None, 0):
        out["interest_coverage"] = round(operating_profit[-1] / interest[-1], 1)
    elif operating_profit and interest and interest[-1] == 0:
        # No interest expense at all = effectively infinite coverage (debt-free)
        out["interest_coverage"] = 999.0

    # Net Profit Margin = Net Profit / Sales (latest year), as %
    if net_profit and sales and sales[-1] not in (None, 0):
        out["net_margin"] = round(100 * net_profit[-1] / sales[-1], 1)

    return out


def _parse_fii(soup):
    """Return change (pp) in FII holding over the last two reported quarters."""
    sh = _parse_section_rows(soup, "shareholding")
    for label, vals in sh.items():
        if "fii" in label and len(vals) >= 2:
            return round(vals[-1] - vals[-2], 2)
    return None


def _parse_filter_fields(soup):
    """D/E, current ratio, promoter holding, pledge - these are NOT in the
    top-ratios box, so we derive them from the balance sheet and shareholding
    sections of the Screener page."""
    bs = _parse_section_rows(soup, "balance-sheet")
    sh = _parse_section_rows(soup, "shareholding")

    out = {"debt_to_equity": None, "current_ratio": None,
           "promoter_holding": None, "promoter_pledge": 0}

    # Debt to Equity = Borrowings / Equity (Equity Capital + Reserves), latest yr
    borrow = bs.get("borrowings")
    equity_cap = bs.get("equity capital")
    reserves = bs.get("reserves")
    if borrow and equity_cap and reserves:
        n = min(len(borrow), len(equity_cap), len(reserves))
        eq = equity_cap[-1] + reserves[-1]
        if eq:
            out["debt_to_equity"] = round(borrow[-1] / eq, 2)

    # Current Ratio = Other Assets / Other Liabilities is unreliable on Screener;
    # use the simpler Total Current Assets / Current Liabilities if present.
    # Screener's balance sheet lumps these, so we approximate with
    # (Other Assets) / (Other Liabilities) only when both exist.
    oa = bs.get("other assets")
    ol = bs.get("other liabilities")
    if oa and ol and ol[-1]:
        out["current_ratio"] = round(oa[-1] / ol[-1], 2)

    # Promoter holding (latest) and pledge from the shareholding section
    for label, vals in sh.items():
        if "promoter" in label and vals:
            out["promoter_holding"] = vals[-1]
            break

    return out


def _fetch_and_parse(url):
    """Fetch one Screener URL and return parsed values, or None on 404."""
    resp = requests.get(url, headers=config.REQUEST_HEADERS, timeout=20)
    if resp.status_code == 404:
        return None, 404
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    top = _parse_top_ratios(soup)
    ranges = _parse_ranges(soup)
    cashflow = _parse_cashflow(soup)
    return (soup, top, ranges, cashflow), 200


def _coverage(parsed):
    """Count how many useful fields a parse produced (to compare pages)."""
    soup, top, ranges, cashflow = parsed
    score = 0
    score += sum(1 for k in ("roe", "roce", "debt to equity") if top.get(k) is not None)
    score += sum(1 for v in ranges.values() if v is not None)
    score += sum(1 for v in cashflow.values() if v is not None)
    return score


def fetch_screener(screener_symbol):
    """Fetch fundamentals, trying consolidated first, then standalone, and
    keeping whichever page yielded more data (handles companies that only
    publish standalone numbers, e.g. single-segment businesses)."""
    base = f"https://www.screener.in/company/{screener_symbol}"

    consolidated, code_c = _fetch_and_parse(f"{base}/consolidated/")
    standalone, code_s = _fetch_and_parse(f"{base}/")

    # Both 404 -> genuinely missing
    if consolidated is None and standalone is None:
        raise NotFound(f"{screener_symbol} (HTTP 404)")

    # Pick whichever parsed page has more usable data
    candidates = [p for p in (consolidated, standalone) if p is not None]
    parsed = max(candidates, key=_coverage)

    soup, top, ranges, cashflow = parsed

    # Revenue growth + acceleration
    rev_ttm = ranges.get("sales_ttm")
    rev_3y = ranges.get("sales_3y")
    accel = None
    if rev_ttm is not None and rev_3y is not None:
        accel = round(rev_ttm - rev_3y, 1)

    filt = _parse_filter_fields(soup)
    risk = _parse_risk_metrics(soup)
    quarterly = _parse_quarterly_history(soup)
    annual = _parse_annual_history(soup)
    checklist = _parse_checklist_data(soup)

    return {
        "roe":                  top.get("roe"),
        "roce":                 top.get("roce"),
        "dividend_payout":      top.get("dividend yield"),
        "opm":                  _parse_opm(soup),
        "revenue_growth":       rev_ttm if rev_ttm is not None else rev_3y,
        "revenue_growth_accel": accel,
        "eps_growth":           ranges.get("profit_ttm"),
        "profit_growth":        ranges.get("profit_ttm"),
        "ocf_growth":           cashflow.get("ocf_growth"),
        "fcf_growth":           cashflow.get("fcf_growth"),
        "fcf_to_profit":        cashflow.get("fcf_to_profit"),
        "cfo_to_op":            cashflow.get("cfo_to_op"),
        "fii_buying":           _parse_fii(soup),
        # Tier-4 risk protectors (scored)
        "interest_coverage":    risk["interest_coverage"],
        "net_margin":           risk["net_margin"],
        "debt_to_equity_score": filt["debt_to_equity"],
        # filter fields (derived from balance sheet / shareholding sections)
        "debt_to_equity":       filt["debt_to_equity"],
        "current_ratio":        filt["current_ratio"],
        "promoter_holding":     filt["promoter_holding"],
        "promoter_pledge":      top.get("pledged percentage") or filt["promoter_pledge"],
        # quarterly + annual + checklist history (stored separately)
        "_history":             {"quarterly": quarterly, "annual": annual,
                                 "checklist": checklist},
    }


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
def run(limit=None):
    database.init_db()
    pairs = load_tickers()          # list of (yahoo_ticker, screener_symbol)
    if limit:
        pairs = pairs[:limit]
    print(f"Collecting data for {len(pairs)} stocks\n")

    yahoo_tickers = [y for y, _ in pairs]
    price_data = fetch_price_data(yahoo_tickers)
    index_members = load_index_members()

    ok_count = 0
    failed = []
    for i, (ticker, screener_symbol) in enumerate(pairs, 1):
        tag = ticker if ticker == screener_symbol else f"{ticker} (screener: {screener_symbol})"
        print(f"[{i}/{len(pairs)}] {tag}")
        values = dict(price_data.get(ticker, {}))
        fundamentals = _retry(fetch_screener, screener_symbol)
        if fundamentals:
            values.update(fundamentals)
            ok_count += 1
            fetch_ok = True
        else:
            fetch_ok = False
            failed.append(ticker)
        # Index membership is keyed off the ticker in stocks.csv
        values["index_member"] = index_members.get(ticker)
        # Pull out quarterly history (not a scored field) and store separately
        hist = values.pop("_history", None)
        if hist:
            database.save_history(ticker, hist)
        database.save_raw(ticker, values, fetch_ok=fetch_ok)
        time.sleep(config.SCREENER_DELAY)

    print(f"\nFetched fundamentals for {ok_count}/{len(pairs)} stocks")
    if failed:
        print(f"Failed (check these ticker symbols on screener.in): "
              f"{', '.join(failed)}")

    print("Scoring all stocks (tier-weighted)...")
    scorer.score_all(yahoo_tickers)

    latest, rows = database.latest_leaderboard()
    print(f"\n=== Priority Leaderboard ({latest}) ===")
    for rank, (tk, total, mx, pct, grade) in enumerate(rows, 1):
        print(f"{rank:3}. {tk:14} {pct:5.1f}%  ({grade})  [{total}/{mx} pts]")


if __name__ == "__main__":
    lim = None
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        lim = int(sys.argv[2])
    run(limit=lim)
