# rules.py
import os
import pandas as pd
import streamlit as st
from user_data import path_in_user_dir

RULES_CSV = path_in_user_dir("rules.csv")
TX_CSV    = path_in_user_dir("transactions.csv")

RULE_COLS = [
    "id",              # int
    "active",          # bool
    "priority",        # int (lower = applied first)
    "kind",            # "Income" | "Expense" | "" (UI value; we'll lowercase when applying)
    "category",        # target category name
    "match_field",     # "note" | "category" | "account_id"
    "contains",        # substring to look for
    "case_sensitive",  # bool
]

# ----------------- file helpers -----------------

def _exists_nonempty(p: str) -> bool:
    return os.path.exists(p) and os.path.getsize(p) > 0

def _ensure_rules_file():
    if not _exists_nonempty(RULES_CSV):
        pd.DataFrame(columns=RULE_COLS).to_csv(RULES_CSV, index=False, encoding="utf-8-sig")
        return
    df = pd.read_csv(RULES_CSV, encoding="utf-8-sig")
    changed = False
    for c in RULE_COLS:
        if c not in df.columns:
            df[c] = pd.NA
            changed = True
    if changed:
        df = df[RULE_COLS]
        df.to_csv(RULES_CSV, index=False, encoding="utf-8-sig")

def _next_id() -> int:
    if not _exists_nonempty(RULES_CSV):
        return 1
    s = pd.read_csv(RULES_CSV, usecols=["id"], encoding="utf-8-sig")["id"]
    m = pd.to_numeric(s, errors="coerce").max()
    return (0 if pd.isna(m) else int(m)) + 1

@st.cache_data
def load_rules() -> pd.DataFrame:
    _ensure_rules_file()
    df = pd.read_csv(RULES_CSV, encoding="utf-8-sig")
    # types/defaults
    if "active" in df: df["active"] = df["active"].fillna(True).astype(bool)
    if "priority" in df: df["priority"] = pd.to_numeric(df["priority"], errors="coerce").fillna(1000).astype(int)
    for c in ["kind","category","match_field","contains"]:
        if c in df: df[c] = df[c].fillna("").astype(str)
    if "case_sensitive" in df: df["case_sensitive"] = df["case_sensitive"].fillna(False).astype(bool)
    return df[RULE_COLS].sort_values(["priority","id"], ascending=[True,True])

def save_rules(df: pd.DataFrame):
    df = df[RULE_COLS].copy()
    df.to_csv(RULES_CSV, index=False, encoding="utf-8-sig")
    load_rules.clear()

# ----------------- core matching -----------------

def _match_contains(text: str, needle: str, case_sensitive: bool) -> bool:
    if not isinstance(text, str):
        text = "" if pd.isna(text) else str(text)
    if not isinstance(needle, str):
        needle = "" if pd.isna(needle) else str(needle)
    if not case_sensitive:
        text   = text.lower()
        needle = needle.lower()
    return needle in text if needle else False

def apply_rules_to_transactions(dry_run: bool = False) -> int:
    """
    Fill missing transaction categories by applying rules in priority order.
    Returns number of rows that got a category set.
    """
    _ensure_rules_file()
    if not _exists_nonempty(TX_CSV):
        return 0

    tx = pd.read_csv(TX_CSV, encoding="utf-8-sig")
    if tx.empty:
        return 0

    # ensure needed columns
    for c in ["category","kind","note","account_id"]:
        if c not in tx.columns:
            tx[c] = ""
    tx["category"]   = tx["category"].fillna("").astype(str)
    tx["note"]       = tx["note"].fillna("").astype(str)
    tx["kind"]       = tx["kind"].fillna("").astype(str)
    tx["account_id"] = tx["account_id"].fillna("").astype(str)

    rules = load_rules()
    if rules.empty:
        return 0

    changed = 0
    # Work only on uncategorised rows
    mask = tx["category"].str.strip() == ""
    idxs = tx.index[mask]

    for i in idxs:
        row = tx.loc[i]
        for _, r in rules.iterrows():
            if not r["active"]:
                continue
            field = r["match_field"] or "note"
            needle = r["contains"] or ""
            cs = bool(r["case_sensitive"])
            if field not in tx.columns:
                continue
            hay = row.get(field, "")
            if _match_contains(hay, needle, cs):
                tx.at[i, "category"] = r["category"]
                # Normalize kind to ledger's lowercase if provided
                rk = str(r["kind"]).strip()
                if rk:
                    tx.at[i, "kind"] = rk.lower()
                changed += 1
                break  # stop at first matching rule

    if not dry_run and changed > 0:
        tx.to_csv(TX_CSV, index=False, encoding="utf-8-sig")

    return changed

# ----------------- UI page -----------------

def rules_manager():
    st.title("Auto-Categorisation Rules 🧠")
    _ensure_rules_file()
    df = load_rules().copy()

    with st.expander("Add rule"):
        colA, colB = st.columns([2,1])
        with colA:
            contains = st.text_input("If text contains… (e.g. 'TESCO', 'NETFLIX')", key="rule_contains")
        with colB:
            match_field = st.selectbox("Search in", ["note","category","account_id"], index=0, key="rule_field")
        col1, col2, col3, col4 = st.columns([1,1,2,1])
        with col1:
            kind = st.selectbox("Kind", ["","Expense","Income"], index=1, key="rule_kind")
        with col2:
            priority = st.number_input("Priority (lower = first)", min_value=0, value=100, step=10, key="rule_pri")
        with col3:
            category = st.text_input("Set category to", key="rule_category")
        with col4:
            case_sensitive = st.checkbox("Case-sensitive", value=False, key="rule_cs")

        if st.button("Add Rule", key="rule_add_btn"):
            if not contains.strip() or not category.strip():
                st.warning("Please enter both 'contains' and 'category'.")
            else:
                nid = _next_id()
                header = not _exists_nonempty(RULES_CSV)
                pd.DataFrame([{
                    "id": nid,
                    "active": True,
                    "priority": int(priority),
                    "kind": kind,  # keep UI titlecase here; we lowercase only when applying
                    "category": category.strip(),
                    "match_field": match_field,
                    "contains": contains.strip(),
                    "case_sensitive": bool(case_sensitive),
                }], columns=RULE_COLS).to_csv(
                    RULES_CSV, mode="a", index=False, header=header, encoding="utf-8-sig"
                )
                load_rules.clear()
                st.success("Rule added.")

    st.subheader("Rules")
    if df.empty:
        st.caption("No rules yet.")
    else:
        edited = st.data_editor(
            df.reset_index(drop=True),
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.NumberColumn(disabled=True),
                "active": st.column_config.CheckboxColumn(),
                "priority": st.column_config.NumberColumn(),
                "kind": st.column_config.SelectboxColumn(options=["","Expense","Income"]),
                "category": st.column_config.TextColumn(),
                "match_field": st.column_config.SelectboxColumn(options=["note","category","account_id"]),
                "contains": st.column_config.TextColumn(),
                "case_sensitive": st.column_config.CheckboxColumn(),
            },
            key="rules_editor",
        )
        if st.button("Save Changes", key="rules_save_btn"):
            try:
                save_rules(edited)
                st.success("Rules saved.")
            except Exception as e:
                st.error(f"Failed to save rules: {e}")

    st.divider()
    st.subheader("Apply to uncategorised transactions")
    if st.button("⚡ Auto-categorise now"):
        try:
            n = apply_rules_to_transactions(dry_run=False)
            st.success(f"Applied rules to {n} transaction(s).")
        except Exception as e:
            st.error(f"Failed: {e}")