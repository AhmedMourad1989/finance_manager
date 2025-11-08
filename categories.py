# categories.py
import os
import pandas as pd
import streamlit as st
from user_data import path_in_user_dir

# FIX: no "data/" here
CATS_CSV = path_in_user_dir("categories.csv")
COLUMNS = ["id", "kind", "name", "active"]  # kind ∈ {"Income","Expense"}

DEFAULT_INCOME = ["Salary", "Locum Work", "Freelance", "Investments", "Gifts"]
DEFAULT_EXPENSE = [
    "Groceries","Food/Eating Out","Transportation","Petrol","Entertainment",
    "Healthcare","Gifts","Family Support","Rent/Mortgage","Utilities",
    "Subscriptions","Council Tax","Insurance","Loan Payments","Credit Card Payment"
]

def _exists_nonempty(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0

@st.cache_data
def load_categories(path: str = CATS_CSV) -> pd.DataFrame:
    if not _exists_nonempty(path):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(path, encoding="utf-8-sig")
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = "" if c != "active" else True
    df["active"] = df["active"].fillna(True).astype(bool)
    df["kind"]   = df["kind"].fillna("").astype(str)
    df["name"]   = df["name"].fillna("").astype(str)
    return df[COLUMNS]

def save_categories(df: pd.DataFrame):
    df = df.reindex(columns=COLUMNS, fill_value="")
    df.to_csv(CATS_CSV, index=False, encoding="utf-8-sig")
    load_categories.clear()

def seed_default_categories():
    """Ensure the per-user categories file exists and has defaults."""
    if not _exists_nonempty(CATS_CSV):
        rows, _id = [], 1
        for n in DEFAULT_INCOME:
            rows.append({"id": _id, "kind": "Income", "name": n, "active": True}); _id += 1
        for n in DEFAULT_EXPENSE:
            rows.append({"id": _id, "kind": "Expense", "name": n, "active": True}); _id += 1
        pd.DataFrame(rows, columns=COLUMNS).to_csv(CATS_CSV, index=False, encoding="utf-8-sig")
        return
    # ensure columns if file exists but odd
    df = load_categories().copy()
    changed = False
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = "" if c != "active" else True
            changed = True
    if changed:
        save_categories(df)

def next_cat_id() -> int:
    df = load_categories()
    if df.empty:
        return 1
    m = pd.to_numeric(df["id"], errors="coerce").max()
    return (0 if pd.isna(m) else int(m)) + 1

def category_select(kind: str, label: str, key: str) -> str:
    """Select active categories; allows inline add."""
    seed_default_categories()  # ensure defaults exist
    df = load_categories()
    options = df[(df["kind"] == kind) & (df["active"])]["name"].dropna().astype(str).tolist()
    options_display = options + ["➕ Add new…"]
    choice = st.selectbox(label, options_display, key=key)
    if choice != "➕ Add new…":
        return choice
    new_name = st.text_input(f"New {kind} category name:", key=f"{key}_new")
    if not new_name:
        return ""
    nid = next_cat_id()
    header_needed = not _exists_nonempty(CATS_CSV)
    pd.DataFrame(
        [{"id": nid, "kind": kind, "name": new_name.strip(), "active": True}],
        columns=COLUMNS
    ).to_csv(CATS_CSV, mode="a", index=False, header=header_needed, encoding="utf-8-sig")
    load_categories.clear()
    st.success(f"Added {kind} category: {new_name.strip()}")
    return new_name.strip()

def manage_categories_page():
    st.title("Manage Categories 🗂️")
    seed_default_categories()
    df = load_categories().copy()

    with st.expander("Add Category"):
        kind = st.selectbox("Kind", ["Income","Expense"], key="cat_add_kind")
        name = st.text_input("Name", key="cat_add_name")
        if st.button("Add", key="cat_add_btn"):
            if name.strip():
                nid = next_cat_id()
                header = not _exists_nonempty(CATS_CSV)
                pd.DataFrame(
                    [{"id": nid, "kind": kind, "name": name.strip(), "active": True}],
                    columns=COLUMNS
                ).to_csv(CATS_CSV, mode="a", index=False, header=header, encoding="utf-8-sig")
                load_categories.clear()
                st.success("Category added.")
            else:
                st.warning("Please enter a name.")

    st.write("### Current Categories")
    if df.empty:
        st.info("No categories yet.")
        return

    edited = st.data_editor(
        df.sort_values(["kind","name"]).reset_index(drop=True),
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "id":   st.column_config.NumberColumn(disabled=True),
            "kind": st.column_config.SelectboxColumn(options=["Income","Expense"]),
            "name": st.column_config.TextColumn(),
            "active": st.column_config.CheckboxColumn(),
        },
        key="cat_editor",
    )
    if st.button("Save Changes", key="cat_save"):
        try:
            save_categories(edited)
            st.success("Categories saved.")
        except Exception as e:
            st.error(f"Failed to save: {e}")