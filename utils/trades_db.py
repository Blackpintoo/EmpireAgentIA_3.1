# >>> EMPIRE PATCH 10 — trades_db (NEW FILE)
import sqlite3, os
DB_PATH = os.path.join("data", "empire.db")

DDL = """
CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc TEXT,
  symbol TEXT,
  side TEXT,
  lots REAL,
  entry REAL,
  sl REAL,
  tp REAL,
  retcode INTEGER,
  ok INTEGER,
  ticket INTEGER,
  reqid TEXT,
  comment TEXT
);
CREATE TABLE IF NOT EXISTS cycles(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc TEXT,
  symbol TEXT,
  vote_json TEXT,
  decision TEXT,
  reason TEXT
);
"""

def init():
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB_PATH) as c:
        c.executescript(DDL)

def insert_trade(row: dict):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""INSERT INTO trades(ts_utc,symbol,side,lots,entry,sl,tp,retcode,ok,ticket,reqid,comment)
                     VALUES(:ts_utc,:symbol,:side,:lots,:entry,:sl,:tp,:retcode,:ok,:ticket,:reqid,:comment)""", row)

def insert_cycle(row: dict):
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""INSERT INTO cycles(ts_utc,symbol,vote_json,decision,reason)
                     VALUES(:ts_utc,:symbol,:vote_json,:decision,:reason)""", row)
# <<< EMPIRE PATCH 10
