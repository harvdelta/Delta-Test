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
# Load secrets from Streamlit's Secrets Manager
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

# ---------- lots per coin mapping ----------
DEFAULT_LOTS = {"BTC": 1000.0, "ETH": 100.0}

# ---------- process positions ----------
rows = []
for p in positions:
    product = p.get("product") or {}
    contract_symbol = product.get("symbol") or p.get("symbol") or ""
    size_lots = to_float(p.get("size"))
    underlying = detect_underlying(product, contract_symbol)

    lots_per_coin = DEFAULT_LOTS.get(underlying, 1.0)
    size_coins = size_lots / lots_per_coin if size_lots is not None else None

    entry_price = to_float(p.get("entry_price"))
    mark_price = to_float(p.get("mark_price"))

    # Index price fallback
    index_price = p.get("index_price") or product.get("index_price")
    if isinstance(index_price, dict):
        index_price = index_price.get("index_price") or index_price.get("price")
    if index_price is None and isinstance(product.get("spot_index"), dict):
        index_price = product["spot_index"].get("index_price") or product["spot_index"].get("spot_price")
    if index_price is None and underlying and underlying in index_map:
        index_price = index_map[underlying]
    index_price = to_float(index_price)

    # UPNL calculation
    upnl_val = None
    if entry_price is not None and mark_price is not None and size_coins is not None:
        if size_coins < 0:
            upnl_val = (entry_price - mark_price) * abs(size_coins)
        else:
            upnl_val = (mark_price - entry_price) * abs(size_coins)

    notional = abs(size_coins) * index_price if index_price is not None and size_coins is not None else None

    rows.append({
        "Symbol": contract_symbol,
        "Size (lots)": f"{size_lots:.0f}" if size_lots is not None else None,
        "Size (coins)": f"{size_coins:.2f}" if size_coins is not None else None,
        "Notional (USD)": f"{notional:.2f}" if notional is not None else None,
        "Entry Price": f"{entry_price:.2f}" if entry_price is not None else None,
        "Index Price": f"{index_price:.2f}" if index_price is not None else None,
        "Mark Price": f"{mark_price:.2f}" if mark_price is not None else None,
        "UPNL (USD)": f"{upnl_val:.2f}" if upnl_val is not None else None
    })

df = pd.DataFrame(rows)

# ---------- ALERT UI (session state) ----------
st.sidebar.header("Set Alert")
if "alerts" not in st.session_state:
    st.session_state.alerts = []
if "triggered" not in st.session_state:
    st.session_state.triggered = set()

# make contract list and handle prefill safely
symbols = df["Symbol"].unique().tolist() if not df.empty else []
pref_sym = st.session_state.get("prefill_symbol", None)
default_index = symbols.index(pref_sym) if (pref_sym in symbols) else 0 if symbols else 0

criteria_list = ["UPNL (USD)", "Mark Price"]
pref_crit = st.session_state.get("prefill_criteria", None)
default_crit_index = criteria_list.index(pref_crit) if (pref_crit in criteria_list) else 0

cond_list = [">=", "<="]
pref_cond = st.session_state.get("prefill_condition", None)
default_cond_index = cond_list.index(pref_cond) if (pref_cond in cond_list) else 0

contract_choice = st.sidebar.selectbox(
    "Contract",
    symbols if symbols else ["No Contracts"],
    index=default_index if symbols else 0
)
criteria_choice = st.sidebar.selectbox(
    "Criteria",
    criteria_list,
    index=default_crit_index
)
condition_choice = st.sidebar.selectbox(
    "Condition",
    cond_list,
    index=default_cond_index
)
threshold_value = st.sidebar.number_input(
    "Threshold",
    format="%.2f",
    value=st.session_state.get("prefill_threshold", 0.0)
)

if st.sidebar.button("Add Alert"):
    if symbols:
        st.session_state.alerts.append({
            "symbol": contract_choice,
            "criteria": criteria_choice,
            "condition": condition_choice,
            "threshold": threshold_value
        })
        st.sidebar.success(f"Alert added for {contract_choice}")
    else:
        st.sidebar.error("No contracts available to add an alert for.")
    # Clear prefill
    for k in ["prefill_symbol", "prefill_criteria", "prefill_condition", "prefill_threshold"]:
        st.session_state.pop(k, None)

# ---------- CHECK ALERTS ----------
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

# ---------- DISPLAY TITLE ----------
st.title("Delta Exchange Positions (Auto-refresh every 3s, Alerts Enabled)")

# ---------- CUSTOM TABLE: header + rows ----------
# This builds a row-by-row display where the final column (right-most) is the Add Alert button.
if df.empty:
    st.info("No position rows to display.")
else:
    # Header
    col_count = len(df.columns) + 1  # +1 for the Alert button column
    header_cols = st.columns([1] * col_count)
    for i, cname in enumerate(df.columns):
        header_cols[i].markdown(f"**{cname}**")
    header_cols[-1].markdown("**Alert**")

    # Rows
    for idx, row in df.iterrows():
        # create columns for all df columns + the final Alert button column
        row_cols = st.columns([1] * col_count)
        for i, cname in enumerate(df.columns):
            val = row[cname]
            # specific formatting for UPNL (USD) to visually match the prior color styling
            if cname == "UPNL (USD)":
                # try numeric and color accordingly
                try:
                    num = float(val)
                    if num > 0:
                        bgcolor = "#bff2c4"  # light green
                    elif num < 0:
                        bgcolor = "#f7bdbd"  # light red
                    else:
                        bgcolor = "transparent"
                    cell_html = f"<div style='padding:6px;border-radius:6px;background:{bgcolor};text-align:right'>{num:.2f}</div>"
                except:
                    cell_html = f"<div style='padding:6px;text-align:right'>{val}</div>"
                row_cols[i].markdown(cell_html, unsafe_allow_html=True)
            else:
                # right align numeric-looking columns, left align otherwise
                try:
                    # numeric check
                    float_val = float(str(val).replace(",", ""))
                    row_cols[i].markdown(f"<div style='text-align:right;padding:4px'>{float_val}</div>", unsafe_allow_html=True)
                except:
                    row_cols[i].markdown(f"<div style='text-align:left;padding:4px'>{val}</div>", unsafe_allow_html=True)

        # Alert button in the right-most column
        if row_cols[-1].button("➕ Alert", key=f"add_alert_{idx}"):
            # prefill the sidebar form for quick alert creation
            st.session_state["prefill_symbol"] = row["Symbol"]
            st.session_state["prefill_criteria"] = "UPNL (USD)"
            st.session_state["prefill_condition"] = ">="
            st.session_state["prefill_threshold"] = 0.0
            # Inform user to use sidebar to finalize
            st.sidebar.info(f"Pre-filled alert form for {row['Symbol']} — set threshold and click Add Alert")

# ---------- SHOW ORIGINAL DATAFRAME STYLED (optional for reference) ----------
# keep this if you still want the interactive styled dataframe below the custom table
def color_pnl(val):
    try:
        num = float(val)
    except:
        return ""
    if num > 0:
        return "background-color: lightgreen"
    elif num < 0:
        return "background-color: salmon"
    return ""

with st.expander("Show styled dataframe (visual reference)", expanded=False):
    st.dataframe(df.style.applymap(color_pnl, subset=["UPNL (USD)"]))

# ---------- ACTIVE ALERTS MAIN AREA (removable) ----------
if st.session_state.alerts:
    st.subheader("Active Alerts")
    for i, alert in enumerate(list(st.session_state.alerts)):  # copy to allow safe pop
        cols = st.columns([5, 1])
        with cols[0]:
            st.write(alert)
        with cols[1]:
            if st.button("❌ Remove", key=f"remove_alert_{i}"):
                # remove that alert and rerun to refresh UI
                st.session_state.alerts.pop(i)
                st.experimental_rerun()
