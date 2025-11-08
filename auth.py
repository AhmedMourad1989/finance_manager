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

    # NEW API: no title string; pass location as a keyword
    authenticator.login(location="main")

    # Read results from session_state (new pattern)
    name = st.session_state.get("name")
    auth_status = st.session_state.get("authentication_status")
    username = st.session_state.get("username")

    return authenticator, name, auth_status, username