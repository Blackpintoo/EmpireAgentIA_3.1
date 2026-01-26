# scripts/test_sentiment.py
from agents.sentiment import SentimentAgent

a = SentimentAgent(symbol="BTCUSD", params={"notify_telegram": False, "contrarian": True})
print(a.generate_signal())  # doit renvoyer un dict, même si l’API FG n'est pas dispo → None géré
