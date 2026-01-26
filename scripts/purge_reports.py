#!/usr/bin/env python
"""
Purge les rapports quotidiens en créant une copie d'archive avant suppression.

Par défaut:
 - Source : reports/daily_exports
 - Archive: reports/archive_exports
 - Âge minimum: 14 jours
 - Cadence: une purge toutes les deux semaines (mise en cache via data/maintenance/last_reports_purge.txt)
"""
from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional

ARCHIVE_TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _parse_folder_ts(name: str) -> Optional[datetime]:
    """
    Extrait le timestamp depuis daily_report_YYYYMMDD_HHMMSS.
    Fallback sur None si format inconnu.
    """
    m = re.match(r"daily_report_(\d{8})_(\d{6})", name)
    if not m:
        return None
    try:
        return datetime.strptime("".join(m.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _list_candidates(source: Path) -> Iterable[Path]:
    for entry in source.iterdir():
        if entry.is_dir():
            yield entry


def _should_run(state_file: Path, interval_days: int, force: bool) -> bool:
    if force:
        return True
    if not state_file.exists():
        return True
    try:
        last = datetime.fromisoformat(state_file.read_text(encoding="utf-8").strip())
    except Exception:
        return True
    return datetime.now() - last >= timedelta(days=interval_days)


def _archive_dest(base: Path, folder_name: str) -> Path:
    dest = base / folder_name
    if not dest.exists():
        return dest
    suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    return base / f"{folder_name}_{suffix}"


def purge_reports(
    *,
    source_dir: Path,
    archive_dir: Path,
    retention_days: int,
    min_interval_days: int,
    state_file: Path,
    force: bool = False,
) -> List[Path]:
    if not source_dir.exists():
        print(f"[purge_reports] Source introuvable: {source_dir}")
        return []
    state_file.parent.mkdir(parents=True, exist_ok=True)

    if not _should_run(state_file, min_interval_days, force):
        print("[purge_reports] Intervalle minimum non atteint, aucune purge.")
        return []

    archive_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    threshold = now - timedelta(days=retention_days)

    removed: List[Path] = []
    for folder in sorted(_list_candidates(source_dir)):
        folder_ts = _parse_folder_ts(folder.name) or datetime.fromtimestamp(folder.stat().st_mtime)
        if folder_ts > threshold:
            continue
        dest = _archive_dest(archive_dir, folder.name)
        print(f"[purge_reports] Archivage {folder} -> {dest}")
        shutil.copytree(folder, dest)
        shutil.rmtree(folder)
        removed.append(folder)

    state_file.write_text(datetime.now().strftime(ARCHIVE_TS_FORMAT), encoding="utf-8")
    print(f"[purge_reports] {len(removed)} dossier(s) archivé(s) puis supprimé(s).")
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Archive puis purge les vieux rapports quotidiens.")
    parser.add_argument("--source", type=Path, default=Path("reports") / "daily_exports", help="Répertoire des rapports.")
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("reports") / "archive_exports",
        help="Répertoire où stocker les copies avant suppression.",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=14,
        help="Âge minimum (en jours) avant archivage/suppression.",
    )
    parser.add_argument(
        "--interval-days",
        type=int,
        default=14,
        help="Intervalle minimal entre deux purges.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("data") / "maintenance" / "last_reports_purge.txt",
        help="Fichier où stocker la date de dernière purge.",
    )
    parser.add_argument("--force", action="store_true", help="Ignorer l'intervalle minimum.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    purge_reports(
        source_dir=args.source,
        archive_dir=args.archive,
        retention_days=max(1, args.retention_days),
        min_interval_days=max(1, args.interval_days),
        state_file=args.state_file,
        force=bool(args.force),
    )


if __name__ == "__main__":
    main()
