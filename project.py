import csv
import os
from datetime import date
import streamlit as st
from auth import login
from user_data import user_id, user_dir, path_in_user_dir


# ---------- page config ----------
st.set_page_config(
    page_title="Finance Manager",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- small utilities ----------
def home():
    st.title("Welcome to Finance Manager 💼")
    st.divider()
    st.header("Get Started 🚀")
    st.caption("Use the sidebar to navigate through the application.")
    st.info("💡 Tip: Start by adding your bank accounts, income and fixed bills first.")
    st.divider()
    st.markdown(":blue[Developed by Ahmed Mourad © 2025]")

def ensure_data_dir():
    # FIX: don't precreate guest paths; just the base
    os.makedirs("data", exist_ok=True)

def csv_not_exists_create(path, headers):
    """Create CSV with headers if missing or 0-byte."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

# ---------- app bootstrap ----------
def bootstrap_files():
    ensure_data_dir()
    os.makedirs(user_dir(), exist_ok=True)  # ensure per-user dir

    csv_not_exists_create(path_in_user_dir("accounts.csv"),
        ["id","account_name","account_type","account_id","balance","currency","limit","apr","note"])

    # FIX: add 'category' column
    csv_not_exists_create(path_in_user_dir("transactions.csv"),
        ["id","date","kind","amount","currency","account_id","category","note"])

    csv_not_exists_create(path_in_user_dir("recurring_expenses.csv"),
        ["id","expense_type","amount","currency","frequency","next_due_date","account_id","note"])

    csv_not_exists_create(path_in_user_dir("recurring_incomes.csv"),
        ["id","income_type","amount","currency","frequency","next_due_date","account_id","note"])

    csv_not_exists_create(path_in_user_dir("debts.csv"),
        ["id","lender","debt_type","account_id","original_amount","current_balance","currency","apr","min_payment","payment_day","note"])

    csv_not_exists_create(path_in_user_dir("credit_card_statements.csv"),
        ["id","card_account_id","period_start","period_end","statement_balance","apr_at_cycle","min_due","due_date","paid_amount","paid_date","carried_balance","note"])

    csv_not_exists_create(path_in_user_dir("categories.csv"),
        ["id","kind","name","active"])

    csv_not_exists_create(path_in_user_dir("rules.csv"),
        ["id","active","priority","kind","category","match_field","contains","case_sensitive"])

    csv_not_exists_create(path_in_user_dir("budgets.csv"),
        ["id","month","category","amount","currency","active","note"])

def run_processors_safely():
    """Run recurring processors without breaking the UI."""
    try:
        from finance import process_recurring_expenses, process_recurring_incomes
        from categories import seed_default_categories
        seed_default_categories()
        process_recurring_expenses()
        process_recurring_incomes()
    except Exception as e:
        st.sidebar.warning(f"Auto-processing skipped: {e}")

# ---------- main ----------
def main():
    # --- Login first (FIX: avoid creating guest files) ---
    authenticator, name, auth_status, username = login()
    if auth_status is False:
        st.error("Invalid username or password.")
        return
    elif auth_status is None:
        st.info("Please log in.")
        return

    # store in session for path helpers
    st.session_state["username"] = username
    st.session_state["full_name"] = name


    import datetime

    today = datetime.date.today()
    st.markdown(f"**{st.session_state.get('name','')}** — {today:%A %d %B %Y}")
    st.write("")

    # now we can safely create per-user files and run processors
    bootstrap_files()
    run_processors_safely()

    if "page" not in st.session_state:
        st.session_state.page = "Welcome"

    # -------- sidebar --------
    st.sidebar.title("Finance Manager 💼")
    with st.sidebar:
        st.write(f"👋 {st.session_state.get('full_name', st.session_state['username'])}")
        authenticator.logout(location="sidebar", key="logout_button")

    page = st.sidebar.radio(
        "Navigate",
        [
            "🏠 Home",
            "📊 Dashboard",
            "🏦 Add Account",
            "💰 Add Income",
            "🧾 Add Expense",
            "🔁 Transfers",
            "📜 Transactions",
            "🔁 Recurring Expenses",
            "📉 Debts",
            "💳 Pay Credit Card",
            "📅 Budgets",
            "🧠 Rules",
            "🔄 Imports/Exports",
            "⚙️ Settings",
        ],
        index=0,
        key="nav",
    )

    # -------- lazy imports per selection --------
    if page == "🏠 Home":
        home()
    elif page == "📊 Dashboard":
        from dashboard import dashboard
        dashboard()
    elif page == "🏦 Add Account":
        from finance import add_account
        add_account()
    elif page == "💰 Add Income":
        from finance import add_income
        add_income()
    elif page == "🧾 Add Expense":
        from finance import add_expense
        add_expense()
    elif page == "🔁 Transfers":
        from finance import transfer_funds
        transfer_funds()
    elif page == "📜 Transactions":
        from transactions import transactions_view
        transactions_view()
    elif page == "🔁 Recurring Expenses":
        from finance import recurring_expenses
        recurring_expenses()
    elif page == "📉 Debts":
        from debts import get_debts
        get_debts()
    elif page == "💳 Pay Credit Card":
        from finance import pay_credit_card
        pay_credit_card()
    elif page == "📅 Budgets":
        from budgets import budgets_page
        budgets_page()
    elif page == "🧠 Rules":
        from rules import rules_manager
        rules_manager()
    elif page == "🔄 Imports/Exports":
        from data_store import imports_exports
        imports_exports()
    elif page == "⚙️ Settings":
        from settings import settings
        settings()

if __name__ == "__main__":
    main()