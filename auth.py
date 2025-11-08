# auth.py
import uuid
import streamlit as st
import streamlit_authenticator as stauth
import yaml

def login():
    # load your config as you already do
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    # Standard login form
    authenticator.login(location="main")

    # --- Guest access UI ---
    st.markdown("### Or")
    if st.button("🚪 Continue as Guest"):
        # create a unique guest username so each visitor gets isolated storage
        guest_id = f"guest-{uuid.uuid4().hex[:6]}"
        st.session_state["authentication_status"] = True
        st.session_state["username"] = guest_id
        st.session_state["name"] = "Guest"
        st.session_state["is_guest"] = True
        st.experimental_rerun()

    # Read results from session_state (new authenticator API)
    name = st.session_state.get("name")
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

    return authenticator, name, auth_status, username