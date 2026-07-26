import importlib, inspect, sys

MSG = "🔔 Test Telegram: Empire prêt (via tg_probe)"

# 1) Import du module
try:
    mod = importlib.import_module("utils.telegram_client")
except Exception as e:
    print(f"❌ Import error utils.telegram_client: {e}")
    sys.exit(1)

# 2) Cherche une fonction candidate
prefer = [
    "_tg", "_t", "send_message", "send", "notify",
    "push", "post", "send_text", "send_telegram",
    "message", "publish"
]

def pick_sender(m):
    for name in prefer:
        fn = getattr(m, name, None)
        if callable(fn):
            return name, fn
    # scan fallback: première callable exportée
    for name, obj in vars(m).items():
        if not name.startswith("_") and callable(obj):
            return name, obj
    return None, None

name, sender = pick_sender(mod)

if sender is None:
    public = [n for n in dir(mod) if not n.startswith("_")]
    print("❌ Aucune fonction d'envoi trouvée dans utils.telegram_client.")
    print("   Noms exportés:", public)
    sys.exit(2)

print(f"→ Utilisation de utils.telegram_client.{name}()")

# 3) Construit des kwargs intelligents selon la signature
try:
    sig = inspect.signature(sender)
    params = sig.parameters
except Exception:
    # pas de signature (builtins) → tente positionnel simple
    params = {}

kwargs = {}
args = []

# paramètre message
if "text" in params:         kwargs["text"] = MSG
elif "message" in params:    kwargs["message"] = MSG
elif "msg" in params:        kwargs["msg"] = MSG
elif "content" in params:    kwargs["content"] = MSG
else:
    # sinon on tente en positionnel
    args.append(MSG)

# flags optionnels si supportés
if "kind" in params:   kwargs["kind"] = "startup"
if "force" in params:  kwargs["force"] = True
if "cfg" in params:    kwargs["cfg"] = None

# 4) Envoi
try:
    if kwargs and args:
        sender(*args, **kwargs)
    elif kwargs:
        sender(**kwargs)
    elif args:
        sender(*args)
    else:
        sender(MSG)  # dernier recours
    print("✅ Message Telegram envoyé (ou tentative effectuée).")
except TypeError as e:
    # dernier essai: juste le message en positionnel
    try:
        sender(MSG)
        print("✅ Message Telegram envoyé en positionnel.")
    except Exception as e2:
        print(f"❌ Échec d'appel ({type(e2).__name__}): {e2}")
except Exception as e:
    print(f"❌ Erreur à l'envoi ({type(e).__name__}): {e}")
