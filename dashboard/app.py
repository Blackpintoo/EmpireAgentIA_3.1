import streamlit as st
import pandas as pd
import MetaTrader5 as mt5
from utils.mt5_client import MT5Client

st.set_page_config(title="Empire Agent IA 3 – Dashboard", layout="wide")
client = MT5Client()

symbol = st.sidebar.selectbox("Symbole", ["BTCUSD", "XAUUSD"])
tf = st.sidebar.selectbox("Timeframe", ["M1", "M5", "H1", "H4", "D1"])

# Convert timeframe string to MT5 constant via client helper
tf_code = client.parse_timeframe(tf)

rates = client.fetch_ohlc(symbol, tf_code, n=500)
df = pd.DataFrame(rates)
if not df.empty:
    df['time'] = pd.to_datetime(df['time'], unit='s')
    st.line_chart(df.set_index('time')[['open', 'high', 'low', 'close']])
else:
    st.warning("Aucune donnée reçue. Vérifie MT5 et le symbole.")
