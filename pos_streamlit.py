import streamlit as st
import requests
import pandas as pd

# =========================
# 🔐 PASSWORD PROTECTION
# =========================

# Read passcode from Streamlit Secrets (Settings → Secrets)
APP_PASSWORD = st.secrets.get("APP_PASSWORD", None)

if APP_PASSWORD is None:
    st.error("❌ App password not set. Please add `APP_PASSWORD` in Streamlit Secrets.")
    st.stop()

# Session-based authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 Restricted Access")
    password_input = st.text_input("Enter passcode", type="password")
    if st.button("Login"):
        if password_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.experimental_rerun()
        else:
            st.error("❌ Incorrect passcode")
    st.stop()

# =========================
# 📊 MAIN APP CODE
# =========================

st.title("📊 Delta Alerts & Options Tracker")

# Example: Fetch markets from Delta API
try:
    response = requests.get("https://api.delta.exchange/v2/markets")
    data = response.json()
    markets = pd.DataFrame(data.get("result", []))
    st.dataframe(markets)
except Exception as e:
    st.error(f"⚠️ Error fetching data: {e}")

st.success("✅ Logged in successfully and app is running!")
