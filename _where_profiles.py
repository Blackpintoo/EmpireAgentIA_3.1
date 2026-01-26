import os, inspect
import utils.config as cfg
print("utils.config file:", inspect.getsourcefile(cfg))
p = getattr(cfg, "PROFILES_PATH", None)
print("PROFILES_PATH in code:", p)
try:
    print("enabled_symbols (from cfg):", cfg.get_enabled_symbols())
except Exception as e:
    print("get_enabled_symbols() error:", e)
