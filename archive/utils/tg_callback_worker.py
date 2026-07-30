# utils/tg_callback_worker.py
import os, time, yaml, requests, asyncio
from typing import Optional

_CFG = os.path.join("config", "config.yaml")

def _load_token_chat():
    try:
        data = yaml.safe_load(open(_CFG, encoding="utf-8")) or {}
        tg = data.get("telegram") or {}
        token = tg.get("token") or tg.get("bot_token")
        chat_id = tg.get("chat_id")
        return token, chat_id
    except Exception:
        return None, None

def run():
    """
    Boucle bloquante (à lancer dans un thread daemon) qui traite les callbacks.
    callback_data attendue: 'orch|<SYMBOL>|VALIDATE|<LONG|SHORT>' ou 'orch|<SYMBOL>|REJECT|<LONG|SHORT>'
    """
    token, chat_id = _load_token_chat()
    if not token or not chat_id:
        return

    API = f"https://api.telegram.org/bot{token}"
    offset = None

    from orchestrator.orchestrator import get_orchestrator, _send_tg  # évite la boucle d'import

    while True:
        try:
            r = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 25}, timeout=30)
            if not r.ok:
                time.sleep(1.0); continue
            data = r.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                cq = upd.get("callback_query")
                if not cq:
                    continue

                # accuse réception visuelle côté Telegram
                try:
                    requests.post(f"{API}/answerCallbackQuery", json={"callback_query_id": cq["id"]}, timeout=5)
                except Exception:
                    pass

                payload = (cq.get("data") or "").strip()
                parts = payload.split("|")
                if len(parts) < 4 or parts[0] != "orch":
                    continue

                symbol = parts[1].upper()
                action = parts[2].upper()
                direction = parts[3].upper()

                orch = get_orchestrator(symbol)
                if not orch:
                    _send_tg(f"⚠️ Aucun orchestrateur actif pour {symbol}.", kind="status", force=True)
                    continue

                if action == "VALIDATE":
                    # on exécute dans une petite boucle dédiée
                    try:
                        asyncio.run(orch.execute_trade(direction))
                    except RuntimeError:
                        # si un loop est déjà actif, on le fait “à l’ancienne”
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(orch.execute_trade(direction))
                        loop.close()
                elif action == "REJECT":
                    _send_tg(f"✋ Trade {symbol} {direction} rejeté.", kind="status", force=True)

        except Exception:
            time.sleep(1.0)
