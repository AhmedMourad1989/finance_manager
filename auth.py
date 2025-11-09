import streamlit as st
import streamlit_authenticator as stauth
import yaml

def login():
    """
    Handles authentication and optional Guest Mode.
    Returns: (authenticator, name, auth_status, username)
    """
    # Load YAML config for streamlit-authenticator
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    authenticator = stauth.Authenticate(
        config["credentials"],
        config["cookie"]["name"],
        config["cookie"]["key"],
        config["cookie"]["expiry_days"],
    )

    # Render login box in main area (new API)
    authenticator.login(location="main")

    # Results are placed in session_state by streamlit-authenticator
    name = st.session_state.get("name")
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

    # Show the Guest button ONLY before login
    if auth_status is None:
        st.write("")
        st.markdown("**Or**")
        if st.button("🧪 Continue as Guest", key="guest_login_btn"):
            st.session_state["authentication_status"] = True
            st.session_state["username"] = "guest"
            st.session_state["name"] = "Guest"
            st.session_state["is_guest"] = True
            st.rerun()

    # If authenticated as a real user, ensure we clear guest flag
    if auth_status is True and username and username != "guest":
        st.session_state.pop("is_guest", None)

    return authenticator, name, auth_status, username