import os, yaml
print("PWD:", os.getcwd())
with open("profiles.yaml", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
prof = (data.get("profiles") or {})
print("enabled_symbols:", data.get("enabled_symbols"))
print("profiles keys:", list(prof.keys()))
print("LINKUSD profile exists:", "LINKUSD" in prof)
