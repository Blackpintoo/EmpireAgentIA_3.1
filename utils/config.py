# utils/config.py
from __future__ import annotations

import os, yaml
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from functools import lru_cache
# === PATCH: imports pour calendrier/tz ===
from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None
try:
    import pytz  # fallback si zoneinfo absent
except Exception:  # pragma: no cover
    pytz = None
# === FIN PATCH imports ===
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # permettra un fallback en renvoyant {}

# -----------------------------------------------------------------------------
# Constantes chemins
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.yaml"
DEFAULT_PROFILES_PATH = CONFIG_DIR / "profiles.yaml"
DEFAULT_OVERRIDES_PATH = CONFIG_DIR / "overrides.yaml"

# Lock d’écriture pour les sauvegardes
_config_lock = threading.RLock()

# -----------------------------------------------------------------------------
# Utilitaires
# -----------------------------------------------------------------------------
def get_tf_config():
    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    prof = yaml.safe_load(open("config/profiles.yaml", encoding="utf-8"))
    over = yaml.safe_load(open("config/overrides.yaml", encoding="utf-8"))

    # ordre: base <- profiles <- overrides
    def deep_merge(a,b):
        import copy
        r = copy.deepcopy(a)
        for k,v in (b or {}).items():
            if isinstance(v, dict) and isinstance(r.get(k), dict):
                r[k] = deep_merge(r[k], v)
            else:
                r[k] = v
        return r

    merged = deep_merge(deep_merge(cfg, prof), over)

    mtf = (merged.get("multi_timeframes") or {})
    tfs = mtf.get("tfs") or ["D1","H4","H1","M30","M5","M1"]
    weights = mtf.get("tf_weights") or {
        "D1":1.2,"H4":1.1,"H1":1.0,"M30":0.9,"M5":0.8,"M1":0.7
    }
    return tfs, weights, (mtf.get("enabled", True))

def _env_or(value: str|int|None, key: str):
    v = os.getenv(key)
    return v if v is not None else value

def _safe_load_yaml(path: Path) -> dict:
    if yaml is None:
        return {}
    try:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}

def _deep_merge(base: dict, extra: dict) -> dict:
    """Fusion récursive (extra écrase base pour les feuilles)."""
    if not isinstance(base, dict):
        base = {}
    if not isinstance(extra, dict):
        return base
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Charge config.yaml puis applique les surcharges d'environnement (.env/vars).
    IMPORTANT : ne rien faire au niveau module avec 'cfg'.
    """
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    cfg: Dict[str, Any] = _safe_load_yaml(p) or {}

    def _env_or(val, key: str):
        v = os.getenv(key)
        return v if (v not in (None, "")) else val

    # ---- Overlays ENV pour MT5 / Telegram ----
    mt5 = cfg.setdefault("mt5", {})
    mt5["account"]  = _env_or(mt5.get("account"),  "MT5_ACCOUNT")
    mt5["password"] = _env_or(mt5.get("password"), "MT5_PASSWORD")
    mt5["server"]   = _env_or(mt5.get("server"),   "MT5_SERVER")

    tg = cfg.setdefault("telegram", {})
    tg["token"]   = _env_or(tg.get("token"),   "TELEGRAM_TOKEN")
    tg["chat_id"] = _env_or(str(tg.get("chat_id")), "TELEGRAM_CHAT_ID")

    return cfg

def save_config(cfg: dict, path: Optional[str] = None) -> None:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    with _config_lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML manquant pour save_config")
        p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

def reload_global_config(path: Optional[str] = None) -> None:
    """
    Invalide le cache de load_config() (et de tout ce qui en dépend).
    """
    load_config.cache_clear()  # type: ignore
    # pas de lecture immédiate: lazy au prochain appel

# -----------------------------------------------------------------------------
# PROFILES (profiles.yaml) + OVERRIDES (overrides.yaml)
# -----------------------------------------------------------------------------
class ProfilesConfigError(RuntimeError):
    pass

_CFG_CACHE: Optional[Dict[str, Any]] = None
_PROFILES_CACHE: Optional[Dict[str, Any]] = None
_OVERRIDES_CACHE: Optional[Dict[str, Any]] = None

def _load_yaml(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def get_cfg() -> Dict[str, Any]:
    global _CFG_CACHE
    if _CFG_CACHE is None:
        _CFG_CACHE = _load_yaml(os.path.join("config", "config.yaml"))
    return _CFG_CACHE

def get_overrides() -> Dict[str, Any]:
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is None:
        # permet à un .bat de pointer un overrides différent via ENV
        ov_path = os.environ.get("EMPIRE_OVERRIDES", os.path.join("config", "overrides.yaml"))
        _OVERRIDES_CACHE = _load_yaml(ov_path)
    return _OVERRIDES_CACHE

def get_profiles() -> Dict[str, Any]:
    global _PROFILES_CACHE
    if _PROFILES_CACHE is None:
        _PROFILES_CACHE = _load_yaml(os.path.join("config", "profiles.yaml"))
    return _PROFILES_CACHE

def get_enabled_symbols() -> List[str]:
    # Toujours depuis profiles.yaml si présent, sinon fallback config.yaml
    p = get_profiles()
    syms = (p.get("enabled_symbols") or [])
    if not syms:
        syms = (get_cfg().get("enabled_symbols") or ["BTCUSD","XAUUSD"])
    return list(dict.fromkeys([s.upper() for s in syms]))

def get_symbol_profile(sym: str) -> Dict[str, Any]:
    """
    Charge le profil d’un symbole en fusionnant :
      profiles.yaml -> section profiles.<SYM>
      overrides.yaml -> GLOBAL puis <SYM> (écrasent)
      + applique tfs / tf_weights par défaut (config.yaml.multi_timeframes) si absents.
    """
    sym = (sym or "").upper()
    p = get_profiles() or {}
    # >>> 1) lire dans 'profiles', pas 'symbols'
    base = (p.get("profiles", {}) or {}).get(sym, {}).copy()

    # >>> 2) TFS/weights par défaut depuis config.yaml (multi_timeframes)
    try:
        cfg = get_cfg() or {}
        mtf = (cfg.get("multi_timeframes") or {})
        if "tfs" not in base:
            base["tfs"] = mtf.get("tfs", ["D1","H4","H1","M30","M5","M1"])
        if "tf_weights" not in base:
            base["tf_weights"] = mtf.get("tf_weights", {
                "D1":1.2,"H4":1.1,"H1":1.0,"M30":0.9,"M5":0.8,"M1":0.7
            })
    except Exception:
        base.setdefault("tfs", ["D1","H4","H1","M30","M5","M1"])
        base.setdefault("tf_weights", {"D1":1.2,"H4":1.1,"H1":1.0,"M30":0.9,"M5":0.8,"M1":0.7})

    # >>> 3) Appliquer overrides.yaml (GLOBAL puis spécifique symbole)
    ov = get_overrides() or {}

    def deep_update(dst: dict, src: dict):
        for k, v in (src or {}).items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                deep_update(dst[k], v)
            else:
                dst[k] = v

    # GLOBAL (si présent)
    g = ov.get("GLOBAL") or {}
    deep_update(base, g)

    # Spécifique symbole : key peut être canonique ou broker
    spec = ov.get(sym) or ov.get(broker_symbol_for(sym)) or {}
    deep_update(base, spec)

    # Pour compat : aplatir orchestrator.* utiles au runtime
    orch = (base.get("orchestrator") or {})
    for k in ("votes_required", "auto_execute", "telegram_validation", "min_confluence"):
        if k in orch:
            base[k] = orch[k]

    return base

# === PATCH: helpers deviation / planning ===

# Lecture d’une valeur de déviation par symbole depuis profiles.yaml,
# avec fallback sur config.yaml: engine.default_deviation, puis sur 'default' paramètre.
def get_symbol_deviation(symbol: str, default: int | None = None) -> int:
    try:
        prof = get_symbol_profile(symbol) or {}
        if "deviation" in prof:
            return int(prof.get("deviation") or (default or 30))
    except Exception:
        pass
    try:
        cfg = load_config() or {}
        eng = cfg.get("engine") or {}
        if "default_deviation" in eng:
            return int(eng.get("default_deviation") or (default or 30))
    except Exception:
        pass
    return int(default or 30)


# Map jours: profils utilisent [MON, TUE, ...]
_DAY_MAP = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

def _get_tz(tz_name: str | None) -> object | None:
    """Retourne un objet timezone utilisable (ZoneInfo prioritaire, sinon pytz, sinon None)."""
    if not tz_name:
        tz_name = "Europe/Zurich"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    if pytz is not None:
        try:
            return pytz.timezone(tz_name)  # type: ignore
        except Exception:
            pass
    return None  # naive fallback


def is_symbol_active_now(symbol: str, now: datetime | None = None, tz_name: str | None = None) -> bool:
    """
    True si le symbole est 'actif' à l’instant courant selon profiles.yaml:
      profiles.<SYMBOL>.enabled (bool)
      profiles.<SYMBOL>.schedule.active_days: [MON..SUN]
      profiles.<SYMBOL>.schedule.active_hours: [start, end]  (ex: [6, 20])
    - start inclusif, end exclusif ; [0, 24] = 24/7 sur les jours listés.
    - tz_name: override de fuseau (sinon config.engine.timezone, sinon Europe/Zurich).
    """
    prof = get_symbol_profile(symbol) or {}
    if not prof:
        return True  # si pas de profil, on ne bloque pas

    # enabled ?
    if str(prof.get("enabled", True)).lower() in ("false", "0", "no"):
        return False

    sched = prof.get("schedule") or {}
    days  = sched.get("active_days") or []
    hours = sched.get("active_hours") or []

    # fuseau horaire (config.yaml -> engine.timezone) puis défaut
    if tz_name is None:
        try:
            cfg = load_config() or {}
            tz_name = (cfg.get("engine") or {}).get("timezone") or "Europe/Zurich"
        except Exception:
            tz_name = "Europe/Zurich"
    tz = _get_tz(tz_name)

    # now en tz
    if now is None:
        now = datetime.utcnow()
    try:
        if tz is not None:
            # si ZoneInfo: now sans tz -> attacher UTC puis convertir
            if getattr(now, "tzinfo", None) is None:
                if ZoneInfo is not None:
                    now = now.replace(tzinfo=ZoneInfo("UTC"))
                elif pytz is not None:
                    now = pytz.utc.localize(now)  # type: ignore
            now_local = now.astimezone(tz)  # type: ignore
        else:
            now_local = now  # naive
    except Exception:
        now_local = now

    # jour actif ?
    if days:
        wd = now_local.weekday()
        allowed = set()
        for d in days:
            try:
                allowed.add(_DAY_MAP[str(d).upper()])
            except Exception:
                continue
        if allowed and wd not in allowed:
            return False

    # heures actives ?
    if isinstance(hours, (list, tuple)) and len(hours) == 2:
        try:
            start_h = int(hours[0])
            end_h   = int(hours[1])
        except Exception:
            start_h, end_h = 0, 24
        h = now_local.hour
        if start_h == end_h:
            # plage vide -> désactivé
            return False
        if start_h < end_h:
            # fenêtre normale dans la même journée
            if not (start_h <= h < end_h):
                return False
        else:
            # fenêtre "overnight" (ex: [22, 6])
            if not (h >= start_h or h < end_h):
                return False

    return True
# === FIN PATCH helpers deviation / planning ===

# -----------------------------------------------------------------------------
# Helpers spécifiques projet (broker, coûts, timeframes, telegram)
# -----------------------------------------------------------------------------
def broker_symbol_for(profile_or_symbol: Any) -> str:
    """
    Renvoie le symbole broker à partir d'un profil OU d'un nom canonique.
    Utilise instrument.broker_symbol si disponible, sinon retourne le symbole tel quel.
    """
    if isinstance(profile_or_symbol, dict):
        instr = profile_or_symbol.get("instrument") or {}
        bro = instr.get("broker_symbol")
        if bro:
            return str(bro)
        sym = (profile_or_symbol.get("symbol") or "").upper()
    else:
        sym = str(profile_or_symbol).upper()

    # LTCUSD remplace LINKUSD depuis 2025-12-05
    if sym == "LTCUSD":
        return "LTCUSD"
    return sym

def canon_symbol_for(broker_symbol: str) -> str:
    s = (broker_symbol or "").upper()
    return s  # Pas de mapping inverse nécessaire pour LTCUSD

def get_broker_costs(cfg: Optional[dict] = None) -> dict:
    """
    Renvoie un dict normalisé des coûts broker.
    Clés normalisées utilisées par RiskManager:
      - commission_per_lot
      - point_value_per_lot
      - spread_points
      - slippage_points_entry
      - slippage_points_exit
    """
    C = cfg or load_config()
    bc = (C.get("broker_costs") or {}).copy()

    # Normalisations/compat
    # alias éventuels: 'slippage_entry' -> 'slippage_points_entry'
    if "slippage_entry" in bc and "slippage_points_entry" not in bc:
        bc["slippage_points_entry"] = bc.pop("slippage_entry")
    if "slippage_exit" in bc and "slippage_points_exit" not in bc:
        bc["slippage_points_exit"] = bc.pop("slippage_exit")

    bc.setdefault("commission_per_lot", 0.0)
    bc.setdefault("point_value_per_lot", 1.0)
    bc.setdefault("spread_points", 0.0)
    bc.setdefault("slippage_points_entry", 0.0)
    bc.setdefault("slippage_points_exit", 0.0)
    return bc

def get_timeframes(cfg: Optional[dict] = None) -> dict:
    C = cfg or load_config()
    return (C.get("timeframes") or {}).copy()

def get_telegram_config(cfg: Optional[dict] = None) -> dict:
    C = cfg or load_config()
    tg = (C.get("telegram") or {}).copy()
    # compat
    if "bot_token" in tg and "token" not in tg:
        tg["token"] = tg.get("bot_token")
    tg.setdefault("enabled", False)
    tg.setdefault("token", None)
    tg.setdefault("chat_id", None)
    tg.setdefault("allow_kinds", ["status","trade_validation","news_digest","trade_event"])
    tg.setdefault("send_trade_validation_only", False)
    return tg

# -----------------------------------------------------------------------------
# Petits helpers risque/tiers (utiles pour tests & RiskManager)
# -----------------------------------------------------------------------------
def get_risk_tiers(cfg: Optional[dict] = None) -> List[dict]:
    C = cfg or load_config()
    tiers = ((C.get("risk") or {}).get("tiers") or [])
    return list(tiers)

def get_monthly_goals(cfg: Optional[dict] = None) -> dict:
    C = cfg or load_config()
    goals = ((C.get("risk") or {}).get("monthly_goal_chf_by_phase") or {})
    return dict(goals)

# -----------------------------------------------------------------------------
# API minimale attendue par d’autres modules plus anciens
# -----------------------------------------------------------------------------
def config_get(path: Optional[str] = None) -> dict:
    """Alias rétro-compatible de load_config."""
    return load_config(path)

# -----------------------------------------------------------------------------
# Méthodes de maintenance (utile dans des scripts ou jobs auto-opt)
# -----------------------------------------------------------------------------
def write_overrides(symbol: str, patch: dict,
                    overrides_path: Optional[str] = None) -> None:
    """
    Écrit/merge des overrides pour un symbole.
    """
    sym = (symbol or "").upper()
    p = Path(overrides_path) if overrides_path else DEFAULT_OVERRIDES_PATH
    cur = _safe_load_yaml(p)
    cur.setdefault(sym, {})
    cur[sym] = _deep_merge(cur[sym], patch or {})
    with _config_lock:
        p.parent.mkdir(parents=True, exist_ok=True)
        if yaml is None:  # pragma: no cover
            raise RuntimeError("PyYAML manquant pour write_overrides")
        p.write_text(yaml.safe_dump(cur, sort_keys=False, allow_unicode=True), encoding="utf-8")

def clear_caches() -> None:
    """Vide les caches LRU de ce module."""
    load_config.cache_clear()       # type: ignore
    load_profiles_yaml.cache_clear()# type: ignore

def _deep_merge(a, b):
    r = copy.deepcopy(a or {}) # type: ignore
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(r.get(k), dict):
            r[k] = _deep_merge(r[k], v)
        else:
            r[k] = v
    return r

def get_tf_config():
    """Retourne (tfs, tf_weights, mtf_enabled) après merge config.yaml <- profiles.yaml <- overrides.yaml"""
    base = {}
    prof = {}
    over = {}
    if os.path.exists("config/config.yaml"):
        base = yaml.safe_load(open("config/config.yaml", encoding="utf-8")) or {}
    if os.path.exists("config/profiles.yaml"):
        prof = yaml.safe_load(open("config/profiles.yaml", encoding="utf-8")) or {}
    if os.path.exists("config/overrides.yaml"):
        over = yaml.safe_load(open("config/overrides.yaml", encoding="utf-8")) or {}

    merged = _deep_merge(_deep_merge(base, prof), over)
    mtf = merged.get("multi_timeframes") or {}
    tfs = mtf.get("tfs") or ["D1","H4","H1","M30","M5","M1"]
    weights = mtf.get("tf_weights") or {"D1":1.2,"H4":1.1,"H1":1.0,"M30":0.9,"M5":0.8,"M1":0.7}
    return tfs, weights, bool(mtf.get("enabled", True))
# <<< EMPIRE PATCH 1

# -----------------------------------------------------------------------------
# INTÉGRATION DES NOUVEAUX PROFILS DE TRADING (SCALPING / SWING)
# Ajouté le 2025-12-07
# -----------------------------------------------------------------------------

import copy

# Import des modules de profils de trading
try:
    from config.trading_profiles import (
        get_trading_config,
        get_position_manager_for_symbol,
        get_structure_agent_for_symbol,
        get_smart_money_agent_for_symbol,
        get_ote_for_symbol,
        should_trade_symbol,
        get_active_profile,
        set_active_profile,
        initialize_profiles,
        validate_config,
        log_config,
        get_all_configs_summary
    )
    from config.killzones import (
        should_trade_now,
        get_active_killzones,
        is_symbol_in_killzone,
        get_symbols_for_current_killzone,
        KILLZONES
    )
    from config.symbols import (
        get_symbol_adjustments,
        get_volatility_class,
        is_crypto,
        is_forex,
        is_index,
        is_commodity,
        ENABLED_SYMBOLS as SYMBOLS_LIST
    )
    TRADING_PROFILES_AVAILABLE = True
except ImportError:
    TRADING_PROFILES_AVAILABLE = False
    # Fonctions fallback si modules non disponibles
    def get_trading_config(symbol, timeframe=None, profile=None):
        return get_symbol_profile(symbol)
    def get_position_manager_for_symbol(symbol, timeframe=None, profile=None):
        return (get_symbol_profile(symbol).get("orchestrator", {}) or {}).get("position_manager", {})
    def get_structure_agent_for_symbol(symbol, timeframe=None, profile=None):
        return {}
    def get_smart_money_agent_for_symbol(symbol, timeframe=None, profile=None):
        return {}
    def get_ote_for_symbol(symbol, timeframe=None, profile=None):
        return {"zone_low": 0.62, "sweet_spot": 0.705, "zone_high": 0.79}
    def should_trade_symbol(symbol, profile=None, strict=False):
        return True, "Profiles module not available"
    def get_active_profile():
        return "SCALPING"
    def set_active_profile(profile):
        pass
    def initialize_profiles(profile=None):
        pass
    def validate_config(config):
        return True, []
    def log_config(symbol, config):
        pass
    def get_all_configs_summary():
        return {}
    def should_trade_now(symbol, profile="SCALPING", current_time=None, strict=True):
        return True, "OK"
    def get_active_killzones(current_time=None):
        return []
    def is_symbol_in_killzone(symbol, current_time=None):
        return True, []
    def get_symbols_for_current_killzone(current_time=None):
        return get_enabled_symbols()
    def get_symbol_adjustments(symbol, profile="SCALPING"):
        return {}
    def get_volatility_class(symbol, profile="SCALPING"):
        return "medium"
    def is_crypto(symbol):
        return symbol.upper() in ["BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"]
    def is_forex(symbol):
        return symbol.upper() in ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
    def is_index(symbol):
        return symbol.upper() in ["DJ30", "NAS100", "GER40"]
    def is_commodity(symbol):
        return symbol.upper() in ["XAUUSD", "XAGUSD", "CL-OIL"]
    KILLZONES = {}
    SYMBOLS_LIST = []


def get_trading_profile_for_symbol(symbol: str, timeframe: str = None) -> Dict[str, Any]:
    """
    Retourne la configuration de trading complète pour un symbole,
    en utilisant les nouveaux profils SCALPING/SWING si disponibles.

    Args:
        symbol: Le symbole (ex: "BTCUSD")
        timeframe: Le timeframe (ex: "M15"). Détermine le profil automatiquement.

    Returns:
        Configuration complète avec position_manager, agents, etc.
    """
    if TRADING_PROFILES_AVAILABLE:
        return get_trading_config(symbol, timeframe)
    else:
        # Fallback vers l'ancien système
        return get_symbol_profile(symbol)


def get_merged_agent_params(symbol: str, agent_name: str, timeframe: str = None) -> Dict[str, Any]:
    """
    Retourne les paramètres d'un agent après fusion avec les nouveaux profils.

    Args:
        symbol: Le symbole
        agent_name: Nom de l'agent ("structure", "smart_money", etc.)
        timeframe: Le timeframe

    Returns:
        Paramètres fusionnés
    """
    if not TRADING_PROFILES_AVAILABLE:
        profile = get_symbol_profile(symbol)
        return (profile.get("agents", {}) or {}).get(agent_name, {})

    if agent_name == "structure":
        return get_structure_agent_for_symbol(symbol, timeframe)
    elif agent_name == "smart_money":
        return get_smart_money_agent_for_symbol(symbol, timeframe)
    else:
        # Pour les autres agents, utiliser le profil standard
        profile = get_symbol_profile(symbol)
        return (profile.get("agents", {}) or {}).get(agent_name, {})


def check_killzone_eligibility(symbol: str, strict: bool = False) -> Tuple[bool, str]:
    """
    Vérifie si un symbole peut être tradé actuellement selon les killzones.

    Args:
        symbol: Le symbole
        strict: Si True, applique les killzones strictement

    Returns:
        Tuple (peut_trader, raison)
    """
    if TRADING_PROFILES_AVAILABLE:
        return should_trade_symbol(symbol, strict=strict)
    return True, "Killzones not available"


def get_position_manager_config_for_symbol(symbol: str, timeframe: str = None) -> Dict[str, Any]:
    """
    Retourne la config Position Manager optimisée pour un symbole.
    Utilise les nouveaux profils SCALPING/SWING.

    Args:
        symbol: Le symbole
        timeframe: Le timeframe (détermine SCALPING vs SWING)

    Returns:
        Configuration Position Manager
    """
    if TRADING_PROFILES_AVAILABLE:
        return get_position_manager_for_symbol(symbol, timeframe)

    # Fallback
    profile = get_symbol_profile(symbol)
    return (profile.get("orchestrator", {}) or {}).get("position_manager", {
        "enabled": True,
        "break_even": {"rr": 1.0, "offset_points": 0.0},
        "partials": [{"rr": 1.0, "close_frac": 0.5}],
        "trailing": {"enabled": True, "start_rr": 1.8, "atr_mult": 1.6}
    })


# Export pour compatibilité
__all__ = [
    # Fonctions existantes
    "load_config", "save_config", "reload_global_config",
    "get_cfg", "get_profiles", "get_overrides",
    "get_enabled_symbols", "get_symbol_profile",
    "get_broker_costs", "get_timeframes", "get_telegram_config",
    "broker_symbol_for", "canon_symbol_for",
    "get_risk_tiers", "get_monthly_goals",
    "write_overrides", "clear_caches",
    "get_symbol_deviation", "is_symbol_active_now",
    "get_tf_config",
    # Nouvelles fonctions profils trading
    "get_trading_profile_for_symbol",
    "get_merged_agent_params",
    "check_killzone_eligibility",
    "get_position_manager_config_for_symbol",
    "TRADING_PROFILES_AVAILABLE",
    # Re-exports des modules de profils
    "get_trading_config",
    "should_trade_symbol",
    "get_active_profile",
    "set_active_profile",
    "initialize_profiles",
    "get_active_killzones",
    "is_symbol_in_killzone",
    "get_symbols_for_current_killzone",
    "is_crypto", "is_forex", "is_index", "is_commodity",
    "get_volatility_class"
]