# scripts/smoke_agents.py
import json, traceback
from utils.config import get_symbol_profile
from agents.technical import TechnicalAgent
from agents.scalping import ScalpingAgent
from agents.swing import SwingAgent
from agents.structure import StructureAgent
from agents.news import NewsAgent
from agents.fundamental import FundamentalAgent

SYMS = ["BTCUSD","ETHUSD","LINKUSD","BNBUSD","EURUSD","XAUUSD"]

def run_agent(name, agent):
    try:
        out = agent.generate_signal()
        print(f"[{name}] OK → {json.dumps(out)[:200]}")
    except Exception:
        print(f"[{name}] ERROR:\n{traceback.format_exc()}")

for s in SYMS:
    prof = get_symbol_profile(s)
    run_agent(f"technical:{s}", TechnicalAgent(s, profile=prof))
    run_agent(f"scalping:{s}",  ScalpingAgent(s, profile=prof))
    run_agent(f"swing:{s}",     SwingAgent(s,  profile=prof))
    run_agent(f"struct:{s}",    StructureAgent(s, profile=prof))
    run_agent(f"news:{s}",      NewsAgent())
    run_agent(f"fund:{s}",      FundamentalAgent(symbol=s, asset_currency="USD"))
