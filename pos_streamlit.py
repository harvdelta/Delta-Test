import time
import hmac
import hashlib
import requests
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import json

# Google Sheets imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ----------------- CONFIG -----------------

# Load secrets
API_KEY = st.secrets["DELTA_API_KEY"]
API_SECRET = st.secrets["DELTA_API_SECRET"]
BASE_URL = st.secrets.get("DELTA_BASE_URL", "https://api.india.delta.exchange")
TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# Google Sheets config
GCP_SA_INFO = st.secrets["gcp_service_account"]
# Put your Google Sheet ID here (you must share the sheet with the service account email)
GOOGLE_SHEET_ID = "1fb_qf6r01flTn6KKu15dkNr2aW-dhbhFr6kDKLkLqA8"

# ----------------- HELPERS -----------------

def sign_request(method: str, path: str, payload: str, timestamp: str) -> str:
    sig_data = method + timestamp + path + payload
    return hmac.new(API_SECRET.encode(), sig_data.encode(), hashlib.sha256).hexdigest()

def api_get(path: str, timeout=15):
    timestamp = str(int(time.time()))
    method = "GET"
    payload = ""
    signature = sign_request(method, path, payload, timestamp)
    headers = {
        "Accept": "application/json",
        "api-key": API_KEY,
        "signature": signature,
        "timestamp": timestamp,
    }
    url = BASE_URL.rstrip("/") + path
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def send_telegram_message(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text}
    try:
        requests.post(url, data=payload, timeout=5)
    except:
        pass

def badge_upnl(val):
    try:
        num = float(val)
    except:
        return val
    if num > 0:
        return f"<span style='padding:4px 8px;border-radius:6px;background:#4CAF50;color:white;font-weight:bold;'>{num:.2f}</span>"
    elif num < 0:
        return f"<span style='padding:4px 8px;border-radius:6px;background:#F44336;color:white;font-weight:bold;'>{num:.2f}</span>"
    else:
        return f"<span style='padding:4px 8px;border-radius:6px;background:#999;color:white;font-weight:bold;'>{num:.2f}</span>"

# ----------------- GOOGLE SHEETS -----------------

def get_sheets_service():
    creds = Credentials.from_service_account_info(GCP_SA_INFO, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    service = build('sheets', 'v4', credentials=creds)
    return service.spreadsheets()

def load_alerts():
    try:
        sheets = get_sheets_service()
        result = sheets.values().get(spreadsheetId=GOOGLE_SHEET_ID, range="alerts!A2:D").execute()
        values = result.get('values', [])
        alerts = []
        for row in values:
            if len(row) < 4:
                continue
            alerts.append({
                "symbol": row[0],
                "criteria": row[1],
                "condition": row[2],
                "threshold": float(row[3])
            })
        return alerts
    except Exception as e:
        st.error(f"Error loading alerts from Google Sheets: {e}")
        return []

def save_alerts(alerts):
    try:
        sheets = get_sheets_service()
        values = [[a["symbol"], a["criteria"], a["condition"], a["threshold"]] for a in alerts]
        # Clear sheet first
        sheets.values().clear(spreadsheetId=GOOGLE_SHEET_ID, range="alerts!A2:D").execute()
        if values:
            sheets.values().update(
                spreadsheetId=GOOGLE_SHEET_ID,
                range="alerts!A2:D",
                valueInputOption="USER_ENTERED",
                body={"values": values}
            ).execute()
    except Exception as e:
        st.error(f"Error saving alerts to Google Sheets: {e}")

# ----------------- MAIN -----------------

st.set_page_config(layout="wide")
st_autorefresh(interval=3000, key="auto_refresh")  # refresh every 3 seconds

# Load alerts from Google Sheets or initialize empty
if "alerts" not in st.session_state:
    st.session_state.alerts = load_alerts()

# Fetch positions data
try:
    positions_j = api_get("/v2/positions/margined")
    positions = positions_j.get("result", []) if isinstance(positions_j, dict) else []
except Exception as e:
    st.error(f"Error fetching positions: {e}")
    positions = []

# Process positions into DataFrame
rows = []
for p in positions:
    product = p.get("product") or {}
    contract_symbol = product.get("symbol") or p.get("symbol") or ""
    size_lots = to_float(p.get("size"))
    entry_price = to_float(p.get("entry_price"))
    mark_price = to_float(p.get("mark_price"))

    upnl_val = None
    if size_lots is not None and entry_price is not None and mark_price is not None:
        upnl_val = (mark_price - entry_price) * abs(size_lots)

    rows.append({
        "Symbol": contract_symbol,
        "Size (lots)": f"{size_lots:.0f}" if size_lots is not None else None,
        "Entry Price": f"{entry_price:.2f}" if entry_price is not None else None,
        "Mark Price": f"{mark_price:.2f}" if mark_price is not None else None,
        "UPNL (USD)": f"{upnl_val:.2f}" if upnl_val is not None else None
    })

df = pd.DataFrame(rows)
df = df.sort_values(by="UPNL (USD)", key=lambda x: x.map(lambda v: abs(float(v)) if v else -999999), ascending=False).reset_index(drop=True)

# Alert checking & removing triggered alerts
triggered_indices = []
for i, alert in enumerate(st.session_state.alerts):
    row = df[df["Symbol"] == alert["symbol"]]
    if row.empty:
        continue
    val_str = row.iloc[0].get(alert["criteria"])
    try:
        val = float(val_str)
    except:
        continue
    cond = (val >= alert["threshold"]) if alert["condition"] == ">=" else (val <= alert["threshold"])
    if cond:
        send_telegram_message(f"ALERT: {alert['symbol']} {alert['criteria']} {alert['condition']} {alert['threshold']}")
        triggered_indices.append(i)

# Remove triggered alerts
if triggered_indices:
    st.session_state.alerts = [a for i, a in enumerate(st.session_state.alerts) if i not in triggered_indices]
    save_alerts(st.session_state.alerts)

# UI layout
left_col, right_col = st.columns([4, 1])

# Left: positions table with alert button
if not df.empty:
    table_html = "<table style='width:100%;border-collapse:collapse'>"
    table_html += "<thead><tr>"
    for col in df.columns:
        table_html += f"<th style='padding:8px;border-bottom:1px solid #ccc;text-align:center'>{col}</th>"
    table_html += "<th>Alert</th></tr></thead><tbody>"
    for idx, row in df.iterrows():
        table_html += "<tr>"
        for col in df.columns:
            val = row[col]
            if col == "Symbol":
                table_html += f"<td style='text-align:left;font-weight:bold'>{val}</td>"
            elif col == "UPNL (USD)":
                badge = badge_upnl(val)
                table_html += f"<td style='text-align:center'>{badge}</td>"
            else:
                table_html += f"<td style='text-align:center'>{val}</td>"
        # Alert + button link
        symbol_encoded = row['Symbol'].replace(' ', '%20').replace('&', '%26')
        table_html += f"<td style='text-align:center'><a href='?edit_symbol={symbol_encoded}' style='text-decoration:none;font-weight:bold;font-size:20px'>+</a></td>"
        table_html += "</tr>"
    table_html += "</tbody></table>"
    left_col.markdown(table_html, unsafe_allow_html=True)
else:
    left_col.info("No positions data available")

# Right: alert editor
query_params = st.experimental_get_query_params()
if "edit_symbol" in query_params:
    edit_symbol = query_params["edit_symbol"][0]
    st.experimental_set_query_params()  # clear query params
else:
    edit_symbol = None

if edit_symbol:
    row = df[df["Symbol"] == edit_symbol]
    if not row.empty:
        row = row.iloc[0]
        upnl_val = float(row["UPNL (USD)"]) if row["UPNL (USD)"] else 0
        header_bg = "#4CAF50" if upnl_val > 0 else "#F44336" if upnl_val < 0 else "#999"
        right_col.markdown(f"<div style='background:{header_bg};padding:10px;border-radius:8px'><b>Create Alert</b></div>", unsafe_allow_html=True)
        right_col.markdown(f"**Symbol:** {edit_symbol}")
        right_col.markdown(f"**UPNL (USD):** {badge_upnl(row['UPNL (USD)'])}", unsafe_allow_html=True)
        right_col.markdown(f"**Mark Price:** {row['Mark Price']}")

        with right_col.form("alert_form"):
            criteria_choice = st.selectbox("Criteria", ["UPNL (USD)", "Mark Price"])
            condition_choice = st.selectbox("Condition", [">=", "<="])
            threshold_value = st.number_input("Threshold", format="%.2f")
            col1, col2 = st.columns(2)
            with col1:
                if st.form_submit_button("Save Alert"):
                    st.session_state.alerts.append({
                        "symbol": edit_symbol,
                        "criteria": criteria_choice,
                        "condition": condition_choice,
                        "threshold": threshold_value
                    })
                    save_alerts(st.session_state.alerts)
                    st.experimental_set_query_params()
                    st.experimental_rerun()
            with col2:
                if st.form_submit_button("Cancel"):
                    st.experimental_set_query_params()
                    st.experimental_rerun()
    else:
        right_col.error("Symbol not found")
else:
    right_col.info("Click + button to create alert")

# Active alerts table
st.subheader("Active Alerts")
if st.session_state.alerts:
    alerts_html = "<table style='width:100%;border-collapse:collapse'>"
    alerts_html += "<thead><tr><th>Symbol</th><th>Criteria</th><th>Condition</th><th>Threshold</th><th>Delete</th></tr></thead><tbody>"
    for i, alert in enumerate(st.session_state.alerts):
        alerts_html += "<tr>"
        alerts_html += f"<td style='font-weight:bold'>{alert['symbol']}</td>"
        alerts_html += f"<td>{alert['criteria']}</td>"
        alerts_html += f"<td>{alert['condition']}</td>"
        alerts_html += f"<td>{alert['threshold']}</td>"
        alerts_html += f"<td><button onclick='window.location.href=\"?delete_alert={i}\"' style='color:red;cursor:pointer;border:none;background:none;font-size:18px;'>❌</button></td>"
        alerts_html += "</tr>"
    alerts_html += "</tbody></table>"
    st.markdown(alerts_html, unsafe_allow_html=True)
else:
    st.write("No active alerts.")

# Delete alert logic
if "delete_alert" in query_params:
    try:
        del_i = int(query_params["delete_alert"][0])
        if 0 <= del_i < len(st.session_state.alerts):
            st.session_state.alerts.pop(del_i)
            save_alerts(st.session_state.alerts)
        st.experimental_set_query_params()
        st.experimental_rerun()
    except:
        st.experimental_set_query_params()
        st.experimental_rerun()
