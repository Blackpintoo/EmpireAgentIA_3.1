from orchestrator.orchestrator import _send_tg
ok = _send_tg("🔔 Ping via orchestrator bridge", kind="startup", force=True)
print("bridge_ok:", ok)
