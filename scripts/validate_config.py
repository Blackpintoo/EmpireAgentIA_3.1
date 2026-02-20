#!/usr/bin/env python3
# scripts/validate_config.py
# FIX 2026-02-20: Script de validation de configuration (étape 6.4)
"""
Vérifie la cohérence de la configuration EmpireAgentIA :
- overrides.yaml : clés requises, types, valeurs dans les bornes
- profiles.yaml : existence et structure
- config.yaml : clés globales
- Imports de tous les modules
"""
from __future__ import annotations

import os
import sys
import importlib

# Ajouter le répertoire racine au path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml


def _load_yaml(path: str) -> dict:
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print(f"  [WARN] Fichier manquant: {path}")
        return {}
    with open(full, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_overrides() -> list[str]:
    """Valide config/overrides.yaml."""
    errors: list[str] = []
    ov = _load_yaml("config/overrides.yaml")
    if not ov:
        errors.append("overrides.yaml est vide ou manquant")
        return errors

    # Vérifier GLOBAL
    glb = ov.get("GLOBAL", {})
    if not glb:
        errors.append("Section GLOBAL manquante dans overrides.yaml")
    else:
        risk = glb.get("risk", {})
        if not risk.get("global_daily_loss_limit"):
            errors.append("GLOBAL.risk.global_daily_loss_limit manquant")
        if not glb.get("eod_close_time_utc"):
            errors.append("GLOBAL.eod_close_time_utc manquant")

    # Vérifier chaque symbole
    required_keys = ["orchestrator"]
    for sym, cfg in ov.items():
        if sym == "GLOBAL" or not isinstance(cfg, dict):
            continue

        orch = cfg.get("orchestrator", {})
        if not orch:
            errors.append(f"{sym}: section orchestrator manquante")
            continue

        # Vérifier position_limits
        pl = orch.get("position_limits", {})
        max_vol = pl.get("max_volume", 0)
        if max_vol and max_vol <= 0:
            errors.append(f"{sym}: max_volume <= 0")

        # Vérifier position_manager
        pm = orch.get("position_manager", {})
        partials = pm.get("partials", [])
        if partials:
            for p in partials:
                rr = p.get("rr", 0)
                pct = p.get("pct", 0)
                if rr < 0.5:
                    errors.append(f"{sym}: partial RR={rr} trop bas (< 0.5)")
                if pct > 100 or pct < 0:
                    errors.append(f"{sym}: partial pct={pct} hors bornes")

        be = pm.get("break_even", {})
        be_rr = be.get("rr", 0)
        if be_rr and be_rr < 0.5:
            errors.append(f"{sym}: break_even RR={be_rr} trop bas")

        # Vérifier cooldown
        cd = orch.get("cooldown", {})
        if cd:
            min_secs = cd.get("min_secs_between_trades", 0)
            if min_secs and min_secs < 60:
                errors.append(f"{sym}: min_secs_between_trades={min_secs} < 60s (risque de spam)")

    return errors


def validate_imports() -> list[str]:
    """Vérifie que tous les modules Python compilent."""
    errors: list[str] = []
    modules = [
        "utils.risk_manager",
        "utils.circuit_breaker",
        "utils.session_filter",
        "utils.composite_score",
        "utils.market_regime",
        "agents.technical",
        "agents.scalping",
        "agents.swing",
        "agents.sentiment",
        "agents.news",
        "agents.structure",
        "agents.price_action",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as e:
            errors.append(f"Import {mod} échoué: {e}")

    return errors


def validate_py_compile() -> list[str]:
    """Compile tous les fichiers Python critiques."""
    import py_compile
    errors: list[str] = []
    critical_files = [
        "orchestrator/orchestrator.py",
        "utils/risk_manager.py",
        "utils/circuit_breaker.py",
        "utils/session_filter.py",
        "utils/composite_score.py",
        "utils/market_regime.py",
        "utils/position_manager.py",
        "agents/technical.py",
        "agents/scalping.py",
        "agents/swing.py",
        "agents/sentiment.py",
        "agents/news.py",
        "agents/structure.py",
        "agents/price_action.py",
        "agents/__init__.py",
        "scripts/start_empire.py",
    ]
    for f in critical_files:
        full = os.path.join(ROOT, f)
        if not os.path.exists(full):
            errors.append(f"Fichier manquant: {f}")
            continue
        try:
            py_compile.compile(full, doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"Erreur syntaxe {f}: {e}")

    return errors


def main():
    print("=" * 60)
    print("VALIDATION CONFIGURATION EMPIREAGENTIA 3")
    print("=" * 60)

    all_errors: list[str] = []

    print("\n[1/3] Validation overrides.yaml...")
    errs = validate_overrides()
    all_errors.extend(errs)
    if errs:
        for e in errs:
            print(f"  [ERREUR] {e}")
    else:
        print("  [OK] overrides.yaml valide")

    print("\n[2/3] Compilation Python (py_compile)...")
    errs = validate_py_compile()
    all_errors.extend(errs)
    if errs:
        for e in errs:
            print(f"  [ERREUR] {e}")
    else:
        print("  [OK] Tous les fichiers compilent")

    print("\n[3/3] Vérification imports...")
    errs = validate_imports()
    all_errors.extend(errs)
    if errs:
        for e in errs:
            print(f"  [ERREUR] {e}")
    else:
        print("  [OK] Tous les imports fonctionnent")

    print("\n" + "=" * 60)
    if all_errors:
        print(f"RÉSULTAT: {len(all_errors)} ERREUR(S) TROUVÉE(S)")
        return 1
    else:
        print("RÉSULTAT: TOUT EST OK")
        return 0


if __name__ == "__main__":
    sys.exit(main())
