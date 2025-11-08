# budgets.py
import os
from datetime import date
import pandas as pd
import streamlit as st
from user_data import path_in_user_dir

TX_PATH   = path_in_user_dir("transactions.csv")
CATS_PATH = path_in_user_dir("categories.csv")
BUD_PATH  = path_in_user_dir("budgets.csv")

BUD_COLS = ["id","month","category","amount","currency","active","note"]

def _exists_nonempty(p: str) -> bool:
    return os.path.exists(p) and os.path.getsize(p) > 0

def _ensure_files():
    if not _exists_nonempty(BUD_PATH):
        pd.DataFrame(columns=BUD_COLS).to_csv(BUD_PATH, index=False, encoding="utf-8-sig")
    if not _exists_nonempty(CATS_PATH):
        pd.DataFrame(columns=["id","kind","name","active"]).to_csv(CATS_PATH, index=False, encoding="utf-8-sig")

def _next_id(p: str, col="id") -> int:
    if not _exists_nonempty(p):
        return 1
    s = pd.read_csv(p, usecols=[col], encoding="utf-8-sig")[col]
    m = pd.to_numeric(s, errors="coerce").max()
    return (0 if pd.isna(m) else int(m)) + 1

def _read_tx():
    cols = ["date","kind","amount","currency","category","account_id","note"]
    if not _exists_nonempty(TX_PATH):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(TX_PATH, encoding="utf-8-sig")
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["category"] = df["category"].fillna("").astype(str)
    df["kind"] = df["kind"].fillna("").astype(str)
    return df[cols]

@st.cache_data
def load_budgets() -> pd.DataFrame:
    _ensure_files()
    df = pd.read_csv(BUD_PATH, encoding="utf-8-sig") if _exists_nonempty(BUD_PATH) \
         else pd.DataFrame(columns=BUD_COLS)
    for c in BUD_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["active"] = df["active"].fillna(True).astype(bool)
    df["month"]  = df["month"].fillna("").astype(str)  # YYYY-MM
    df["category"] = df["category"].fillna("").astype(str)
    df["currency"] = df["currency"].fillna("GBP").astype(str)
    df["note"] = df["note"].fillna("").astype(str)
    return df[BUD_COLS]

def save_budgets(df: pd.DataFrame):
    df = df[BUD_COLS].copy()
    df.to_csv(BUD_PATH, index=False, encoding="utf-8-sig")
    load_budgets.clear()

def _month_str(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"

def _month_bounds(yyyymm: str):
    y, m = map(int, yyyymm.split("-"))
    start = pd.Timestamp(y, m, 1)
    end   = start + pd.offsets.MonthEnd(1)  # last day inclusive
    return start, end

def budgets_page():
    st.title("Budgets 📅")

    _ensure_files()
    tx = _read_tx()
    cats = pd.read_csv(CATS_PATH, encoding="utf-8-sig") if _exists_nonempty(CATS_PATH) \
           else pd.DataFrame(columns=["name"])
    categories = sorted(set(
        cats.get("name", pd.Series(dtype=str)).dropna().tolist() +
        tx.get("category", pd.Series(dtype=str)).dropna().tolist()
    ))
    budgets = load_budgets().copy()

    # ---- Month picker ----
    today = date.today()
    default_month = _month_str(today)
    st.write("Select month")
    colA, colB = st.columns(2)
    with colA:
        month = st.text_input("YYYY-MM", value=default_month, help="Type a month like 2025-11")
    with colB:
        currency = st.selectbox("Default currency", ["GBP","USD","EUR","CAD","AUD"], index=0)

    # ---- Add budget form ----
    with st.form("add_budget", clear_on_submit=True):
        col1, col2 = st.columns([2,1])
        with col1:
            cat = st.selectbox("Category", options=[""] + categories, index=0, help="Pick or leave blank to type below")
            if not cat:
                cat = st.text_input("Or type a new category")
        with col2:
            amt = st.number_input("Monthly limit", min_value=0.0, step=10.0, value=0.0)
        note = st.text_input("Note", "")
        submitted = st.form_submit_button("Add budget")
        if submitted:
            if not month or len(month.split("-")) != 2:
                st.error("Please enter month in YYYY-MM format.")
            elif not cat or not str(cat).strip():
                st.error("Please choose a category.")
            elif amt <= 0:
                st.error("Amount must be > 0.")
            else:
                nid = _next_id(BUD_PATH)
                header = not _exists_nonempty(BUD_PATH)
                pd.DataFrame([{
                    "id": nid,
                    "month": month.strip(),
                    "category": str(cat).strip(),
                    "amount": float(amt),
                    "currency": currency,
                    "active": True,
                    "note": note or "",
                }], columns=BUD_COLS).to_csv(BUD_PATH, mode="a", index=False, header=header, encoding="utf-8-sig")
                load_budgets.clear()
                st.success("Budget added.")

    st.divider()
    st.subheader("Budgets for selected month")

    # filter budgets for the month
    bud_m = budgets[(budgets["month"] == month) & (budgets["active"])].copy()
    if bud_m.empty:
        st.caption("No budgets set for this month yet.")
    else:
        # Compute actual spend for the month (expenses only).
        # Your ledger stores expense amounts as positive numbers; abs() is harmless here.
        start, end = _month_bounds(month)
        txm = tx[(tx["date"] >= start) & (tx["date"] <= end)]
        spent = (txm[txm["kind"] == "expense"]
                 .groupby("category")["amount"]
                 .sum()
                 .abs()   # safe even if amounts are positive
                 .rename("spent"))
        view = bud_m.merge(spent, how="left", left_on="category", right_index=True).fillna({"spent": 0.0})
        view["remaining"] = (view["amount"] - view["spent"]).round(2)
        view = view.sort_values("category")

        # Progress display
        for _, r in view.iterrows():
            used = float(r["spent"])
            cap  = float(r["amount"])
            pct  = 0 if cap <= 0 else min(100, int(round((used / cap) * 100)))
            st.write(f"**{r['category']}** — {used:,.2f} / {cap:,.2f} {r['currency']}  (remaining {r['remaining']:,.2f})")
            st.progress(pct)

        st.dataframe(view[["category","amount","spent","remaining","currency","note"]], use_container_width=True)

    st.divider()
    st.subheader("Manage budgets")
    edited = st.data_editor(
        budgets.reset_index(drop=True),
        use_container_width=True,
        num_rows="dynamic",
        key="bud_editor",
        column_config={
            "id": st.column_config.NumberColumn(disabled=True),
            "month": st.column_config.TextColumn(help="YYYY-MM"),
            "category": st.column_config.TextColumn(),
            "amount": st.column_config.NumberColumn(step=10.0, min_value=0.0),
            "currency": st.column_config.SelectboxColumn(options=["GBP","USD","EUR","CAD","AUD"]),
            "active": st.column_config.CheckboxColumn(),
            "note": st.column_config.TextColumn(),
        }
    )
    if st.button("Save budgets"):
        try:
            save_budgets(edited)
            st.success("Saved.")
        except Exception as e:
            st.error(f"Failed to save: {e}")