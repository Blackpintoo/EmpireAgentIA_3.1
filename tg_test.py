try:
    from utils.telegram_client import _tg as _send
    used = "_tg"
except Exception:
    try:
        from utils.telegram_client import _t as _send
        used = "_t"
    except Exception:
        try:
            from utils.telegram_client import send_message as _send
            used = "send_message"
        except Exception:
            _send = None
            used = None

if _send is None:
    print("❌ Aucun sender Telegram trouvé (utils/telegram_client).")
else:
    import inspect
    params = set(inspect.signature(_send).parameters)
    kwargs = {}
    if "kind" in params: kwargs["kind"] = "startup"
    if "force" in params: kwargs["force"] = True
    if "cfg" in params: kwargs["cfg"] = None
    msg = "🔔 Test Telegram: Empire prêt (essai direct)"
    _send(msg, **kwargs) if kwargs else _send(msg)
    print(f"✅ Message envoyé via {used}")
