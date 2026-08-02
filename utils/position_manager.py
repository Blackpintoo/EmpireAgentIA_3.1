# utils/position_manager.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, List, Tuple
import os
import json
import math
import time
import threading
from datetime import datetime, timezone

import pandas as pd

# =============================================================================
# GLOBAL LOCK pour éviter les opérations MT5 simultanées (fix 2025-12-17)
# Problème: Quand plusieurs cryptos atteignent TP1 en même temps, les closes
#           partiels peuvent échouer ou ne pas être enregistrés correctement.
# Solution: Lock global + délai minimum entre opérations MT5.
# =============================================================================
_MT5_OPERATION_LOCK = threading.Lock()
_LAST_MT5_OPERATION_TIME: float = 0.0
_MT5_OPERATION_DELAY_SEC: float = 1.5  # Délai minimum entre opérations MT5

# Alias pour compatibilité
_PARTIAL_CLOSE_LOCK = _MT5_OPERATION_LOCK
_PARTIAL_UNSUPPORTED_LOGGED = False  # FIX 2026-07-26 (P3)
_LAST_PARTIAL_CLOSE_TIME: float = 0.0
_PARTIAL_CLOSE_DELAY_SEC: float = 2.0  # Délai spécifique pour closes partiels

try:
    import MetaTrader5 as mt5  # type: ignore
except Exception:
    mt5 = None

try:
    from utils.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)

try:
    from utils.mt5_client import MT5Client
except Exception:
    MT5Client = None  # type: ignore
# ------------------------------- helpers --------------------------------
def _canon_to_broker(sym: str) -> str:
        """Convertit un symbole canonique vers le symbole broker si nécessaire."""
        s = (sym or "").upper()
        # Pas de mapping nécessaire actuellement
        return s

def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        v = float(x)
        if pd.isna(v):
            return default
        return v
    except Exception:
        return default

def _atr_from_rates(df: pd.DataFrame, period: int) -> Optional[float]:
    try:
        if df is None or df.empty:
            return None
        if not all(c in df.columns for c in ("high", "low", "close")):
            return None
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=int(period)).mean().iloc[-1]
        if pd.isna(atr):
            return None
        return float(atr)
    except Exception:
        return None

def _compute_rr(side: str, entry: float, sl: float, tp: float, price: float) -> Optional[float]:
    """R multiple courant par rapport au SL/TP proposés (approx)."""
    try:
        if side == "BUY":
            risk = max(entry - sl, 1e-9)
            reward_now = price - entry
        else:
            risk = max(sl - entry, 1e-9)
            reward_now = entry - price
        return float(reward_now / risk)
    except Exception:
        return None

def _round_to_step(x: float, step: float) -> float:
    if step <= 0:
        return float(x)
    return math.floor((x + 1e-12) / step) * step

# ------------------------------- state ----------------------------------
_STATE_PATH = os.path.join("data", "pm_state.json")

# FIX 2026-08-02 : nombre de lectures MT5 consecutives sans un ticket avant de
# le declarer ferme. A 20 s de cycle, 3 lectures = ~60 s de confirmation.
_ABSENCES_AVANT_CLOTURE = int(os.environ.get("EMPIRE_PM_ABSENCES", "3") or 3)

# FIX 2026-08-02 : nombre de cycles d'attente du deal MT5 avant d'ecrire quand
# meme la ligne MFE, marquee non resolue (~5 min a 20 s de cycle).
_MFE_ATTENTE_MAX_CYCLES = int(os.environ.get("EMPIRE_MFE_ATTENTE", "15") or 15)

# FIX 2026-08-02 : paliers de backoff (minutes) apres un refus de cloture.
_BACKOFF_CLOTURE_MIN = (1, 2, 5, 15, 30, 60)

# Verrou thread-safe pour accès concurrent au fichier d'état
_FILE_LOCK = threading.Lock()

def _load_state() -> Dict[str, Any]:
    with _FILE_LOCK:
        try:
            if os.path.exists(_STATE_PATH):
                with open(_STATE_PATH, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
            logger.warning(f"[STATE] Erreur I/O {_STATE_PATH}: {e}")
    return {}

def _save_state(state: Dict[str, Any]) -> None:
    with _FILE_LOCK:
        _ecrire_etat(state)


def _ecrire_etat(state: Dict[str, Any]) -> None:
    """Écriture atomique. À appeler verrou déjà tenu."""
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        tmp_path = _STATE_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, _STATE_PATH)
    except (IOError, OSError) as e:
        logger.warning(f"[STATE] Erreur I/O écriture {_STATE_PATH}: {e}")


def fusionner_etat(maj: Optional[Dict[str, Any]] = None,
                   suppressions: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """
    FIX 2026-08-02 : écriture par FUSION, relue depuis le disque sous verrou.

    Le défaut corrigé : `self._state` était chargé UNE FOIS à la construction
    du PositionManager, et `_save_state(self._state)` réécrivait le fichier
    ENTIER à partir de cette copie mémoire. Avec 12 orchestrateurs, donc 12
    PositionManager partageant `data/pm_state.json`, chaque sauvegarde
    écrasait les entrées créées entre-temps par les autres symboles.

    Séquence observée en production :
      - PM(SP500) ouvre 1690929973  -> sauvegarde {…, SP500:1690929973}
      - PM(BTCUSD), dont la copie mémoire date du démarrage et ignore cette
        entrée, ouvre sa position -> sauvegarde {…, BTCUSD:…}
        => l'entrée SP500 disparaît, sans aucune trace dans les logs.

    Chaque appelant n'affirme désormais que SES clés ; tout le reste du
    fichier est préservé. Renvoie l'état complet après fusion.
    """
    with _FILE_LOCK:
        try:
            disque: Dict[str, Any] = {}
            if os.path.exists(_STATE_PATH):
                with open(_STATE_PATH, "r", encoding="utf-8") as f:
                    disque = json.load(f) or {}
        except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
            logger.warning("[STATE] Relecture impossible avant fusion (%s) — "
                           "on repart de l'état mémoire pour ne rien perdre", e)
            disque = {}
        if maj:
            disque.update(maj)
        for cle in (suppressions or ()):
            disque.pop(cle, None)
        _ecrire_etat(disque)
        return disque


# ----------------------------- Market Hours -------------------------------
# Horaires de fermeture des marchés (heure UTC)
# Format: {symbole_pattern: (heure_fermeture, minute_fermeture, jours_trading)}
# jours_trading: 0=Lundi, 4=Vendredi, None=24/7
MARKET_CLOSE_TIMES = {
    # Indices - ferment à 21:00 UTC (22:00 CET) du lundi au vendredi
    "GER40": (21, 0, [0, 1, 2, 3, 4]),      # DAX
    "DJ30": (21, 0, [0, 1, 2, 3, 4]),       # Dow Jones
    "NAS100": (21, 0, [0, 1, 2, 3, 4]),     # Nasdaq
    "US500": (21, 0, [0, 1, 2, 3, 4]),      # S&P 500
    # Forex - ferme vendredi 21:00 UTC (pas de week-end)
    "EURUSD": (21, 0, [4]),                 # Ferme vendredi soir
    "GBPUSD": (21, 0, [4]),
    "USDJPY": (21, 0, [4]),
    "AUDUSD": (21, 0, [4]),
    # Matières premières
    "CL-OIL": (21, 0, [0, 1, 2, 3, 4]),     # Pétrole
    "XAUUSD": (21, 0, [4]),                 # Or - ferme vendredi
    "XAGUSD": (21, 0, [4]),                 # Argent - ferme vendredi
    # Cryptos - 24/7, pas de fermeture
}

# ----------------------------- dataclasses -------------------------------
@dataclass
class PMBreakEven:
    rr: float = 1.0
    offset_points: float = 0.0

@dataclass
class PMPartial:
    rr: float
    close_frac: float

@dataclass
class PMTrailing:
    enabled: bool = True
    start_rr: float = 1.2
    atr_timeframe: str = "M5"
    atr_period: int = 14
    atr_mult: float = 1.6
    lock_rr: float = 0.2  # ne jamais revenir sous +lock_rr


# ----------------------------- main class --------------------------------
class PositionManager:
    """
    Gère BE / Partials / Trailing pour les positions ouvertes du symbole.
    - Lecture des paramètres depuis profiles.yaml: profiles.<SYMBOL>.orchestrator.position_manager
    - Persiste l’état par ticket dans data/pm_state.json pour éviter les répétitions
    - Utilise MT5Client si dispo, sinon fallback MetaTrader5 direct
    """

    def __init__(self, mt5_client: Any, symbol: str, profile: Dict[str, Any], notifier=None):
        self.mt5 = mt5_client
        self.symbol_canon = symbol
        self.profile = profile
        self._notifier = notifier
        # wrapper de notification sécurisé
        def _notify(tag: str, payload: dict):
            try:
                if callable(self._notifier):
                    self._notifier(tag, payload)
            except Exception:
                pass
        self._notify = _notify
        # persistance des positions ouvertes détectées
        self._open_state_path = os.path.join("data", "open_positions.json")
        self.mt5c = mt5_client
        inst = (self.profile.get("instrument") or {}) if isinstance(self.profile, dict) else {}
        self.broker_symbol = inst.get("broker_symbol") or _canon_to_broker(self.symbol_canon)
        self.point = float(inst.get("point", 0.01) or 0.01)
        self.min_lot = float(inst.get("min_lot", 0.01) or 0.01)
        self.lot_step = float(inst.get("lot_step", 0.01) or 0.01)
        self._state: Dict[str, Any] = _load_state()
        # FIX 2026-08-02 : compte les lectures consecutives sans un ticket.
        self._absences: Dict[str, int] = {}
        # FIX 2026-08-02 : clotures dont le deal MT5 n'est pas encore publie.
        self._clotures_en_attente: Dict[int, Dict[str, Any]] = {}
        # FIX 2026-08-02 : backoff par ticket sur les clotures refusees.
        self._echecs_cloture: Dict[int, Dict[str, Any]] = {}
        pm_cfg = ((self.profile.get("orchestrator") or {}).get("position_manager") or {}) if isinstance(self.profile, dict) else {}
        self.enabled = bool(pm_cfg.get("enabled", True))
        be_cfg = pm_cfg.get("break_even") or {}
        self.be = PMBreakEven(
            rr=float(be_cfg.get("rr", 1.0)),
            offset_points=float(be_cfg.get("offset_points", 0.0)),
        )
        partials_cfg = pm_cfg.get("partials") or []
        self.partials = [
            PMPartial(rr=float(p.get("rr")), close_frac=float(p.get("close_frac", 0.5)))
            for p in partials_cfg
            if isinstance(p, dict) and p.get("rr") is not None
        ]
        self.partials.sort(key=lambda p: p.rr)
        trail_cfg = pm_cfg.get("trailing") or {}
        self.trailing = PMTrailing(
            enabled=bool(trail_cfg.get("enabled", True)),
            start_rr=float(trail_cfg.get("start_rr", 1.2)),
            atr_timeframe=str(trail_cfg.get("atr_timeframe", "M5")),
            atr_period=int(trail_cfg.get("atr_period", 14)),
            atr_mult=float(trail_cfg.get("atr_mult", 1.6)),
            lock_rr=float(trail_cfg.get("lock_rr", 0.2)),
        )

        # Configuration fermeture avant clôture marché
        close_before_cfg = pm_cfg.get("close_before_market_close") or {}
        self.close_before_enabled = bool(close_before_cfg.get("enabled", True))
        self.close_before_minutes = int(close_before_cfg.get("minutes_before", 30))

        # FIX 2026-02-24: Timeout max par position (Directive 4)
        self.max_duration_minutes = int(pm_cfg.get("max_duration_minutes", 0) or 0)
        self.timeout_only_if_losing = bool(pm_cfg.get("timeout_only_if_losing", False))

    def _load_open_state(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self._open_state_path):
                with open(self._open_state_path, encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_open_state(self, st: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._open_state_path), exist_ok=True)
            with open(self._open_state_path, "w", encoding="utf-8") as f:
                json.dump(st, f)
        except Exception:
            pass
    # ---------------------------- MT5 helpers ----------------------------
    def _positions_get(self) -> List[Any]:
        # FIX 2026-02-24: Fallback élargi avec filtrage manuel (Directive 3 — Étape D)
        try:
            if self.mt5c and hasattr(self.mt5c, "positions_get"):
                poss = self.mt5c.positions_get(symbol=self.broker_symbol)
                if poss is not None and len(list(poss)) > 0:
                    result = list(poss)
                    logger.debug(f"[PM_DIAG] _positions_get via mt5c: {len(result)} pos pour {self.broker_symbol}")
                    return result
        except Exception:
            pass
        try:
            if mt5:
                poss = mt5.positions_get(symbol=self.broker_symbol)
                if poss is not None and len(poss) > 0:
                    logger.debug(f"[PM_DIAG] _positions_get via mt5 direct: {len(poss)} pos pour {self.broker_symbol}")
                    return list(poss)
        except Exception:
            pass
        # FIX 2026-02-24: Fallback sans filtre symbole + filtrage manuel
        try:
            if mt5:
                all_poss = mt5.positions_get()
                if all_poss:
                    _bs = self.broker_symbol.upper()
                    _sc = self.symbol_canon.upper()
                    filtered = [p for p in all_poss if getattr(p, "symbol", "").upper() in (_bs, _sc)]
                    logger.debug(f"[PM_DIAG] _positions_get fallback sans filtre: {len(all_poss)} total, {len(filtered)} matchés ({_bs}/{_sc})")
                    return filtered
        except Exception:
            pass
        return []

    def _modify_sl_tp(self, ticket: int, sl: Optional[float], tp: Optional[float]) -> bool:
        """
        Modifie SL/TP d'une position avec lock global.
        Fix 2025-12-17: Évite les modifications simultanées sur plusieurs positions.
        """
        global _LAST_MT5_OPERATION_TIME

        with _MT5_OPERATION_LOCK:
            # Petit délai entre opérations MT5
            now = time.time()
            elapsed = now - _LAST_MT5_OPERATION_TIME
            if elapsed < _MT5_OPERATION_DELAY_SEC:
                wait_time = _MT5_OPERATION_DELAY_SEC - elapsed
                time.sleep(wait_time)

            try:
                if self.mt5c and hasattr(self.mt5c, "modify_position_sl_tp"):
                    result = bool(self.mt5c.modify_position_sl_tp(ticket=ticket, sl=sl, tp=tp))
                    if result:
                        _LAST_MT5_OPERATION_TIME = time.time()
                    return result
            except Exception:
                pass

            # fallback natif
            try:
                if not mt5:
                    return False
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": int(ticket),
                    "sl": sl if sl else 0.0,
                    "tp": tp if tp else 0.0,
                    "deviation": int((self.profile.get("deviation") or 30)),
                }
                res = mt5.order_send(request)
                result = bool(res) and int(getattr(res, "retcode", -1)) == getattr(mt5, "TRADE_RETCODE_DONE", 10009)
                if result:
                    _LAST_MT5_OPERATION_TIME = time.time()
                return result
            except Exception:
                return False

    def _close_partial(self, ticket: int, volume_close: float) -> bool:
        """
        Ferme partiellement une position avec lock global et délai.
        Fix 2025-12-17: Évite les closes simultanés sur plusieurs cryptos.
        FIX 2026-03-01: Enregistre le deal_ticket dans pm_state pour le TradeOutcomeTracker.
        """
        global _LAST_PARTIAL_CLOSE_TIME

        # Acquérir le lock global pour éviter les closes simultanés
        with _PARTIAL_CLOSE_LOCK:
            # Vérifier le délai depuis le dernier close
            now = time.time()
            elapsed = now - _LAST_PARTIAL_CLOSE_TIME
            if elapsed < _PARTIAL_CLOSE_DELAY_SEC:
                wait_time = _PARTIAL_CLOSE_DELAY_SEC - elapsed
                logger.info(f"[PM] Attente {wait_time:.1f}s avant close partial (anti-collision)")
                time.sleep(wait_time)

            # FIX 2026-02-24: Log AVANT tentative de fermeture (Directive 3 — Étape E)
            logger.info(f"[PM_PARTIAL_EXEC] ticket={ticket} vol_close={volume_close:.4f} symbol={self.broker_symbol}")

            # Exécuter le close partial
            result = False
            try:
                if self.mt5c and hasattr(self.mt5c, "close_partial"):
                    result = bool(self.mt5c.close_partial(ticket=ticket, volume=volume_close))
                    if result:
                        _LAST_PARTIAL_CLOSE_TIME = time.time()
                        logger.info(f"[PM_PARTIAL_EXEC] ticket={ticket} SUCCÈS via mt5c")
                        self._record_partial_deal_ticket(ticket, volume_close)
                        return True
            except Exception as e:
                logger.warning(f"[PM] close_partial via mt5c failed: {e}")

            # fallback natif: position_close_partially
            try:
                if mt5 and hasattr(mt5, "position_close_partial"):
                    r = mt5.position_close_partial(ticket, volume_close)
                    result = bool(r)
                    if result:
                        _LAST_PARTIAL_CLOSE_TIME = time.time()
                        logger.info(f"[PM_PARTIAL_EXEC] ticket={ticket} SUCCÈS via mt5 natif")
                        self._record_partial_deal_ticket(ticket, volume_close)
                    else:
                        _err = mt5.last_error() if hasattr(mt5, "last_error") else "N/A"
                        logger.warning(f"[PM_PARTIAL_EXEC] ticket={ticket} ÉCHEC via mt5 natif: {_err}")
                    return result
            except Exception as e:
                logger.warning(f"[PM] close_partial via mt5 native failed: {e}")

            # FIX 2026-07-26 (P3): aucune primitive de fermeture partielle n'existe.
            # MT5Client n'expose pas close_partial et l'API MetaTrader5 n'a pas de
            # position_close_partial. Cette fonction renvoyait False en silence depuis
            # l'origine : 0 partiel sur 3220 positions. On le dit clairement une fois.
            global _PARTIAL_UNSUPPORTED_LOGGED
            if not _PARTIAL_UNSUPPORTED_LOGGED:
                _PARTIAL_UNSUPPORTED_LOGGED = True
                logger.error(
                    "[PM] FERMETURE PARTIELLE INDISPONIBLE : ni MT5Client.close_partial "
                    "ni mt5.position_close_partial n'existent. Les paliers 'partials' "
                    "configures ne seront JAMAIS executes. Retirer la config ou "
                    "implementer la primitive."
                )
            return False

    def _record_partial_deal_ticket(self, position_ticket: int, volume_closed: float) -> None:
        """
        Après un partial close réussi, cherche le deal_ticket correspondant
        dans l'historique MT5 récent et l'enregistre dans pm_state.

        FIX 2026-03-01: Permet au TradeOutcomeTracker de détecter les partiels
        et d'éviter le double-comptage.
        """
        try:
            if not mt5:
                return
            from datetime import timedelta, timezone as _tz
            _now = datetime.now(_tz.utc)
            _start = _now - timedelta(minutes=5)
            deals = mt5.history_deals_get(_start, _now)
            if not deals:
                return

            # Chercher le deal de clôture le plus récent pour ce ticket
            for deal in reversed(list(deals)):
                if (int(getattr(deal, "position_id", 0)) == int(position_ticket)
                        and int(getattr(deal, "entry", 0)) == 1):
                    deal_id = int(getattr(deal, "ticket", getattr(deal, "order", 0)))
                    deal_volume = float(getattr(deal, "volume", 0.0))
                    deal_profit = float(getattr(deal, "profit", 0.0))

                    # Enregistrer dans pm_state
                    st = self._get_tstate(position_ticket)
                    if "partial_deal_tickets" not in st:
                        st["partial_deal_tickets"] = []
                    if deal_id not in st["partial_deal_tickets"]:
                        st["partial_deal_tickets"].append(deal_id)
                    # Tracker le volume fermé cumulé
                    st["volume_closed"] = round(
                        st.get("volume_closed", 0.0) + deal_volume, 6
                    )
                    self._set_tstate(position_ticket, st)

                    logger.info(
                        f"[PM_PARTIAL] Recorded deal_ticket={deal_id} for position={position_ticket} "
                        f"vol={deal_volume} profit={deal_profit:.2f} "
                        f"total_closed={st['volume_closed']:.4f}"
                    )
                    return

        except Exception as e:
            logger.debug(f"[PM_PARTIAL] Erreur enregistrement deal_ticket: {e}")

    def _get_rates(self, timeframe: str, count: int = 200) -> Optional[pd.DataFrame]:
        try:
            if self.mt5c and hasattr(self.mt5c, "get_rates"):
                bars = self.mt5c.get_rates(self.broker_symbol, timeframe, count=count)
                if bars:
                    return pd.DataFrame(bars)
        except Exception:
            pass
        try:
            if mt5:
                tf_map = {
                    "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
                    "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1
                }
                tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_M5)
                rates = mt5.copy_rates_from_pos(self.broker_symbol, tf, 0, count)
                if rates:
                    return pd.DataFrame(list(rates))
        except Exception:
            pass
        return None

    # ---------------------------- Market Close helpers ----------------------------
    def _get_market_close_time(self) -> Optional[Tuple[int, int, List[int]]]:
        """Retourne (heure, minute, jours) de fermeture pour ce symbole, ou None si 24/7."""
        sym = self.symbol_canon.upper()
        return MARKET_CLOSE_TIMES.get(sym)

    def _is_near_market_close(self) -> bool:
        """Vérifie si on est dans les X minutes avant la fermeture du marché."""
        if not self.close_before_enabled:
            return False

        close_info = self._get_market_close_time()
        if close_info is None:
            return False  # Marché 24/7 (cryptos)

        close_hour, close_minute, trading_days = close_info
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # 0=Lundi, 4=Vendredi

        # Vérifier si aujourd'hui est un jour où le marché ferme
        if weekday not in trading_days:
            return False

        # Calculer l'heure de fermeture
        close_time = now.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)

        # Calculer la différence en minutes
        diff_seconds = (close_time - now).total_seconds()
        diff_minutes = diff_seconds / 60

        # Si on est dans la fenêtre de fermeture (entre 0 et close_before_minutes avant)
        return 0 <= diff_minutes <= self.close_before_minutes

    def _cloture_en_backoff(self, ticket: int) -> bool:
        """
        FIX 2026-08-02 : vrai si une nouvelle tentative de cloture doit etre
        differee pour ce ticket.

        Constate en production : le ticket SP500 1690929973 a genere
        10 659 lignes de log en une journee. Toutes les 20 s, le timeout de
        duree declenchait une fermeture, le broker repondait "Market closed",
        et le cycle recommencait a l'identique. Un marche ferme ne rouvre pas
        parce qu'on insiste : reessayer 3 fois par minute n'apporte rien et
        noie les logs ou l'on cherche les vrais incidents.
        """
        info = self._echecs_cloture.get(int(ticket))
        return bool(info and time.time() < info.get("prochain_essai", 0.0))

    def _noter_echec_cloture(self, ticket: int, motif: str) -> None:
        """Recule la prochaine tentative : 1, 2, 5, 15, 30 puis 60 min."""
        info = self._echecs_cloture.setdefault(int(ticket), {"essais": 0})
        info["essais"] += 1
        delai = _BACKOFF_CLOTURE_MIN[min(info["essais"] - 1, len(_BACKOFF_CLOTURE_MIN) - 1)]
        info["prochain_essai"] = time.time() + delai * 60.0
        info["motif"] = motif
        logger.warning(
            "[PM] %s ticket=%s : cloture refusee (%s). Tentative %d ; "
            "prochaine dans %d min.",
            self.symbol_canon, ticket, motif, info["essais"], delai)

    def _close_position_full(self, ticket: int, volume: float, side: str) -> bool:
        """Ferme entièrement une position."""
        try:
            if not mt5:
                return False

            # FIX 2026-08-02 : ne pas marteler un broker qui vient de refuser.
            if self._cloture_en_backoff(ticket):
                logger.debug("[PM] %s ticket=%s : cloture differee (backoff)",
                             self.symbol_canon, ticket)
                return False

            # Déterminer le type d'ordre inverse
            if side == "BUY":
                order_type = mt5.ORDER_TYPE_SELL
                tick = mt5.symbol_info_tick(self.broker_symbol)
                price = tick.bid if tick else 0
            else:
                order_type = mt5.ORDER_TYPE_BUY
                tick = mt5.symbol_info_tick(self.broker_symbol)
                price = tick.ask if tick else 0

            if not price or price <= 0:
                logger.warning(f"[PM] Cannot get price to close position {ticket}")
                return False

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": int(ticket),
                "symbol": self.broker_symbol,
                "volume": float(volume),
                "type": order_type,
                "price": price,
                "deviation": 30,
                "magic": 0,
                "comment": "close_before_market",
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC,
            }

            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[PM] Position {ticket} closed before market close")
                self._echecs_cloture.pop(int(ticket), None)   # backoff leve
                return True
            else:
                err = result.comment if result else "Unknown"
                self._noter_echec_cloture(ticket, str(err))
                return False

        except Exception as e:
            logger.warning(f"[PM] Error closing position {ticket}: {e}")
            return False

    def _close_positions_before_market_close(self) -> int:
        """Ferme toutes les positions si on est proche de la fermeture du marché.
        Retourne le nombre de positions fermées."""
        if not self._is_near_market_close():
            return 0

        positions = self._positions_get()
        if not positions:
            return 0

        closed_count = 0
        close_info = self._get_market_close_time()
        close_hour, close_minute, _ = close_info or (0, 0, [])

        for p in positions:
            try:
                ticket = int(getattr(p, "ticket", 0) or 0)
                volume = float(getattr(p, "volume", 0) or 0)
                side = "BUY" if int(getattr(p, "type", 0)) == 0 else "SELL"
                profit = float(getattr(p, "profit", 0) or 0)

                if ticket <= 0 or volume <= 0:
                    continue

                logger.info(
                    f"[PM] Closing {self.symbol_canon} position {ticket} before market close "
                    f"({close_hour}:{close_minute:02d} UTC). Current P&L: {profit:+.2f}"
                )

                if self._close_position_full(ticket, volume, side):
                    closed_count += 1
                    self._notify("CLOSE_TRADE", {
                        "symbol": self.symbol_canon,
                        "ticket": ticket,
                        "result": "MARKET_CLOSE",
                        "pnl_ccy": f"{profit:+.2f}",
                        "pnl_pips": "N/A",
                        "duration": "N/A",
                        "rr": "N/A",
                        "mfe": "N/A",
                        "mae": "N/A",
                    })

            except Exception as e:
                logger.warning(f"[PM] Error processing position for market close: {e}")
                continue

        if closed_count > 0:
            logger.info(f"[PM] Closed {closed_count} position(s) before market close for {self.symbol_canon}")

        return closed_count

    _MFE_COLONNES = ["ts_utc", "symbol", "ticket", "side", "entry", "exit",
                     "pnl", "mfe_r", "mae_r", "sl_orig", "be_done",
                     "trail_active", "resolu"]

    def _mfe_chemin(self) -> str:
        # FIX 2026-07-30 (P5): journal cloisonne par compte MT5.
        from utils.account_scope import chemin_donnees as _chemin_donnees
        return str(_chemin_donnees("trade_mfe.csv"))

    def _mfe_migrer_entete(self, path: str) -> None:
        """
        FIX 2026-08-02 : ajoute la colonne `resolu` a un journal existant.
        Migration unique, non destructive : les lignes deja ecrites sont
        conservees et marquees resolu=False, puisqu'on ne peut pas savoir
        apres coup si leur P&L etait connu au moment de l'ecriture.
        """
        import csv, os
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", newline="", encoding="utf-8") as f:
                lignes = list(csv.reader(f))
            if not lignes or lignes[0] == self._MFE_COLONNES:
                return
            corps = [l + [""] * (len(self._MFE_COLONNES) - 1 - len(l)) + ["False"]
                     for l in lignes[1:] if l]
            tmp = path + ".tmp"
            with open(tmp, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(self._MFE_COLONNES)
                w.writerows(corps)
            os.replace(tmp, path)
            logger.info("[PM] trade_mfe.csv migre : colonne 'resolu' ajoutee "
                        "(%d lignes existantes marquees non resolues)", len(corps))
        except Exception as e:
            logger.debug("[PM] migration trade_mfe.csv impossible: %s", e)

    def _log_mfe_row(self, ticket, side, entry, px_close, pnl, mfe, mae, st,
                     resolu: bool = True) -> None:
        """
        Journalise MFE/MAE a la CLOTURE, pour arbitrer partiels / break-even /
        trailing sur donnees plutot qu'a l'aveugle.

        FIX 2026-08-02 : la ligne etait ecrite des la detection de la cloture,
        avant que MT5 n'ait publie le deal correspondant. Consequence mesuree
        sur le journal de production : `pnl` valait 0.0 sur 8 lignes sur 8, et
        `exit` etait vide sur 5 sur 8. Le journal documentait la trajectoire
        mais pas l'issue — donc inutilisable pour decider d'un break-even.
        L'ecriture est desormais differee tant que le deal n'est pas trouve
        (voir _resoudre_clotures_en_attente) ; `resolu` dit si la ligne
        s'appuie sur un deal reellement lu.
        """
        try:
            import csv, os
            from datetime import datetime, timezone as _tz
            path = self._mfe_chemin()
            os.makedirs(os.path.dirname(path) or "data", exist_ok=True)
            new_file = not os.path.exists(path)
            if not new_file:
                self._mfe_migrer_entete(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(self._MFE_COLONNES)
                w.writerow([datetime.now(_tz.utc).isoformat(), self.symbol_canon, ticket, side,
                            entry, px_close if px_close is not None else "",
                            round(float(pnl), 2) if pnl is not None else "",
                            mfe if mfe is not None else "",
                            mae if mae is not None else "",
                            st.get("sl_orig", ""), st.get("be_done", ""),
                            st.get("trail_active", ""), bool(resolu)])
        except Exception as e:
            logger.debug(f"[PM] _log_mfe_row failed: {e}")

    def _resoudre_clotures_en_attente(self, deals) -> None:
        """
        FIX 2026-08-02 : rejoue les clotures dont le deal n'etait pas encore
        publie par MT5 au moment ou on les a detectees. Au-dela de
        _MFE_ATTENTE_MAX_CYCLES tentatives (~5 min a 20 s de cycle), la ligne
        est ecrite quand meme avec resolu=False : mieux vaut une ligne
        signalee incomplete qu'un trade absent du journal.
        """
        if not self._clotures_en_attente:
            return
        for tk in list(self._clotures_en_attente.keys()):
            ctx = self._clotures_en_attente[tk]
            ctx["essais"] = ctx.get("essais", 0) + 1
            tk_deals = [d for d in (deals or [])
                        if int(getattr(d, "position_id", 0) or 0) == int(tk)
                        or int(getattr(d, "order", 0) or 0) == int(tk)]
            pnl = sum(float(getattr(d, "profit", 0.0) or 0.0) for d in tk_deals) if tk_deals else None
            px = next((float(getattr(d, "price") or 0) for d in tk_deals
                       if getattr(d, "price", None)), None)
            if tk_deals and px is not None:
                self._log_mfe_row(tk, ctx["side"], ctx["entry"], px, pnl,
                                  ctx["mfe"], ctx["mae"], ctx["st"], resolu=True)
                logger.info("[PM] %s ticket=%s : P&L resolu apres %d cycle(s) "
                            "-> %.2f", self.symbol_canon, tk, ctx["essais"], pnl or 0.0)
                self._clotures_en_attente.pop(tk, None)
            elif ctx["essais"] >= _MFE_ATTENTE_MAX_CYCLES:
                self._log_mfe_row(tk, ctx["side"], ctx["entry"], None, None,
                                  ctx["mfe"], ctx["mae"], ctx["st"], resolu=False)
                logger.warning("[PM] %s ticket=%s : aucun deal trouve apres %d "
                               "cycles, ligne MFE ecrite comme NON RESOLUE",
                               self.symbol_canon, tk, ctx["essais"])
                self._clotures_en_attente.pop(tk, None)

    # ---------------------------- state per ticket -----------------------
    def _tk(self, ticket: int) -> str:
        return f"{self.symbol_canon}:{ticket}"

    def _get_tstate(self, ticket: int) -> Dict[str, Any]:
        return self._state.get(self._tk(ticket), {
            "partials_done": [], "be_done": False, "trail_active": False,
            # FIX 2026-07-26 (P3): SL d'origine fige a l'ouverture. Toutes les mesures
            # de R doivent s'y referer : une fois le SL deplace au break-even, le calcul
            # sur le SL courant donne risk ~ 0 et fait exploser le R.
            "sl_orig": None, "mfe_r": None, "mae_r": None,
        })

    def _set_tstate(self, ticket: int, st: Dict[str, Any]) -> None:
        # FIX 2026-08-02 : fusion au lieu d'écrasement global (voir
        # fusionner_etat). On resynchronise la copie mémoire sur le disque.
        cle = self._tk(ticket)
        self._state[cle] = st
        self._state = fusionner_etat(maj={cle: st})

    # ---------------------------- core rules -----------------------------
    def _apply_break_even(
        self,
        side: str,
        entry: float,
        sl: float,
        price: float,
        *,
        force: bool = False,
    ) -> Optional[float]:
        """
        Retourne un nouveau SL si le passage à BE est requis, sinon None.
        """
        # FIX 2026-07-26 (P3): le parametre `force` court-circuitait le seuil be.rr des
        # qu'un partiel reussissait, rendant be.rr lettre morte. Le seuil est desormais
        # toujours respecte. `force` est conserve pour compatibilite d'appel mais ignore.
        rr = _compute_rr(side, entry, sl, tp=entry, price=price)  # TP fictif=entry pour calculer R atteint
        if rr is None or rr < float(self.be.rr):
            return None
        offs = float(self.be.offset_points or 0.0) * self.point
        return (entry + offs) if side == "BUY" else (entry - offs)

    def _apply_partials(self, ticket: int, volume: float, rr_now: float) -> Tuple[float, bool]:
        """
        Tente de fermer des portions selon partials[]. Met à jour l'état. Retourne (volume restant, partial déclenché).
        """
        st = self._get_tstate(ticket)
        done = set(st.get("partials_done", []))
        vol_left = float(volume)
        partial_hit = False

        for p in self.partials:
            if p.rr in done:
                continue
            if rr_now >= float(p.rr):
                # calc vol à fermer
                to_close = max(0.0, float(p.close_frac) * vol_left)
                to_close = _round_to_step(to_close, self.lot_step)
                if to_close >= self.min_lot and to_close < vol_left - self.lot_step / 2:
                    # FIX 2026-03-14 R11: Limiter les tentatives de partial close
                    _partial_fail_key = f"partial_fail_{p.rr}"
                    _partial_fails = st.get(_partial_fail_key, 0)
                    if _partial_fails >= 5:
                        # Abandonner après 5 échecs (~ 100s à 20s/cycle)
                        if _partial_fails == 5:
                            logger.warning(
                                f"[PM] Partial close #{ticket} R:R={p.rr} abandonné "
                                f"après 5 échecs consécutifs"
                            )
                            st[_partial_fail_key] = 6  # Éviter de logger à chaque cycle
                            self._set_tstate(ticket, st)
                        continue

                    ok = self._close_partial(ticket, to_close)
                    if ok:
                        st[_partial_fail_key] = 0  # Reset sur succès
                        vol_left = max(self.min_lot, vol_left - to_close)
                        done.add(p.rr)
                        st["partials_done"] = sorted(list(done))
                        self._set_tstate(ticket, st)
                        logger.info(f"[PM] Partial {self.symbol_canon} ticket={ticket} rr>={p.rr} close={to_close}")
                        partial_hit = True
                    else:
                        st[_partial_fail_key] = _partial_fails + 1
                        self._set_tstate(ticket, st)
                        if _partial_fails < 5:
                            logger.info(
                                f"[PM] Partial close #{ticket} R:R={p.rr} échoué "
                                f"({_partial_fails + 1}/5)"
                            )
        return vol_left, partial_hit

    def _apply_trailing(self, side: str, entry: float, sl: float, price: float, atr: float,
                        sl_ref: Optional[float] = None) -> Optional[float]:
        """
        Trailing ATR : nouveau SL proposé si > SL actuel (buy) ou < SL actuel (sell).
        - start_rr: n’active le trailing que si R courant >= start_rr
        - lock_rr: ne jamais redescendre sous +lock_rr
        """
        try:
            # FIX 2026-07-26 (P3): le R et le verrou lock_rr se mesurent sur le SL
            # d'origine. Sur le SL courant, une position deja passee au break-even
            # donnait risk ~ 0, un R infini, et un lock_sl colle a l'entree : le
            # verrou lock_rr ne garantissait plus rien.
            _sl0 = sl_ref if sl_ref is not None else sl
            rr_now = _compute_rr(side, entry, _sl0, tp=entry, price=price)
            if rr_now is None or rr_now < float(self.trailing.start_rr):
                return None

            mult = float(self.trailing.atr_mult)
            delta = max(atr * mult, 1e-9)

            if side == "BUY":
                new_sl = price - delta
                # lock_rr: calculer le SL min garanti (entry + lock_rr * risk)
                risk = max(entry - _sl0, 1e-9)
                lock_sl = entry + float(self.trailing.lock_rr) * risk
                new_sl = max(new_sl, lock_sl, sl)  # jamais en-dessous de l’actuel
            else:
                new_sl = price + delta
                risk = max(_sl0 - entry, 1e-9)
                lock_sl = entry - float(self.trailing.lock_rr) * risk
                new_sl = min(new_sl, lock_sl, sl)  # jamais au-dessus de l’actuel
            return float(new_sl)
        except Exception:
            return None

    # ---------------------------- public entry ---------------------------
    def manage_open_positions(self) -> None:
        if not self.enabled:
            return

        # FIX 2026-02-24: Log diagnostic PM (Directive 3 — Étape A)
        logger.info(f"[PM_DIAG] {self.symbol_canon}: broker_symbol={self.broker_symbol}, enabled={self.enabled}")

        # PRIORITÉ: Fermer les positions avant la clôture du marché
        closed_before_market = self._close_positions_before_market_close()
        if closed_before_market > 0:
            return  # Positions fermées, pas besoin de continuer

        prev = self._load_open_state().get(self.symbol_canon, {})
        current: Dict[str, dict] = {}
        try:
            positions = self._positions_get()
        except Exception:
            positions = []

        # FIX 2026-02-24: Log nombre de positions trouvées (Directive 3 — Étape B)
        logger.info(f"[PM_DIAG] {self.symbol_canon}: {len(positions)} position(s) trouvée(s)")
        if not positions:
            logger.debug(f"[PM_DIAG] Aucune position trouvée pour broker_symbol={self.broker_symbol}")
        for p in positions or []:
            try:
                ticket = int(getattr(p, "ticket", 0) or 0)
                current[str(ticket)] = {
                    "entry": float(getattr(p, "price_open", 0.0) or 0.0),
                    "sl": float(getattr(p, "sl", 0.0) or 0.0),
                    "tp": float(getattr(p, "tp", 0.0) or 0.0),
                    "side": "BUY" if getattr(p, "type", 0) in (0, mt5.ORDER_TYPE_BUY if mt5 else 0) else "SELL",
                    "time": int(getattr(p, "time", 0) or 0),
                }
            except Exception:
                continue
        # FIX 2026-08-02 : un ticket n'est declare ferme qu'apres N lectures
        # consecutives sans lui.
        #
        # Defaut corrige, observe en production le 01/08/2026 a 08:25:49 :
        # sur 5 534 cycles, UN SEUL a renvoye "SP500: 0 position(s)" — le
        # cycle suivant, 20 s plus tard, revoyait la position, et elle est
        # restee visible les 5 533 cycles suivants. Ce hoquet unique a suffi
        # a supprimer definitivement l'entree pm_state du ticket 1690929973 :
        # plus de break-even, plus de trailing, plus de suivi MFE/MAE sur une
        # position restee ouverte 61 heures.
        #
        # `_positions_get()` renvoie aussi [] quand MT5 leve une exception :
        # une indisponibilite passagere condamnait donc TOUTES les positions
        # du symbole. Exiger plusieurs absences ne supprime pas le risque, il
        # le rend improbable : il faut desormais que la lecture echoue
        # _ABSENCES_AVANT_CLOTURE fois d'affilee.
        absents = [k for k in prev.keys() if k not in current]
        for k in list(self._absences.keys()):
            if k not in absents:
                self._absences.pop(k, None)
        closed_ids = []
        for k in absents:
            n = self._absences.get(k, 0) + 1
            self._absences[k] = n
            if n >= _ABSENCES_AVANT_CLOTURE:
                closed_ids.append(int(k))
            else:
                logger.warning(
                    "[PM] %s ticket=%s absent de la lecture MT5 (%d/%d) — "
                    "cloture NON declaree pour l'instant",
                    self.symbol_canon, k, n, _ABSENCES_AVANT_CLOTURE)
        if absents and not current:
            logger.warning(
                "[PM] %s : lecture MT5 vide alors que %d position(s) etaient "
                "connues. Hoquet de lecture ou fermeture reelle ?",
                self.symbol_canon, len(prev))
        if closed_ids or self._clotures_en_attente:
            try:
                from datetime import datetime, timedelta, timezone as _tz
                end = datetime.now(_tz.utc); start = end - timedelta(days=2)
                deals = mt5.history_deals_get(start, end) if mt5 else []
            except Exception:
                deals = []
            # Rejoue d'abord les clotures en attente de leur deal.
            self._resoudre_clotures_en_attente(deals)
            for tk in closed_ids:
                tk_deals = [d for d in (deals or []) if int(getattr(d, "position_id", 0) or 0) == int(tk)
                            or int(getattr(d, "order", 0) or 0) == int(tk)]
                pnl = sum(float(getattr(d, "profit", 0.0) or 0.0) for d in tk_deals)
                close_time = max((int(getattr(d, "time", 0) or 0) for d in tk_deals), default=None)
                entry = float(prev[str(tk)].get("entry") or 0.0)
                side = prev[str(tk)].get("side")
                point = float(getattr(mt5.symbol_info(self.broker_symbol), "point", 0.01)) if mt5 else 0.01
                px_close = next((float(getattr(d, "price") or 0) for d in tk_deals if getattr(d, "price", None)), None)
                pnl_pips = ((px_close - entry)/point if side=="BUY" else (entry - px_close)/point) if (px_close and entry) else 0.0
                dur = "N/A"
                try:
                    t_open = int(prev[str(tk)].get("time") or 0)
                    if t_open and close_time:
                        mins = max(0, int(close_time) - int(t_open)) // 60
                        dur = f"{mins//60}h{mins%60:02d}"
                except Exception:
                    pass
                result = "TP" if pnl > 0 else ("SL" if pnl < 0 else "BE/Manuel")
                # FIX 2026-07-26 (P3): publier MFE/MAE mesures pendant la vie du trade
                _stc = self._state.get(f"{self.symbol_canon}:{tk}", {}) or {}
                _mfe = _stc.get("mfe_r"); _mae = _stc.get("mae_r")
                self._notify("CLOSE_TRADE", {
                    "symbol": self.symbol_canon, "ticket": tk, "result": result,
                    "pnl_ccy": f"{pnl:+.2f}", "pnl_pips": f"{pnl_pips:+.1f}",
                    "duration": dur, "rr": "N/A",
                    "mfe": f"{float(_mfe):+.2f}R" if _mfe is not None else "N/A",
                    "mae": f"{float(_mae):+.2f}R" if _mae is not None else "N/A",
                })
                # FIX 2026-08-02 : ne pas ecrire une ligne vide. Si MT5 n'a pas
                # encore publie le deal, on met la cloture en attente et on
                # reessaie aux cycles suivants.
                if tk_deals and px_close is not None:
                    self._log_mfe_row(tk, side, entry, px_close, pnl, _mfe, _mae, _stc,
                                      resolu=True)
                else:
                    self._clotures_en_attente[int(tk)] = {
                        "side": side, "entry": entry, "mfe": _mfe, "mae": _mae,
                        "st": dict(_stc), "essais": 0,
                    }
                    logger.info("[PM] %s ticket=%s : cloture detectee mais deal "
                                "absent de l'historique MT5 — ligne MFE differee",
                                self.symbol_canon, tk)

            # (audit fev2026) Nettoyage positions fantômes dans pm_state
            cleaned = 0
            a_supprimer = []
            for tk in closed_ids:
                self._absences.pop(str(tk), None)
                for key_fmt in [f"{self.symbol_canon}:{tk}", str(tk)]:
                    if key_fmt in self._state:
                        del self._state[key_fmt]
                        cleaned += 1
                    a_supprimer.append(key_fmt)
            if cleaned > 0:
                # FIX 2026-08-02 : suppression par fusion — on ne retire que
                # nos propres cles, les entrees des autres symboles restent.
                self._state = fusionner_etat(suppressions=a_supprimer)
                logger.info(f"[PM] Cleaned ghost positions from pm_state: {cleaned} entries for {self.symbol_canon} (tickets: {closed_ids})")

        # persister l'état courant
        # FIX 2026-08-02 : ne pas effacer d'open_positions.json un ticket dont
        # l'absence n'est pas encore confirmee. Sans cela, le compteur
        # d'absences ne pourrait jamais grimper : au cycle suivant, `prev`
        # serait deja vide et le ticket sortirait du suivi sans qu'aucune
        # cloture ne soit declaree — la position deviendrait invisible pour
        # le gestionnaire tout en restant ouverte chez le broker.
        en_attente = {k: v for k, v in prev.items() if k in self._absences}
        state = self._load_open_state()
        state[self.symbol_canon] = {**en_attente, **current}
        self._save_open_state(state)
        try:
            positions = self._positions_get()
            if not positions:
                return

            # Préparer ATR si trailing activé
            atr_val: Optional[float] = None
            if self.trailing.enabled:
                df = self._get_rates(self.trailing.atr_timeframe, count=max(60, self.trailing.atr_period + 5))
                atr_val = _atr_from_rates(df, self.trailing.atr_period) if df is not None else None

            for p in positions:
                try:
                    typ = int(getattr(p, "type", 0))  # 0 BUY, 1 SELL
                    side = "BUY" if typ == 0 else "SELL"
                    ticket = int(getattr(p, "ticket", getattr(p, "identifier", 0)) or 0)
                    entry = _safe_float(getattr(p, "price_open", None))
                    sl    = _safe_float(getattr(p, "sl", None))
                    tp    = _safe_float(getattr(p, "tp", None))
                    price = _safe_float(getattr(p, "price_current", None))
                    volume= _safe_float(getattr(p, "volume", None))

                    if None in (entry, sl, price, volume) or ticket <= 0:
                        continue

                    # FIX 2026-07-26 (P3): figer le SL d'origine des la premiere vue du
                    # ticket, et mesurer tous les R par rapport a lui.
                    _st0 = self._get_tstate(ticket)
                    sl0 = _st0.get("sl_orig")
                    if sl0 is None or float(sl0) <= 0:
                        sl0 = sl
                        _st0["sl_orig"] = float(sl0)
                        self._set_tstate(ticket, _st0)
                    sl0 = float(sl0)

                    # RR actuel (si TP absent, on utilise entry pour RR BE/partials)
                    rr_now = _compute_rr(side, entry, sl0, tp or entry, price) or 0.0

                    # FIX 2026-07-26 (P3): instrumentation MFE/MAE. Sans elle, impossible
                    # de trancher sur les partiels, le break-even et le trailing autrement
                    # qu'a l'aveugle.
                    _mfe = _st0.get("mfe_r"); _mae = _st0.get("mae_r")
                    _new_mfe = rr_now if _mfe is None else max(float(_mfe), rr_now)
                    _new_mae = rr_now if _mae is None else min(float(_mae), rr_now)
                    if _new_mfe != _mfe or _new_mae != _mae:
                        _st0["mfe_r"] = round(float(_new_mfe), 4)
                        _st0["mae_r"] = round(float(_new_mae), 4)
                        self._set_tstate(ticket, _st0)

                    # ---- PARTIALS
                    # FIX 2026-02-24: Log diagnostic partials (Directive 3 — Étape C)
                    logger.debug(f"[PM_PARTIAL] ticket={ticket} rr_now={rr_now:.2f} vol={volume} partials_cfg={[(p.rr, p.close_frac) for p in self.partials]}")
                    partial_hit = False
                    if self.partials and volume and rr_now >= min(pp.rr for pp in self.partials):
                        volume, partial_hit = self._apply_partials(ticket, volume, rr_now)

                    st = self._get_tstate(ticket)

                    # ---- BREAK-EVEN
                    # FIX 2026-07-26 (P3): mesure sur le SL d'origine, et plus de
                    # declenchement force par un partiel.
                    new_sl_be = self._apply_break_even(side, entry, sl0, price)
                    if new_sl_be is not None and ((side == "BUY" and new_sl_be > sl) or (side == "SELL" and new_sl_be < sl)):
                        if self._modify_sl_tp(ticket, new_sl_be, tp):
                            sl = new_sl_be
                            st = self._get_tstate(ticket)
                            st["be_done"] = True
                            self._set_tstate(ticket, st)
                            self._notify("MOVE_BE", {"symbol": self.symbol_canon, "detail": f"ticket={ticket} SL->{new_sl_be:.5f}"})


                    # ---- TRAILING
                    if self.trailing.enabled and atr_val and atr_val > 0:
                        new_sl_tr = self._apply_trailing(side, entry, sl, price, atr_val, sl_ref=sl0)
                        if new_sl_tr is not None and ((side == "BUY" and new_sl_tr > sl) or (side == "SELL" and new_sl_tr < sl)):
                            if self._modify_sl_tp(ticket, new_sl_tr, tp):
                                sl = new_sl_tr
                                st = self._get_tstate(ticket)
                                st["trail_active"] = True
                                self._set_tstate(ticket, st)
                                self._notify("TRAILING_SL_UPDATE", {"symbol": self.symbol_canon, "detail": f"ticket={ticket} SL->{new_sl_tr:.5f}"})

                except Exception as e:
                    logger.warning(f"[PM] manage position error: {e}")

            # FIX 2026-02-24: Timeout — fermeture automatique après max_duration_minutes (Directive 4)
            if self.max_duration_minutes > 0:
                from datetime import datetime, timezone
                _now_utc = datetime.now(timezone.utc)
                for p in positions:
                    try:
                        ticket = int(getattr(p, "ticket", getattr(p, "identifier", 0)) or 0)
                        if ticket <= 0:
                            continue
                        _open_time = int(getattr(p, "time", 0))
                        if _open_time <= 0:
                            continue
                        _open_dt = datetime.fromtimestamp(_open_time, tz=timezone.utc)
                        _elapsed_min = (_now_utc - _open_dt).total_seconds() / 60.0
                        if _elapsed_min < self.max_duration_minutes:
                            continue
                        _pnl = float(getattr(p, "profit", 0.0) or 0.0)
                        # Si timeout_only_if_losing, ne fermer que les perdants
                        if self.timeout_only_if_losing and _pnl >= 0:
                            continue
                        _vol = float(getattr(p, "volume", 0.0) or 0.0)
                        _side = "BUY" if int(getattr(p, "type", 0)) == 0 else "SELL"
                        _hours = int(_elapsed_min // 60)
                        _mins = int(_elapsed_min % 60)
                        # FIX 2026-08-02 : ne pas reannoncer la fermeture a
                        # chaque cycle quand elle est en backoff.
                        if self._cloture_en_backoff(ticket):
                            continue
                        logger.warning(f"[PM_TIMEOUT] {self.symbol_canon} ticket={ticket} durée={_hours}h{_mins:02d}m P&L={_pnl:.2f} → fermeture")
                        closed = self._close_position_full(ticket, _vol, _side)
                        if closed:
                            self._notify("TIMEOUT_CLOSE", {
                                "symbol": self.symbol_canon,
                                "detail": f"ticket={ticket} durée={_hours}h{_mins:02d}m P&L={_pnl:+.2f}"
                            })
                    except Exception as _to_err:
                        logger.debug(f"[PM_TIMEOUT] Erreur check timeout: {_to_err}")

        except Exception as e:
            logger.warning(f"[PM] manage_open_positions failed: {e}")
