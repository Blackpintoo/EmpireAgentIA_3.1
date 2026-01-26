
import streamlit as st
import json
import os
import pandas as pd
import datetime
import time

st.set_page_config(page_title="Empire IA - Signaux Live", layout="wide")

DATA_PATH = "data/latest_signals.json"
HISTO_PATH = "data/signal_history.csv"

st.title("📡 Dashboard Live - Empire IA")
st.markdown("Affichage en temps réel des signaux générés par les agents IA.")

# === Chargement des données JSON ===
def load_latest_signals(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

data = load_latest_signals(DATA_PATH)

if not data:
    st.warning("Aucun signal disponible pour le moment.")
    st.stop()

timestamp = data.get("timestamp", "N/A")
symbol = data.get("symbol", "N/A")
signals = data.get("signals", {})

st.subheader(f"🕒 Signaux actuels — {symbol} @ {timestamp}")

# === Tableau principal ===
rows = []
for agent, signal_data in signals.items():
    s = signal_data.get("signal")
    intensity = signal_data.get("intensity", None)
    reason = signal_data.get("reason", None)
    color = "🟢" if s else "🔴"
    status = s if s else (reason or "Aucun")
    rows.append((agent, color, status, intensity))

df = pd.DataFrame(rows, columns=["Agent", "Statut", "Signal / Raison", "Intensité"])
st.dataframe(df, use_container_width=True, height=300)

# === Historique ===
def append_to_history(symbol, timestamp, signals, histo_path=HISTO_PATH):
    os.makedirs(os.path.dirname(histo_path), exist_ok=True)
    rows = []
    for agent, s in signals.items():
        rows.append({
            "timestamp": timestamp,
            "symbol": symbol,
            "agent": agent,
            "signal": s.get("signal"),
            "intensity": s.get("intensity"),
            "reason": s.get("reason", "")
        })
    df = pd.DataFrame(rows)
    if os.path.exists(histo_path):
        df.to_csv(histo_path, mode="a", index=False, header=False)
    else:
        df.to_csv(histo_path, index=False)

# Enregistrement historique à chaque rafraîchissement
append_to_history(symbol, timestamp, signals)

# === Graphiques ===
st.subheader("📊 Historique des signaux")

if os.path.exists(HISTO_PATH):
    df_histo = pd.read_csv(HISTO_PATH)
    df_histo["timestamp"] = pd.to_datetime(df_histo["timestamp"])
    agents = df_histo["agent"].unique()

    tab1, tab2 = st.tabs(["🎯 Intensité", "⛔ Blocages / Aucun signal"])

    with tab1:
        for agent in agents:
            sub = df_histo[(df_histo["agent"] == agent) & (df_histo["intensity"].notna())]
            if sub.empty:
                continue
            st.line_chart(
                sub.set_index("timestamp")[["intensity"]],
                height=200,
                use_container_width=True
            )

    with tab2:
        df_blocked = df_histo[df_histo["signal"].isna()]
        if df_blocked.empty:
            st.info("Aucun blocage détecté dans l'historique.")
        else:
            st.dataframe(df_blocked[["timestamp", "agent", "reason"]], use_container_width=True)
else:
    st.info("Aucune donnée historique enregistrée pour l'instant.")

# === Auto-refresh ===
st.markdown("""<meta http-equiv="refresh" content="30">""", unsafe_allow_html=True)
