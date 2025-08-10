import os
import time
import hmac
import hashlib
import requests
import re
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

Auto-refresh every 3 seconds
st_autorefresh(interval=3000)
st.set_page_config(layout="wide")

---------- CONFIG ----------
API_KEY = st.secrets["DELTA_API_KEY"]
API_SECRET = st.secrets["DELTA_API_SECRET"]
BASE_URL = st.secrets.get("DELTA_BASE_URL", "https://api.india.delta.exchange")
TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

---------- helpers ----------
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

def detect_underlying(product: dict, fallback_symbol: str):
if not isinstance(product, dict):
product = {}
for key in ("underlying_symbol", "underlying", "base_asset_symbol", "settlement_asset_symbol"):
val = product.get(key)
if isinstance(val, str):
v = val.upper()
if "BTC" in v:
return "BTC"
if "ETH" in v:
return "ETH"
spot = product.get("spot_index") or {}
if isinstance(spot, dict):
s = (spot.get("symbol") or "").upper()
if "BTC" in s:
return "BTC"
if "ETH" in s:
return "ETH"
txt = (fallback_symbol or "").upper()
m = re.search(r"\b(BTC|ETH)\b", txt)
if m:
return m.group(1)
if "BTC" in txt:
return "BTC"
if "ETH" in txt:
return "ETH"
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
# Keep the numeric formatting identical
if num > 0:
return f"{num:.2f}"
elif num < 0:
return f"{num:.2f}"
else:
return f"{num:.2f}"

---------- fetch data ----------
try:
positions_j = api_get("/v2/positions/margined")
positions = positions_j.get("result", []) if isinstance(positions_j, dict) else []
except Exception:
positions = []

try:
tickers_j = api_get("/v2/tickers")
tickers = tickers_j.get("result", []) if isinstance(tickers_j, dict) else []
except Exception:
tickers = []

---------- BTC/ETH index map ----------
index_map = {}
for t in tickers:
sym = (t.get("symbol") or "").upper()
price = t.get("index_price") or t.get("spot_price") or t.get("last_traded_price") or t.get("mark_price")
price = to_float(price)
if not price:
continue
if "BTC" in sym and "USD" in sym and "BTC" not in index_map:
index_map["BTC"] = price
if "ETH" in sym and "USD" in sym and "ETH" not in index_map:
index_map["ETH"] = price

---------- process positions ----------
rows = []
for p in positions:
product = p.get("product") or {}
contract_symbol = product.get("symbol") or p.get("symbol") or ""
size_lots = to_float(p.get("size"))
underlying = detect_underlying(product, contract_symbol)
entry_price = to_float(p.get("entry_price"))
mark_price = to_float(p.get("mark_price"))

text
index_price = p.get("index_price") or product.get("index_price")
if isinstance(index_price, dict):
    index_price = index_price.get("index_price") or index_price.get("price")
if index_price is None and isinstance(product.get("spot_index"), dict):
    index_price = product["spot_index"].get("index_price") or product["spot_index"].get("spot_price")
if index_price is None and underlying and underlying in index_map:
    index_price = index_map[underlying]
index_price = to_float(index_price)

upnl_val = None
size_coins = None
if size_lots is not None and underlying:
    lots_per_coin = {"BTC": 1000.0, "ETH": 100.0}.get(underlying, 1.0)
    size_coins = size_lots / lots_per_coin

if entry_price is not None and mark_price is not None and size_coins is not None:
    if size_coins < 0:
        upnl_val = (entry_price - mark_price) * abs(size_coins)
    else:
        upnl_val = (mark_price - entry_price) * abs(size_coins)

rows.append({
    "Symbol": contract_symbol,
    "Size (lots)": f"{size_lots:.0f}" if size_lots is not None else None,
    "Size (coins)": f"{size_coins:.2f}" if size_coins is not None else None,
    "Entry Price": f"{entry_price:.2f}" if entry_price is not None else None,
    "Index Price": f"{index_price:.2f}" if index_price is not None else None,
    "Mark Price": f"{mark_price:.2f}" if mark_price is not None else None,
    "UPNL (USD)": f"{upnl_val:.2f}" if upnl_val is not None else None,
})
df = pd.DataFrame(rows)

Sort by absolute UPNL (keep exact formatting)
if not df.empty:
df = df.sort_values(
by="UPNL (USD)",
key=lambda x: x.map(lambda v: abs(float(v)) if v not in [None, ""] else -999999),
ascending=False
).reset_index(drop=True)

---------- STATE ----------
if "alerts" not in st.session_state:
st.session_state.alerts = []

if "alert_form_open" not in st.session_state:
st.session_state.alert_form_open = False

if "alert_form_symbol" not in st.session_state:
st.session_state.alert_form_symbol = None

---------- ALERT CHECK ----------
def get_float_from_cell(v):
try:
return float(v)
except:
return None

triggered_messages = []
for alert in list(st.session_state.alerts):
row = df[df["Symbol"] == alert["symbol"]]
if row.empty:
continue
val_str = row.iloc.get(alert["criteria"])
val = get_float_from_cell(val_str)
if val is None:
continue
if alert["condition"] == ">=":
cond = val >= alert["threshold"]
else:
cond = val <= alert["threshold"]
if cond:
msg = f"ALERT: {alert['symbol']} {alert['criteria']} {alert['condition']} {alert['threshold']}"
triggered_messages.append(msg)

send telegram after evaluation
for m in triggered_messages:
send_telegram_message(m)

---------- CSS ----------
st.markdown("""

<style> /* Keep UI unchanged; only ensure popup appears as overlay */ .alert-modal { position: fixed; top: 0; left: 0; right:0; bottom:0; background: rgba(0,0,0,0.45); z-index: 9999; display: flex; align-items: center; justify-content: center; } .alert-card { background: #111827; border: 1px solid #374151; border-radius: 10px; padding: 16px; width: 360px; color: #e5e7eb; box-shadow: 0 10px 30px rgba(0,0,0,0.5); } .alert-card h4 { margin: 0 0 10px 0; } .alert-card .row { margin-bottom: 10px; } .alert-card .row label { display: block; font-size: 12px; color: #9ca3af; margin-bottom: 4px; } .alert-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; } </style>
""", unsafe_allow_html=True)

---------- LAYOUT ----------
left_col, right_col = st.columns([4,]

--- LEFT: TABLE ---
if not df.empty:
# Build HTML table to preserve your UI
cols = list(df.columns)
table_html = '<div style="overflow-x:auto;"><table class="table" style="width:100%; border-collapse:collapse;">'
# Header
table_html += "<thead><tr>"
for col in cols:
table_html += f"<th style='text-align:left; padding:8px; border-bottom:1px solid #333;'>{col.upper()}</th>"
table_html += "<th style='text-align:left; padding:8px; border-bottom:1px solid #333;'>ALERT</th>"
table_html += "</tr></thead>"

text
# Body rows
table_html += "<tbody>"
for idx, row in df.iterrows():
    table_html += "<tr>"
    for col in cols:
        val = row[col]
        if col == "UPNL (USD)":
            val = badge_upnl(val)
        table_html += f"<td style='padding:8px; border-bottom:1px solid #222;'>{val if val is not None else ''}</td>"

    # ALERT column: render a + button using a unique Streamlit button per row (outside HTML string)
    table_html += f"<td style='padding:8px; border-bottom:1px solid #222;'>{{BTN_PLACEHOLDER_{idx}}}</td>"
    table_html += "</tr>"
table_html += "</tbody></table></div>"

# Render the table row-by-row so we can inject Streamlit buttons
# Split HTML before/after each placeholder
# Prepare parts
rendered = table_html
parts = []
placeholders = []
for i in range(len(df)):
    token = f"{{BTN_PLACEHOLDER_{i}}}"
    if token in rendered:
        before, after = rendered.split(token, 1)
        parts.append(before)
        placeholders.append(i)
        rendered = after
parts.append(rendered)

# Output with interleaved buttons
for i, part in enumerate(parts):
    st.markdown(part, unsafe_allow_html=True)
    if i < len(placeholders):
        r_idx = placeholders[i]
        symbol_here = df.iloc[r_idx]["Symbol"]

        # The actual + button per row
        if st.button("+", key=f"add_alert_{r_idx}"):
            st.session_state.alert_form_open = True
            st.session_state.alert_form_symbol = symbol_here
            st.rerun()
else:
with left_col:
st.write("No positions found.")

--- RIGHT: SIMPLE LIST OF ALERTS (unchanged UI philosophy) ---
with right_col:
st.subheader("Alerts")
if st.session_state.alerts:
for a_i, a in enumerate(st.session_state.alerts):
st.write(f"{a['symbol']} - {a['criteria']} {a['condition']} {a['threshold']}")
else:
st.write("No alerts yet.")

---------- POPUP FORM (appears when + is clicked) ----------
def popup():
st.markdown('<div class="alert-modal"><div class="alert-card">', unsafe_allow_html=True)
st.markdown("<h4>Create Alert</h4>", unsafe_allow_html=True)

text
symbol = st.session_state.alert_form_symbol or ""
criteria_default = "Mark Price"
criteria_options = ["Mark Price", "Index Price", "Entry Price", "UPNL (USD)", "Size (coins)", "Size (lots)"]

# Inline form controls with Streamlit widgets
# Use unique keys so reruns keep values
criteria = st.selectbox("Criteria", criteria_options, index=criteria_options.index(criteria_default) if criteria_default in criteria_options else 0, key="alert_criteria_select")
condition = st.selectbox("Condition", [">=", "<="], key="alert_condition_select")
threshold = st.text_input("Threshold (number)", key="alert_threshold_input")

st.markdown('<div class="alert-actions">', unsafe_allow_html=True)
col1, col2 = st.columns()[1]
with col1:
    if st.button("Cancel", key="alert_cancel_btn"):
        st.session_state.alert_form_open = False
        st.session_state.alert_form_symbol = None
        st.rerun()
with col2:
    if st.button("Create", key="alert_create_btn"):
        try:
            th = float(threshold)
        except:
            st.warning("Enter a valid numeric threshold.")
            st.stop()

        # Save alert
        st.session_state.alerts.append({
            "symbol": symbol,
            "criteria": criteria,
            "condition": condition,
            "threshold": th,
        })
        st.session_state.alert_form_open = False
        st.session_state.alert_form_symbol = None
        st.success("Alert created.")
        st.rerun()
st.markdown('</div>', unsafe_allow_html=True)  # actions
st.markdown('</div></div>', unsafe_allow_html=True)  # card+modal
