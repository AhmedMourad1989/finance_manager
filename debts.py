# debts.py
import os
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import ledger as lg
from user_data import path_in_user_dir

# FIX: per-user file without extra "data/"
DEBTS_CSV = path_in_user_dir("debts.csv")

# Target schema
DEBT_COLS = [
    "id","lender","debt_type","account_id","original_amount","current_balance",
    "currency","apr","min_payment","payment_day","note",
]

# -----------------------
# CSV helpers
# -----------------------

def _exists_nonempty(p: str) -> bool:
    return os.path.exists(p) and os.path.getsize(p) > 0

def _ensure_file():
    # path_in_user_dir already ensures parent, but keep guard
    os.makedirs(os.path.dirname(DEBTS_CSV), exist_ok=True)
    if not _exists_nonempty(DEBTS_CSV):
        pd.DataFrame(columns=DEBT_COLS).to_csv(DEBTS_CSV, index=False, encoding="utf-8-sig")
        return

    # Coerce existing file into our schema (add missing cols)
    df = pd.read_csv(DEBTS_CSV, encoding="utf-8-sig")
    changed = False
    for c in DEBT_COLS:
        if c not in df.columns:
            df[c] = pd.NA
            changed = True
    if changed:
        df = df[DEBT_COLS]
        df.to_csv(DEBTS_CSV, index=False, encoding="utf-8-sig")

def _next_id() -> int:
    if not _exists_nonempty(DEBTS_CSV):
        return 1
    s = pd.read_csv(DEBTS_CSV, usecols=["id"], encoding="utf-8-sig")["id"]
    m = pd.to_numeric(s, errors="coerce").max()
    return (0 if pd.isna(m) else int(m)) + 1

@st.cache_data
def load_debts() -> pd.DataFrame:
    _ensure_file()
    df = pd.read_csv(DEBTS_CSV, encoding="utf-8-sig")
    # types / defaults
    for c in ["original_amount", "current_balance", "apr", "min_payment"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    if "payment_day" in df.columns:
        df["payment_day"] = pd.to_numeric(df["payment_day"], errors="coerce").fillna(1).clip(1, 28).astype(int)
    for c in ["lender","debt_type","account_id","currency","note"]:
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str)
    return df[DEBT_COLS]

def save_debts(df: pd.DataFrame):
    df = df[DEBT_COLS].copy()
    df.to_csv(DEBTS_CSV, index=False, encoding="utf-8-sig")
    load_debts.clear()

# -----------------------
# Calculations
# -----------------------

def next_due_date(payment_day: int, today: date | None = None) -> date:
    """Next calendar date with that day-of-month (1..28)."""
    t = pd.to_datetime(today or date.today())
    this_month = t.replace(day=min(payment_day, 28))
    if this_month.date() >= t.date():
        return this_month.date()
    nm = (this_month + pd.DateOffset(months=1)).replace(day=min(payment_day, 28))
    return nm.date()

def default_min_payment(balance: float, explicit_min: float | None = None) -> float:
    """If explicit min set, use it; else UK-ish rule: max(£25, 3% of balance)."""
    if explicit_min and explicit_min > 0:
        return round(float(explicit_min), 2)
    return round(max(25.0, abs(balance) * 0.03), 2)

def monthly_interest(amount: float, apr: float) -> float:
    """Simple monthly interest = APR/12 * amount."""
    if apr <= 0 or amount <= 0:
        return 0.0
    return round(float(amount) * (apr / 100.0 / 12.0), 2)

# -----------------------
# Actions
# -----------------------

def accrue_loan_interest_all(when: date | None = None):
    """
    Apply monthly interest to non–credit-card debts.
    If a debt has a linked 'Loan' account, post an 'interest' expense via ledger.
    Otherwise, bump 'current_balance' in debts.csv.
    """
    when = when or date.today()
    debts = load_debts().copy()
    if debts.empty:
        return 0

    accounts = lg.load_accounts()
    n = 0

    for i, r in debts.iterrows():
        debt_type = str(r["debt_type"]).strip().lower()
        if debt_type not in {"loan", "overdraft", "other"}:
            # credit cards handled elsewhere
            continue

        apr = float(r["apr"])
        if apr <= 0:
            continue

        # principal source
        principal = 0.0
        acc_id = str(r.get("account_id", "")).strip()
        acc_row = None
        if acc_id:
            idx = accounts.index[accounts["account_id"].astype(str) == acc_id]
            if len(idx):
                acc_row = accounts.loc[idx[0]]
                principal = float(acc_row.get("balance", 0.0))
            else:
                principal = float(r.get("current_balance", 0.0))
        else:
            principal = float(r.get("current_balance", 0.0))

        intr = monthly_interest(principal, apr)
        if intr <= 0:
            continue

        if acc_row is not None:
            lg.post_expense(
                account_id=acc_id,
                amount=intr,
                currency=str(acc_row.get("currency", "GBP")),
                when=when,
                category="Interest",
                note=f"Monthly interest @ {apr:.2f}% APR (loan)",
                ref_table="debts_interest",
                ref_id=int(r["id"]),
            )
        else:
            debts.at[i, "current_balance"] = round(float(r.get("current_balance", 0.0)) + intr, 2)

        n += 1

    save_debts(debts)
    return n

def pay_debt(from_account_id: str, debt_account_id: str | None, amount: float, currency: str, when: date, note: str, debt_row_id: int | None = None):
    """
    Payment from bank/current to the debt:
    - If linked account exists -> ledger transfer bank -> loan account.
    - Else -> decrement debts.csv current_balance + write a bank expense row for history.
    """
    amount = float(amount)
    if amount <= 0:
        raise ValueError("Payment amount must be > 0")

    if debt_account_id:
        lg.transfer(from_account_id, debt_account_id, amount, currency, when, note=note or "Debt payment")
    else:
        df = load_debts().copy()
        if debt_row_id is None:
            raise ValueError("Standalone debt payment requires debt_row_id")
        row = df.loc[df["id"] == debt_row_id]
        if row.empty:
            raise ValueError("Debt not found")
        idx = row.index[0]
        new_bal = max(0.0, float(df.at[idx, "current_balance"]) - amount)
        df.at[idx, "current_balance"] = round(new_bal, 2)
        save_debts(df)
        lg.post_expense(
            account_id=from_account_id,
            amount=amount,
            currency=currency,
            when=when,
            category="Debt Payment",
            note=note or f"Payment to {row.iloc[0].get('lender','debt')}",
            ref_table="debts_payment",
            ref_id=int(debt_row_id),
        )

# -----------------------
# UI Page
# -----------------------

def get_debts():
    st.title("Debts 📉")
    _ensure_file()

    debts = load_debts().copy()
    accts  = lg.load_accounts().copy()
    accts["account_id"] = accts["account_id"].astype(str)

    rows = []
    today = date.today()

    for _, r in debts.iterrows():
        lender  = r["lender"]
        dtype   = str(r["debt_type"]).strip().title() or "Loan"
        apr     = float(r["apr"])
        acc_id  = str(r.get("account_id","") or "")
        currency = r.get("currency","") or "GBP"
        explicit_min = float(r.get("min_payment", 0.0))
        pday    = int(r.get("payment_day", 1))

        # Live balance: prefer linked account if present
        bal = float(r.get("current_balance", 0.0))
        if acc_id:
            idx = accts.index[accts["account_id"].astype(str) == acc_id]
            if len(idx):
                bal = float(accts.loc[idx[0], "balance"])

        min_due = default_min_payment(bal, explicit_min or None)
        due_dt  = next_due_date(pday, today)

        rows.append({
            "id": int(r["id"]),
            "lender": lender,
            "type": dtype,
            "APR %": apr,
            "balance": round(bal, 2),
            "min_due": min_due,
            "due_date": due_dt.isoformat(),
            "currency": currency,
            "account_id": acc_id,
        })

    table = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","lender","type","APR %","balance","min_due","due_date","currency","account_id"])

    # KPIs
    total_bal = round(table["balance"].sum() if not table.empty else 0.0, 2)
    avg_apr   = round(table["APR %"].mean() if not table.empty else 0.0, 2)

    c1, c2 = st.columns(2)
    c1.metric("Total Debt Balance", f"{total_bal:,.2f}")
    c2.metric("Average APR", f"{avg_apr:.2f}%")

    st.subheader("Debts Overview")
    if table.empty:
        st.info("No debts found. Add one below.")
    else:
        st.dataframe(
            table[["id","lender","type","APR %","balance","min_due","due_date","currency"]],
            use_container_width=True
        )

    # ------- Actions -------
    st.divider()
    st.subheader("Make a Payment")

    if table.empty and debts.empty:
        st.caption("Nothing to pay yet.")
    else:
        options = table.to_dict("records")
        if not options:
            st.caption("No debts to select.")
        else:
            selected = st.selectbox(
                "Choose a debt",
                options=options,
                format_func=lambda r: f"{r['lender']} • {r['type']} • bal {r['balance']:.2f}",
                key="debt_choice"
            )

            # Choose bank/source account (not a credit card)
            banks = accts[accts["account_type"].str.lower().isin(["current","savings","investment","other"])]
            if banks.empty:
                st.info("Add a bank/current/savings account to pay from.")
                return
            bank_opts = banks[["account_name","account_id","currency"]].to_dict("records")
            bank = st.selectbox(
                "Pay from",
                options=bank_opts,
                format_func=lambda r: f"{r['account_name']} ({r['currency']})",
                key="debt_pay_bank"
            )

            pay_mode = st.radio("Payment type", ["Minimum", "Custom"], horizontal=True, key="debt_pay_mode")

            amount = selected["min_due"]
            if pay_mode == "Custom":
                amount = st.number_input("Amount", min_value=0.0, step=25.0, value=float(selected["min_due"]))

            when = st.date_input("Payment date", value=date.today())
            currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"], index=0)
            note = st.text_input("Note (optional)", value=f"Debt payment to {selected['lender']}", key="debt_pay_note")

            if st.button("💸 Pay"):
                try:
                    debt_account_id = selected.get("account_id") or None
                    pay_debt(
                        from_account_id=bank["account_id"],
                        debt_account_id=debt_account_id,
                        amount=float(amount),
                        currency=currency,
                        when=when,
                        note=note,
                        debt_row_id=int(selected["id"]),
                    )
                    st.success("Payment recorded ✅")
                except Exception as e:
                    st.error(f"Payment failed: {e}")

    st.divider()
    st.subheader("Accrue Monthly Interest (Loans/Overdrafts)")
    st.caption("Applies APR/12 for debts (type Loan/Overdraft/Other). Credit cards are handled in the Credit Card tab.")
    colA, colB = st.columns([1,2])
    with colA:
        when = st.date_input("Accrual date", value=date.today(), key="debt_intr_date")
    if st.button("➕ Accrue Interest"):
        try:
            n = accrue_loan_interest_all(when)
            st.success(f"Interest accrued on {n} debt(s) ✅")
        except Exception as e:
            st.error(f"Failed to accrue interest: {e}")

    st.divider()
    st.subheader("Add / Edit Debt")
    with st.form("debt_add_form", clear_on_submit=True):
        lender = st.text_input("Lender / Name")
        dtype  = st.selectbox("Debt type", ["loan","overdraft","other","credit card"], index=0)
        accounts = lg.load_accounts()
        acc_opts = accounts[["account_name","account_type","account_id","currency"]].to_dict("records")
        acc_choice = st.selectbox(
            "Linked account (optional, recommended)", 
            options=[{"account_name":"— None —","account_type":"","account_id":"","currency":""}] + acc_opts,
            format_func=lambda r: f"{r['account_name']} ({r['account_type']})" if r["account_id"] else r["account_name"]
        )
        acc_id = acc_choice["account_id"] if acc_choice and acc_choice.get("account_id") else ""

        original = st.number_input("Original amount", min_value=0.0, step=100.0)
        current  = st.number_input("Current balance (only used if no linked account)", min_value=0.0, step=100.0)
        currency = st.selectbox("Currency", ["GBP","USD","EUR","CAD","AUD"])
        apr      = st.number_input("APR %", min_value=0.0, step=0.1)
        minpay   = st.number_input("Minimum payment (leave 0 to auto-calc)", min_value=0.0, step=10.0)
        payday   = st.number_input("Payment day (1–28)", min_value=1, max_value=28, value=15, step=1)
        note     = st.text_area("Note", "")

        submitted = st.form_submit_button("Add / Save Debt")
        if submitted:
            try:
                df = load_debts().copy()
                nid = _next_id()
                new_row = pd.DataFrame([{
                    "id": nid,
                    "lender": lender.strip() or "Unnamed Debt",
                    "debt_type": dtype.strip().lower(),
                    "account_id": str(acc_id) if acc_id else "",
                    "original_amount": float(original),
                    "current_balance": float(current),
                    "currency": currency,
                    "apr": float(apr),
                    "min_payment": float(minpay),
                    "payment_day": int(payday),
                    "note": note or "",
                }], columns=DEBT_COLS)
                df = pd.concat([df, new_row], ignore_index=True)
                save_debts(df)
                st.success("Debt saved ✅")
            except Exception as e:
                st.error(f"Failed to save debt: {e}")