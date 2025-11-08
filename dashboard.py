# dashboard.py
import os
import pandas as pd
import streamlit as st
from datetime import date, timedelta
from ledger import load_accounts
from user_data import path_in_user_dir
from utils_format import fmt_money

# Per-user data paths (no extra "data/" prefix)
TX_PATH = path_in_user_dir("transactions.csv")
REC_EXP = path_in_user_dir("recurring_expenses.csv")
REC_INC = path_in_user_dir("recurring_incomes.csv")
CC_STM  = path_in_user_dir("credit_card_statements.csv")

def _read_tx():
    cols = ["id","date","kind","amount","currency","account_id",
            "counterparty_account_id","category","ref_table","ref_id","note"]
    if not os.path.exists(TX_PATH) or os.path.getsize(TX_PATH) == 0:
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(TX_PATH, encoding="utf-8-sig")
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    df["date"]       = pd.to_datetime(df["date"], errors="coerce")
    df["amount"]     = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["kind"]       = df["kind"].astype(str)
    df["category"]   = df["category"].astype(str)
    df["account_id"] = df["account_id"].astype(str)
    return df[cols]

def _is_liability(acc_type: str) -> bool:
    return str(acc_type).strip().lower() in {"credit card", "loan", "liability"}

def _read_df_if_any(path, columns):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, encoding="utf-8-sig")
    for c in columns:
        if c not in df.columns:
            df[c] = pd.NA
    return df

def _upcoming_recurring(days=30) -> pd.DataFrame:
    rows = []
    today = pd.Timestamp.today().normalize()
    horizon = today + pd.Timedelta(days=days)

    def collect(path, kind, name_col):
        df = _read_df_if_any(path, [])
        if df.empty or "next_due_date" not in df.columns:
            return
        df["next_due_date"] = pd.to_datetime(df["next_due_date"], errors="coerce")
        q = df[(df["next_due_date"].notna()) &
               (df["next_due_date"] >= today) &
               (df["next_due_date"] <= horizon)]
        for _, r in q.iterrows():
            rows.append({
                "type": kind,
                "name": r.get(name_col, ""),
                "amount": r.get("amount", 0.0),
                "currency": r.get("currency", ""),
                "due_date": r.get("next_due_date"),
                "account_id": str(r.get("account_id", "")),
                "frequency": r.get("frequency", ""),
                "note": r.get("note", ""),
            })

    collect(REC_EXP, "Expense", "expense_type")
    collect(REC_INC, "Income",  "income_type")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.sort_values("due_date")

def _cc_due_within(days=14) -> pd.DataFrame:
    df = _read_df_if_any(CC_STM, [
        "id","card_account_id","period_start","period_end","statement_balance",
        "apr_at_cycle","min_due","due_date","paid_amount","paid_date",
        "carried_balance","note"
    ])
    if df.empty:
        return df
    df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    today = pd.Timestamp.today().normalize()
    horizon = today + pd.Timedelta(days=days)
    q = df[(df["due_date"].notna()) &
           (df["due_date"] >= today) &
           (df["due_date"] <= horizon)]
    return q.sort_values("due_date")

def _try_import_altair():
    try:
        import altair as alt
        return alt
    except Exception:
        return None

def dashboard():
    # tighter heading for visual balance
    st.markdown("### Dashboard 📊")

    # ---------- Filters ----------
    accts = load_accounts().copy()
    if accts.empty:
        st.info("Add an account to see balances.")
        return

    accts["account_id"] = accts["account_id"].astype(str)
    accts["is_liab"]    = accts["account_type"].apply(_is_liability)

    with st.expander("Filters", expanded=True):
        account_options = [{"label": f"{r.account_name} ({r.account_type})", "value": r.account_id}
                           for _, r in accts.iterrows()]
        selected_accounts = st.multiselect(
            "Accounts (blank = all)",
            options=[o["value"] for o in account_options],
            format_func=lambda v: next((o["label"] for o in account_options if o["value"] == v), v),
            default=[],
        )
        colA, colB = st.columns(2)
        with colA:
            months_back = st.slider("Months back", 1, 24, 6)
        with colB:
            include_future = st.checkbox("Include future transactions", value=False)

    # ---------- Balance KPIs ----------
    assets = accts.loc[~accts["is_liab"], "balance"].sum()
    liabilities = accts.loc[accts["is_liab"], "balance"].sum()
    net_worth = round(assets - liabilities, 2)

    k1, k2, k3 = st.columns(3)
    k1.metric("Assets", fmt_money(assets))
    k2.metric("Liabilities (owed)", fmt_money(liabilities))
    k3.metric("Net Worth", fmt_money(net_worth))

    with st.expander("Accounts"):
        view = accts[["account_name","account_type","currency","balance"]].copy()
        view["Balance"] = [fmt_money(b, c) for b, c in zip(view["balance"], view["currency"])]
        view = view.drop(columns=["balance"]).rename(
            columns={"account_name":"Account","account_type":"Type","currency":"Cur."}
        ).sort_values("Account")
        st.dataframe(view, use_container_width=True, hide_index=True)

    # Quick visual: balances by account (Altair if available)
    st.subheader("Balances by Account")
    acc_view = accts[["account_name","account_type","balance"]].copy()
    if not acc_view.empty:
        alt = _try_import_altair()
        if alt:
            ch = (
                alt.Chart(acc_view)
                .mark_bar()
                .encode(
                    x=alt.X("balance:Q", title="Balance"),
                    y=alt.Y("account_name:N", sort="-x", title="Account"),
                    color=alt.Color("account_type:N", title="Type"),
                    tooltip=["account_name:N","account_type:N", alt.Tooltip("balance:Q", format=",.2f")],
                )
            )
            st.altair_chart(ch, use_container_width=True)
        else:
            st.bar_chart(acc_view.set_index("account_name")["balance"])

    # ---------- Transactions slice ----------
    tx = _read_tx()
    uncat = (tx["category"].str.strip() == "").sum() if not tx.empty else 0
    if uncat:
        st.caption(f"🟡 {uncat} uncategorised transaction(s). Open Rules to fix.")
    if selected_accounts:
        tx = tx[tx["account_id"].isin([str(a) for a in selected_accounts])]

    if not tx.empty:
        end = pd.Timestamp.today() + (pd.Timedelta(days=365) if include_future else pd.Timedelta(days=0))
        start = end - pd.DateOffset(months=months_back)
        txw = tx[(tx["date"] >= start) & (tx["date"] <= end)].copy()

        # Monthly cash flow
        txw["month"] = txw["date"].dt.to_period("M").astype(str)
        inc = txw[txw["kind"]=="income"].groupby("month")["amount"].sum().rename("income")
        exp = txw[txw["kind"]=="expense"].groupby("month")["amount"].sum().rename("expense")
        flow = pd.concat([inc, exp], axis=1).fillna(0.0)
        flow["net"] = flow["income"] - flow["expense"]

        st.subheader("Monthly Cash Flow")
        if not flow.empty:
            alt = _try_import_altair()
            if alt:
                flow2 = flow.reset_index().rename(columns={"index": "month"}) if "index" in flow.columns else flow.reset_index()
                if "month" not in flow2.columns:
                    flow2 = flow2.rename(columns={flow2.columns[0]: "month"})
                flow2["month_dt"] = pd.to_datetime(flow2["month"] + "-01", errors="coerce")
                flow2 = flow2.sort_values("month_dt")

                long = flow2.melt(
                    id_vars=["month","month_dt"],
                    value_vars=["income","expense","net"],
                    var_name="type",
                    value_name="value"
                )

                bars = (
                    alt.Chart(long)
                    .mark_bar()
                    .encode(
                        x=alt.X("month:N", sort=flow2["month"].tolist(), title="Month"),
                        y=alt.Y("value:Q", title="Amount"),
                        color=alt.Color("type:N", title=""),
                        tooltip=["month:N","type:N", alt.Tooltip("value:Q", format=",.2f")],
                    )
                )

                net_line = (
                    alt.Chart(long[long["type"] == "net"])
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("month:N", sort=flow2["month"].tolist()),
                        y=alt.Y("value:Q"),
                        tooltip=["month:N", alt.Tooltip("value:Q", format=",.2f")],
                    )
                )

                st.altair_chart((bars + net_line).interactive(), use_container_width=True)
            else:
                st.bar_chart(flow[["income","expense","net"]], use_container_width=True)
        else:
            st.caption("No transactions in selected window.")

        # Top expense categories in window
        recent_exp = txw[txw["kind"]=="expense"]
        if not recent_exp.empty:
            st.subheader("Top Expense Categories (Selected Window)")
            topcats = (
                recent_exp.groupby("category")["amount"]
                .sum()
                .sort_values(ascending=False)
                .head(8)
                .reset_index()
            )
            if not topcats.empty:
                alt = _try_import_altair()
                if alt:
                    ch = (
                        alt.Chart(topcats)
                        .mark_bar()
                        .encode(
                            x=alt.X("amount:Q", title="Amount"),
                            y=alt.Y("category:N", sort="-x", title="Category"),
                            tooltip=["category:N", alt.Tooltip("amount:Q", format=",.2f")],
                        )
                    )
                    st.altair_chart(ch, use_container_width=True)
                else:
                    st.bar_chart(topcats.set_index("category")["amount"])
            else:
                st.caption("No expense data in window.")

    # ---------- Alerts ----------
    st.subheader("Alerts 🔔")

    # Upcoming recurring (30 days)
    up = _upcoming_recurring(days=30)
    if up.empty:
        st.caption("No upcoming recurring items in 30 days.")
    else:
        st.write("**Upcoming Recurring (30 days)**")
        st.dataframe(up, use_container_width=True)

    # Credit card statements due within 14 days
    due = _cc_due_within(days=14)
    if due.empty:
        st.caption("No credit card statements due within 14 days.")
    else:
        st.write("**Credit Card Statements Due (≤14 days)**")
        show = due[[
            "id","card_account_id","period_end","statement_balance","min_due","due_date","paid_amount","carried_balance"
        ]].copy()
        st.dataframe(show, use_container_width=True, hide_index=True)