#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MONITOR KPIs - Suivi quotidien des indicateurs de performance
PHASE 2 - 2025-12-25
CORRECTION AUDIT #7 - 2025-12-27

Ce script monitore les KPIs critiques definis dans le plan d'action:
- Win Rate (seuil min: 42%, cible: 50%+)
- Profit Factor (seuil min: 1.2, cible: 1.5+)
- Score moyen des trades (seuil min: 7.5, cible: 9.0+)
- Confluence moyenne (seuil min: 4.5, cible: 5.5+)
- % Trades contre-trend (seuil max: 20%, cible: <10%)
- Drawdown journalier (seuil max: 3%, cible: <2%)

Fonctionnalités ajoutées (AUDIT 2025-12-27):
- Exécution via cron (toutes les 4h recommandé)
- Envoi de résumé Telegram si dégradation détectée
- Sauvegarde de l'historique des KPI dans data/kpi_history.csv
- Détection de dégradation vs période précédente

Usage:
    python scripts/monitor_kpis.py
    python scripts/monitor_kpis.py --days 7
    python scripts/monitor_kpis.py --alert-only
    python scripts/monitor_kpis.py --cron  # Mode automatisé pour cron

Crontab recommandé (toutes les 4 heures):
    0 */4 * * * cd /path/to/EmpireAgentIA_3 && python scripts/monitor_kpis.py --cron >> logs/kpi_monitor.log 2>&1
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Encoding fix for Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import Telegram client
try:
    from utils.telegram_client import send_message as send_telegram
    TELEGRAM_AVAILABLE = True
except ImportError:
    def send_telegram(text, **kwargs):
        print(f"[TG] {text}")
    TELEGRAM_AVAILABLE = False

# Import logger
try:
    from utils.logger import logger
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

KPI_HISTORY_FILE = Path("data/kpi_history.csv")
DEGRADATION_THRESHOLD = 0.15  # 15% de dégradation déclenche une alerte


@dataclass
class KPIThresholds:
    """Seuils KPI selon le plan d'action"""
    win_rate_min: float = 42.0
    win_rate_target: float = 50.0
    profit_factor_min: float = 1.2
    profit_factor_target: float = 1.5
    score_mean_min: float = 7.5
    score_mean_target: float = 9.0
    confluence_mean_min: float = 4.5
    confluence_mean_target: float = 5.5
    contre_trend_max: float = 20.0
    contre_trend_target: float = 10.0
    drawdown_daily_max: float = 3.0
    drawdown_daily_target: float = 2.0
    trades_per_day_min: int = 2
    trades_per_day_max: int = 5


@dataclass
class KPIResult:
    """Resultat d'un KPI"""
    name: str
    value: float
    unit: str
    status: str  # OK, WARNING, CRITICAL
    threshold_min: Optional[float] = None
    threshold_max: Optional[float] = None
    target: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "status": self.status,
            "threshold": self.threshold_min or self.threshold_max,
            "target": self.target,
        }


def load_journal_files(journal_dir: Path, days: int = 7) -> List[Dict[str, Any]]:
    """Charge les fichiers journal CSV des N derniers jours"""
    trades = []
    cutoff = datetime.now() - timedelta(days=days)

    for csv_file in sorted(journal_dir.glob("trades_*.csv"), reverse=True):
        try:
            # Extraire la date du nom de fichier
            date_str = csv_file.stem.replace("trades_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")

            if file_date < cutoff:
                continue

            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    row["_file_date"] = file_date
                    trades.append(row)
        except Exception as e:
            print(f"[WARN] Erreur lecture {csv_file}: {e}")
            continue

    return trades


def load_proposals_log(data_dir: Path, days: int = 7) -> List[Dict[str, Any]]:
    """Charge le log des propositions"""
    proposals = []
    proposals_file = data_dir / "proposals_log.csv"

    if not proposals_file.exists():
        return proposals

    cutoff = datetime.now() - timedelta(days=days)

    try:
        with open(proposals_file, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = row.get("timestamp", "")
                    if ts:
                        row_date = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if row_date.replace(tzinfo=None) >= cutoff:
                            proposals.append(row)
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] Erreur lecture proposals_log.csv: {e}")

    return proposals


def calculate_win_rate(trades: List[Dict]) -> Tuple[float, int, int]:
    """Calcule le win rate"""
    if not trades:
        return 0.0, 0, 0

    wins = 0
    total = 0

    for t in trades:
        try:
            # Chercher un champ de profit
            profit = None
            for key in ["profit", "pnl", "result", "net_profit"]:
                if key in t and t[key]:
                    try:
                        profit = float(t[key])
                        break
                    except (ValueError, TypeError):
                        continue

            if profit is not None:
                total += 1
                if profit > 0:
                    wins += 1
        except Exception:
            continue

    return (wins / total * 100) if total > 0 else 0.0, wins, total


def calculate_profit_factor(trades: List[Dict]) -> Tuple[float, float, float]:
    """Calcule le profit factor"""
    gross_profit = 0.0
    gross_loss = 0.0

    for t in trades:
        try:
            profit = None
            for key in ["profit", "pnl", "result", "net_profit"]:
                if key in t and t[key]:
                    try:
                        profit = float(t[key])
                        break
                    except (ValueError, TypeError):
                        continue

            if profit is not None:
                if profit > 0:
                    gross_profit += profit
                else:
                    gross_loss += abs(profit)
        except Exception:
            continue

    pf = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
    return pf, gross_profit, gross_loss


def calculate_score_stats(proposals: List[Dict]) -> Tuple[float, float, int]:
    """Calcule les statistiques de score"""
    scores = []

    for p in proposals:
        try:
            score = float(p.get("score", 0))
            if score > 0:
                scores.append(score)
        except (ValueError, TypeError):
            continue

    if not scores:
        return 0.0, 0.0, 0

    mean = sum(scores) / len(scores)
    low_score_count = sum(1 for s in scores if s < 7.0)
    low_score_pct = (low_score_count / len(scores) * 100)

    return mean, low_score_pct, len(scores)


def calculate_confluence_stats(proposals: List[Dict]) -> Tuple[float, float, int]:
    """Calcule les statistiques de confluence"""
    confluences = []

    for p in proposals:
        try:
            conf = float(p.get("confluence", 0))
            if conf >= 0:
                confluences.append(conf)
        except (ValueError, TypeError):
            continue

    if not confluences:
        return 0.0, 0.0, 0

    mean = sum(confluences) / len(confluences)
    low_conf_count = sum(1 for c in confluences if c < 5)
    low_conf_pct = (low_conf_count / len(confluences) * 100)

    return mean, low_conf_pct, len(confluences)


def calculate_contre_trend_pct(proposals: List[Dict]) -> Tuple[float, int, int]:
    """Calcule le pourcentage de trades contre-trend"""
    # Cette metrique necessite les donnees MTF qui ne sont pas toujours dans proposals_log
    # On utilise une heuristique basee sur les notes de decision si disponibles

    total = 0
    contre_trend = 0

    for p in proposals:
        total += 1
        notes = str(p.get("notes", "") or p.get("decision_notes", "")).lower()
        if "contre_trend" in notes or "against_trend" in notes or "htf_opposed" in notes:
            contre_trend += 1

    pct = (contre_trend / total * 100) if total > 0 else 0.0
    return pct, contre_trend, total


def evaluate_kpis(
    trades: List[Dict],
    proposals: List[Dict],
    thresholds: KPIThresholds,
    days: int
) -> List[KPIResult]:
    """Evalue tous les KPIs et retourne les resultats"""
    results = []

    # 1. Win Rate
    wr, wins, total_trades = calculate_win_rate(trades)
    if wr < thresholds.win_rate_min:
        status = "CRITICAL"
    elif wr < thresholds.win_rate_target:
        status = "WARNING"
    else:
        status = "OK"
    results.append(KPIResult(
        name="Win Rate",
        value=wr,
        unit="%",
        status=status,
        threshold_min=thresholds.win_rate_min,
        target=thresholds.win_rate_target
    ))

    # 2. Profit Factor
    pf, gross_profit, gross_loss = calculate_profit_factor(trades)
    if pf < thresholds.profit_factor_min:
        status = "CRITICAL"
    elif pf < thresholds.profit_factor_target:
        status = "WARNING"
    else:
        status = "OK"
    results.append(KPIResult(
        name="Profit Factor",
        value=pf,
        unit="x",
        status=status,
        threshold_min=thresholds.profit_factor_min,
        target=thresholds.profit_factor_target
    ))

    # 3. Score moyen
    score_mean, low_score_pct, score_count = calculate_score_stats(proposals)
    if score_mean < thresholds.score_mean_min:
        status = "CRITICAL"
    elif score_mean < thresholds.score_mean_target:
        status = "WARNING"
    else:
        status = "OK"
    results.append(KPIResult(
        name="Score moyen",
        value=score_mean,
        unit="pts",
        status=status,
        threshold_min=thresholds.score_mean_min,
        target=thresholds.score_mean_target
    ))

    # 4. Confluence moyenne
    conf_mean, low_conf_pct, conf_count = calculate_confluence_stats(proposals)
    if conf_mean < thresholds.confluence_mean_min:
        status = "CRITICAL"
    elif conf_mean < thresholds.confluence_mean_target:
        status = "WARNING"
    else:
        status = "OK"
    results.append(KPIResult(
        name="Confluence moyenne",
        value=conf_mean,
        unit="pts",
        status=status,
        threshold_min=thresholds.confluence_mean_min,
        target=thresholds.confluence_mean_target
    ))

    # 5. % Contre-trend
    ct_pct, ct_count, ct_total = calculate_contre_trend_pct(proposals)
    if ct_pct > thresholds.contre_trend_max:
        status = "CRITICAL"
    elif ct_pct > thresholds.contre_trend_target:
        status = "WARNING"
    else:
        status = "OK"
    results.append(KPIResult(
        name="% Contre-trend",
        value=ct_pct,
        unit="%",
        status=status,
        threshold_max=thresholds.contre_trend_max,
        target=thresholds.contre_trend_target
    ))

    # 6. Trades par jour
    trades_per_day = len(proposals) / max(days, 1)
    if trades_per_day < thresholds.trades_per_day_min:
        status = "WARNING"
    elif trades_per_day > thresholds.trades_per_day_max:
        status = "WARNING"
    else:
        status = "OK"
    results.append(KPIResult(
        name="Trades/jour",
        value=trades_per_day,
        unit="trades",
        status=status,
        threshold_min=thresholds.trades_per_day_min,
        threshold_max=thresholds.trades_per_day_max,
        target=3.0
    ))

    # 7. Net P&L
    net_pnl = gross_profit - gross_loss
    results.append(KPIResult(
        name="Net P&L",
        value=net_pnl,
        unit="USD",
        status="OK" if net_pnl >= 0 else "CRITICAL"
    ))

    return results


def print_kpi_report(results: List[KPIResult], days: int, alert_only: bool = False) -> None:
    """Affiche le rapport KPI"""

    # Filtrer si alert_only
    if alert_only:
        results = [r for r in results if r.status in ("WARNING", "CRITICAL")]
        if not results:
            print("[OK] Tous les KPIs sont dans les seuils cibles.")
            return

    print("=" * 60)
    print(f"  RAPPORT KPIs - Derniers {days} jours")
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print()

    # En-tete du tableau
    print(f"{'KPI':<22} {'Valeur':>12} {'Statut':>10} {'Seuil':>10} {'Cible':>10}")
    print("-" * 60)

    for r in results:
        # Format valeur
        if r.unit == "%":
            val_str = f"{r.value:.1f}%"
        elif r.unit == "x":
            val_str = f"{r.value:.2f}x"
        elif r.unit == "pts":
            val_str = f"{r.value:.1f}"
        elif r.unit == "USD":
            val_str = f"${r.value:,.0f}"
        elif r.unit == "trades":
            val_str = f"{r.value:.1f}"
        else:
            val_str = f"{r.value:.2f}"

        # Status icon
        if r.status == "OK":
            status_str = "[OK]"
        elif r.status == "WARNING":
            status_str = "[WARN]"
        else:
            status_str = "[CRIT]"

        # Seuil
        if r.threshold_min is not None:
            thresh_str = f">{r.threshold_min:.1f}"
        elif r.threshold_max is not None:
            thresh_str = f"<{r.threshold_max:.1f}"
        else:
            thresh_str = "-"

        # Cible
        target_str = f"{r.target:.1f}" if r.target is not None else "-"

        print(f"{r.name:<22} {val_str:>12} {status_str:>10} {thresh_str:>10} {target_str:>10}")

    print("-" * 60)

    # Resume
    crit_count = sum(1 for r in results if r.status == "CRITICAL")
    warn_count = sum(1 for r in results if r.status == "WARNING")
    ok_count = sum(1 for r in results if r.status == "OK")

    print()
    print(f"Resume: {ok_count} OK | {warn_count} WARNING | {crit_count} CRITICAL")

    if crit_count > 0:
        print()
        print("[!] ACTIONS REQUISES:")
        for r in results:
            if r.status == "CRITICAL":
                print(f"    - {r.name}: {r.value:.1f}{r.unit} (seuil: {r.threshold_min or r.threshold_max})")


# =============================================================================
# NOUVELLES FONCTIONS - AUDIT 2025-12-27
# =============================================================================

def save_kpi_history(results: List[KPIResult], days: int) -> None:
    """
    Sauvegarde les résultats KPI dans l'historique CSV.

    AUDIT 2025-12-27 - CORRECTION #7: Historique des KPI
    """
    try:
        base_dir = Path(__file__).parent.parent
        history_file = base_dir / KPI_HISTORY_FILE
        history_file.parent.mkdir(parents=True, exist_ok=True)

        file_exists = history_file.exists()

        with open(history_file, "a", encoding="utf-8", newline="") as f:
            fieldnames = [
                "timestamp", "period_days", "win_rate", "profit_factor",
                "score_mean", "confluence_mean", "contre_trend_pct",
                "trades_per_day", "net_pnl", "critical_count", "warning_count"
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            # Construire le dict des valeurs
            row = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "period_days": days,
                "critical_count": sum(1 for r in results if r.status == "CRITICAL"),
                "warning_count": sum(1 for r in results if r.status == "WARNING"),
            }

            # Mapper les KPIs par nom
            kpi_map = {
                "Win Rate": "win_rate",
                "Profit Factor": "profit_factor",
                "Score moyen": "score_mean",
                "Confluence moyenne": "confluence_mean",
                "% Contre-trend": "contre_trend_pct",
                "Trades/jour": "trades_per_day",
                "Net P&L": "net_pnl",
            }

            for r in results:
                if r.name in kpi_map:
                    row[kpi_map[r.name]] = round(r.value, 4)

            writer.writerow(row)

        logger.debug(f"[KPI] Historique sauvegardé dans {history_file}")

    except Exception as e:
        logger.warning(f"[KPI] Erreur sauvegarde historique: {e}")


def get_previous_kpis(days_back: int = 7) -> Optional[Dict[str, float]]:
    """
    Récupère les KPIs de la période précédente pour comparaison.

    Returns:
        Dict des KPIs moyens de la période précédente, ou None si pas de données
    """
    try:
        base_dir = Path(__file__).parent.parent
        history_file = base_dir / KPI_HISTORY_FILE

        if not history_file.exists():
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

        kpi_sums: Dict[str, float] = {}
        kpi_counts: Dict[str, int] = {}

        with open(history_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = datetime.fromisoformat(row.get("timestamp", "").replace("Z", "+00:00"))
                    if ts >= cutoff:
                        continue  # On veut les données AVANT cutoff

                    # Accumuler les valeurs
                    for key in ["win_rate", "profit_factor", "score_mean",
                                "confluence_mean", "trades_per_day"]:
                        if key in row and row[key]:
                            val = float(row[key])
                            kpi_sums[key] = kpi_sums.get(key, 0) + val
                            kpi_counts[key] = kpi_counts.get(key, 0) + 1

                except Exception:
                    continue

        if not kpi_sums:
            return None

        # Calculer les moyennes
        return {k: kpi_sums[k] / kpi_counts[k] for k in kpi_sums if kpi_counts.get(k, 0) > 0}

    except Exception as e:
        logger.warning(f"[KPI] Erreur lecture historique: {e}")
        return None


def detect_degradation(
    current_results: List[KPIResult],
    previous_kpis: Optional[Dict[str, float]]
) -> List[Dict[str, Any]]:
    """
    Détecte les dégradations significatives par rapport à la période précédente.

    Returns:
        Liste des dégradations détectées
    """
    if not previous_kpis:
        return []

    degradations = []

    # Mapper les noms de KPI
    kpi_map = {
        "Win Rate": "win_rate",
        "Profit Factor": "profit_factor",
        "Score moyen": "score_mean",
        "Confluence moyenne": "confluence_mean",
        "Trades/jour": "trades_per_day",
    }

    for r in current_results:
        key = kpi_map.get(r.name)
        if not key or key not in previous_kpis:
            continue

        prev_val = previous_kpis[key]
        if prev_val <= 0:
            continue

        # Calculer le changement (positif = amélioration, négatif = dégradation)
        # Pour les KPIs où plus haut = mieux
        change_pct = (r.value - prev_val) / prev_val

        # Dégradation significative?
        if change_pct < -DEGRADATION_THRESHOLD:
            degradations.append({
                "kpi": r.name,
                "current": r.value,
                "previous": prev_val,
                "change_pct": change_pct * 100,
                "unit": r.unit,
            })

    return degradations


def send_telegram_alert(
    results: List[KPIResult],
    degradations: List[Dict[str, Any]],
    days: int
) -> None:
    """
    Envoie une alerte Telegram si des problèmes sont détectés.

    AUDIT 2025-12-27 - CORRECTION #7: Alertes Telegram automatiques
    """
    crit_count = sum(1 for r in results if r.status == "CRITICAL")
    warn_count = sum(1 for r in results if r.status == "WARNING")

    # Pas d'alerte si tout va bien
    if crit_count == 0 and warn_count == 0 and not degradations:
        return

    try:
        msg = f"📊 **Alerte KPI** ({days} jours)\n\n"

        # KPIs critiques
        if crit_count > 0:
            msg += f"🔴 **{crit_count} KPIs CRITIQUES:**\n"
            for r in results:
                if r.status == "CRITICAL":
                    if r.unit == "%":
                        val_str = f"{r.value:.1f}%"
                    elif r.unit == "x":
                        val_str = f"{r.value:.2f}x"
                    elif r.unit == "USD":
                        val_str = f"${r.value:,.0f}"
                    else:
                        val_str = f"{r.value:.1f}"
                    msg += f"  • {r.name}: {val_str}\n"
            msg += "\n"

        # KPIs en warning
        if warn_count > 0:
            msg += f"🟠 **{warn_count} KPIs en WARNING:**\n"
            for r in results:
                if r.status == "WARNING":
                    if r.unit == "%":
                        val_str = f"{r.value:.1f}%"
                    elif r.unit == "x":
                        val_str = f"{r.value:.2f}x"
                    else:
                        val_str = f"{r.value:.1f}"
                    msg += f"  • {r.name}: {val_str}\n"
            msg += "\n"

        # Dégradations
        if degradations:
            msg += f"📉 **Dégradations détectées:**\n"
            for d in degradations:
                msg += f"  • {d['kpi']}: {d['change_pct']:.1f}% ({d['previous']:.1f} → {d['current']:.1f})\n"
            msg += "\n"

        # Recommandation
        if crit_count > 0:
            msg += "⚠️ Action recommandée: Vérifier les paramètres de trading"

        send_telegram(msg)
        logger.info("[KPI] Alerte Telegram envoyée")

    except Exception as e:
        logger.warning(f"[KPI] Erreur envoi Telegram: {e}")


def run_kpi_check(
    days: int = 7,
    alert_only: bool = False,
    cron_mode: bool = False,
    journal_dir: str = "data/journal",
    data_dir: str = "data",
) -> Dict[str, Any]:
    """
    Exécute une vérification complète des KPIs.

    Args:
        days: Nombre de jours à analyser
        alert_only: Afficher uniquement les alertes
        cron_mode: Mode automatisé (sauvegarde + Telegram si alerte)
        journal_dir: Dossier des journaux de trades
        data_dir: Dossier data

    Returns:
        Dict avec les résultats de l'analyse
    """
    # Chemins
    base_dir = Path(__file__).parent.parent
    journal_path = base_dir / journal_dir
    data_path = base_dir / data_dir

    # Charger les données
    if not cron_mode:
        print(f"[INFO] Chargement des données ({days} jours)...")

    trades = load_journal_files(journal_path, days)
    proposals = load_proposals_log(data_path, days)

    if not cron_mode:
        print(f"[INFO] Trades chargés: {len(trades)}")
        print(f"[INFO] Propositions chargées: {len(proposals)}")
        print()

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "trades_count": len(trades),
        "proposals_count": len(proposals),
        "kpis": [],
        "degradations": [],
        "alerts_sent": False,
    }

    if not trades and not proposals:
        if not cron_mode:
            print("[WARN] Aucune donnée trouvée.")
        return result

    # Évaluer les KPIs
    thresholds = KPIThresholds()
    results = evaluate_kpis(trades, proposals, thresholds, days)

    result["kpis"] = [r.to_dict() for r in results]

    # Mode cron: sauvegarder et envoyer alertes
    if cron_mode:
        # Sauvegarder l'historique
        save_kpi_history(results, days)

        # Récupérer les KPIs précédents pour comparaison
        previous = get_previous_kpis(days_back=7)

        # Détecter les dégradations
        degradations = detect_degradation(results, previous)
        result["degradations"] = degradations

        # Envoyer alerte Telegram si nécessaire
        crit_count = sum(1 for r in results if r.status == "CRITICAL")
        if crit_count > 0 or degradations:
            send_telegram_alert(results, degradations, days)
            result["alerts_sent"] = True

        # Log en mode cron
        logger.info(f"[KPI] Vérification terminée: {crit_count} critiques, {len(degradations)} dégradations")
    else:
        # Mode interactif: afficher le rapport
        print_kpi_report(results, days, alert_only)

    return result


def main():
    parser = argparse.ArgumentParser(description="Monitoring KPIs quotidien")
    parser.add_argument("--days", type=int, default=7, help="Nombre de jours à analyser")
    parser.add_argument("--alert-only", action="store_true", help="Afficher uniquement les alertes")
    parser.add_argument("--journal-dir", default="data/journal", help="Dossier des fichiers journal")
    parser.add_argument("--data-dir", default="data", help="Dossier data")
    parser.add_argument(
        "--cron",
        action="store_true",
        help="Mode cron: sauvegarde historique + alertes Telegram automatiques"
    )
    args = parser.parse_args()

    # Utiliser la nouvelle fonction unifiée
    result = run_kpi_check(
        days=args.days,
        alert_only=args.alert_only,
        cron_mode=args.cron,
        journal_dir=args.journal_dir,
        data_dir=args.data_dir,
    )

    # En mode cron, afficher un résumé JSON si debug
    if args.cron:
        crit = sum(1 for k in result.get("kpis", []) if k.get("status") == "CRITICAL")
        warn = sum(1 for k in result.get("kpis", []) if k.get("status") == "WARNING")
        print(f"[KPI] {datetime.now().strftime('%Y-%m-%d %H:%M')} - "
              f"CRIT:{crit} WARN:{warn} Alertes:{result.get('alerts_sent', False)}")


if __name__ == "__main__":
    main()
