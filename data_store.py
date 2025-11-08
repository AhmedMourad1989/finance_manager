# data_store.py
import os
import io
import csv
import zipfile
from datetime import date
import hashlib

import pandas as pd
import streamlit as st

import ledger as lg
from user_data import path_in_user_dir, user_dir

# Optional rules engine (safe import)
try:
    from rules import apply_rules_to_transactions
    HAS_RULES = True
except Exception:
    HAS_RULES = False

TX_PATH = path_in_user_dir("transactions.csv")

REQUIRED_TX_COLS = [
    "id","date","kind","amount","currency","account_id",
    "counterparty_account_id","category","ref_table","ref_id","note"
]

def _exists_nonempty(p: str) -> bool:
    return os.path.exists(p) and os.path.getsize(p) > 0

def _read_tx_df() -> pd.DataFrame:
    if not _exists_nonempty(TX_PATH):
        return pd.DataFrame(columns=REQUIRED_TX_COLS)
    df = pd.read_csv(TX_PATH, encoding="utf-8-sig")
    for c in REQUIRED_TX_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["account_id"] = df["account_id"].astype(str)
    df["category"] = df["category"].fillna("").astype(str)
    df["note"] = df["note"].fillna("").astype(str)
    return df[REQUIRED_TX_COLS]

def _tx_key(date_str: str, amount: float, account_id: str, note: str) -> str:
    """Stable dedupe key."""
    raw = f"{date_str}|{amount:.2f}|{account_id}|{note[:60]}".encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()

def _known_keys(df: pd.DataFrame) -> set[str]:
    keys = set()
    if df.empty:
        return keys
    for _, r in df.iterrows():
        d = pd.to_datetime(r["date"]).date().isoformat() if pd.notna(r["date"]) else ""
        a = float(r.get("amount", 0.0))
        acc = str(r.get("account_id", ""))
        note = str(r.get("note", ""))
        keys.add(_tx_key(d, a, acc, note))
    return keys

def _map_amount(df: pd.DataFrame, amount_col: str, debit_col: str | None, credit_col: str | None, invert_amount: bool) -> pd.Series:
    """
    Build a signed amount series:
    - If both debit/credit given: signed = credit - debit
    - Else: use amount_col (invert sign if user ticked 'invert')
    """
    if debit_col and credit_col and debit_col in df and credit_col in df:
        debit = pd.to_numeric(df[debit_col], errors="coerce").fillna(0.0)
        credit = pd.to_numeric(df[credit_col], errors="coerce").fillna(0.0)
        series = credit - debit
    else:
        series = pd.to_numeric(df[amount_col], errors="coerce").fillna(0.0)
        if invert_amount:
            series = -series
    return series

def imports_exports():
    st.title("Imports / Exports 🔄")

    tabs = st.tabs(["📥 Import CSV", "📤 Export Data"])

    # --------------------------- IMPORT TAB ---------------------------
    with tabs[0]:
        st.subheader("Import bank/export CSV")
        st.caption("Map columns, preview, de-dupe, then commit to your ledger.")

        file = st.file_uploader("Upload a CSV file", type=["csv"], accept_multiple_files=False)
        if not file:
            st.info("Upload a CSV to begin.")
            st.divider()
        else:
            try:
                raw = pd.read_csv(file)
            except Exception as e:
                st.error(f"Failed to read CSV: {e}")
                return

            st.write("**Preview (first 20 rows)**")
            st.dataframe(raw.head(20), use_container_width=True)

            # Column mapping UI
            st.markdown("### Column mapping")
            cols = list(raw.columns)

            date_col   = st.selectbox("Date column", options=cols, index=0 if cols else None)
            amount_col = st.selectbox("Amount column (if your CSV has separate debit/credit, you can set them below)", options=[None] + cols, index=0)
            debit_col  = st.selectbox("Debit column (optional)", options=[None] + cols, index=0)
            credit_col = st.selectbox("Credit column (optional)", options=[None] + cols, index=0)

            invert_amount = st.checkbox("Invert amount sign", value=False,
                                        help="Tick if your amount column is positive for outgoings and negative for income (we want +income / -expense).")

            desc_col   = st.selectbox("Description / Memo column", options=[None] + cols, index=0)

            # Choose destination account
            accts = lg.load_accounts()
            if accts.empty:
                st.warning("No accounts found. Add an account first.")
                return
            accts_opts = accts[["account_name","account_type","account_id","currency"]].to_dict("records")
            dest = st.selectbox(
                "Import into account",
                options=accts_opts,
                format_func=lambda r: f"{r['account_name']} ({r['account_type']})",
                key="imp_acct",
            )

            currency = st.selectbox("Currency for these rows", ["GBP","USD","EUR","CAD","AUD"], index=0)

            # Build normalized frame
            if not date_col or (not amount_col and not (debit_col and credit_col)):
                st.info("Select at least Date and Amount (or Debit+Credit) to continue.")
                return

            norm = pd.DataFrame()
            norm["date"] = pd.to_datetime(raw[date_col], errors="coerce").dt.date.astype("string")
            norm["amount"] = _map_amount(raw, amount_col, debit_col, credit_col, invert_amount)
            norm["note"] = raw[desc_col].astype(str) if desc_col else ""
            norm["currency"] = currency
            norm["account_id"] = str(dest["account_id"])
            # classify kind from sign
            norm["kind"] = norm["amount"].apply(lambda x: "income" if x > 0 else ("expense" if x < 0 else ""))
            # ensure positive amounts for display; we'll send sign to the correct post_* call
            norm["abs_amount"] = norm["amount"].abs()

            # Drop rows with no date or zero amount
            norm = norm[(norm["date"].notna()) & (norm["date"] != "") & (norm["amount"] != 0.0)].copy()

            # De-dupe against existing transactions
            existing = _read_tx_df()
            known = _known_keys(existing)
            norm["key"] = norm.apply(lambda r: _tx_key(str(r["date"]), float(r["amount"]), str(r["account_id"]), str(r["note"])), axis=1)
            new_rows = norm[~norm["key"].isin(known)].copy()

            st.markdown("### Preview new rows (after de-duplication)")
            if new_rows.empty:
                st.success("Nothing new — all rows already exist.")
            else:
                show = new_rows[["date","kind","abs_amount","currency","note"]].rename(columns={"abs_amount":"amount"})
                st.dataframe(show.head(200), use_container_width=True, height=320)
                st.caption(f"Showing up to 200 of {len(new_rows)} new row(s).")

                # Commit button
                run_rules = st.checkbox("Auto-categorise after import (Rules engine)", value=HAS_RULES)
                if st.button("✅ Commit to ledger"):
                    try:
                        for _, r in new_rows.iterrows():
                            amt = float(r["amount"])
                            if amt > 0:
                                lg.post_income(
                                    account_id=r["account_id"],
                                    amount=amt,
                                    currency=r["currency"],
                                    when=pd.to_datetime(r["date"]).date(),
                                    category="",  # let rules fill later
                                    note=str(r["note"]),
                                )
                            else:
                                lg.post_expense(
                                    account_id=r["account_id"],
                                    amount=abs(amt),
                                    currency=r["currency"],
                                    when=pd.to_datetime(r["date"]).date(),
                                    category="",  # let rules fill later
                                    note=str(r["note"]),
                                )
                        # Apply rules to set categories (optional)
                        if run_rules and HAS_RULES:
                            apply_rules_to_transactions(dry_run=False)
                        st.success(f"Imported {len(new_rows)} transaction(s) into ledger.")
                    except Exception as e:
                        st.error(f"Import failed: {e}")

    # --------------------------- EXPORT TAB ---------------------------
    with tabs[1]:
        st.subheader("Export your data")

        tx = _read_tx_df()
        accts = lg.load_accounts()
        accts["account_id"] = accts["account_id"].astype(str)

        # filters
        col1, col2 = st.columns(2)
        with col1:
            date_from = st.date_input("From", value=date(2024,1,1))
        with col2:
            date_to   = st.date_input("To", value=date.today())

        sel_accounts = st.multiselect(
            "Accounts (blank = all)",
            options=accts["account_id"].tolist(),
            format_func=lambda aid: f"{accts.loc[accts['account_id']==aid, 'account_name'].values[0]}",
            default=[]
        )

        if not tx.empty:
            mask = (tx["date"].dt.date >= date_from) & (tx["date"].dt.date <= date_to)
            if sel_accounts:
                mask &= tx["account_id"].isin([str(a) for a in sel_accounts])
            out = tx[mask].copy()
        else:
            out = pd.DataFrame(columns=REQUIRED_TX_COLS)

        st.write("**Preview**")
        st.dataframe(out.head(300), use_container_width=True, height=320)
        st.caption(f"{len(out)} row(s) in selection.")

        # Download filtered transactions
        csv_bytes = out.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "⬇️ Download filtered transactions (CSV)",
            data=csv_bytes,
            file_name=f"transactions_{date_from.isoformat()}_{date_to.isoformat()}.csv",
            mime="text/csv",
        )

        # Optional: zip all per-user data files for quick backup
        st.markdown("### Full backup (zip)")
        if st.button("Create zip of all my data files"):
            buf = io.BytesIO()
            root = str(user_dir())
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for fname in sorted(os.listdir(root)):
                    path = os.path.join(root, fname)
                    if os.path.isfile(path):
                        z.write(path, arcname=fname)
            st.download_button(
                "⬇️ Download my_data.zip",
                data=buf.getvalue(),
                file_name="finance_data_backup.zip",
                mime="application/zip",
            )