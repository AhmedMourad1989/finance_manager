# transactions.py
import os
import pandas as pd
import streamlit as st
from user_data import path_in_user_dir

TX_PATH = path_in_user_dir("transactions.csv")

EXPECTED_COLS = [
    "id","date","kind","amount","currency","account_id",
    "counterparty_account_id","category","ref_table","ref_id","note"
]

def load_transactions(path: str) -> pd.DataFrame:
    """Load transactions with sensible dtypes; assume headers are correct."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=EXPECTED_COLS)

    df = pd.read_csv(path, encoding="utf-8-sig")

    # Ensure expected columns exist (in case older files lack optional cols)
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    # Types
    df["id"] = pd.to_numeric(df["id"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    # Strings
    for c in ["kind","currency","account_id","counterparty_account_id","category","ref_table","ref_id","note"]:
        df[c] = df[c].astype(str).fillna("")

    # Order columns consistently
    df = df[EXPECTED_COLS]

    return df

def transactions_view():
    st.title("Transactions 📜")

    df = load_transactions(TX_PATH)
    if df.empty:
        st.info("No transactions yet.")
        return

    # ---------- Filters ----------
    with st.expander("Filters", expanded=True):
        # Kind
        kind_options = sorted([k for k in df["kind"].dropna().astype(str).unique() if k])
        kinds = st.multiselect("Kind", options=kind_options, default=[])

        # Account / Category contains
        c1, c2 = st.columns(2)
        with c1:
            acct = st.text_input("Account ID contains…", placeholder="e.g. 1234")
        with c2:
            cat = st.text_input("Category contains…", placeholder="e.g. Groceries")

        # Date range (based on min/max present)
        dmin, dmax = df["date"].min(), df["date"].max()
        if pd.notna(dmin) and pd.notna(dmax):
            start, end = st.date_input(
                "Date range",
                value=(dmin.date(), dmax.date()),
                min_value=dmin.date(),
                max_value=dmax.date()
            )
        else:
            start, end = None, None

        # Quick refresh
        if st.button("Refresh ↻", use_container_width=False):
            st.rerun()

    # ---------- Apply filters ----------
    q = df.copy()

    if kinds:
        q = q[q["kind"].isin(kinds)]
    if acct:
        q = q[q["account_id"].str.contains(acct, case=False, na=False)]
    if cat:
        q = q[q["category"].str.contains(cat, case=False, na=False)]
    if start and end:
        q = q[(q["date"] >= pd.to_datetime(start)) & (q["date"] <= pd.to_datetime(end))]

    # ---------- Order + Show ----------
    # Prefer date desc then id desc (fallback to id if date is NaT)
    q = q.sort_values(
        by=["date","id"] if "date" in q.columns else ["id"],
        ascending=[False, False] if "date" in q.columns else [False],
        kind="stable"
    )

    st.dataframe(
        q,
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.NumberColumn(format="%d"),
            "date": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
            "amount": st.column_config.NumberColumn(format="%.2f"),
            "currency": st.column_config.TextColumn(width="small"),
            "kind": st.column_config.TextColumn(width="small"),
            "account_id": st.column_config.TextColumn(width="medium"),
            "counterparty_account_id": st.column_config.TextColumn(width="medium"),
            "category": st.column_config.TextColumn(width="medium"),
            "ref_table": st.column_config.TextColumn(width="small"),
            "ref_id": st.column_config.TextColumn(width="small"),
            "note": st.column_config.TextColumn(width="large"),
        }
    )