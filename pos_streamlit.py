import streamlit as st
import pandas as pd
import requests

# -------------------------------------------------
# PAGE SETTINGS
# -------------------------------------------------
st.set_page_config(layout="wide")
st.markdown(
    "<h1 style='display:flex; align-items:center;'>"
    "<img src='https://img.icons8.com/color/48/combo-chart--v1.png' style='margin-right:10px'/>"
    "Delta Exchange Positions"
    "</h1>",
    unsafe_allow_html=True
)

# -------------------------------------------------
# SESSION STATE FOR ALERT EDITOR
# -------------------------------------------------
if "edit_symbol" not in st.session_state:
    st.session_state.edit_symbol = None

# -------------------------------------------------
# FETCH POSITIONS (REPLACE WITH YOUR API)
# -------------------------------------------------
def fetch_positions():
    try:
        # This is placeholder data — replace with your API call
        data = [
            {"symbol": "C-BTC-120800-110825", "size": -250, "size_currency": -0.25, "entry_price": 197.0, "index_price": 118258.6, "mark_price": 106.15, "unrealized_pnl": 22.71},
            {"symbol": "C-BTC-119400-100825", "size": -312, "size_currency": -0.31, "entry_price": 75.5, "index_price": 118258.6, "mark_price": 5.62, "unrealized_pnl": 21.80},
            {"symbol": "C-BTC-119800-100825", "size": -250, "size_currency": -0.25, "entry_price": 85.0, "index_price": 118258.6, "mark_price": 2.11, "unrealized_pnl": 20.72},
            {"symbol": "C-BTC-130000-290825", "size": -300, "size_currency": -0.30, "entry_price": 468.0, "index_price": 118258.6, "mark_price": 404.78, "unrealized_pnl": 18.97},
            {"symbol": "C-ETH-4400-110825", "size": -169, "size_currency": -1.69, "entry_price": 18.9, "index_price": 4229.44, "mark_price": 8.40, "unrealized_pnl": 17.75},
            {"symbol": "C-ETH-4800-290825", "size": -108, "size_currency": -1.08, "entry_price": 65.4, "index_price": 4229.44, "mark_price": 77.86, "unrealized_pnl": -13.45},
        ]
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error fetching positions: {e}")
        return pd.DataFrame()

df = fetch_positions()

# -------------------------------------------------
# RENDER TABLE
# -------------------------------------------------
if not df.empty:
    # Rename columns for display
    df.columns = ["Symbol", "Size (lots)", "Size (coins)", "Entry Price", "Index Price", "Mark Price", "UPNL (USD)"]

    # Table column ratios
    col_widths = [2.5, 1.2, 1.2, 1.2, 1.5, 1.5, 1.5, 0.8]

    # Header
    header_cols = st.columns(col_widths)
    headers = list(df.columns) + ["Alert"]
    for hcol, hname in zip(header_cols, headers):
        hcol.markdown(f"<b>{hname}</b>", unsafe_allow_html=True)

    # Rows
    for _, row in df.iterrows():
        cols = st.columns(col_widths)
        cols[0].markdown(f"<b>{row['Symbol']}</b>", unsafe_allow_html=True)
        cols[1].write(row["Size (lots)"])
        cols[2].write(row["Size (coins)"])
        cols[3].write(f"{row['Entry Price']:.2f}")
        cols[4].write(f"{row['Index Price']:.2f}")
        cols[5].write(f"{row['Mark Price']:.2f}")
        
        # UPNL color coding
        upnl_color = "#2ecc71" if row["UPNL (USD)"] > 0 else "#e74c3c"
        cols[6].markdown(
            f"<div style='background-color:{upnl_color};color:white;border-radius:6px;padding:4px;text-align:center'>{row['UPNL (USD)']:.2f}</div>",
            unsafe_allow_html=True
        )

        # Alert button
        if cols[7].button("➕", key=f"alert_{row['Symbol']}", help=f"Set alert for {row['Symbol']}"):
            st.session_state.edit_symbol = row["Symbol"]

# -------------------------------------------------
# ALERT EDITOR PANEL
# -------------------------------------------------
with st.sidebar:
    if st.session_state.edit_symbol:
        st.header(f"Set Alert for {st.session_state.edit_symbol}")
        move_percent = st.number_input("Move %", value=5.0, step=0.1)
        price_target = st.number_input("Target Price", value=0.0, step=0.01)
        if st.button("💾 Save Alert"):
            st.success(f"✅ Alert set for {st.session_state.edit_symbol} — {move_percent}% or ${price_target}")
            st.session_state.edit_symbol = None
    else:
        st.info("Select a contract to set an alert")
