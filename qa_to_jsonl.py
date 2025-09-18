#!/usr/bin/env python3
"""
excel_to_jsonl.py - robust version that handles Excel files with multiple sheets.

Usage:
    python excel_to_jsonl.py --input qa.xlsx --output train.jsonl
    python excel_to_jsonl.py --input qa.xlsx --output train.jsonl --valid valid.jsonl --valid-frac 0.1 --sheet "Sheet1"
"""

import argparse
import json
import logging
import sys
from pathlib import Path
import unicodedata
import random

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Helpers
def normalize_header(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ASCII", "ignore").decode("ASCII")
    return s.lower().strip()

QUESTION_KEYWORDS = {"cau hoi", "cauhoi", "cau_hoi", "cau-hoi", "question", "q", "quest"}
ANSWER_KEYWORDS = {"tra loi", "traloi", "tra_loi", "tra-loi", "answer", "a", "ans"}

def find_columns(df: pd.DataFrame):
    normalized = {col: normalize_header(col) for col in df.columns}
    q_col = None
    a_col = None

    for col, norm in normalized.items():
        tokens = set(norm.replace("-", " ").replace("_", " ").split())
        if tokens & QUESTION_KEYWORDS and q_col is None:
            q_col = col
        if tokens & ANSWER_KEYWORDS and a_col is None:
            a_col = col

    if q_col is None or a_col is None:
        if len(df.columns) >= 2:
            logging.warning("Could not automatically detect both headers; falling back to first two columns.")
            q_col = q_col or df.columns[0]
            a_col = a_col or df.columns[1]

    return q_col, a_col

def to_jsonl_rows(df: pd.DataFrame, q_col: str, a_col: str):
    rows = []
    for i, row in df.iterrows():
        q = row.get(q_col, None)
        a = row.get(a_col, None)
        if pd.isna(q) or pd.isna(a):
            continue
        q_text = str(q).strip()
        a_text = str(a).strip()
        if not q_text or not a_text:
            continue
        prompt = f"Question: {q_text}\n\nAnswer:"
        completion = " " + a_text + "\n"
        rows.append({"prompt": prompt, "completion": completion})
    return rows

def write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def main():
    parser = argparse.ArgumentParser(description="Convert Excel Q&A to JSONL for fine-tuning.")
    parser.add_argument("--input", "-i", required=True, help="Input Excel file (.xlsx)")
    parser.add_argument("--sheet", "-s", default=None, help="Sheet name or index (optional)")
    parser.add_argument("--output", "-o", required=True, help="Output train JSONL file path")
    parser.add_argument("--valid", "-v", default=None, help="Optional output validation JSONL file path")
    parser.add_argument("--valid-frac", type=float, default=0.0, help="Validation fraction (0.0-0.5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for shuffle/split")
    args = parser.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        logging.error(f"Input file not found: {inp}")
        sys.exit(2)

    logging.info(f"Reading Excel file: {inp}")
    try:
        # If a specific sheet is provided, pass it directly (pandas accepts string or int).
        # If not provided, use sheet_name=None to fetch all sheets and pick the first.
        if args.sheet is not None:
            df = pd.read_excel(inp, sheet_name=args.sheet, engine="openpyxl")
            # pd.read_excel returns a DataFrame when sheet is specified
            if isinstance(df, dict):
                # unexpected but handle defensively
                first_sheet = list(df.keys())[0]
                logging.warning(f"sheet argument returned multiple sheets; using first sheet: {first_sheet}")
                df = df[first_sheet]
        else:
            # Read all sheets, get dict, and pick the first sheet by order
            all_sheets = pd.read_excel(inp, sheet_name=None, engine="openpyxl")
            if isinstance(all_sheets, dict):
                sheet_names = list(all_sheets.keys())
                logging.info(f"Found sheets: {sheet_names}")
                first = sheet_names[0]
                logging.info(f"Using first sheet: {first}")
                df = all_sheets[first]
            else:
                # unlikely, but ensure df is DataFrame
                df = all_sheets
    except Exception as e:
        logging.exception("Failed to read Excel file. Ensure openpyxl is installed and the file is a valid .xlsx")
        raise

    logging.info(f"Columns found: {list(df.columns)}")
    q_col, a_col = find_columns(df)
    if q_col is None or a_col is None:
        logging.error("Failed to determine question/answer columns. Please make sure the sheet has at least two columns.")
        sys.exit(3)

    logging.info(f"Using question column: '{q_col}' and answer column: '{a_col}'")
    rows = to_jsonl_rows(df, q_col, a_col)
    logging.info(f"Extracted {len(rows)} Q→A rows (non-empty)")

    if not rows:
        logging.error("No valid rows found. Exiting.")
        sys.exit(4)

    # Shuffle and split if needed
    random.seed(args.seed)
    random.shuffle(rows)

    train_rows = rows
    valid_rows = []
    if args.valid and args.valid_frac > 0.0:
        vf = float(args.valid_frac)
        if not (0.0 < vf < 0.5):
            logging.warning("valid-frac should be between 0.0 and 0.5; ignoring validation split.")
        else:
            n_valid = max(1, int(len(rows) * vf))
            valid_rows = train_rows[:n_valid]
            train_rows = train_rows[n_valid:]
            logging.info(f"Split into train={len(train_rows)} and valid={len(valid_rows)}")

    out_train = Path(args.output)
    write_jsonl(out_train, train_rows)
    logging.info(f"Wrote train JSONL: {out_train} ({len(train_rows)} lines)")

    if args.valid and valid_rows:
        out_valid = Path(args.valid)
        write_jsonl(out_valid, valid_rows)
        logging.info(f"Wrote valid JSONL: {out_valid} ({len(valid_rows)} lines)")

    logging.info("Done. Use temperature=0 and same prompt template when calling the fine-tuned model.")

if __name__ == "__main__":
    main()
