#!/usr/bin/env python3
"""
qa_to_text_chunks.py

Convert a Q&A source (Excel .xlsx or chat-style JSONL) into plain text chunk files:

  data/chunks/<source_basename>/chunk_001.txt
  each file contains:
    Q: {question}

    A: {answer}

Usage:
  python qa_to_text_chunks.py --input VNU_Q&A.xlsx
  python qa_to_text_chunks.py --input train_chat.jsonl --out-root data/chunks

Options:
  --input / -i    : input file (.xlsx or .jsonl) (required)
  --out-root / -o : output root directory (default: data/chunks)
  --sheet / -s    : sheet name or index for Excel (optional)
  --qcol          : explicit question column name (optional)
  --acol          : explicit answer column name (optional)
"""
import argparse
import json
from pathlib import Path
import unicodedata
import pandas as pd

# ---------- helpers ----------
def normalize_header(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ASCII", "ignore").decode("ASCII")
    return s.lower().strip()

QUESTION_KEYS = {"cau hoi", "cauhoi", "cau_hoi", "cau-hoi", "question", "q", "quest"}
ANSWER_KEYS   = {"tra loi", "traloi", "tra_loi", "tra-loi", "answer", "a", "ans", "tra-loi"}

def detect_q_a_columns(df: pd.DataFrame, qcol_hint=None, acol_hint=None):
    if qcol_hint and acol_hint and qcol_hint in df.columns and acol_hint in df.columns:
        return qcol_hint, acol_hint
    normalized = {col: normalize_header(col) for col in df.columns}
    qcol = None
    acol = None
    for col, norm in normalized.items():
        tokens = set(norm.replace("-", " ").replace("_", " ").split())
        if tokens & QUESTION_KEYS and qcol is None:
            qcol = col
        if tokens & ANSWER_KEYS and acol is None:
            acol = col
    if qcol is None or acol is None:
        # fallback to first two columns
        if len(df.columns) >= 2:
            qcol = qcol or df.columns[0]
            acol = acol or df.columns[1]
    return qcol, acol

def read_excel_input(path: Path, sheet=None, qcol=None, acol=None):
    if sheet is not None:
        df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        if isinstance(df, dict):
            first = list(df.keys())[0]
            df = df[first]
    else:
        all_sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
        if isinstance(all_sheets, dict):
            first = list(all_sheets.keys())[0]
            df = all_sheets[first]
        else:
            df = all_sheets
    qcol_detected, acol_detected = detect_q_a_columns(df, qcol, acol)
    return df, qcol_detected, acol_detected

def read_chat_jsonl_input(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            msgs = obj.get("messages") or []
            user = None
            assistant = None
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                if role == "user" and not user:
                    user = m.get("content", "").strip()
                if role == "assistant" and not assistant:
                    # prefer assistant content (skip assistant entries that only have tool_calls and no content)
                    if m.get("content"):
                        assistant = m.get("content", "").strip()
            if user and assistant:
                rows.append({"question": user, "answer": assistant, "source": str(path)})
    df = pd.DataFrame(rows)
    return df, "question", "answer"

# ---------- main ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True, help="Input file (.xlsx or .jsonl)")
    parser.add_argument("--out-root", "-o", default="data/chunks", help="Output root directory (default: data/chunks)")
    parser.add_argument("--sheet", "-s", default=None, help="Excel sheet name or index (optional)")
    parser.add_argument("--qcol", default=None, help="Question column name (optional)")
    parser.add_argument("--acol", default=None, help="Answer column name (optional)")
    args = parser.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        raise SystemExit(f"Input not found: {inp}")

    out_root = Path(args.out_root)
    source_basename = inp.stem  # filename without suffix
    target_dir = out_root / source_basename
    target_dir.mkdir(parents=True, exist_ok=True)

    # read input to DataFrame of rows with columns question/answer
    if inp.suffix.lower() in [".xlsx", ".xls"]:
        df, qcol, acol = read_excel_input(inp, args.sheet, args.qcol, args.acol)
    else:
        df, qcol, acol = read_chat_jsonl_input(inp)

    if qcol is None or acol is None:
        raise SystemExit("Could not detect question/answer columns automatically. Provide --qcol and --acol.")

    # Build list of (question, answer)
    pairs = []
    for _, row in df.iterrows():
        q = (row.get(qcol) if qcol in row else row.get("question")) or ""
        a = (row.get(acol) if acol in row else row.get("answer")) or ""
        q = str(q).strip()
        a = str(a).strip()
        if not q or not a:
            continue
        pairs.append((q, a))

    total = len(pairs)
    if total == 0:
        print("No valid Q/A pairs found.")
        return

    # zero-pad width
    pad = max(3, len(str(total)))
    for i, (q, a) in enumerate(pairs, start=1):
        filename = f"chunk_{i:0{pad}d}.txt"
        path = target_dir / filename
        content = f"Q: {q}\n\nA: {a}"
        path.write_text(content, encoding="utf-8")
    print(f"Wrote {total} chunk files to: {target_dir}")

    # print first few files produced
    preview = list(target_dir.glob("chunk_*.txt"))[:10]
    if preview:
        print("Preview (first files):")
        for p in preview:
            print(" -", p.name)

if __name__ == "__main__":
    main()
