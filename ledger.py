# ledger.py
import os
import pandas as pd
from datetime import date
import streamlit as st
from user_data import path_in_user_dir

# FIXED: no extra "data/" here
TRANSACTIONS_CSV = path_in_user_dir("transactions.csv")
ACCOUNTS_CSV     = path_in_user_dir("accounts.csv")

# Canonical column order for transactions
TX_COLUMNS = [
    "id", "date", "kind", "amount", "currency", "account_id",
    "counterparty_account_id", "category", "ref_table", "ref_id", "note"
]

# ---------- tiny helpers ----------

def _file_exists_and_nonempty(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0

def _ensure_transactions_header_if_needed():
    """Normalize/repair header so TX_COLUMNS exist and order is correct."""
    if not os.path.exists(TRANSACTIONS_CSV):
        return
    if os.path.getsize(TRANSACTIONS_CSV) == 0:
        pd.DataFrame(columns=TX_COLUMNS).to_csv(TRANSACTIONS_CSV, index=False, encoding="utf-8-sig")
        return
    try:
        df = pd.read_csv(TRANSACTIONS_CSV, encoding="utf-8-sig")
        for c in TX_COLUMNS:
            if c not in df.columns:
                df[c] = "" if c not in ("amount", "id") else 0
        df = df[TX_COLUMNS]
        df.to_csv(TRANSACTIONS_CSV, index=False, encoding="utf-8-sig")
    except Exception:
        pd.DataFrame(columns=TX_COLUMNS).to_csv(TRANSACTIONS_CSV, index=False, encoding="utf-8-sig")

def _next_seq_id(csv_path: str, id_col="id") -> int:
    if not _file_exists_and_nonempty(csv_path):
        return 1
    try:
        s = pd.read_csv(csv_path, usecols=[id_col], encoding="utf-8-sig")[id_col]
        m = pd.to_numeric(s, errors="coerce").max()
        return (0 if pd.isna(m) else int(m)) + 1
    except Exception:
        return 1

@st.cache_data
def load_accounts(path: str = ACCOUNTS_CSV) -> pd.DataFrame:
    cols = ["id","account_name","account_type","account_id","balance","currency","limit","apr","note"]
    if not _file_exists_and_nonempty(path):
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path, encoding="utf-8-sig")

    # Normalize headers and repair common typo
    df.columns = [str(c).strip() for c in df.columns]
    if "limt" in df.columns:
        df = df.rename(columns={"limt": "limit"})

    # Ensure all required columns exist
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA

    # Defaults + type normalization
    df["id"]            = pd.to_numeric(df["id"], errors="coerce")
    df["account_id"]    = df["account_id"].fillna(df["id"]).astype(str).str.strip()
    df["account_name"]  = df["account_name"].fillna("Unnamed account").astype(str).str.strip()
    df["account_type"]  = df["account_type"].fillna("").astype(str).str.strip()  # <— critical for "Credit Card "
    df["currency"]      = df["currency"].fillna("GBP").astype(str).str.strip().str.upper()
    df["balance"]       = pd.to_numeric(df["balance"], errors="coerce").fillna(0.0)
    df["limit"]         = pd.to_numeric(df["limit"],   errors="coerce").fillna(0.0)
    df["apr"]           = pd.to_numeric(df["apr"],     errors="coerce").fillna(0.0)
    df["note"]          = df["note"].fillna("").astype(str)

    # Return in canonical order
    return df[cols]

def save_accounts(df: pd.DataFrame, path: str = ACCOUNTS_CSV) -> None:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    load_accounts.clear()

# ---------- balance math ----------

def _apply_delta_to_account(acc_df: pd.DataFrame, account_id: str, delta: float) -> pd.DataFrame:
    """
    delta > 0 increases bank balance.
    For credit cards (balance = amount owed), delta > 0 REDUCES owed.
    """
    if acc_df.empty:
        return acc_df
    idx = acc_df.index[acc_df["account_id"].astype(str) == str(account_id)]
    if len(idx) == 0:
        return acc_df
    i = idx[0]
    acc_type = str(acc_df.at[i, "account_type"]).strip().lower()
    bal = float(acc_df.at[i, "balance"]) if not pd.isna(acc_df.at[i, "balance"]) else 0.0
    new_bal = bal - float(delta) if acc_type == "credit card" else bal + float(delta)
    acc_df.at[i, "balance"] = round(new_bal, 2)
    return acc_df

def _append_tx(row: dict):
    _ensure_transactions_header_if_needed()
    next_id = _next_seq_id(TRANSACTIONS_CSV)
    row = {**row, "id": int(next_id)}
    pd.DataFrame([row], columns=TX_COLUMNS).to_csv(
        TRANSACTIONS_CSV,
        mode="a",
        index=False,
        header=False,
        encoding="utf-8-sig"
    )

# ---------- public API ----------

def post_income(account_id: str, amount: float, currency: str, when: date,
                category="Income", note="", ref_table=None, ref_id=None):
    acc = load_accounts()
    acc = _apply_delta_to_account(acc, account_id, +abs(float(amount)))
    save_accounts(acc)
    _append_tx({
        "date": pd.to_datetime(when).date().isoformat(),
        "kind": "income", "amount": float(amount), "currency": currency,
        "account_id": str(account_id), "counterparty_account_id": "",
        "category": category, "ref_table": ref_table or "", "ref_id": ref_id or "", "note": note or ""
    })

def post_expense(account_id: str, amount: float, currency: str, when: date,
                 category: str, note="", ref_table=None, ref_id=None):
    acc = load_accounts()
    acc = _apply_delta_to_account(acc, account_id, -abs(float(amount)))
    save_accounts(acc)
    _append_tx({
        "date": pd.to_datetime(when).date().isoformat(),
        "kind": "expense", "amount": float(amount), "currency": currency,
        "account_id": str(account_id), "counterparty_account_id": "",
        "category": category, "ref_table": ref_table or "", "ref_id": ref_id or "", "note": note or ""
    })

def transfer(from_account_id: str, to_account_id: str, amount: float, currency: str, when: date, note=""):
    acc = load_accounts()
    acc = _apply_delta_to_account(acc, from_account_id, -abs(float(amount)))
    acc = _apply_delta_to_account(acc, to_account_id, +abs(float(amount)))
    save_accounts(acc)
    _append_tx({
        "date": pd.to_datetime(when).date().isoformat(),
        "kind": "transfer", "amount": float(amount), "currency": currency,
        "account_id": str(from_account_id), "counterparty_account_id": str(to_account_id),
        "category": "transfer_out", "ref_table": "", "ref_id": "", "note": note or ""
    })
    _append_tx({
        "date": pd.to_datetime(when).date().isoformat(),
        "kind": "transfer", "amount": float(amount), "currency": currency,
        "account_id": str(to_account_id), "counterparty_account_id": str(from_account_id),
        "category": "transfer_in", "ref_table": "", "ref_id": "", "note": note or ""
    })

def accrue_credit_card_interest(statement_date: date | None = None):
    """Monthly interest: simple APR/12 on current owed (>=0)."""
    when = pd.to_datetime(statement_date or date.today()).date()
    acc = load_accounts()
    changed = False
    for i, row in acc.iterrows():
        if str(row.get("account_type","")).strip().lower() != "credit card":
            continue
        bal = float(row.get("balance", 0.0))
        apr = float(row.get("apr", 0.0))
        if bal <= 0 or apr <= 0:
            continue
        interest = round(bal * (apr/100.0/12.0), 2)
        if interest <= 0:
            continue
        acc = _apply_delta_to_account(acc, row["account_id"], -interest)  # increases owed
        _append_tx({
            "date": when.isoformat(),
            "kind": "interest", "amount": float(interest), "currency": row.get("currency","GBP"),
            "account_id": str(row["account_id"]), "counterparty_account_id": "",
            "category": "interest", "ref_table": "", "ref_id": "", "note": f"Monthly interest @{apr}% APR"
        })
        changed = True
    if changed:
        save_accounts(acc)

# ---------- optional one-off fixer ----------

def backfill_transaction_ids():
    """Assign sequential IDs where missing/NaN and normalize columns."""
    if not _file_exists_and_nonempty(TRANSACTIONS_CSV):
        return
    df = pd.read_csv(TRANSACTIONS_CSV, encoding="utf-8-sig")
    for c in TX_COLUMNS:
        if c not in df.columns:
            df[c] = "" if c not in ("amount", "id") else 0
    s = pd.to_numeric(df["id"], errors="coerce")
    current_max = int(s.max()) if s.notna().any() else 0
    need = s.isna()
    if need.any():
        start = current_max + 1
        df.loc[need, "id"] = range(start, start + need.sum())
    df = df[TX_COLUMNS]
    df.to_csv(TRANSACTIONS_CSV, index=False, encoding="utf-8-sig")