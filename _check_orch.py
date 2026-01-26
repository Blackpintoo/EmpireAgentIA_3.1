import orchestrator.orchestrator as m, inspect
print("FILE:", m.__file__)
print("HAS _log_equity_snapshot:", hasattr(m.Orchestrator, "_log_equity_snapshot"))
