# finance.py
import os
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import pandas as pd
import streamlit as st

import ledger as lg
from categories import category_select
from user_data import path_in_user_dir

# ================================
# Helpers (defined BEFORE use)
# ================================

def _exists_nonempty(p: str) -> bool:
    return os.path.exists(p) and os.path.getsize(p) > 0

def _safe_read_csv(path: str, columns: list[str]) -> pd.DataFrame:
    """Read CSV with utf-8-sig and guarantee columns exist."""
    if not _exists_nonempty(path):
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, encoding="utf-8-sig")
    for c in columns:
        if c not in df.columns:
            df[c] = pd.NA
    return df[columns]

def load_accounts() -> pd.DataFrame:
    """Load per-user accounts CSV with stable schema and safe defaults."""
    cols = ["id","account_name","account_type","account_id","balance","currency","limit","apr","note"]
    path = path_in_user_dir("accounts.csv")
    df = _safe_read_csv(path, cols)

    # one-time repair for earlier typo
    if "limt" in df.columns:
        df = df.rename(columns={"limt": "limit"})

    # ensure essential fields & dtypes
    if "account_id" not in df.columns:
        df["account_id"] = df["id"]
    df["account_id"]   = df["account_id"].astype(str)
    df["account_name"] = df["account_name"].fillna("Unnamed account").astype(str)
    df["account_type"] = df["account_type"].fillna("").astype(str).str.strip()
    df["currency"]     = df["currency"].fillna("GBP").astype(str).str.upper()

    # numerics
    for c in ["balance","limit","apr"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    return df

def account_selectbox(label: str, key: str):
    """Show NAME in UI, return the underlying account_id (string)."""
    df = load_accounts()
    if df.empty:
        st.info("No accounts found yet. Enter an account ID manually.")
        return st.text_input("Account ID", key=f"{key}_manual")

    options = df[["account_name", "account_type", "account_id"]].to_dict("records")

    def fmt(r):
        t = f" ({r['account_type']})" if r.get("account_type") else ""
        return f"{r['account_name']}{t}"

    chosen = st.selectbox(label, options=options, format_func=fmt, key=key)
    return str(chosen["account_id"])

def next_seq_id(csv_path: str, id_col: str = "id") -> int:
    """Return next sequential integer id from a CSV safely."""
    if not _exists_nonempty(csv_path):
        return 1
    try:
        s = pd.read_csv(csv_path, usecols=[id_col], encoding="utf-8-sig")[id_col]
        m = pd.to_numeric(s, errors="coerce").max()
        return (0 if pd.isna(m) else int(m)) + 1
    except Exception:
        return 1

# ================================
# Recurrence utilities
# ================================

FREQ_OFFSETS = {
    "Yearly":     lambda dt: dt + relativedelta(years=1),
    "Monthly":    lambda dt: dt + relativedelta(months=1),
    "Bi-Monthly": lambda dt: dt + relativedelta(months=2),
    "Quarterly":  lambda dt: dt + relativedelta(months=3),
    "Weekly":     lambda dt: dt + timedelta(weeks=1),
    "Bi-Weekly":  lambda dt: dt + timedelta(weeks=2),
    "Daily":      lambda dt: dt + timedelta(days=1),
}

def time_calculation(next_due_date, frequency: str):
    if pd.isna(next_due_date):
        return pd.NaT
    if not isinstance(next_due_date, (pd.Timestamp,)):
        next_due_date = pd.to_datetime(next_due_date, errors="coerce")
    func = FREQ_OFFSETS.get(frequency, lambda dt: dt)
    return func(next_due_date)

# (kept for possible future use)
def _empty_expenses_df():
    return pd.DataFrame(columns=["id","expense_type","amount","currency","date","account_id","note"])

def _empty_income_df():
    return pd.DataFrame(columns=["id","income_type","amount","currency","date","account_id","note"])

# ================================
# Recurring processors (ledger-aware)
# ================================

def process_recurring_expenses():
    rec_path = path_in_user_dir("recurring_expenses.csv")
    if not _exists_nonempty(rec_path):
        return
    rec = pd.read_csv(rec_path, encoding="utf-8-sig")
    if rec.empty:
        return

    rec = rec.copy()
    rec["next_due_date"] = pd.to_datetime(rec["next_due_date"], errors="coerce")
    today = pd.Timestamp.today().normalize()

    for i, row in rec.iterrows():
        nd = row["next_due_date"]
        if pd.isna(nd):
            continue
        freq = str(row.get("frequency", "")).strip()

        while nd <= today:
            try:
                lg.post_expense(
                    account_id=str(row.get("account_id","")),
                    amount=float(row.get("amount", 0.0)),
                    currency=str(row.get("currency","GBP")),
                    when=nd.date(),
                    category=str(row.get("expense_type","Expense")),
                    note=str(row.get("note","")),
                    ref_table="recurring_expenses",
                    ref_id=int(row.get("id", 0)) if "id" in row else None,
                )
            except Exception as e:
                st.warning(f"Failed to post recurring expense (id {row.get('id','?')}): {e}")
                break
            nd = time_calculation(nd, freq)

        rec.at[i, "next_due_date"] = nd

    rec.to_csv(rec_path, index=False, encoding="utf-8-sig")

def process_recurring_incomes():
    rec_path = path_in_user_dir("recurring_incomes.csv")
    if not _exists_nonempty(rec_path):
        return
    rec = pd.read_csv(rec_path, encoding="utf-8-sig")
    if rec.empty:
        return

    rec = rec.copy()
    rec["next_due_date"] = pd.to_datetime(rec["next_due_date"], errors="coerce")
    today = pd.Timestamp.today().normalize()

    for i, row in rec.iterrows():
        nd = row["next_due_date"]
        if pd.isna(nd):
            continue
        freq = str(row.get("frequency", "")).strip()

        while nd <= today:
            try:
                lg.post_income(
                    account_id=str(row.get("account_id","")),
                    amount=float(row.get("amount", 0.0)),
                    currency=str(row.get("currency","GBP")),
                    when=nd.date(),
                    category=str(row.get("income_type","Income")),
                    note=str(row.get("note","")),
                    ref_table="recurring_incomes",
                    ref_id=int(row.get("id", 0)) if "id" in row else None,
                )
            except Exception as e:
                st.warning(f"Failed to post recurring income (id {row.get('id','?')}): {e}")
                break
            nd = time_calculation(nd, freq)

        rec.at[i, "next_due_date"] = nd

    rec.to_csv(rec_path, index=False, encoding="utf-8-sig")

# ================================
# Pages
# ================================

def add_income():
    st.title("Add Income 💰")
    st.caption("Record a single income or create a recurring one.")
    st.divider()

    with st.form("form_add_income", clear_on_submit=True):
        income_label = category_select("Income", "Income category", key="income_cat")
        account_id = account_selectbox("Deposit to account", key="income_account")

        col1, col2 = st.columns([1,1])
        with col1:
            amount = st.number_input(f"Amount ({income_label or 'Income'})", min_value=0.0, step=100.0)
        with col2:
            currency = st.selectbox("Currency", ["GBP", "USD", "EUR", "CAD", "AUD"])

        col3, col4 = st.columns([1,1])
        with col3:
            income_date = st.date_input("Income date", value=date.today())
        with col4:
            frequency = st.selectbox("Frequency", ["One-Time", "Monthly", "Bi-Weekly", "Weekly", "Yearly", "Daily"])

        note = st.text_area("Notes (optional)", key="income_note")

        submitted = st.form_submit_button("➕ Add income")
        if submitted:
            if not account_id:
                st.error("Please select an account.")
                return
            if amount <= 0:
                st.error("Amount must be greater than 0.")
                return
            try:
                lg.post_income(
                    account_id=account_id,
                    amount=float(amount),
                    currency=currency,
                    when=income_date,
                    category=income_label or "Income",
                    note=note,
                    ref_table="manual_income",
                    ref_id=None,
                )
            except Exception as e:
                st.error(f"Failed to post income: {e}")
                return

            # create recurring entry if needed
            if frequency != "One-Time":
                rec_path = path_in_user_dir("recurring_incomes.csv")
                rec_nid = next_seq_id(rec_path)
                next_due = time_calculation(pd.to_datetime(income_date), frequency)
                pd.DataFrame([{
                    "id": int(rec_nid),
                    "income_type": income_label or "Income",
                    "amount": float(amount),
                    "currency": currency,
                    "frequency": frequency,
                    "next_due_date": next_due.date().isoformat() if pd.notna(next_due) else "",
                    "account_id": str(account_id),
                    "note": note or "",
                }])[["id","income_type","amount","currency","frequency","next_due_date","account_id","note"]]\
                  .to_csv(rec_path, mode="a", index=False,
                          header=not os.path.exists(rec_path), encoding="utf-8-sig")

            st.success("Income added successfully ✅")
            st.rerun()

def add_expense():
    st.title("Add Expense 🧾")
    st.caption("Record a single expense.")
    st.divider()

    with st.form("form_add_expense", clear_on_submit=True):
        expense_label = category_select("Expense", "Expense category", key="expense_cat")
        account_id = account_selectbox("Paid from account", key="expense_account")

        col1, col2 = st.columns([1,1])
        with col1:
            amount = st.number_input(f"Amount ({expense_label or 'Expense'})", min_value=0.0, step=50.0)
        with col2:
            currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"])

        expense_date = st.date_input("Expense date", value=date.today())
        note = st.text_area("Notes (optional)", key="expense_note")

        submitted = st.form_submit_button("➖ Add expense")
        if submitted:
            if not account_id:
                st.error("Please select an account.")
                return
            if amount <= 0:
                st.error("Amount must be greater than 0.")
                return
            try:
                lg.post_expense(
                    account_id=account_id,
                    amount=float(amount),
                    currency=currency,
                    when=expense_date,
                    category=expense_label or "Expense",
                    note=note,
                    ref_table="manual_expense",
                    ref_id=None,
                )
            except Exception as e:
                st.error(f"Failed to post expense: {e}")
                return

            st.success("Expense added successfully ✅")
            st.rerun()

def recurring_expenses():
    st.title("Recurring Expenses 🔁")
    st.caption("Create a recurring expense; it will auto-post on/after the due date.")
    st.divider()

    with st.form("form_recurring_expense", clear_on_submit=True):
        expense_label = category_select("Expense", "Recurring expense category", key="rec_expense_cat")
        account_id = account_selectbox("Paid from account", key="recurring_expense_account")

        col1, col2 = st.columns([1,1])
        with col1:
            amount = st.number_input(f"Amount ({expense_label or 'Expense'})", min_value=0.0, step=50.0)
        with col2:
            currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"])

        col3, col4 = st.columns([1,1])
        with col3:
            frequency = st.selectbox("Frequency", ["Monthly","Bi-Weekly","Weekly","Yearly","Daily"])
        with col4:
            next_due_date = st.date_input("Next due date", value=date.today())

        note = st.text_area("Notes (optional)", key="recurring_expense_note")

        submitted = st.form_submit_button("🔁 Save recurring expense")
        if submitted:
            if not account_id:
                st.error("Please select an account.")
                return
            if amount <= 0:
                st.error("Amount must be greater than 0.")
                return

            rec_path = path_in_user_dir("recurring_expenses.csv")
            nid = next_seq_id(rec_path)

            pd.DataFrame([{
                "id": int(nid),
                "expense_type": expense_label or "Expense",
                "amount": float(amount),
                "currency": currency,
                "frequency": frequency,
                "next_due_date": pd.to_datetime(next_due_date).date().isoformat(),
                "account_id": str(account_id),
                "note": note or "",
            }])[["id","expense_type","amount","currency","frequency","next_due_date","account_id","note"]]\
              .to_csv(rec_path, mode="a", index=False,
                      header=not os.path.exists(rec_path), encoding="utf-8-sig")

            st.success("Recurring expense added successfully ✅")
            st.rerun()

def add_account():
    st.title("Add Account 🏦")
    st.caption("Current/Savings/Credit Card/Investment/Other")
    st.divider()

    with st.form("form_add_account", clear_on_submit=True):
        account_name = st.text_input("Account name (Bank / Card) *")
        account_type = st.selectbox("Account type *", ["Current","Savings","Credit Card","Investment","Other"])
        account_id   = st.text_input("Account ID (e.g., account number) *")

        c1, c2 = st.columns([1,1])
        with c1:
            balance = st.number_input("Initial balance", min_value=0.0, step=100.0)
            currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"])
        with c2:
            limit_v = st.number_input("Limit (for credit cards/overdrafts)", min_value=0.0, step=100.0)
            apr     = st.number_input("APR % (for credit cards/loans)", min_value=0.0, step=0.1)

        note = st.text_area("Notes (optional)", key="account_note")

        submitted = st.form_submit_button("➕ Add account")
        if submitted:
            if not str(account_name).strip():
                account_name = "Unnamed account"
            if not str(account_id).strip():
                st.error("Account ID is required.")
                return

            path = path_in_user_dir("accounts.csv")
            cols = ["id","account_name","account_type","account_id","balance","currency","limit","apr","note"]
            _ = _safe_read_csv(path, cols)  # ensure header on empty write
            nid = next_seq_id(path)

            pd.DataFrame([{
                "id": int(nid),
                "account_name": account_name,
                "account_type": account_type,
                "account_id": account_id,
                "balance": float(balance),
                "currency": currency,
                "limit": float(limit_v),
                "apr": float(apr),
                "note": note or "",
            }])[cols].to_csv(path, mode="a", index=False,
                             header=not os.path.exists(path), encoding="utf-8-sig")

            # Clear ledger cache so new account appears everywhere
            lg.load_accounts.clear()

            st.success("Account added successfully ✅")
            st.rerun()

def transfer_funds():
    st.title("Transfer Funds 🔁")
    st.caption("Move money between your accounts.")
    st.divider()

    with st.form("form_transfer", clear_on_submit=True):
        from_acct = account_selectbox("From account", key="xfer_from")
        to_acct   = account_selectbox("To account",   key="xfer_to")

        if from_acct == to_acct and from_acct:
            st.warning("Select two different accounts.")

        c1, c2 = st.columns([1,1])
        with c1:
            amount   = st.number_input("Amount", min_value=0.0, step=50.0)
            currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"])
        with c2:
            when     = st.date_input("Transfer date", value=date.today())
            note     = st.text_input("Note (optional)")

        submitted = st.form_submit_button("➡️ Submit transfer")
        if submitted:
            if not from_acct or not to_acct:
                st.error("Please select both accounts.")
                return
            if from_acct == to_acct:
                st.error("From and To accounts must differ.")
                return
            if amount <= 0:
                st.error("Amount must be greater than 0.")
                return
            try:
                lg.transfer(from_acct, to_acct, float(amount), currency, when, note=note)
                st.success("Transfer recorded ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Transfer failed: {e}")

def pay_credit_card():
    import cc_statements as cc

    st.title("Pay Credit Card 💳")
    st.caption("Select a card, optionally close a statement, then make a payment.")
    st.divider()

    # choose card
    cards_df = load_accounts()
    cards_df = cards_df[cards_df["account_type"].str.strip().str.lower() == "credit card"].copy()
    if cards_df.empty:
        st.info("No credit cards found. Add a credit card account first.")
        return

    card_options = cards_df[["account_name","account_id","currency"]].to_dict("records")
    card = st.selectbox("Credit card", card_options, format_func=lambda r: f"{r['account_name']}", key="cc_pay_card")

    # choose bank/source (exclude credit cards)
    banks_df = load_accounts()
    banks_df = banks_df[banks_df["account_type"].str.strip().str.lower() != "credit card"].copy()
    if banks_df.empty:
        st.info("No bank accounts found.")
        return
    bank_options = banks_df[["account_name","account_id","currency"]].to_dict("records")
    bank = st.selectbox("Pay from (bank/current)", bank_options, format_func=lambda r: f"{r['account_name']}", key="cc_pay_bank")

    # latest statement
    from cc_statements import latest_open_stmt_for_card
    stmt_id = latest_open_stmt_for_card(card["account_id"])
    if stmt_id is None:
        st.caption("No statements found for this card yet. You can close one now.")

    # show current owed & min due info (if any)
    stmt_csv = path_in_user_dir("credit_card_statements.csv")
    stmt_df = pd.read_csv(stmt_csv, encoding="utf-8-sig") if _exists_nonempty(stmt_csv) else pd.DataFrame()
    if stmt_id and not stmt_df.empty:
        row = stmt_df.loc[stmt_df["id"] == stmt_id]
        if not row.empty:
            owed = float(pd.to_numeric(row["carried_balance"], errors="coerce").fillna(0.0).iloc[0])
            min_due = float(pd.to_numeric(row["min_due"], errors="coerce").fillna(0.0).iloc[0])
            due_date = str(row["due_date"].iloc[0])
            st.info(f"Carried balance: {owed:,.2f}  |  Minimum due: {min_due:,.2f}  |  Due: {due_date}")

    col_btn1, col_btn2 = st.columns([1,3])
    with col_btn1:
        if st.button("🔒 Close statement (today)"):
            try:
                nid = cc.close_statement(card["account_id"], date.today())
                st.success(f"Statement {nid} closed for {card['account_name']}.")
                stmt_id = nid
                st.rerun()
            except Exception as e:
                st.error(f"Failed to close statement: {e}")

    st.divider()

    with st.form("form_cc_payment", clear_on_submit=True):
        pay_mode = st.radio("Payment type", ["Minimum due", "Custom amount"], horizontal=True)

        pay_amount = 0.0
        if pay_mode == "Custom amount":
            pay_amount = st.number_input("Amount to pay", min_value=0.0, step=25.0, key="cc_pay_amt")
        else:
            if stmt_id and not stmt_df.empty:
                row = stmt_df.loc[stmt_df["id"] == stmt_id]
                if not row.empty:
                    pay_amount = float(pd.to_numeric(row["min_due"], errors="coerce").fillna(0.0).iloc[0])
            st.caption("Will pay the minimum due.")

        col1, col2 = st.columns([1,1])
        with col1:
            when = st.date_input("Payment date", value=date.today())
        with col2:
            currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"], index=0)

        note = st.text_input("Note (optional)", key="cc_pay_note")

        submitted = st.form_submit_button("💸 Make payment")
        if submitted:
            if stmt_id is None:
                st.error("No statement available—close a statement first.")
                return
            if pay_amount <= 0:
                st.error("Amount must be greater than 0.")
                return
            try:
                cc.record_cc_payment(
                    stmt_id,
                    from_bank_account_id=bank["account_id"],
                    amount=float(pay_amount),
                    currency=currency,
                    when=when,
                    note=note
                )
                st.success("Payment recorded and balances updated ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Payment failed: {e}")