import json
import time
import hmac
import hashlib
import requests
import re
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Auto-refresh every 3 seconds
st_autorefresh(interval=3000)
st.set_page_config(layout="wide")

# ---------- CONFIG ----------
API_KEY = st.secrets["DELTA_API_KEY"]
API_SECRET = st.secrets["DELTA_API_SECRET"]
BASE_URL = st.secrets.get("DELTA_BASE_URL", "https://api.india.delta.exchange")
TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# Google Sheets config
SPREADSHEET_ID = "1fb_qf6r01flTn6KKu15dkNr2aW-dhbhFr6kDKLkLqA8"
SHEET_NAME = "Delta Alerts"
RANGE_NAME = f"{SHEET_NAME}!A1:Z1000"

# ---------- Google Sheets Authentication ----------
def get_gsheets_service():
    gcp_json_str = st.secrets["GCP_CREDENTIALS_JSON"]
    gcp_info = json.loads(gcp_json_str)
    scopes = ['https://www.googleapis.com/auth/spreadsheets']
    creds = Credentials.from_service_account_info(gcp_info, scopes=scopes)
    service = build('sheets', 'v4', credentials=creds)
    return service

service = get_gsheets_service()

def ensure_sheet_exists():
    try:
        spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
        sheets = spreadsheet.get('sheets', [])
        sheet_titles = [s.get("properties", {}).get("title") for s in sheets]

        if SHEET_NAME not in sheet_titles:
            batch_update_body = {
                "requests": [{
                    "addSheet": {
                        "properties": {
                            "title": SHEET_NAME,
                            "gridProperties": {"rowCount": 1000, "columnCount": 26}
                        }
                    }
                }]
            }
            service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=batch_update_body).execute()
    except HttpError as e:
        st.error(f"Error ensuring sheet exists: {e}")

def load_alerts_from_sheets():
    try:
        ensure_sheet_exists()
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])

        if not values or len(values) < 2:
            return []

        headers = values[0]
        alerts = []
        for row in values[1:]:
            alert = {headers[i]: row[i] if i < len(row) else '' for i in range(len(headers))}
            try:
                alert['threshold'] = float(alert.get('threshold', 0))
            except ValueError:
                alert['threshold'] = 0
            alerts.append(alert)
        return alerts
    except HttpError as e:
        st.error(f"Error loading alerts: {e}")
        return []

def save_alerts_to_sheets(alerts):
    try:
        ensure_sheet_exists()
        if not alerts:
            # Clear the sheet
            service.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
            return

        headers = ["symbol", "criteria", "condition", "threshold"]
        values = [headers]
        for alert in alerts:
            values.append([
                alert.get("symbol", ""),
                alert.get("criteria", ""),
                alert.get("condition", ""),
                str(alert.get("threshold", ""))
            ])

        body = {"values": values}
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption="RAW",
            body=body
        ).execute()
    except HttpError as e:
        st.error(f"Error saving alerts: {e}")

# ---------- Load alerts at start ----------
if "alerts" not in st.session_state:
    st.session_state.alerts = load_alerts_from_sheets()

if "triggered" not in st.session_state:
    st.session_state.triggered = set()
if "edit_symbol" not in st.session_state:
    st.session_state.edit_symbol = None

# ---------- Your existing code for fetching positions, tickers, processing, alert checking, layout, etc. ----------
# ...
# (Keep your existing code for fetching from API, processing dataframe, UI, etc.)
# ...

# ---------- When you add or delete alerts, save to sheets ----------
def add_alert(alert):
    st.session_state.alerts.append(alert)
    save_alerts_to_sheets(st.session_state.alerts)

def delete_alert(index):
    if 0 <= index < len(st.session_state.alerts):
        st.session_state.alerts.pop(index)
        save_alerts_to_sheets(st.session_state.alerts)

# Replace places in your code where you add or remove alerts:
# For example, in your alert form submit:
# instead of:
# st.session_state.alerts.append({...})
# use:
# add_alert({...})

# Similarly, when deleting alert:
# instead of:
# st.session_state.alerts.pop(index)
# use:
# delete_alert(index)

# ---------- Rest of your Streamlit UI code continues ----------
