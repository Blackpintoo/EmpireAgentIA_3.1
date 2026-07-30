# -*- coding: utf-8 -*-
"""
utils/startup_selftest.py — garde-fou de démarrage (P1, 2026-07-30).

Empêche le lancement du bot si la suite de tests ne passe pas entièrement.

Motivation
----------
Le 30 juillet 2026, le bot a tourné plusieurs heures sans pouvoir
s'authentifier auprès de MT5 : `_strip_inline_comment` tronquait le mot de
passe au premier `#`. Un test couvrait déjà le cas, mais la suite n'était
jamais exécutée avant le démarrage. Ce module ferme cette porte.

Comportement
------------
- La suite est relancée uniquement quand le code Python a changé (empreinte
  du contenu de tous les `.py` suivis). Sinon le résultat mémorisé dans
  `data/selftest_state.json` est réutilisé : coût nul au redémarrage.
- Fermeture par défaut (*fail-closed*) : suite en échec, pytest absent,
  dépassement du délai → le démarrage est refusé.
- Échappatoire explicite : `EMPIRE_SKIP_SELFTEST=1`. Elle laisse une trace
  bruyante dans les logs, volontairement.

Usage :
    from utils.startup_selftest import enforce_selftest
    enforce_selftest(ROOT)      # sort avec le code 3 si la suite échoue
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

# Répertoires jamais parcourus pour l'empreinte du code.
_SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "env",
    "archive", "data", "logs", "reports", "_transfert", "node_modules",
    ".mypy_cache", ".ruff_cache", "backups",
}

_STATE_REL = os.path.join("data", "selftest_state.json")
_DEFAULT_TIMEOUT_S = 420


def _iter_python_files(root: str) -> List[str]:
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                found.append(os.path.join(dirpath, name))
    found.sort()
    return found


def code_fingerprint(root: str) -> str:
    """Empreinte du contenu de tout le code Python du dépôt."""
    h = hashlib.sha256()
    for path in _iter_python_files(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        h.update(rel.encode("utf-8", "replace"))
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"<illisible>")
    return h.hexdigest()


def _read_state(root: str) -> Dict[str, object]:
    try:
        with open(os.path.join(root, _STATE_REL), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(root: str, state: Dict[str, object]) -> None:
    path = os.path.join(root, _STATE_REL)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        # Le cache est un confort, jamais une dépendance : un échec d'écriture
        # signifie simplement que la suite sera relancée au prochain démarrage.
        pass


def run_suite(root: str, timeout_s: int = _DEFAULT_TIMEOUT_S) -> Tuple[bool, str]:
    """Exécute `pytest tests/` et renvoie (succès, sortie tronquée)."""
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", "-p", "no:cacheprovider"]
    env = dict(os.environ)
    # Marqueur pour que le code applicatif puisse détecter le contexte de test.
    env["EMPIRE_SELFTEST"] = "1"
    try:
        proc = subprocess.run(
            cmd, cwd=root, env=env, timeout=timeout_s,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        return False, "pytest introuvable (python -m pytest n'a pas pu être lancé)."
    except subprocess.TimeoutExpired:
        return False, "la suite de tests a dépassé %d s." % timeout_s
    out = (proc.stdout or b"").decode("utf-8", "replace")
    if len(out) > 8000:
        out = out[:2000] + "\n... [tronqué] ...\n" + out[-6000:]
    return proc.returncode == 0, out


def check(root: str, *, force: bool = False,
          timeout_s: int = _DEFAULT_TIMEOUT_S) -> Tuple[bool, str]:
    """
    Renvoie (autorisé, motif). Réutilise le résultat mémorisé tant que
    l'empreinte du code est inchangée, sauf si `force=True`.
    """
    fingerprint = code_fingerprint(root)
    state = _read_state(root)

    if not force and state.get("fingerprint") == fingerprint and state.get("ok") is True:
        quand = state.get("ts_utc", "?")
        return True, "suite validée le %s, code inchangé depuis." % quand

    ok, output = run_suite(root, timeout_s=timeout_s)
    _write_state(root, {
        "fingerprint": fingerprint,
        "ok": bool(ok),
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "tail": output[-2000:],
    })
    if ok:
        return True, "suite de tests intégralement passée."
    return False, output


def enforce_selftest(root: str, *, logger_obj: Optional[object] = None,
                     exit_code: int = 3) -> None:
    """
    Garde-fou de démarrage. À appeler le plus tôt possible dans le point
    d'entrée, avant toute connexion MT5 ou envoi d'ordre.
    """
    def _dire(msg: str, erreur: bool = False) -> None:
        if logger_obj is not None:
            try:
                (logger_obj.error if erreur else logger_obj.info)(msg)  # type: ignore[attr-defined]
                return
            except Exception:
                pass
        print(msg, file=sys.stderr if erreur else sys.stdout, flush=True)

    if os.environ.get("EMPIRE_SKIP_SELFTEST", "").strip() in ("1", "true", "True", "yes"):
        _dire("[SELFTEST] CONTOURNE via EMPIRE_SKIP_SELFTEST=1 — "
              "le bot démarre SANS validation de la suite de tests.", erreur=True)
        return

    force = os.environ.get("EMPIRE_FORCE_SELFTEST", "").strip() in ("1", "true", "True", "yes")
    ok, motif = check(root, force=force)
    if ok:
        _dire("[SELFTEST] OK — %s" % motif)
        return

    _dire("=" * 70, erreur=True)
    _dire("[SELFTEST] DEMARRAGE REFUSE : la suite de tests ne passe pas.", erreur=True)
    _dire("=" * 70, erreur=True)
    _dire(motif, erreur=True)
    _dire("", erreur=True)
    _dire("Relance la suite pour voir le détail :", erreur=True)
    _dire("    python -m pytest tests -q", erreur=True)
    _dire("Pour démarrer malgré tout (à tes risques) : "
          "définis EMPIRE_SKIP_SELFTEST=1", erreur=True)
    sys.exit(exit_code)
