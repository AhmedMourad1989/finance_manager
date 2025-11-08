# settings.py
import json
import os
import streamlit as st
from user_data import path_in_user_dir
from ledger import load_accounts

PREFS_JSON = path_in_user_dir("prefs.json")

DEFAULT_PREFS = {
    "display_name": "",
    "base_currency": "GBP",
    "dashboard_months_back": 6,
    "include_future_tx": False,
    "default_income_account": "",
    "default_expense_account": "",
    "week_starts_on": "Mon",
    "number_format": "1,234.56",
    "recurring_autorun": True,
    "cc_statement_day": 25,
    "min_payment_rule": "max(25, 3%)",
}

def _load_prefs() -> dict:
    if os.path.exists(PREFS_JSON):
        try:
            with open(PREFS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = {**DEFAULT_PREFS, **data}
                return merged
        except Exception:
            pass
    return DEFAULT_PREFS.copy()

def _save_prefs(p: dict):
    os.makedirs(os.path.dirname(PREFS_JSON), exist_ok=True)
    with open(PREFS_JSON, "w", encoding="utf-8") as f:
        json.dump(p, f, indent=2, ensure_ascii=False)

def settings():
    st.title("Settings ⚙️")

    prefs = _load_prefs()
    accts = load_accounts().copy()

    st.subheader("Profile")
    c1, c2 = st.columns(2)
    with c1:
        prefs["display_name"] = st.text_input("Display name", value=prefs.get("display_name",""))

        base_currencies = ["GBP","USD","EUR","CAD","AUD"]
        bc_val = prefs.get("base_currency","GBP")
        prefs["base_currency"] = st.selectbox(
            "Base currency",
            base_currencies,
            index=base_currencies.index(bc_val) if bc_val in base_currencies else 0
        )

    with c2:
        week_opts = ["Mon","Sun"]
        wk_val = prefs.get("week_starts_on","Mon")
        prefs["week_starts_on"] = st.selectbox(
            "Week starts on",
            week_opts,
            index=week_opts.index(wk_val) if wk_val in week_opts else 0
        )

        num_formats = ["1,234.56","1.234,56"]
        nf_val = prefs.get("number_format","1,234.56")
        prefs["number_format"] = st.selectbox(
            "Number format",
            num_formats,
            index=num_formats.index(nf_val) if nf_val in num_formats else 0
        )

    st.divider()
    st.subheader("Defaults")

    if accts.empty:
        acc_opts = []
    else:
        accts["account_id"] = accts["account_id"].astype(str)
        acc_opts = accts[["account_name","account_id","account_type"]].to_dict("records")

    id_list = [""] + [r["account_id"] for r in acc_opts]
    id_to_label = {"": "— None —"} | {
        r["account_id"]: f"{r['account_name']} ({r['account_type']})" for r in acc_opts
    }
    def fmt_account(aid: str) -> str:
        return id_to_label.get(aid, "— None —")

    left, right = st.columns(2)
    with left:
        inc_default = prefs.get("default_income_account","")
        inc_index = id_list.index(inc_default) if inc_default in id_list else 0
        prefs["default_income_account"] = st.selectbox(
            "Default income account",
            id_list,
            format_func=fmt_account,
            index=inc_index,
        )

        exp_default = prefs.get("default_expense_account","")
        exp_index = id_list.index(exp_default) if exp_default in id_list else 0
        prefs["default_expense_account"] = st.selectbox(
            "Default expense account",
            id_list,
            format_func=fmt_account,
            index=exp_index,
        )

    with right:
        prefs["dashboard_months_back"] = st.slider(
            "Dashboard: months back", 1, 24, int(prefs.get("dashboard_months_back",6))
        )
        prefs["include_future_tx"] = st.checkbox(
            "Dashboard: include future tx", value=bool(prefs.get("include_future_tx", False))
        )

    st.divider()
    st.subheader("Automation & Credit Cards")
    a1, a2 = st.columns(2)
    with a1:
        prefs["recurring_autorun"] = st.checkbox(
            "Auto-run recurring processors on load",
            value=bool(prefs.get("recurring_autorun", True))
        )
        cc_day = int(prefs.get("cc_statement_day", 25))
        if not (1 <= cc_day <= 28):
            cc_day = 25
        prefs["cc_statement_day"] = st.number_input(
            "Credit card statement day (1–28)",
            min_value=1, max_value=28, value=cc_day
        )
    with a2:
        st.caption(f"Minimum payment rule (info): {prefs.get('min_payment_rule','max(25, 3%)')}")

    st.divider()
    if st.button("Save settings"):
        _save_prefs(prefs)
        st.success("Settings saved.")