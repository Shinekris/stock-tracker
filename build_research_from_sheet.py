"""
build_research_from_sheet.py
Converts a Google Sheet CSV export into the research_notes.csv format the
tracker needs (columns: ticker, description, score).

USAGE:
  1. In Google Sheets: File -> Download -> Comma-separated values (.csv)
  2. Save it as  research_sheet.csv  in this folder.
  3. Run:  python build_research_from_sheet.py
  4. It produces research_notes.csv (and reports any rows it skipped).

The Google Sheet should have these columns (header row, any order):
    ticker        - NSE symbol in CAPITALS  (e.g. ANNAPURNA)
    description   - short text of the factor (e.g. Strong order book)
    score         - whole number from -3 to +3 (no zero)

The script is forgiving about column-name capitalisation and a few common
aliases (stock/symbol -> ticker, factor/note -> description, points -> score).
"""
import csv
import os
import sys

INPUT = "research_sheet.csv"      # the Google Sheet CSV export
OUTPUT = "research_notes.csv"     # what the tracker reads

# Accept a few common header variations
TICKER_KEYS = {"ticker", "stock", "symbol", "nse", "scrip"}
DESC_KEYS = {"description", "factor", "note", "notes", "comment", "reason"}
SCORE_KEYS = {"score", "points", "rating", "value"}


def find_col(fieldnames, candidates):
    for f in fieldnames:
        if f and f.strip().lower() in candidates:
            return f
    return None


def main():
    if not os.path.exists(INPUT):
        print(f"ERROR: '{INPUT}' not found in this folder.")
        print("Download your Google Sheet as CSV, save it as "
              f"'{INPUT}', and run again.")
        sys.exit(1)

    with open(INPUT, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        tcol = find_col(fields, TICKER_KEYS)
        dcol = find_col(fields, DESC_KEYS)
        scol = find_col(fields, SCORE_KEYS)

        if not (tcol and dcol and scol):
            print("ERROR: couldn't find the needed columns.")
            print(f"  Found headers: {fields}")
            print("  Need columns for: ticker, description, score "
                  "(or accepted aliases).")
            sys.exit(1)

        good, skipped = [], []
        for i, row in enumerate(reader, start=2):  # row 1 = header
            ticker = (row.get(tcol) or "").strip().upper()
            desc = (row.get(dcol) or "").strip()
            raw_score = (row.get(scol) or "").strip()
            # Validate
            if not ticker or not desc or not raw_score:
                skipped.append((i, "blank field", row))
                continue
            try:
                score = int(float(raw_score))   # tolerate "2" or "2.0"
            except ValueError:
                skipped.append((i, f"score not a number ({raw_score})", row))
                continue
            if score < -3 or score > 3 or score == 0:
                skipped.append((i, f"score out of range ({score})", row))
                continue
            good.append((ticker, desc, score))

    # Write the tracker's research_notes.csv
    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "description", "score"])
        for t, d, s in good:
            w.writerow([t, d, s])

    print(f"Done. Wrote {len(good)} factor(s) to {OUTPUT}.")
    if skipped:
        print(f"\nSkipped {len(skipped)} row(s):")
        for line_no, why, _ in skipped:
            print(f"  - row {line_no}: {why}")
        print("\nFix those rows in the sheet, re-download, and run again "
              "if you want them included.")


if __name__ == "__main__":
    main()
