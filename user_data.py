# user_data.py
import os
from pathlib import Path
import re
import streamlit as st

BASE = Path("data")

def _safe_user_segment(s: str) -> str:
    # lower, trim, replace spaces, and strip unsafe path chars
    s = s.strip().lower().replace(" ", "_")
    s = re.sub(r"[^a-z0-9._-]", "-", s)  # keep simple, cross-platform
    return s or "guest"

def user_id() -> str:
    # use login username; fallback to guest
    raw = str(st.session_state.get("username", "guest"))
    return _safe_user_segment(raw)

def user_dir() -> Path:
    p = BASE / user_id()
    p.mkdir(parents=True, exist_ok=True)
    return p

def path_in_user_dir(filename: str) -> str:
    """
    Build a per-user path. If caller mistakenly prefixes 'data/' or gives an
    absolute path, normalize it so we never get data/<user>/data/... or outside.
    """
    # normalize incoming filename
    fname = filename.lstrip("/\\")               # drop leading slashes
    if fname.lower().startswith("data/"):
        fname = fname.split("/", 1)[1]          # strip accidental 'data/' prefix
    # prevent '..' traversal
    fname = fname.replace("..", "__")
    p = user_dir() / fname
    os.makedirs(p.parent, exist_ok=True)
    return str(p)