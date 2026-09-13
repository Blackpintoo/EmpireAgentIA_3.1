# -*- coding: utf-8 -*-
"""Diagnostic de connexion - MT5 et Telegram.

Lit .env, compare ce que TOI tu as ecrit avec ce que le BOT lit reellement,
teste les deux connexions et envoie un message de test sur Telegram.
Ne modifie aucun fichier.
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

SECRETS = ("MT5_PASSWORD", "TELEGRAM_BOT_TOKEN")

def lire_brut(path=".env"):
    """Lecture litterale : ce que tu as tape."""
    env = {}
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            for l in f:
                s = l.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                env[k.strip()] = v
    except Exception as e:
        print("  [ERREUR] .env illisible :", e)
    return env

def lire_comme_le_bot(path=".env"):
    """Lecture par le parseur du projet : ce que le bot recoit vraiment."""
    try:
        from utils.config_loader import _parse_env_lines
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return _parse_env_lines(f.read().splitlines(), base={})
    except Exception as e:
        print("  [INFO] parseur du projet indisponible (%s)" % e)
        return None

print("=" * 64)
print("  DIAGNOSTIC DE CONNEXION")
print("=" * 64)

brut = lire_brut()
bot  = lire_comme_le_bot()

# ------------------------------------------------- 0. coherence du .env
print("\n[0/3] Lecture du .env")
souci = False
if bot is None:
    print("  (comparaison impossible)")
else:
    print("  %-20s %-16s %-16s %s" % ("variable", "toi", "le bot lit", "verdict"))
    for k in ("MT5_ACCOUNT", "MT5_SERVER", "MT5_PASSWORD",
              "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        a, b = brut.get(k, ""), bot.get(k, "")
        if k in SECRETS:
            va, vb = "%d car." % len(a), "%d car." % len(b)
        else:
            va, vb = a or "(absent)", b or "(absent)"
        if not a:
            verdict = "ABSENT"
        elif a == b:
            verdict = "ok"
        else:
            verdict = "<<< TRONQUE OU ALTERE"
            souci = True
        print("  %-20s %-16s %-16s %s" % (k, va, vb, verdict))
    if souci:
        print("\n  [PROBLEME] Une valeur est alteree a la lecture.")
        print("  Cause la plus frequente : un caractere # dans la valeur. Le parseur")
        print("  coupe au premier #. Solution : entoure la valeur de guillemets droits :")
        print('      MT5_PASSWORD="mon#mot#de#passe"')
        print("  Le plus sain reste un mot de passe sans caractere special.")

env = bot if bot else brut

# ------------------------------------------------------------ 1. MT5
print("\n[1/3] MetaTrader 5")
login, pwd, server = env.get("MT5_ACCOUNT", ""), env.get("MT5_PASSWORD", ""), env.get("MT5_SERVER", "")
print("  compte  :", login or "(absent)")
print("  serveur :", server or "(absent)")

try:
    import MetaTrader5 as mt5
except Exception as e:
    print("  [ECHEC] module MetaTrader5 introuvable :", e)
    mt5 = None

if mt5:
    print("\n  -- essai 1 : terminal deja ouvert et connecte ?")
    if mt5.initialize():
        ai = mt5.account_info()
        if ai:
            print("     [OK] compte %s | %s" % (ai.login, ai.server))
            print("     solde  : %.2f %s" % (ai.balance, ai.currency))
            print("     equity : %.2f %s" % (ai.equity, ai.currency))
            print("     levier : 1:%s" % ai.leverage)
            print("     Algo Trading :", "ACTIVE" if ai.trade_allowed else "DESACTIVE  <<< bouton a passer au vert dans MT5")
            if str(ai.login) != str(login):
                print("     [ATTENTION] terminal sur %s, .env demande %s" % (ai.login, login))
            print("\n     >>> Risque par trade a 0.5%% de l'equity : %.0f %s" % (0.005 * ai.equity, ai.currency))
            print("     >>> Plafond configure : 250 USD")
        mt5.shutdown()
    else:
        print("     non connecte :", mt5.last_error())
        print("\n  -- essai 2 : connexion avec les identifiants du .env")
        print("     (peut prendre jusqu'a 60 s : MT5 lance le terminal et s'authentifie)")
        sys.stdout.flush()
        ok = False
        try:
            ok = mt5.initialize(login=int(login), password=pwd, server=server)
        except Exception as e:
            print("     exception :", e)
        if ok:
            ai = mt5.account_info()
            print("     [OK] authentification reussie")
            if ai:
                print("     compte %s | solde %.2f %s | equity %.2f %s"
                      % (ai.login, ai.balance, ai.currency, ai.equity, ai.currency))
                print("     >>> Risque a 0.5%% de l'equity : %.0f %s" % (0.005 * ai.equity, ai.currency))
            mt5.shutdown()
        else:
            code, msg = mt5.last_error()
            print("     [ECHEC] code %s : %s" % (code, msg))
            if code == -6:
                print("     -> Le trio compte / mot de passe / serveur est refuse.")
                print("        1. Verifie la ligne [0/3] ci-dessus : le mot de passe est-il tronque ?")
                print("        2. Ouvre MT5 a la main et connecte-toi au compte %s" % login)
                print("           sur %s. Si MT5 refuse aussi, le compte est mort." % server)
                print("        3. Attention au mot de passe INVESTISSEUR (lecture seule) :")
                print("           il permet de se connecter mais interdit le trading.")
            elif code == -10:
                print("     -> Le terminal ne demarre pas. Verifie mt5.terminal_path dans config.yaml.")

# -------------------------------------------------------- 2. Telegram
print("\n[2/3] Telegram")
tok  = env.get("TELEGRAM_BOT_TOKEN", "")
chat = env.get("TELEGRAM_CHAT_ID", "")

if not tok:
    print("  [ABSENT] TELEGRAM_BOT_TOKEN")
else:
    try:
        import requests
    except Exception as e:
        print("  [ECHEC] module requests indisponible :", e)
        requests = None

    if requests:
        base = "https://api.telegram.org/bot%s" % tok
        print("  -- getMe : le token est-il valide ?")
        try:
            d = requests.get(base + "/getMe", timeout=15).json()
        except Exception as e:
            d = {"ok": False, "description": str(e)}
        if d.get("ok"):
            b = d["result"]
            uname = b.get("username")
            print("     [OK] bot @%s (%s)" % (uname, b.get("first_name")))
            print("     lien direct : https://t.me/%s" % uname)
        else:
            print("     [ECHEC]", d.get("description"))
            print("     -> Token revoque ou bot supprime. Dans @BotFather : /mybots -> API Token.")
            uname = None

        if d.get("ok"):
            print("\n  -- getUpdates : as-tu appuye sur DEMARRER dans la conversation ?")
            try:
                u = requests.get(base + "/getUpdates", timeout=15).json()
            except Exception as e:
                u = {"ok": False, "description": str(e)}
            vus = set()
            for it in (u.get("result") or []):
                for cle in ("message", "edited_message", "channel_post", "callback_query"):
                    o = it.get(cle) or {}
                    c = (o.get("chat") or (o.get("message") or {}).get("chat") or {})
                    if c.get("id") is not None:
                        vus.add((str(c["id"]), c.get("first_name") or c.get("title") or ""))
            if vus:
                print("     conversations detectees :")
                for cid, nom in vus:
                    marque = "  <-- celui du .env" if cid == str(chat) else ""
                    print("       chat_id %s  %s%s" % (cid, nom, marque))
                if str(chat) not in {c for c, _ in vus}:
                    print("     [ATTENTION] le chat_id du .env (%s) n'apparait pas." % chat)
                    print("     Utilise plutot un des chat_id ci-dessus.")
            else:
                print("     aucune conversation vue.")
                print("     -> Ouvre https://t.me/%s et appuie sur DEMARRER." % (uname or "ton_bot"))
                print("        Un bot ne peut PAS ecrire a quelqu'un qui ne lui a jamais parle.")
                print("        (getUpdates est aussi vide si le bot tourne deja ailleurs et")
                print("         a consomme les messages : dans ce doute, fie-toi au test ci-dessous.)")

            print("\n  -- envoi d'un message de test vers le chat_id %s" % (chat or "(absent)"))
            if not chat:
                print("     [IGNORE] TELEGRAM_CHAT_ID absent du .env")
            else:
                txt = "EmpireAgentIA - test de connexion reussi. Si tu lis ceci, les notifications fonctionnent."
                try:
                    r = requests.post(base + "/sendMessage",
                                      data={"chat_id": chat, "text": txt}, timeout=15)
                    j = r.json()
                except Exception as e:
                    r, j = None, {"ok": False, "description": str(e)}
                if j.get("ok"):
                    print("     [OK] message envoye. Verifie ton Telegram.")
                else:
                    code = getattr(r, "status_code", "?")
                    print("     [ECHEC] %s - %s" % (code, j.get("description")))
                    desc = (j.get("description") or "").lower()
                    if "chat not found" in desc:
                        print("     -> Le bot ne connait pas ce chat. Ouvre https://t.me/%s" % (uname or "ton_bot"))
                        print("        et appuie sur DEMARRER, puis relance ce diagnostic.")
                    elif "blocked" in desc:
                        print("     -> Tu as bloque ce bot. Debloque-le dans la conversation.")
                    elif "unauthorized" in desc:
                        print("     -> Token invalide.")

# ---------------------------------------------------------- 3. resume
print("\n[3/3] Resume")
print("  Si MT5 et Telegram affichent [OK], tu peux relancer START_EMPIRE.bat.")
print("  Sinon, corrige d'abord la ou les lignes marquees ci-dessus.")
print("\n" + "=" * 64)
