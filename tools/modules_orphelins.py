# -*- coding: utf-8 -*-
"""
tools/modules_orphelins.py — identifie les modules jamais atteints par le
runtime, et distingue ceux qui sont vraiment orphelins de ceux qui servent
encore à un script ou un test.

AJOUT 2026-07-30 (P6).

Méthode, en deux passes indépendantes :

  1. ACCESSIBILITE. On part des points d'entrée réels (main.py,
     scheduler_empire.py, scripts/start_empire.py) et on suit les imports en
     lisant l'AST — pas en important, pour ne rien exécuter. Tout module du
     dépôt non atteint est un candidat.

  2. RECHERCHE DE REFERENCES. Pour chaque candidat, on cherche toute mention
     de son nom de module dans TOUT le dépôt (imports dynamiques, chaînes de
     caractères, importlib, configuration). Un candidat encore mentionné
     ailleurs n'est PAS orphelin.

Seuls les modules qui échouent aux deux passes sont proposés à l'archivage.

    python tools/modules_orphelins.py                 # rapport
    python tools/modules_orphelins.py --deplacer      # deplace vers archive/
"""
import argparse
import ast
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

POINTS_ENTREE = ["main.py", "scheduler_empire.py", "scripts/start_empire.py"]
PAQUETS = ("utils", "agents", "orchestrator", "connectors", "optimization",
           "backtest", "scripts", "tools", "core", "risk")
IGNORER = {".git", "__pycache__", ".venv", "venv", "archive", "data", "logs",
           "reports", "_transfert", ".pytest_cache", "tests", "backups"}


def modules_du_depot() -> Dict[str, Path]:
    """Nom de module pointé (utils.risk_manager) -> chemin."""
    trouves: Dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in IGNORER]
        for nom in filenames:
            if not nom.endswith(".py"):
                continue
            chemin = Path(dirpath) / nom
            rel = chemin.relative_to(".")
            parts = list(rel.parts)
            if parts[-1] == "__init__.py":
                parts = parts[:-1]
            else:
                parts[-1] = parts[-1][:-3]
            if not parts:
                continue
            trouves[".".join(parts)] = rel
    return trouves


def imports_de(chemin: Path) -> Set[str]:
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return set()
    noms: Set[str] = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for a in noeud.names:
                noms.add(a.name)
        elif isinstance(noeud, ast.ImportFrom):
            if noeud.module and noeud.level == 0:
                noms.add(noeud.module)
                for a in noeud.names:
                    noms.add("%s.%s" % (noeud.module, a.name))
    return noms


def accessibles(index: Dict[str, Path]) -> Set[str]:
    vus: Set[str] = set()
    pile: List[Path] = [Path(p) for p in POINTS_ENTREE if Path(p).exists()]
    while pile:
        chemin = pile.pop()
        for nom in imports_de(chemin):
            if nom in vus:
                continue
            if nom in index:
                vus.add(nom)
                pile.append(index[nom])
            else:
                # from utils.x import y -> essayer le prefixe
                parent = nom.rsplit(".", 1)[0]
                if parent in index and parent not in vus:
                    vus.add(parent)
                    pile.append(index[parent])
    return vus


def references(nom_module: str) -> List[str]:
    """Toute mention du module ailleurs dans le depot (hors lui-meme)."""
    court = nom_module.rsplit(".", 1)[-1]
    motif = re.compile(r"\b%s\b" % re.escape(court))
    hits: List[str] = []
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in IGNORER - {"tests"}]
        for nom in filenames:
            if not nom.endswith((".py", ".yaml", ".yml", ".cfg", ".ini", ".bat", ".toml")):
                continue
            chemin = Path(dirpath) / nom
            if str(chemin.relative_to(".")).replace("\\", "/") == \
                    str(Path(nom_module.replace(".", "/") + ".py")).replace("\\", "/"):
                continue
            try:
                texte = chemin.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, ligne in enumerate(texte.splitlines(), 1):
                if motif.search(ligne) and (
                        "import" in ligne or "importlib" in ligne or court + "." in ligne):
                    hits.append("%s:%d" % (chemin.relative_to("."), i))
                    break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deplacer", action="store_true",
                    help="deplace vers archive/ les modules confirmes orphelins")
    a = ap.parse_args()

    index = modules_du_depot()
    joignables = accessibles(index)

    candidats = sorted(m for m in index
                       if m not in joignables
                       and m.split(".")[0] in PAQUETS
                       and not m.startswith(("tools.", "scripts.")))

    orphelins, encore_utilises = [], []
    for m in candidats:
        refs = references(m)
        (orphelins if not refs else encore_utilises).append((m, refs))

    print("=" * 78)
    print("  MODULES NON ATTEINTS PAR LE RUNTIME")
    print("  points d'entree : %s" % ", ".join(POINTS_ENTREE))
    print("=" * 78)
    print("\n  %d module(s) atteints, %d candidat(s) hors chemin d'execution.\n"
          % (len(joignables), len(candidats)))

    print("  ORPHELINS CONFIRMES (aucune reference nulle part) : %d" % len(orphelins))
    for m, _ in orphelins:
        print("    %-45s %s" % (m, index[m]))

    print("\n  HORS RUNTIME MAIS ENCORE REFERENCES : %d" % len(encore_utilises))
    for m, refs in encore_utilises:
        print("    %-45s <- %s" % (m, ", ".join(refs[:3])))

    if not a.deplacer:
        print("\n  Rapport seul. Ajoute --deplacer pour archiver les orphelins confirmes.")
        return 0

    deplaces = 0
    for m, _ in orphelins:
        src = index[m]
        dst = Path("archive") / src
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        deplaces += 1
        print("    archive : %s -> %s" % (src, dst))
    print("\n  %d module(s) deplace(s) vers archive/. Aucun n'a ete supprime." % deplaces)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
