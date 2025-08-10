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
from datetime import datetime

# Auto-refresh every 3 seconds
st_autorefresh(interval=3000)
st.set_page_config(layout="wide", page_title="Delta Exchange Trading Dashboard")

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
@st.cache_resource
def get_gsheets_service():
    """Cached Google Sheets service to avoid re-initialization"""
    try:
        gcp_json_str = st.secrets["GCP_CREDENTIALS_JSON"]
        gcp_info = json.loads(gcp_json_str)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(gcp_info, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        return service
    except Exception as e:
        st.error(f"Google Sheets connection failed: {e}")
        return None

def ensure_sheet_exists():
    """Ensure the alerts sheet exists"""
    try:
        service = get_gsheets_service()
        if not service:
            return False
            
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
            st.success(f"Created sheet '{SHEET_NAME}'")
        return True
    except HttpError as e:
        st.error(f"Error ensuring sheet exists: {e}")
        return False

def load_alerts_from_sheets():
    """Load alerts from Google Sheets"""
    try:
        service = get_gsheets_service()
        if not service:
            return []
            
        if not ensure_sheet_exists():
            return []
            
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
        values = result.get('values', [])

        if not values or len(values) < 2:
            return []

        headers = values[0]
        alerts = []
        for row in values[1:]:
            if not any(row):  # Skip empty rows
                continue
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
    except Exception as e:
        st.error(f"Unexpected error loading alerts: {e}")
        return []

def save_alerts_to_sheets(alerts):
    """Save alerts to Google Sheets"""
    try:
        service = get_gsheets_service()
        if not service:
            raise Exception("Google Sheets service not available")
            
        if not ensure_sheet_exists():
            raise Exception("Could not create/access sheet")
        
        # Clear the sheet first
        service.spreadsheets().values().clear(
            spreadsheetId=SPREADSHEET_ID, 
            range=RANGE_NAME
        ).execute()
        
        if not alerts:
            return True

        headers = ["symbol", "criteria", "condition", "threshold", "created_at"]
        values = [headers]
        
        for alert in alerts:
            values.append([
                alert.get("symbol", ""),
                alert.get("criteria", ""),
                alert.get("condition", ""),
                str(alert.get("threshold", "")),
                alert.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            ])

        body = {"values": values}
        result = service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=RANGE_NAME,
            valueInputOption="RAW",
            body=body
        ).execute()
        
        return True
        
    except HttpError as e:
        st.error(f"Google Sheets API error: {e}")
        return False
    except Exception as e:
        st.error(f"Error saving alerts: {e}")
        return False

# ---------- Delta Exchange API Functions ----------
def generate_signature(method, endpoint, payload=""):
    """Generate HMAC signature for Delta Exchange API"""
    timestamp = str(int(time.time()))
    signature_data = method + timestamp + endpoint + payload
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature, timestamp

def make_api_request(method, endpoint, payload=None):
    """Make authenticated request to Delta Exchange API"""
    url = BASE_URL + endpoint
    payload_str = json.dumps(payload) if payload else ""
    signature, timestamp = generate_signature(method, endpoint, payload_str)
    
    headers = {
        'api-key': API_KEY,
        'signature': signature,
        'timestamp': timestamp,
        'Content-Type': 'application/json'
    }
    
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, data=payload_str, timeout=10)
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API request failed: {e}")
        return None

def get_positions():
    """Fetch current positions from Delta Exchange"""
    return make_api_request('GET', '/v2/positions')

def get_tickers():
    """Fetch all tickers from Delta Exchange"""
    try:
        response = requests.get(f"{BASE_URL}/v2/tickers", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to fetch tickers: {e}")
        return None

def get_wallet_balances():
    """Fetch wallet balances"""
    return make_api_request('GET', '/v2/wallet/balances')

# ---------- Telegram Functions ----------
def send_telegram_message(message):
    """Send alert message to Telegram"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return False
    
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    params = {
        'chat_id': TG_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        return response.status_code == 200
    except Exception as e:
        st.error(f"Failed to send Telegram message: {e}")
        return False

# ---------- Alert Processing ----------
def check_alerts(df, alerts):
    """Check if any alerts should be triggered"""
    triggered_alerts = []
    
    for alert in alerts:
        symbol = alert['symbol']
        criteria = alert['criteria']
        condition = alert['condition']
        threshold = alert['threshold']
        
        # Find matching row in dataframe
        matching_rows = df[df['symbol'] == symbol]
        if matching_rows.empty:
            continue
            
        current_value = None
        row = matching_rows.iloc[0]
        
        # Get current value based on criteria
        if criteria == 'price':
            current_value = row.get('mark_price', 0)
        elif criteria == 'pnl':
            current_value = row.get('unrealized_pnl', 0)
        elif criteria == 'pnl_percent':
            current_value = row.get('unrealized_pnl_percent', 0)
        
        if current_value is None:
            continue
            
        # Check condition
        alert_triggered = False
        if condition == 'above' and current_value > threshold:
            alert_triggered = True
        elif condition == 'below' and current_value < threshold:
            alert_triggered = True
        elif condition == 'equal' and abs(current_value - threshold) < 0.01:
            alert_triggered = True
            
        if alert_triggered:
            triggered_alerts.append({
                'alert': alert,
                'current_value': current_value,
                'symbol': symbol,
                'criteria': criteria,
                'condition': condition,
                'threshold': threshold
            })
    
    return triggered_alerts

# ---------- Initialize Session State ----------
def initialize_alerts():
    """Initialize alerts from Google Sheets on startup"""
    try:
        alerts = load_alerts_from_sheets()
        st.session_state.alerts = alerts
        return len(alerts)
    except Exception as e:
        st.error(f"Failed to initialize alerts: {e}")
        st.session_state.alerts = []
        return 0

# Initialize session state
if 'alerts' not in st.session_state:
    count = initialize_alerts()

if 'triggered' not in st.session_state:
    st.session_state.triggered = set()

if 'edit_symbol' not in st.session_state:
    st.session_state.edit_symbol = None

# ---------- Helper Functions for Alert Management ----------
def add_alert(alert):
    """Add new alert and save to sheets"""
    alert['created_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.alerts.append(alert)
    
    if save_alerts_to_sheets(st.session_state.alerts):
        st.success(f"✅ Alert saved for {alert['symbol']}")
        return True
    else:
        st.error("❌ Failed to save alert")
        # Remove from session state since save failed
        st.session_state.alerts.pop()
        return False

def delete_alert(index):
    """Delete alert and save to sheets"""
    if 0 <= index < len(st.session_state.alerts):
        deleted_alert = st.session_state.alerts.pop(index)
        
        if save_alerts_to_sheets(st.session_state.alerts):
            st.success(f"🗑️ Deleted alert for {deleted_alert.get('symbol', 'Unknown')}")
            return True
        else:
            st.error("❌ Failed to delete alert")
            # Restore the alert since delete failed
            st.session_state.alerts.insert(index, deleted_alert)
            return False

def sync_alerts():
    """Force sync alerts from Google Sheets"""
    try:
        alerts = load_alerts_from_sheets()
        st.session_state.alerts = alerts
        st.success(f"🔄 Synced {len(alerts)} alerts from Google Sheets")
    except Exception as e:
        st.error(f"Failed to sync alerts: {e}")

# ---------- Main Dashboard UI ----------
st.title("🔥 Delta Exchange Trading Dashboard")

# Top controls
col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

with col1:
    if st.button("🔄 Refresh Data"):
        st.rerun()

with col2:
    if st.button("🔄 Sync Alerts"):
        sync_alerts()

with col3:
    st.metric("Active Alerts", len(st.session_state.alerts))

with col4:
    if st.button("📊 Test Connection"):
        service = get_gsheets_service()
        if service:
            st.success("✅ Google Sheets Connected")
        else:
            st.error("❌ Connection Failed")

st.markdown("---")

# ---------- Fetch and Display Data ----------
# Fetch current positions
with st.spinner("Fetching positions..."):
    positions_data = get_positions()

# Fetch tickers for price data
with st.spinner("Fetching market data..."):
    tickers_data = get_tickers()

# Process positions if available
positions_df = pd.DataFrame()
if positions_data and 'result' in positions_data:
    positions = positions_data['result']
    if positions:
        positions_df = pd.DataFrame(positions)
        
        # Add current prices from tickers
        if tickers_data and 'result' in tickers_data:
            tickers_df = pd.DataFrame(tickers_data['result'])
            if 'symbol' in tickers_df.columns and 'close' in tickers_df.columns:
                price_map = dict(zip(tickers_df['symbol'], tickers_df['close']))
                positions_df['current_price'] = positions_df['symbol'].map(price_map)
        
        # Calculate unrealized PnL percentage
        if 'unrealized_pnl' in positions_df.columns and 'margin' in positions_df.columns:
            positions_df['unrealized_pnl_percent'] = (
                positions_df['unrealized_pnl'] / positions_df['margin'].replace(0, 1) * 100
            )

# Display positions
if not positions_df.empty:
    st.subheader("📈 Current Positions")
    
    # Format the dataframe for display
    display_columns = ['symbol', 'size', 'entry_price', 'mark_price', 'unrealized_pnl']
    if 'unrealized_pnl_percent' in positions_df.columns:
        display_columns.append('unrealized_pnl_percent')
    if 'margin' in positions_df.columns:
        display_columns.append('margin')
    
    display_df = positions_df[display_columns].copy()
    
    # Format numeric columns
    numeric_columns = ['unrealized_pnl', 'unrealized_pnl_percent', 'entry_price', 'mark_price']
    for col in numeric_columns:
        if col in display_df.columns:
            display_df[col] = pd.to_numeric(display_df[col], errors='coerce').round(2)
    
    st.dataframe(display_df, use_container_width=True)
    
    # Check alerts
    triggered_alerts = check_alerts(positions_df, st.session_state.alerts)
    
    # Process triggered alerts
    for triggered in triggered_alerts:
        alert_key = f"{triggered['symbol']}_{triggered['criteria']}_{triggered['condition']}_{triggered['threshold']}"
        
        if alert_key not in st.session_state.triggered:
            st.session_state.triggered.add(alert_key)
            
            # Show alert in UI
            st.error(f"🚨 ALERT TRIGGERED: {triggered['symbol']} {triggered['criteria']} is {triggered['condition']} {triggered['threshold']} (Current: {triggered['current_value']:.2f})")
            
            # Send Telegram notification
            message = f"🚨 <b>DELTA ALERT</b>\n\n" \
                     f"Symbol: {triggered['symbol']}\n" \
                     f"Condition: {triggered['criteria']} {triggered['condition']} {triggered['threshold']}\n" \
                     f"Current Value: {triggered['current_value']:.2f}\n" \
                     f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            if send_telegram_message(message):
                st.success("📱 Telegram notification sent!")
            else:
                st.warning("⚠️ Failed to send Telegram notification")

else:
    st.info("📭 No active positions found")

st.markdown("---")

# ---------- Alert Management Section ----------
st.subheader("⚠️ Alert Management")

# Add new alert form
with st.expander("➕ Add New Alert", expanded=len(st.session_state.alerts) == 0):
    with st.form("add_alert_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            alert_symbol = st.text_input("Symbol", placeholder="BTCUSDT", key="new_alert_symbol")
            alert_criteria = st.selectbox("Criteria", ["price", "pnl", "pnl_percent"], key="new_alert_criteria")
        
        with col2:
            alert_condition = st.selectbox("Condition", ["above", "below", "equal"], key="new_alert_condition")
            alert_threshold = st.number_input("Threshold", value=0.0, step=0.01, key="new_alert_threshold")
        
        if st.form_submit_button("🔔 Add Alert", use_container_width=True):
            if alert_symbol and alert_threshold != 0:
                new_alert = {
                    'symbol': alert_symbol.upper(),
                    'criteria': alert_criteria,
                    'condition': alert_condition,
                    'threshold': float(alert_threshold)
                }
                if add_alert(new_alert):
                    st.rerun()
            else:
                st.error("Please fill in all fields")

# Display existing alerts
if st.session_state.alerts:
    st.subheader("📋 Active Alerts")
    
    for i, alert in enumerate(st.session_state.alerts):
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            
            with col1:
                st.write(f"**{alert['symbol']}** - {alert['criteria']} {alert['condition']} {alert['threshold']}")
                if alert.get('created_at'):
                    st.caption(f"Created: {alert['created_at']}")
            
            with col2:
                if st.button("🗑️", key=f"delete_{i}", help="Delete alert"):
                    if delete_alert(i):
                        st.rerun()
            
            with col3:
                # Show current value if position exists
                if not positions_df.empty:
                    matching_pos = positions_df[positions_df['symbol'] == alert['symbol']]
                    if not matching_pos.empty:
                        current_val = None
                        if alert['criteria'] == 'price':
                            current_val = matching_pos.iloc[0].get('mark_price')
                        elif alert['criteria'] == 'pnl':
                            current_val = matching_pos.iloc[0].get('unrealized_pnl')
                        elif alert['criteria'] == 'pnl_percent':
                            current_val = matching_pos.iloc[0].get('unrealized_pnl_percent')
                        
                        if current_val is not None:
                            st.metric("Current", f"{current_val:.2f}")
            
            st.markdown("---")
else:
    st.info("📝 No alerts configured. Add your first alert above!")

# ---------- Debug Section (can be removed in production) ----------
with st.sidebar:
    st.subheader("🔧 Debug Info")
    st.write(f"Alerts in memory: {len(st.session_state.alerts)}")
    
    if st.button("🔍 Test Google Sheets"):
        service = get_gsheets_service()
        if service:
            try:
                result = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
                st.success(f"✅ Connected to: {result.get('properties', {}).get('title', 'Spreadsheet')}")
            except Exception as e:
                st.error(f"❌ Test failed: {e}")
        else:
            st.error("❌ No service available")
