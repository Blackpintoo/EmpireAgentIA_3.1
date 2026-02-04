# orchestrator/orchestrator.py
import asyncio
import importlib
import time
import os
import json
import threading
import inspect
from typing import Dict, Any, List, Optional, Tuple, Callable
from datetime import datetime, timezone, timedelta
from utils.news_filter import is_frozen_now
from zoneinfo import ZoneInfo
import pytz
import pandas as pd
import pathlib
try:
    import MetaTrader5 as _mt5
except Exception:
    _mt5 = None
import requests
import yaml
import csv
import subprocess
import sys
import types as _types
try:
    # cas 1 : config_loader.py à la racine du projet
    from config_loader import load_dotenv_env, get_required  # type: ignore
except Exception:
    try:
        # cas 2 : utils/config_loader.py
        from utils.config_loader import load_dotenv_env, get_required  # type: ignore
    except Exception:
        # fallback no-op (utile en tests unitaires qui n’ont pas besoin de .env)
        def load_dotenv_env(*args, **kwargs):  # type: ignore
            return {}
        def get_required(*keys):  # type: ignore
            return {}

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
# Garantit un event loop même en contexte test
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
from apscheduler.schedulers.base import SchedulerAlreadyRunningError
from utils.order_result import to_dict as order_res_dict, get as order_res_get
from utils.position_manager import PositionManager  # type: ignore
from utils.config import get_symbol_profile, get_enabled_symbols, is_symbol_active_now, load_config, reload_global_config
from utils.logger import logger
from utils.mt5_client import MT5Client
from utils.performance_tracker import PerformancePoint, default_tracker
from utils.risk_manager import RiskManager
from utils.gating import load_thresholds_for, should_allow_trade
from utils.digest import daily_digest_for, format_digest_message
from reporting.daily_digest import send_daily_digest
from utils.live_metrics import should_allow_live, rolling_metrics
from utils.audit import append as audit_append
from utils.health import start_health_server
from agents.whale_agent import WhaleAgent
from utils.whale_scoring import ewma
from utils.metrics import record_whale_trust_ewma, record_whale_pf
from optimization.optimizer import optimize_agent
# PHASE 4: Import AssetManager pour configuration par type d'actif
from utils.asset_manager import get_asset_manager
# OPTIMISATION 2025-12-13: Import du filtre de volatilité
try:
    from utils.volatility_filter import should_trade_volatility, VolatilityConfig
except Exception:
    should_trade_volatility = None  # type: ignore
    VolatilityConfig = None  # type: ignore

# OPTIMISATION 2025-12-13: Import des outils d'analyse avancés
try:
    from agents.volume_profile import VolumeProfileAgent, create_volume_profile_agent
except Exception:
    VolumeProfileAgent = None  # type: ignore
    create_volume_profile_agent = None  # type: ignore

try:
    from utils.market_regime import MarketRegimeDetector, detect_market_regime, MarketRegime
except Exception:
    MarketRegimeDetector = None  # type: ignore
    detect_market_regime = None  # type: ignore
    MarketRegime = None  # type: ignore

try:
    from utils.mtf_confluence import MTFConfluenceAnalyzer, analyze_mtf_confluence
except Exception:
    MTFConfluenceAnalyzer = None  # type: ignore
    analyze_mtf_confluence = None  # type: ignore

try:
    from utils.advanced_sentiment import AdvancedSentimentAnalyzer, analyze_advanced_sentiment
except Exception:
    AdvancedSentimentAnalyzer = None  # type: ignore
    analyze_advanced_sentiment = None  # type: ignore

try:
    from utils.inter_market_correlation import InterMarketCorrelationAnalyzer, analyze_inter_market_correlation
except Exception:
    InterMarketCorrelationAnalyzer = None  # type: ignore
    analyze_inter_market_correlation = None  # type: ignore

# PHASE 1 (2025-12-17): Event Guard - Protection contre annonces économiques
try:
    from utils.event_guard import get_event_guard, is_trade_blocked_by_event, EventGuard
except Exception:
    get_event_guard = None  # type: ignore
    is_trade_blocked_by_event = None  # type: ignore
    EventGuard = None  # type: ignore

# PHASE 2 (2025-12-25): Economic Calendar - Gestion amelioree des news
try:
    from utils.economic_calendar import should_avoid_trading as econ_should_avoid_trading
    ECONOMIC_CALENDAR_AVAILABLE = True
except Exception:
    econ_should_avoid_trading = None  # type: ignore
    ECONOMIC_CALENDAR_AVAILABLE = False

# PHASE 3 (2025-12-17): Score Composite - Unification de tous les signaux
try:
    from utils.composite_score import (
        get_composite_calculator,
        calculate_composite_score,
        CompositeScoreCalculator,
        CompositeResult
    )
    COMPOSITE_SCORE_AVAILABLE = True
except Exception:
    get_composite_calculator = None  # type: ignore
    calculate_composite_score = None  # type: ignore
    CompositeScoreCalculator = None  # type: ignore
    CompositeResult = None  # type: ignore
    COMPOSITE_SCORE_AVAILABLE = False

# PHASE 4 (2025-12-17): Inter-Market Guard - Blocage si contre flux macro
try:
    from utils.inter_market_guard import (
        get_inter_market_guard,
        is_trade_blocked_by_inter_market,
        InterMarketGuard
    )
    INTER_MARKET_GUARD_AVAILABLE = True
except Exception:
    get_inter_market_guard = None  # type: ignore
    is_trade_blocked_by_inter_market = None  # type: ignore
    InterMarketGuard = None  # type: ignore
    INTER_MARKET_GUARD_AVAILABLE = False

# AUDIT 2025-12-27: Trade Outcome Tracker - Feedback loop P&L réel
try:
    from utils.trade_outcome_tracker import start_outcome_tracking, get_outcome_stats
    OUTCOME_TRACKER_AVAILABLE = True
except Exception:
    start_outcome_tracking = None  # type: ignore
    get_outcome_stats = None  # type: ignore
    OUTCOME_TRACKER_AVAILABLE = False

# AUDIT 2025-12-27: Loss Pattern Analyzer - Analyse des trades perdants
try:
    from utils.loss_pattern_analyzer import get_loss_analyzer
    LOSS_ANALYZER_AVAILABLE = True
except Exception:
    get_loss_analyzer = None  # type: ignore
    LOSS_ANALYZER_AVAILABLE = False

try:
    from connectors.whale_feeds.onchain_listener import OnchainListener
except Exception:  # pragma: no cover
    OnchainListener = None  # type: ignore
try:
    from connectors.whale_feeds.cex_tracker import CexTracker
except Exception:  # pragma: no cover
    CexTracker = None  # type: ignore
try:
    from connectors.whale_feeds.social_verifier import SocialVerifier
except Exception:  # pragma: no cover
    SocialVerifier = None  # type: ignore

OVERRIDES_PATH: Optional[str] = None
CONFIG_PATH = pathlib.Path("config") / "config.yaml"

# =============================================================================
# Crypto bucket guard (BTC, ETH, LTC, BNB, ADA, SOL) - Mis à jour 2025-12-05
# =============================================================================
# Canoniques (profiles.yaml)
CRYPTO_CANON = {"BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "ADAUSD", "SOLUSD"}
# Noms Broker/MT5 (positions_get renvoie souvent les noms broker)
CRYPTO_REAL  = {"BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "ADAUSD", "SOLUSD"}

def _is_crypto_canon(s: str) -> bool:
    return (s or "").upper() in CRYPTO_CANON

def _is_crypto_real(s: str) -> bool:
    return (s or "").upper() in CRYPTO_REAL

def _to_canon(s_real: str) -> str:
    """Map broker symbol -> canonical profiles.yaml symbol."""
    s = (s_real or "").upper()
    # Pas de mapping spécial pour LTCUSD (même nom chez le broker)
    return s
# =============================================================================
# Helpers symbol mapping
# =============================================================================
def canon_to_broker(sym: str) -> str:
    """Map symbol canonique (profiles.yaml) -> symbole broker MT5."""
    s = (sym or "").upper()
    # Pas de mapping spécial pour LTCUSD (même nom chez le broker)
    return s

def broker_to_canon(sym: str) -> str:
    s = (sym or "").upper()
    # Pas de mapping spécial pour LTCUSD (même nom chez le broker)
    return s

# NOTE: _crypto_bucket_risk_used est définie plus bas (ligne ~430) avec la signature (get_profile) -> float

# =============================================================================
# Telegram: résolution auto d’un "sender" + long-polling des callbacks
# =============================================================================
def _load_tg_cfg():
    path = os.path.join("config", "config.yaml")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    tg = data.get("telegram") or {}
    token = tg.get("token") or tg.get("bot_token")
    chat_id = tg.get("chat_id")
    return token, chat_id

def _send_buttons_direct(text: str, buttons, *, kind: str = "trade_validation") -> bool:
    """Envoi inline-keys direct via l’API Telegram si le wrapper n’expose pas les boutons."""
    try:
        token, chat_id = _load_tg_cfg()
        if not (token and chat_id):
            return False
        kb = {
            "inline_keyboard": [[
                {"text": b.get("text", "?"), "callback_data": b.get("callback_data", "")}
                for b in buttons
            ]]
        }
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": json.dumps(kb, ensure_ascii=False),
            "disable_web_page_preview": True,
        }
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data=payload, timeout=10)
        return True
    except Exception:
        return False

def _resolve_tg_sender() -> Optional[Callable[..., Any]]:
    """
    Retourne un callable de signature souple (text[, kind][, force]) vers utils.telegram_client.
    Essaye différentes fonctions / une classe TelegramClient / tout callable public.
    """
    try:
        mod = importlib.import_module("utils.telegram_client")
    except Exception:
        return None

    prefer = [
        "_tg", "_t", "send_message", "send", "notify",
        "push", "post", "send_text", "send_telegram",
        "message", "publish"
    ]
    for name in prefer:
        obj = getattr(mod, name, None)
        if callable(obj):
            return obj

    cls = getattr(mod, "TelegramClient", None)
    if cls:
        try:
            inst = cls()
            for m in ("send_message", "send", "__call__"):
                meth = getattr(inst, m, None)
                if callable(meth):
                    return meth
        except Exception:
            pass

    for name, obj in vars(mod).items():
        if not name.startswith("_") and callable(obj):
            return obj
    return None

def _call_sender(fn, text: str, kind: str, force: bool) -> None:
    """Appelle fn avec les bons kwargs si possible, sinon en positionnel."""
    try:
        params = set(inspect.signature(fn).parameters)
    except Exception:
        params = set()

    # argument message
    if "text" in params:
        kwargs = {"text": text}
    elif "message" in params:
        kwargs = {"message": text}
    elif "msg" in params:
        kwargs = {"msg": text}
    elif "content" in params:
        kwargs = {"content": text}
    else:
        fn(text)
        return

    # options si supportées
    if "kind" in params:
        kwargs["kind"] = kind
    if "force" in params:
        kwargs["force"] = force
    if "cfg" in params:
        kwargs["cfg"] = None

    fn(**kwargs)

_SEND_TG_FN = _resolve_tg_sender()

def _send_tg(text: str, kind: str = "status", force: bool = False) -> bool:
    """Envoi rapide via utils.telegram_client si dispo. Retourne True si tentative effectuée."""
    if _SEND_TG_FN is None:
        return False
    try:
        _call_sender(_SEND_TG_FN, text, kind, force)
        return True
    except Exception:
        try:
            _SEND_TG_FN(text)  # dernier recours
            return True
        except Exception:
            return False

def _load_tg_token_chat() -> Tuple[Optional[str], Optional[int]]:
    """Lit token/chat_id depuis config/config.yaml pour le long-polling callback."""
    try:
        with open(os.path.join("config", "config.yaml"), encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        tg = cfg.get("telegram") or {}
        token = tg.get("token") or tg.get("bot_token")
        chat_id = tg.get("chat_id")
        return token, chat_id
    except Exception:
        return None, None

# Registry d’orchestrateurs (pour retrouver l’instance depuis le callback Telegram)
_ORCH_REGISTRY: Dict[str, "Orchestrator"] = {}

def register_orchestrator_instance(orch: "Orchestrator") -> None:
    try:
        _ORCH_REGISTRY[orch.symbol.upper()] = orch
    except Exception:
        pass

def get_orchestrator(symbol: str) -> Optional["Orchestrator"]:
    return _ORCH_REGISTRY.get((symbol or "").upper())

def _tg_callback_longpoll_loop():
    """
    Thread daemon: lit les callbacks Telegram (inline keyboard) et déclenche l’exécution.
    callback_data: 'orch|<SYMBOL>|VALIDATE|<LONG|SHORT>' ou 'orch|<SYMBOL>|REJECT|<LONG|SHORT>'
    """
    token, _ = _load_tg_token_chat()
    if not token:
        logger.warning("[TG] Token absent → pas de worker callbacks.")
        return

    API = f"https://api.telegram.org/bot{token}"

    # ⚠️ Evite le conflit webhook/getUpdates
    try:
        requests.get(f"{API}/deleteWebhook", timeout=10)
    except Exception:
        pass

    # On saute les updates anciens
    offset = None
    try:
        r0 = requests.get(f"{API}/getUpdates", params={"timeout": 1}, timeout=5)
        if r0.ok and r0.json().get("result"):
            offset = r0.json()["result"][-1]["update_id"] + 1
    except Exception:
        pass

    logger.info("[TG] Callback worker en écoute (long-poll).")

    while True:
        try:
            r = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "timeout": 25, "allowed_updates": ["callback_query"]},
                timeout=30,
            )
            if not r.ok:
                time.sleep(1.0)
                continue

            data = r.json()
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1

                cq = upd.get("callback_query")
                if not cq:
                    continue

                payload = (cq.get("data") or "").strip()
                logger.info(f"[TG] callback_query reçu: {payload}")

                # Toast visible dans Telegram
                try:
                    requests.post(
                        f"{API}/answerCallbackQuery",
                        json={"callback_query_id": cq["id"], "text": "Reçu 👍", "show_alert": False},
                        timeout=5
                    )
                except Exception:
                    pass

                parts = payload.split("|")
                if len(parts) != 4 or parts[0] != "orch":
                    continue

                symbol = parts[1].upper()
                action = parts[2].upper()
                direction = parts[3].upper()

                orch = get_orchestrator(symbol)
                if not orch:
                    _send_tg(f"⚠️ Aucun orchestrateur actif pour {symbol}.", kind="status", force=True)
                    continue

                if action == "VALIDATE":
                    try:
                        loop = asyncio.new_event_loop()
                        loop.run_until_complete(orch.execute_trade(direction))
                    except Exception as e:
                        logger.exception(f"[TG] Erreur exécution trade {symbol} {direction}: {e}")
                    finally:
                        try:
                            loop.close()
                        except Exception:
                            pass
                elif action == "REJECT":
                    orch._send_telegram(f"✋ Trade {symbol} {direction} rejeté.", kind="status", force=True)
                    try:
                        # petit cooldown de rejet si configuré
                        orch._arm_cooldown(getattr(orch, "_cooldown_after_reject_min", 0), "rejet")
                    except Exception:
                        pass

        except Exception as e:
            logger.warning(f"[TG] loop err: {e}")
            time.sleep(1.0)

def _start_tg_callback_worker_once():
    if getattr(_start_tg_callback_worker_once, "_started", False):
        return
    th = threading.Thread(target=_tg_callback_longpoll_loop, name="tg-callback-worker", daemon=True)
    th.start()
    _start_tg_callback_worker_once._started = True
    logger.info("[TG] Callback worker démarré.")

def _notify_global_start(symbols_started: List[str]) -> None:
    """Ping unique au lancement pour tous les symboles démarrés."""
    try:
        tz = pytz.timezone("Europe/Zurich")
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    msg = f"🔔 Empire lancé ({now})\nSymbols: " + ", ".join(symbols_started)
    ok = _send_tg(msg, kind="startup", force=True)
    if not ok:
        logger.warning("[TG] Message de start global non envoyé (sender indisponible).")
    logger.info(msg)



def _crypto_bucket_risk_used(get_profile) -> float:
    """
    Exposition déjà utilisée par des positions crypto:
      1) tente d'estimer le risque réel par position (distance SL × lots × valeur du point / equity)
      2) sinon fallback: somme des risk_per_trade des profils des symboles ouverts
    Retour: ratio d'equity (ex: 0.012 = 1.2%)
    """
    used = 0.0
    try:
        poss = _mt5.positions_get() or []
        # Equity du compte pour normaliser en %
        equity = None
        try:
            ai = _mt5.account_info()
            equity = float(getattr(ai, "equity", None) or 0.0)
        except Exception:
            equity = 0.0

        for p in poss:
            s_real = str(getattr(p, "symbol", "") or "").upper()
            if s_real not in CRYPTO_REAL:
                continue
            s_canon = _to_canon(s_real) or s_real
            prof = get_profile(s_canon) or {}
            inst = (prof.get("instrument") or {})
            point = float(inst.get("point") or 0.0)
            pip_value = float(inst.get("pip_value") or 0.0)
            contract_size = float(inst.get("contract_size") or 1.0)

            price_open = getattr(p, "price_open", None)
            sl         = getattr(p, "sl", None)
            vol        = getattr(p, "volume", None)

            risk_ratio = None
            try:
                if equity and equity > 0 and price_open and sl and vol and point and pip_value:
                    # approx: distance en points × valeur du point × lots / equity
                    dist_pts = abs(float(price_open) - float(sl)) / max(point, 1e-9)
                    risk_ccy = dist_pts * pip_value * float(vol)
                    risk_ratio = risk_ccy / equity
            except Exception:
                risk_ratio = None

            if risk_ratio is None:
                # fallback proxy: risk_per_trade du profil
                r = float(((prof.get("risk") or {}).get("risk_per_trade") or 0.0))
                used += r
            else:
                used += float(max(0.0, risk_ratio))
    except Exception:
        pass
    return float(used)

def _apply_crypto_bucket_guard(symbol_canon: str, planned_risk: float, *, cap: float,
                               get_profile) -> float:
    """
    Retourne un facteur [0..1] à appliquer au volume:
      - 0.0 : refuse (cap dépassé)
      - (0,1] : réduit proportionnellement l’exposition
    """
    if (symbol_canon or "").upper() not in CRYPTO_CANON:
        return 1.0

    used = _crypto_bucket_risk_used(get_profile)
    room = max(0.0, float(cap) - used)
    if room >= planned_risk:
        return 1.0
    if room <= 0.0:
        return 0.0
    return room / max(planned_risk, 1e-9)

def _count_open_crypto_positions() -> int:
    """Nombre de positions ouvertes relevant du bucket crypto (noms broker)."""
    try:
        poss = _mt5.positions_get() or []
        n = 0
        for p in poss:
            s_real = str(getattr(p, "symbol", "") or "").upper()
            if s_real in CRYPTO_REAL:
                n += 1
        return n
    except Exception:
        return 0
    
def _norm(sig: Optional[str]) -> str:
    """Normalize signal to 'LONG'/'SHORT'/'' ; treat WAIT/None as ''."""
    s = (sig or "").strip().upper()
    return s if s in ("LONG", "SHORT") else ""

def _record_guard_event(symbol: str, tag: str, message: str) -> None:
    try:
        logs_dir = pathlib.Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        entry = f"{ts}|{symbol}|{tag}|{message}\n"
        with (logs_dir / "guards.log").open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass



# =============================================================================
# Orchestrateur
# =============================================================================
class Orchestrator:
    """
    Orchestrateur multi-timeframe / multi-agents.
    - Agrège les signaux
    - Applique seuils (score / confluence / confirmations)
    - Garde-fous risque (incl. crypto bucket guard)
    - Fallback ATR pour TP/SL/Lots
    - Telegram (statuts / rapports ; validation optionnelle)
    - Auto-optimisation nocturne (overrides.yaml)
    - Gating anti-spam (min délai, une fois par bougie, plafond/jour)

    Cooldown config (orchestrator.cooldown):
      enabled: bool
      after_trade_min: int
      after_loss_min: int
      after_win_min: int
      after_reject_min: int
      after_streak_n: int
      after_streak_min: int
      min_secs_between_trades: int
      max_trades_per_day: int
    """
    import threading
    _ORCH_LOCKS = {}
    def _sym_lock(sym: str) -> threading.Lock:
        lk = _ORCH_LOCKS.get(sym) # type: ignore
        if lk is None:
            lk = threading.Lock()
            _ORCH_LOCKS[sym] = lk # type: ignore
        return lk

    def __init__(
        self,
        symbol: Optional[str] = None,
        cfg: Optional[Dict[str, Any]] = None,
        dry_run: Optional[bool] = None,
        overrides_path: Optional[str] = None,
        telegram_client=None,
    ):
        # --- Symbol d'abord ---
        enabled_symbols: List[str] = []
        try:
            enabled_symbols = get_enabled_symbols()
        except Exception:
            enabled_symbols = []
        self._enabled_symbols = enabled_symbols

        if symbol is None:
            if not enabled_symbols:
                raise SystemExit("Aucun symbole activé dans profiles.yaml")
            symbol = enabled_symbols[0]
        self.symbol = symbol  # canonique
        self.telegram_client = telegram_client

        # --- Configuration globale & overrides ---
        global OVERRIDES_PATH
        if overrides_path:
            OVERRIDES_PATH = overrides_path
        self.overrides_path = overrides_path or OVERRIDES_PATH

        if cfg is not None:
            self.cfg = cfg
        else:
            try:
                self.cfg = load_config() or {}
            except Exception:
                self.cfg = {}
        self.optimization_cfg: Dict[str, Any] = dict(self.cfg.get("optimization") or {})
        primary_symbol = self.optimization_cfg.get("symbol")
        if not primary_symbol:
            primary_symbol = enabled_symbols[0] if enabled_symbols else self.symbol
        self._primary_symbol = primary_symbol or self.symbol
        self._is_primary_optimizer = self.symbol == self._primary_symbol
        self.whale_cfg: Dict[str, Any] = dict(self.cfg.get("whale") or {})
        self.whale_allow_in_vol_spike: bool = bool(self.whale_cfg.get("allow_in_vol_spike", False))

        try:
            self.profile = get_symbol_profile(self.symbol, overrides_path=self.overrides_path) or {}
        except TypeError:
            self.profile = get_symbol_profile(self.symbol) or {}

        ori = (self.profile.get("orchestrator") or {})
        if dry_run is None:
            self.dry_run = bool(ori.get("dry_run", False))
        else:
            self.dry_run = bool(dry_run)

        # --- MT5 EN PREMIER ---
        MT5Client.initialize_if_needed()
        self.mt5 = MT5Client()
        try:
            self.broker_symbol = self.mt5.resolve_symbol_name(self.symbol)
            self.mt5.ensure_symbol(self.broker_symbol)
        except Exception as e:
            logger.warning(f"[MT5] Résolution/ensure symbole a échoué: {e}")
            self.broker_symbol = self.symbol

        # --- PHASE 4: AssetManager pour configuration par type d'actif ---
        try:
            self.asset_manager = get_asset_manager()
            logger.info(f"[PHASE4] AssetManager initialisé pour {self.symbol} (type: {self.asset_manager.get_asset_type(self.symbol)})")
        except Exception as e:
            logger.warning(f"[PHASE4] AssetManager init failed: {e}, continuing without it")
            self.asset_manager = None

        # --- Profil & overrides ---
        try:
            ov_path = os.path.join("config", "overrides.yaml")
            if os.path.exists(ov_path):
                with open(ov_path, encoding="utf-8") as f:
                    ov_all = yaml.safe_load(f) or {}
                self._apply_overrides_for_symbol(ov_all.get(self.symbol) or {})
        except Exception as e:
            logger.warning(f"[OVR] load overrides.yaml: {e}")

        # --- Orchestrator config ---
        self.ori_cfg: Dict[str, Any] = self.profile.get("orchestrator", {}) or {}
        self.auto_execute = bool(self.ori_cfg.get("auto_execute", True))
        self.use_telegram_validation = bool(self.ori_cfg.get("telegram_validation", False))
        self.status_report_hours = int(self.ori_cfg.get("status_report_hours", 2))
        self._last_report_ts: Optional[datetime] = None

        weights_cfg = self.ori_cfg.get("agent_weights", {}) or {}
        self.w_news      = float(weights_cfg.get("news",     0.6))
        self.w_swing     = float(weights_cfg.get("swing",    0.5))
        self.w_scalp     = float(weights_cfg.get("scalping", 0.3))
        self.w_structure = float(weights_cfg.get("structure", 0.6))
        self.w_smc       = float(weights_cfg.get("smc", 0.5))
        self.w_whale     = float(weights_cfg.get("whale", self.whale_cfg.get("weight", 0.4)))

        self.votes_required: int = int(self.ori_cfg.get("votes_required", 2))
        self.min_confluence: float = float(self.ori_cfg.get("min_confluence", 2))
        self.min_score_for_proposal: float = float(self.ori_cfg.get("min_score_for_proposal", 2.0))
        self.require_scalping_entry: bool = bool(self.ori_cfg.get("require_scalping_entry", False))
        self.require_swing_confirm: bool  = bool(self.ori_cfg.get("require_swing_confirm", False))
        self.confluence_weights: Dict[str, float] = {
            str(k): float(v)
            for k, v in (self.ori_cfg.get("confluence_weights") or {}).items()
        }
        self.min_confluence_dispersion: float = float(
            self.ori_cfg.get("min_confluence_dispersion", 0.25)
        )
        self.tracker_confluence_weight: float = float(
            self.ori_cfg.get("tracker_confluence_weight", 0.5)
        )
        self.tracker_vote_threshold: float = float(
            self.ori_cfg.get("tracker_vote_threshold", 0.6)
        )
        self.market_confluence_weight: float = float(
            self.ori_cfg.get("market_confluence_weight", 0.5)
        )
        self.weekend_guard_cfg: Dict[str, Any] = dict(self.ori_cfg.get("weekend_guard") or {})
        default_wg = {
            "enabled": True,
            "close_positions": True,
            "close_day": "FRI",
            "close_time": "23:00",
            "reopen_day": "MON",
            "reopen_time": "00:05",
        }
        if not self.weekend_guard_cfg:
            self.weekend_guard_cfg = dict(default_wg)
        else:
            for key, value in default_wg.items():
                self.weekend_guard_cfg.setdefault(key, value)
        self._weekend_guard_last_flatten: Optional[int] = None
        self._weekend_guard_state: Optional[str] = None

        mtf = self.ori_cfg.get("multi_timeframes", {}) or {}
        self.mtf_enabled: bool = bool(mtf.get("enabled", True))
        self.tfs: List[str] = list(mtf.get("tfs", ["H4", "H1", "M30", "M15", "M5", "M1"]))
        self.tf_weights: Dict[str, float] = dict(mtf.get("tf_weights", {}))
        self.whale_override_cfg: Dict[str, Any] = dict(self.ori_cfg.get("whale_override") or {})
        self._whale_trust_ewma: Optional[float] = None
        self._whale_market_ctx: Dict[str, Dict[str, Any]] = {}
        self._whale_stats_cache: Dict[str, Dict[str, Any]] = {}
        self.tf_dynamic_scale: float = float(self.ori_cfg.get("tf_weight_dynamic_scale", 0.2))

        self.timeframes_cfg: Dict[str, Any] = self.ori_cfg.get("timeframes", {})
        self.proposal_ttl_secs: int = int(self.ori_cfg.get("proposal_ttl_secs", 300))
        engine_cfg: Dict[str, Any] = {}
        if isinstance(self.cfg, dict):
            engine_cfg = self.cfg.get("engine", {}) or {}
        tzname = str(engine_cfg.get("timezone", "Europe/Zurich"))
        try:
            self._tz = pytz.timezone(tzname)
        except Exception:
            self._tz = pytz.timezone("Europe/Zurich")
        self._weekdays_only: bool = bool(
            self.ori_cfg.get(
                "weekdays_only",
                engine_cfg.get("weekdays_only", False),
            )
        )
        # Créer le scheduler principal pour l'orchestrateur
        from apscheduler.schedulers.background import BackgroundScheduler
        self.scheduler = BackgroundScheduler(timezone=self._tz)
        self.scheduler.start()

        # Stocker référence au event loop pour exécuter coroutines async depuis scheduler
        self._event_loop = None

        # Programmer le digest une seule fois (si multi-symboles, choisis un "primary")
        # RÉACTIVÉ : Daily digest à 10:00 et 19:00
        self._maybe_schedule_daily_digest()

        # Auto-optimization (Phase 5)
        # DÉSACTIVÉ : L'auto-optimization est maintenant gérée globalement dans main.py
        # self._init_auto_optimization()

        # Cooldown et gating
        self._init_cooldown_and_gating()

        # Health server (une seule fois)
        if not hasattr(self.__class__, "_health_started"):
            try:
                start_health_server(host="0.0.0.0", port=9108)
                self.__class__._health_started = True
                logger.info("[Health] /healthz ready on :9108")
            except Exception as e:
                logger.warning(f"[Health] failed to start: {e}")
    def _maybe_schedule_daily_digest(self):
        try:
            tg = (self.cfg or {}).get("telegram", {}) or {}
            if not bool(tg.get("send_daily_digest", False)):
                return

            raw_times = tg.get("daily_digest_times")
            if isinstance(raw_times, (list, tuple, set)):
                times = [str(t).strip() for t in raw_times if str(t).strip()]
            elif raw_times:
                times = [str(raw_times)]
            else:
                times = [str(tg.get("daily_digest_time", "19:00"))]

            from apscheduler.schedulers.background import BackgroundScheduler
            if not hasattr(self.__class__, "_digest_scheduler"):
                sched = BackgroundScheduler(timezone=self._tz)
                sched.start(paused=False)
                self.__class__._digest_scheduler = sched
            sched = self.__class__._digest_scheduler

            def _digest_job(hour: int, minute: int) -> None:
                # Utilise tous les symboles activés, pas seulement celui de cet orchestrateur
                try:
                    syms = get_enabled_symbols()
                except Exception:
                    syms = [getattr(self, "symbol", "BTCUSD")]
                logger.info(f"[Digest] summary triggered ({hour:02d}:{minute:02d}) for {len(syms)} symbols.")
                send_daily_digest(self._send_telegram, syms, tz_name="Europe/Zurich")  # type: ignore

            for hhmm in times:
                try:
                    hh, mm = [int(x) for x in hhmm.split(":")]
                except Exception:
                    logger.warning(f"[Digest] invalid schedule '{hhmm}' skipped.")
                    continue

                job_id = f"daily_digest_job_{hh:02d}{mm:02d}"
                if sched.get_job(job_id):
                    continue

                sched.add_job(
                    _digest_job,
                    "cron",
                    id=job_id,
                    hour=hh,
                    minute=mm,
                    replace_existing=True,
                    args=(hh, mm),
                )
                logger.info(f"[Digest] ✅ Job planifié: {job_id} à {hh:02d}:{mm:02d} Europe/Zurich")
        except Exception as e:
            logger.error(f"[Digest] schedule failed: {e}", exc_info=True)

    # --- Fin de _maybe_schedule_daily_digest ---

    def _init_auto_optimization(self):
        """Initialise l'optimisation automatique (Phase 5)"""
        try:
            from optimization.auto_optimizer import start_auto_optimization
            logger.info("[ORCH] Démarrage auto-optimization...")
            self._auto_optimizer = start_auto_optimization()
            logger.info("[ORCH] ✅ Auto-optimization activée")
        except Exception as e:
            logger.warning(f"[ORCH] Auto-optimization non disponible : {e}")
            self._auto_optimizer = None

    def _init_cooldown_and_gating(self):
        """Initialise le cooldown et gating (anti-overtrading)"""
        # ══════════════════════════════════════════════════════════════════
        # OPTIMISATION 2025-12-13: Cooldown renforcé (Solution 5)
        # ══════════════════════════════════════════════════════════════════
        cd = (self.ori_cfg.get("cooldown") or {})
        self._cooldown_enabled          = bool(cd.get("enabled", True))
        self._cooldown_after_trade_min  = int(cd.get("after_trade_min", 5))   # AUGMENTÉ 2→5
        self._cooldown_after_loss_min   = int(self.ori_cfg.get("cooldown_after_loss_minutes") or cd.get("after_loss_min", 30))  # AUGMENTÉ 5→30
        self._cooldown_after_win_min    = int(cd.get("after_win_min", 2))     # AUGMENTÉ 1→2
        self._cooldown_after_reject_min = int(cd.get("after_reject_min", 3))  # AUGMENTÉ 2→3
        self._cooldown_streak_n         = int(self.ori_cfg.get("max_consecutive_losses_pause") or cd.get("after_streak_n", 3))
        self._cooldown_streak_min       = int(cd.get("after_streak_min", 60)) # AUGMENTÉ 10→60 min après 3 pertes consec
        self._cooldown_until: Optional[datetime] = None

        # --- Gating trades (anti-spam) ---
        self.once_per_candle_tf: Optional[str] = (self.ori_cfg.get("once_per_candle_tf") or None)
        # OPTIMISATION 2025-12-13: Limites de trading journalières (Solution 5)
        self._min_secs_between_trades: int = int(cd.get("min_secs_between_trades", 300))  # AUGMENTÉ 120→300 sec (5 min)
        self._max_trades_per_day: int      = int(self.ori_cfg.get("max_trades_per_day") or cd.get("max_trades_per_day", 15))  # 15 trades max/jour
        # FIX 2025-12-17: Budget horaire pour éviter concentration des trades
        self._max_trades_per_hour: int     = int(self.ori_cfg.get("max_trades_per_hour", 5))  # Max 5 trades/heure

        # Runtime gating state
        self._last_bar_traded_by_tf: Dict[str, int] = {}   # tf -> bar_id
        self._last_exec_ts: Optional[datetime] = None
        # FIX 2025-12-17: Tracking des trades par heure
        self._trades_this_hour: int = 0
        self._current_hour: int = datetime.now(timezone.utc).hour

        # Pacing & qualité d'entrée
        self.min_rr = float(self.ori_cfg.get("min_rr", 1.5))

        # --- Scheduler (AsyncIO) ---
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self._sched = AsyncIOScheduler(event_loop=loop)

        # --- Risk manager APRES MT5 ---
        self.risk = RiskManager(self.symbol)

        self._whale_connectors: Dict[str, Any] = {}
        self._social_verifier = None
        if bool(self.whale_cfg.get("enabled", False)):
            self.whale_agent = WhaleAgent(
                cfg=self.whale_cfg,
                market_ctx_provider=lambda sym: self._whale_market_ctx.get(str(sym).upper(), {}),
                stats_provider=lambda wallet: self._whale_stats_cache.get(wallet, {}),
                risk_manager=self.risk,
            )
            self._setup_whale_connectors()
        else:
            self.whale_agent = None

        # --- Cache d'agents & proposition / contexte ---
        self._agents: Dict[str, Any] = {}
        self.tracker = default_tracker()
        self._last_proposal: Optional[Dict[str, Any]] = None
        self._last_ctx: Optional[Dict[str, Any]] = None  # per_tf_signals / global_signals / indicators / market

        # --- Position Manager ---
        try:
            self.pm = PositionManager(self.mt5, self.symbol, self.profile, notifier=self._notify_trade_event)
            # assure qu'on passe dans manage_open_positions() si le flag est supporté
            if hasattr(self.pm, "enabled"):
                self.pm.enabled = True  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"[PM] init failed: {e}")
            self.pm = None

        logger.info(
            f"[ORCH] {self.symbol} (broker={self.broker_symbol}) "
            f"votes_required={self.votes_required} tfs={self.tfs} weights={self.tf_weights}"
        )
        register_orchestrator_instance(self)

    # --- Fin de __init__ ---
    # --- Anti-spam local (cooldown + déduplication) ---
    def _tg_antispam_ok(self, kind: str, text: str) -> bool:
        """
        Retourne False si on a déjà envoyé un message identique pour ce 'kind'
        dans la fenêtre de cooldown (min) définie dans config: orchestrator.anti_spam.cooldown_minutes.
        """
        try:
            cfg = (self.profile.get("orchestrator") or {}).get("anti_spam") or {}
            cd_min = int(cfg.get("cooldown_minutes", 5))
        except Exception:
            cd_min = 5
        if not hasattr(self, "_tg_cache"):
            self._tg_cache = {"last_sent_at": {}, "last_hash": {}}
        cache = self._tg_cache
        now = datetime.now(timezone.utc).timestamp()
        last = cache["last_sent_at"].get(kind)
        if last and now - last < cd_min * 60:
            h = hash(text)
            if cache["last_hash"].get(kind) == h:
                return False
        cache["last_sent_at"][kind] = now
        cache["last_hash"][kind] = hash(text)
        return True

    def _notify_trade_event(self, tag: str, payload: dict) -> None:
        """
        Envoie des messages structurés: NEW_TRADE, CLOSE_TRADE,
        MOVE_BE, TP1_HIT, TRAILING_SL_UPDATE (kind='trade_event').
        """
        try:
            tz = self._tz
        except Exception:
            tz = pytz.timezone("Europe/Zurich")
        ts = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
        sym = payload.get("symbol") or getattr(self, "symbol", "UNKNOWN")

        if tag == "NEW_TRADE":
            side  = payload.get("side")
            entry = float(payload.get("entry", 0.0))
            sl    = float(payload.get("sl", 0.0))
            tp    = payload.get("tp")
            lots  = float(payload.get("lots", 0.0))
            score = payload.get("score")
            conf  = payload.get("confluence")
            # Déduire TP1/TP2 via RR si dispo dans profile
            rr_partials = []
            try:
                pm_cfg = ((self.profile.get("orchestrator") or {}).get("position_manager") or {})
                pm_partials = pm_cfg.get("partials") or []
                rr_partials = [float(x.get("rr")) for x in pm_partials if x.get("rr") is not None][:2]
            except Exception:
                rr_partials = []

            def rr_to_tp(rr):
                if rr is None:
                    return None
                risk_px = abs(entry - sl)
                if risk_px <= 0:
                    return None
                return entry + rr * risk_px if (side == "LONG") else entry - rr * risk_px
            tp1 = rr_to_tp(rr_partials[0]) if len(rr_partials) >= 1 else None
            tp2 = rr_to_tp(rr_partials[1]) if len(rr_partials) >= 2 else None
            tp1_str = f"{tp1:.2f}" if tp1 is not None else "N/A"
            tp2_str = f"{tp2:.2f}" if tp2 is not None else "N/A"
            # RR breakeven (optionnel)
            try:
                pm_cfg = ((self.profile.get("orchestrator") or {}).get("position_manager") or {})
                be_rr = float((pm_cfg.get("break_even") or {}).get("rr", 1.0))
            except Exception:
                be_rr = 1.0
            msg = (
                f"#NEW_TRADE | {sym} | {side} | entry {entry:.2f} | {lots:.3f} lots | "
                f"SL {sl:.2f} | TP1 {tp1_str} | TP2 {tp2_str} | BE RR≥{be_rr:.1f} | {ts}"
            )
            if score is not None or conf is not None:
                msg += f" | score {score if score is not None else 'N/A'} / conf {conf if conf is not None else 'N/A'}"

            if self._tg_antispam_ok("trade_event", msg):
                self._send_telegram(msg, kind="trade_event", force=True)

        elif tag == "CLOSE_TRADE":
            msg = (f"#CLOSE_TRADE | {sym} | {payload.get('result','N/A')} | "
                   f"P&L {payload.get('pnl_ccy','0.00')} ({payload.get('pnl_pips','0')} pips) | "
                   f"durée {payload.get('duration','N/A')} | R:R {payload.get('rr','N/A')} | "
                   f"MFE {payload.get('mfe','N/A')} | MAE {payload.get('mae','N/A')} | "
                   f"ticket {payload.get('ticket','?')} | {ts}")
            if self._tg_antispam_ok("trade_event", msg):
                self._send_telegram(msg, kind="trade_event", force=True)

        else:
            # MOVE_BE / TP1_HIT / TRAILING_SL_UPDATE / ERROR etc.
            detail = payload.get("detail", "")
            msg = f"#{tag} | {sym} | {detail} | {ts}"
            if self._tg_antispam_ok("trade_event", msg):
                self._send_telegram(msg, kind="trade_event", force=True)

    # ---------------- Fenêtre de trading configurable ----------------
    def _parse_days(self, days_val) -> set:
        """Accepte ['mon',...], ['lundi',...], [1..7] ou 'weekdays'."""
        if not days_val:
            return set()
        if isinstance(days_val, str):
            s = days_val.strip().lower()
            if s in ("weekdays", "ouvrables"):
                return {1, 2, 3, 4, 5}
            days_val = [s]
        out = set()
        map_en = {"mon":1,"tue":2,"wed":3,"thu":4,"fri":5,"sat":6,"sun":7}
        map_fr = {"lundi":1,"mardi":2,"mercredi":3,"jeudi":4,"vendredi":5,"samedi":6,"dimanche":7}
        for d in days_val:
            if isinstance(d, int):
                if 1 <= d <= 7:
                    out.add(d)
                continue
            s = str(d).strip().lower()
            out.add(map_en.get(s[:3], map_fr.get(s, None)))
        return {x for x in out if x}

    def _is_in_trading_window(self, when: Optional[datetime] = None) -> bool:
        """Vrai si 'when' est dans la fenêtre de trading définie dans le profil."""
        tw = (self.ori_cfg.get("trading_window") or {})
        tzname = tw.get("timezone") or "Europe/Zurich"
        try:
            tz = pytz.timezone(tzname)
        except Exception:
            tz = self._tz

        if when is None:
            when = datetime.now(timezone.utc)
        local_dt = when.astimezone(tz)

        # Vérifier si c'est le week-end
        is_weekend = local_dt.isoweekday() in {6, 7}  # Samedi=6, Dimanche=7

        # Option weekend_crypto_only : autoriser uniquement les cryptos le week-end
        engine_cfg = (self.cfg or {}).get("engine", {}) or {}
        weekend_crypto_only = bool(engine_cfg.get("weekend_crypto_only", False))

        if is_weekend and weekend_crypto_only:
            # Liste des cryptos autorisées le week-end
            crypto_symbols = {"BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"}
            if self.symbol.upper() not in crypto_symbols:
                return False  # Bloquer les non-cryptos le week-end
            # Les cryptos peuvent trader le week-end - continuer les vérifications

        enforce_weekdays = bool(getattr(self, "_weekdays_only", False))
        if not bool(tw.get("enabled", False)):
            if enforce_weekdays and is_weekend:
                # Si weekend_crypto_only est actif et c'est une crypto, on autorise
                if weekend_crypto_only and self.symbol.upper() in {"BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"}:
                    return True
                return False
            return True  # pas de contrainte horaire supplémentaire

        # Jours
        allowed = self._parse_days(tw.get("days") or tw.get("weekdays"))
        if not allowed and enforce_weekdays:
            allowed = {1, 2, 3, 4, 5}
        if allowed and local_dt.isoweekday() not in allowed:
            return False

        # Heures
        start_s = str(tw.get("start", "00:00")).strip()
        end_s   = str(tw.get("end",   "23:59")).strip()

        def _to_sec(hhmm: str) -> int:
            hh, mm = hhmm.split(":")
            return int(hh)*3600 + int(mm)*60
        try:
            start_sec = _to_sec(start_s)
            end_sec   = _to_sec(end_s)
        except Exception:
            return True  # si parsing foire, on laisse passer

        t = local_dt.hour*3600 + local_dt.minute*60 + local_dt.second
        if end_sec > start_sec:
            return start_sec <= t < end_sec
        else:
            # fenêtre qui traverse minuit (ex: 22:00-06:00)
            return t >= start_sec or t < end_sec

    def _weekend_guard_blocked(self, now: Optional[datetime] = None) -> bool:
        """Retourne True si la garde week-end doit bloquer le trading."""
        # Les cryptos ne sont jamais bloquées par le weekend guard
        crypto_symbols = {"BTCUSD", "ETHUSD", "BNBUSD", "LTCUSD", "ADAUSD", "SOLUSD"}
        if self.symbol.upper() in crypto_symbols:
            return False  # Cryptos tradent 24/7

        cfg = getattr(self, "weekend_guard_cfg", {}) or {}
        if not bool(cfg.get("enabled", False)):
            return False

        day_map = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

        def _day_to_idx(val: str, default: int) -> int:
            try:
                return day_map[str(val).upper()]
            except Exception:
                return default

        def _time_to_minutes(val: str, default: str) -> int:
            try:
                hh, mm = str(val).split(":")
                return int(hh) * 60 + int(mm)
            except Exception:
                hh, mm = default.split(":")
                return int(hh) * 60 + int(mm)

        tz_obj = getattr(self, "_tz", None)
        current = now or datetime.utcnow().replace(tzinfo=timezone.utc)
        try:
            if tz_obj is not None:
                current_local = current.astimezone(tz_obj)  # type: ignore
            else:
                current_local = current
        except Exception:
            current_local = current

        close_positions = bool(cfg.get("close_positions", True))
        close_day_idx = _day_to_idx(cfg.get("close_day", "FRI"), 4)
        reopen_day_idx = _day_to_idx(cfg.get("reopen_day", "SUN"), 6)
        close_minutes = _time_to_minutes(cfg.get("close_time", "21:40"), "21:40")
        reopen_minutes = _time_to_minutes(cfg.get("reopen_time", "22:05"), "22:05")

        minute_of_week = current_local.weekday() * 1440 + current_local.hour * 60 + current_local.minute
        close_mow = close_day_idx * 1440 + close_minutes
        reopen_mow = reopen_day_idx * 1440 + reopen_minutes

        if close_mow <= reopen_mow:
            blocked = close_mow <= minute_of_week < reopen_mow
        else:
            blocked = minute_of_week >= close_mow or minute_of_week < reopen_mow

        if blocked and close_positions:
            self._flatten_positions_for_weekend(minute_of_week)
            if getattr(self, "_weekend_guard_state", None) != "closed":
                week_note = ""
                try:
                    stats = rolling_metrics(self.symbol, days=7)
                    week_note = (
                        f" | Semaine: net={stats.get('pnl', 0.0):.2f} USD "
                        f"(trades={stats.get('trades', 0)}, PF={stats.get('pf', 0.0):.2f})"
                    )
                except Exception:
                    week_note = ""
                try:
                    self._send_telegram(
                        f"[WeekendGuard] {self.symbol}: clôture hebdo à {current_local:%Y-%m-%d %H:%M} "
                        f"(positions fermées){week_note}.",
                        kind="status",
                        force=True,
                    )
                except Exception:
                    pass
                self._weekend_guard_state = "closed"
        elif not blocked:
            self._weekend_guard_last_flatten = None
            if getattr(self, "_weekend_guard_state", None) == "closed":
                try:
                    self._send_telegram(
                        f"[WeekendGuard] {self.symbol}: réouverture {current_local:%Y-%m-%d %H:%M}. Trading autorisé.",
                        kind="status",
                        force=True,
                    )
                except Exception:
                    pass
                self._weekend_guard_state = "open"

        return blocked

    def _flatten_positions_for_weekend(self, guard_key: int) -> None:
        """Ferme toutes les positions ouvertes pour respecter la garde week-end."""
        if getattr(self, "_weekend_guard_last_flatten", None) == guard_key:
            return
        try:
            results: List[Dict[str, Any]] = []
            if hasattr(self, "mt5") and hasattr(self.mt5, "close_positions"):
                results = self.mt5.close_positions(self.symbol, comment="weekend_guard")
            if results:
                for res in results:
                    if res.get("ok", False):
                        logger.info(
                            "[WeekendGuard] %s position %s close ok (retcode=%s)",
                            self.symbol,
                            res.get("position"),
                            res.get("retcode"),
                        )
                    else:
                        logger.warning("[WeekendGuard] %s close failed: %s", self.symbol, res)
        except Exception as e:
            logger.warning(f"[WeekendGuard] close positions error: {e}")
        finally:
            self._weekend_guard_last_flatten = guard_key

    def _is_symbol_profile_active_now(self) -> bool:
        """
        Vérifie le planning global du symbole défini dans profiles.yaml:
        profiles.<SYM>.schedule.active_days / active_hours
        """
        try:
            return bool(is_symbol_active_now(self.symbol))
        except Exception:
            return True

    # ---------------------------- Dashboard live ----------------------------
    def save_signals_to_json(self, symbol: str, global_signals: Dict[str, str]) -> None:
        """Enregistre les signaux globaux (par agent) pour le dashboard live → data/latest_signals.json."""
        try:
            data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "signals": {
                    agent: {
                        "signal": s,
                        "intensity": None,
                        "reason": "" if s else "no_signal",
                    }
                    for agent, s in (global_signals or {}).items()
                    if s is not None
                },

            }
            os.makedirs("data", exist_ok=True)
            with open("data/latest_signals.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[ORCH] Ecriture latest_signals.json échouée: {e}")

    # ---------------------------- RAPPORT PERIODIQUE ----------------------------
    async def _send_status_report(self):
        """Rapport court: heure locale, equity/balance, positions ouvertes du symbole, derniers trades."""
        try:
            tz = self._tz
            now_loc = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")

            # Compte
            ai = getattr(self.mt5, "get_account_info", lambda: None)()
            eq = float(getattr(ai, "equity", 0.0) or 0.0) if ai else 0.0
            bal = float(getattr(ai, "balance", 0.0) or 0.0) if ai else 0.0

            # Positions ouvertes pour ce symbole
            poss = []
            try:
                poss_raw = _mt5.positions_get(symbol=self.broker_symbol) or []
                for p in poss_raw:
                    typ = int(getattr(p, "type", 0))  # 0=BUY, 1=SELL
                    side = "BUY" if typ == 0 else "SELL"
                    vol  = float(getattr(p, "volume", 0.0) or 0.0)
                    po   = float(getattr(p, "price_open", 0.0) or 0.0)
                    sl   = getattr(p, "sl", None)
                    tp   = getattr(p, "tp", None)
                    prf  = float(getattr(p, "profit", 0.0) or 0.0)
                    poss.append(f"{side} {vol:.2f} @ {po:.5f} | SL={sl} TP={tp} | P/L={prf:.2f}")
            except Exception:
                pass

            # Trades récents (depuis dernier rapport) dans data/trades_log.csv
            recent = []
            try:
                path = os.path.join("data","trades_log.csv")
                if os.path.exists(path):
                    since = self._last_report_ts  # datetime ou None
                    with open(path, encoding="utf-8") as f:
                        r = csv.DictReader(f)
                        rows = [row for row in r if (row.get("symbol","") == self.symbol)]
                    if since:
                        def _ok(row):
                            try:
                                ts = datetime.fromisoformat(row.get("ts_utc",""))
                                return ts > since
                            except Exception:
                                return False
                        rows = [row for row in rows if _ok(row)]
                    for row in rows[-5:]:
                        recent.append(
                            f"{row.get('side')} lots={row.get('lots')} ret={row.get('retcode')} ticket={row.get('ticket')}"
                        )
            except Exception:
                pass

            lines = [
                f"🧭 Rapport {self.symbol} — {now_loc}",
                f"Equity={eq:.2f} | Balance={bal:.2f}",
                f"Positions ouvertes ({len(poss)}):" if poss else "Positions ouvertes: 0",
            ]
            lines += (poss[:5] if poss else [])
            if recent:
                lines.append("Derniers trades:")
                lines += recent
            msg = "\n".join(lines)

            if not self._tg_quiet():
                self._send_telegram(msg, kind="status", force=False)

        except Exception as e:
            logger.warning(f"[REPORT] {self.symbol} erreur: {e}")
        finally:
            try:
                self._last_report_ts = datetime.now(timezone.utc)
            except Exception:
                pass
                # ---------------------------- DIGEST QUOTIDIEN ----------------------------
    def _send_daily_digest(self):
        """Résumé quotidien Europe/Zurich basé sur reports/audit_trades.jsonl."""
        try:
            tz = ZoneInfo("Europe/Zurich")
            ymd = datetime.now(tz).strftime("%Y-%m-%d")
            d = daily_digest_for(ymd)
            msg = format_digest_message(d, ymd)
            self._send_telegram(msg, kind="status", force=True)
        except Exception as e:
            self._send_telegram(f"[DIGEST] erreur: {e}", kind="status", force=False)


    # ---------------------------- Cooldown ----------------------------
    def _cooldown_active(self) -> bool:
        """Retourne True si on est en période de cooldown ; purge l’état si expiré."""
        if not self._cooldown_enabled or not self._cooldown_until:
            return False
        now = datetime.now(timezone.utc)
        if now < self._cooldown_until:
            return True
        # expiré -> on nettoie
        self._cooldown_until = None
        return False

    def _arm_cooldown(self, minutes: int, reason: str = "") -> None:
        """Démarre un cooldown de N minutes (safe si désactivé ou N<=0)."""
        try:
            if not self._cooldown_enabled or int(minutes) <= 0:
                return
            self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
            left = int(minutes)
            if reason:
                self._send_telegram(f"⏸️ Cooldown {self.symbol}: {left} min ({reason}).", kind="status")
            else:
                self._send_telegram(f"⏸️ Cooldown {self.symbol}: {left} min.", kind="status")
        except Exception:
            pass

    # ---------------------------- Timeframe & gating helpers ----------------------------
    def _tf_to_minutes(self, tf: str) -> Optional[int]:
        m = {"M1":1,"M5":5,"M15":15,"M30":30,"H1":60,"H4":240,"D1":1440}
        return m.get(str(tf).upper())

    def _current_bar_id(self, timeframe: str) -> Optional[int]:
        """Identifiant stable de la bougie courante pour `timeframe`."""
        try:
            tfm = self._tf_to_minutes(timeframe)
            if not tfm:
                return None

            # 1) via MT5 (précis)
            try:
                if hasattr(self.mt5, "get_rates"):
                    rates = self.mt5.get_rates(self.broker_symbol, timeframe, count=1)
                    if rates:
                        last = rates[-1]
                        t = last.get("time") if isinstance(last, dict) else getattr(last, "time", None)
                        if t:
                            return int(t)  # epoch seconds
            except Exception:
                pass

            # 2) fallback: bucketiser maintenant
            now_utc = datetime.now(timezone.utc)
            minutes = (now_utc.minute // tfm) * tfm
            anchor = now_utc.replace(minute=minutes, second=0, microsecond=0)
            return int(anchor.timestamp())
        except Exception:
            return None

    def _trades_today_count(self) -> int:
        """
        Nombre de trades LOGGÉS aujourd'hui pour CE symbole (via data/trades_log.csv, colonne ok=True).
        """
        try:
            path = os.path.join("data", "trades_log.csv")
            if not os.path.exists(path):
                return 0

            tz = self._tz
            today_local = datetime.now(tz).date()
            n = 0
            with open(path, encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    if (row.get("symbol") or "") != self.symbol:
                        continue
                    if str(row.get("ok","")).lower() not in ("true","1","yes"):
                        continue
                    ts = row.get("ts_utc")
                    if not ts:
                        continue
                    try:
                        dt_utc = datetime.fromisoformat(ts).astimezone(timezone.utc)
                        dt_loc = dt_utc.astimezone(tz)
                        if dt_loc.date() == today_local:
                            n += 1
                    except Exception:
                        continue
            return n
        except Exception:
            return 0

    def _trades_today_all_symbols_count(self) -> int:
        """
        Nombre total de trades LOGGÉS aujourd'hui pour TOUS les symboles.
        (2026-01-06) Utilisé pour le cap global journalier.
        """
        try:
            path = os.path.join("data", "trades_log.csv")
            if not os.path.exists(path):
                return 0

            tz = self._tz
            today_local = datetime.now(tz).date()
            n = 0
            with open(path, encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    if str(row.get("ok","")).lower() not in ("true","1","yes"):
                        continue
                    ts = row.get("ts_utc")
                    if not ts:
                        continue
                    try:
                        dt_utc = datetime.fromisoformat(ts).astimezone(timezone.utc)
                        dt_loc = dt_utc.astimezone(tz)
                        if dt_loc.date() == today_local:
                            n += 1
                    except Exception:
                        continue
            return n
        except Exception:
            return 0

    def _get_symbol_daily_limit(self) -> int:
        """
        (2026-01-06) Retourne la limite de trades/jour pour CE symbole.
        Lit depuis config.yaml orchestrator.symbol_daily_limits
        """
        try:
            orch_cfg = self.cfg.get("orchestrator", {})
            limits_cfg = orch_cfg.get("symbol_daily_limits", {})
            if not limits_cfg.get("enabled", False):
                return 999  # Pas de limite si désactivé

            # Limite spécifique au symbole
            limits = limits_cfg.get("limits", {})
            if self.symbol in limits:
                return int(limits[self.symbol])

            # Limite par défaut
            return int(limits_cfg.get("default_max_per_symbol", 2))
        except Exception:
            return 2  # Par défaut: 2 trades/jour/symbole

    def _trade_gate_ok(self) -> Tuple[bool, str]:
        """
        Garde-fous anti-spam :
          - cooldown actif
          - min_secs_between_trades
          - once_per_candle_tf
          - max_trades_per_day
          - max_trades_per_hour (FIX 2025-12-17)
        Retourne (ok, pourquoi_si_refus).
        """
        if self._cooldown_active():
            return False, "cooldown actif"

        now = datetime.now(timezone.utc)

        # délai min entre deux exécutions
        if self._last_exec_ts:
            dt = (now - self._last_exec_ts).total_seconds()
            if dt < max(0, self._min_secs_between_trades):
                return False, f"délai min {self._min_secs_between_trades}s non écoulé ({int(dt)}s)"

        # une seule exécution par bougie (si activé)
        if self.once_per_candle_tf:
            cur_bar = self._current_bar_id(self.once_per_candle_tf)
            if cur_bar is not None:
                last_bar = self._last_bar_traded_by_tf.get(self.once_per_candle_tf)
                if last_bar == cur_bar:
                    return False, f"une exécution déjà faite sur la bougie {self.once_per_candle_tf}"

        # FIX 2025-12-17: Budget horaire - reset si nouvelle heure
        current_hour = now.hour
        if current_hour != self._current_hour:
            self._current_hour = current_hour
            self._trades_this_hour = 0
            logger.debug(f"[GATE] Reset compteur horaire → heure {current_hour}")

        # FIX 2025-12-17: max trades par heure
        if self._trades_this_hour >= max(1, self._max_trades_per_hour):
            return False, f"max trades/heure atteint ({self._max_trades_per_hour})"

        # max trades par jour pour CE symbole (basé sur le journal CSV)
        trades_today = self._trades_today_count()
        if trades_today >= max(1, self._max_trades_per_day):
            return False, f"max trades/jour atteint ({self._max_trades_per_day})"

        # (2026-01-06) Limite par symbole - allocation journalière
        symbol_limit = self._get_symbol_daily_limit()
        if trades_today >= symbol_limit:
            return False, f"limite symbole {self.symbol}: {trades_today}/{symbol_limit} trades/jour"

        # (2026-01-06) Cap global tous symboles confondus
        total_trades = self._trades_today_all_symbols_count()
        global_max = self.cfg.get("orchestrator", {}).get("max_trades_per_day", 10)
        if total_trades >= global_max:
            return False, f"cap global atteint: {total_trades}/{global_max} trades/jour"

        return True, ""

    # ---------------------------- Propositions & snapshots (analytics) ----------------------------
    def _log_proposal_csv(self, side, price, sl, tp, lots, score, confluence, ttl_sec, expired=False, executed=False):
        try:
            path = os.path.join("data", "proposals_log.csv")
            fields = ["ts_utc","symbol","side","price","sl","tp","lots","score","confluence","ttl_sec","expired","executed"]
            os.makedirs("data", exist_ok=True)
            file_exists = os.path.exists(path)
            row = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": self.symbol, "side": side,
                "price": float(price) if price is not None else None,
                "sl": float(sl) if sl is not None else None,
                "tp": float(tp) if tp is not None else None,
                "lots": float(lots) if lots is not None else None,
                "score": float(score) if score is not None else None,
                "confluence": int(confluence) if confluence is not None else None,
                "ttl_sec": int(ttl_sec) if ttl_sec is not None else None,
                "expired": bool(expired), "executed": bool(executed),
            }
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                if not file_exists: w.writeheader()
                w.writerow(row)
        except Exception as e:
            logger.warning(f"[LOG] proposals_log.csv erreur: {e}")

    def _log_agents_snapshot_jsonl(self, per_tf_signals, global_signals, indicators, market, context="executed"):
        """Écrit un snapshot JSONL (une ligne JSON) pour analyse post-trade."""
        def _serialize_value(v):
            """Sérialise une valeur pour JSON, gérant les types spéciaux."""
            if hasattr(v, 'to_dict'):
                return v.to_dict()
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, list):
                return [_serialize_value(item) for item in v]
            if isinstance(v, dict):
                return {k: _serialize_value(val) for k, val in v.items()}
            return v

        try:
            os.makedirs("data", exist_ok=True)
            rec = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": self.symbol,
                "context": context,
                "per_tf_signals": _serialize_value(per_tf_signals or {}),
                "global_signals": _serialize_value(global_signals or {}),
                "indicators": {k: _serialize_value(v) for k, v in (indicators or {}).items()},
                "market": _serialize_value(market or {}),
            }
            with open(os.path.join("data", "agents_snap.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"[LOG] agents_snap.jsonl erreur: {e}")

    def _record_performance_stats(
        self,
        proposal: Optional[Dict[str, Any]],
        *,
        executed: bool,
        outcome: Optional[float] = None,
        retcode: Optional[int] = None,
    ) -> None:
        if not proposal:
            return
        signals = proposal.get("signals") or []
        if not signals:
            return
        if outcome is None:
            outcome = self._estimate_rr(proposal)
        regime = proposal.get("regime") or "default"
        metadata = {
            "weighted_vote": proposal.get("weighted_vote"),
            "tracker_vote": proposal.get("tracker_vote"),
            "retcode": retcode,
            "executed": executed,
        }
        if executed:
            self._append_trade_journal(proposal, metadata)


        for sig in signals:
            agent = str(sig.get("agent") or sig.get("source") or "unknown")
            timeframe = str(sig.get("timeframe") or proposal.get("timeframe") or "NA").upper()
            score = float(sig.get("score") or proposal.get("weighted_vote") or 0.0)
            try:
                point = PerformancePoint(
                    symbol=self.symbol,
                    agent=agent,
                    timeframe=timeframe,
                    regime=str(regime),
                    score=score,
                    outcome=outcome if executed else None,
                    executed=executed,
                    reward_risk=outcome,
                    metadata=metadata,
                )
                self.tracker.record(point)
            except Exception:
                logger.debug("[TRACKER] impossible d'enregistrer %s/%s", self.symbol, agent)
        try:
            snapshot = self.tracker.snapshot(top_n=1)
            if snapshot:
                top = snapshot[0]
                logger.info("[TRACKER] top %s/%s bucket=%s weight=%s count=%s",
                            top.get("symbol"),
                            top.get("agent"),
                            top.get("bucket"),
                            f"{float(top.get('weight', 0.0)):.2f}",
                            str(int(top.get("count", 0))),)
        except Exception:
            logger.debug("[TRACKER] snapshot indisponible")
    # ---------------------------- ENVOI PROPOSITION / AUTO ----------------------------
    async def _send_validation_proposal(
        self,
        msg: str,
        direction: str,
        price: float,
        sl: float,
        tp: float,
        lots: float,
        score_agr: float,
        confluence: int,
        *,
        weighted_vote: Optional[float] = None,
        tracker_vote: Optional[float] = None,
        signals: Optional[List[Dict[str, Any]]] = None,
        regime: Optional[str] = None,
        rr: Optional[float] = None,
    ):
        """Stocke la proposition; si auto_execute, on lance; sinon on envoie les boutons Telegram."""
        now_utc = datetime.now(timezone.utc)
        expires_at = now_utc + timedelta(seconds=self.proposal_ttl_secs)

        # fenêtre de trading (planning global + fenêtre orchestrator)
        if not self._is_symbol_profile_active_now():
            logger.info(f"[SCHEDULE] {self.symbol} désactivé → pas d’envoi.")
            return
        if not self._is_in_trading_window():
            logger.info(f"[WINDOW] {self.symbol} hors fenêtre → pas d’envoi.")
            return


        eff_vote = float(weighted_vote if weighted_vote is not None else score_agr)
        raw_tracker = float(tracker_vote) if tracker_vote is not None else eff_vote
        eff_rr = float(rr if rr is not None else score_agr)
        eff_regime = regime or str(self.ori_cfg.get("regime", "default"))
        self._last_proposal = {
            "symbol": self.symbol,
            "side": direction,
            "entry": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "lots": float(lots),
            "score": float(score_agr),
            "confluence": int(confluence),
            "weighted_vote": eff_vote,
            "tracker_vote": raw_tracker,
            "signals": signals or [],
            "rr": eff_rr,
            "regime": eff_regime,
            "timestamp": now_utc.isoformat(),
            "expires_at": expires_at.isoformat(),
        }

        # On log la proposition (non exécutée pour l’instant)
        self._log_proposal_csv(direction, price, sl, tp, lots, score_agr, confluence, self.proposal_ttl_secs, expired=False, executed=False)

        # Snapshot "proposed"
        try:
            self._log_agents_snapshot_jsonl(
                (self._last_ctx or {}).get("per_tf_signals"),
                (self._last_ctx or {}).get("global_signals"),
                (self._last_ctx or {}).get("indicators"),
                (self._last_ctx or {}).get("market"),
                context="proposed"
            )
        except Exception:
            pass

        # Auto-exécution demandée ?
        if getattr(self, "auto_execute", True) and not getattr(self, "use_telegram_validation", False):
            self.execute_trade(direction)
            return

        # Sinon: envoi avec boutons
        ttl_min = max(1, self.proposal_ttl_secs // 60)
        msg = f"{msg}\n⏳ Expire dans ~{ttl_min} min"
        buttons = [
            {"text": "✅ Valider", "callback_data": f"orch|{self.symbol}|VALIDATE|{direction}"},
            {"text": "❌ Rejeter", "callback_data": f"orch|{self.symbol}|REJECT|{direction}"},
        ]
        try:
            if self.telegram_client and hasattr(self.telegram_client, "send_message"):
                send_fn = self.telegram_client.send_message
                if asyncio.iscoroutinefunction(send_fn):
                    await send_fn(msg, buttons=buttons, kind="trade_validation", force=True)
                else:
                    send_fn(msg, buttons=buttons, kind="trade_validation", force=True)
                return
        except Exception as e:
            logger.warning(f"[TG] Envoi interactif échoué: {e}")
        if _send_buttons_direct(msg, buttons, kind="trade_validation"):
            return
        self._send_telegram(msg, kind="proposal", force=True)

    # ---------------------------- EXÉCUTION ----------------------------
    def _append_trade_journal(self, proposal: Dict[str, Any], metadata: Dict[str, Any]) -> None:
        try:
            ts = datetime.now(timezone.utc)
            day = ts.strftime("%Y-%m-%d")
            journal_dir = pathlib.Path("data") / "journal"
            journal_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "timestamp": ts.isoformat(),
                "symbol": self.symbol,
                "side": proposal.get("side"),
                "lots": float(proposal.get("lots")) if proposal.get("lots") is not None else None,
                "entry": float(proposal.get("entry")) if proposal.get("entry") is not None else None,
                "sl": float(proposal.get("sl")) if proposal.get("sl") is not None else None,
                "tp": float(proposal.get("tp")) if proposal.get("tp") is not None else None,
                "score": float(proposal.get("score")) if proposal.get("score") is not None else None,
                "confluence": int(proposal.get("confluence")) if proposal.get("confluence") is not None else None,
                "rr_estimate": self._estimate_rr(proposal),
                "weighted_vote": metadata.get("weighted_vote") if metadata else None,
                "tracker_vote": metadata.get("tracker_vote") if metadata else None,
                "retcode": metadata.get("retcode") if metadata else None,
            }
            json_path = journal_dir / f"trades_{day}.jsonl"
            with json_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            csv_path = journal_dir / f"trades_{day}.csv"
            write_header = not csv_path.exists()
            with csv_path.open("a", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(record.keys()))
                if write_header:
                    writer.writeheader()
                writer.writerow(record)
        except Exception as exc:
            logger.debug("[Journal] unable to append trade: %s", exc)

    def execute_trade(self, signal: str):
        symbol = self.symbol  # Utilise le symbole de l'orchestrateur
        # --------- GATING QUALITÉ (backtests/rapports récents) ----------
        # DÉSACTIVÉ TEMPORAIREMENT pour permettre le trading sans historique de backtest
        # Pour réactiver: décommenter le bloc ci-dessous
        # try:
        #     # thresholds par défaut + overrides.yaml éventuels (self.ori_cfg)
        #     th = load_thresholds_for(symbol, overrides={"GLOBAL": (self.ori_cfg.get("gating_thresholds") or {})})
        #     ok, reason, metrics = should_allow_trade(symbol, thresholds=th, report_dir="reports/backtests")
        #     if not ok:
        #         # Log uniquement, pas de notification Telegram (trop de spam)
        #         logger.info(f"[GATING] {symbol}: rejet exécution ({reason}) | {metrics}")
        #         return False
        # except Exception as e:
        #     # en cas de souci de lecture, on loggue mais on n'empêche pas
        #     logger.warning(f"[GATING] {symbol}: erreur gating ({e})")
        # ---------------------------------------------------------------

        # Re-vérifie la fenêtre au moment de l'exécution
        if not self._is_symbol_profile_active_now():
            self._send_telegram(
                f"⏳ Fenêtre fermée pour {self.symbol} (planning profiles.schedule).",
                kind="status", force=True
            )
            return False
        if not self._is_in_trading_window():
            self._send_telegram(
                f"⏳ Fenêtre fermée pour {self.symbol} (orchestrator.trading_window).",
                kind="status", force=True
            )
            return False

        # --- PHASE 4: Vérification sessions de trading par type d'actif ---
        if self.asset_manager:
            try:
                now = datetime.now(ZoneInfo("Europe/Zurich"))
                allowed, reason = self.asset_manager.is_trading_allowed(self.symbol, now)
                if not allowed:
                    self._send_telegram(
                        f"⏰ [PHASE4] Session fermée pour {self.symbol}: {reason}",
                        kind="status", force=True
                    )
                    logger.info(f"[PHASE4] Trading not allowed for {self.symbol}: {reason}")
                    return False
                logger.debug(f"[PHASE4] Trading session OK for {self.symbol}: {reason}")
            except Exception as e:
                logger.warning(f"[PHASE4] Session check failed: {e}, continuing anyway")

            # Vérification des corrélations (éviter de trader symboles corrélés simultanément)
            try:
                # Récupérer les positions ouvertes
                open_positions = []
                positions = _mt5.positions_get() if _mt5 else []
                for pos in positions or []:
                    pos_symbol = broker_to_canon(str(getattr(pos, "symbol", "")))
                    if pos_symbol:
                        open_positions.append(pos_symbol)

                # Vérifier conflit de corrélation
                if open_positions:
                    conflict = self.asset_manager.check_correlation_conflict(self.symbol, open_positions)
                    if conflict:
                        self._send_telegram(
                            f"🔗 [PHASE4] Conflit de corrélation pour {self.symbol} (positions: {', '.join(open_positions)})",
                            kind="status", force=True
                        )
                        logger.info(f"[PHASE4] Correlation conflict for {self.symbol} with {open_positions}")
                        return False
            except Exception as e:
                logger.warning(f"[PHASE4] Correlation check failed: {e}, continuing anyway")
        # --- FIN PHASE 4 ---

        sig = (signal or "").upper().strip()
        if sig not in ("LONG", "SHORT"):
            raise ValueError("Signal invalide")

        if not self._last_proposal or self._last_proposal.get("side") != sig:
            logger.error("[EXEC] Aucun payload compatible en mémoire.")
            self._send_telegram("⚠️ Aucun trade prêt à exécuter.", kind="status")
            return False

        # --- TTL ---
        try:
            exp = self._last_proposal.get("expires_at")
            if exp:
                exp_dt = datetime.fromisoformat(exp)
                now_dt = datetime.now(timezone.utc)
                if now_dt > exp_dt:
                    # log l'expiration
                    self._log_proposal_csv(
                        self._last_proposal.get("side"),
                        self._last_proposal.get("entry"),
                        self._last_proposal.get("sl"),
                        self._last_proposal.get("tp"),
                        self._last_proposal.get("lots"),
                        self._last_proposal.get("score"),
                        self._last_proposal.get("confluence"),
                        self.proposal_ttl_secs,
                        expired=True,
                        executed=False
                    )
                    self._send_telegram(
                        f"⌛ Proposition expirée pour {self.symbol} → rejet automatique.",
                        kind="status", force=True
                    )
                    return False
        except Exception:
            pass

        p = self._last_proposal
        symbol = p["symbol"]          # canonique
        broker_symbol = canon_to_broker(symbol) or self.broker_symbol
        entry = float(p.get("entry", 0.0))
        lots = float(p["lots"])
        sl = float(p["sl"])
        tp = float(p["tp"])
        action = "BUY" if sig == "LONG" else "SELL"

        # ══════════════════════════════════════════════════════════════════════
        # HARD FILTERS - Qualité minimum absolue (FIX 2025-12-17)
        # Ces filtres ne peuvent PAS être contournés, même par auto_execute
        # ══════════════════════════════════════════════════════════════════════
        score_agr = float(p.get("score", 0.0) or 0.0)
        confluence = int(p.get("confluence", 0) or 0)
        tracker_vote = float(p.get("tracker_vote", 0.0) or 0.0)

        # 1) HARD FILTER: Score minimum absolu >= 8 (AUGMENTÉ 2026-01-06)
        HARD_MIN_SCORE = 8.0
        if score_agr < HARD_MIN_SCORE:
            logger.warning(f"[HARD_FILTER] {symbol}: score {score_agr:.1f} < {HARD_MIN_SCORE} → REJET")
            self._send_telegram(
                f"⛔ [QUALITÉ] {symbol}: score {score_agr:.1f} trop faible (min={HARD_MIN_SCORE}) → rejet",
                kind="status", force=True
            )
            return False

        # 2) HARD FILTER: Confluence minimum absolue >= 5 (AUGMENTÉ 2025-12-24)
        HARD_MIN_CONFLUENCE = 5
        if confluence < HARD_MIN_CONFLUENCE:
            logger.warning(f"[HARD_FILTER] {symbol}: confluence {confluence} < {HARD_MIN_CONFLUENCE} → REJET")
            self._send_telegram(
                f"⛔ [QUALITÉ] {symbol}: confluence {confluence} trop faible (min={HARD_MIN_CONFLUENCE}) → rejet",
                kind="status", force=True
            )
            return False

        # 3) HARD FILTER: Tracker vote contradictoire
        # Si le tracker historique indique que les agents ont mal performé dans cette direction
        TRACKER_CONTRADICTION_THRESHOLD = 0.25
        tracker_contradicts = (
            (sig == "LONG" and tracker_vote < -TRACKER_CONTRADICTION_THRESHOLD) or
            (sig == "SHORT" and tracker_vote > TRACKER_CONTRADICTION_THRESHOLD)
        )
        if tracker_contradicts:
            logger.warning(f"[HARD_FILTER] {symbol}: tracker_vote {tracker_vote:+.2f} contradictoire avec {sig} → REJET")
            self._send_telegram(
                f"⛔ [QUALITÉ] {symbol}: tracker {tracker_vote:+.2f} contradictoire avec {sig} → rejet",
                kind="status", force=True
            )
            return False

        logger.info(f"[HARD_FILTER] {symbol}: PASS score={score_agr:.1f} conf={confluence} tracker={tracker_vote:+.2f}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # (2026-01-06) HARD FILTER 4: DAILY LOSS LIMIT - Blocage si pertes journalières > 2%
        # Calcule le P&L réel depuis MT5 et bloque si limite atteinte
        # ══════════════════════════════════════════════════════════════════════
        try:
            risk_cfg = self.cfg.get("risk", {})
            daily_limit = float(risk_cfg.get("daily_loss_limit_pct", 0.02))

            if _mt5 and hasattr(_mt5, 'account_info'):
                account_info = _mt5.account_info()
                if account_info:
                    equity = float(account_info.equity)
                    balance = float(account_info.balance)
                    # P&L du jour = équité - balance de début de journée
                    # Approximation: utiliser le profit flottant + réalisé du jour
                    floating_pnl = float(account_info.profit)
                    daily_pnl_pct = floating_pnl / balance if balance > 0 else 0

                    if daily_pnl_pct <= -daily_limit:
                        logger.warning(f"[DAILY_LOSS] {symbol}: P&L journalier {daily_pnl_pct:.2%} <= -{daily_limit:.0%} → REJET")
                        self._send_telegram(
                            f"🛑 [DAILY LOSS] {symbol}: Limite journalière atteinte\n"
                            f"P&L: {daily_pnl_pct:.2%} (limite: -{daily_limit:.0%})\n"
                            f"Trading bloqué jusqu'à demain",
                            kind="alert", force=True
                        )
                        return False
        except Exception as e:
            logger.debug(f"[DAILY_LOSS] Erreur calcul: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # (2026-01-06) HARD FILTER 5: SESSION FILTER - Blocage heures toxiques
        # Bloque 0-5h et 18-23h UTC sauf crypto
        # ══════════════════════════════════════════════════════════════════════
        try:
            vol_cfg = self.cfg.get("volatility_filter", {})
            if vol_cfg.get("avoid_low_liquidity", True):
                current_hour_utc = datetime.now(timezone.utc).hour
                blocked_hours = vol_cfg.get("low_liquidity_hours_utc", [0, 1, 2, 3, 4, 5, 18, 19, 20, 21, 22, 23])

                # Vérifier si c'est une crypto (exception)
                is_crypto = symbol.upper() in ("BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "ADAUSD", "SOLUSD")
                asset_override = vol_cfg.get("asset_overrides", {}).get("crypto", {})
                crypto_exempt = is_crypto and not asset_override.get("avoid_low_liquidity", False)

                if current_hour_utc in blocked_hours and not crypto_exempt:
                    logger.warning(f"[SESSION_FILTER] {symbol}: heure {current_hour_utc}h UTC bloquée → REJET")
                    self._send_telegram(
                        f"🕐 [SESSION] {symbol}: Heure toxique {current_hour_utc}h UTC\n"
                        f"Trading bloqué 0-5h et 18-23h UTC\n→ Trade rejeté",
                        kind="status", force=True
                    )
                    return False
        except Exception as e:
            logger.debug(f"[SESSION_FILTER] Erreur: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # (2026-01-06) HARD FILTER 5: MTF CONFLUENCE - Blocage contre-tendance D1/H4
        # Utilise analyze_mtf_confluence pour vérifier l'alignement des TF supérieurs
        # ══════════════════════════════════════════════════════════════════════
        if analyze_mtf_confluence is not None:
            try:
                adv_cfg = self.cfg.get("advanced_analysis", {})
                mtf_cfg = adv_cfg.get("mtf_confluence", {})
                if mtf_cfg.get("block_counter_trend", True):
                    mtf_result = analyze_mtf_confluence(
                        symbol=symbol,
                        mt5_client=self.mt5,
                        target_direction=sig
                    )
                    if mtf_result:
                        alignment = mtf_result.get("alignment_ratio", 0.5)
                        min_align = float(mtf_cfg.get("min_alignment_ratio", 0.7))
                        recommendation = mtf_result.get("recommendation", "WAIT")

                        # Bloquer si alignement insuffisant ET contre la recommandation
                        if alignment < min_align and recommendation != sig:
                            logger.warning(
                                f"[MTF_FILTER] {symbol}: alignement {alignment:.0%} < {min_align:.0%}, "
                                f"reco={recommendation} vs {sig} → REJET"
                            )
                            self._send_telegram(
                                f"📊 [MTF] {symbol}: Contre-tendance D1/H4\n"
                                f"Alignement: {alignment:.0%} (min {min_align:.0%})\n"
                                f"Tendance HTF: {recommendation}\n→ {sig} rejeté",
                                kind="status", force=True
                            )
                            return False
                        logger.debug(f"[MTF_FILTER] {symbol}: alignement {alignment:.0%} OK, reco={recommendation}")
            except Exception as e:
                logger.warning(f"[MTF_FILTER] Erreur vérification {symbol}: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 1: EVENT GUARD - Blocage annonces économiques (2025-12-17)
        # Vérifie si une annonce HIGH/MEDIUM est imminente pour ce symbole
        # ══════════════════════════════════════════════════════════════════════
        if is_trade_blocked_by_event is not None:
            try:
                event_blocked, event_reason = is_trade_blocked_by_event(symbol)
                if event_blocked:
                    logger.warning(f"[EVENT_GUARD] {symbol}: {event_reason} → REJET")
                    self._send_telegram(
                        f"📅 [EVENT] {symbol}: Annonce économique imminente\n{event_reason}\n→ Trade rejeté",
                        kind="alert", force=True
                    )
                    return False
                else:
                    logger.debug(f"[EVENT_GUARD] {symbol}: pas de blocage événement")
            except Exception as e:
                logger.warning(f"[EVENT_GUARD] Erreur vérification {symbol}: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 3: SCORE COMPOSITE - Enrichissement du score avec tous les outils
        # Calcule un score unifié et optimise SL/TP via Volume Profile
        # ══════════════════════════════════════════════════════════════════════
        composite_result = None
        if COMPOSITE_SCORE_AVAILABLE and calculate_composite_score is not None:
            try:
                composite_result = calculate_composite_score(
                    symbol=symbol,
                    direction=sig,
                    agents_score=score_agr,
                    agents_confluence=confluence,
                    current_price=entry,
                    original_sl=sl,
                    original_tp=tp
                )

                # Log le score composite
                logger.info(f"[COMPOSITE] {symbol}: score_composite={composite_result.composite_score:.1f} "
                           f"(original={score_agr:.1f}) conf={composite_result.composite_confidence:.2f}")

                # Bloquer si Inter-Market contradictoire
                if sig == "LONG" and composite_result.im_should_avoid_long:
                    logger.warning(f"[COMPOSITE] {symbol}: Inter-Market recommande d'éviter LONG → REJET")
                    self._send_telegram(
                        f"🌐 [INTER-MARKET] {symbol}: Flux macro bearish\n"
                        f"Bias: {composite_result.im_bias}\n→ LONG rejeté",
                        kind="status", force=True
                    )
                    return False

                if sig == "SHORT" and composite_result.im_should_avoid_short:
                    logger.warning(f"[COMPOSITE] {symbol}: Inter-Market recommande d'éviter SHORT → REJET")
                    self._send_telegram(
                        f"🌐 [INTER-MARKET] {symbol}: Flux macro bullish\n"
                        f"Bias: {composite_result.im_bias}\n→ SHORT rejeté",
                        kind="status", force=True
                    )
                    return False

                # Optimiser SL/TP via Volume Profile si disponible
                if composite_result.vp_suggested_sl or composite_result.vp_suggested_tp:
                    calculator = get_composite_calculator()
                    optimized_sl, optimized_tp = calculator.optimize_sl_tp(
                        result=composite_result,
                        original_sl=sl,
                        original_tp=tp,
                        current_price=entry,
                        direction=sig
                    )

                    # Appliquer les optimisations si elles sont valides
                    if optimized_sl != sl:
                        logger.info(f"[COMPOSITE] {symbol}: SL optimisé {sl:.5f} → {optimized_sl:.5f}")
                        sl = optimized_sl
                    if optimized_tp != tp:
                        logger.info(f"[COMPOSITE] {symbol}: TP optimisé {tp:.5f} → {optimized_tp:.5f}")
                        tp = optimized_tp

            except Exception as e:
                logger.warning(f"[COMPOSITE] Erreur calcul score {symbol}: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 4: INTER-MARKET GUARD - Blocage si contre flux macro (2025-12-17)
        # Vérifie directement via MT5 si le trade est contre le flux dominant
        # (Backup si le score composite n'a pas pu analyser)
        # ══════════════════════════════════════════════════════════════════════
        if (INTER_MARKET_GUARD_AVAILABLE and
            is_trade_blocked_by_inter_market is not None and
            composite_result is None):  # Seulement si composite n'a pas déjà vérifié
            try:
                # Initialiser le guard avec MT5 si disponible
                mt5_client = getattr(self, 'mt5', None)
                if mt5_client and hasattr(mt5_client, '_mt5'):
                    mt5_raw = mt5_client._mt5
                else:
                    mt5_raw = _mt5

                im_blocked, im_reason = is_trade_blocked_by_inter_market(symbol, sig, mt5_raw)

                if im_blocked:
                    logger.warning(f"[IM_GUARD] {symbol} {sig}: {im_reason} → REJET")
                    self._send_telegram(
                        f"🌐 [INTER-MARKET] {symbol} {sig}\n{im_reason}\n→ Trade rejeté",
                        kind="status", force=True
                    )
                    return False
                else:
                    logger.debug(f"[IM_GUARD] {symbol} {sig}: autorisé ({im_reason})")

            except Exception as e:
                logger.warning(f"[IM_GUARD] Erreur vérification {symbol}: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # --- Soft cap crypto bucket (safety à l'exécution) ---
        orch_cfg   = (self.profile.get("orchestrator") or {})
        crypto_cfg = (orch_cfg.get("crypto_bucket") or {})
        if bool(crypto_cfg.get("enabled", True)):
            cap        = float(crypto_cfg.get("cap", 0.02))
            min_factor = float(crypto_cfg.get("min_factor", 0.33))
            # override cap par phase (overrides.yaml)
            try:
                cap_override = float((self.ori_cfg.get("crypto_bucket_cap_override") or 0.0))
                if cap_override > 0:
                    cap = cap_override
            except Exception:
                pass
            prof = get_symbol_profile(symbol)  # type: ignore
            planned_risk = float(((prof.get("risk") or {}).get("risk_per_trade") or 0.0))

            factor = _apply_crypto_bucket_guard(symbol, planned_risk,
                                                cap=cap, get_profile=get_symbol_profile)

            if factor <= 0.0:
                self._send_telegram(f"[GUARD] {symbol}: crypto bucket plein → exécution annulée.",
                                    kind="status", force=True)
                return False

            lots = float(lots) * factor
            if factor < min_factor:
                self._send_telegram(f"[GUARD] {symbol}: facteur {factor:.2f} trop faible → exécution annulée.",
                                    kind="status", force=True)
                return False

            # Limite de positions ouvertes simultanées dans le bucket
            try:
                max_open = int(crypto_cfg.get("max_open", 2))
            except Exception:
                max_open = 2
            cur_open = _count_open_crypto_positions()
            if cur_open >= max_open:
                self._send_telegram(
                    f"[GUARD] {symbol}: {cur_open} positions crypto déjà ouvertes (max {max_open}) → exécution annulée.",
                    kind="status", force=True
                )
                return False
        # ------------------------------------------------------

        # --- Gating anti-spam (toutes conditions locales) ---
        ok_gate, why = self._trade_gate_ok()
        if not ok_gate:
            self._send_telegram(f"⛔ Gate {self.symbol}: {why} → exécution annulée.", kind="status", force=True)
            return False
        # --------- NEWS FREEZE (fenêtre autour des news majeures) ---------
        orch_cfg = (self.profile.get("orchestrator") or {})
        news_cfg = (orch_cfg.get("news_filter") or {})
        if bool(news_cfg.get("enabled", True)):
            csv_path = str(news_cfg.get("csv_path", "data/news_calendar.csv"))
            win_before = int(news_cfg.get("window_before_min", 15))
            win_after  = int(news_cfg.get("window_after_min", 15))
            impacts    = news_cfg.get("impacts", ["High"])
            # fenêtres manuelles forcées via overrides (isoformat local)
            manual = []
            for rng in (news_cfg.get("manual_freezes") or []):
                if isinstance(rng, dict) and rng.get("start") and rng.get("end"):
                    manual.append((rng["start"], rng["end"]))
            frozen, why = is_frozen_now(
                symbol=symbol,
                profile=self.profile,
                news_csv=csv_path,
                window_before_min=win_before,
                window_after_min=win_after,
                impacts=impacts,
                manual_freezes=manual
            )
            if frozen:
                _record_guard_event(self.symbol, "news-freeze", why)
                self._send_telegram(f"[NEWS] Freeze actif: {why} -> execution annulee.", kind="status", force=True)
                return False
        # ------------------------------------------------------------------
        # --------- LIVE GUARD (PF/HitRate 7j sur audit) ----------
        try:
            live_cfg = (self.profile.get("orchestrator") or {}).get("live_guard") or {}
            if bool(live_cfg.get("enabled", True)):
                ok, reason, m = should_allow_live(
                    symbol=symbol,
                    thresholds={
                        "pf_min_live": live_cfg.get("pf_min_live", 1.10),
                        "hit_min_live": live_cfg.get("hit_min_live", 0.45),
                        "min_trades_live": live_cfg.get("min_trades_live", 10),
                        "lookback_days": live_cfg.get("lookback_days", 7),
                    }
                )
                if not ok:
                    _record_guard_event(self.symbol, "live-guard", f"{reason} | metrics={m}")
                    self._send_telegram(
                        f"[LIVE GUARD] {symbol}: rejet execution ({reason}) | metrics={m}",
                        kind="status", force=True
                    )
                    return False
        except Exception as e:
            self._send_telegram(f"[LIVE GUARD] erreur: {e}", kind="status", force=False)
        # --------- DRY RUN : pas d'envoi MT5, juste notification + audit ----------
        if getattr(self, "dry_run", False):
            msg = (f"#NEW_TRADE_SIM | {symbol} | {side} | entry={entry} | vol={volume} | " # type: ignore
                   f"SL={sl} | TP1={tp1} | TP2={tp2} | score={score} | confluences={','.join(confluences)[:120]}") # type: ignore
            self._send_telegram(msg, kind="status", force=True)
            audit_append("NEW_TRADE_SIM", {
                "symbol": symbol,
                "side": side, # type: ignore
                "entry": entry,
                "volume": volume, # type: ignore
                "sl": sl,
                "tp1": tp1, # type: ignore
                "tp2": tp2, # pyright: ignore[reportUndefinedVariable]
                "score": score, # type: ignore
                "meta": {"dry_run": True}
            })
            self._record_performance_stats(self._last_proposal, executed=False, outcome=None, retcode=None)
            return True
        # --------------------------------------------------------------------------

        # ══════════════════════════════════════════════════════════════════════
        # (2026-02-04) CRITICAL FIX: Enforce max_volume per-trade limit
        # AVANT l'envoi de l'ordre, plafonner le volume à la limite configurée
        # ══════════════════════════════════════════════════════════════════════
        pos_limits = (self.profile.get("orchestrator") or {}).get("position_limits") or {}
        max_volume_limit = float(pos_limits.get("max_volume", 0.0) or 0.0)

        if max_volume_limit > 0 and lots > max_volume_limit:
            logger.warning(
                f"[RISK] {symbol}: Volume {lots:.2f} dépasse limite max_volume={max_volume_limit:.2f} → plafonné"
            )
            self._send_telegram(
                f"⚠️ [VOLUME LIMIT] {symbol}: Volume plafonné\n"
                f"Calculé: {lots:.2f} lots\n"
                f"Limite: {max_volume_limit:.2f} lots\n"
                f"→ Exécution avec {max_volume_limit:.2f} lots",
                kind="status", force=True
            )
            lots = max_volume_limit
        # ══════════════════════════════════════════════════════════════════════

        # --- Envoi ordre ---
        result = self.mt5.place_order(broker_symbol, action, lots, price=None, sl=sl, tp=tp)
        retcode_val = int(result.get("retcode", -1)) if result else None
        ok = bool(result) and retcode_val == getattr(_mt5, "TRADE_RETCODE_DONE", 10009) if _mt5 else (retcode_val == 10009)

        # --- Log CSV exécution ---
        self._log_trade_execution(self._last_proposal or {
            "symbol": symbol, "side": sig, "entry": None, "sl": sl, "tp": tp, "lots": lots
        }, result, ok)
        self._record_performance_stats(
            self._last_proposal,
            executed=ok,
            outcome=self._estimate_rr(self._last_proposal) if ok else None,
            retcode=retcode_val,
        )

        if ok:
            # Safe conversion to float for logging
            try:
                conf_val = float(self._last_ctx.get("confluence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf_val = 0.0
            try:
                tracker_val = float(self._last_ctx.get("tracker_vote_raw", 0.0) or 0.0)
            except (TypeError, ValueError):
                tracker_val = 0.0
            logger.info(
                "[EXEC] %s confluence=%.2f components=%s notes=%s tracker=%.2f",
                self.symbol,
                conf_val,
                self._last_ctx.get("confluence_breakdown"),
                self._last_ctx.get("decision_notes"),
                tracker_val,
            )
            # mémorise la bougie pour le TF de gating
            if self.once_per_candle_tf:
                try:
                    bar_id = self._current_bar_id(self.once_per_candle_tf)
                    if bar_id is not None:
                        self._last_bar_traded_by_tf[self.once_per_candle_tf] = bar_id
                except Exception:
                    pass

            # met à jour l'horodatage de dernière exécution
            self._last_exec_ts = datetime.now(timezone.utc)

            # FIX 2025-12-17: Incrémenter le compteur horaire
            self._trades_this_hour += 1
            logger.info(f"[GATE] Trades cette heure: {self._trades_this_hour}/{self._max_trades_per_hour}")

            # cooldown post-trade
            self._arm_cooldown(self._cooldown_after_trade_min, "post-trade")

            # log agents snapshot pour l'analyse post-trade
            try:
                ctx = self._last_ctx or {}
                self._log_agents_snapshot_jsonl(
                    ctx.get("per_tf_signals"), ctx.get("global_signals"),
                    ctx.get("indicators"), ctx.get("market"),
                    context="executed"
                )
            except Exception:
                pass

            self._send_telegram(
                f"🚀 Trade {sig} exécuté sur {symbol} | lots={lots:.3f}", kind="status", force=True
            )
            self._notify_trade_event("NEW_TRADE", {
                "symbol": symbol,
                "side": sig,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "lots": lots,
                "score": locals().get("score_agr"),
                "confluence": locals().get("confluence"),
            })
            return True
        else:
            self._send_telegram(
                f"❌ Échec exécution trade {sig} sur {symbol} | retcode={result.get('retcode') if result else 'None'}",
                kind="status",
                force=True,
            )
            return False

    # ---------------------------- PUBLIC API ----------------------------
    def _run_agents_and_decide_sync(self):
        """
        Wrapper synchrone pour BackgroundScheduler.
        Exécute la coroutine async _run_agents_and_decide dans le event loop principal.
        """
        if self._event_loop and self._event_loop.is_running():
            import asyncio
            # Programmer la coroutine dans le loop principal depuis le thread du scheduler
            asyncio.run_coroutine_threadsafe(self._run_agents_and_decide(), self._event_loop)
        else:
            logger.warning(f"[ORCH] {self.symbol} - Event loop non disponible, agents non exécutés")

    async def start(self):
        # Stocker le event loop pour que le scheduler puisse exécuter les coroutines async
        import asyncio
        self._event_loop = asyncio.get_running_loop()
        logger.info(f"[ORCH] {self.symbol} - Event loop stocké pour exécution async depuis scheduler")

        interval_seconds = int(self.timeframes_cfg.get("orchestrator", 60))
        job_id = f"orch_{self.symbol}"

        # Nettoyage d’anciens jobs, si existent
        for jid in (job_id, f"report_{self.symbol}", f"autoopt_{self.symbol}", f"pm_{self.symbol}"):
            try:
                self.scheduler.remove_job(jid)
            except Exception:
                pass

        # Boucle principale de décision
        # Utiliser le wrapper synchrone qui exécute la coroutine async dans le bon event loop
        self.scheduler.add_job(
            self._run_agents_and_decide_sync,
            "interval",
            seconds=interval_seconds,
            id=job_id,
            replace_existing=True,
        )

        # Rapport toutes les N heures (2h par défaut via status_report_hours)
        try:
            self.scheduler.add_job(
                self._send_status_report,
                "interval",
                hours=max(1, self.status_report_hours),
                id=f"report_{self.symbol}",
                replace_existing=True,
            )
        except Exception as e:
            logger.warning(f"[REPORT] schedule fail: {e}")

        # Auto-optimisation (ex. 21:05)
        try:
            self.scheduler.add_job(
                self._auto_optimize_job,
                "cron",
                hour=21,
                minute=5,
                id=f"autoopt_{self.symbol}",
                replace_existing=True,
            )
        except Exception as e:
            logger.warning(f"[AUTO-OPT] schedule fail: {e}")

        # Optimisation Optuna globale (une seule fois, symbole principal)
        if self._is_primary_optimizer and bool(self.optimization_cfg.get("enabled", False)):
            opt_hour = int(self.optimization_cfg.get("hour", 1))
            opt_minute = int(self.optimization_cfg.get("minute", 15))
            try:
                self.scheduler.add_job(
                    self._nightly_backtest_and_optimize,
                    "cron",
                    hour=opt_hour,
                    minute=opt_minute,
                    id=f"nightly_optimize_{self.symbol}",
                    replace_existing=True,
                )
            except Exception as e:
                logger.warning(f"[NightlyOpt] schedule fail: {e}")

        # Gestion des positions ouvertes (BE/partials/trailing)
        pm_secs = int((self.profile.get("position_manager") or {}).get("interval_secs", 20))
        try:
            if self.pm and hasattr(self.pm, "manage_open_positions"):
                self.scheduler.add_job(
                    self.pm.manage_open_positions,
                    "interval",
                    seconds=pm_secs,
                    id=f"pm_{self.symbol}",
                    replace_existing=True,
                )
        except Exception as e:
            logger.warning(f"[PM] schedule fail: {e}")

        # Synchronisation historique MT5 (toutes les 5 minutes) - uniquement pour le premier symbole
        if self._is_primary_optimizer:
            try:
                self.scheduler.add_job(
                    self._sync_history_job,
                    "interval",
                    minutes=5,
                    id="sync_history_global",
                    replace_existing=True,
                )
                logger.info("[SYNC] History sync job scheduled (every 5 min)")
            except Exception as e:
                logger.warning(f"[SYNC] schedule fail: {e}")

        # Démarrage scheduler (protégé)
        try:
            self.scheduler.start()
        except SchedulerAlreadyRunningError:
            pass

        logger.info(f"[ORCH] {self.symbol} scheduler démarré ({interval_seconds}s).")

        # Message startup
        self._send_telegram(
            f"🚀 [STARTUP] EmpireIA — {self.symbol} prêt. Auto={self.auto_execute} TFs={self.tfs} votes={self.votes_required}",
            kind="startup",
            force=True,
        )

        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            self.scheduler.shutdown(wait=False)

    async def run(self):
        """Compatibilité avec ancien main.py"""
        await self.start()

    # ---------------------------- CORE ORCHESTRATION ----------------------------
    def _today_pnl_currency(self) -> float:
        """Somme du PnL réalisé aujourd’hui (timezone profil) pour CE symbole (broker)."""
        try:
            tz = self._tz
            now = datetime.now(tz)
            start = tz.localize(datetime(now.year, now.month, now.day, 0, 0, 0)).astimezone(timezone.utc)
            end   = tz.localize(datetime(now.year, now.month, now.day, 23, 59, 59)).astimezone(timezone.utc)
            deals = _mt5.history_deals_get(start, end) or []
            total = 0.0
            for d in deals:
                if getattr(d, "symbol", "") == self.broker_symbol:
                    total += float(getattr(d, "profit", 0.0) or 0.0)
            return float(total)
        except Exception:
            return 0.0

    def _current_position_stats(self) -> tuple[int, float, float]:
        try:
            poss = _mt5.positions_get(symbol=self.broker_symbol) or []
        except Exception:
            poss = []
        count = 0
        volume = 0.0
        net = 0.0
        buy_type = getattr(_mt5, "POSITION_TYPE_BUY", 0) if _mt5 else 0
        for p in poss:
            try:
                vol = float(getattr(p, "volume", 0.0) or 0.0)
            except Exception:
                vol = 0.0
            if vol <= 0:
                continue
            count += 1
            volume += vol
            try:
                p_type = int(getattr(p, "type", 0) or 0)
            except Exception:
                p_type = buy_type
            if p_type == buy_type:
                net += vol
            else:
                net -= vol
        return count, volume, net

    def _current_losing_streak(self, max_scan: int = 200) -> int:
        """Compte la streak de trades perdants consécutifs la PLUS récente pour CE symbole."""
        try:
            tz = self._tz
            end = datetime.now(tz).astimezone(timezone.utc)
            start = (datetime.now(tz) - timedelta(days=14)).astimezone(timezone.utc)
            deals = _mt5.history_deals_get(start, end) or []
            deals = sorted([d for d in deals if getattr(d, "symbol", "") == self.broker_symbol],
                           key=lambda x: getattr(x, "time", 0), reverse=True)[:max_scan]
            streak = 0
            for d in deals:
                profit = float(getattr(d, "profit", 0.0) or 0.0)
                if profit < 0:
                    streak += 1
                elif profit > 0:
                    break
                else:
                    break
            return streak
        except Exception:
            return 0

    async def _run_agents_and_decide(self):
        # === Cooldown guard ==========================================================
        if self._cooldown_active():
            try:
                secs = int((self._cooldown_until - datetime.now(timezone.utc)).total_seconds()) if self._cooldown_until else 0
                mins = max(0, (secs + 59) // 60)
                logger.info(f"[COOLDOWN] {self.symbol} actif ~{mins} min → skip cycle.")
            except Exception:
                pass
            return
        # ============================================================================

        # calcule les inputs nécessaires au RiskManager
        # Gardes quotidiens (fichiers de controle)
        guard_dir = pathlib.Path("data") / "guards"
        guard_reason = None
        guard_tag = None
        stop_flag = guard_dir / "stop_all.flag"
        target_flag = guard_dir / "target_met.flag"
        if stop_flag.exists():
            try:
                guard_reason = stop_flag.read_text(encoding="utf-8").strip() or "daily stop flag"
            except Exception:
                guard_reason = "daily stop flag"
            guard_tag = "daily-stop-flag"
        elif target_flag.exists():
            try:
                guard_reason = target_flag.read_text(encoding="utf-8").strip() or "daily target reached"
            except Exception:
                guard_reason = "daily target reached"
            guard_tag = "daily-target-flag"
        if guard_reason:
            if getattr(self, "_last_daily_guard_reason", None) != guard_reason:
                self._send_telegram(f"[GUARD] {self.symbol}: {guard_reason} | pause des entrees.", kind="status", force=True)
            self._last_daily_guard_reason = guard_reason
            _record_guard_event(self.symbol, guard_tag or "daily-guard", guard_reason)
            self._arm_cooldown(self._cooldown_after_loss_min, guard_tag or "daily-guard")
            return
        else:
            self._last_daily_guard_reason = None

        pos_limits = (self.profile.get("orchestrator") or {}).get("position_limits") or {}
        if pos_limits:
            max_positions = int(pos_limits.get("max_positions", 0) or 0)
            max_volume = float(pos_limits.get("max_volume", 0.0) or 0.0)
            max_net = float(pos_limits.get("max_net_volume", 0.0) or 0.0)
            count, volume, net = self._current_position_stats()
            reasons = []
            if max_positions and count >= max_positions:
                reasons.append(f"positions {count}/{max_positions}")
            if max_volume and volume >= max_volume:
                reasons.append(f"volume {volume:.2f}/{max_volume:.2f} lots")
            if max_net and abs(net) >= max_net:
                reasons.append(f"net {net:.2f} lots (lim {max_net:.2f})")
            if reasons:
                if getattr(self, "_last_position_guard_reason", None) != tuple(reasons):
                    self._send_telegram(f"[LIMIT] {self.symbol}: {', '.join(reasons)} – pause des entrees.", kind="status", force=True)
                self._last_position_guard_reason = tuple(reasons)
                _record_guard_event(self.symbol, "position-limit", ', '.join(reasons))
                cooldown_min = max(self._cooldown_after_loss_min, 5)
                self._arm_cooldown(cooldown_min, "position-limit")
                return
            else:
                self._last_position_guard_reason = None

        try:
            equity_start = float(((self.profile.get("account") or {}).get("equity_start") or 100000.0))  # type: ignore
        except Exception:
            equity_start = 100000.0

        pnl_today_ccy = self._today_pnl_currency()                      # P/L réalisé aujourd’hui (ce symbole)
        daily_loss_pct = pnl_today_ccy / max(equity_start, 1e-9)        # ex: -0.012 = -1.2%
        consec_losses = int(self._current_losing_streak())              # série de pertes consécutives

        # Limite journalière absolue (en devise)
        try:
            abs_limit = float((self.profile.get("risk") or {}).get("daily_loss_abs") or 0.0)
        except Exception:
            abs_limit = 0.0
        if abs_limit > 0 and pnl_today_ccy <= -abs(abs_limit):
            logger.info("[RISK] %s daily absolute loss limit reached (%.2f <= -%.2f)", self.symbol, pnl_today_ccy, abs_limit)
            _record_guard_event(self.symbol, "daily-abs-guard", f"PnL {pnl_today_ccy:.2f} <= -{abs_limit:.2f}")
            self._arm_cooldown(self._cooldown_after_loss_min, "daily-abs-guard")
            self._send_telegram(
                f"[RISK] Limite journaliere atteinte ({self.symbol}) - PnL {pnl_today_ccy:.2f} <= -{abs_limit:.2f}. Pause des entrees.",
                kind="status",
                force=True,
            )
            return

        # appelle la méthode nouvelle signature (2 args), sinon fallback ancienne (0 arg)
        stop = False
        try:
            stop = bool(self.risk.is_daily_limit_reached(daily_loss_pct, consec_losses))  # type: ignore
        except TypeError:
            stop = bool(self.risk.is_daily_limit_reached())  # type: ignore
        except Exception as e:
            logger.warning(f"[RISK] Guard check failed: {e}")
            stop = False

        if stop:
            _record_guard_event(self.symbol, "risk-guard", f"daily={daily_loss_pct:.2%}, streak={consec_losses}")
            self._arm_cooldown(self._cooldown_after_loss_min, "risk-guard")
            self._send_telegram(
                f"[RISK] Limites atteintes ({self.symbol}) - daily={daily_loss_pct:.2%}, streak={consec_losses}. Pause des entrees.",
                kind="status", force=True
            )
            return

        # --- Cooldown suite à série de pertes (configurable) ---
        if self._cooldown_enabled and self._cooldown_streak_n > 0 and consec_losses >= self._cooldown_streak_n:
            self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self._cooldown_streak_min)
            logger.info(f"[COOLDOWN] {self.symbol} → pause {self._cooldown_streak_min} min (streak={consec_losses}).")
            self._send_telegram(
                f"⏸️ Cooldown {self.symbol} {self._cooldown_streak_min} min (streak={consec_losses}).",
                kind="status"
            )
            return

        try:
            # Snapshot régulier d’equity pour suivi du DD/P&L
            self._log_equity_snapshot()

            symbol = self.symbol

            # 1) Planning profiles.yaml (on priorise le planning par symbole)
            if not self._is_symbol_profile_active_now():
                logger.info(f"[SCHEDULE] {symbol} désactivé selon profiles.schedule → pas d'action.")
                return

            # 2) Fenêtre orchestrator (optionnelle, fine-tuning intra-jour par profil)
            if not self._is_in_trading_window():
                logger.info(f"[WINDOW] {symbol} hors fenêtre orchestrator.trading_window → pas d'action.")
                return



            # 1) Collecte des signaux agents + indicateurs (+ hints SL/TP/PRICE)
            per_tf_signals, global_signals, indicators, market = self._gather_agent_signals(symbol)

            # Sauvegarde pour dashboard live
            self.save_signals_to_json(symbol, global_signals)

            # Prix courant & contexte
            price = market.get("price")

            # Fallback prix robuste
            if price is None:
                try:
                    price = self.mt5.get_last_price(symbol, side="BUY")
                except Exception:
                    price = None

            if price is None:
                logger.info(f"[{symbol}] Pas de prix (tick & fallback indisponibles) → skip.")
                return

            # 2) Agrégation → direction/score/confluence
            direction, score_agr, confluence, _details = self._compute_aggregate_direction(
                per_tf_signals, global_signals, indicators
            )
            regime_label, tracker_input = self._build_tracker_signals(per_tf_signals, global_signals)
            tracker_vote_raw = 0.0
            confluence_components: Dict[str, float] = {"agents": confluence}
            decision_notes: List[str] = []
            enriched_signals: List[Dict[str, Any]] = []
            if getattr(self, 'tracker', None) is not None and tracker_input:
                try:
                    tracker_vote_raw, enriched_signals = self.tracker.compute_weighted_vote(
                        self.symbol,
                        tracker_input,
                        regime=regime_label,
                    )
                except Exception:
                    tracker_vote_raw = 0.0
                    enriched_signals = tracker_input
            else:
                enriched_signals = tracker_input or []
            vote_strength = max(float(score_agr), abs(float(tracker_vote_raw)))

            # 3) Fast-tracks
            tech_signals = per_tf_signals.get("technical", {})
            news_dir = _norm(global_signals.get("news") if global_signals else None)
            tech_majority_long = sum(1 for sig in tech_signals.values() if _norm(sig) == "LONG")
            tech_majority_short = sum(1 for sig in tech_signals.values() if _norm(sig) == "SHORT")

            if tech_majority_long >= 4 and news_dir == "LONG":
                direction = "LONG"; score_agr = max(score_agr, 2.1); confluence = max(confluence, 2)
            elif tech_majority_short >= 4 and news_dir == "SHORT":
                direction = "SHORT"; score_agr = max(score_agr, 2.1); confluence = max(confluence, 2)
            else:
                has_tech_dir = any(_norm(sig) in ("LONG", "SHORT") for sig in tech_signals.values())
                swing_dir = _norm(global_signals.get("swing") if global_signals else None)
                if not has_tech_dir and swing_dir and swing_dir == news_dir and swing_dir in ("LONG", "SHORT"):
                    direction = swing_dir; score_agr = max(score_agr, 1.9); confluence = max(confluence, 2)

            whale_dir = _norm(global_signals.get("whale") if global_signals else None)
            if whale_dir in ("LONG", "SHORT") and self.whale_agent:
                over_cfg = self.whale_override_cfg
                if bool(over_cfg.get("enable", False)):
                    trust_val = float(indicators.get("WHALE_TRUST_SCORE", 0.0))
                    signal_val = float(indicators.get("WHALE_SIGNAL_SCORE", 0.0))
                    min_trust = float(over_cfg.get("min_trust", self.whale_cfg.get("min_trust", self.min_trust)))
                    min_signal = float(over_cfg.get("min_signal", self.whale_cfg.get("min_signal", self.min_signal)))
                    allow_vol = bool(over_cfg.get("allow_in_vol_spike", self.whale_cfg.get("allow_in_vol_spike", self.whale_allow_in_vol_spike)))
                    vol_limit = float(over_cfg.get("volatility_z_th", 3.0))
                    vol_z = float(self._whale_market_ctx.get(self.symbol, {}).get("volatility_zscore", 0.0) or 0.0)
                    if trust_val >= min_trust and signal_val >= min_signal:
                        if allow_vol or vol_z <= vol_limit:
                            direction = whale_dir
                            score_agr = max(score_agr, 1.8 + signal_val)
                            if self._whale_trust_ewma is not None:
                                score_agr = max(score_agr, 1.5 + self._whale_trust_ewma)
                            confluence = max(confluence, 2)
                            indicators["WHALE_OVERRIDE_ACTIVE"] = 1.0
                        else:
                            indicators["WHALE_OVERRIDE_BLOCKED"] = vol_z

            tracker_contrib = 0.0
            tracker_dir = "LONG" if tracker_vote_raw > 0 else ("SHORT" if tracker_vote_raw < 0 else "")
            tracker_strength = abs(float(tracker_vote_raw))
            if tracker_dir and direction and tracker_strength >= self.tracker_vote_threshold:
                normalized_tracker = min(tracker_strength, 3.0) / 3.0
                if tracker_dir == direction:
                    tracker_contrib = self.tracker_confluence_weight * normalized_tracker
                    decision_notes.append("tracker_support")
                else:
                    tracker_contrib = -self.tracker_confluence_weight * normalized_tracker
                    decision_notes.append("tracker_divergent")
            if tracker_contrib:
                confluence += tracker_contrib
                confluence_components["tracker"] = tracker_contrib

            market_contrib_map: Dict[str, float] = {}
            macro_block_active = bool(indicators.get("MACRO_BLOCK"))
            spread_block_active = bool(indicators.get("SPREAD_BLOCK"))
            atr_block_active = bool(indicators.get("ATR_BLOCK"))
            if macro_block_active:
                delta = -self.market_confluence_weight
                confluence += delta
                market_contrib_map["macro_block"] = delta
                decision_notes.append("macro_block")
            if spread_block_active:
                delta = -self.market_confluence_weight * 0.5
                confluence += delta
                market_contrib_map["spread_block"] = delta
                decision_notes.append("spread_block")
            if atr_block_active:
                delta = -self.market_confluence_weight * 0.5
                confluence += delta
                market_contrib_map["atr_block"] = delta
                decision_notes.append("atr_block")

            if not macro_block_active:
                vol_bias = float(indicators.get("VOL_ZSCORE") or indicators.get("VOL_Z") or 0.0)
                if abs(vol_bias) >= 1.5 and direction:
                    normalized_vol = min(abs(vol_bias), 3.0) / 3.0
                    if (direction == "LONG" and vol_bias > 0) or (direction == "SHORT" and vol_bias < 0):
                        delta = self.market_confluence_weight * 0.5 * normalized_vol
                        decision_notes.append("volatility_supports")
                    else:
                        delta = -self.market_confluence_weight * 0.5 * normalized_vol
                        decision_notes.append("volatility_opposes")
                    confluence += delta
                    market_contrib_map["volatility_bias"] = market_contrib_map.get("volatility_bias", 0.0) + delta

            if market_contrib_map:
                confluence_components["market"] = confluence_components.get("market", 0.0) + sum(market_contrib_map.values())

            if confluence < 0:
                confluence = 0.0

            # 4) Conditions minimales
            reasons: List[str] = []
            # Blocage macro autour des news
            if indicators.get("MACRO_BLOCK"):
                reasons.append("macro_block")

            # ══════════════════════════════════════════════════════════════════
            # PHASE 2 (2025-12-25): Economic Calendar - Blocage autour des news
            # ══════════════════════════════════════════════════════════════════
            if ECONOMIC_CALENDAR_AVAILABLE and econ_should_avoid_trading is not None:
                try:
                    avoid_trade, avoid_reason = econ_should_avoid_trading(symbol)
                    if avoid_trade:
                        reasons.append(f"econ_calendar:{avoid_reason}")
                        decision_notes.append(f"econ_blocked:{avoid_reason}")
                        logger.info(f"[ECON_CAL] {symbol} bloque: {avoid_reason}")
                except Exception as e:
                    logger.debug(f"[ECON_CAL] Erreur verification: {e}")

            if self._weekend_guard_blocked():
                reasons.append("forex_weekend_guard")
                decision_notes.append("forex_weekend_guard")

            if direction not in ("LONG", "SHORT"):
                reasons.append("direction_indeterminee")
            if score_agr < self.min_score_for_proposal:
                reasons.append(f"score({score_agr:.2f})<min({self.min_score_for_proposal:.2f})")
            if confluence < self.min_confluence:
                reasons.append(f"confluence({confluence})<min({self.min_confluence})")

            # ══════════════════════════════════════════════════════════════════
            # OPTIMISATION 2025-12-13: Filtre de volatilité
            # ══════════════════════════════════════════════════════════════════
            if should_trade_volatility is not None:
                try:
                    vol_cfg = (load_config() or {}).get("volatility_filter", {})
                    if vol_cfg.get("enabled", True):
                        current_atr = indicators.get("ATR_H1") or indicators.get("ATR_M30") or 0
                        spread = indicators.get("SPREAD") or 0
                        has_news = bool(indicators.get("MACRO_BLOCK") or indicators.get("NEWS_PENDING"))
                        vol_allowed, vol_reason, vol_metrics = should_trade_volatility(
                            symbol=symbol,
                            current_atr=float(current_atr),
                            spread=float(spread) if spread else None,
                            has_news_event=has_news
                        )
                        if not vol_allowed:
                            reasons.append(f"volatility_filter:{vol_reason}")
                            decision_notes.append(f"vol_blocked:{vol_reason}")
                except Exception as e:
                    logger.debug(f"[VOL_FILTER] Erreur: {e}")

            swing_sig = _norm(global_signals.get("swing") if global_signals else None)
            scalping_sig = _norm(global_signals.get("scalping") if global_signals else None)
            if self.require_swing_confirm and swing_sig != direction:
                reasons.append("swing_non_confirme")
            if self.require_scalping_entry and scalping_sig != direction:
                reasons.append("scalping_non_confirme")

            # 5) SL/TP/Lots
            sl = float(indicators.get("CANDIDATE_SL")) if indicators.get("CANDIDATE_SL") is not None else None
            tp = float(indicators.get("CANDIDATE_TP")) if indicators.get("CANDIDATE_TP") is not None else None
            price_hint = float(indicators.get("CANDIDATE_PRICE")) if indicators.get("CANDIDATE_PRICE") is not None else None
            if price_hint:
                price = price_hint

            lots = None
            atr = indicators.get("ATR_H1") or indicators.get("ATR_M30")
            if direction in ("LONG", "SHORT"):
                if atr is None:
                    atr = self._compute_atr(symbol, timeframe="H1") or self._compute_atr(symbol, timeframe="M30")

                # Fallback ATR si manque SL/TP
                if atr:
                    mul_sl = float(self.ori_cfg.get("atr_sl_mult", 1.5))
                    mul_tp = float(self.ori_cfg.get("atr_tp_mult", 2.5))
                    if sl is None or tp is None:
                        if direction == "LONG":
                            sl = price - mul_sl * atr if sl is None else sl
                            tp = price + mul_tp * atr if tp is None else tp
                        else:
                            sl = price + mul_sl * atr if sl is None else sl
                            tp = price - mul_tp * atr if tp is None else tp

                # --- Normalisation SL/TP (anti-inversion / distance mini) ---
                try:
                    pt = float((self.profile.get("instrument", {}) or {}).get("point", 0.01))
                except Exception:
                    pt = 0.01
                mul_sl = float(self.ori_cfg.get("atr_sl_mult", 1.5))
                mul_tp = float(self.ori_cfg.get("atr_tp_mult", 2.5))
                # Distance minimale: max(10% ATR, 50 points broker)
                est_atr = float(atr) if atr is not None else (pt * 200.0)  # heuristique si ATR manquant
                broker_min = 0.0
                try:
                    if hasattr(self.mt5, "_min_stop_distance_points"):
                        min_pts_candidate = float(self.mt5._min_stop_distance_points(self.symbol))  # type: ignore[attr-defined]
                        broker_min = max(broker_min, min_pts_candidate * pt)
                except Exception:
                    broker_min = broker_min or 0.0
                min_pts = max(est_atr * 0.10, pt * 50.0, broker_min)

                def ensure_min_distance(p, s, t, side):
                    if side == "LONG":
                        if s is None or s >= p - min_pts:
                            s = p - mul_sl * (atr or pt * 200)
                        if t is None or t <= p + min_pts:
                            t = p + mul_tp * (atr or pt * 200)
                    else:
                        if s is None or s <= p + min_pts:
                            s = p + mul_sl * (atr or pt * 200)
                        if t is None or t >= p - min_pts:
                            t = p - mul_tp * (atr or pt * 200)
                    # enforce distances mini finales
                    if abs(p - s) < min_pts:
                        s = p - min_pts if side == "LONG" else p + min_pts
                    if abs(t - p) < min_pts:
                        t = p + min_pts if side == "LONG" else p - min_pts
                    return s, t

                if direction in ("LONG", "SHORT") and price is not None:
                    sl, tp = ensure_min_distance(price, sl, tp, direction)

                # Calcul lots si possible
                if (lots is None or lots <= 0) and sl is not None:
                    equity = market.get("equity")
                    if equity is None:
                        get_eq = getattr(self.risk, "get_equity", None)
                        if callable(get_eq):
                            try:
                                equity = float(get_eq())
                            except Exception:
                                equity = None
                    if equity is None:
                        equity = float(self.profile.get("account", {}).get("equity_start", 100000.0))

                    stop_distance_points = abs(price - sl) / max(
                        float(self.profile.get("instrument", {}).get("point", 0.01)), 1e-9
                    )
                    lots = self.risk.compute_position_size(
                        equity=equity, stop_distance_points=stop_distance_points
                    )
                    if lots is None or lots <= 0:
                        reasons.append("lot<=0")

            # ══════════════════════════════════════════════════════════════════
            # OPTIMISATION 2025-12-13: Filtre R:R minimum (Solution 2)
            # Refuse les trades avec un ratio Risk/Reward insuffisant
            # ══════════════════════════════════════════════════════════════════
            try:
                # Priorité: config orchestrator, sinon ori_cfg, sinon 1.5 par défaut
                min_rr = float(self.ori_cfg.get("min_rr_required") or self.ori_cfg.get("min_rr") or 1.5)
            except Exception:
                min_rr = 1.5  # Défaut OPTIMISATION 2025-12-13

            if sl is not None and tp is not None and price is not None and direction in ("LONG","SHORT"):
                if direction == "LONG":
                    risk = abs(price - sl)
                    reward = abs(tp - price)
                else:
                    risk = abs(sl - price)
                    reward = abs(price - tp)

                rr = reward / max(risk, 1e-9)

                if rr < min_rr:
                    reasons.append(f"rr({rr:.2f})<min_rr({min_rr:.2f})")
                    decision_notes.append(f"rr_blocked:{rr:.2f}<{min_rr}")
                    logger.debug(f"[RR_FILTER] {symbol} bloqué: R:R={rr:.2f} < min={min_rr}")

            # ══════════════════════════════════════════════════════════════════
            # OPTIMISATION 2025-12-13: Outils d'analyse avancés
            # ══════════════════════════════════════════════════════════════════
            advanced_tools_cfg = (load_config() or {}).get("advanced_analysis", {})

            # --- Outil 2: Market Regime Detector ---
            if detect_market_regime is not None and advanced_tools_cfg.get("market_regime_enabled", True):
                try:
                    # Récupérer les données OHLCV pour l'analyse de régime
                    regime_df = self._get_ohlcv_dataframe(symbol, "H1", 150) if hasattr(self, "_get_ohlcv_dataframe") else None
                    if regime_df is not None and len(regime_df) > 50:
                        regime_result = detect_market_regime(symbol, regime_df)
                        regime_type = regime_result.get("regime_name", "unknown")
                        regime_confidence = regime_result.get("confidence", 0)

                        decision_notes.append(f"regime:{regime_type}({regime_confidence:.2f})")

                        # Vérifier si le trade est aligné avec le régime
                        if regime_result.get("regime_stable", False):
                            # Refuser les longs en downtrend fort
                            if regime_type == "trending_down" and direction == "LONG" and regime_confidence > 0.6:
                                reasons.append(f"regime_against_long:{regime_type}")
                                logger.debug(f"[REGIME] {symbol} LONG bloqué: régime={regime_type}")
                            # Refuser les shorts en uptrend fort
                            elif regime_type == "trending_up" and direction == "SHORT" and regime_confidence > 0.6:
                                reasons.append(f"regime_against_short:{regime_type}")
                                logger.debug(f"[REGIME] {symbol} SHORT bloqué: régime={regime_type}")
                            # Avertir si marché trop volatile
                            elif regime_type == "volatile" and regime_confidence > 0.7:
                                decision_notes.append("volatile_market_caution")

                        # ══════════════════════════════════════════════════════════════
                        # OPTIMISATION 2025-12-30: Renforcer filtre contre-tendance BUY
                        # Si tendance baissiere HTF (meme non stable), exiger score >= 10
                        # ══════════════════════════════════════════════════════════════
                        if regime_type == "trending_down" and direction == "LONG":
                            current_score = confidence if isinstance(confidence, (int, float)) else 0
                            min_score_counter_trend = 10.0
                            if regime_confidence > 0.4 and current_score < min_score_counter_trend:
                                reasons.append(f"counter_trend_low_score:{current_score:.1f}<{min_score_counter_trend}")
                                decision_notes.append(f"buy_against_downtrend_blocked")
                                logger.info(f"[COUNTER_TREND] {symbol} BUY bloqué: score={current_score:.1f} < {min_score_counter_trend} en downtrend (conf={regime_confidence:.2f})")
                        elif regime_type == "trending_up" and direction == "SHORT":
                            current_score = confidence if isinstance(confidence, (int, float)) else 0
                            min_score_counter_trend = 10.0
                            if regime_confidence > 0.4 and current_score < min_score_counter_trend:
                                reasons.append(f"counter_trend_low_score:{current_score:.1f}<{min_score_counter_trend}")
                                decision_notes.append(f"short_against_uptrend_blocked")
                                logger.info(f"[COUNTER_TREND] {symbol} SHORT bloqué: score={current_score:.1f} < {min_score_counter_trend} en uptrend (conf={regime_confidence:.2f})")
                except Exception as e:
                    logger.debug(f"[REGIME] Erreur analyse régime: {e}")

            # --- Outil 4: Advanced Sentiment (contrarian) ---
            if analyze_advanced_sentiment is not None and advanced_tools_cfg.get("sentiment_enabled", True):
                try:
                    sentiment_result = analyze_advanced_sentiment(symbol)
                    sentiment_signal = sentiment_result.get("signal", "WAIT")
                    contrarian_signal = sentiment_result.get("contrarian_signal")
                    sentiment_score = sentiment_result.get("sentiment_score", 0)

                    decision_notes.append(f"sentiment:{sentiment_signal}({sentiment_score:.2f})")

                    # Signal contrarian fort (retail extrême)
                    if contrarian_signal:
                        if contrarian_signal != direction and abs(sentiment_score) > 0.5:
                            decision_notes.append(f"contrarian_warning:{contrarian_signal}")
                            # Optionnel: bloquer si sentiment très extrême contre notre direction
                            if abs(sentiment_score) > 0.7:
                                reasons.append(f"sentiment_extreme_against:{contrarian_signal}")
                except Exception as e:
                    logger.debug(f"[SENTIMENT] Erreur analyse sentiment: {e}")

            # Configuration crypto bucket depuis le profil
            cb_cfg = (self.profile.get("orchestrator") or {}).get("crypto_bucket") or {}
            if _is_crypto_canon(symbol) and bool(cb_cfg.get("enabled", True)):
                # Limite de positions simultanées
                open_crypto = _count_open_crypto_positions()  # type: ignore
                max_open = int(cb_cfg.get("max_open", 2))
                if open_crypto >= max_open:
                    self._send_telegram(f"⛔ Crypto cap: {open_crypto} positions déjà ouvertes (max {max_open}) → skip", kind="status", force=False)
                    return None  # rejette la proposition

                # Cap d'exposition
                cap = float(cb_cfg.get("cap", 0.02))
                # override via overrides.yaml → self.ori_cfg déjà chargée en init
                try:
                    cap_override = float(self.ori_cfg.get("crypto_bucket_cap_override") or 0.0)
                    if cap_override > 0:
                        cap = cap_override
                except Exception:
                    pass
                used = _crypto_bucket_risk_used(get_symbol_profile)
                room = max(0.0, cap - used)

                # risque prévu pour le trade courant (approx comme dans _crypto_bucket_risk_used)
                inst = (self.profile.get("instrument") or {})
                point = float(inst.get("point") or 0.0)
                pip_value = float(inst.get("pip_value") or 0.0)
                ai = _mt5.account_info()
                equity = float(getattr(ai, "equity", 0.0) or 0.0)
                risk_ratio_planned = 0.0
                try:
                    if equity > 0 and point > 0 and pip_value > 0 and sl and entry and lots: # type: ignore
                        dist_pts = abs(float(entry) - float(sl)) / point # type: ignore
                        risk_ccy = dist_pts * pip_value * float(lots)
                        risk_ratio_planned = risk_ccy / equity
                except Exception:
                    risk_ratio_planned = 0.0

                if risk_ratio_planned > 0 and room < risk_ratio_planned:
                    factor = room / risk_ratio_planned if risk_ratio_planned > 0 else 0.0
                    min_factor = float(cb_cfg.get("min_factor", 0.33))
                    if factor < min_factor:
                        self._send_telegram(f"⚠️ Crypto cap room insuffisant (room={room:.4f}) → skip", kind="status", force=False)
                        return None
                    adj_lots = max(0.0, float(lots) * float(factor))
                    lots = adj_lots

            # 7) Décision : auto ou validation
            if reasons:
                logger.info(f"[RISK] Conditions non remplies → pas d'action. Raison: {', '.join(reasons)}")
                if confluence_components:
                    logger.info(
                        "[RISK] %s confluence breakdown=%s notes=%s",
                        self.symbol,
                        confluence_components,
                        decision_notes,
                    )
                return

            # conserve un contexte pour snapshot si exécution/proposition
            self._last_ctx = {
                "per_tf_signals": per_tf_signals,
                "global_signals": global_signals,
                "indicators": indicators,
                "market": market,
                "tracker_signals": enriched_signals,
                "tracker_vote": float(tracker_vote_raw),
                "weighted_vote": float(vote_strength),
                "regime": regime_label,
                "confluence_breakdown": confluence_components,
                "decision_notes": decision_notes,
                "confluence": float(confluence),
            }
            logger.debug(
                "[ORCH] %s confluence=%.2f breakdown=%s notes=%s tracker=%.2f score=%.2f",
                self.symbol,
                float(confluence),
                confluence_components,
                decision_notes,
                float(tracker_vote_raw),
                float(score_agr),
            )

            if direction in ("LONG", "SHORT"):
                missing = []
                if sl is None: missing.append("SL")
                if tp is None: missing.append("TP")
                if lots is None or lots <= 0: missing.append("lots")
                if missing:
                    logger.info(f"[RISK] Skip. Manque: {missing} | equity={market.get('equity')} | price={price}")
                    return

                msg = (
                    f"📢 Proposition {symbol} → {direction}\n"
                    f"Prix: {price:.2f}\n"
                    f"SL: {sl:.2f} | TP: {tp:.2f}\n"
                    f"Lots: {lots:.3f}\n"
                    f"Score: {score_agr:.2f} | Confluence: {confluence}"
                )

                if self.auto_execute and not self.use_telegram_validation:
                    # préparer payload et exécuter directement
                    self._last_proposal = {
                        "symbol": self.symbol,
                        "side": direction,
                        "entry": float(price),
                        "sl": float(sl),
                        "tp": float(tp),
                        "lots": float(lots),
                        "score": float(score_agr),
                        "confluence": int(confluence),
                        "weighted_vote": float(vote_strength),
                        "tracker_vote": float(tracker_vote_raw),
                        "signals": enriched_signals,
                        "rr": float(score_agr),
                        "regime": regime_label,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=self.proposal_ttl_secs)).isoformat(),
                    }
                    # log proposal comme exécutée (la tentative va suivre)
                    self._log_proposal_csv(direction, price, sl, tp, lots, score_agr, confluence, self.proposal_ttl_secs, expired=False, executed=True)

                    # Snapshot "proposed" (même si auto)
                    try:
                        self._log_agents_snapshot_jsonl(
                            per_tf_signals, global_signals, indicators, market, context="proposed"
                        )
                    except Exception:
                        pass

                    self.execute_trade(direction)
                else:
                    # Snapshot "proposed"
                    try:
                        self._log_agents_snapshot_jsonl(
                            per_tf_signals, global_signals, indicators, market, context="proposed"
                        )
                    except Exception:
                        pass

                    await self._send_validation_proposal(
                        msg, direction, price, sl, tp, lots, score_agr, confluence,
                        weighted_vote=vote_strength,
                        tracker_vote=tracker_vote_raw,
                        signals=enriched_signals,
                        regime=regime_label,
                        rr=score_agr,
                    )
            else:
                logger.info(f"[{symbol}] Direction non établie → pas d'action.")

        except Exception as e:
            logger.exception(f"[ORCH] Erreur {self.symbol}: {e}")

    # ---------------------------- Helpers ----------------------------
    def _send_telegram(self, text: str, kind: str = "status", force: bool = False,
                       buttons: Optional[List[Dict[str, str]]] = None):
        """Envoi Telegram unifié."""
        try:
            if self.telegram_client and hasattr(self.telegram_client, "send_message"):
                # Si on a un event loop, programmer l'envoi async, sinon utiliser fallback
                if self._event_loop and self._event_loop.is_running():
                    import asyncio
                    asyncio.run_coroutine_threadsafe(
                        self.telegram_client.send_message(text, kind=kind, force=force, buttons=buttons),
                        self._event_loop
                    )
                else:
                    # Fallback si pas de loop (au démarrage par exemple)
                    try:
                        self.telegram_client.send_message(text, kind=kind, force=force, buttons=buttons)
                    except RuntimeWarning:
                        pass  # Ignorer le warning au démarrage
                return
        except Exception as e:
            logger.warning(f"[TG] Envoi via telegram_client échoué: {e}")

        if not _send_tg(text, kind=kind, force=force):
            logger.warning("[TG] Aucun sender Telegram disponible.")
    def _tg_quiet(self) -> bool:
        try:
            cfg = load_config() or {}
            tg = cfg.get("telegram") or {}
            return bool(tg.get("send_trade_validation_only", False))
        except Exception:
            return False

    def _safe_float(self, v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            f = float(v)
            if pd.isna(f):
                return None
            return f
        except Exception:
            return None

    def _setup_whale_connectors(self) -> None:
        feeds_cfg: Dict[str, Any] = dict(self.whale_cfg.get("feeds") or {})
        # Social verifier
        social_cfg = dict(feeds_cfg.get("social") or {})
        if SocialVerifier and bool(social_cfg.get("enabled", True)):
            try:
                self._social_verifier = SocialVerifier(sources=social_cfg.get("sources"))
            except Exception as exc:
                logger.warning("[Whale] social verifier init failed: %s", exc)
                self._social_verifier = None

        # On-chain listener
        onchain_cfg = dict(feeds_cfg.get("onchain") or {})
        if OnchainListener and bool(onchain_cfg.get("enabled", False)):
            try:
                listener = OnchainListener(
                    providers=onchain_cfg.get("providers", []),
                    poll_seconds=float(onchain_cfg.get("poll_seconds", 15.0)),
                )
                listener.start(self._on_whale_onchain_event)
                self._whale_connectors["onchain"] = listener
            except Exception as exc:
                logger.warning("[Whale] on-chain listener init failed: %s", exc)

        # CEX tracker
        cex_cfg = dict(feeds_cfg.get("cex") or {})
        if CexTracker and bool(cex_cfg.get("enabled", False)):
            try:
                tracker = CexTracker(
                    venues=cex_cfg.get("venues", []),
                    ws_url=cex_cfg.get("ws_url"),
                )
                tracker.connect(self._on_whale_cex_event)
                self._whale_connectors["cex"] = tracker
            except Exception as exc:
                logger.warning("[Whale] CEX tracker init failed: %s", exc)

    # ---------------------------- Whale helpers ----------------------------
    def register_whale_stats(self, wallet: str, stats: Dict[str, Any]) -> None:
        if not wallet or not stats:
            return
        key = str(wallet)
        current = self._whale_stats_cache.get(key, {})
        current.update(stats)
        self._whale_stats_cache[key] = current
        try:
            pf = current.get("pnl_ratio_30d")
            if pf is not None:
                record_whale_pf(wallet, float(pf))
        except Exception:
            pass

    def handle_whale_event(self, payload: Dict[str, Any], source: str = "onchain") -> None:
        if self.whale_agent is None:
            return
        try:
            event_payload = dict(payload or {})
            event_payload["symbol"] = str(event_payload.get("symbol", self.symbol)).upper()
            event_payload["side"] = str(event_payload.get("side", "")).upper()
            event_payload.setdefault("source", source)
            stats = event_payload.get("stats")
            if isinstance(stats, dict):
                self.register_whale_stats(event_payload.get("wallet", ""), stats)
            self.whale_agent.ingest_event(event_payload, source=source)
        except Exception as exc:
            logger.warning("[Whale] ingest error: %s", exc)
    def _refresh_whale_profile(self, wallet: str) -> None:
        if not wallet or self._social_verifier is None:
            return
        try:
            profile = self._social_verifier.refresh(wallet)
            self.register_whale_stats(
                wallet,
                {
                    "followers": profile.follower_count,
                    "verified": profile.verified,
                },
            )
        except Exception as exc:
            logger.debug("[Whale] social refresh failed: %s", exc)

    def _on_whale_onchain_event(self, event) -> None:
        try:
            ts = float(getattr(event, "ts", time.time()))
            wallet = str(getattr(event, "wallet", "") or "")
            symbol = str(getattr(event, "symbol", self.symbol)).upper()
            side = str(getattr(event, "side", "LONG")).upper()
            amount = float(getattr(event, "amount", 0.0) or 0.0)
            meta = dict(getattr(event, "meta", {}) or {})
            price = float(meta.get("price") or 0.0)
            if price <= 0:
                last_price = self._get_last_price(symbol)
                if last_price:
                    price = float(last_price)
            notional = float(meta.get("notional_usd") or 0.0)
            if notional <= 0 and price > 0 and amount:
                notional = price * amount
            if price <= 0 or notional <= 0:
                logger.debug("[Whale] on-chain event ignored (price/notional missing) wallet=%s", wallet)
                return
            payload = {
                "ts": ts,
                "wallet": wallet,
                "symbol": symbol,
                "side": side,
                "price": price,
                "volume_usd": notional,
                "price_impact_bps": float(meta.get("impact_bps", 0.0)),
                "slippage_bps": float(meta.get("slippage_bps", 0.0)),
                "volatility_zscore": float(meta.get("volatility_zscore", 0.0)),
                "setup_quality": float(meta.get("setup_quality", 0.5)),
                "entry_confidence": float(meta.get("entry_confidence", 0.5)),
                "stats": meta.get("stats"),
                "meta": meta,
            }
            self._refresh_whale_profile(wallet)
            self.handle_whale_event(payload, source="onchain")
        except Exception as exc:
            logger.warning("[Whale] on-chain handler error: %s", exc)

    def _on_whale_cex_event(self, event) -> None:
        try:
            ts = float(getattr(event, "ts", time.time()))
            wallet = str(getattr(event, "wallet", "") or "")
            symbol = str(getattr(event, "symbol", self.symbol)).upper()
            side = str(getattr(event, "side", "LONG")).upper()
            price = float(getattr(event, "price", 0.0) or 0.0)
            size_usd = float(getattr(event, "size_usd", 0.0) or 0.0)
            meta = dict(getattr(event, "meta", {}) or {})
            if price <= 0:
                last_price = self._get_last_price(symbol)
                if last_price:
                    price = float(last_price)
            if price <= 0 or size_usd <= 0:
                logger.debug("[Whale] CEX event ignored (price/notional missing) wallet=%s", wallet)
                return
            payload = {
                "ts": ts,
                "wallet": wallet,
                "symbol": symbol,
                "side": side,
                "price": price,
                "volume_usd": size_usd,
                "price_impact_bps": float(meta.get("impact_bps", 0.0)),
                "slippage_bps": float(meta.get("slippage_bps", 0.0)),
                "volatility_zscore": float(meta.get("volatility_zscore", 0.0)),
                "setup_quality": float(meta.get("setup_quality", 0.6)),
                "entry_confidence": float(meta.get("entry_confidence", 0.6)),
                "stats": meta.get("stats"),
                "meta": meta,
            }
            self._refresh_whale_profile(wallet)
            self.handle_whale_event(payload, source=str(getattr(event, "venue", "cex")).lower())
        except Exception as exc:
            logger.warning("[Whale] CEX handler error: %s", exc)

    def _gather_agent_signals(
        self, symbol: str
    ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str], Dict[str, float], Dict[str, Any]]:
        """
        Récupère les signaux par agent/TF + signaux globaux + indicateurs + contexte de marché.
        """
        # --- Contexte marché ---
        price = self._get_last_price(symbol)
        equity = None
        try:
            if hasattr(self.mt5, "get_account_info"):
                ai = self.mt5.get_account_info()
                if ai and hasattr(ai, "equity"):
                    equity = float(ai.equity)
        except Exception:
            pass

        agents_cfg = (self.profile.get("agents") or {})

        def agent_enabled(name: str) -> bool:
            try:
                cfg = agents_cfg.get(name) or {}
                return bool(cfg.get("enabled", True))
            except Exception:
                return True

        per_tf_signals: Dict[str, Dict[str, str]] = {
            "technical": {},
            "scalping": {},
            "swing": {},
            "structure": {},     # Price Action (BOS/CHoCH/FBO/AMD via StructureAgent/ScalpingAgent)
            "fundamental": {},
            "sentiment": {},
            "smc": {},
        }

        global_signals: Dict[str, str] = {}
        indicators: Dict[str, float] = {}
        market: Dict[str, Any] = {"price": price, "equity": equity}

        pref_tfs = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

        tech_details: Dict[str, Dict[str, float]] = {}
        scalp_details: Dict[str, Dict[str, float]] = {}
        swing_details: Dict[str, Dict[str, float]] = {}
        structure_details: Dict[str, Dict[str, float]] = {}
        whale_details: Dict[str, Dict[str, float]] = {}

        # --- Loader dynamique ---
        def load_agent(module_name: str, class_name: str):
            try:
                mod = importlib.import_module(f"agents.{module_name}")
                cls = getattr(mod, class_name, None)
                if cls is None:
                    logger.warning(f"[AGENT] Classe introuvable: agents.{module_name}.{class_name}")
                    return None

                init = getattr(cls, "__init__", None)
                if init is None:
                    return cls()

                sig = inspect.signature(init)
                accepted = set(sig.parameters.keys())

                params = {}
                if "symbol" in accepted:
                    params["symbol"] = symbol
                for k in ("mt5", "client", "mt5_client"):
                    if k in accepted:
                        params[k] = self.mt5
                        break
                for k in ("profile", "cfg", "config", "conf"):
                    if k in accepted:
                        params[k] = self.profile
                        break

                return cls(**params)
            except Exception as e:
                logger.warning(f"[AGENT] Chargement agents.{module_name}.{class_name} a échoué: {e}")
                return None

        # --- Runner générique ---
        def call_agent(agent, timeframe: Optional[str] = None) -> Optional[Dict[str, Any]]:
            if agent is None:
                return None

            try:
                if timeframe and hasattr(agent, "params") and isinstance(getattr(agent, "params"), dict):
                    agent.params["timeframe"] = timeframe
            except Exception:
                pass

            candidates = [
                "generate_signal", "execute",
                "run", "analyze", "analyse",
                "get_signal", "get_signals",
                "evaluate", "compute", "predict",
                "decide", "decision",
                "signal_tf", "get_tf_signal", "signal_for",
                "step", "process", "call", "__call__",
                "signal",
            ]
            last_err = None

            for name in candidates:
                fn = getattr(agent, name, None)

                if fn is not None and not callable(fn) and name == "signal":
                    try:
                        sig = str(fn).strip().upper()
                        return {"signal": sig}
                    except Exception as e:
                        last_err = e
                        continue

                if not callable(fn):
                    continue

                try:
                    res = None
                    if timeframe is not None and hasattr(fn, "__code__") and "timeframe" in getattr(fn, "__code__", ()).co_varnames:
                        res = fn(timeframe=timeframe)
                    else:
                        try:
                            res = fn()
                        except TypeError:
                            res = fn(timeframe)

                    if isinstance(res, dict):
                        return res
                    if isinstance(res, (list, tuple)) and res and isinstance(res[0], dict):
                        return res[0]
                    if isinstance(res, str):
                        return {"signal": res}
                except Exception as e:
                    last_err = e
                    continue

            return {"error": f"Aucune méthode compatible trouvée. Dernière erreur: {last_err}"}

        def store_details(bucket: Dict[str, Dict[str, float]], tf: str, out: Dict[str, Any]):
            sl = self._safe_float(out.get("sl"))
            tp = self._safe_float(out.get("tp"))
            pr = self._safe_float(out.get("price"))
            if sl is None and tp is None and pr is None:
                return
            bucket[tf] = {}
            if sl is not None:
                bucket[tf]["sl"] = sl
            if tp is not None:
                bucket[tf]["tp"] = tp
            if pr is not None:
                bucket[tf]["price"] = pr

        def pick_candidate(*buckets: Dict[str, Dict[str, float]]) -> Dict[str, float]:
            for bucket in buckets:
                for tf in pref_tfs:
                    d = bucket.get(tf)
                    if not d:
                        continue
                    cand = {}
                    if "price" in d:
                        cand["CANDIDATE_PRICE"] = d["price"]
                    if "sl" in d:
                        cand["CANDIDATE_SL"] = d["sl"]
                    if "tp" in d:
                        cand["CANDIDATE_TP"] = d["tp"]
                    if cand:
                        return cand
            return {}

        # 1) Technical
        technical = load_agent("technical", "TechnicalAgent") if agent_enabled("technical") else None
        if technical:
            for tf in self.tfs:
                out = call_agent(technical, timeframe=tf)
                if isinstance(out, dict):
                    per_tf_signals["technical"][tf] = _norm(out.get("signal"))
                    for k in ("ATR_H1", "ATR_M30", f"ATR_{tf}"):
                        if k in out and isinstance(out[k], (int, float)):
                            indicators[k] = float(out[k])
                    store_details(tech_details, tf, out)
        else:
            logger.info("[AGENTS] Technical désactivé via profile.")

        # 2) Scalping
        scalping = load_agent("scalping", "ScalpingAgent") if agent_enabled("scalping") else None
        if scalping:
            for tf in self.tfs:
                out = call_agent(scalping, timeframe=tf)
                if isinstance(out, dict):
                    per_tf_signals["scalping"][tf] = _norm(out.get("signal"))
                    store_details(scalp_details, tf, out)
        else:
            logger.info("[AGENTS] Scalping désactivé via profile.")

        # 3) Swing
        swing = load_agent("swing", "SwingAgent") if agent_enabled("swing") else None
        swing_votes = {"LONG": 0, "SHORT": 0}
        if swing:
            for tf in self.tfs:
                out = call_agent(swing, timeframe=tf)
                if isinstance(out, dict):
                    s = _norm(out.get("signal"))
                    if s:
                        per_tf_signals["swing"][tf] = s
                        swing_votes[s] += 1
                    store_details(swing_details, tf, out)
            if swing_votes["LONG"] > swing_votes["SHORT"]:
                global_signals["swing"] = "LONG"
            elif swing_votes["SHORT"] > swing_votes["LONG"]:
                global_signals["swing"] = "SHORT"
        else:
            logger.info("[AGENTS] Swing désactivé via profile.")

        # 3.5) Structure (BOS/CHoCH/FBO/AMD)
        structure = load_agent("structure", "StructureAgent") if agent_enabled("structure") else None
        structure_votes = {"LONG": 0, "SHORT": 0}
        smc_votes = {"LONG": 0, "SHORT": 0}
        if structure:
            for tf in self.tfs:
                out = call_agent(structure, timeframe=tf)
                if isinstance(out, dict):
                    s = _norm(out.get("signal"))
                    if s:
                        per_tf_signals["structure"][tf] = s
                        structure_votes[s] += 1
                    store_details(structure_details, tf, out)
                    smc = _norm(out.get("smc_signal"))
                    if smc:
                        per_tf_signals.setdefault("smc", {})[tf] = smc
                        smc_votes[smc] += 1
                    if out.get("smc_events"):
                        market.setdefault("smc_events", {})[tf] = out["smc_events"]
                    if out.get("smc_meta"):
                        market.setdefault("smc_meta", {})[tf] = out["smc_meta"]
            if structure_votes["LONG"] > structure_votes["SHORT"]:
                global_signals["structure"] = "LONG"
            elif structure_votes["SHORT"] > structure_votes["LONG"]:
                global_signals["structure"] = "SHORT"
            if smc_votes["LONG"] > smc_votes["SHORT"]:
                global_signals["smc"] = "LONG"
            elif smc_votes["SHORT"] > smc_votes["LONG"]:
                global_signals["smc"] = "SHORT"
        else:
            logger.info("[AGENTS] Structure désactivé via profile.")

        # 3.6) Whale agent (copy trading)
        whale = getattr(self, "whale_agent", None)
        if whale:
            out = whale.generate_signal()
            if isinstance(out, dict):
                s = _norm(out.get("signal"))
                if s and s != "WAIT":
                    per_tf_signals.setdefault("whale", {})["GLOBAL"] = s
                    global_signals["whale"] = s
                    indicators["WHALE_TRUST_SCORE"] = float(out.get("trust_score", 0.0))
                    indicators["WHALE_SIGNAL_SCORE"] = float(out.get("signal_score", 0.0))
                    indicators["WHALE_LATENCY_MS"] = float(out.get("latency_ms", 0.0))
                    whale_details["GLOBAL"] = {
                        "lots": float(out.get("lots", 0.0) or 0.0),
                        "sl": float(out.get("sl", 0.0) or 0.0),
                        "tp": float(out.get("tp", 0.0) or 0.0),
                    }
                    market.setdefault("whale", {}).update(
                        {
                            "wallet": out.get("wallet"),
                            "source": out.get("source"),
                            "latency_ms": out.get("latency_ms"),
                        }
                    )
                    alpha = float(self.whale_cfg.get("ewma_alpha", 0.2))
                    self._whale_trust_ewma = ewma(self._whale_trust_ewma, float(out.get("trust_score", 0.0)), alpha=alpha)
                    if self._whale_trust_ewma is not None:
                        record_whale_trust_ewma(self.symbol, float(self._whale_trust_ewma))
                    indicators["WHALE_TRUST_EWMA"] = float(self._whale_trust_ewma or 0.0)
        else:
            logger.info("[AGENTS] Whale agent désactivé via config.")

        # 4) News
        news = load_agent("news", "NewsAgent") if agent_enabled("news") else None
        if news:
            s = ""
            out_g = call_agent(news, timeframe=None)
            if isinstance(out_g, dict):
                s = _norm(out_g.get("signal"))
            if s:
                global_signals["news"] = s
            if "news" not in global_signals:
                votes = {"LONG": 0, "SHORT": 0}
                for tf in self.tfs:
                    out = call_agent(news, timeframe=tf)
                    if isinstance(out, dict):
                        s = _norm(out.get("signal"))
                        if s:
                            votes[s] += 1
                if votes["LONG"] > votes["SHORT"]:
                    global_signals["news"] = "LONG"
                elif votes["SHORT"] > votes["LONG"]:
                    global_signals["news"] = "SHORT"
        else:
            logger.info("[AGENTS] News désactivé via profile.")

        # 5) Sentiment
        sentiment = load_agent("sentiment", "SentimentAgent") if agent_enabled("sentiment") else None
        if sentiment:
            out_g = call_agent(sentiment, timeframe=None)
            if isinstance(out_g, dict):
                s = _norm(out_g.get("signal"))
                if s:
                    global_signals["sentiment"] = s
            if "sentiment" not in global_signals:
                votes = {"LONG": 0, "SHORT": 0}
                for tf in self.tfs:
                    out = call_agent(sentiment, timeframe=tf)
                    if isinstance(out, dict):
                        s = _norm(out.get("signal"))
                        if s:
                            votes[s] += 1
                if votes["LONG"] > votes["SHORT"]:
                    global_signals["sentiment"] = "LONG"
                elif votes["SHORT"] > votes["LONG"]:
                    global_signals["sentiment"] = "SHORT"
        else:
            logger.info("[AGENTS] Sentiment désactivé via profile.")

        # 6) Fundamental
        fundamental = load_agent("fundamental", "FundamentalAgent") if agent_enabled("fundamental") else None
        if fundamental:
            votes = {"LONG": 0, "SHORT": 0}
            for tf in self.tfs:
                out = call_agent(fundamental, timeframe=tf)
                if isinstance(out, dict):
                    s = _norm(out.get("signal"))
                    if s:
                        per_tf_signals["fundamental"][tf] = s
                        votes[s] += 1
            if votes["LONG"] == 0 and votes["SHORT"] == 0:
                out_g = call_agent(fundamental, timeframe=None)
                if isinstance(out_g, dict):
                    s = _norm(out_g.get("signal"))
                    if s:
                        global_signals["fundamental"] = s
        else:
            logger.info("[AGENTS] Fundamental désactivé via profile.")

        # 7) Macro (blocage news + biais)
        macro = load_agent("macro", "MacroAgent") if agent_enabled("macro") else None
        if macro:
            out_g = call_agent(macro, timeframe=None)
            if isinstance(out_g, dict):
                # blocage (indicateur)
                if bool(out_g.get("block")):
                    indicators["MACRO_BLOCK"] = 1.0
                s = _norm(out_g.get("signal"))
                if s:
                    # injecte comme 'fundamental' global
                    global_signals["fundamental"] = s
        else:
            logger.info("[AGENTS] Macro désactivé via profile.")

        # Nettoyage: enlever les agents vides pour la confluence
        per_tf_signals = {k: v for k, v in per_tf_signals.items() if any(_norm(s) for s in v.values())}

        # Choix d’un candidat SL/TP/PRICE (scalping > structure > technical > swing)
        candidate = pick_candidate(scalp_details, structure_details, tech_details, swing_details)
        indicators.update(candidate)

        # ATR de base si manquants
        if "ATR_H1" not in indicators:
            atr_h1 = self._compute_atr(symbol, timeframe="H1")
            if atr_h1:
                indicators["ATR_H1"] = atr_h1
        if "ATR_M30" not in indicators:
            atr_m30 = self._compute_atr(symbol, timeframe="M30")
            if atr_m30:
                indicators["ATR_M30"] = atr_m30

        atr_ctx = indicators.get("ATR_H1") or indicators.get("ATR_M30") or indicators.get("ATR_M15")
        self._whale_market_ctx[self.symbol] = {
            "atr": atr_ctx,
            "volatility_zscore": indicators.get("VOL_ZSCORE") or indicators.get("VOL_Z") or 0.0,
        }
        return per_tf_signals, global_signals, indicators, market

    def _compute_aggregate_direction(
        self,
        per_tf_signals: Dict[str, Dict[str, str]],
        global_signals: Dict[str, str],
        indicators: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, float, float, Dict[str, Any]]:
        """Calcule direction, score agrégé et confluence."""
        tf_w = self.tf_weights or {}

        vol_score = 0.0
        if indicators:
            vol_score = float(indicators.get("VOL_ZSCORE") or indicators.get("VOL_Z") or 0.0)
        vol_score = max(-3.0, min(3.0, vol_score))

        tf_priority = {
            "MN": 1.00,
            "W1": 0.95,
            "D1": 0.90,
            "H12": 0.85,
            "H8": 0.80,
            "H6": 0.75,
            "H4": 0.70,
            "H3": 0.65,
            "H2": 0.60,
            "H1": 0.55,
            "M45": 0.50,
            "M30": 0.45,
            "M20": 0.40,
            "M15": 0.35,
            "M10": 0.30,
            "M5": 0.20,
            "M3": 0.15,
            "M1": 0.10,
        }

        def w(tf: str) -> float:
            base = float(tf_w.get(tf, 1.0))
            if not self.tf_dynamic_scale:
                return base
            rank = tf_priority.get(tf.upper(), 0.5)
            dyn = 1.0
            if vol_score > 0.1:
                dyn += (vol_score / 3.0) * rank * self.tf_dynamic_scale
            elif vol_score < -0.1:
                dyn += (abs(vol_score) / 3.0) * (1.0 - rank) * self.tf_dynamic_scale
            return base * dyn

        score_long = 0.0
        score_short = 0.0
        confluence = 0.0

        for agent_name, tf_map in per_tf_signals.items():
            longs = sum(w(tf) for tf, sig in tf_map.items() if _norm(sig) == "LONG")
            shorts = sum(w(tf) for tf, sig in tf_map.items() if _norm(sig) == "SHORT")
            total_weight = longs + shorts
            if longs > shorts:
                score_long += longs - shorts
                dispersion = (longs - shorts) / max(total_weight, 1e-6)
                if dispersion >= self.min_confluence_dispersion:
                    confluence += float(self.confluence_weights.get(agent_name, 1.0))
            elif shorts > longs:
                score_short += shorts - longs
                dispersion = (shorts - longs) / max(total_weight, 1e-6)
                if dispersion >= self.min_confluence_dispersion:
                    confluence += float(self.confluence_weights.get(agent_name, 1.0))

        news_dir = _norm(global_signals.get("news") if global_signals else None)
        if news_dir == "LONG":
            score_long += self.w_news; confluence += 1
        elif news_dir == "SHORT":
            score_short += self.w_news; confluence += 1

        swing_dir = _norm(global_signals.get("swing") if global_signals else None)
        if swing_dir == "LONG":
            score_long += self.w_swing
        elif swing_dir == "SHORT":
            score_short += self.w_swing

        scalping_dir = _norm(global_signals.get("scalping") if global_signals else None)
        if scalping_dir == "LONG":
            score_long += self.w_scalp
        elif scalping_dir == "SHORT":
            score_short += self.w_scalp

        structure_dir = _norm(global_signals.get("structure") if global_signals else None)
        if structure_dir == "LONG":
            score_long += self.w_structure
        elif structure_dir == "SHORT":
            score_short += self.w_structure

        direction = "LONG" if score_long > score_short else ("SHORT" if score_short > score_long else "")
        score_agr = max(score_long, score_short)
        details: Dict[str, Any] = {}
        return direction, float(score_agr), int(confluence), details
    def _estimate_rr(self, proposal: Optional[Dict[str, Any]]) -> Optional[float]:
        try:
            if not proposal:
                return None
            side = (proposal.get("side") or "").upper()
            entry = float(proposal.get("entry"))
            sl = float(proposal.get("sl"))
            tp = float(proposal.get("tp"))
            if side == "LONG":
                return (tp - entry) / max(entry - sl, 1e-9)
            if side == "SHORT":
                return (entry - tp) / max(sl - entry, 1e-9)
        except Exception:
            return None
        return None


    def _build_tracker_signals(
        self,
        per_tf_signals: Dict[str, Dict[str, str]],
        global_signals: Dict[str, str],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        regime = str(self.ori_cfg.get("regime", "default"))
        signals: List[Dict[str, Any]] = []
        tf_weights = self.tf_weights or {}
        for agent, tf_map in (per_tf_signals or {}).items():
            for tf, sig in (tf_map or {}).items():
                norm = _norm(sig)
                if norm not in {"LONG", "SHORT"}:
                    continue
                weight = float(tf_weights.get(tf, 1.0))
                score = weight if norm == "LONG" else -weight
                signals.append({
                    "agent": f"{agent}_{tf.lower()}",
                    "source": agent,
                    "timeframe": tf,
                    "score": score,
                    "direction": norm,
                    "regime": regime,
                })
        trust_ewma = getattr(self, "_whale_trust_ewma", None)
        dynamic_whale_weight = getattr(self, "w_whale", 0.4)
        if trust_ewma is not None:
            dynamic_whale_weight *= max(0.2, float(trust_ewma))
        else:
            dynamic_whale_weight *= 0.3

        global_weights = [
            ("news", getattr(self, "w_news", 1.0)),
            ("swing", getattr(self, "w_swing", 1.0)),
            ("scalping", getattr(self, "w_scalp", 1.0)),
            ("structure", getattr(self, "w_structure", 1.0)),
            ("smc", getattr(self, "w_smc", 0.5)),
            ("whale", dynamic_whale_weight),
        ]
        for name, weight in global_weights:
            sig = _norm((global_signals or {}).get(name))
            if sig not in {"LONG", "SHORT"}:
                continue
            score = float(weight if sig == "LONG" else -weight)
            signals.append({
                "agent": f"global_{name}",
                "source": name,
                "timeframe": name.upper(),
                "score": score,
                "direction": sig,
                "regime": regime,
            })
        return regime, signals

    # NOTE: _count_open_crypto_positions est définie au niveau module (ligne ~458)

    # ---------------------------- Market helpers ----------------------------
    def _deep_merge(self, base: dict, extra: dict) -> dict:
        for k, v in (extra or {}).items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    def _apply_overrides_for_symbol(self, ov: dict) -> None:
        if not ov:
            return
        self.profile = self._deep_merge(self.profile or {}, ov)
        # refresh snapshots sans supposer que les attributs existent déjà
        self.ori_cfg = dict(self.profile.get("orchestrator") or {})
        self.votes_required = int(self.ori_cfg.get("votes_required", getattr(self, "votes_required", 1)))
        self.min_confluence = float(self.ori_cfg.get("min_confluence", getattr(self, "min_confluence", 1.0)))
        self.min_score_for_proposal = float(
            self.ori_cfg.get("min_score_for_proposal", getattr(self, "min_score_for_proposal", 2.0))
        )
        self.confluence_weights = {
            str(k): float(v)
            for k, v in (self.ori_cfg.get("confluence_weights") or {}).items()
        }
        self.min_confluence_dispersion = float(
            self.ori_cfg.get(
                "min_confluence_dispersion", getattr(self, "min_confluence_dispersion", 0.25)
            )
        )
        self.tracker_confluence_weight = float(
            self.ori_cfg.get(
                "tracker_confluence_weight", getattr(self, "tracker_confluence_weight", 0.5)
            )
        )
        self.tracker_vote_threshold = float(
            self.ori_cfg.get(
                "tracker_vote_threshold", getattr(self, "tracker_vote_threshold", 0.6)
            )
        )
        self.market_confluence_weight = float(
            self.ori_cfg.get(
                "market_confluence_weight", getattr(self, "market_confluence_weight", 0.5)
            )
        )
        self.tf_dynamic_scale = float(
            self.ori_cfg.get("tf_weight_dynamic_scale", getattr(self, "tf_dynamic_scale", 0.2))
        )
        default_wg = {
            "enabled": True,
            "close_positions": True,
            "close_day": "FRI",
            "close_time": "23:00",
            "reopen_day": "MON",
            "reopen_time": "00:05",
        }
        self.weekend_guard_cfg = dict(self.ori_cfg.get("weekend_guard") or getattr(self, "weekend_guard_cfg", {}))
        if not self.weekend_guard_cfg:
            self.weekend_guard_cfg = dict(default_wg)
        else:
            for key, value in default_wg.items():
                self.weekend_guard_cfg.setdefault(key, value)
        self._weekend_guard_last_flatten = None

    def _get_last_price(self, symbol: str) -> Optional[float]:
        """Récupère un prix récent (tick si dispo, sinon close M1) avec quelques retries."""
        try:
            broker = canon_to_broker(symbol) if symbol else self.broker_symbol

            # S'assure du symbole coté
            try:
                if hasattr(self.mt5, "ensure_symbol"):
                    self.mt5.ensure_symbol(broker)
            except Exception:
                pass

            # 1) Tick (mid si bid/ask, sinon last)
            if hasattr(self.mt5, "get_tick"):
                for _ in range(3):
                    tick = self.mt5.get_tick(broker)
                    if tick:
                        val = None
                        if isinstance(tick, dict):
                            bid = tick.get("bid"); ask = tick.get("ask"); last = tick.get("last")
                        else:
                            bid = getattr(tick, "bid", None); ask = getattr(tick, "ask", None); last = getattr(tick, "last", None)
                        if bid is not None and ask is not None:
                            val = (float(bid) + float(ask)) / 2.0
                        elif last is not None:
                            val = float(last)
                        if val:
                            return val
                    time.sleep(0.1)


            # 2) Fallback M1
            if hasattr(self.mt5, "get_rates"):
                for _ in range(5):
                    rates = self.mt5.get_rates(broker, "M1", count=1)
                    if rates:
                        last = rates[-1]
                        if isinstance(last, dict) and "close" in last:
                            return float(last["close"])
                        if hasattr(last, "close"):
                            return float(last.close)
                    time.sleep(0.1)

            return None
        except Exception:
            return None

    def _compute_atr(self, symbol: str, timeframe: str = "H1", period: int = 14) -> Optional[float]:
        """Calcul ATR simple depuis données MT5 si disponibles."""
        try:
            if not hasattr(self.mt5, "get_rates"):
                return None
            broker = canon_to_broker(symbol) if symbol else self.broker_symbol
            bars = self.mt5.get_rates(broker, timeframe, count=period + 2)
            if not bars or len(bars) < period + 2:
                return None

            df = pd.DataFrame(bars)
            if not all(c in df.columns for c in ("high", "low", "close")):
                return None

            high_low = df["high"] - df["low"]
            high_close = (df["high"] - df["close"].shift()).abs()
            low_close = (df["low"] - df["close"].shift()).abs()
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean().iloc[-1]
            if pd.isna(atr):
                return None
            return float(atr)
        except Exception:
            return None

    def _log_trade_execution(self, payload: dict, result: dict | None, ok: bool) -> None:
        """
        Append une ligne dans data/trades_log.csv à chaque tentative d'ordre.
        Colonnes: ts_utc, symbol, side, lots, entry, sl, tp, retcode, ok, ticket, reqid
        """
        try:
            os.makedirs("data", exist_ok=True)
            path = os.path.join("data", "trades_log.csv")
            fields = [
                "ts_utc","symbol","side","lots","entry","sl","tp",
                "retcode","ok","ticket","reqid"
            ]
            out = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": (payload or {}).get("symbol"),
                "side":   (payload or {}).get("side"),
                "lots":   float((payload or {}).get("lots", 0) or 0),
                "entry":  float((payload or {}).get("entry", 0) or 0),
                "sl":     float((payload or {}).get("sl", 0) or 0),
                "tp":     float((payload or {}).get("tp", 0) or 0),
                "retcode": (result or {}).get("retcode"),
                "ok":     bool(ok),
                "ticket": (result or {}).get("order") or (result or {}).get("deal"),
                "reqid":  (result or {}).get("request_id"),
            }
            file_exists = os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                if not file_exists:
                    w.writeheader()
                w.writerow(out)
        except Exception as e:
            logger.warning(f"[LOG] trades_log.csv erreur: {e}")

    def _log_equity_snapshot(self) -> None:
        """Append un snapshot equity dans data/equity_log.csv à chaque cycle."""
        try:
            ai = getattr(self.mt5, "get_account_info", lambda: None)()
            if not ai:
                return
            os.makedirs("data", exist_ok=True)
            path = os.path.join("data", "equity_log.csv")
            fields = ["ts_utc","balance","equity","margin","free_margin"]

            row = {
                "ts_utc":     datetime.now(timezone.utc).isoformat(),
                "balance":    float(getattr(ai, "balance", 0.0) or 0.0),
                "equity":     float(getattr(ai, "equity", 0.0) or 0.0),
                "margin":     float(getattr(ai, "margin", 0.0) or 0.0),
                "free_margin":float(getattr(ai, "margin_free", 0.0) or 0.0),
            }
            file_exists = os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                if not file_exists:
                    w.writeheader()
                w.writerow(row)
        except Exception as e:
            logger.warning(f"[LOG] equity_log.csv erreur: {e}")

    # ---------------------------- Nightly Optuna optimization ----------------------------
    async def _nightly_backtest_and_optimize(self):
        """Lance une optimisation Optuna globale puis recharge la config."""
        if not self._is_primary_optimizer:
            return
        try:
            cfg = load_config(str(CONFIG_PATH)) or {}
        except Exception:
            cfg = load_config() or {}
        opt_cfg = dict(cfg.get("optimization") or self.optimization_cfg or {})
        if not opt_cfg.get("enabled", False):
            logger.info("[NightlyOpt] Optimisation désactivée.")
            return

        target_symbol = opt_cfg.get("symbol") or self.symbol
        months = int(opt_cfg.get("months", 6))
        n_trials = int(opt_cfg.get("n_trials", 30))
        agents_to_opt = opt_cfg.get("agents") or ["technical", "scalping", "swing"]

        for agent_key in agents_to_opt:
            try:
                logger.info(f"[NightlyOpt] Optimisation {agent_key} ({months}m, {n_trials} trials) sur {target_symbol}")
                optimize_agent(agent_key=agent_key, symbol=target_symbol, months=months, n_trials=n_trials)
            except Exception as exc:
                logger.exception(f"[NightlyOpt] Echec optimisation {agent_key}: {exc}")

        try:
            reload_global_config(str(CONFIG_PATH))
            self.cfg = load_config(str(CONFIG_PATH)) or self.cfg
            self.optimization_cfg = dict(self.cfg.get("optimization") or {})
            logger.info("[NightlyOpt] Config rechargée après optimisation.")
        except Exception as exc:
            logger.warning(f"[NightlyOpt] Reload config failed: {exc}")

    # ---------------------------- Synchronisation historique MT5 ----------------------------
    def _sync_history_job(self):
        """
        Synchronise l'historique des deals MT5 vers data/deals_history.csv
        Appelé automatiquement toutes les 5 minutes.
        """
        try:
            import csv
            from datetime import timedelta

            if _mt5 is None:
                return

            end = datetime.now(timezone.utc)
            start = end - timedelta(days=1)  # Dernier jour seulement pour les syncs fréquentes
            deals = _mt5.history_deals_get(start, end) or []

            if not deals:
                return

            os.makedirs("data", exist_ok=True)
            path = os.path.join("data", "deals_history.csv")

            # Lire les position_id déjà enregistrés pour éviter les doublons
            existing_ids = set()
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            key = f"{row.get('time', '')}_{row.get('position_id', '')}_{row.get('order', '')}"
                            existing_ids.add(key)
                except Exception:
                    pass

            fields = ["time", "symbol", "type", "entry", "volume", "price", "profit",
                      "commission", "swap", "magic", "comment", "position_id", "order"]
            write_header = not os.path.exists(path)

            new_deals = 0
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                if write_header:
                    w.writeheader()
                for d in deals:
                    key = f"{getattr(d, 'time', 0)}_{getattr(d, 'position_id', 0)}_{getattr(d, 'order', 0)}"
                    if key in existing_ids:
                        continue
                    w.writerow({
                        "time": getattr(d, "time", 0),
                        "symbol": getattr(d, "symbol", ""),
                        "type": getattr(d, "type", ""),
                        "entry": getattr(d, "entry", ""),
                        "volume": float(getattr(d, "volume", 0.0) or 0.0),
                        "price": float(getattr(d, "price", 0.0) or 0.0),
                        "profit": float(getattr(d, "profit", 0.0) or 0.0),
                        "commission": float(getattr(d, "commission", 0.0) or 0.0),
                        "swap": float(getattr(d, "swap", 0.0) or 0.0),
                        "magic": getattr(d, "magic", 0),
                        "comment": getattr(d, "comment", ""),
                        "position_id": getattr(d, "position_id", 0),
                        "order": getattr(d, "order", 0),
                    })
                    new_deals += 1

            if new_deals > 0:
                logger.info(f"[SYNC] {new_deals} nouveaux deals synchronisés")

        except Exception as e:
            logger.warning(f"[SYNC] history sync error: {e}")

    # ---------------------------- Auto-optimisation nocturne ----------------------------
    async def _auto_optimize_job(self):
        """
        1) sync MT5 deals -> data/deals_history.csv
        2) run tuner -> proposals/profiles_patch.yaml
        3) si patch pour ce symbole: clamp + write to config/overrides.yaml + reload
        + sécurité : ne rien faire s'il y a des positions ouvertes sur ce symbole
        """
        try:
            # sécurité: ne pas modifier si position ouverte sur ce symbole
            try:
                poss = _mt5.positions_get(symbol=self.broker_symbol) or []
                if poss:
                    return
            except Exception:
                pass

            # Lancer synchronisation + tuner si présents
            try:
                if os.path.exists(os.path.join("utils", "sync_history.py")):
                    subprocess.run([sys.executable, os.path.join("utils","sync_history.py")], check=False)
            except Exception:
                pass
            try:
                if os.path.exists(os.path.join("utils", "param_tuner.py")):
                    subprocess.run([sys.executable, os.path.join("utils","param_tuner.py")], check=False)
            except Exception:
                pass

            ppath = os.path.join("proposals", "profiles_patch.yaml")
            if not os.path.exists(ppath):
                return

            with open(ppath, encoding="utf-8") as f:
                patch_all = yaml.safe_load(f) or {}
            patch_sym = patch_all.get(self.symbol)
            if not patch_sym:
                return

            # garde-fous: clamp des valeurs sensibles
            o = (patch_sym.get("orchestrator") or {})
            if "min_score_for_proposal" in o:
                o["min_score_for_proposal"] = float(min(3.0, max(1.4, float(o["min_score_for_proposal"]))))

            if "atr_sl_mult" in o:
                o["atr_sl_mult"] = float(min(3.0, max(1.0, float(o["atr_sl_mult"]))))

            if "atr_tp_mult" in o:
                o["atr_tp_mult"] = float(min(4.0, max(1.5, float(o["atr_tp_mult"]))))

            if "votes_required" in o:
                try:
                    o["votes_required"] = int(min(3, max(1, int(o["votes_required"]))))
                except Exception:
                    o.pop("votes_required", None)

            # écrire/merge dans config/overrides.yaml
            ov_path = os.path.join("config", "overrides.yaml")
            cur = {}
            if os.path.exists(ov_path):
                with open(ov_path, encoding="utf-8") as f:
                    cur = yaml.safe_load(f) or {}
            cur.setdefault(self.symbol, {}).setdefault("orchestrator", {}).update(o)

            os.makedirs("config", exist_ok=True)
            with open(ov_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cur, f, allow_unicode=True, sort_keys=False)

            # recharger en mémoire
            self._apply_overrides_for_symbol(cur.get(self.symbol) or {})
            self._send_telegram(f"🛠️ Auto-opt: overrides appliqués pour {self.symbol}: {list(o.keys())}",
                                kind="status", force=True)
        except Exception as e:
            logger.warning(f"[AUTO-OPT] job failed: {e}")


# =============================================================================
# Multi-symbol runner
# =============================================================================
async def run_for_symbols(symbols: List[str]):
    orchs: List[Orchestrator] = []
    started: List[str] = []
    for sym in symbols:
        try:
            o = Orchestrator(sym)
            # force depuis CLI si présent
            try:
                import builtins as _bi
                if getattr(_bi, "__EMPIRE_DRY_RUN__", False):
                    o.dry_run = True
            except Exception:
                pass
            orchs.append(o)
            started.append(sym)
        except Exception as e:
            logger.error(f"[ORCH] Skip {sym}: {e}")

    if started:
        _notify_global_start(started)
        # Ne démarre le worker qu'en cas de validation Telegram requise
        needs_cb = any(getattr(o, "use_telegram_validation", False) and not getattr(o, "auto_execute", True) for o in orchs)
        if needs_cb:
            _start_tg_callback_worker_once()

        # AUDIT 2025-12-27: Démarrer le Trade Outcome Tracker pour le feedback loop P&L
        if OUTCOME_TRACKER_AVAILABLE and start_outcome_tracking is not None:
            try:
                start_outcome_tracking()
                logger.info("[ORCH] Trade Outcome Tracker démarré")
            except Exception as e:
                logger.warning(f"[ORCH] Impossible de démarrer Outcome Tracker: {e}")

    tasks = [o.start() for o in orchs]  # coroutines
    await asyncio.gather(*tasks)

    if __name__ == "__main__":
        try:
            start_health_server(host="0.0.0.0", port=9108)
            logger.info("[/healthz] ready on :9108")
        except Exception as e:
            logger.warning(f"[health] start failed: {e}")
        # 1) Charger .env / .env.local (sans écraser les env existants)
        load_dotenv_env("config/.env", extra_paths=("config/.env.local",), overwrite=False)
        # 2) Valider la présence des secrets essentiels (on tolère l'absence en mode dry)
        try:
            get_required("MT5_LOGIN","MT5_PASSWORD","MT5_SERVER","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID")
        except RuntimeError as e:
            # En démo/dry-run, on peut logguer un warning et continuer
            logger.warning(f"[CONFIG] Secrets incomplets: {e}")
        import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", help="Liste des symboles à lancer")
    parser.add_argument("--dry-run", action="store_true", help="N'envoie aucun ordre MT5 (simulation/notification seulement)")
    # ... votre parser
    parser.add_argument(
        "--overrides",
        type=str,
        default=None,
        help="Chemin du fichier overrides (ex: config/presets/overrides.demo.yaml)"
    )
    args = parser.parse_args()

    global OVERRIDES_PATH
    if args.overrides:
        OVERRIDES_PATH = args.overrides

    syms = args.symbols if args.symbols else get_enabled_symbols()
    if not syms:
        raise SystemExit("Aucun symbole à lancer. Renseignez enabled_symbols dans profiles.yaml ou utilisez --symbols.")
    logger.info(f"Lancement Orchestrator en parallèle pour: {syms}")
    dry = bool(getattr(args, "dry_run", False))
    # astuce simple: mémoriser dans une globale pour que run_for_symbols la lise
    import builtins as _bi
    _bi.__EMPIRE_DRY_RUN__ = dry # type: ignore
    start_health_server(host="0.0.0.0", port=9108)
    if _mt5 is None:
        logger.warning("[MT5] module non disponible — mode démo/dry-run recommandé")

    asyncio.run(run_for_symbols(syms))
