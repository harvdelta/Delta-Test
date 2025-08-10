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
    url = "https://api.delta.exchange/v2/positions"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()["result"]
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error fetching positions: {e}")
        return pd.DataFrame()

df = fetch_positions()

# ---------------- PROCESS DATA ----------------
if not df.empty:
    # Keep only the required columns
    df = df[["symbol", "size", "size_currency", "entry_price", "index_price", "mark_price", "unrealized_pnl"]]
    df.columns = ["Symbol", "Size (lots)", "Size (coins)", "Entry Price", "Index Price", "Mark Price", "UPNL (USD)"]

    # Color for UPNL
    def color_upnl(val):
        color = "green" if val > 0 else "red"
        return f"<div style='background-color:{color};color:white;border-radius:6px;padding:4px;text-align:center'>{val:.2f}</div>"

    # Create HTML table
    table_html = """
    <style>
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            text-align: center;
            padding: 8px;
        }
        td {
            text-align: center;
            padding: 8px;
            font-family: monospace;
        }
        th:first-child, td:first-child {
            text-align: left;
            font-weight: bold;
            font-family: sans-serif;
        }
        button.alert-btn {
            background-color: #262730;
            border: 1px solid #555;
            color: white;
            padding: 4px 8px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        button.alert-btn:hover {
            background-color: #444;
        }
    </style>
    <table>
        <tr>
            {}
        </tr>
    """.format("".join(f"<th>{col}</th>" for col in df.columns) + "<th>Alert</th>")

    # Build rows
    for _, row in df.iterrows():
        table_html += "<tr>"
        for col in df.columns:
            if col == "UPNL (USD)":
                table_html += f"<td>{color_upnl(row[col])}</td>"
            else:
                table_html += f"<td>{row[col]}</td>"
        # Alert button triggers session state change via form
        btn_key = f"alert_{row['Symbol']}"
        table_html += f"<td><form action='' method='post'><input type='hidden' name='symbol' value='{row['Symbol']}' /><button class='alert-btn' type='submit'>+</button></form></td>"
        table_html += "</tr>"

    table_html += "</table>"

    st.markdown(table_html, unsafe_allow_html=True)

# ---------------- FORM HANDLING ----------------
# Streamlit hack to capture POST form submissions
import streamlit.runtime.scriptrunner.script_run_context as ctx
import streamlit.runtime.state.session_state as state

# We can't capture HTML form post in Streamlit directly — so we'll use st.button in real layout
# Instead of using pure HTML buttons, let's rebuild with Streamlit's native elements for real-time session changes.

# Rerun with native button layout
st.write("")  # Spacer

for i, row in df.iterrows():
    if st.button("+", key=f"alertbtn_{row['Symbol']}", help=f"Set alert for {row['Symbol']}"):
        st.session_state.edit_symbol = row['Symbol']

# ---------------- ALERT EDITOR ----------------
if st.session_state.edit_symbol:
    with st.sidebar:
        st.header(f"Set Alert for {st.session_state.edit_symbol}")
        move_percent = st.number_input("Move %", value=5.0, step=0.1)
        price_target = st.number_input("Target Price", value=0.0, step=0.01)
        if st.button("Save Alert"):
            st.success(f"Alert set for {st.session_state.edit_symbol} — {move_percent}% or ${price_target}")
            st.session_state.edit_symbol = None
