import importlib, inspect, sys
try:
    mod = importlib.import_module("utils.telegram_client")
    print("Loaded:", mod.__file__)
except Exception as e:
    print("❌ Import error:", e); sys.exit(1)

def call(fn, *a, **k):
    try:
        fn(*a, **k); print("✓ call OK:", fn.__name__, a, k)
    except TypeError:
        try:
            fn(a[0]); print("✓ fallback positional OK:", fn.__name__)
        except Exception as e:
            print("❌ call failed:", fn.__name__, type(e).__name__, e)
    except Exception as e:
        print("❌ call failed:", fn.__name__, type(e).__name__, e)

# 1) Fonctions directes si présentes
for name in ("_tg","_t","send_message","send","notify","push","post","send_text","send_telegram","message","publish"):
    fn = getattr(mod, name, None)
    if callable(fn):
        print("Trying function:", name)
        try:
            params = set(inspect.signature(fn).parameters)
        except Exception:
            params = set()
        kw = {}
        if "kind" in params: kw["kind"]="startup"
        if "force" in params: kw["force"]=True
        if "cfg" in params: kw["cfg"]=None
        call(fn, "🔔 Test direct (function)", **kw)

# 2) Classe TelegramClient (si dispo)
cls = getattr(mod, "TelegramClient", None)
if cls:
    print("Found class TelegramClient -> instantiating")
    try:
        inst = cls()
        for m in ("send_message","send","__call__"):
            meth = getattr(inst, m, None)
            if callable(meth):
                print("Trying method:", m)
                call(meth, "🔔 Test via TelegramClient")
    except Exception as e:
        print("❌ TelegramClient init failed:", type(e).__name__, e)
