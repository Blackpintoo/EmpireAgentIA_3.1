__all__ = ["Orchestrator", "_norm"]

def __getattr__(name):
    if name in __all__:
        from .orchestrator import Orchestrator, _norm
        return {"Orchestrator": Orchestrator, "_norm": _norm}[name]
    raise AttributeError(name)