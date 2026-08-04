# -*- coding: utf-8 -*-
"""
orchestrator/trade_guards.py — gardes d'exécution extraits de `execute_trade`.

AJOUT 2026-07-30 (P2).

Pourquoi
--------
`Orchestrator.execute_trade` faisait 1327 lignes et enchaînait 36 points de
refus imbriqués dans le calcul. Impossible de savoir, en lisant le code, quels
gardes existent, dans quel ordre ils s'appliquent, ni lequel a bloqué un trade
donné. Ce module isole la *décision* de chaque garde ; l'orchestrateur garde la
*collecte du contexte* et l'application des effets.

Contrat
-------
Chaque garde a la signature demandée :

    garde(contexte: Dict[str, Any]) -> Tuple[bool, str]
                                       (autorisé, motif)

`autorisé=True` → motif vide. `autorisé=False` → motif = texte du refus.
Une fonction de garde ne loggue rien, n'envoie rien, ne mute rien : elle décide.
Les effets (log, Telegram, valeur de retour) sont décrits par `Garde` et
appliqués par l'appelant, à l'identique du code d'origine.

Contrainte respectée : AUCUN changement de comportement. L'équivalence est
prouvée par différentiel dans `tests/test_trade_guards_equivalence.py`, qui
confronte ce module au code d'origine extrait verbatim du commit dff6ec7
(voir `tools/gen_legacy_guards.py`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

Verdict = Tuple[bool, str]
OK: Verdict = (True, "")


@dataclass(frozen=True)
class Garde:
    """Décision + description des effets, tels qu'ils existaient à l'origine."""
    nom: str
    fn: Callable[[Dict[str, Any]], Verdict]
    # (niveau, message) loggué au moment du refus ; None = aucun log
    log: Optional[Callable[[Dict[str, Any], str], Tuple[str, str]]] = None
    # (texte, kind, force) envoyé sur Telegram ; None = aucun envoi
    tg: Optional[Callable[[Dict[str, Any], str], Tuple[str, str, bool]]] = None
    # valeur que `execute_trade` retournait
    retour: Any = False
    # ce garde levait une exception au lieu de retourner
    leve: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════
# Les gardes, dans l'ordre exact d'évaluation d'origine.
# La condition de chaque fonction est recopiée depuis execute_trade ;
# seules les références `self.X` / variables locales deviennent `c["X"]`.
# ══════════════════════════════════════════════════════════════════════════

def fenetre_profil_symbole(c: Dict[str, Any]) -> Verdict:
    if not c["profil_actif_maintenant"]:
        return False, "planning profiles.schedule"
    return OK


def fenetre_trading_window(c: Dict[str, Any]) -> Verdict:
    if not c["dans_trading_window"]:
        return False, "orchestrator.trading_window"
    return OK


def session_asset_manager(c: Dict[str, Any]) -> Verdict:
    if not c["session_autorisee"]:
        return False, str(c.get("session_motif", ""))
    return OK


def conflit_correlation(c: Dict[str, Any]) -> Verdict:
    if c["positions_ouvertes"] and c["conflit_correlation"]:
        return False, ", ".join(c["positions_ouvertes"])
    return OK


def cooldown_quick_reversal(c: Dict[str, Any]) -> Verdict:
    if c["now_ts"] < c["qr_cooldown_until"]:
        restant = int((c["qr_cooldown_until"] - c["now_ts"]) / 60)
        return False, str(restant)
    return OK


def reversal_cooldown(c: Dict[str, Any]) -> Verdict:
    """Anti-whipsaw : pas d'inversion juste après une perte."""
    cooldown_min = c["reversal_cooldown_min"]
    ltr = c["last_trade_result"]
    if cooldown_min > 0 and ltr is not None:
        last_dir = ltr.get("direction", "")
        last_pnl = float(ltr.get("pnl", 0))
        last_ts = float(ltr.get("close_ts", 0))
        if last_pnl < 0 and last_dir and last_dir != c["sig"] and last_ts > 0:
            ecoule_min = (c["now_ts"] - last_ts) / 60.0
            if ecoule_min < cooldown_min:
                restant = int(cooldown_min - ecoule_min)
                return False, "%s|%s|%s" % (last_dir, abs(last_pnl), restant)
    return OK


def signal_invalide(c: Dict[str, Any]) -> Verdict:
    if c["sig"] not in ("LONG", "SHORT"):
        return False, "Signal invalide"
    return OK


def proposal_absente(c: Dict[str, Any]) -> Verdict:
    prop = c["proposal"]
    if not prop or prop.get("side") != c["sig"]:
        return False, "Aucun payload compatible en mémoire."
    return OK


def anti_spam_position_ouverte(c: Dict[str, Any]) -> Verdict:
    n = c["nb_positions_symbole"]
    if n and n > 0:
        return False, str(n)
    return OK


def proposal_ttl_expiree(c: Dict[str, Any]) -> Verdict:
    if c["ttl_expiree"]:
        return False, "proposition expirée"
    return OK


def hour_filter_blacklist(c: Dict[str, Any]) -> Verdict:
    if c["blocked_hours"] and c["current_hour_utc"] in c["blocked_hours"]:
        return False, str(c["current_hour_utc"])
    return OK


def hour_filter_whitelist(c: Dict[str, Any]) -> Verdict:
    if c["allowed_hours"] and c["current_hour_utc"] not in c["allowed_hours"]:
        return False, str(c["current_hour_utc"])
    return OK


def asia_block(c: Dict[str, Any]) -> Verdict:
    if not c["asia_enabled"]:
        return OK
    if c["current_hour_utc"] in c["asia_hours"] and not (c["asia_exempt"] and c["est_crypto"]):
        return False, str(c["current_hour_utc"])
    return OK


def hard_min_score(c: Dict[str, Any]) -> Verdict:
    if c["score_agr"] < c["hard_min_score"]:
        return False, "%s|%s" % (c["score_agr"], c["hard_min_score"])
    return OK


def hard_min_confluence(c: Dict[str, Any]) -> Verdict:
    if c["confluence"] < c["hard_min_confluence"]:
        return False, "%s|%s" % (c["confluence"], c["hard_min_confluence"])
    return OK


def tracker_contradiction(c: Dict[str, Any]) -> Verdict:
    seuil = c["tracker_contradiction_seuil"]
    vote = c["tracker_vote"]
    contradit = (
        (c["sig"] == "LONG" and vote < -seuil) or
        (c["sig"] == "SHORT" and vote > seuil)
    )
    if contradit:
        return False, str(vote)
    return OK


def short_penalty(c: Dict[str, Any]) -> Verdict:
    penalite = c["short_penalty"]
    if c["sig"] == "SHORT" and penalite > 0:
        seuil = c["hard_min_score"] + penalite
        if c["score_agr"] < seuil:
            return False, "%s|%s" % (c["score_agr"], seuil)
    return OK


def direction_filter(c: Dict[str, Any]) -> Verdict:
    dirs = c["allowed_directions"]
    if dirs is not None and c["sig"] not in dirs:
        return False, str(dirs)
    return OK


def daily_loss_limit(c: Dict[str, Any]) -> Verdict:
    if not c["daily_loss_evaluable"]:
        return OK
    if c["daily_pnl_pct"] <= -c["daily_limit"]:
        return False, "%s|%s" % (c["daily_pnl_pct"], c["daily_limit"])
    return OK


def session_filter(c: Dict[str, Any]) -> Verdict:
    if not c["session_filter_actif"]:
        return OK
    if c["current_hour_utc"] in c["session_blocked_hours"] and not c["crypto_exempt"]:
        return False, str(c["current_hour_utc"])
    return OK


# ══════════════════════════════════════════════════════════════════════════
# Registre : ordre + effets, identiques à l'original.
# ══════════════════════════════════════════════════════════════════════════

def _n(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


GARDES: List[Garde] = [
    Garde(
        nom="fenetre_profil_symbole",
        fn=fenetre_profil_symbole,
        tg=lambda c, m: (
            "⏳ Fenêtre fermée pour %s (planning profiles.schedule)." % c["symbol_self"],
            "status", True),
    ),
    Garde(
        nom="fenetre_trading_window",
        fn=fenetre_trading_window,
        tg=lambda c, m: (
            "⏳ Fenêtre fermée pour %s (orchestrator.trading_window)." % c["symbol_self"],
            "status", True),
    ),
    Garde(
        nom="session_asset_manager",
        fn=session_asset_manager,
        log=lambda c, m: ("info", "[PHASE4] Trading not allowed for %s: %s" % (c["symbol_self"], m)),
        tg=lambda c, m: ("⏰ [PHASE4] Session fermée pour %s: %s" % (c["symbol_self"], m),
                         "status", True),
    ),
    Garde(
        nom="conflit_correlation",
        fn=conflit_correlation,
        log=lambda c, m: ("info", "[PHASE4] Correlation conflict for %s with %s" % (
            c["symbol_self"], c["positions_ouvertes"])),
        tg=lambda c, m: ("🔗 [PHASE4] Conflit de corrélation pour %s (positions: %s)" % (
            c["symbol_self"], m), "status", True),
    ),
    Garde(
        nom="cooldown_quick_reversal",
        fn=cooldown_quick_reversal,
        log=lambda c, m: ("warning",
                          "[COOLDOWN] %s: trade bloqué — cooldown QUICK_REVERSAL "
                          "encore %s min" % (c["symbol_self"], m)),
    ),
    Garde(
        nom="reversal_cooldown",
        fn=reversal_cooldown,
        log=lambda c, m: ("warning",
                          "[REVERSAL_COOLDOWN] %s: %s bloqué — dernier trade "
                          "était %s (perte $%.0f), cooldown encore %s min" % (
                              c["symbol_self"], c["sig"], m.split("|")[0],
                              _n(m.split("|")[1]), m.split("|")[2])),
        tg=lambda c, m: (
            "🔄 [ANTI-WHIPSAW] %s: %s bloqué\nDernier trade: %s (perte)\n"
            "Cooldown inversé: encore %s min" % (
                c["symbol_self"], c["sig"], m.split("|")[0], m.split("|")[2]),
            "status", True),
    ),
    Garde(
        nom="signal_invalide",
        fn=signal_invalide,
        leve="Signal invalide",
    ),
    Garde(
        nom="proposal_absente",
        fn=proposal_absente,
        log=lambda c, m: ("error", "[EXEC] Aucun payload compatible en mémoire."),
        tg=lambda c, m: ("⚠️ Aucun trade prêt à exécuter.", "status", False),
    ),
    Garde(
        nom="anti_spam_position_ouverte",
        fn=anti_spam_position_ouverte,
        log=lambda c, m: ("info",
                          "[ANTI_SPAM] %s: %s position(s) déjà ouverte(s) → "
                          "pas de nouvel ordre" % (c["symbol_self"], m)),
    ),
    Garde(
        nom="proposal_ttl_expiree",
        fn=proposal_ttl_expiree,
        tg=lambda c, m: ("⌛ Proposition expirée pour %s → rejet automatique." % c["symbol_self"],
                         "status", True),
    ),
    Garde(
        nom="hour_filter_blacklist",
        fn=hour_filter_blacklist,
        log=lambda c, m: ("info",
                          "[HOUR_FILTER][BLACKLIST] Trade %s bloqué - heure %sh UTC "
                          "dans blocked_hours %s" % (c["symbol"], m, c["blocked_hours"])),
        tg=lambda c, m: (
            "⏰ [HOUR FILTER][BLACKLIST] %s: Trade bloqué\nHeure actuelle: %sh UTC\n"
            "Heures bloquées: %s\n→ Trade rejeté" % (c["symbol"], m, c["blocked_hours"]),
            "status", True),
    ),
    Garde(
        nom="hour_filter_whitelist",
        fn=hour_filter_whitelist,
        log=lambda c, m: ("info",
                          "[HOUR_FILTER][WHITELIST] Trade %s bloqué - heure %sh UTC "
                          "pas dans allowed_hours %s" % (c["symbol"], m, c["allowed_hours"])),
        tg=lambda c, m: (
            "⏰ [HOUR FILTER][WHITELIST] %s: Trade bloqué\nHeure actuelle: %sh UTC\n"
            "Heures autorisées: %s\n→ Trade rejeté" % (c["symbol"], m, c["allowed_hours"]),
            "status", True),
    ),
    Garde(
        nom="asia_block",
        fn=asia_block,
        log=lambda c, m: ("warning",
                          "[ASIA_BLOCK] %s: entry bloquée — heure %sh UTC en session "
                          "Asie (00-07 UTC). Non-crypto interdit." % (c["symbol"], m)),
        tg=lambda c, m: (
            "🌙 [ASIA_BLOCK] %s: entry bloquée\nHeure: %sh UTC (session Asie)\n"
            "→ Seules les cryptos sont autorisées 00-07 UTC" % (c["symbol"], m),
            "status", True),
    ),
    Garde(
        nom="hard_min_score",
        fn=hard_min_score,
        log=lambda c, m: ("warning", "[HARD_FILTER] %s: score %.4f < %s → REJET" % (
            c["symbol"], c["score_agr"], c["hard_min_score"])),
        tg=lambda c, m: ("⛔ [QUALITÉ] %s: score %.1f trop faible (min=%s) → rejet" % (
            c["symbol"], c["score_agr"], c["hard_min_score"]), "status", True),
    ),
    Garde(
        nom="hard_min_confluence",
        fn=hard_min_confluence,
        log=lambda c, m: ("warning", "[HARD_FILTER] %s: confluence %s < %s → REJET" % (
            c["symbol"], c["confluence"], c["hard_min_confluence"])),
        tg=lambda c, m: ("⛔ [QUALITÉ] %s: confluence %s trop faible (min=%s) → rejet" % (
            c["symbol"], c["confluence"], c["hard_min_confluence"]), "status", True),
    ),
    Garde(
        nom="tracker_contradiction",
        fn=tracker_contradiction,
        log=lambda c, m: ("warning",
                          "[HARD_FILTER] %s: tracker_vote %+.2f contradictoire avec %s → REJET" % (
                              c["symbol"], c["tracker_vote"], c["sig"])),
        tg=lambda c, m: ("⛔ [QUALITÉ] %s: tracker %+.2f contradictoire avec %s → rejet" % (
            c["symbol"], c["tracker_vote"], c["sig"]), "status", True),
    ),
    Garde(
        nom="short_penalty",
        fn=short_penalty,
        log=lambda c, m: ("warning",
                          "[SHORT_PENALTY] %s: score %.4f < %.1f (base %s + penalty %s) "
                          "→ REJET SHORT" % (
                              c["symbol"], c["score_agr"],
                              c["hard_min_score"] + c["short_penalty"],
                              c["hard_min_score"], c["short_penalty"])),
        tg=lambda c, m: (
            "⬇️ [SHORT_PENALTY] %s: score %.1f trop faible pour SHORT (min=%.1f) → rejet" % (
                c["symbol"], c["score_agr"], c["hard_min_score"] + c["short_penalty"]),
            "status", True),
    ),
    Garde(
        nom="direction_filter",
        fn=direction_filter,
        log=lambda c, m: ("warning", "[DIRECTION_FILTER] %s: %s bloqué — allowed=%s" % (
            c["symbol"], c["sig"], c["allowed_directions"])),
        tg=lambda c, m: ("\U0001f6ab [DIRECTION_FILTER] %s: %s bloqué (seuls %s autorisés)" % (
            c["symbol"], c["sig"], c["allowed_directions"]), "status", True),
    ),
    Garde(
        nom="daily_loss_limit",
        fn=daily_loss_limit,
        log=lambda c, m: ("warning", "[DAILY_LOSS] %s: P&L journalier %.2f%% <= -%.0f%% → REJET" % (
            c["symbol"], c["daily_pnl_pct"] * 100, c["daily_limit"] * 100)),
        tg=lambda c, m: (
            "🛑 [DAILY LOSS] %s: Limite journalière atteinte\nP&L: %.2f%% (limite: -%.0f%%)\n"
            "Trading bloqué jusqu'à demain" % (
                c["symbol"], c["daily_pnl_pct"] * 100, c["daily_limit"] * 100),
            "alert", True),
    ),
    Garde(
        nom="session_filter",
        fn=session_filter,
        log=lambda c, m: ("warning", "[SESSION_FILTER] %s: heure %sh UTC bloquée → REJET" % (
            c["symbol"], m)),
        tg=lambda c, m: (
            "🕐 [SESSION] %s: Heure toxique %sh UTC\nTrading bloqué 0-5h et 18-23h UTC\n"
            "→ Trade rejeté" % (c["symbol"], m), "status", True),
    ),
]

# ══════════════════════════════════════════════════════════════════════════
# Dérivations de contexte — pures, partagées entre l'orchestrateur et le
# test différentiel. Elles reproduisent à l'identique les calculs qui, dans
# execute_trade, précédaient immédiatement les gardes concernés.
# ══════════════════════════════════════════════════════════════════════════

def calculer_blocked_hours(symbol: str, local_blocked: Sequence[int],
                           global_blocked: Sequence[int],
                           allowed_hours: Optional[Sequence[int]],
                           whitelist_override: Sequence[str],
                           current_hour_utc: int) -> Tuple[List[int], bool]:
    """
    Union blacklist locale ∪ globale. Seuls les symboles de
    BLACKLIST_OVERRIDE_WHITELIST peuvent soustraire leur whitelist locale.
    Renvoie (blocked_hours, exception_appliquee_maintenant).
    """
    sym_upper = (symbol or "").upper()
    if sym_upper in whitelist_override:
        allowed_set = set(allowed_hours or [])
        blocked = sorted((set(local_blocked) | set(global_blocked)) - allowed_set)
        bypass = (
            current_hour_utc in global_blocked
            and current_hour_utc in allowed_set
            and current_hour_utc not in blocked
        )
        return blocked, bypass
    return sorted(set(local_blocked) | set(global_blocked)), False


def budget_risque_effectif(equite: Optional[float], pct_vise: Optional[float],
                           cap_usd: Optional[float]
                           ) -> Tuple[Optional[float], str]:
    """
    Budget de risque REELLEMENT vise pour un trade, et sa source.

    AJOUT 2026-08-04. Deux plafonds coexistent et le plus bas gagne :
      - `risk_per_trade` du profil, en pourcentage de l'equite ;
      - `max_risk_per_trade_usd`, un plafond absolu (250 $).

    La trace [RISK_TRACE] ne comparait qu'au premier. Sur une equite de
    ~98 500 $, 0,5 % vaut ~492 $, tandis que le cap absolu vaut 250 $ : les
    lots de SP500 et NAS100 etaient donc reduits DELIBEREMENT a ~250 $ de
    risque, et la trace les denoncait a 0,51x comme « incoherents » — 4 ERROR
    le 03/08 pour un comportement conforme. Rapporte au budget effectif, le
    meme dimensionnement vaut 1,00x.

    Renvoie (budget, source). `budget` vaut None si rien n'est calculable.
    """
    budget_pct = None
    if equite and pct_vise:
        budget_pct = float(equite) * float(pct_vise)

    cap = float(cap_usd) if cap_usd else None

    if budget_pct and cap:
        if cap < budget_pct:
            return cap, "cap max_risk_per_trade_usd"
        return budget_pct, "profil"
    if cap:
        return cap, "cap max_risk_per_trade_usd"
    if budget_pct:
        return budget_pct, "profil"
    return None, "inconnu"


def calculer_liq_penalty(est_crypto: bool, current_hour_utc: int,
                         liq_hours: Sequence[int], penalite: float) -> float:
    if not est_crypto and current_hour_utc in liq_hours:
        return float(penalite)
    return 0.0


def calculer_daily_pnl_pct(floating_pnl: float, balance: float) -> float:
    return floating_pnl / balance if balance > 0 else 0


def calculer_crypto_exempt(est_crypto: bool, asset_override: Dict[str, Any]) -> bool:
    return est_crypto and not asset_override.get("avoid_low_liquidity", False)


PAR_NOM: Dict[str, Garde] = {g.nom: g for g in GARDES}
ORDRE: List[str] = [g.nom for g in GARDES]


@dataclass
class Refus:
    """Ce qu'un garde a décidé, et les effets à appliquer."""
    garde: str
    motif: str
    log: Optional[Tuple[str, str]] = None
    telegram: Optional[Tuple[str, str, bool]] = None
    retour: Any = False
    leve: Optional[str] = None


def evaluer(noms: Sequence[str], contexte: Dict[str, Any]) -> Optional[Refus]:
    """
    Évalue les gardes `noms` dans l'ordre du registre. Renvoie None si tous
    autorisent, sinon le `Refus` du premier qui bloque (court-circuit, comme
    les `return` d'origine).
    """
    for nom in noms:
        garde = PAR_NOM[nom]
        autorise, motif = garde.fn(contexte)
        if autorise:
            continue
        return Refus(
            garde=garde.nom,
            motif=motif,
            log=garde.log(contexte, motif) if garde.log else None,
            telegram=garde.tg(contexte, motif) if garde.tg else None,
            retour=garde.retour,
            leve=garde.leve,
        )
    return None
