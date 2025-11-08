# auth.py
import uuid
import streamlit as st
import streamlit_authenticator as stauth
import yaml

def login():
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    # Render username/password form
    authenticator.login(location="main")

    st.markdown("### Or")
    if st.button("🚪 Continue as Guest"):
        guest_id = f"guest-{uuid.uuid4().hex[:6]}"
        st.session_state["authentication_status"] = True
        st.session_state["username"] = guest_id
        st.session_state["name"] = "Guest"
        st.session_state["is_guest"] = True
        st.rerun()  # <-- use modern API

    # Read results from session_state (per streamlit-authenticator >=0.3)
    name = st.session_state.get("name")
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

    return authenticator, name, auth_status, username