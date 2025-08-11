import os
import time
import hmac
import hashlib
import requests
import re
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import gspread
import json
from datetime import datetime

# =======================
# 🔐 AUTHENTICATION BLOCK
# =======================

OWNER_EMAIL = "harv@duck.com"  # Your Streamlit Cloud account email
APP_PASSWORD = st.secrets.get("APP_PASSWORD", "changeme")  # Stored securely in secrets

# Try to get logged-in user info (Streamlit Cloud only)
user_email = None
try:
    if hasattr(st, "experimental_user"):
        user_email = st.experimental_user.get("email")
except Exception:
    pass

def password_gate():
    """Show password prompt and stop app if incorrect."""
    def password_entered():
        if st.session_state["password"] == APP_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # remove from memory
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.stop()
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        st.stop()

# If user is not owner, ask for password
if user_email != OWNER_EMAIL:
    password_gate()

# =======================
# Rest of your app starts here
# =======================

# Auto-refresh every 15 seconds
st_autorefresh(interval=15000)
st.set_page_config(layout="wide")

# ---------- CONFIG ----------
API_KEY = st.secrets["DELTA_API_KEY"]
API_SECRET = st.secrets["DELTA_API_SECRET"]
BASE_URL = st.secrets.get("DELTA_BASE_URL", "https://api.india.delta.exchange")
TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# Google Sheets Config
GOOGLE_SHEET_ID = st.secrets["GOOGLE_SHEET_ID"]
GOOGLE_CREDENTIALS = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])

# ---------- GOOGLE SHEETS CONNECTION ----------
gc = gspread.service_account_from_dict(GOOGLE_CREDENTIALS)
sh = gc.open_by_key(GOOGLE_SHEET_ID)
worksheet = sh.sheet1

# ---------- DELTA API FUNCTIONS ----------
def generate_signature(api_secret, verb, endpoint, data, timestamp):
    payload = f"{timestamp}{verb}{endpoint}{data}"
    return hmac.new(api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

def fetch_positions():
    endpoints = [
        "/v2/positions/margined",
        "/v2/positions"
    ]
    for endpoint in endpoints:
        url = BASE_URL + endpoint
        timestamp = str(int(time.time() * 1000))
        signature = generate_signature(API_SECRET, "GET", endpoint, "", timestamp)
        headers = {
            "api-key": API_KEY,
            "timestamp": timestamp,
            "signature": signature
        }
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()["result"]
        except Exception as e:
            st.error(f"Error with endpoint {url}: {e}")
    return []

def send_telegram_message(message):
    if TG_BOT_TOKEN and TG_CHAT_ID:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TG_CHAT_ID, "text": message}
        try:
            requests.post(url, data=data)
        except Exception as e:
            st.error(f"Telegram send error: {e}")

# ---------- MAIN APP ----------
st.title("📊 Delta Exchange Positions Monitor")

positions = fetch_positions()

if not positions:
    st.warning("No positions found or API error.")
else:
    df = pd.DataFrame(positions)
    if not df.empty:
        st.dataframe(df)
        try:
            worksheet.clear()
            worksheet.update([df.columns.values.tolist()] + df.values.tolist())
            st.success("✅ Data updated to Google Sheets.")
        except Exception as e:
            st.error(f"Google Sheets update error: {e}")

# Example alert sending
if positions:
    send_telegram_message("📢 Positions updated on Delta Exchange monitor.")
