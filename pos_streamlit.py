import streamlit as st
import pandas as pd
import requests

# ---------------- CONFIG ----------------
st.set_page_config(layout="wide")
st.title("📊 Delta Exchange Positions")

# Session state for alert editing
if "edit_symbol" not in st.session_state:
    st.session_state.edit_symbol = None

# ---------------- FETCH DATA ----------------
def fetch_positions():
    # Replace with your actual API endpoint
    # Using dummy data for example
    data = [
        {"symbol": "C-BTC-120800-110825", "size": -250, "size_currency": -0.25, "entry_price": 197.0, "index_price": 118258.6, "mark_price": 106.15, "unrealized_pnl": 22.71},
        {"symbol": "C-ETH-4400-110825", "size": -169, "size_currency": -1.69, "entry_price": 18.9, "index_price": 4229.44, "mark_price": 8.40, "unrealized_pnl": 17.75},
    ]
    return pd.DataFrame(data)

df = fetch_positions()

# ---------------- PROCESS DATA ----------------
if not df.empty:
    df.columns = ["Symbol", "Size (lots)", "Size (coins)", "Entry Price", "Index Price", "Mark Price", "UPNL (USD)"]

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
        if cols[7].button("➕", key=f"alert_{row['Symbol']}"):
            st.session_state.edit_symbol = row["Symbol"]

# ---------------- ALWAYS RENDER SIDEBAR ----------------
with st.sidebar:
    if st.session_state.edit_symbol:
        st.header(f"Set Alert for {st.session_state.edit_symbol}")
        move_percent = st.number_input("Move %", value=5.0, step=0.1, key="move_input")
        price_target = st.number_input("Target Price", value=0.0, step=0.01, key="price_input")
        if st.button("💾 Save Alert", key="save_alert"):
            st.success(f"✅ Alert set for {st.session_state.edit_symbol} — {move_percent}% or ${price_target}")
            st.session_state.edit_symbol = None
    else:
        st.info("Select a contract to set an alert")
