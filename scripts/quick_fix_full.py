# scripts/quick_fix_keepalive.py
import re, pathlib

p = pathlib.Path("orchestrator/orchestrator.py")
src = p.read_text(encoding="utf-8")
orig = src

changed = False

# a) S'assurer qu'on a import time
if "import time" not in src:
    src = src.replace("\nimport logging", "\nimport logging\nimport time", 1)
    changed = True

# b) Ajouter une bannière claire après parse_args / OVERRIDES_PATH
if "START Orchestrator | symbols=" not in src and "args.symbols" in src:
    src = re.sub(
        r'(OVERRIDES_PATH\s*=\s*args\.overrides\s*)',
        r'\1\nlogger.info(f"START Orchestrator | symbols={args.symbols} | overrides={OVERRIDES_PATH}")\n',
        src, count=1
    )
    changed = True

# c) Démarrer /healthz s'il n'est pas déjà démarré
if "from utils.health import start_health_server" not in src:
    lines = src.splitlines()
    # injecter l'import juste après le dernier import
    last_import = 0
    for i, line in enumerate(lines[:200]):
        if line.startswith(("import ", "from ")):
            last_import = i
    lines.insert(last_import+1, "from utils.health import start_health_server")
    src = "\n".join(lines)
    changed = True

if "start_health_server(" not in src:
    src = re.sub(
        r'(if __name__ == .__main__.:)',
        r'\1\n'
        r'    try:\n'
        r'        start_health_server(host="0.0.0.0", port=9108)\n'
        r'        logger.info("[/healthz] ready on :9108")\n'
        r'    except Exception as e:\n'
        r'        logger.warning(f"[health] start failed: {e}")',
        src, count=1
    )
    changed = True

# d) Ajouter un keepalive pour empêcher la sortie immédiate
if "KEEPALIVE_LOOP_START" not in src:
    src = re.sub(
        r'(if __name__ == .__main__.:.*?$)',
        r'\1\n'
        r'    # KEEPALIVE_LOOP_START\n'
        r'    try:\n'
        r'        while True:\n'
        r'            time.sleep(5)\n'
        r'    except KeyboardInterrupt:\n'
        r'        logger.info("Shutting down (KeyboardInterrupt)")\n'
        r'    # KEEPALIVE_LOOP_END',
        src, flags=re.DOTALL, count=1
    )
    changed = True

if changed:
    p.with_suffix(".py.keepbak").write_text(orig, encoding="utf-8")
    p.write_text(src, encoding="utf-8")
    print("✅ Keepalive patch appliqué. Sauvegarde:", str(p.with_suffix(".py.keepbak")))
else:
    print("ℹ️ Aucun changement (déjà patché).")
