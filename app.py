"""
app.py
Streamlit dashboard for the India wealth-creation tracker (priority edition).

Scores stocks on the top 3 tiers of direct-traceable wealth-creation
parameters, weighted by price-impact priority (Tier 1 x3, Tier 2 x2, Tier 3 x1).

Run with:
    python -m streamlit run app.py
"""

import sqlite3
import pandas as pd
import streamlit as st

import config
import scorer
import database

APP_VERSION = "v2.0"
APP_VERSION_DATE = "Jun 2026"   # bump both when you release a new version

st.set_page_config(page_title="India Stock Wealth Tracker",
                   page_icon="📈", layout="wide")


# --------------------------------------------------------------------------- #
# Password gate (two roles: owner sees everything, viewer sees analysis only)
# --------------------------------------------------------------------------- #
# Passwords are read from Streamlit secrets (set in Streamlit Cloud settings):
#   app_password         -> OWNER: full access incl. holdings-based tabs
#   viewer_password      -> VIEWER: analysis tabs only, holdings hidden
# If no password is configured (e.g. running locally), access is full ("owner").
def _check_password():
    owner_pw = viewer_pw = None
    try:
        owner_pw = st.secrets.get("app_password")
        viewer_pw = st.secrets.get("viewer_password")
    except Exception:
        owner_pw = viewer_pw = None

    # No owner password configured -> local use, full access
    if not owner_pw:
        st.session_state["role"] = "owner"
        return

    if st.session_state.get("role"):
        return

    st.title("🔒 Stock Wealth Tracker")
    st.write("This dashboard is password-protected.")
    pwd = st.text_input("Enter password", type="password")
    if pwd:
        if pwd == owner_pw:
            st.session_state["role"] = "owner"
            st.rerun()
        elif viewer_pw and pwd == viewer_pw:
            st.session_state["role"] = "viewer"
            st.rerun()
        else:
            st.error("Incorrect password.")
    st.stop()


_check_password()
IS_OWNER = st.session_state.get("role") == "owner"



def load_holdings():
    """Load holdings as {ticker: invested_value}.

    Priority:
      1. Streamlit secrets key 'holdings_csv' (used when hosted online, so the
         data never has to live in a public repo), OR
      2. a local holdings.csv file (used when running on your own PC).
    Both use the format:  ticker,invested_value  (one per line, header row ok).
    """
    import csv as _csv
    import io as _io

    text = None
    # 1. Try Streamlit secrets (online, private)
    try:
        text = st.secrets.get("holdings_csv")
    except Exception:
        text = None

    # 2. Fall back to local file
    if not text:
        try:
            with open("holdings.csv", newline="") as f:
                text = f.read()
        except FileNotFoundError:
            return {}

    holdings = {}
    for row in _csv.DictReader(_io.StringIO(text)):
        t = (row.get("ticker") or "").strip().upper()
        v = row.get("invested_value")
        if t and v:
            try:
                holdings[t] = float(v)
            except ValueError:
                pass
    return holdings


# --------------------------------------------------------------------------- #
# Research factors (manual +/- entries per stock) — saved locally
# --------------------------------------------------------------------------- #
# Each stock can have unlimited factors. Each factor has a description and a
# score from -3 to +3 (positive = favourable, negative = a concern).
# Stored one row per factor: ticker, description, score
RESEARCH_FILE = "research_notes.csv"


def load_research():
    """Load research factors as {ticker: [ {desc, score}, ... ]}."""
    import csv as _csv
    out = {}
    try:
        with open(RESEARCH_FILE, newline="", encoding="utf-8") as f:
            for row in _csv.DictReader(f):
                t = (row.get("ticker") or "").strip().upper()
                desc = (row.get("description") or "").strip()
                try:
                    score = int(row.get("score"))
                except (TypeError, ValueError):
                    continue
                if t and desc:
                    out.setdefault(t, []).append(
                        {"desc": desc, "score": score})
    except FileNotFoundError:
        pass
    return out


def _write_research(data):
    """Write the whole {ticker: [factors]} structure back to the CSV."""
    import csv as _csv
    with open(RESEARCH_FILE, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=["ticker", "description", "score"])
        w.writeheader()
        for t in sorted(data):
            for fac in data[t]:
                w.writerow({"ticker": t, "description": fac["desc"],
                            "score": fac["score"]})


def add_research_factor(ticker, desc, score):
    data = load_research()
    data.setdefault(ticker.upper(), []).append(
        {"desc": desc.strip(), "score": int(score)})
    _write_research(data)


def delete_research_factor(ticker, index):
    data = load_research()
    facs = data.get(ticker.upper(), [])
    if 0 <= index < len(facs):
        facs.pop(index)
        data[ticker.upper()] = facs
        _write_research(data)


def research_totals(ticker, research_data):
    """Return (total, count, average) for a stock's manual factors."""
    facs = research_data.get(ticker.upper(), [])
    if not facs:
        return 0, 0, None
    total = sum(f["score"] for f in facs)
    return total, len(facs), round(total / len(facs), 2)


@st.cache_data(ttl=300)
def load_data():
    con = sqlite3.connect(config.DB_PATH)
    latest = pd.read_sql("SELECT MAX(date) AS d FROM daily_scores", con)["d"][0]
    if latest is None:
        con.close()
        return None, None, None
    scores = pd.read_sql(
        "SELECT * FROM daily_scores WHERE date = ? ORDER BY pct DESC",
        con, params=(latest,))
    raw = pd.read_sql("SELECT * FROM raw_data WHERE date = ?",
                      con, params=(latest,))
    history = pd.read_sql(
        "SELECT date, ticker, pct FROM daily_scores ORDER BY date", con)
    con.close()
    return latest, scores.merge(raw, on=["date", "ticker"], how="left"), history


def grade_dot(g):
    return {"A+": "🟢", "A": "🟢", "B": "🔵", "C": "🟡", "D": "🔴"}.get(g, "⚪")


@st.cache_data(ttl=300)
def load_discovery():
    """Load the discovery snapshot CSV (exported from the discovery tool and
    copied into this folder). Returns a scored dataframe or None."""
    import os as _os
    if not _os.path.exists("discovery_snapshot.csv"):
        return None
    try:
        d = pd.read_csv("discovery_snapshot.csv")
        if d.empty:
            return None
        if "pct" in d.columns:
            d = d.sort_values("pct", ascending=False)
        return d
    except Exception:
        return None


latest_date, df, history = load_data()
st.title(f"📈 India Stock Wealth-Creation Tracker  ·  {APP_VERSION}")

if df is None or df.empty:
    st.warning("No data yet. Run `python collector.py --test 5` first, "
               "then refresh.")
    st.stop()

live_params = [k for k, p in config.PRIORITY_PARAMS.items() if p.get("live")]
st.caption(f"Latest data: **{latest_date}**  •  {len(df)} stocks  •  "
           f"Tier-weighted score on {len(live_params)} live priority "
           f"parameters (of {len(config.PRIORITY_PARAMS)} total)")

if IS_OWNER:
    (tab1, tab2, tab6, tab3, tab5, tab8, tab9, tab10, tab11, ctab,
     dtab1, dtab2, dtab5) = st.tabs(
        ["🏆 Board", "📊 Compare", "🔢 Values",
         "🔍 Screen", "🔬 Deep",
         "🌱 Invest", "⚖️ Rebal", "📋 Research",
         "📈 History",
         "🥇 Combined",
         "🔭 Disc: Board", "🔭 Disc: Values", "🔭 Disc: Deep Dive"])
else:
    # Viewer role: analysis tabs only — holdings-based tabs are hidden.
    (tab1, tab2, tab6, tab3, tab5, tab10, tab11, ctab,
     dtab1, dtab2, dtab5) = st.tabs(
        ["🏆 Board", "📊 Compare", "🔢 Values",
         "🔍 Screen", "🔬 Deep", "📋 Research",
         "📈 History",
         "🥇 Combined",
         "🔭 Disc: Board", "🔭 Disc: Values", "🔭 Disc: Deep Dive"])
    tab8 = tab9 = None   # holdings tabs not shown for viewers


# --------------------------------------------------------------------------- #
# TAB 1 - Leaderboard
# --------------------------------------------------------------------------- #
with tab1:
    st.subheader("Ranked by tier-weighted priority score")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stocks", len(df))
    c2.metric("Top score", f"{df['pct'].max():.1f}%")
    c3.metric("Average", f"{df['pct'].mean():.1f}%")
    c4.metric("Grade A / A+", int(df["grade"].isin(["A", "A+"]).sum()))

    board = df[["ticker", "pct", "grade", "total_score", "max_score"]].copy()
    board.insert(0, "Rank", range(1, len(board) + 1))
    board["Grade"] = board["grade"].apply(lambda g: f"{grade_dot(g)} {g}")
    board = board.rename(columns={"ticker": "Stock", "pct": "Score %",
                                  "total_score": "Wtd Pts", "max_score": "Max"})

    # Height tall enough to show every row without an internal scrollbar
    # (~35px per row + header), so the full list is visible above the chart.
    full_height = 38 + 35 * len(board)
    st.dataframe(
        board[["Rank", "Stock", "Score %", "Grade", "Wtd Pts", "Max"]],
        width='stretch', hide_index=True, height=full_height,
        column_config={"Score %": st.column_config.ProgressColumn(
            "Score %", min_value=0, max_value=100, format="%.1f%%")})

    st.subheader("Score comparison")
    st.bar_chart(df.set_index("ticker")["pct"], height=300)

# --------------------------------------------------------------------------- #
# TAB 2 - Compare All (per-parameter matrix, sorted by score descending)
# --------------------------------------------------------------------------- #
with tab2:
    st.subheader("All stocks vs all parameters")
    st.caption("Every stock (rows, ranked by score) against all 13 parameters "
               "(columns). Cells show each parameter's score: 3 = strong, "
               "2 = average, 1 = weak. Hover a cell to see the column name.")

    live = [k for k, p in config.PRIORITY_PARAMS.items() if p.get("live")]
    # Short column headers so the matrix fits in one window
    short_labels = {
        "revenue_growth_accel": "Rev Accel",
        "revenue_growth": "Rev Gr",
        "eps_growth": "EPS Gr",
        "price_momentum_52w": "Momentum",
        "fcf_growth": "FCF Gr",
        "fii_buying": "FII",
        "roe": "ROE",
        "roce": "ROCE",
        "opm": "OPM",
        "dividend_payout": "Div",
        "ocf_growth": "OCF Gr",
        "fcf_to_profit": "FCF/NP",
        "cfo_to_op": "CFO/OP",
        "debt_to_equity_score": "D/E",
        "interest_coverage": "Int Cov",
        "net_margin": "Net Mgn",
    }

    # Build a matrix of 1/2/3 scores, one row per stock (already score-sorted)
    matrix = []
    for _, r in df.iterrows():
        row = {"Stock": r["ticker"], "Score %": r["pct"], "Grade": r["grade"]}
        for k in live:
            s = scorer.score_value(k, r.get(k))
            row[short_labels.get(k, k)] = s   # may be None if no data
        matrix.append(row)
    mat = pd.DataFrame(matrix)

    param_cols = [short_labels.get(k, k) for k in live]

    def color_score(v):
        if v == 3:
            return "background-color: #d4f0df; color: #1a6e3c;"
        if v == 2:
            return "background-color: #fff3cd; color: #7a5200;"
        if v == 1:
            return "background-color: #fde8e8; color: #921f1f;"
        return "background-color: #f0f0f0; color: #999;"  # no data

    styled = (mat.style
              .map(color_score, subset=param_cols)
              .format({"Score %": "{:.1f}%"})
              .format({c: lambda v: "-" if pd.isna(v) else f"{int(v)}"
                       for c in param_cols}))

    # Use a fixed, screen-sized height so the table scrolls INTERNALLY.
    # Streamlit keeps the column headers frozen at the top during internal
    # scroll, so the parameter names stay visible as you move down the list.
    st.dataframe(styled, width='stretch', hide_index=True, height=600)

    st.caption("🟢 3 = Strong   🟡 2 = Average   🔴 1 = Weak   ⬜ no data  "
               "— scroll within the table; headers stay pinned.")

# --------------------------------------------------------------------------- #
# TAB 6 - Compare Values (actual numbers, colored by their score)
# --------------------------------------------------------------------------- #
with tab6:
    st.subheader("All stocks vs all parameters — actual values")
    st.caption("Same layout as Compare All, but showing the real numbers "
               "(ROE %, D/E, growth %, ratios) instead of 1/2/3 scores. "
               "Cells are still colored by quality so you can read value and "
               "rating together.")

    live_v = [k for k, p in config.PRIORITY_PARAMS.items() if p.get("live")]
    # Reuse the same short labels defined in the Compare All tab
    short_labels_v = {
        "revenue_growth_accel": "Rev Accel", "revenue_growth": "Rev Gr",
        "eps_growth": "EPS Gr", "price_momentum_52w": "Momentum",
        "fcf_growth": "FCF Gr", "fii_buying": "FII", "roe": "ROE",
        "roce": "ROCE", "opm": "OPM", "dividend_payout": "Div",
        "ocf_growth": "OCF Gr", "fcf_to_profit": "FCF/NP",
        "cfo_to_op": "CFO/OP", "debt_to_equity_score": "D/E",
        "interest_coverage": "Int Cov", "net_margin": "Net Mgn",
    }

    # Build a "good range" string for each parameter from its scoring rule.
    # cut3 is the threshold for a top score (3), so it defines "good".
    def good_range(key):
        p = config.PRIORITY_PARAMS[key]
        if p["direction"] == "higher":
            return f"≥ {p['cut3']:g}"
        else:
            return f"≤ {p['cut3']:g}"

    # Build two parallel matrices: one of actual values (shown) and one of
    # scores (used only to pick each cell's color).
    val_rows, score_rows = [], []

    # First row = the target/good range for each parameter (reference row)
    target_row = {"Stock": "🎯 GOOD", "Score %": float("nan"), "Grade": "—"}
    for k in live_v:
        target_row[short_labels_v.get(k, k)] = good_range(k)
    val_rows.append(target_row)
    score_rows.append({short_labels_v.get(k, k): None for k in live_v})

    for _, r in df.iterrows():
        vrow = {"Stock": r["ticker"], "Score %": r["pct"], "Grade": r["grade"]}
        srow = {}
        for k in live_v:
            label = short_labels_v.get(k, k)
            raw = r.get(k)
            vrow[label] = raw
            srow[label] = scorer.score_value(k, raw)
        val_rows.append(vrow)
        score_rows.append(srow)
    val_mat = pd.DataFrame(val_rows)
    score_mat = pd.DataFrame(score_rows).reset_index(drop=True)
    val_mat = val_mat.reset_index(drop=True)
    pcols = [short_labels_v.get(k, k) for k in live_v]

    def color_by_score(col):
        # Color each value cell according to its score in the parallel matrix.
        # The first row (target reference) gets a distinct blue tint.
        styles = []
        for i in col.index:
            if i == 0:  # target reference row
                styles.append("background-color: #e6f1fb; color: #042C53; "
                              "font-weight: 600;")
                continue
            s = score_mat.loc[i, col.name] if col.name in score_mat else None
            if s == 3:
                styles.append("background-color: #d4f0df; color: #1a6e3c;")
            elif s == 2:
                styles.append("background-color: #fff3cd; color: #7a5200;")
            elif s == 1:
                styles.append("background-color: #fde8e8; color: #921f1f;")
            else:
                styles.append("background-color: #f0f0f0; color: #999;")
        return styles

    def fmt_val(v):
        if pd.isna(v):
            return "-"
        if isinstance(v, str):   # the target-range strings
            return v
        return f"{v:g}"

    styled_v = (val_mat.style
                .apply(color_by_score, subset=pcols)
                .format({"Score %": lambda v: "" if pd.isna(v) else f"{v:.1f}%"})
                .format({c: fmt_val for c in pcols}))

    st.dataframe(styled_v, width='stretch', hide_index=True, height=600)
    st.caption("Top blue row 🎯 = the 'good' target for each parameter. "
               "Color = quality (🟢 strong / 🟡 average / 🔴 weak / ⬜ no data); "
               "number = actual value. Headers stay pinned while scrolling.")

    # ---- Explanation panel ----
    with st.expander("📖 What each parameter means and the good range"):
        explanations = {
            "revenue_growth_accel": "How much revenue growth is speeding up "
                "(this year's growth minus the 3-yr average). Positive = "
                "accelerating, which the market rewards most.",
            "revenue_growth": "Year-on-year sales growth. Higher means the "
                "business is expanding its top line.",
            "eps_growth": "Growth in earnings per share / profit. The engine "
                "of long-term stock returns.",
            "price_momentum_52w": "Price change over the last 52 weeks. "
                "Strong uptrends tend to persist.",
            "fcf_growth": "Growth in free cash flow (cash left after capex). "
                "Real cash is harder to fake than profit.",
            "fii_buying": "Change in foreign institutional holding. Rising = "
                "smart money is accumulating.",
            "roe": "Return on Equity — profit generated per rupee of "
                "shareholder money. Measures profitability.",
            "roce": "Return on Capital Employed — how efficiently total "
                "capital (debt + equity) is used. Best single quality gauge.",
            "opm": "Operating / EBITDA margin — core operating profitability "
                "as a % of sales.",
            "dividend_payout": "Dividend yield — cash returned to shareholders "
                "as a % of price.",
            "ocf_growth": "Growth in operating cash flow — is the core business "
                "generating more cash each year?",
            "fcf_to_profit": "Free cash flow as a fraction of net profit — "
                "checks that reported profit converts to real cash.",
            "cfo_to_op": "Cash from operations ÷ operating profit — cash "
                "conversion of the core engine. Near/above 1 is healthy.",
            "debt_to_equity_score": "Debt ÷ equity — financial leverage. "
                "Lower is safer (less risk in downturns).",
            "interest_coverage": "Operating profit ÷ interest — how easily the "
                "company covers its interest bills.",
            "net_margin": "Net profit ÷ sales — bottom-line profitability "
                "after all costs.",
        }
        for k in live_v:
            p = config.PRIORITY_PARAMS[k]
            label = short_labels_v.get(k, k)
            tier = config.TIER_NAME[p["tier"]]
            st.markdown(
                f"**{label}** ({p['label']}) — *{tier}*  \n"
                f"Good: **{good_range(k)}**  •  "
                f"{explanations.get(k, '')}")

# --------------------------------------------------------------------------- #
# TAB 3 - Screener
# --------------------------------------------------------------------------- #
with tab3:
    st.subheader("Filter and shortlist")
    a, b = st.columns(2)
    with a:
        min_score = st.slider("Minimum score %", 0, 100, 60)
        min_roe = st.slider("Minimum ROE %", 0, 60, 15)
    with b:
        max_de = st.slider("Maximum Debt/Equity", 0.0, 3.0, 1.0, 0.1)
        max_pledge = st.slider("Maximum Promoter Pledge %", 0, 50, 10)

    f = df.copy()
    f = f[f["pct"] >= min_score]
    # For filters, only exclude a stock if it HAS the data and fails the test.
    # Missing data does not silently drop a stock (which previously caused
    # "0 matches" when a column was unpopulated).
    f = f[(f["roe"].isna()) | (f["roe"] >= min_roe)]
    f = f[(f["debt_to_equity"].isna()) | (f["debt_to_equity"] <= max_de)]
    f = f[(f["promoter_pledge"].isna()) | (f["promoter_pledge"] <= max_pledge)]
    st.write(f"**{len(f)} stocks** match:")
    if not f.empty:
        show = f[["ticker", "pct", "grade", "roe", "roce",
                  "revenue_growth", "debt_to_equity", "promoter_pledge"]].rename(
            columns={"ticker": "Stock", "pct": "Score %", "grade": "Grade",
                     "roe": "ROE", "roce": "ROCE",
                     "revenue_growth": "Rev Gr%", "debt_to_equity": "D/E",
                     "promoter_pledge": "Pledge%"})
        st.dataframe(show, width='stretch', hide_index=True)
    else:
        st.info("No matches. Loosen the filters.")

# --------------------------------------------------------------------------- #
# TAB 5 - Deep Dive (tier-grouped)
# --------------------------------------------------------------------------- #
with tab5:
    st.subheader("Per-parameter breakdown by tier")
    stock = st.selectbox("Choose a stock", sorted(df["ticker"].tolist()))
    row = df[df["ticker"] == stock].iloc[0]
    st.metric(f"{stock} priority score", f"{row['pct']:.1f}%  ({row['grade']})")

    # Loop through every tier present in the framework (sorted), so all
    # parameters appear — including Tier 4 and any tiers added later.
    for tier in sorted(config.TIER_NAME):
        keys = [k for k, p in config.PRIORITY_PARAMS.items() if p["tier"] == tier]
        if not keys:
            continue
        st.markdown(f"**{config.TIER_NAME[tier]}**  "
                    f"_(weight ×{config.TIER_WEIGHT[tier]})_")
        recs = []
        for k in keys:
            p = config.PRIORITY_PARAMS[k]
            val = row.get(k)
            if not p.get("live"):
                recs.append({"Parameter": p["label"], "Value": "—",
                             "Score": "—", "Rating": "⏳ pending source"})
                continue
            s = scorer.score_value(k, val)
            if s is None:
                rating = "⚪ no data"
            else:
                rating = {3: "🟢 Strong", 2: "🟡 Average",
                          1: "🔴 Weak"}[s]
            recs.append({
                "Parameter": p["label"],
                "Value": "—" if val is None else str(round(val, 2)),
                "Score": "—" if s is None else str(s),
                "Rating": rating,
            })
        st.dataframe(pd.DataFrame(recs), width='stretch', hide_index=True)

    # ---- Historical trends (quarterly P&L + annual ratios) ----
    hist = database.load_history(stock)

    def render_history_table(block, period_word, metrics):
        """Render a metrics-as-rows, periods-as-columns table for a history
        block (dict with 'labels' and per-metric series)."""
        if not block or not block.get("labels"):
            return False
        labels = block["labels"]
        rows = []
        for metric in metrics:
            series = block.get(metric, [])
            if not series or all(v is None for v in series):
                continue
            rec = {"Metric": metric}
            for i, lab in enumerate(labels):
                rec[lab] = (series[i] if i < len(series)
                            and series[i] is not None else "—")
            rows.append(rec)
        if rows:
            st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)
            return True
        return False

    if hist:
        st.markdown("### Recent trends")

        q = hist.get("quarterly", {})
        a = hist.get("annual", {})

        st.markdown("**Quarterly (P&L metrics — last 4 quarters)**")
        shown_q = render_history_table(
            q, "quarter", ["Sales", "OPM %", "Net Profit", "Net Margin %"])
        if shown_q:
            opm_series = [v for v in q.get("OPM %", []) if v is not None]
            if len(opm_series) > 1:
                qlabels = q.get("labels", [])
                opm_df = pd.DataFrame(
                    {"Quarter": qlabels[:len(opm_series)],
                     "OPM %": opm_series}).set_index("Quarter")
                st.line_chart(opm_df, height=200)
        else:
            st.caption("No quarterly data available for this stock.")

        st.markdown("**Annual (returns, cash-flow & debt ratios — last 4 years)**")
        shown_a = render_history_table(
            a, "year", ["ROE %", "ROCE %", "OPM %", "Net Margin %",
                        "D/E", "OCF", "FCF", "CFO/OP", "FCF/Net Profit"])
        if shown_a:
            roce_series = [v for v in a.get("ROCE %", []) if v is not None]
            roe_series = [v for v in a.get("ROE %", []) if v is not None]
            alabels = a.get("labels", [])
            if len(roce_series) > 1 or len(roe_series) > 1:
                chart_data = {}
                m = max(len(roce_series), len(roe_series))
                if roe_series:
                    chart_data["ROE %"] = roe_series
                if roce_series:
                    chart_data["ROCE %"] = roce_series
                idx = alabels[-m:] if len(alabels) >= m else alabels
                # pad to equal length
                for kk in chart_data:
                    while len(chart_data[kk]) < len(idx):
                        chart_data[kk].insert(0, None)
                try:
                    ann_df = pd.DataFrame(chart_data, index=idx)
                    st.line_chart(ann_df, height=200)
                except Exception:
                    pass
        else:
            st.caption("Annual ratio history not available for this stock.")
        st.caption("Annual ratios are computed from Screener's yearly P&L, "
                   "balance-sheet and cash-flow tables. Period alignment is "
                   "best-effort and may occasionally be off by one period for "
                   "some companies.")
    else:
        st.caption("History will appear after the next collector run.")

    h = history[history["ticker"] == stock]
    if len(h) > 1:
        st.write("**Score trend**")
        st.line_chart(h.set_index("date")["pct"], height=250)
    else:
        st.caption("Score-trend chart appears once you have 2+ days of data.")

    # ---- Why isn't the score higher? ----
    st.markdown("### Why isn't this score higher?")

    # Plain-language meaning of a weakness in each parameter
    weak_reasons = {
        "revenue_growth_accel": "revenue growth is slowing down rather than "
            "accelerating",
        "revenue_growth": "sales are growing slowly (or shrinking)",
        "eps_growth": "profits/earnings are growing slowly or falling",
        "price_momentum_52w": "the stock price has underperformed over the "
            "past year",
        "fcf_growth": "free cash flow is not growing well",
        "fii_buying": "foreign institutions are not accumulating (or are "
            "reducing) their stake",
        "roe": "return on equity is low — modest profit per rupee of "
            "shareholder capital",
        "roce": "return on capital employed is low — capital isn't being used "
            "very efficiently",
        "opm": "operating margins are thin",
        "dividend_payout": "little or no dividend is being paid",
        "ocf_growth": "operating cash flow isn't growing",
        "fcf_to_profit": "reported profit isn't fully converting into free cash",
        "cfo_to_op": "operating profit isn't converting well into actual cash",
        "debt_to_equity": "the company carries high debt relative to equity",
        "debt_to_equity_score": "the company carries high debt relative to "
            "equity",
        "interest_coverage": "earnings only thinly cover interest payments",
        "net_margin": "the net profit margin is low",
    }

    weak, average, missing = [], [], []
    for k, p in config.PRIORITY_PARAMS.items():
        if not p.get("live"):
            continue
        val = row.get(k)
        s = scorer.score_value(k, val)
        label = p["label"].split("(")[0].strip()

        # Build the "good" target string and a readable value + unit
        if p["direction"] == "higher":
            target_str = f"≥ {p['cut3']:g}"
        else:
            target_str = f"≤ {p['cut3']:g}"
        # Unit hint: most growth/return params are %, ratios are not
        ratio_keys = {"fcf_to_profit", "cfo_to_op", "debt_to_equity_score",
                      "interest_coverage", "fii_buying", "revenue_growth_accel"}
        unit = "" if k in ratio_keys else "%"
        val_str = "no data" if val is None else f"{round(val, 2):g}{unit}"

        entry = (label, weak_reasons.get(k, ""), val_str, f"{target_str}{unit}")
        if s is None:
            missing.append(label)
        elif s == 1:
            weak.append(entry)
        elif s == 2:
            average.append(entry)

    if not weak and not average and not missing:
        st.success("This stock scores strongly across all measured "
                   "parameters — nothing is dragging it down.")
    else:
        if row["pct"] >= 80:
            st.info(f"{stock} already scores well ({row['pct']:.0f}%). "
                    "The items below are the relatively softer spots:")
        else:
            st.write(f"{stock} scores {row['pct']:.0f}%. The main things "
                     "holding it back:")

        if weak:
            st.markdown("**🔴 Weak areas (scoring 1):**")
            for label, reason, val_str, target_str in weak:
                line = f"- **{label}**: {val_str} (target {target_str})"
                if reason:
                    line += f" — {reason}"
                st.markdown(line)
        if average:
            st.markdown("**🟡 Average areas (scoring 2 — room to improve):**")
            for label, reason, val_str, target_str in average:
                line = f"- **{label}**: {val_str} (target {target_str})"
                if reason:
                    line += f" — {reason}"
                st.markdown(line)
        if missing:
            st.markdown("**⚪ No data (not counted, but limits confidence):** "
                        + ", ".join(missing))

        st.caption("These are mechanical readings from the ratings, not a "
                   "judgement on the company. A low score on one measure can "
                   "be fine depending on the business and sector — e.g. a "
                   "fast-growing small-cap may pay no dividend by choice. Use "
                   "this as a prompt for your own research, not a verdict.")

# --------------------------------------------------------------------------- #
# TAB 8 - Future Investment (top-up mode: direct new money to under-weighted)
# --------------------------------------------------------------------------- #
if IS_OWNER:
  with tab8:
    st.subheader("Future investment — top-up to target")
    st.caption("Given new money to invest, this directs it toward stocks that "
               "are BELOW their score-weighted target, moving you toward the "
               "target allocation without selling anything. Reads your current "
               "holdings from holdings.csv. Not financial advice.")

    # Load current holdings (from Streamlit secrets online, or local file)
    holdings = load_holdings()
    if not holdings:
        st.warning("No holdings found. Add a holdings.csv locally (columns "
                   "`ticker,invested_value`), or set the `holdings_csv` secret "
                   "when hosting online.")

    c1, c2, c3 = st.columns(3)
    with c1:
        new_money = st.number_input("New amount to invest (₹)",
                                    min_value=0.0, value=100000.0, step=10000.0)
    with c2:
        fi_threshold = st.slider("Min score % to include ", 0, 100, 65,
                                 key="fi_thresh")
    with c3:
        fi_cap = st.slider("Max % per stock ", 5, 100, 15, key="fi_cap")

    q = df[df["pct"] >= fi_threshold].copy()
    if q.empty:
        st.info("No stocks above the threshold.")
    elif new_money <= 0:
        st.info("Enter an amount to invest.")
    else:
        # Current value of only the qualifying stocks that you hold
        cur = {t: holdings.get(t, 0.0) for t in q["ticker"]}
        cur_total = sum(cur.values())
        future_total = cur_total + new_money

        # Target weights (score-weighted, capped) for qualifying stocks
        weights = dict(zip(q["ticker"], q["pct"].astype(float)))
        cap = fi_cap / 100.0
        tw = sum(weights.values())
        target = {t: w / tw for t, w in weights.items()}
        for _ in range(100):
            over = {t: a for t, a in target.items() if a > cap + 1e-9}
            if not over:
                break
            excess = sum(a - cap for a in over.values())
            for t in over:
                target[t] = cap
            uncapped = [t for t in target if target[t] < cap - 1e-9]
            if not uncapped:
                break
            base = sum(weights[t] for t in uncapped)
            for t in uncapped:
                target[t] += excess * (weights[t] / base)

        # Target rupee value in the COMBINED (future) portfolio
        target_val = {t: target[t] * future_total for t in target}
        # Gap = how far below target each stock currently is (only positive gaps
        # get new money; we never suggest selling)
        gap = {t: max(0.0, target_val[t] - cur.get(t, 0.0)) for t in target}
        gap_sum = sum(gap.values())

        rows = []
        if gap_sum <= 0:
            st.info("Every qualifying stock is already at or above its target. "
                    "New money can't reduce existing overweights without "
                    "selling. Consider raising the cap or threshold.")
        else:
            for t in sorted(gap, key=lambda x: -gap[x]):
                invest = new_money * (gap[t] / gap_sum)
                if invest < 1:
                    continue
                srow = q[q["ticker"] == t].iloc[0]
                rows.append({
                    "Stock": t,
                    "Score %": round(srow["pct"], 1),
                    "Grade": srow["grade"],
                    "Invested ₹": round(cur.get(t, 0.0)),
                    "Target ₹": round(target_val[t]),
                    "Invest now ₹": round(invest),
                })
            inv_df = pd.DataFrame(rows)
            st.write(f"Deploying **₹{new_money:,.0f}** across "
                     f"**{len(inv_df)}** under-weighted stocks:")
            st.dataframe(
                inv_df, width='stretch', hide_index=True,
                column_config={
                    "Invested ₹": st.column_config.NumberColumn(format="₹%d"),
                    "Target ₹": st.column_config.NumberColumn(format="₹%d"),
                    "Invest now ₹": st.column_config.NumberColumn(format="₹%d"),
                })
            st.caption(f"Invested (qualifying): ₹{cur_total:,.0f}  •  "
                       f"After investing: ₹{future_total:,.0f}")
            st.bar_chart(inv_df.set_index("Stock")["Invest now ₹"], height=300)

# --------------------------------------------------------------------------- #
# TAB 9 - Rebalance (target vs current diagnostic + optional trade list)
# --------------------------------------------------------------------------- #
if IS_OWNER:
  with tab9:
    st.subheader("Rebalance — target vs current")
    st.caption("Shows, for each holding, the score-weighted target position "
               "vs what you currently hold. View 1 is informational (no need "
               "to sell). View 2 shows the exact sell+buy trades for a full "
               "rebalance. Not financial advice — selling crystallises losses "
               "and has tax/cost implications.")

    holdings9 = load_holdings()

    rb_threshold = st.slider("Min score % to include in target", 0, 100, 65,
                             key="rb_thresh")
    rb_cap = st.slider("Max % per stock ", 5, 100, 15, key="rb_cap")

    if not holdings9:
        st.info("Add a holdings.csv to use this tab.")
    else:
        port_total = sum(holdings9.values())

        # Qualifying stocks (>= threshold) get a score-weighted, capped target.
        q = df[df["pct"] >= rb_threshold].copy()
        q_tickers = set(q["ticker"])
        weights = dict(zip(q["ticker"], q["pct"].astype(float)))
        cap = rb_cap / 100.0

        target_w = {}
        if weights:
            tw = sum(weights.values())
            target_w = {t: w / tw for t, w in weights.items()}
            for _ in range(100):
                over = {t: a for t, a in target_w.items() if a > cap + 1e-9}
                if not over:
                    break
                excess = sum(a - cap for a in over.values())
                for t in over:
                    target_w[t] = cap
                uncapped = [t for t in target_w if target_w[t] < cap - 1e-9]
                if not uncapped:
                    break
                base = sum(weights[t] for t in uncapped)
                for t in uncapped:
                    target_w[t] += excess * (weights[t] / base)

        # Build a full row set: every current holding + any target stock
        all_tickers = sorted(set(holdings9) | q_tickers)
        rows = []
        for t in all_tickers:
            cur_val = holdings9.get(t, 0.0)
            tgt_val = target_w.get(t, 0.0) * port_total
            srow = df[df["ticker"] == t]
            score = round(srow.iloc[0]["pct"], 1) if not srow.empty else None
            grade = srow.iloc[0]["grade"] if not srow.empty else "-"
            delta = tgt_val - cur_val
            if abs(delta) < port_total * 0.005:
                action = "Hold"
            elif delta > 0:
                action = "Under-weight (add)"
            else:
                action = "Over-weight (trim)"
            rows.append({
                "Stock": t,
                "Score %": score if score is not None else float("nan"),
                "Grade": grade,
                "Invested ₹": round(cur_val),
                "Invested %": round(100 * cur_val / port_total, 1),
                "Target ₹": round(tgt_val),
                "Target %": round(100 * tgt_val / port_total, 1),
                "Gap ₹": round(delta),
                "Action": action,
            })
        rb_df = pd.DataFrame(rows).sort_values("Target ₹", ascending=False)

        # ---- View 1: diagnostic ----
        st.markdown("### View 1 — Target vs invested (informational)")
        st.caption("Where each holding sits vs its rating-based target, using "
                   "your INVESTED capital as the base. 'Trim' rows are shown "
                   "for information; you don't have to act.")
        st.dataframe(
            rb_df[["Stock", "Score %", "Grade", "Invested ₹", "Invested %",
                   "Target ₹", "Target %", "Action"]],
            width='stretch', hide_index=True, height=600,
            column_config={
                "Invested ₹": st.column_config.NumberColumn(format="₹%d"),
                "Target ₹": st.column_config.NumberColumn(format="₹%d"),
            })

        # ---- View 2: explicit trades ----
        st.markdown("### View 2 — Full rebalance trade list")
        st.caption("The exact moves to reach target, based on invested capital. "
                   "Note: this uses invested amounts, not current market value.")

        sells = rb_df[rb_df["Gap ₹"] < -1][["Stock", "Score %", "Invested ₹",
                                            "Target ₹", "Gap ₹"]].copy()
        buys = rb_df[rb_df["Gap ₹"] > 1][["Stock", "Score %", "Invested ₹",
                                          "Target ₹", "Gap ₹"]].copy()

        ca, cb = st.columns(2)
        with ca:
            st.markdown("**🔴 SELL / Trim**")
            if sells.empty:
                st.caption("Nothing to trim.")
            else:
                sells["Sell ₹"] = (-sells["Gap ₹"]).round()
                st.dataframe(
                    sells[["Stock", "Score %", "Sell ₹"]],
                    width='stretch', hide_index=True,
                    column_config={"Sell ₹": st.column_config.NumberColumn(
                        format="₹%d")})
                st.caption(f"Total to sell: ₹{sells['Sell ₹'].sum():,.0f}")
        with cb:
            st.markdown("**🟢 BUY / Add**")
            if buys.empty:
                st.caption("Nothing to add.")
            else:
                buys["Buy ₹"] = buys["Gap ₹"].round()
                st.dataframe(
                    buys[["Stock", "Score %", "Buy ₹"]],
                    width='stretch', hide_index=True,
                    column_config={"Buy ₹": st.column_config.NumberColumn(
                        format="₹%d")})
                st.caption(f"Total to buy: ₹{buys['Buy ₹'].sum():,.0f}")

        st.caption(f"Portfolio base: ₹{port_total:,.0f}  •  "
                   "In a full rebalance, total sells ≈ total buys.")

# --------------------------------------------------------------------------- #
# TAB 10 - Research Checklist (reference for the non-automated parameters)
# --------------------------------------------------------------------------- #
with tab10:
    st.subheader("Research checklist — the factors the tracker can't auto-score")
    st.caption("These parameters from the wealth-creation framework need manual "
               "research (they're not reliably available from free data feeds). "
               "Below, a stock's auto-scraped values are shown where available — "
               "many fields will be blank because the data simply isn't on the "
               "free sources. Use the guidance to research the rest yourself. "
               "Reference only — not financial advice.")

    research_data = load_research()

    # ----------------------------------------------------------------- #
    # Research ranking (cumulative manual +/- factors)
    # ----------------------------------------------------------------- #
    st.markdown("### 🏅 Research ranking (by total points)")
    st.caption("Each stock's score is the sum of your manual factors, each "
               "rated −3 to +3 (positive = favourable, negative = a concern). "
               "Ranked by total points. Count and average are shown too, so a "
               "high total from many factors can be told apart from a high "
               "total from just one.")

    rank_rows = []
    for t in df["ticker"].tolist():
        total, count, avg = research_totals(t, research_data)
        rank_rows.append({
            "Stock": t,
            "Total points": total,
            "Factors": count,
            "Avg / factor": avg if avg is not None else float("nan"),
        })
    rank_df = pd.DataFrame(rank_rows).sort_values(
        ["Total points", "Factors"], ascending=[False, False])
    # Only show stocks that have at least one factor at the top, but keep all
    rated = rank_df[rank_df["Factors"] > 0].copy()
    unrated_n = int((rank_df["Factors"] == 0).sum())
    # Add an explicit Rank column (1 = highest total points)
    if not rated.empty:
        rated.insert(0, "Rank", range(1, len(rated) + 1))
    st.dataframe(
        rated if not rated.empty else rank_df,
        width='stretch', hide_index=True, height=380,
        column_config={
            "Total points": st.column_config.NumberColumn(
                "Total points", format="%d"),
        })
    if not rated.empty:
        st.caption(f"Showing {len(rated)} rated stock(s). {unrated_n} stock(s) "
                   "have no factors yet — add some below.")
    else:
        st.info("No research factors entered yet. Add some below and the "
                "ranking will build up.")

    # ----------------------------------------------------------------- #
    # Manual entry — add factors (saved to research_notes.csv locally)
    # ----------------------------------------------------------------- #
    st.markdown("### ✍️ Add a research factor")
    entry_stock = st.selectbox("Stock", sorted(df["ticker"].tolist()),
                               key="re_stock")

    # Show existing factors for this stock, each with a delete button
    existing = research_data.get(entry_stock.upper(), [])
    if existing:
        st.markdown(f"**Current factors for {entry_stock}:**")
        for i, fac in enumerate(existing):
            sign = "🟢" if fac["score"] > 0 else ("🔴" if fac["score"] < 0
                                                 else "⚪")
            c1, c2 = st.columns([6, 1])
            with c1:
                st.markdown(f"{sign} **{fac['score']:+d}**  —  {fac['desc']}")
            with c2:
                if st.button("🗑️", key=f"del_{entry_stock}_{i}",
                             help="Delete this factor"):
                    delete_research_factor(entry_stock, i)
                    st.cache_data.clear()
                    st.rerun()
        t_, c_, a_ = research_totals(entry_stock, research_data)
        st.markdown(f"**Running total: {t_:+d}**  ({c_} factors, "
                    f"avg {a_:+.2f})")
    else:
        st.caption(f"No factors yet for {entry_stock}.")

    PRESET_FACTORS = [
        "— Type my own —",
        # Order momentum
        "Order Book / Backlog",
        "Book-to-Bill Ratio",
        "New Contract Wins",
        "Order Growth Rate",
        # Forward indicators
        "Management Guidance Revision",
        "Earnings Beat Consistency",
        "Analyst Consensus Rating",
        "Analyst Price Target Upside",
        "3-Year Revenue Forecast",
        # Quality trends
        "EBITDA Margin Expansion (trend)",
        "Net Profit Margin Trend",
        # Financial health
        "Current Ratio",
        "Cash & Equivalents level",
        # Market sentiment
        "Insider / Promoter Buying vs Selling",
        "Index Addition / Deletion",
        "Short Interest",
        # Risk & red flags
        "Business Model Disruption Risk",
        "Regulatory / Geopolitical / Policy Risk",
        "Contingent Liabilities / Litigation",
        "Corporate Governance Quality",
        "Management Quality",
        # Other
        "Conference call available",
        "Other factor",
    ]

    with st.form("research_form", clear_on_submit=True):
        preset = st.selectbox("Pick a factor (or type your own below)",
                              PRESET_FACTORS)
        custom = st.text_input("Custom factor description (optional)",
                               placeholder="Used only if '— Type my own —' "
                                           "is selected above")
        score = st.select_slider("Score", options=[-3, -2, -1, 0, 1, 2, 3],
                                 value=0,
                                 help="Positive = favourable, negative = concern")
        submitted = st.form_submit_button("➕ Add factor")
        if submitted:
            use_custom = preset in ("— Type my own —", "Other factor")
            desc = custom.strip() if use_custom else preset
            if not desc:
                st.warning("Pick a preset factor, or choose '— Type my own —' "
                           "/ 'Other factor' and enter a description.")
            elif score == 0:
                st.warning("Please pick a non-zero score (−3 to +3).")
            else:
                try:
                    add_research_factor(entry_stock, desc, score)
                    st.cache_data.clear()
                    st.success(f"Added '{desc}' to {entry_stock}.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Couldn't save: {e}")

    st.caption("⚠️ Saving works on your local PC (writes research_notes.csv). "
               "On the hosted version, edits won't persist across restarts — "
               "maintain factors locally and push the file to sync online.")

    st.divider()

    # --- Per-stock auto-scraped data (what little we can get) ---
    cl_stock = st.selectbox("Show scraped data for stock",
                            sorted(df["ticker"].tolist()), key="cl_stock")
    cl_hist = database.load_history(cl_stock)
    cl = (cl_hist or {}).get("checklist", {}) if cl_hist else {}

    st.markdown(f"#### Auto-scraped data for {cl_stock}")
    if not cl:
        st.caption("No scraped checklist data yet — run the collector first.")
    else:
        def show_val(v):
            if v is None or v == "" or v == []:
                return "—  *(not available)*"
            return v

        rows = [
            ("Promoter Holding (latest %)",
             show_val(cl.get("promoter_holding_latest"))),
            ("Promoter Holding Change (pp)",
             show_val(cl.get("promoter_holding_change"))),
        ]
        for label, val in rows:
            st.markdown(f"- **{label}:** {val}")

        # Screener's own Pros & Cons, if captured
        pros = cl.get("pros") or []
        cons = cl.get("cons") or []
        if pros or cons:
            cpa, cpb = st.columns(2)
            with cpa:
                st.markdown("**🟢 Screener Pros**")
                if pros:
                    for p in pros:
                        st.markdown(f"- {p}")
                else:
                    st.caption("—")
            with cpb:
                st.markdown("**🔴 Screener Cons**")
                if cons:
                    for c in cons:
                        st.markdown(f"- {c}")
                else:
                    st.caption("—")

    # ---- Reference: parameters NOT auto-traced ----
    st.divider()
    with st.expander("📌 Parameters NOT auto-traced (what to research manually)"):
        st.caption("From the original wider framework, these factors are not "
                   "captured by the automated scoring — either the data isn't "
                   "on free sources, or they need human judgement. This is your "
                   "reminder of what the score does NOT include. Capture the "
                   "ones that matter via the factor entry above.")

        not_traced = [
            ("📦 Order momentum",
             ["Order Book / Backlog", "Book-to-Bill Ratio",
              "New Contract Wins", "Order Growth Rate"]),
            ("🔭 Forward indicators",
             ["Management Guidance Revision", "Earnings Beat Consistency",
              "Analyst Consensus Rating", "Analyst Price Target Upside",
              "3-Year Revenue Forecast"]),
            ("📈 Quality trends",
             ["EBITDA Margin Expansion (trend)",
              "Net Profit Margin Trend"]),
            ("🏦 Financial health (extra)",
             ["Current Ratio (used in filter, not scored)",
              "Cash & Equivalents level"]),
            ("📣 Market sentiment",
             ["Insider / Promoter Buying vs Selling (partly auto)",
              "Index Addition / Deletion", "Short Interest"]),
            ("⚠️ Risk & red flags",
             ["Business Model Disruption Risk",
              "Regulatory / Geopolitical / Policy Risk",
              "Contingent Liabilities / Litigation",
              "Corporate Governance Quality",
              "Management Quality"]),
        ]
        for group, items in not_traced:
            st.markdown(f"**{group}**")
            st.markdown("\n".join(f"- {it}" for it in items))

        st.caption("Note: the 16 automated parameters (growth, returns, "
                   "margins, cash flow, debt) are on the Leaderboard / Compare "
                   "tabs. The list above is everything *outside* that automated "
                   "set.")



# --------------------------------------------------------------------------- #
# TAB 11 - Snapshot History (compare scores across weekly archived snapshots)
# --------------------------------------------------------------------------- #
with tab11:
    st.subheader("Snapshot history — how scores evolved")
    st.caption("Reads the weekly snapshots saved by snapshot.bat (in the "
               "archive folder). Use this to check whether high-scoring stocks "
               "held up or improved over time — the key test of whether the "
               "framework actually works. Not financial advice.")

    import glob as _glob
    import os as _os

    snap_files = sorted(_glob.glob(_os.path.join("archive", "tracker_*.db")))
    if not snap_files:
        st.info("No snapshots yet. Run snapshot.bat (ideally weekly) to start "
                "building history. Each run saves a dated copy of the database "
                "into the archive folder; come back here to see scores over "
                "time.")
    else:
        # Read each snapshot's latest daily scores
        @st.cache_data(ttl=300)
        def _load_snapshots(files):
            frames = []
            for fp in files:
                # date stamp from filename tracker_YYYY-MM-DD.db
                stamp = _os.path.basename(fp).replace("tracker_", "").replace(
                    ".db", "")
                try:
                    con = sqlite3.connect(fp)
                    latest = pd.read_sql(
                        "SELECT MAX(date) AS d FROM daily_scores", con)["d"][0]
                    s = pd.read_sql(
                        "SELECT ticker, pct FROM daily_scores WHERE date = ?",
                        con, params=(latest,))
                    con.close()
                    s["snapshot"] = stamp
                    frames.append(s)
                except Exception:
                    continue
            return pd.concat(frames) if frames else pd.DataFrame()

        snaps = _load_snapshots(snap_files)
        if snaps.empty:
            st.warning("Snapshots found but couldn't be read.")
        else:
            n_snaps = snaps["snapshot"].nunique()
            st.caption(f"{n_snaps} snapshot(s) on record: "
                       f"{', '.join(sorted(snaps['snapshot'].unique()))}")

            # Pivot: rows = stock, columns = snapshot date, values = score %
            pivot = snaps.pivot_table(index="ticker", columns="snapshot",
                                      values="pct")
            # Add change from first to latest snapshot
            cols = sorted(pivot.columns)
            if len(cols) >= 2:
                pivot["Change"] = (pivot[cols[-1]] - pivot[cols[0]]).round(1)
            pivot = pivot.round(1).sort_values(
                cols[-1] if cols else "ticker", ascending=False)
            st.markdown("**Score % by snapshot (per stock)**")
            st.dataframe(pivot, width='stretch', height=500)

            # Per-stock trend line
            st.markdown("**Trend for one stock**")
            pick = st.selectbox("Stock", sorted(snaps["ticker"].unique()),
                                key="snap_stock")
            one = snaps[snaps["ticker"] == pick].sort_values("snapshot")
            if len(one) >= 2:
                st.line_chart(one.set_index("snapshot")["pct"], height=250)
            else:
                st.caption("Need at least 2 snapshots to draw a trend.")

    # ---- Research ranking history (monthly snapshots of research_notes) ----
    st.divider()
    st.markdown("### 🏅 Research ranking history (monthly)")
    st.caption("How your manual research TOTAL per stock changed across monthly "
               "snapshots of research_notes.csv (saved automatically on the 1st "
               "of each month). Shows how your own view of each stock evolved.")

    res_files = sorted(_glob.glob(_os.path.join("archive", "research_*.csv")))
    if not res_files:
        st.info("No research snapshots yet. The first is saved automatically on "
                "the 1st of the month (or add archive/research_YYYY-MM-DD.csv "
                "manually). Come back once you have one or more.")
    else:
        @st.cache_data(ttl=300)
        def _load_research_snaps(files):
            import csv as _csv2
            frames = []
            for fp in files:
                stamp = _os.path.basename(fp).replace("research_", "").replace(
                    ".csv", "")
                totals = {}
                try:
                    with open(fp, newline="", encoding="utf-8") as f:
                        for row in _csv2.DictReader(f):
                            t = (row.get("ticker") or "").strip().upper()
                            try:
                                sc = int(row.get("score"))
                            except (TypeError, ValueError):
                                continue
                            if t:
                                totals[t] = totals.get(t, 0) + sc
                except Exception:
                    continue
                for t, tot in totals.items():
                    frames.append({"ticker": t, "total": tot,
                                   "snapshot": stamp})
            return pd.DataFrame(frames)

        rsnaps = _load_research_snaps(res_files)
        if rsnaps.empty:
            st.warning("Research snapshots found but couldn't be read.")
        else:
            nrs = rsnaps["snapshot"].nunique()
            st.caption(f"{nrs} research snapshot(s): "
                       f"{', '.join(sorted(rsnaps['snapshot'].unique()))}")
            rpivot = rsnaps.pivot_table(index="ticker", columns="snapshot",
                                        values="total")
            rcols = sorted(rpivot.columns)
            if len(rcols) >= 2:
                rpivot["Change"] = (rpivot[rcols[-1]] -
                                    rpivot[rcols[0]]).round(1)
            rpivot = rpivot.round(1).sort_values(
                rcols[-1] if rcols else "ticker", ascending=False)
            st.markdown("**Research total by snapshot (per stock)**")
            st.dataframe(rpivot, width='stretch', height=400)

            st.markdown("**Research trend for one stock**")
            rpick = st.selectbox("Stock ", sorted(rsnaps["ticker"].unique()),
                                 key="res_snap_stock")
            rone = rsnaps[rsnaps["ticker"] == rpick].sort_values("snapshot")
            if len(rone) >= 2:
                st.line_chart(rone.set_index("snapshot")["total"], height=250)
            else:
                st.caption("Need at least 2 research snapshots to draw a trend.")

    # ---- Combined ranking history (weekly snapshots of combined values) ----
    st.divider()
    st.markdown("### 🥇 Combined ranking history (weekly)")
    st.caption("How each stock's COMBINED score (fundamental + research "
               "adjustment) changed across weekly snapshots. Saved "
               "automatically with the Sunday snapshot.")

    comb_files = sorted(_glob.glob(_os.path.join("archive", "combined_*.csv")))
    if not comb_files:
        st.info("No combined snapshots yet. The first is saved automatically "
                "with the next Sunday snapshot (file: "
                "archive/combined_YYYY-MM-DD.csv).")
    else:
        @st.cache_data(ttl=300)
        def _load_combined_snaps(files):
            import csv as _csv3
            frames = []
            for fp in files:
                stamp = _os.path.basename(fp).replace("combined_", "").replace(
                    ".csv", "")
                try:
                    with open(fp, newline="", encoding="utf-8") as f:
                        for row in _csv3.DictReader(f):
                            t = (row.get("ticker") or "").strip().upper()
                            try:
                                cv = float(row.get("combined"))
                            except (TypeError, ValueError):
                                continue
                            if t:
                                frames.append({"ticker": t, "combined": cv,
                                               "snapshot": stamp})
                except Exception:
                    continue
            return pd.DataFrame(frames)

        csnaps = _load_combined_snaps(comb_files)
        if csnaps.empty:
            st.warning("Combined snapshots found but couldn't be read.")
        else:
            ncs = csnaps["snapshot"].nunique()
            st.caption(f"{ncs} combined snapshot(s): "
                       f"{', '.join(sorted(csnaps['snapshot'].unique()))}")
            cpivot = csnaps.pivot_table(index="ticker", columns="snapshot",
                                        values="combined")
            ccols = sorted(cpivot.columns)
            if len(ccols) >= 2:
                cpivot["Change"] = (cpivot[ccols[-1]] -
                                    cpivot[ccols[0]]).round(1)
            cpivot = cpivot.round(1).sort_values(
                ccols[-1] if ccols else "ticker", ascending=False)
            st.markdown("**Combined score by snapshot (per stock)**")
            st.dataframe(cpivot, width="stretch", height=400)

            st.markdown("**Combined trend for one stock**")
            cpick = st.selectbox("Stock  ", sorted(csnaps["ticker"].unique()),
                                 key="comb_snap_stock")
            cone = csnaps[csnaps["ticker"] == cpick].sort_values("snapshot")
            if len(cone) >= 2:
                st.line_chart(cone.set_index("snapshot")["combined"],
                              height=250)
            else:
                st.caption("Need at least 2 combined snapshots to draw a trend.")


# =========================================================================== #
# COMBINED RANKING - fundamental score (primary) + research adjustment
# =========================================================================== #
with ctab:
    st.subheader("Combined ranking — fundamentals + research")
    st.caption("Fundamental score is primary; your manual research nudges it up "
               "or down. The adjustment uses the AVERAGE factor score (−3..+3) "
               "mapped to −10..+10 — so quality matters, not how many factors a "
               "stock has. Not financial advice.")

    research_data_c = load_research()

    crows = []
    for _, r in df.iterrows():
        tkr = r["ticker"]
        fund = float(r["pct"])
        rtotal, rcount, ravg = research_totals(tkr, research_data_c)
        rtotal = rtotal or 0
        # Adjustment = average factor score (-3..+3) mapped to -10..+10.
        # Quality-based, so the number of factors doesn't inflate it.
        if rcount and ravg is not None:
            adj = round(ravg * (10.0 / 3.0), 1)
        else:
            adj = 0.0
        combined = round(fund + adj, 1)
        crows.append({
            "Stock": tkr,
            "Combined": combined,
            "Fundamental %": round(fund, 1),
            "Avg/factor": ravg if rcount else None,
            "Adj applied": adj,
            "Factors": rcount,
            "Research pts": rtotal,
            "Grade": r["grade"],
        })

    cdf = pd.DataFrame(crows).sort_values("Combined", ascending=False)
    cdf.insert(0, "Rank", range(1, len(cdf) + 1))

    st.dataframe(
        cdf, width="stretch", hide_index=True,
        height=38 + 35 * min(len(cdf), 20),
        column_config={
            "Combined": st.column_config.NumberColumn("Combined", format="%.1f"),
            "Fundamental %": st.column_config.NumberColumn(
                "Fundamental %", format="%.1f%%"),
        })
    st.caption("Combined = Fundamental % + adjustment, where adjustment = "
               "average factor score (−3..+3) × 10/3 (so −10..+10). Stocks with "
               "no research factors rank purely on fundamentals. Rank 1 = best.")
    st.bar_chart(cdf.set_index("Stock")["Combined"], height=300)



# =========================================================================== #
# DISCOVERY TABS - read from discovery_snapshot.csv (synced from discovery tool)
# =========================================================================== #
ddf = load_discovery()
_live = [k for k, p in config.PRIORITY_PARAMS.items() if p.get("live")]
_short = {
    "revenue_growth_accel": "Rev Accel", "revenue_growth": "Rev Gr",
    "eps_growth": "EPS Gr", "price_momentum_52w": "Mom 52w",
    "fcf_growth": "FCF Gr", "fii_buying": "FII", "roe": "ROE",
    "roce": "ROCE", "opm": "OPM", "dividend_payout": "Div",
    "ocf_growth": "OCF Gr", "fcf_to_profit": "FCF/NP",
    "cfo_to_op": "CFO/OP", "debt_to_equity_score": "D/E",
    "interest_coverage": "Int Cov", "net_margin": "Net Mgn",
}

def _no_discovery():
    st.info("No discovery data yet. In the discovery tool run "
            "export_discovery.bat, then copy discovery_snapshot.csv into this "
            "folder and refresh.")

# ---- Discovery Leaderboard ----
with dtab1:
    st.subheader("Discovery - ranked by score")
    st.caption("Candidate stocks from your discovery screen. Synced snapshot - "
               "refresh by re-running the discovery export and copying the file.")
    if ddf is None:
        _no_discovery()
    else:
        b = ddf[["ticker", "pct", "grade", "total_score", "max_score"]].copy()
        b.insert(0, "Rank", range(1, len(b) + 1))
        b["Grade"] = b["grade"].apply(lambda g: f"{grade_dot(g)} {g}")
        b = b.rename(columns={"ticker": "Stock", "pct": "Score %",
                              "total_score": "Wtd Pts", "max_score": "Max"})
        st.dataframe(
            b[["Rank", "Stock", "Score %", "Grade", "Wtd Pts", "Max"]],
            width="stretch", hide_index=True,
            column_config={"Score %": st.column_config.ProgressColumn(
                "Score %", min_value=0, max_value=100, format="%.1f%%")})
        st.bar_chart(ddf.set_index("ticker")["pct"], height=300)

# ---- Discovery Compare Values (actual numbers, colored by score) ----
with dtab2:
    st.subheader("Discovery - all stocks vs all parameters (actual values)")
    st.caption("The real numbers (ROE %, growth %, ratios) for discovery "
               "candidates, colored by quality (green strong / yellow avg / "
               "red weak / grey no data).")
    if ddf is None:
        _no_discovery()
    else:
        val_rows, score_rows = [], []
        for _, r in ddf.iterrows():
            vrow = {"Stock": r["ticker"], "Score %": r["pct"],
                    "Grade": r["grade"]}
            srow = {}
            for k in _live:
                label = _short.get(k, k)
                raw = r.get(k)
                vrow[label] = raw
                srow[label] = scorer.score_value(k, raw)
            val_rows.append(vrow)
            score_rows.append(srow)
        val_mat = pd.DataFrame(val_rows).reset_index(drop=True)
        score_mat = pd.DataFrame(score_rows).reset_index(drop=True)
        pcols = [_short.get(k, k) for k in _live]

        def _color_by_score(col):
            styles = []
            for i in range(len(col)):
                s = score_mat.loc[i, col.name] if col.name in score_mat else None
                if s == 3:
                    styles.append("background-color:#d4f0df;color:#1a6e3c;")
                elif s == 2:
                    styles.append("background-color:#fff3cd;color:#7a5200;")
                elif s == 1:
                    styles.append("background-color:#fde8e8;color:#921f1f;")
                else:
                    styles.append("background-color:#f0f0f0;color:#999;")
            return styles

        def _fmt_val(v):
            if pd.isna(v):
                return "-"
            return f"{v:.2f}" if isinstance(v, float) else str(v)

        styled_v = (val_mat.style
                    .apply(_color_by_score, subset=pcols)
                    .format({"Score %": lambda v: "" if pd.isna(v)
                             else f"{v:.1f}%"})
                    .format({c: _fmt_val for c in pcols}))
        st.dataframe(styled_v, width="stretch", hide_index=True, height=600)
        st.caption("Number = actual value; color = quality "
                   "(🟢 strong / 🟡 average / 🔴 weak / ⬜ no data).")

# ---- Discovery Deep Dive ----
with dtab5:
    st.subheader("Discovery - per-stock breakdown")
    if ddf is None:
        _no_discovery()
    else:
        stock = st.selectbox("Choose a discovery stock",
                             sorted(ddf["ticker"].tolist()), key="disc_dd")
        row = ddf[ddf["ticker"] == stock].iloc[0]
        st.metric(f"{stock} score", f"{row['pct']:.1f}%  ({row['grade']})")
        for tier in sorted({p["tier"] for p in config.PRIORITY_PARAMS.values()}):
            recs = []
            for k, p in config.PRIORITY_PARAMS.items():
                if not p.get("live") or p.get("tier") != tier:
                    continue
                val = row.get(k)
                s = scorer.score_value(k, val)
                rating = ("⚪ no data" if s is None else
                          {3: "🟢 Strong", 2: "🟡 Average", 1: "🔴 Weak"}[s])
                recs.append({"Parameter": p["label"],
                             "Value": "-" if val is None else str(round(val, 2)),
                             "Rating": rating})
            if recs:
                st.markdown(f"**{config.TIER_NAME[tier]}**")
                st.dataframe(pd.DataFrame(recs), width="stretch",
                             hide_index=True)

st.divider()
st.caption(f"⚠️ For research and educational use only. Not financial advice. "
           f"Always consult a SEBI-registered adviser before investing.  ·  "
           f"Stock Wealth-Creation Tracker {APP_VERSION} ({APP_VERSION_DATE})")
