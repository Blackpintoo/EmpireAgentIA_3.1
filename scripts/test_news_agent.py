# scripts/test_news_agent.py
from agents.news import NewsAgent
na = NewsAgent(params={"macro_block": True, "retry": 0, "max_per_feed": 5})
print(na.generate_signal())  # doit renvoyer dict avec signal None si macro block détecté (selon contexte)
