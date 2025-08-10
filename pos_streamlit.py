import os
import time
import hmac
import hashlib
import requests
import re
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

# Auto-refresh every 3 seconds
st_autorefresh(interval=3000)

# ---------- CONFIG ----------
API_KEY = st.secrets["DELTA_API_KEY"]
API_SECRET = st.secrets["DELTA_API_SECRET"]
BASE_URL = st.secrets.get("DELTA_BASE_URL", "https://api.india.delta.exchange")
TG_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# ---------- helpers ----------
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
    if num > 0:
        return f"<span style='padding:4px 8px;border-radius:6px;background:#b6f7b0;color:#065f08;font-weight:bold;'>{num:.2f}</span>"
    elif num < 0:
        return f"<span style='padding:4px 8px;border-radius:6px;background:#f7b0b0;color:#6b0000;font-weight:bold;'>{num:.2f}</span>"
    else:
        return f"<span style='padding:4px 8px;border-radius:6px;background:#ddd;color:#000;font-weight:bold;'>{num:.2f}</span>"

# ---------- fetch data ----------
positions_j = api_get("/v2/positions/margined")
positions = positions_j.get("result", []) if isinstance(positions_j, dict) else []

tickers_j = api_get("/v2/tickers")
tickers = tickers_j.get("result", []) if isinstance(tickers_j, dict) else []

# ---------- BTC/ETH index map ----------
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

# ---------- process positions ----------
rows = []
for p in positions:
    product = p.get("product") or {}
    contract_symbol = product.get("symbol") or p.get("symbol") or ""
    size_lots = to_float(p.get("size"))
    underlying = detect_underlying(product, contract_symbol)

    entry_price = to_float(p.get("entry_price"))
    mark_price = to_float(p.get("mark_price"))

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
        "UPNL (USD)": f"{upnl_val:.2f}" if upnl_val is not None else None
    })

df = pd.DataFrame(rows)

# Sort by absolute UPNL
def safe_abs_upnl(val):
    try:
        return abs(float(val))
    except:
        return -999999
df = df.sort_values(by="UPNL (USD)", key=lambda x: x.map(safe_abs_upnl), ascending=False).reset_index(drop=True)

# ---------- STATE ----------
if "alerts" not in st.session_state:
    st.session_state.alerts = []
if "triggered" not in st.session_state:
    st.session_state.triggered = set()
if "edit_symbol" not in st.session_state:
    st.session_state.edit_symbol = None

# ---------- ALERT CHECK ----------
triggered_alerts = []
for alert in st.session_state.alerts:
    row = df[df["Symbol"] == alert["symbol"]]
    if row.empty:
        continue
    val_str = row.iloc[0].get(alert["criteria"])
    try:
        val = float(val_str)
    except:
        continue
    cond = (val >= alert["threshold"]) if alert["condition"] == ">=" else (val <= alert["threshold"])
    alert_key = f"{alert['symbol']}-{alert['criteria']}-{alert['threshold']}-{alert['condition']}"
    if cond and alert_key not in st.session_state.triggered:
        msg = f"ALERT: {alert['symbol']} {alert['criteria']} {alert['condition']} {alert['threshold']} (current: {val:.2f})"
        send_telegram_message(msg)
        st.session_state.triggered.add(alert_key)
        triggered_alerts.append(msg)

if triggered_alerts:
    st.error("Triggered Alerts:\n" + "\n".join(triggered_alerts))

# ---------- STYLING ----------
st.markdown("""
<style>
.table-cell {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-family: monospace;
    padding: 4px;
}
.table-header {
    color: #888;
    font-weight: bold;
    font-size: 0.9rem;
}
</style>
""", unsafe_allow_html=True)

# ---------- LAYOUT ----------
st.title("📊 Delta Exchange Positions")

left_col, right_col = st.columns([3, 1])
col_widths = [2, 1, 1, 1, 1, 1, 1, 0.5]

# --- LEFT: TABLE ---
if not df.empty:
    header_cols = left_col.columns(col_widths)
    for i, cname in enumerate(df.columns):
        header_cols[i].markdown(f"<div class='table-header'>{cname.upper()}</div>", unsafe_allow_html=True)
    header_cols[-1].markdown("<div class='table-header'>ALERT</div>", unsafe_allow_html=True)

    for idx, row in df.iterrows():
        row_cols = left_col.columns(col_widths)
        for i, cname in enumerate(df.columns):
            if cname == "UPNL (USD)":
                row_cols[i].markdown(badge_upnl(row[cname]), unsafe_allow_html=True)
            else:
                row_cols[i].markdown(f"<div class='table-cell'>{row[cname]}</div>", unsafe_allow_html=True)
        if row_cols[-1].button("➕", key=f"add_alert_{idx}"):
            st.session_state.edit_symbol = row["Symbol"]

# --- RIGHT: ALERT EDITOR ---
if st.session_state.edit_symbol:
    row = df[df["Symbol"] == st.session_state.edit_symbol].iloc[0]
    try:
        upnl_val = float(row["UPNL (USD)"])
        if upnl_val > 0:
            header_bg = "#b6f7b0"
        elif upnl_val < 0:
            header_bg = "#f7b0b0"
        else:
            header_bg = "#ddd"
    except:
        header_bg = "#ddd"

    right_col.markdown(f"<div style='background:{header_bg};padding:10px;border-radius:8px'><b>Create Alert</b></div>", unsafe_allow_html=True)
    right_col.markdown(f"**Symbol:** {st.session_state.edit_symbol}")
    right_col.markdown(f"**UPNL (USD):** {badge_upnl(row['UPNL (USD)'])}", unsafe_allow_html=True)
    right_col.markdown(f"**Mark Price:** {row['Mark Price']}")  # plain text

    with right_col.form("alert_form"):
        criteria_choice = st.selectbox("Criteria", ["UPNL (USD)", "Mark Price"])
        condition_choice = st.selectbox("Condition", [">=", "<="])
        threshold_value = st.number_input("Threshold", format="%.2f")
        submitted = st.form_submit_button("Save Alert")
        if submitted:
            st.session_state.alerts.append({
                "symbol": st.session_state.edit_symbol,
                "criteria": criteria_choice,
                "condition": condition_choice,
                "threshold": threshold_value
            })
            st.session_state.edit_symbol = None
            st.success("Alert added!")
else:
    right_col.info("Select a contract to set an alert")

# --- ACTIVE ALERTS ---
st.subheader("Active Alerts")
if st.session_state.alerts:
    for i, alert in enumerate(list(st.session_state.alerts)):
        cols = st.columns([5, 1])
        with cols[0]:
            st.write(alert)
        with cols[1]:
            if st.button("❌", key=f"remove_alert_{i}"):
                st.session_state.alerts.pop(i)
                st.experimental_rerun()
else:
    st.write("No active alerts.")
