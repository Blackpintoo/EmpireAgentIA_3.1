# utils/mt5_client.py
from __future__ import annotations
import os
import threading
from typing import Optional, Dict, Any, List, Tuple
import math
import time
import yaml
from utils.logger import logger
from utils.config import load_config
from utils.order_result import to_dict as _ordict
from utils.telegram_client import _CFG_PATH
from datetime import datetime, timezone
from collections import deque

# Import MetaTrader5 avec fallback (Windows uniquement)
try:
    import MetaTrader5 as _mt5
    MT5_AVAILABLE = True
    logger.info("[MT5] MetaTrader5 module disponible")
except ImportError:
    _mt5 = None
    MT5_AVAILABLE = False
    logger.warning("[MT5] MetaTrader5 non disponible (Linux/WSL) - Mode simulation uniquement")


def _precheck_symbol(symbol: str) -> tuple[bool, str]:
    """Valide la sélection du symbole via MT5 si disponible, sinon via profiles.yaml."""
    backend = mt5
    if _use_sim():
        return True, "dry-run"
    if backend is not None:
        try:
            symbol_select = getattr(backend, 'symbol_select', None)
            if callable(symbol_select) and not symbol_select(symbol, True):
                return False, f"Symbol {symbol} not selectable."
            info = getattr(backend, 'symbol_info', lambda *_: None)(symbol)
            if not info:
                return False, f"Symbol {symbol} info missing."
            trade_mode = getattr(info, 'trade_mode', None)
            disabled_mode = getattr(backend, 'SYMBOL_TRADE_MODE_DISABLED', None)
            if disabled_mode is not None and trade_mode == disabled_mode:
                return False, f"Symbol {symbol} trade disabled."
            volume_step = getattr(info, 'volume_step', 0)
            volume_min = getattr(info, 'volume_min', 0)
            if volume_step <= 0 or volume_min <= 0:
                return False, f"Lot step/min invalid: step={volume_step} min={volume_min}"
            digits = getattr(info, 'digits', 0)
            if digits not in (0, 1, 2, 3, 4, 5):
                return False, f"Digits abnormal: {digits}"
            return True, ""
        except Exception:
            pass
    from utils.config import get_symbol_profile
    prof = get_symbol_profile(symbol) or {}
    inst = prof.get("instrument") or {}
    if not inst.get("lot_step") or not inst.get("lot_min"):
        return False, "Missing lot_step/lot_min in profiles."
    return True, ""

def _safe_import_mt5():
    return _mt5

mt5 = _safe_import_mt5()

_SIM = None

def market_info(symbol: str) -> dict:
    """Retourne un snapshot leger des infos MT5 pour un symbole donne."""
    info = mt5.symbol_info(symbol) if mt5 else None
    tick = mt5.symbol_info_tick(symbol) if mt5 else None
    out = {
        "symbol": symbol,
        "trade_mode": getattr(info, "trade_mode", None),
        "spread": getattr(info, "spread", None),
        "digits": getattr(info, "digits", None),
        "session_deals": getattr(info, "session_deals", None),
        "ask": getattr(tick, "ask", None),
        "bid": getattr(tick, "bid", None),
        "time": getattr(tick, "time", None),
    }
    return out


def _use_sim() -> bool:
    # 1) env a priorité (ex: MT5_DRY_RUN=1)
    v = os.environ.get("MT5_DRY_RUN")
    if v is not None and v.strip() != "":
        return v.strip() not in ("0","false","False","FALSE")
    # 2) via config d'exécution si dispo dans self.cfg (captée plus bas)
    return False


class MT5Client:
    """
    Client MetaTrader5 robuste (thread-safe).
      - initialize/login une seule fois pour tout le process
      - mapping symboles logiques -> broker si nécessaire
      - helpers OHLC/ticks/prix
      - place_order() MARKET avec gestion des retcodes, requotes, invalid stops
      - parse_timeframe() compatible 'M1'..'D1' + constants
      - fetch_ohlc()/get_rates() adaptés aux agents (DataFrame prêt à l’emploi côté agent)

    Méthodes clés utilisées par tes agents/orchestrateur :
      - parse_timeframe(tf)
      - fetch_ohlc(symbol, tf_code, count)
      - get_rates(symbol, timeframe, count) -> List[dict]
      - get_tick(symbol)
      - get_last_price(symbol, side='BUY')
      - ensure_symbol(symbol)
      - place_order(symbol, side, lot, price=None, sl=None, tp=None, deviation=None, **kwargs)
    """

    _initialized = False
    _login = None
    _server = None
    _last_init_ts = None
    _logged_in = False


    # partage global des symboles déjà sélectionnés (évite de spammer symbol_select)
    _selected_global: set[str] = set()
    _selected_lock = threading.Lock()

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        # 1) Charger la config et appliquer éventuelle surcharge
        base_cfg = load_config() or {}
        if cfg is not None:
            merged = dict(base_cfg)
            merged.update(cfg)
            self.cfg = merged
        else:
            self.cfg = base_cfg

        # 2) Propager le dry-run global posé par l'orchestrateur (builtins)
        try:
            import builtins
            if getattr(builtins, '__EMPIRE_DRY_RUN__', False):
                os.environ.setdefault('MT5_DRY_RUN', '1')
        except Exception:
            pass

        # 3) État local
        self._err_times = []
        self._symbol_cache = {}
        self._inst_cache = {}
        self._last_ping = None
        self._recent_orders = deque(maxlen=128)

        # 4) Dry-run via config (execution.dry_run)
        if (self.cfg.get('execution') or {}).get('dry_run') is True:
            os.environ.setdefault('MT5_DRY_RUN', '1')

        # 5) Recharge optionnelle depuis _CFG_PATH (si présent)
        try:
            with open(_CFG_PATH, encoding='utf-8') as f:
                cfg2 = yaml.safe_load(f) or {}
                if isinstance(cfg2, dict) and cfg2:
                    self.cfg = cfg2
        except Exception:
            pass

        if cfg is not None:
            merged = dict(self.cfg)
            merged.update(cfg)
            self.cfg = merged

        backend = globals().get('mt5')
        env_flag = os.environ.get('MT5_DRY_RUN')
        cfg_flag = bool((self.cfg.get('execution') or {}).get('dry_run'))
        if not cfg_flag and env_flag and env_flag.strip() not in ('0', 'false', 'False'):
            if backend is not None and hasattr(backend, 'order_send'):
                os.environ['MT5_DRY_RUN'] = '0'

        # 6) Init/login (géré dans _ensure_initialized_and_login)
        self._ensure_initialized_and_login()

    # ----------------------------- Helpers config -----------------------------
    def _exec_cfg(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        ex = (self.cfg or {}).get("execution", {}) or {}
        # surcharge par symbole si présent dans profiles
        try:
            from utils.config import get_symbol_profile
            if symbol:
                prof = (get_symbol_profile(symbol) or {})
                ex = {**ex, **(prof.get("execution") or {})}
        except Exception:
            pass
        return {
            "slippage_points": int(ex.get("slippage_points", 10)),
            "max_retries": int(ex.get("max_retries", 3)),
            "backoff_seconds": list(ex.get("backoff_seconds", [0.5, 1.0, 2.0])),
            "price_refresh_on_requote": bool(ex.get("price_refresh_on_requote", True)),
            "cb_window": int(((ex.get("circuit_breaker") or {}).get("window_seconds", 60))),
            "cb_max_errors": int(((ex.get("circuit_breaker") or {}).get("max_errors", 5))),
        }

    # ----------------------------- Circuit Breaker ----------------------------
    def _cb_allow(self, cb_window: int, cb_max: int) -> bool:
        now = datetime.now(timezone.utc).timestamp() # type: ignore
        self._err_times = [t for t in self._err_times if now - t <= cb_window]
        return len(self._err_times) < cb_max

    def _cb_note_error(self):
        self._err_times.append(datetime.now(timezone.utc).timestamp()) # type: ignore

    # ----------------------------- Pré-check symbole --------------------------
    def _symbol_precheck(self, symbol: str, volume: float, sl: Optional[float], tp: Optional[float]) -> Tuple[bool, str, Dict[str, Any]]:
        if mt5 is None:
            return False, "MT5 module unavailable", {}
        info = mt5.symbol_info(symbol)
        if info is None:
            return False, f"symbol_info({symbol}) is None", {}
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                return False, f"symbol_select({symbol}) failed", {}
        # contraintes volume
        vol_min, vol_max, vol_step = info.volume_min, info.volume_max, info.volume_step
        if volume < vol_min - 1e-12 or volume > vol_max + 1e-12:
            return False, f"Invalid volume {volume} (min {vol_min}, max {vol_max})", {"vol_min": vol_min, "vol_max": vol_max}
        # normaliser sur le step
        step_units = round((volume - vol_min) / vol_step) if vol_step > 0 else 0
        vol_norm = round(vol_min + step_units * vol_step, 8)
        # Soft check: ne pas bloquer si pas aligné, suggérer une correction
        meta: Dict[str, Any] = {"point": info.point or 0.0, "stops_level": getattr(info, "stops_level", 0) or 0, "vol_step": vol_step}
        if abs(vol_norm - volume) > 1e-8:
            meta["suggested_volume"] = vol_norm
            meta["warn"] = f"volume not aligned (step {vol_step})"
            return True, "WARN_VOLUME_STEP", meta
        # contraintes stops
        stops_level = getattr(info, "stops_level", 0) or 0
        point = info.point or 0.0
        # sl/tp trop proches ?
        if sl is not None and tp is not None and point > 0 and stops_level > 0:
            # pré-check sur distance minimale : on validera finement côté serveur
            pass
        meta["point"] = point
        meta["stops_level"] = stops_level
        return True, "OK", meta

    # ----------------------------- Table retcodes -----------------------------
    def _retcode_action(self, rc: int) -> str:
        """
        Retourne l'action à entreprendre:
        - 'retry_same' : retenter sans changer
        - 'refresh_price' : re-obtenir prix (requote/price_changed)
        - 'adjust_volume' : aligner au step
        - 'abort' : abandonner
        """
        if mt5 is None:
            return "abort"
        DONE = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
        PRICE_CHANGED = getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10032)
        REQUOTE = getattr(mt5, "TRADE_RETCODE_REQUOTE", 10031)
        REJECT = getattr(mt5, "TRADE_RETCODE_REJECT", 10004)
        BUSY = getattr(mt5, "TRADE_RETCODE_TRADE_CONTEXT_BUSY", 10002)
        INVALID_VOL = getattr(mt5, "TRADE_RETCODE_INVALID_VOLUME", 10030)
        INVALID_STOPS = getattr(mt5, "TRADE_RETCODE_INVALID_STOPS", 10027)
        NO_MONEY = getattr(mt5, "TRADE_RETCODE_NO_MONEY", 10019)
        MARKET_CLOSED = getattr(mt5, "TRADE_RETCODE_MARKET_CLOSED", 10018)
        if rc in (PRICE_CHANGED, REQUOTE):
            return "refresh_price"
        if rc in (BUSY,):
            return "retry_same"
        if rc in (INVALID_VOL,):
            return "adjust_volume"
        if rc in (INVALID_STOPS, REJECT, NO_MONEY, MARKET_CLOSED):
            return "abort"
        return "retry_same"

    # ---------------- Initialization / Login ----------------
    @classmethod
    def _initialize_if_needed(cls):
        global _SIM  # Déclaration globale une seule fois au début

        if cls._initialized:
            return

        # Si MT5 non disponible (Linux/WSL), activer dry-run automatiquement
        if mt5 is None or not MT5_AVAILABLE:
            logger.warning("[MT5] MetaTrader5 non disponible - Mode dry-run forcé")
            os.environ['MT5_DRY_RUN'] = '1'
            if _SIM is None:
                from utils.mt5_sim import MT5Sim
                _SIM = MT5Sim(balance=float(os.environ.get("MT5_SIM_BALANCE", "10000") or 10000))
            cls._initialized = True
            return

        if _use_sim():
            # init simulateur
            if _SIM is None:
                from utils.mt5_sim import MT5Sim
                _SIM = MT5Sim(balance=float(os.environ.get("MT5_SIM_BALANCE", "10000") or 10000))
            cls._initialized = True
            return
        if not hasattr(mt5, "initialize"):
            cls._initialized = True
            return
        ok = mt5.initialize()
        if not ok:
            error = mt5.last_error()
            raise RuntimeError(f"Échec mt5.initialize() - Code: {error}")
        cls._initialized = True



    @classmethod
    def _login_if_needed(cls, cfg=None):
        if cls._logged_in:
            return
        # En mode simulateur, pas de login réel
        if _use_sim():
            cls._logged_in = True
            return
        login    = (cfg or {}).get("login")    or os.environ.get("MT5_LOGIN")
        password = (cfg or {}).get("password") or os.environ.get("MT5_PASSWORD")
        server   = (cfg or {}).get("server")   or os.environ.get("MT5_SERVER")
        if not all([login, password, server]):
            raise RuntimeError("MT5 login info manquante (login/password/server).")
        if not hasattr(mt5, 'login'):
            cls._logged_in = True
            return
        ok = mt5.login(int(login), password=password, server=server)
        if not ok:
            raise RuntimeError("MT5 login échec.")
        cls._logged_in = True
    @classmethod
    def is_initialized(cls) -> bool:
        return bool(getattr(cls, "_initialized", False))
    
    @classmethod
    def initialize_if_needed(cls, login=None, password=None, server=None, *, force: bool=False):
        if cls.is_initialized() and not force:
            return True

        # Certaines bases définissent _initialize_if_needed() sans arguments,
        # d'autres avec (login, password, server). On gère les deux.
        try:
            # 1) Essayer SANS arguments
            cls._initialize_if_needed()
            return True
        except TypeError:
            # 2) Essayer en positionnel (login, password, server)
            try:
                cls._initialize_if_needed(login, password, server)
                return True
            except TypeError:
                raise TypeError(
                    "MT5Client._initialize_if_needed signature inattendue. "
                    "Attendu: () ou (login, password, server)."
                )
    @classmethod
    def shutdown_if_needed(cls):
        try:
            import MetaTrader5 as _mt5
            _mt5.shutdown()
        except Exception:
            pass
        cls._initialized = False

    def _ensure_initialized_and_login(self, cfg=None):
        # cfg prioritaire: arg -> self.cfg -> load_config()
        cfg = cfg or getattr(self, "cfg", None) or load_config()

        # Si MT5 n'est pas disponible (Linux/WSL), forcer dry-run
        if not MT5_AVAILABLE or _mt5 is None:
            logger.warning("[MT5] MetaTrader5 non disponible - Activation automatique du dry-run")
            os.environ['MT5_DRY_RUN'] = '1'
            MT5Client._initialize_if_needed()
            MT5Client._logged_in = True
            return

        # En simulateur, on initialise le faux client une fois
        if _use_sim():
            MT5Client._initialize_if_needed()
            MT5Client._logged_in = True
            return

        # 1) initialise le terminal (API de classe)
        MT5Client.initialize_if_needed()

        # 2) login via API de classe (en aplatissant la cfg globale -> {login,password,server})
        mt5_cfg = (cfg.get("mt5") or {})
        flat = {
            "login": mt5_cfg.get("account"),
            "password": mt5_cfg.get("password"),
            "server": mt5_cfg.get("server"),
        }
        MT5Client._login_if_needed(flat)

        # 3) (Option) cohérence: si info compte dispo et cfg fournie, on log l'état
        try:
            info = mt5.account_info() if mt5 is not None else None
            if info and flat["login"] and flat["server"]:
                if str(getattr(info, "login", "")) == str(flat["login"]) and \
                str(getattr(info, "server", "")) == str(flat["server"]):
                    logger.info(f"MT5 logged in: account={flat['login']} server={flat['server']}")
        except Exception:
            pass

    # ---------------- Symbol alias / resolution ----------------
    @staticmethod
    def resolve_symbol_name(symbol: str) -> str:
        """
        Mappe les symboles logiques vers les vrais tickers du broker si nécessaire.
        La plupart des symboles sont identiques chez le broker.
        """
        s = (symbol or "").upper()
        mapping = {
            "BTCUSD": "BTCUSD",
            "ETHUSD": "ETHUSD",
            "XAUUSD": "XAUUSD",
            "EURUSD": "EURUSD",
            "LTCUSD": "LTCUSD",
            "DJ30": "DJ30",
            "CL-OIL": "CL-OIL",
        }
        return mapping.get(s, s)

    def resolve_symbol(self, base: str) -> str:
        """
        Résout un symbole vers le symbole coté réel chez le broker.
        1) essaie l'alias mappé
        2) sinon teste le nom brut
        3) sinon scanne le catalogue pour une correspondance proche
        """
        if mt5 is None:
            return self.resolve_symbol_name(base)

        alias = self.resolve_symbol_name(base)
        try:
            if mt5.symbol_select(alias, True) and mt5.symbol_info_tick(alias):
                return alias
        except Exception:
            pass

        # fallback: tenter le nom brut
        try:
            if mt5.symbol_select(base, True) and mt5.symbol_info_tick(base):
                logger.info(f"[SYMBOL MAP] {base} -> {base}")
                return base
        except Exception:
            pass

        # scan global de secours
        try:
            infos = mt5.symbols_get() or []
            candidates = [s.name for s in infos if s.name.upper().startswith(alias.upper())]
            if not candidates:
                candidates = [s.name for s in infos if s.name.upper().startswith(base.upper())]
            for name in sorted(candidates):
                try:
                    if mt5.symbol_select(name, True) and mt5.symbol_info_tick(name):
                        logger.info(f"[SYMBOL MAP] {base} -> {name}")
                        return name
                except Exception:
                    continue
        except Exception:
            pass

        # En dernier recours: renvoyer l'alias même si pas tradable (la couche appelante gérera)
        return alias

    # Cache des symboles qui ont échoué pour éviter de spammer les logs
    _symbol_fail_cache: dict = {}
    _SYMBOL_FAIL_COOLDOWN: float = 300.0  # 5 minutes entre les logs d'erreur par symbole

    def ensure_symbol(self, symbol: str) -> bool:
        """
        Sélection idempotente & thread-safe du symbole réel.
        Retourne True si visible/sélectionné, False sinon.
        """
        import time
        real = self.resolve_symbol(symbol)
        if mt5 is None:
            return True
        with self._selected_lock:
            if real not in self._selected_global:
                try:
                    info = mt5.symbol_info(real)
                    if info and info.visible:
                        self._selected_global.add(real)
                        return True
                    if not mt5.symbol_select(real, True):
                        # Ne loguer qu'une fois toutes les 5 minutes par symbole
                        now = time.time()
                        last_fail = self._symbol_fail_cache.get(real, 0)
                        if now - last_fail > self._SYMBOL_FAIL_COOLDOWN:
                            logger.warning(f"Impossible de sélectionner {real}: {mt5.last_error()}")
                            self._symbol_fail_cache[real] = now
                        return False
                    self._selected_global.add(real)
                    logger.info(f"Symbol {real} selected for trading")
                except Exception as e:
                    now = time.time()
                    last_fail = self._symbol_fail_cache.get(real, 0)
                    if now - last_fail > self._SYMBOL_FAIL_COOLDOWN:
                        logger.warning(f"ensure_symbol({real}) échec: {e}")
                        self._symbol_fail_cache[real] = now
                    return False
        return True

    # ---------------- Timeframe helpers ----------------
    @staticmethod
    def parse_timeframe(tf) -> int:
        """
        Accepte 'M1','M5','M15','M30','H1','H4','D1','W1','MN1' ou un int mt5.TIMEFRAME_*.
        Retourne toujours une constante TIMEFRAME_* MetaTrader5.
        """
        if mt5 is None:
            # valeur par défaut si MetaTrader5 indispo (pour tests hors terminal)
            return 1
        if tf is None:
            return mt5.TIMEFRAME_M15
        if isinstance(tf, int):
            return tf
        s = str(tf).strip().upper()
        table = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }
        return table.get(s, mt5.TIMEFRAME_M15)

    # ---------------- OHLC / Market data ----------------
    def fetch_ohlc(self, symbol: str, tf_code, count: int = 500):
        """
        Retourne l'array numpy struct MT5 depuis copy_rates_from_pos (brut).
        Agents plus modernes préfèrent get_rates() qui normalise en List[dict].
        """
        real = self.resolve_symbol(symbol)
        self.ensure_symbol(real)
        if mt5 is None:
            return []
        data = mt5.copy_rates_from_pos(real, int(tf_code), 0, int(count))
        if data is None:
            return []
        try:
            if getattr(data, "size", 0) == 0:
                return []
        except Exception:
            pass
        return data

    def get_rates(self, symbol: str, timeframe: str, count: int = 1) -> List[Dict[str, Any]]:
        """
        Retourne une LISTE DE DICTS: time, open, high, low, close, tick_volume, real_volume, spread.
        Utile pour DataFrame/JSON/débogage multi-plateformes.
        """
        real = self.resolve_symbol(symbol)
        self.ensure_symbol(real)
        if mt5 is None:
            return []

        tf = self.parse_timeframe(timeframe)
        data = mt5.copy_rates_from_pos(real, tf, 0, int(count))
        if data is None:
            return []

        try:
            names = tuple(getattr(data, "dtype", None).names or ())
            if names:
                out: List[Dict[str, Any]] = []
                for row in data:
                    d: Dict[str, Any] = {}
                    for k in ("time", "open", "high", "low", "close", "tick_volume", "real_volume", "spread"):
                        if k in names:
                            v = row[k]
                            if k == "time":
                                try:
                                    v = int(v)
                                except Exception:
                                    pass
                            elif k in ("tick_volume", "real_volume", "spread"):
                                try:
                                    v = int(v)
                                except Exception:
                                    pass
                            else:
                                try:
                                    v = float(v)
                                except Exception:
                                    pass
                            d[k] = v
                    out.append(d)
                return out
        except Exception:
            pass

        # Fallback: cast grossier
        try:
            return list(data)  # type: ignore
        except Exception:
            return []

    def get_tick(self, symbol: str):
        real = self.resolve_symbol(symbol)
        self.ensure_symbol(real)
        if mt5 is None:
            return None
        return mt5.symbol_info_tick(real)

    def symbol_info_tick(self, symbol: str):
        """
        Wrapper attendu par l'orchestrateur.
        Retourne l'objet tick MetaTrader5 (avec .bid/.ask/.time), ou None si indisponible.
        """
        real = self.resolve_symbol(symbol)
        try:
            self.ensure_symbol(real)
        except Exception:
            pass
        if mt5 is None:
            return None
        try:
            return mt5.symbol_info_tick(real)
        except Exception:
            return None

    def symbol_info(self, symbol: str):
        """
        Wrapper attendu par l'orchestrateur.
        Retourne l'objet symbol_info MetaTrader5, ou None si indisponible.
        """
        real = self.resolve_symbol(symbol)
        try:
            self.ensure_symbol(real)
        except Exception:
            pass
        if mt5 is None:
            return None
        try:
            return mt5.symbol_info(real)
        except Exception:
            return None


    def get_last_price(self, symbol: str, side: str = "BUY") -> Optional[float]:
        """
        Prix récent: ask (BUY) / bid (SELL) / mid si both, sinon close dernière barre M1.
        """
        real = self.resolve_symbol(symbol)
        try:
            self.ensure_symbol(real)
        except Exception:
            pass

        if mt5 is not None:
            tick = mt5.symbol_info_tick(real)
            if tick:
                side = (side or "BUY").upper()
                bid = getattr(tick, "bid", None)
                ask = getattr(tick, "ask", None)
                if side == "BUY" and ask is not None:
                    try:
                        return float(ask)
                    except Exception:
                        pass
                if side != "BUY" and bid is not None:
                    try:
                        return float(bid)
                    except Exception:
                        pass
                if bid is not None and ask is not None:
                    try:
                        return (float(bid) + float(ask)) / 2.0
                    except Exception:
                        pass

            # Fallback: close dernière barre M1
            bars = self.get_rates(real, "M1", count=1)
            if bars:
                last = bars[-1]
                if isinstance(last, dict) and "close" in last:
                    try:
                        return float(last["close"])
                    except Exception:
                        pass
        return None

    def get_account_info(self):
        try:
            return mt5.account_info() if mt5 is not None else None
        except Exception:
            return None

    # ---------------- Stops helpers ----------------
    def _min_stop_distance_points(self, symbol: str) -> float:
        """
        Distance minimale (en points broker) à respecter pour SL/TP,
        basée sur stops_level et freeze_level du symbole.

        Applique une distance minimale de sécurité par type d'actif pour éviter
        les erreurs 10016 (INVALID_STOPS) même si stops_level=0.
        """
        if mt5 is None:
            return 100.0  # Fallback sécuritaire

        try:
            real_symbol = self.resolve_symbol(symbol)
            info = mt5.symbol_info(real_symbol)

            # Récupérer stops_level et freeze_level du broker
            level  = float(getattr(info, "stops_level", 0) or 0)
            freeze = float(getattr(info, "freeze_level", 0) or 0)
            broker_min = max(level, freeze, 0.0)

            # Distances minimales de sécurité par type d'actif
            # (appliquées même si stops_level=0)
            symbol_upper = symbol.upper()
            safety_mins = {
                # FOREX : minimum 10 pips (100 points pour 5 digits)
                'EURUSD': 100, 'GBPUSD': 100, 'USDJPY': 100,
                'AUDUSD': 100, 'USDCAD': 100, 'NZDUSD': 100,

                # CRYPTOS : minimum 50 points (ajusté selon volatilité)
                'BTCUSD': 50, 'ETHUSD': 50, 'LTCUSD': 50,
                'BNBUSD': 50, 'ADAUSD': 50, 'SOLUSD': 50,

                # INDICES : minimum 50 points
                'DJ30': 50, 'NAS100': 50, 'GER40': 50, 'SPX500': 50,

                # MATIÈRES : minimum 50 points
                'XAUUSD': 50, 'XAGUSD': 50, 'CL-OIL': 50, 'UKOIL': 50,
            }

            # Détection automatique par préfixe si symbole non listé
            if symbol_upper not in safety_mins:
                if any(symbol_upper.startswith(prefix) for prefix in ['XAU', 'XAG', 'XPT', 'XPD']):
                    safety_mins[symbol_upper] = 50  # Métaux précieux
                elif 'USD' in symbol_upper or 'EUR' in symbol_upper or 'GBP' in symbol_upper:
                    safety_mins[symbol_upper] = 100  # Forex
                elif any(symbol_upper.startswith(prefix) for prefix in ['BTC', 'ETH', 'SOL', 'ADA']):
                    safety_mins[symbol_upper] = 50  # Cryptos
                else:
                    safety_mins[symbol_upper] = 100  # Défaut sécuritaire

            safety_min = safety_mins.get(symbol_upper, 100)

            # Retourner le maximum entre broker_min et safety_min
            final_min = max(broker_min, safety_min)

            logger.debug(f"[MT5] Min stops for {symbol}: broker={broker_min} safety={safety_min} final={final_min}")
            return final_min

        except Exception as e:
            logger.warning(f"[MT5] _min_stop_distance_points error for {symbol}: {e}")
            return 100.0  # Fallback sécuritaire

    def _respect_min_stops(self, symbol: str, side: int, price: float, sl: Optional[float], tp: Optional[float]):
        """
        Ajuste SL/TP pour respecter la distance minimale.
        side: 1 = BUY, -1 = SELL
        """
        if sl is None and tp is None:
            return sl, tp

        point = 0.01
        if mt5 is not None:
            try:
                info = mt5.symbol_info(self.resolve_symbol(symbol))
                point = float(getattr(info, "point", 0.01) or 0.01)
            except Exception:
                pass

        min_dist = self._min_stop_distance_points(symbol) * point

        def adj(target, is_sl):
            if target is None:
                return None
            if side == 1:  # BUY
                if is_sl and target > price - min_dist:
                    return price - min_dist
                if (not is_sl) and target < price + min_dist:
                    return price + min_dist
            else:          # SELL
                if is_sl and target < price + min_dist:
                    return price + min_dist
                if (not is_sl) and target > price - min_dist:
                    return price - min_dist
            return target

        return adj(sl, True), adj(tp, False)

    # ---------------- Orders ----------------
    def _candidate_fillings(self, symbol: str) -> List[int]:
        """
        Renvoie une liste d'ORDER_FILLING_* à essayer, en priorisant
        les modes supportés par le broker pour ce symbole.

        filling_mode est un MASQUE BINAIRE:
        - bit 0 (valeur 1): FOK supporté
        - bit 1 (valeur 2): IOC supporté
        - bit 2 (valeur 4): RETURN supporté
        """
        if mt5 is None:
            return [1]  # IOC par défaut

        modes: List[int] = []
        try:
            info = mt5.symbol_info(self.resolve_symbol(symbol))
            filling_mask = int(getattr(info, "filling_mode", 0) or 0)

            # Décoder le masque binaire - prioriser IOC car plus courant
            if filling_mask & 2:  # IOC supporté (bit 1)
                modes.append(int(getattr(mt5, "ORDER_FILLING_IOC", 1)))
            if filling_mask & 4:  # RETURN supporté (bit 2)
                modes.append(int(getattr(mt5, "ORDER_FILLING_RETURN", 2)))
            if filling_mask & 1:  # FOK supporté (bit 0)
                modes.append(int(getattr(mt5, "ORDER_FILLING_FOK", 0)))
        except Exception:
            pass

        # Fallback si rien trouvé: IOC en premier (le plus courant)
        if not modes:
            modes = [
                int(getattr(mt5, "ORDER_FILLING_IOC", 1)),
                int(getattr(mt5, "ORDER_FILLING_RETURN", 2)),
                int(getattr(mt5, "ORDER_FILLING_FOK", 0)),
            ]

        return modes

    def _normalize_volume(self, symbol: str, volume: float) -> float:
        """
        Aligne le volume sur les contraintes broker (min, max, step) en TRONQUANT au pas
        pour éviter INVALID_VOLUME (retcode 10030).
        """
        vmin, vstep, vmax = 0.01, 0.01, 100.0
        real = self.resolve_symbol(symbol)
        if mt5 is not None:
            try:
                info = mt5.symbol_info(real)
                vmin  = float(getattr(info, "volume_min",  0.01) or 0.01)
                vstep = float(getattr(info, "volume_step", 0.01) or 0.01)
                vmax  = float(getattr(info, "volume_max",  100.0) or 100.0)
            except Exception:
                pass

        # garde-fous
        v = max(float(volume), vmin)
        if vstep > 0:
            # TRONQUE au nombre entier de steps (évite les arrondis binaires)
            steps = math.floor((v - vmin + 1e-12) / vstep)
            v = vmin + steps * vstep
            # si on est retombé sous vmin à cause d’une très petite value -> remonte à vmin
            if v < vmin:
                v = vmin
        if v > vmax:
            v = vmax
        # protection floating pour 0.30000000004
        v = round(v, 3) if vstep >= 0.001 else round(v, 2)
        return float(v)


    def _osr_to_dict(self, res) -> dict:
        """
        Normalise un OrderSendResult MT5 en dict tolérant aux attributs manquants.
        Ajoute 'ok', 'retcode', 'order', 'deal', 'comment', etc. et conserve la réponse brute sous '_raw'.
        """
        d = {}
        try:
            d["retcode"] = int(getattr(res, "retcode", -1) or -1)
            d["order"] = getattr(res, "order", None)
            d["deal"] = getattr(res, "deal", None)
            d["comment"] = getattr(res, "comment", "") or ""
            d["request_id"] = getattr(res, "request_id", None)
            d["volume"] = getattr(res, "volume", None)
            d["price"] = getattr(res, "price", None)
            d["ask"] = getattr(res, "ask", None)
            d["bid"] = getattr(res, "bid", None)
            ok_done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            ok_part = getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
            d["ok"] = d["retcode"] in (ok_done, ok_part)
        except Exception:
            d.setdefault("retcode", -1)
            d.setdefault("ok", False)
        d["_raw"] = res
        return d
    
    def _log_volume_rules(self, symbol: str):
        real = self.resolve_symbol(symbol)
        if mt5 is None:
            logger.info(f"[VOL] {symbol} (no mt5)")
            return
        try:
            info = mt5.symbol_info(real)
            vmin  = float(getattr(info, "volume_min",  0.01) or 0.01)
            vstep = float(getattr(info, "volume_step", 0.01) or 0.01)
            vmax  = float(getattr(info, "volume_max",  100.0) or 100.0)
            logger.info(f"[VOL] {symbol}->{real} rules: min={vmin}, step={vstep}, max={vmax}")
        except Exception as e:
            logger.info(f"[VOL] {symbol} rules: error {e}")

    def _is_market_open(self, symbol: str) -> Tuple[bool, str]:
        """
        Vérifie si le marché est ouvert pour le symbole donné.
        Retourne (is_open: bool, reason: str)

        Règles par type d'actif :
        - FOREX : Lundi 00:00 - Vendredi 22:00 UTC
        - CRYPTO : 24/7 (toujours ouvert)
        - INDICES : Heures spécifiques selon la région
        - MATIÈRES : Lundi-Vendredi avec horaires spécifiques
        """
        from datetime import datetime, timezone

        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()  # 0=Lundi, 6=Dimanche
        hour = now_utc.hour

        symbol_upper = symbol.upper()

        # CRYPTO : 24/7
        crypto_symbols = ['BTC', 'ETH', 'LINK', 'BNB', 'ADA', 'SOL', 'XRP', 'DOGE', 'MATIC']
        if any(crypto in symbol_upper for crypto in crypto_symbols):
            return True, "crypto_24_7"

        # Week-end complet (Samedi + Dimanche avant 22h UTC)
        if weekday == 5:  # Samedi
            return False, f"saturday_closed (weekday={weekday})"
        if weekday == 6 and hour < 22:  # Dimanche avant 22h
            return False, f"sunday_closed_before_22h (weekday={weekday}, hour={hour})"

        # FOREX : Lundi 00:00 - Vendredi 22:00 UTC
        forex_pairs = ['EUR', 'GBP', 'USD', 'JPY', 'CHF', 'AUD', 'NZD', 'CAD']
        if any(pair in symbol_upper for pair in forex_pairs):
            # Vendredi après 22h UTC → fermé
            if weekday == 4 and hour >= 22:
                return False, f"friday_after_22h (weekday={weekday}, hour={hour})"
            return True, "forex_open"

        # INDICES US (DJ30, NAS100, SPX500)
        us_indices = ['DJ30', 'NAS100', 'SPX500', 'USTEC']
        if any(idx in symbol_upper for idx in us_indices):
            # Lundi-Vendredi, session principale 14:30-21:00 UTC
            if weekday >= 5:  # Week-end
                return False, f"weekend_closed (weekday={weekday})"
            # En semaine mais hors heures (simplifié - trading 24h sur certains brokers)
            # On accepte trading 24h pour les indices CFD
            return True, "us_index_open"

        # INDICES EU (GER40, UK100, FRA40)
        eu_indices = ['GER40', 'GER30', 'DAX', 'UK100', 'FTSE', 'FRA40', 'CAC']
        if any(idx in symbol_upper for idx in eu_indices):
            if weekday >= 5:  # Week-end
                return False, f"weekend_closed (weekday={weekday})"
            # Session EU : 07:00-16:30 UTC (simplifié - acceptons 24h pour CFD)
            return True, "eu_index_open"

        # MATIÈRES (XAUUSD, XAGUSD, USOIL)
        commodities = ['XAU', 'XAG', 'OIL', 'BRENT', 'NATGAS', 'COPPER']
        if any(cmd in symbol_upper for cmd in commodities):
            # Or/Argent : Lundi-Vendredi (comme Forex)
            if weekday >= 5:
                return False, f"weekend_closed (weekday={weekday})"
            if weekday == 4 and hour >= 22:  # Vendredi après 22h
                return False, f"friday_after_22h (weekday={weekday}, hour={hour})"
            return True, "commodity_open"

        # Défaut : considérer ouvert (pour ne pas bloquer de nouveaux symboles)
        logger.warning(f"[MT5] Unknown symbol type for {symbol}, assuming market is open")
        return True, "unknown_symbol_assumed_open"

    def _symbol_precheck(self, symbol: str, volume: float, sl: Optional[float], tp: Optional[float]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Wrapper interne pour harmoniser l'appel depuis place_order.
        S'appuie sur la fonction module _precheck_symbol(symbol) et renvoie (ok, msg, meta).
        """
        ok, msg = _precheck_symbol(symbol)
        return ok, msg, {}

    def place_order(
        self,
        symbol: str,
        side: str,
        volume: float,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
        deviation: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Envoie un ordre marché (DEAL) BUY/SELL.
        - deviation : slippage toléré en points (si None, pris depuis la config execution.slippage_points)
        - **kwargs  : paramètres MT5 optionnels à injecter dans la requête (type_filling, type_time, expiration, etc.)
        """
        if getattr(self, "dry_run", False):
            return {"retcode": 0, "order": None, "dry_run": True}

        if mt5 is None:
            return {"ok": False, "error": "MT5 module unavailable"}

        ex = self._exec_cfg(symbol)

        # Circuit breaker
        if not self._cb_allow(ex["cb_window"], ex["cb_max_errors"]):
            return {"ok": False, "error": "circuit_breaker_open"}

        # Vérification horaires de marché (évite retcode 10018 MARKET_CLOSED)
        is_open, market_reason = self._is_market_open(symbol)
        if not is_open:
            logger.warning(f"[MT5] Market closed for {symbol}: {market_reason}")
            return {"ok": False, "error": "market_closed", "reason": market_reason, "symbol": symbol}

        # Pré-checks symbole/volume
        ok, msg, meta = self._symbol_precheck(symbol, volume, sl, tp)
        if not ok:
            logger.warning(f"[MT5] precheck failed: {msg} | meta={meta}")
            return {"ok": False, "error": f"precheck:{msg}", "meta": meta}
        # Si le pré-check suggère un volume corrigé, on l'applique avant l'envoi
        if isinstance(meta, dict) and "suggested_volume" in meta:
            volume = float(meta["suggested_volume"])
        order_type = mt5.ORDER_TYPE_BUY if side.upper() == "BUY" else mt5.ORDER_TYPE_SELL

        side_sign = 1 if order_type == mt5.ORDER_TYPE_BUY else -1

        # Normalise le volume selon les contraintes broker (min/max/step)
        volume = self._normalize_volume(symbol, float(volume))

        # Ajuste SL/TP pour respecter la distance minimale exigée par le broker
        adj_sl, adj_tp = sl, tp
        base_price = float(price) if price is not None else None
        if adj_sl is not None or adj_tp is not None:
            if base_price is None:
                tick = self.symbol_info_tick(symbol)
                if tick:
                    try:
                        base_price = float(tick.ask if side_sign == 1 else tick.bid)
                    except Exception:
                        base_price = None
            if base_price is None:
                try:
                    base_price = float(self.get_last_price(symbol, side=side))
                except Exception:
                    base_price = None
            if base_price is not None:
                adj_sl, adj_tp = self._respect_min_stops(
                    symbol, side_sign, float(base_price), adj_sl, adj_tp
                )

        sl = adj_sl
        tp = adj_tp

        duplicate_window = float((self.cfg.get('execution') or {}).get('duplicate_window_seconds', 1.5))
        signature = (
            symbol.upper(),
            side.upper(),
            round(float(volume or 0.0), 6),
            round(float(price), 5) if price is not None else None,
            round(float(sl), 5) if sl is not None else None,
            round(float(tp), 5) if tp is not None else None,
            (comment or '').strip(),
        )
        now_ts = time.time()
        queue = getattr(self, '_recent_orders', None)
        if queue is None:
            queue = self._recent_orders = deque(maxlen=128)
        while queue and now_ts - queue[0][1] > duplicate_window:
            queue.popleft()
        if any(entry[0] == signature for entry in queue):
            return {"ok": False, "error": "duplicate_order_suppressed", "request": signature}
        queue.append((signature, now_ts))

        # Slippage (points)
        dev_points = int(deviation) if deviation is not None else int(ex["slippage_points"])

        # Récupérer le prix actuel si non fourni (OBLIGATOIRE pour TRADE_ACTION_DEAL)
        tick = self.symbol_info_tick(symbol)
        if price is None:
            if tick:
                if order_type == mt5.ORDER_TYPE_BUY:
                    price = float(getattr(tick, "ask", 0.0))
                else:
                    price = float(getattr(tick, "bid", 0.0))
            if not price or price <= 0:
                logger.error(f"[MT5] Cannot get price for {symbol} - order aborted")
                return {"ok": False, "error": "no_price", "symbol": symbol}

        # Récupérer le nombre de décimales (digits) pour arrondir correctement
        digits = 5  # Valeur par défaut
        info = self.symbol_info(symbol)
        if info:
            digits = int(getattr(info, "digits", 5) or 5)

        # Arrondir prix, SL, TP au bon nombre de décimales
        price = round(float(price), digits)
        if sl is not None:
            sl = round(float(sl), digits)
        if tp is not None:
            tp = round(float(tp), digits)

        # Payload MT5
        request: Dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "type": order_type,
            "volume": float(volume),
            "price": price,  # TOUJOURS inclure le prix
            "deviation": dev_points,
            "magic": 0,
            "comment": comment[:30] if comment else "",
        }
        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp

        # Champs optionnels explicitement passés par l'appelant (ex: type_filling)
        # On limite aux clés MT5 usuelles pour éviter d’injecter n’importe quoi.
        allowed_extra = {"type_filling", "type_time", "expiration"}
        for k, v in kwargs.items():
            if k in allowed_extra:
                request[k] = v

        # Retry/Backoff
        backoffs = list(ex["backoff_seconds"]) if ex["backoff_seconds"] else [0.5]
        tries = 0

        # Ajouter type_filling si non spécifié (crucial pour éviter 10030)
        if "type_filling" not in request:
            fillings = self._candidate_fillings(symbol)
            if fillings:
                request["type_filling"] = fillings[0]

        while True:
            tries += 1

            # Log détaillé avant envoi
            if tries == 1:
                logger.info(f"[MT5] ORDER_SEND {symbol} {side} vol={request.get('volume')} "
                           f"price={request.get('price')} sl={request.get('sl')} tp={request.get('tp')} "
                           f"filling={request.get('type_filling')} dev={request.get('deviation')}")

            try:
                # Simulation ou réel
                if _use_sim():
                    global _SIM
                    res = _SIM.order_send(request)
                else:
                    res = mt5.order_send(request)
            except Exception as e:
                self._cb_note_error()
                logger.exception("[MT5] order_send raised")
                return {"ok": False, "error": f"exception:{e}", "request": request}

            # Supporte l’objet SimOrderResult ou objet natif mt5
            rc = int(getattr(res, "retcode", getattr(res, "retcode", -1)))
            if rc == getattr(mt5, "TRADE_RETCODE_DONE", 10009):
                order_id = getattr(res, "order", None)
                deal_id  = getattr(res, "deal", None)
                return {"ok": True, "retcode": rc, "order": order_id, "deal": deal_id}

            action = self._retcode_action(rc)
            logger.warning(f"[MT5] retcode={rc} action={action} try={tries}/{ex['max_retries']}")

            if action == "refresh_price" and ex["price_refresh_on_requote"]:
                tick = mt5.symbol_info_tick(symbol)
                if tick:
                    request["price"] = float(tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid)

            elif action == "adjust_volume":
                info = mt5.symbol_info(symbol)
                if info:
                    step = info.volume_step or 0.0
                    vmin = info.volume_min or 0.0
                    units = round((float(request["volume"]) - vmin) / step) if step > 0 else 0
                    request["volume"] = round(vmin + units * step, 8)

            elif action == "abort":
                self._cb_note_error()
                return {"ok": False, "retcode": rc, "error": "abort", "request": request}

            # Limite d’essais
            if tries >= ex["max_retries"]:
                self._cb_note_error()
                return {"ok": False, "retcode": rc, "error": "max_retries", "request": request}

            # Backoff progressif
            delay = backoffs[min(tries - 1, len(backoffs) - 1)]
            time.sleep(delay)

    def close_positions(
        self,
        symbol: str,
        comment: str = "",
        deviation: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Ferme toutes les positions ouvertes pour un symbole donné et retourne la liste des résultats.
        """
        results: List[Dict[str, Any]] = []
        if mt5 is None:
            return results

        ex = self._exec_cfg(symbol)
        dev_points = int(deviation) if deviation is not None else int(ex.get("slippage_points", 10))

        real = self.resolve_symbol(symbol)
        try:
            self.ensure_symbol(real)
        except Exception:
            pass

        try:
            positions = mt5.positions_get(symbol=real)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"[MT5] close_positions positions_get failed: {e}")
            return results

        if not positions:
            return results

        buy_type = getattr(mt5, "ORDER_TYPE_BUY", 0)
        sell_type = getattr(mt5, "ORDER_TYPE_SELL", 1)
        action_deal = getattr(mt5, "TRADE_ACTION_DEAL", 1)

        for pos in positions:
            try:
                volume = float(getattr(pos, "volume", 0.0) or 0.0)
                if volume <= 0:
                    continue
                ticket = int(getattr(pos, "ticket", 0) or 0)
                pos_type = int(getattr(pos, "type", 0) or 0)
                order_type = sell_type if pos_type == buy_type else buy_type

                price = None
                try:
                    tick = mt5.symbol_info_tick(real)  # type: ignore[attr-defined]
                except Exception:
                    tick = None
                if tick:
                    try:
                        price = float(tick.ask if order_type == buy_type else tick.bid)
                    except Exception:
                        price = None

                request: Dict[str, Any] = {
                    "action": action_deal,
                    "symbol": real,
                    "type": order_type,
                    "position": ticket,
                    "volume": float(volume),
                    "deviation": dev_points,
                    "magic": 0,
                    "comment": (comment or "")[:30],
                }
                if price is not None:
                    request["price"] = price

                try:
                    if _use_sim():
                        global _SIM
                        res = _SIM.order_send(request)  # type: ignore[attr-defined]
                    else:
                        res = mt5.order_send(request)  # type: ignore[attr-defined]
                except Exception as e:
                    logger.warning(f"[MT5] close_positions order_send failed: {e}")
                    continue

                res_dict = self._osr_to_dict(res)
                res_dict["position"] = ticket
                results.append(res_dict)
            except Exception as e:
                logger.warning(f"[MT5] close_positions error: {e}")

        return results

