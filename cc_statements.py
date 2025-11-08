# cc_statements.py
import os
import pandas as pd
from datetime import date, timedelta
import streamlit as st
import ledger as lg
from user_data import path_in_user_dir

# FIX: per-user file without extra "data/"
CC_STMT_CSV = path_in_user_dir("credit_card_statements.csv")
STMT_COLS = [
    "id", "card_account_id", "period_start", "period_end",
    "statement_balance", "apr_at_cycle", "min_due", "due_date",
    "paid_amount", "paid_date", "carried_balance", "note"
]

def _exists_nonempty(p: str) -> bool:
    return os.path.exists(p) and os.path.getsize(p) > 0

def _next_id(path: str) -> int:
    if not _exists_nonempty(path):
        return 1
    s = pd.read_csv(path, usecols=["id"], encoding="utf-8-sig")["id"]
    m = pd.to_numeric(s, errors="coerce").max()
    return (0 if pd.isna(m) else int(m)) + 1

def _read_df() -> pd.DataFrame:
    if not _exists_nonempty(CC_STMT_CSV):
        return pd.DataFrame(columns=STMT_COLS)
    df = pd.read_csv(CC_STMT_CSV, encoding="utf-8-sig")
    for c in STMT_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[STMT_COLS]

def _write_df(df: pd.DataFrame):
    df = df[STMT_COLS]
    df.to_csv(CC_STMT_CSV, index=False, encoding="utf-8-sig")

def default_min_due(balance: float, pct: float = 3.0, floor: float = 25.0) -> float:
    """Rule of thumb: max(floor, pct% of statement balance)."""
    return round(max(floor, abs(balance) * (pct/100.0)), 2)

def close_statement(card_account_id: str, period_end: date, period_start: date | None = None,
                    due_days: int = 25, min_pct: float = 3.0, min_floor: float = 25.0, note: str = ""):
    """
    Create a monthly statement snapshot for a credit card:
      - Reads current owed (credit card balance from accounts).
      - Computes min_due.
      - Appends a row to credit_card_statements.csv.
    """
    acc = lg.load_accounts()
    idx = acc.index[acc["account_id"].astype(str) == str(card_account_id)]
    if len(idx) == 0:
        raise ValueError("Card account not found.")
    i = idx[0]
    if str(acc.at[i, "account_type"]).strip().lower() != "credit card":
        raise ValueError("Selected account is not a credit card.")

    apr = float(acc.at[i, "apr"]) if not pd.isna(acc.at[i, "apr"]) else 0.0
    bal = float(acc.at[i, "balance"]) if not pd.isna(acc.at[i, "balance"]) else 0.0  # owed (>=0 typical)

    stmt_bal = round(bal, 2)
    md = default_min_due(stmt_bal, pct=min_pct, floor=min_floor)
    due_dt = pd.to_datetime(period_end).date() + timedelta(days=due_days)
    p_start = pd.to_datetime(period_start or (pd.to_datetime(period_end) - pd.Timedelta(days=30))).date()

    df = _read_df()
    nid = _next_id(CC_STMT_CSV)
    new_row = pd.DataFrame([{
        "id": nid,
        "card_account_id": str(card_account_id),
        "period_start": p_start.isoformat(),
        "period_end": pd.to_datetime(period_end).date().isoformat(),
        "statement_balance": stmt_bal,
        "apr_at_cycle": apr,
        "min_due": md,
        "due_date": due_dt.isoformat(),
        "paid_amount": 0.0,
        "paid_date": "",
        "carried_balance": stmt_bal,
        "note": note or "",
    }], columns=STMT_COLS)

    df = pd.concat([df, new_row], ignore_index=True)
    _write_df(df)
    return int(nid)

def record_cc_payment(stmt_id: int, from_bank_account_id: str, amount: float, currency: str, when: date, note: str = ""):
    """
    Pay a statement: transfer bank -> card, update paid_amount & carried_balance.
    """
    # 1) move money
    lg.transfer(from_bank_account_id, _card_id_for_stmt(stmt_id), float(amount), currency, when, note=note)

    # 2) update statement aggregates
    df = _read_df()
    row = df.loc[df["id"] == stmt_id]
    if row.empty:
        raise ValueError("Statement not found.")
    idx = row.index[0]

    prev_paid = float(df.at[idx, "paid_amount"]) if not pd.isna(df.at[idx, "paid_amount"]) else 0.0
    stmt_bal  = float(df.at[idx, "statement_balance"]) if not pd.isna(df.at[idx, "statement_balance"]) else 0.0
    new_paid  = round(prev_paid + float(amount), 2)
    carried   = max(0.0, round(stmt_bal - new_paid, 2))

    df.at[idx, "paid_amount"] = new_paid
    df.at[idx, "paid_date"] = pd.to_datetime(when).date().isoformat()
    df.at[idx, "carried_balance"] = carried
    _write_df(df)

def _card_id_for_stmt(stmt_id: int) -> str:
    df = _read_df()
    row = df.loc[df["id"] == stmt_id]
    if row.empty:
        raise ValueError("Statement not found.")
    return str(row.iloc[0]["card_account_id"])

def latest_open_stmt_for_card(card_account_id: str) -> int | None:
    df = _read_df()
    q = df[df["card_account_id"].astype(str) == str(card_account_id)].copy()
    if q.empty:
        return None
    q = q.sort_values("id", ascending=False)
    return int(q.iloc[0]["id"])