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
from utils.performance_tracker import PerformancePoint, default_tracker, get_tracker_for_symbol
from utils.risk_manager import RiskManager
# AJOUT 2026-07-30 (P2) : gardes d'exécution extraits de execute_trade.
from orchestrator.trade_guards import (
    evaluer as _tg_evaluer,
    calculer_blocked_hours as _tg_blocked_hours,
    calculer_liq_penalty as _tg_liq_penalty,
    calculer_daily_pnl_pct as _tg_daily_pnl_pct,
    calculer_crypto_exempt as _tg_crypto_exempt,
)
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

# FIX 2026-02-20: Kill Switch Global + Circuit Breaker + Session Filter (étape 2)
try:
    from utils.risk_manager import get_global_kill_switch, GlobalKillSwitch
except Exception:
    get_global_kill_switch = None  # type: ignore
    GlobalKillSwitch = None  # type: ignore

try:
    from utils.circuit_breaker import get_circuit_breaker, CircuitBreaker
except Exception:
    get_circuit_breaker = None  # type: ignore
    CircuitBreaker = None  # type: ignore

try:
    from utils.session_filter import (
        is_in_prime_hours, get_adjusted_min_score, is_eod_restricted, should_close_eod
    )
except Exception:
    is_in_prime_hours = None  # type: ignore
    get_adjusted_min_score = None  # type: ignore
    is_eod_restricted = None  # type: ignore
    should_close_eod = None  # type: ignore

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
    from utils.trade_outcome_tracker import start_outcome_tracking, get_outcome_stats, get_qr_cooldown
    OUTCOME_TRACKER_AVAILABLE = True
except Exception:
    start_outcome_tracking = None  # type: ignore
    get_outcome_stats = None  # type: ignore
    get_qr_cooldown = None  # type: ignore
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
# Canoniques (profiles.yaml) — valeurs par défaut, configurable via orchestrator.crypto_symbols
CRYPTO_CANON = {"BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "ADAUSD", "SOLUSD"}
# Noms Broker/MT5 (positions_get renvoie souvent les noms broker)
CRYPTO_REAL  = {"BTCUSD", "ETHUSD", "LTCUSD", "BNBUSD", "ADAUSD", "SOLUSD"}

# FIX 2026-04-30: Symboles autorisés à contourner la blacklist horaire globale
# via leur whitelist locale (allowed_hours_utc). Pour tous les autres symboles,
# la blacklist globale s'applique strictement (union global ∪ local).
BLACKLIST_OVERRIDE_WHITELIST = ["XAUUSD"]

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
    """Lit token/chat_id via load_config() (résout les ${VAR} depuis .env)."""
    try:
        cfg = load_config() or {}
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



# ================================================================
# FIX 2026-03-10: Lock HYBRIDE inter-orchestrateurs + Position Manager pour MT5 COM
# Le COM MT5 est mono-thread : un seul thread peut l'utiliser à la fois
# _MT5Lock supporte:
#   - async with (coroutines asyncio) → attend sans bloquer l'event loop
#   - with (threads BackgroundScheduler) → blocking classique
# Les deux partagent le même threading.Lock() → exclusion mutuelle totale
# Doit être au niveau MODULE (pas classe) pour être accessible partout
# ================================================================
import asyncio as _aio_mod
import threading as _threading_mod


class _MT5Lock:
    """Lock hybride pour MT5 COM — fonctionne en async (coroutines) et sync (threads)."""

    def __init__(self):
        self._lock = _threading_mod.Lock()

    # --- Mode sync (BackgroundScheduler threads: PM, sync_history) ---
    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *args):
        self._lock.release()

    # --- Mode async (coroutines asyncio: _run_agents_and_decide, execute_trade) ---
    async def __aenter__(self):
        loop = _aio_mod.get_event_loop()
        # Attendre le lock dans un thread executor → ne bloque PAS l'event loop
        await loop.run_in_executor(None, self._lock.acquire)
        return self

    async def __aexit__(self, *args):
        self._lock.release()


_GLOBAL_MT5_SEMAPHORE = _MT5Lock()

# FIX 2026-03-24 R16: Compteur streak momentum INVERSE par symbole+direction
_MOMENTUM_STREAK: Dict[str, int] = {}  # clé = "SYMBOL_ACTION", valeur = nb blocages consécutifs
_MOMENTUM_STREAK_THRESHOLD = 3  # Après 3 INVERSE consécutifs, bloquer aussi "net neutre"

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
        # ══════════════════════════════════════════════════════════════════════
        # R19: TAG DE VERSION — Permet de vérifier que le code déployé est le bon
        # ══════════════════════════════════════════════════════════════════════
        logger.warning(
            "═══════════════════════════════════════════════════════════════\n"
            "  ORCHESTRATOR VERSION: R19 — 2026-04-16\n"
            "  Features: ASIA_BLOCK, PROBATION, LIQ_PENALTY, REVERSAL_COOLDOWN,\n"
            "            ADAPTIVE_SCORE, SHORT_PENALTY, XAUUSD_PROBATION, NAS100_BOOST\n"
            "═══════════════════════════════════════════════════════════════"
        )

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

        # FIX 2026-05-19 D13: SL_GUARD spread-aware (retcode 10016) — compteurs
        self._sl_guard_stats: Dict[str, int] = {
            "adjustments": 0,
            "rejections_post_guard": 0,
            "broker_aborts": 0,
        }

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
        self.overrides_all: Dict[str, Any] = {}  # FIX 2026-02-20: stocké pour accès global
        try:
            ov_path = os.path.join("config", "overrides.yaml")
            if os.path.exists(ov_path):
                with open(ov_path, encoding="utf-8") as f:
                    ov_all = yaml.safe_load(f) or {}
                self.overrides_all = ov_all  # FIX 2026-02-20: persisté pour kill switch/EOD
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
        self.agent_weights = weights_cfg  # FIX 2026-02-20: stocké pour _compute_aggregate_direction (étape 3.2)
        self.w_news      = float(weights_cfg.get("news",     0.6))
        self.w_swing     = float(weights_cfg.get("swing",    0.5))
        self.w_scalp     = float(weights_cfg.get("scalping", 0.3))
        self.w_structure = float(weights_cfg.get("structure", 0.6))
        self.w_smc       = float(weights_cfg.get("smc", 0.5))
        self.w_whale     = float(weights_cfg.get("whale", self.whale_cfg.get("weight", 0.4)))

        self.votes_required: int = int(self.ori_cfg.get("votes_required", 2))
        # FIX 2026-02-20: seuils relevés à 2.5 par défaut (étape 3.5)
        self.min_confluence: float = float(self.ori_cfg.get("min_confluence", 2.0))  # FIX 2026-03-08: 2.5→2.0
        self.min_score_for_proposal: float = float(self.ori_cfg.get("min_score_for_proposal", 2.5))

        # ── Hard filters externalisés (2026-03-01) ──
        _orch_cfg = self.cfg.get("orchestrator", {}) or {}
        _hf = _orch_cfg.get("hard_filters") or {}
        self._hf_min_score: float = float(_hf.get("min_score", 2.5))  # FIX 2026-03-06: default 8.0→2.5
        self._hf_min_confluence: float = float(_hf.get("min_confluence", 2.0))  # FIX 2026-03-08: 3→2.0
        self._hf_tracker_contradiction: float = float(_hf.get("tracker_contradiction", 0.25))
        self._hf_disagree_block_pct: float = float(_hf.get("disagree_block_pct", 0.45))
        self._hf_disagree_penalty_pct: float = float(_hf.get("disagree_penalty_pct", 0.35))
        self._hf_min_rr: float = float(_hf.get("min_rr", 0.8))  # FIX 2026-03-08: 1.5→0.8
        self._hf_counter_trend_min_score: float = float(_hf.get("counter_trend_min_score", 6.0))  # FIX R15: 10.0→6.0 (10.0 inatteignable)
        self._hf_quiet_block_confidence: float = float(_hf.get("quiet_block_confidence", 0.7))

        _session_cfg = _orch_cfg.get("session") or {}
        self._hf_blocked_hours: list = list(_session_cfg.get("blocked_hours_utc", [0,1,2,3,4,5]))  # FIX 2026-03-06: default réduit
        self._hf_blocked_hours_extended: list = list(_session_cfg.get("blocked_hours_extended_utc", [0,1,2,3,4,5,22,23]))  # FIX 2026-03-06: forex/indices
        self._hf_crypto_symbols: set = set(_orch_cfg.get("crypto_symbols", ["BTCUSD","ETHUSD","LTCUSD","BNBUSD","ADAUSD","SOLUSD"]))

        _pm_defaults = _orch_cfg.get("position_manager_defaults") or {}
        self._hf_default_be_rr: float = float(_pm_defaults.get("be_rr", 1.0))

        _risk_cfg = self.cfg.get("risk", {}) or {}
        _ks_cfg = _risk_cfg.get("kill_switch") or {}
        self._hf_kill_switch_usd: float = float(_ks_cfg.get("daily_loss_usd", 400.0))

        self._hf_whale_max_vol_z: float = float(self.whale_cfg.get("max_vol_zscore", 3.0))

        logger.info(
            f"[HARD_FILTERS] min_score={self._hf_min_score} min_conf={self._hf_min_confluence} "
            f"tracker_contra={self._hf_tracker_contradiction} disagree={self._hf_disagree_penalty_pct}/{self._hf_disagree_block_pct} "
            f"min_rr={self._hf_min_rr} counter_trend={self._hf_counter_trend_min_score} "
            f"quiet_conf={self._hf_quiet_block_confidence} kill_switch={self._hf_kill_switch_usd}USD "
            f"be_rr={self._hf_default_be_rr} whale_vol_z={self._hf_whale_max_vol_z}"
        )
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
        self.tfs: List[str] = list(mtf.get("tfs", ["H1", "M15", "M5"]))  # FIX 2026-03-06: réduit de 6→3 TFs pour éviter saturation MT5
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

        # Agent error monitoring (audit fev2026) + réactivation auto (2026-03-01)
        self._agent_error_counts: Dict[str, int] = {}
        self._agent_disabled_until: Dict[str, datetime] = {}
        self._agent_cooldown_hours: Dict[str, float] = {}  # Cooldown progressif: 1h, 2h, 4h, 8h max

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
        self.min_rr = float(self.ori_cfg.get("min_rr", 0.8))  # FIX 2026-03-08: 1.5→0.8

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
        self._agent_cache: Dict[str, Any] = {}  # cache instances agents (Part A perf)
        self.tracker = get_tracker_for_symbol(self.symbol)
        self._last_proposal: Optional[Dict[str, Any]] = None
        self._last_ctx: Optional[Dict[str, Any]] = None  # per_tf_signals / global_signals / indicators / market
        self._last_trade_result: Optional[Dict[str, Any]] = None  # R17: Dernier résultat trade (direction, pnl, close_ts)

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
                be_rr = float((pm_cfg.get("break_even") or {}).get("rr", self._hf_default_be_rr))
            except Exception:
                be_rr = self._hf_default_be_rr
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

            # R17: Stocker le résultat du dernier trade pour REVERSAL_COOLDOWN
            try:
                _pnl_close = float(str(payload.get("pnl_ccy", "0")).replace("+", ""))
                _dir_close = payload.get("side") or payload.get("direction") or ""
                self._last_trade_result = {
                    "direction": _dir_close.upper() if _dir_close else "",
                    "pnl": _pnl_close,
                    "close_ts": time.time(),
                }
            except Exception as _ltr_err:
                logger.debug(f"[REVERSAL_COOLDOWN] Erreur stockage résultat: {_ltr_err}")

            # FIX 2026-02-20: Circuit-Breaker record_loss/record_win (étape 2.4)
            try:
                if get_circuit_breaker is not None:
                    _cb = get_circuit_breaker()
                    _pnl_str = str(payload.get("pnl_ccy", "0")).replace("+", "")
                    _pnl_val = float(_pnl_str)
                    if _pnl_val < 0:
                        _cb.record_loss(sym)
                        logger.info(f"[CIRCUIT_BREAKER] {sym}: perte enregistrée (P&L={_pnl_val:+.2f})")
                    elif _pnl_val > 0:
                        _cb.record_win(sym)
            except Exception as _cb_err:
                logger.debug(f"[CIRCUIT_BREAKER] Erreur enregistrement: {_cb_err}")

            # FIX 2026-02-20: Kill Switch — mise à jour P&L réalisé (étape 2.1)
            try:
                if get_global_kill_switch is not None:
                    _pnl_str2 = str(payload.get("pnl_ccy", "0")).replace("+", "")
                    _pnl_val2 = float(_pnl_str2)
                    _ks = get_global_kill_switch()
                    _ks.update_realized_pnl(_pnl_val2)
            except Exception as _ks_err:
                logger.debug(f"[KILL_SWITCH] Erreur update P&L: {_ks_err}")

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
            if self.symbol.upper() not in self._hf_crypto_symbols:
                return False  # Bloquer les non-cryptos le week-end
            # Les cryptos peuvent trader le week-end - continuer les vérifications

        enforce_weekdays = bool(getattr(self, "_weekdays_only", False))
        if not bool(tw.get("enabled", False)):
            if enforce_weekdays and is_weekend:
                # Si weekend_crypto_only est actif et c'est une crypto, on autorise
                if weekend_crypto_only and self.symbol.upper() in self._hf_crypto_symbols:
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
        if self.symbol.upper() in self._hf_crypto_symbols:
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

    # AJOUT 2026-07-30 (P2) : applique les effets d'un refus de garde.
    # Reproduit exactement ce que faisait le code inline : le log, puis le
    # message Telegram, puis la valeur de retour (ou l'exception).
    def _appliquer_refus(self, refus) -> Any:
        if refus.log:
            niveau, message = refus.log
            getattr(logger, niveau, logger.info)(message)
        if refus.telegram:
            texte, kind, force = refus.telegram
            self._send_telegram(texte, kind=kind, force=force)
        if refus.leve:
            raise ValueError(refus.leve)
        return refus.retour

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
    def _send_status_report(self):
        """Rapport court: heure locale, equity/balance, positions ouvertes du symbole, derniers trades."""
        try:
            tz = self._tz
            now_loc = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")

            # Compte
            # FIX 2026-03-10 R6: Protéger l'appel MT5 avec le lock hybride (thread scheduler)
            with _GLOBAL_MT5_SEMAPHORE:
                ai = getattr(self.mt5, "get_account_info", lambda: None)()
            eq = float(getattr(ai, "equity", 0.0) or 0.0) if ai else 0.0
            bal = float(getattr(ai, "balance", 0.0) or 0.0) if ai else 0.0

            # Positions ouvertes pour ce symbole
            poss = []
            try:
                # FIX 2026-03-10 R6: Protéger l'appel MT5 avec le lock hybride
                with _GLOBAL_MT5_SEMAPHORE:
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

            # FIX 2026-05-19 D13: log compteurs SL_GUARD (rythme = status_report_hours)
            try:
                _sg = getattr(self, "_sl_guard_stats", None)
                if _sg:
                    logger.info(
                        f"[SL_GUARD][STATS] {self.symbol}: adjustments={_sg['adjustments']} "
                        f"rejections_post_guard={_sg['rejections_post_guard']} "
                        f"broker_aborts={_sg['broker_aborts']}"
                    )
            except Exception:
                pass

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

        # FIX 2026-07-29 (P5): SHADOW MODE — auto_execute=False ET telegram_validation=False.
        # Le code retombait ici et envoyait des boutons de validation, alors que le shadow
        # mode doit seulement OBSERVER : proposition journalisée dans proposals_log.csv,
        # aucun ordre, aucune notification. Pire, l'écouteur de clics ne démarre que si
        # telegram_validation=True (voir needs_cb) : ces boutons n'étaient reliés à rien.
        # Mesuré le 27/07 : 619 boutons morts envoyés en une seule journée.
        if not getattr(self, "use_telegram_validation", False):
            logger.info(
                f"[SHADOW] {self.symbol} {direction} @ {price} SL={sl} TP={tp} lots={lots} "
                f"score={score_agr:.2f} conf={confluence} — proposition journalisée, "
                f"aucun ordre, aucune notification"
            )
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

    def _get_adaptive_score_boost(self) -> float:
        """R17: Calcule un boost de min_score basé sur le win rate récent du symbole."""
        try:
            adaptive_cfg = (self.cfg.get("orchestrator", {})
                           .get("hard_filters", {})
                           .get("adaptive_score", {}))
            if not adaptive_cfg.get("enabled", False):
                return 0.0

            # Lire les outcomes récents depuis trade_outcomes.csv
            # FIX 2026-07-30 (P5): fichier DU COMPTE courant. Avant, le boost
            # adaptatif — donc le seuil de score effectif — se calculait sur
            # l'historique d'un compte potentiellement ferme.
            from utils.account_scope import chemin_donnees as _chemin_donnees
            outcomes_path = pathlib.Path(_chemin_donnees("trade_outcomes.csv"))
            if not outcomes_path.exists():
                return 0.0

            lookback = int(adaptive_cfg.get("lookback_trades", 15))
            symbol_trades = []
            with open(outcomes_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("symbol", "").upper() == self.symbol.upper():
                        symbol_trades.append(row)

            # Garder les N derniers
            recent = symbol_trades[-lookback:] if len(symbol_trades) >= 5 else []
            if len(recent) < 5:
                return 0.0  # Pas assez de données

            wins = sum(1 for t in recent if float(t.get("pnl", 0)) > 0)
            hr = wins / len(recent)

            hr_hard = float(adaptive_cfg.get("hr_threshold_boost_hard", 0.15))
            hr_medium = float(adaptive_cfg.get("hr_threshold_boost_medium", 0.30))
            boost_hard = float(adaptive_cfg.get("score_boost_hard", 3.0))
            boost_medium = float(adaptive_cfg.get("score_boost_medium", 1.5))

            if hr < hr_hard:
                logger.info(
                    f"[ADAPTIVE_SCORE] {self.symbol}: HR={hr:.0%} ({wins}/{len(recent)}) "
                    f"< {hr_hard:.0%} → boost +{boost_hard}"
                )
                return boost_hard
            elif hr < hr_medium:
                logger.info(
                    f"[ADAPTIVE_SCORE] {self.symbol}: HR={hr:.0%} ({wins}/{len(recent)}) "
                    f"< {hr_medium:.0%} → boost +{boost_medium}"
                )
                return boost_medium
            else:
                logger.debug(
                    f"[ADAPTIVE_SCORE] {self.symbol}: HR={hr:.0%} ({wins}/{len(recent)}) → pas de boost"
                )
                return 0.0
        except Exception as e:
            logger.debug(f"[ADAPTIVE_SCORE] {self.symbol}: erreur — {e}")
            return 0.0

    def execute_trade(self, signal: str):
        symbol = self.symbol  # Utilise le symbole de l'orchestrateur
        # ══════════════════════════════════════════════════════════════════════
        # R19: CHECKPOINT — Confirmer que le code R19 est bien celui qui s'exécute
        # ══════════════════════════════════════════════════════════════════════
        logger.debug(
            f"[R19_CHECKPOINT] {symbol}: execute_trade() appelé — "
            f"code version R19 (2026-04-16)"
        )
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

        # ══════════════════════════════════════════════════════════════════
        # P2 (2026-07-30) — GARDES EXTRAITS.
        # Les 20 gardes qui occupaient ici ~480 lignes vivent maintenant dans
        # orchestrator/trade_guards.py, chacun sous la forme
        #     garde(contexte) -> (autorisé, motif)
        # Ce bloc ne fait plus que : collecter le contexte, appeler la boucle
        # d'évaluation, appliquer les effets. Aucun changement de comportement :
        # l'équivalence est prouvée par tests/test_trade_guards_equivalence.py
        # (80 000 scénarios confrontés au code d'origine extrait verbatim).
        # ══════════════════════════════════════════════════════════════════
        _ctx: Dict[str, Any] = {
            "symbol_self": self.symbol,
            "symbol": self.symbol,
            "profil_actif_maintenant": self._is_symbol_profile_active_now(),
            "dans_trading_window": self._is_in_trading_window(),
        }
        _refus = _tg_evaluer(["fenetre_profil_symbole", "fenetre_trading_window"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)

        # --- PHASE 4: sessions de trading par type d'actif ---
        if self.asset_manager:
            try:
                now = datetime.now(ZoneInfo("Europe/Zurich"))
                allowed, reason = self.asset_manager.is_trading_allowed(self.symbol, now)
                _ctx["session_autorisee"] = allowed
                _ctx["session_motif"] = reason
                _refus = _tg_evaluer(["session_asset_manager"], _ctx)
                if _refus is not None:
                    return self._appliquer_refus(_refus)
                logger.debug(f"[PHASE4] Trading session OK for {self.symbol}: {reason}")
            except Exception as e:
                logger.warning(f"[PHASE4] Session check failed: {e}, continuing anyway")

            # Corrélations : éviter de trader des symboles corrélés simultanément
            try:
                open_positions = []
                positions = _mt5.positions_get() if _mt5 else []
                for pos in positions or []:
                    pos_symbol = broker_to_canon(str(getattr(pos, "symbol", "")))
                    if pos_symbol:
                        open_positions.append(pos_symbol)

                _ctx["positions_ouvertes"] = open_positions
                _ctx["conflit_correlation"] = (
                    self.asset_manager.check_correlation_conflict(self.symbol, open_positions)
                    if open_positions else False
                )
                _refus = _tg_evaluer(["conflit_correlation"], _ctx)
                if _refus is not None:
                    return self._appliquer_refus(_refus)
            except Exception as e:
                logger.warning(f"[PHASE4] Correlation check failed: {e}, continuing anyway")
        # --- FIN PHASE 4 ---

        # FIX 2026-03-23 R15: cooldown anti-QUICK_REVERSAL
        if get_qr_cooldown is not None:
            import time as _time_mod
            _ctx["qr_cooldown_until"] = get_qr_cooldown(symbol)
            _ctx["now_ts"] = _time_mod.time()
            _refus = _tg_evaluer(["cooldown_quick_reversal"], _ctx)
            if _refus is not None:
                return self._appliquer_refus(_refus)

        sig = (signal or "").upper().strip()
        _ctx["sig"] = sig

        # FIX 2026-04-10 R18: REVERSAL COOLDOWN — anti-whipsaw
        logger.info(
            f"[REV_COOLDOWN_ZONE] {symbol}: entrée dans la zone REVERSAL_COOLDOWN — "
            f"last_trade_result={'SET' if getattr(self, '_last_trade_result', None) is not None else 'None'}"
        )
        try:
            _ctx["reversal_cooldown_min"] = int(
                (self.cfg.get("orchestrator", {}).get("cooldown", {})
                 .get("reversal_cooldown_min", 60))
            )
            _ctx["last_trade_result"] = self._last_trade_result
            _ctx["now_ts"] = time.time()
            _refus = _tg_evaluer(["reversal_cooldown"], _ctx)
            if _refus is not None:
                return self._appliquer_refus(_refus)
            _ltr = self._last_trade_result
            if _ltr is None:
                logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: aucun trade précédent enregistré → PASS")
            elif _ltr.get("direction", "") == sig:
                logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: même direction {sig} → pas de reversal → PASS")
            elif float(_ltr.get("pnl", 0)) >= 0:
                logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: dernier trade {_ltr.get('direction','')} était gagnant → PASS")
            else:
                logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: cooldown expiré → PASS")
        except Exception as _rev_err:
            logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: erreur — {_rev_err}")

        _refus = _tg_evaluer(["signal_invalide"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)

        _ctx["proposal"] = self._last_proposal
        _refus = _tg_evaluer(["proposal_absente"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)

        # FIX 2026-03-24 R16: anti-spam si position déjà ouverte sur le symbole
        try:
            if _mt5 is not None:
                _existing_pos = _mt5.positions_get(symbol=self.broker_symbol)
                _ctx["nb_positions_symbole"] = len(_existing_pos) if _existing_pos else 0
                _refus = _tg_evaluer(["anti_spam_position_ouverte"], _ctx)
                if _refus is not None:
                    return self._appliquer_refus(_refus)
        except Exception as _asp_err:
            logger.debug(f"[ANTI_SPAM] {self.symbol}: check échoué ({_asp_err}) — PASS")

        # --- TTL ---
        try:
            exp = self._last_proposal.get("expires_at")
            _ctx["ttl_expiree"] = bool(
                exp and datetime.now(timezone.utc) > datetime.fromisoformat(exp)
            )
            if _ctx["ttl_expiree"]:
                # Effet propre au garde TTL : trace CSV de l'expiration.
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
                _refus = _tg_evaluer(["proposal_ttl_expiree"], _ctx)
                if _refus is not None:
                    return self._appliquer_refus(_refus)
        except Exception:
            pass

        p = self._last_proposal
        self._last_proposal = None  # FIX R16: Consommer la proposal (empêche re-exécution)
        symbol = p["symbol"]          # canonique
        broker_symbol = canon_to_broker(symbol) or self.broker_symbol
        entry = float(p.get("entry", 0.0))
        lots = float(p["lots"])
        sl = float(p["sl"])
        tp = float(p["tp"])
        action = "BUY" if sig == "LONG" else "SELL"
        _ctx["symbol"] = symbol

        # ── HOUR FILTER ────────────────────────────────────────────────────
        current_hour_utc = datetime.now(timezone.utc).hour
        orch_cfg = (self.profile.get("orchestrator") or {})
        local_blocked = list(orch_cfg.get("blocked_hours_utc", []) or [])
        allowed_hours = orch_cfg.get("allowed_hours_utc", None)
        _global_blocked: list = []
        try:
            from utils.config import get_overrides as _get_overrides
            _ov = _get_overrides() or {}
            _global_blocked = list(
                ((_ov.get("GLOBAL") or {}).get("orchestrator") or {}).get("blocked_hours_utc", []) or []
            )
        except Exception:
            _global_blocked = []

        blocked_hours, _bypass_now = _tg_blocked_hours(
            symbol, local_blocked, _global_blocked, allowed_hours,
            BLACKLIST_OVERRIDE_WHITELIST, current_hour_utc)
        if _bypass_now:
            logger.info(
                f"[HOUR_FILTER][EXCEPTION] {symbol} autorisé sur h{current_hour_utc} "
                f"via allowed_hours_utc local malgré blacklist globale"
            )

        hour_filter_mode = "WHITELIST" if allowed_hours else "BLACKLIST" if blocked_hours else None

        _ctx.update({
            "current_hour_utc": current_hour_utc,
            "blocked_hours": blocked_hours,
            "allowed_hours": allowed_hours,
        })
        _refus = _tg_evaluer(["hour_filter_blacklist", "hour_filter_whitelist"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)

        if hour_filter_mode:
            logger.info(
                f"[HOUR_FILTER][{hour_filter_mode}] {symbol}: heure {current_hour_utc}h UTC autorisée "
                f"(blocked={blocked_hours}, allowed={allowed_hours})"
            )

        # ── ASIA BLOCK (FIX 2026-04-10 R18) ────────────────────────────────
        _est_crypto = symbol.upper() in self._hf_crypto_symbols
        _ctx["est_crypto"] = _est_crypto
        try:
            _asia_cfg = (self.cfg.get("orchestrator", {})
                        .get("hard_filters", {})
                        .get("asia_block", {}))
            _ctx["asia_enabled"] = bool(_asia_cfg.get("enabled", False))
            _ctx["asia_hours"] = _asia_cfg.get("hours_utc", [0, 1, 2, 3, 4, 5, 6, 7])
            _ctx["asia_exempt"] = _asia_cfg.get("exempt_crypto", True)
            _refus = _tg_evaluer(["asia_block"], _ctx)
            if _refus is not None:
                return self._appliquer_refus(_refus)
            if (_ctx["asia_enabled"] and current_hour_utc in _ctx["asia_hours"]
                    and _ctx["asia_exempt"] and _est_crypto):
                logger.debug(
                    f"[ASIA_BLOCK] {symbol}: crypto exemptée — heure {current_hour_utc}h UTC PASS"
                )
        except Exception as _asia_err:
            logger.debug(f"[ASIA_BLOCK] {symbol}: erreur — {_asia_err}")

        _is_probation = bool(self.ori_cfg.get("probation", False))
        if _is_probation:
            logger.info(
                f"[PROBATION] {symbol}: symbole en MODE PROBATION — "
                f"restrictions max (1 trade/jour, risk 0.1%, score 7.0+, 4 votes)"
            )

        # ── HARD FILTERS ───────────────────────────────────────────────────
        score_agr = float(p.get("score", 0.0) or 0.0)
        confluence = int(p.get("confluence", 0) or 0)
        tracker_vote = float(p.get("tracker_vote", 0.0) or 0.0)

        _adaptive_boost = self._get_adaptive_score_boost()

        logger.info(
            f"[LIQ_PENALTY_ZONE] {symbol}: entrée dans la zone LIQ_PENALTY — "
            f"hour={current_hour_utc}, crypto={_est_crypto}"
        )
        _hf_cfg_r17 = self.cfg.get("orchestrator", {}).get("hard_filters", {})
        _liq_hours = _hf_cfg_r17.get("low_liquidity_hours_utc", [0, 1, 2, 3, 4, 5, 6, 7, 22, 23])
        _liq_penalty = _tg_liq_penalty(
            _est_crypto, current_hour_utc, _liq_hours,
            float(_hf_cfg_r17.get("low_liquidity_score_penalty", 2.0)))
        if _liq_penalty > 0:
            logger.info(
                f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
                f"penalty +{_liq_penalty} sur min_score"
            )
        else:
            logger.debug(
                f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
                f"pas de penalty (crypto={_est_crypto}, in_liq_hours={current_hour_utc in _liq_hours})"
            )

        HARD_MIN_SCORE = self._hf_min_score + _adaptive_boost + _liq_penalty
        if _adaptive_boost > 0 or _liq_penalty > 0:
            logger.info(f"[ADAPTIVE_SCORE] {symbol}: min_score ajusté {self._hf_min_score} + adaptive={_adaptive_boost} + liq={_liq_penalty} = {HARD_MIN_SCORE}")
        HARD_MIN_CONFLUENCE = self._hf_min_confluence

        _ctx.update({
            "score_agr": score_agr,
            "confluence": confluence,
            "tracker_vote": tracker_vote,
            "hard_min_score": HARD_MIN_SCORE,
            "hard_min_confluence": HARD_MIN_CONFLUENCE,
            "tracker_contradiction_seuil": self._hf_tracker_contradiction,
        })
        _refus = _tg_evaluer(
            ["hard_min_score", "hard_min_confluence", "tracker_contradiction"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)

        logger.info(f"[HARD_FILTER] {symbol}: PASS score={score_agr:.1f} conf={confluence} tracker={tracker_vote:+.2f}")

        # ── SHORT PENALTY (FIX 2026-04-03 R17) ─────────────────────────────
        _short_penalty = float(
            (self.cfg.get("orchestrator", {}).get("hard_filters", {})
             .get("short_score_penalty", 1.5))
        )
        _ctx["short_penalty"] = _short_penalty
        _refus = _tg_evaluer(["short_penalty"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)
        if sig == "SHORT" and _short_penalty > 0:
            logger.info(f"[SHORT_PENALTY] {symbol}: score {score_agr:.1f} >= {HARD_MIN_SCORE + _short_penalty:.1f} → SHORT autorisé")

        # ── FILTRE DIRECTIONNEL (FIX 2026-02-24) ───────────────────────────
        _ctx["allowed_directions"] = self.ori_cfg.get("allowed_directions")
        _refus = _tg_evaluer(["direction_filter"], _ctx)
        if _refus is not None:
            return self._appliquer_refus(_refus)

        # ── DAILY LOSS LIMIT ───────────────────────────────────────────────
        try:
            risk_cfg = self.cfg.get("risk", {})
            _ctx["daily_limit"] = float(risk_cfg.get("daily_loss_limit_pct", 0.02))
            _ctx["daily_loss_evaluable"] = False
            if _mt5 and hasattr(_mt5, 'account_info'):
                account_info = _mt5.account_info()
                if account_info:
                    # equity/balance lus comme dans le code d'origine : si
                    # l'objet compte est incomplet, l'exception est avalee et
                    # le garde saute, exactement comme avant.
                    equity = float(account_info.equity)
                    balance = float(account_info.balance)
                    _ctx["daily_loss_evaluable"] = True
                    _ctx["daily_pnl_pct"] = _tg_daily_pnl_pct(
                        float(account_info.profit), balance)
            _refus = _tg_evaluer(["daily_loss_limit"], _ctx)
            if _refus is not None:
                return self._appliquer_refus(_refus)
        except Exception as e:
            logger.debug(f"[DAILY_LOSS] Erreur calcul: {e}")

        # ── SESSION FILTER (heures toxiques) ───────────────────────────────
        try:
            vol_cfg = self.cfg.get("volatility_filter", {})
            _ctx["session_filter_actif"] = bool(vol_cfg.get("avoid_low_liquidity", True))
            if _ctx["session_filter_actif"]:
                current_hour_utc = datetime.now(timezone.utc).hour
                _ctx["current_hour_utc"] = current_hour_utc
                is_crypto = symbol.upper() in self._hf_crypto_symbols
                asset_override = vol_cfg.get("asset_overrides", {}).get("crypto", {})
                _ctx["crypto_exempt"] = _tg_crypto_exempt(is_crypto, asset_override)
                _ctx["session_blocked_hours"] = vol_cfg.get(
                    "low_liquidity_hours_utc",
                    self._hf_blocked_hours if is_crypto else self._hf_blocked_hours_extended)
            _refus = _tg_evaluer(["session_filter"], _ctx)
            if _refus is not None:
                return self._appliquer_refus(_refus)
        except Exception as e:
            logger.debug(f"[SESSION_FILTER] Erreur: {e}")
        # ══════════════════════════════════════════════════════════════════════

        # ══════════════════════════════════════════════════════════════════════
        # (2026-01-06) HARD FILTER 5: MTF CONFLUENCE - Blocage contre-tendance D1/H4
        # Utilise analyze_mtf_confluence pour vérifier l'alignement des TF supérieurs
        # ══════════════════════════════════════════════════════════════════════
        if False:  # FIX 2026-03-08: MTF filter désactivé — signature incompatible crash orchestrators
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
        # --------- Variables communes dry-run / live ----------
        volume = lots
        side = sig
        score = score_agr

        # TP1/TP2 via RR partials du profile
        tp1 = None
        tp2 = None
        try:
            pm_cfg = ((self.profile.get("orchestrator") or {}).get("position_manager") or {})
            pm_partials = pm_cfg.get("partials") or []
            rr_partials = [float(x.get("rr")) for x in pm_partials if x.get("rr") is not None][:2]
            risk_px = abs(entry - sl) if entry and sl else 0.0
            if risk_px > 0:
                def _rr_to_tp(rr_val):
                    return entry + rr_val * risk_px if side == "LONG" else entry - rr_val * risk_px
                tp1 = _rr_to_tp(rr_partials[0]) if len(rr_partials) >= 1 else tp
                tp2 = _rr_to_tp(rr_partials[1]) if len(rr_partials) >= 2 else tp
            else:
                tp1 = tp
                tp2 = tp
        except Exception:
            tp1 = tp
            tp2 = tp

        # Confluence breakdown & decision notes depuis le contexte
        ctx = self._last_ctx or {}
        confluence_breakdown = ctx.get("confluence_breakdown", {})
        decision_notes = ctx.get("decision_notes", "")
        confluences_list = []
        if isinstance(confluence_breakdown, dict):
            confluences_list = [k for k, v in confluence_breakdown.items() if v]
        elif isinstance(confluence_breakdown, (list, tuple)):
            confluences_list = [str(c) for c in confluence_breakdown]
        # ------------------------------------------------------------------

        # --------- DRY RUN : pas d'envoi MT5, juste notification + audit ----------
        if getattr(self, "dry_run", False):
            logger.info(f"[DRY_RUN] Signal {side} {symbol} score={score} lots={volume}")
            tp1_str = f"{tp1:.2f}" if tp1 is not None else "N/A"
            tp2_str = f"{tp2:.2f}" if tp2 is not None else "N/A"
            msg = (f"#NEW_TRADE_SIM | {symbol} | {side} | entry={entry} | vol={volume} | "
                   f"SL={sl} | TP1={tp1_str} | TP2={tp2_str} | score={score} | "
                   f"confluences={','.join(confluences_list)[:120]}")
            self._send_telegram(msg, kind="status", force=True)
            audit_append("NEW_TRADE_SIM", {
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "volume": volume,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "score": score,
                "confluence_breakdown": confluence_breakdown,
                "decision_notes": decision_notes,
                "meta": {"dry_run": True}
            })
            self._record_performance_stats(self._last_proposal, executed=False, outcome=None, retcode=None)
            return True
        # --------------------------------------------------------------------------

        # ══════════════════════════════════════════════════════════════════════
        # (2026-02-04) CRITICAL FIX: Enforce max_volume per-trade limit
        # AVANT l'envoi de l'ordre, plafonner le volume à la limite configurée
        # FIX 2026-02-24: Lire d'abord depuis overrides (ori_cfg), fallback profile (Directive 8)
        # ══════════════════════════════════════════════════════════════════════
        _ov_pl = (self.ori_cfg.get("position_limits") or {})
        _pf_pl = (self.profile.get("orchestrator") or {}).get("position_limits") or {}
        _ov_max = float(_ov_pl.get("max_volume", 0.0) or 0.0)
        _pf_max = float(_pf_pl.get("max_volume", 0.0) or 0.0)
        # FIX 2026-02-24: Prendre la valeur la plus restrictive si les deux existent
        if _ov_max > 0 and _pf_max > 0:
            max_volume_limit = min(_ov_max, _pf_max)
        else:
            max_volume_limit = _ov_max or _pf_max
        _mv_source = "override" if _ov_max > 0 else "profile"
        logger.info(f"[MAX_VOLUME] {symbol}: limit={max_volume_limit:.2f} (source={_mv_source}, ov={_ov_max}, pf={_pf_max})")

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

        # FIX 2026-03-15 R12: Garde-fou R:R — BLOQUE le trade si RR aberrant
        _rr_trade_blocked = False
        try:
            _final_rr_min = max(0.50, float(getattr(self, '_hf_min_rr', 0.80)))
            if action == "BUY":
                _f_risk = abs(entry - sl) if (entry and sl and entry > sl) else 0
                _f_reward = abs(tp - entry) if (entry and tp and tp > entry) else 0
            else:
                _f_risk = abs(sl - entry) if (entry and sl and sl > entry) else 0
                _f_reward = abs(entry - tp) if (entry and tp and entry > tp) else 0

            _f_rr = _f_reward / max(_f_risk, 1e-9) if _f_risk > 0 else 0

            if _f_risk > 0 and _f_rr < _final_rr_min:
                # Tenter de corriger le TP
                _f_new_tp_dist = _f_risk * self._hf_min_rr
                if action == "BUY":
                    tp = entry + _f_new_tp_dist
                else:
                    tp = entry - _f_new_tp_dist
                _f_new_rr = _f_new_tp_dist / max(_f_risk, 1e-9)
                logger.warning(
                    f"[RR_SAFETY] {symbol}: R:R {_f_rr:.3f} < {_final_rr_min} → "
                    f"TP corrigé {tp:.5f} (R:R={_f_new_rr:.2f})"
                )

            # Vérifier que le RR est maintenant acceptable
            if _f_risk > 0:
                if action == "BUY":
                    _f_reward_final = abs(tp - entry) if tp > entry else 0
                else:
                    _f_reward_final = abs(entry - tp) if entry > tp else 0
                _f_rr_final = _f_reward_final / max(_f_risk, 1e-9)
                if _f_rr_final < 0.30:
                    # RR toujours aberrant après correction → BLOQUER
                    _rr_trade_blocked = True
                    logger.error(
                        f"[RR_SAFETY] {symbol}: R:R TOUJOURS ABERRANT {_f_rr_final:.3f} "
                        f"après correction — TRADE BLOQUÉ "
                        f"(entry={entry}, sl={sl}, tp={tp})"
                    )
            elif entry and sl:
                # Risk = 0 signifie SL = entry → trade sans risque ou bug
                logger.warning(
                    f"[RR_SAFETY] {symbol}: risk=0 (entry={entry}, sl={sl}) — suspect"
                )

        except Exception as _rr_safety_err:
            logger.warning(f"[RR_SAFETY] {symbol}: Erreur guard — {_rr_safety_err}")

        if _rr_trade_blocked:
            logger.error(f"[RR_SAFETY] {symbol}: Trade REJETÉ (RR aberrant)")
            return None

        # FIX 2026-03-13 R9: Garde-fou risque absolu par trade
        try:
            _max_risk_usd = float((self.cfg.get("risk") or {}).get("max_risk_per_trade_usd", 300.0))
            if sl and entry and lots:
                _sl_dist = abs(entry - sl)
                _point_val = 1.0
                _sym_info = None
                try:
                    if _mt5:
                        _sym_info = _mt5.symbol_info(broker_symbol)
                        if _sym_info:
                            _ts = getattr(_sym_info, "trade_tick_size", 0)
                            _tv = getattr(_sym_info, "trade_tick_value", 0)
                            if _ts > 0 and _tv > 0:
                                _point_val = _tv / _ts
                            # FIX 2026-03-18 R14: Fallback si tick_size/tick_value sont 0
                            if _point_val == 1.0:
                                _cs = getattr(_sym_info, "trade_contract_size", 0)
                                _pt = getattr(_sym_info, "point", 0)
                                if _cs > 0 and _pt > 0:
                                    _point_val = _cs * _pt
                                    logger.info(
                                        f"[RISK_CAP] {symbol}: point_val fallback via "
                                        f"contract_size={_cs} × point={_pt} = {_point_val}"
                                    )
                except Exception as _pv_err:
                    logger.warning(f"[RISK_CAP] symbol_info({broker_symbol}) échoué: {_pv_err}")

                # FIX 2026-03-23 R15: Override point_val pour indices CFD libellés en USD.
                # contract_size × point donne 0.01 pour SP500/NAS100 mais le risque réel
                # est ~$1/pt/lot (vérifié empiriquement).
                # FIX 2026-04-30: retrait UK100/GER40 du dict point_value override.
                # Ces indices ont currency_profit GBP/EUR; l'override 1.0 sous-estimait
                # le risque (~36% UK100, ~17% GER40 selon mt5.symbol_info live).
                # Ils utilisent désormais la voie native MT5 (trade_tick_value/trade_tick_size).
                # L'override n'est conservé que pour les indices avec currency_profit == USD.
                _indices_point_val = {
                    "SP500": 1.0, "SP500#1": 1.0,
                    "NAS100": 1.0, "NAS100#1": 1.0,
                    "DJ30": 1.0, "DJ30#1": 1.0,
                }
                _sym_upper = symbol.upper()
                if _sym_upper in _indices_point_val:
                    _old_pv = _point_val
                    _point_val = _indices_point_val[_sym_upper]
                    logger.info(
                        f"[RISK_CAP] {symbol}: mode=override_indices_USD point_val={_point_val} "
                        f"(était {_old_pv})"
                    )
                else:
                    logger.info(
                        f"[RISK_CAP] {symbol}: mode=MT5_native_tick_conversion point_val={_point_val:.4f}"
                    )

                # FIX 2026-03-18 R13: Alerte si point_value reste au défaut
                # FIX R16: Exclure les indices avec override (1.0 est correct pour eux)
                if _point_val == 1.0 and symbol.upper() not in _indices_point_val:
                    logger.warning(
                        f"[RISK_CAP] {symbol}: _point_val=1.0 (défaut) — "
                        f"risque possiblement sous-estimé. "
                        f"sym_info={'OK' if _sym_info else 'None'}"
                    )
                    # Fallback conservateur pour les cryptos : bloquer si lots > 1.0
                    if symbol.endswith("USD") and lots > 1.0:
                        _risk_usd = _max_risk_usd + 1  # Forcer le cap
                        logger.warning(
                            f"[RISK_CAP] {symbol}: point_val inconnu + {lots:.2f} lots "
                            f"→ forçage cap à {_max_risk_usd}$"
                        )
                _risk_usd = _sl_dist * lots * _point_val
                if _risk_usd > _max_risk_usd:
                    _old_lots = lots
                    lots = (_max_risk_usd / (_sl_dist * _point_val))
                    try:
                        _vol_step = getattr(_sym_info, "volume_step", 0.01) if _sym_info else 0.01
                        lots = max(_vol_step, round(lots / _vol_step) * _vol_step)
                    except Exception:
                        lots = max(0.01, round(lots, 2))
                    logger.warning(
                        f"[RISK_CAP] {symbol}: risque ${_risk_usd:.0f} > max ${_max_risk_usd:.0f} "
                        f"→ lots réduits {_old_lots:.4f} → {lots:.4f}"
                    )
        except Exception as _risk_cap_err:
            logger.debug(f"[RISK_CAP] Erreur: {_risk_cap_err}")

        # AJOUT 2026-08-02 : trace du risque REELLEMENT engage, juste avant
        # l'envoi. Constate sur le trade BTCUSD du 01/08 : 1 R valait 486,63 USD
        # alors que le profil demande 0,5 % d'une equite d'environ 49 000 USD,
        # soit ~245 USD — le double. Les profils des 6 symboles declarent tous
        # risk_per_trade = 0.005, et RiskManager renvoie le meme budget pour
        # tous : l'ecart nait donc APRES le calcul de risque, quelque part
        # entre la proposition et l'envoi. Cette trace rend l'ecart mesurable
        # a chaque ordre au lieu de devoir le reconstituer a posteriori.
        # Elle ne modifie AUCUNE decision.
        try:
            _pv = float((self.profile.get("instrument") or {}).get(
                "pip_value", 0) or 0) or (
                float((self.profile.get("instrument") or {}).get("contract_size", 1) or 1)
                * float((self.profile.get("instrument") or {}).get("point", 0.01) or 0.01))
            _dist_pts = abs(float(entry) - float(sl)) / max(
                float((self.profile.get("instrument") or {}).get("point", 0.01) or 0.01), 1e-9)
            _risque_reel = _dist_pts * _pv * float(lots)
            _eq = None
            try:
                _ai = _mt5.account_info() if _mt5 else None
                _eq = float(_ai.equity) if _ai else None
            except Exception:
                _eq = None
            _pct_vise = float((self.profile.get("risk") or {}).get("risk_per_trade", 0.0) or 0.0)
            _budget = (_eq * _pct_vise) if (_eq and _pct_vise) else None
            _ecart = (_risque_reel / _budget) if _budget else None
            logger.warning(
                "[RISK_TRACE] %s %s: lots=%s dist=%.1f pts pip_value=%.5f "
                "-> risque_engage=%.2f USD | budget=%s (%.3f%% de %s) | ratio=%s",
                symbol, action, lots, _dist_pts, _pv, _risque_reel,
                ("%.2f USD" % _budget) if _budget else "inconnu",
                _pct_vise * 100, ("%.0f USD" % _eq) if _eq else "equite inconnue",
                ("%.2fx" % _ecart) if _ecart else "n/a")
            if _ecart and (_ecart > 1.25 or _ecart < 0.75):
                logger.error(
                    "[RISK_TRACE] %s: le risque engage vaut %.2fx le budget vise. "
                    "Dimensionnement incoherent avec le profil.", symbol, _ecart)
        except Exception as _rt_err:
            logger.debug("[RISK_TRACE] %s: trace indisponible (%s)", symbol, _rt_err)

        # FIX 2026-03-18 R13: Diagnostic TP avant order_send
        logger.warning(
            f"[TP_TRACE] {symbol} {action}: entry={entry}, sl={sl}, tp={tp}, lots={lots}, "
            f"proposal_tp={float(p.get('tp', 0))}, "
            f"rr_final={abs(tp - entry) / max(abs(entry - sl), 1e-9):.3f}"
        )

        # ═══════════════════════════════════════════════════════════════
        # FIX 2026-03-20 R15: Filtre Momentum Pré-Exécution
        # Vérifie que le prix se déplace dans la direction du signal
        # sur les dernières 3 bougies M5. Bloque si momentum inverse.
        # ═══════════════════════════════════════════════════════════════
        try:
            _momentum_ok = True
            # R17: Paramètres momentum asymétriques (SHORT plus strict)
            _hf_cfg = self.cfg.get("orchestrator", {}).get("hard_filters", {})
            if action == "SELL":
                _momentum_bars = int(_hf_cfg.get("short_momentum_bars", 5))
                _momentum_threshold = float(_hf_cfg.get("short_momentum_threshold", 0.7))
            else:
                _momentum_bars = 3
                _momentum_threshold = 0.6

            if hasattr(self.mt5, "get_rates"):
                _m5_rates = self.mt5.get_rates(broker_symbol, "M5", count=_momentum_bars + 1)
            else:
                _m5_rates = None

            if _m5_rates and len(_m5_rates) >= _momentum_bars + 1:
                _closes = [float(r["close"]) for r in _m5_rates]
                _confirms = 0

                for i in range(1, len(_closes)):
                    if action == "BUY" and _closes[i] > _closes[i - 1]:
                        _confirms += 1
                    elif action == "SELL" and _closes[i] < _closes[i - 1]:
                        _confirms += 1

                _confirm_ratio = _confirms / _momentum_bars if _momentum_bars > 0 else 0

                if _confirm_ratio < _momentum_threshold:
                    # Vérifier aussi la direction globale (close[-1] vs close[0])
                    _net_move = _closes[-1] - _closes[0]
                    _against = (action == "BUY" and _net_move < 0) or \
                               (action == "SELL" and _net_move > 0)

                    if _against:
                        _streak_key = f"{symbol}_{action}"
                        _MOMENTUM_STREAK[_streak_key] = _MOMENTUM_STREAK.get(_streak_key, 0) + 1
                        logger.warning(
                            f"[MOMENTUM_CHECK] {symbol} {action}: momentum INVERSE "
                            f"({_confirm_ratio*100:.0f}% confirm, net={_net_move:.5f}). "
                            f"Trade BLOQUÉ — streak={_MOMENTUM_STREAK[_streak_key]}"
                        )
                        _momentum_ok = False
                    else:
                        # FIX R16: Vérifier le streak avant de PASS
                        _streak_key = f"{symbol}_{action}"
                        _streak_count = _MOMENTUM_STREAK.get(_streak_key, 0)
                        if _streak_count >= _MOMENTUM_STREAK_THRESHOLD:
                            logger.warning(
                                f"[MOMENTUM_CHECK] {symbol} {action}: momentum faible "
                                f"({_confirm_ratio*100:.0f}% confirm) — BLOQUÉ car "
                                f"streak={_streak_count} INVERSE consécutifs"
                            )
                            _momentum_ok = False
                        else:
                            logger.info(
                                f"[MOMENTUM_CHECK] {symbol} {action}: momentum faible "
                                f"({_confirm_ratio*100:.0f}% confirm) mais net neutre — PASS"
                            )
                else:
                    _streak_key = f"{symbol}_{action}"
                    _MOMENTUM_STREAK[_streak_key] = 0  # Reset streak
                    logger.debug(
                        f"[MOMENTUM_CHECK] {symbol} {action}: momentum OK "
                        f"({_confirm_ratio*100:.0f}% confirm)"
                    )
            else:
                logger.debug(f"[MOMENTUM_CHECK] {symbol}: données M5 indisponibles — PASS")

            if not _momentum_ok:
                return None

        except Exception as _mom_err:
            logger.debug(f"[MOMENTUM_CHECK] {symbol}: Erreur — {_mom_err}")
            # En cas d'erreur, laisser passer (fail-open)

        # ═══════════════════════════════════════════════════════════════
        # FIX 2026-03-18 R14: Recalcul SL/TP sur prix actuel
        # Les agents calculent SL/TP sur le prix au moment de l'analyse.
        # Entre l'analyse et l'exécution, le marché bouge.
        # On préserve les DISTANCES (risk/reward) mais on les applique
        # au prix ACTUEL pour maintenir le R:R correct.
        # ═══════════════════════════════════════════════════════════════
        try:
            _current_price = None
            try:
                if _mt5:
                    _tick = _mt5.symbol_info_tick(broker_symbol)
                    if _tick:
                        _current_price = float(_tick.ask if action == "BUY" else _tick.bid)
            except Exception:
                pass

            if _current_price and _current_price > 0 and entry and entry > 0:
                _sl_dist = abs(entry - sl) if sl else 0
                _tp_dist = abs(tp - entry) if tp else 0
                _price_drift = abs(_current_price - entry)

                # Seuil : ne recalculer que si le drift est significatif
                # (> 10% de la distance SL, sinon pas la peine)
                _drift_threshold = _sl_dist * 0.10 if _sl_dist > 0 else 0

                if _price_drift > _drift_threshold and _sl_dist > 0 and _tp_dist > 0:
                    _old_entry = entry
                    _old_sl = sl
                    _old_tp = tp

                    entry = _current_price
                    if action == "BUY":
                        sl = _current_price - _sl_dist
                        tp = _current_price + _tp_dist
                    else:  # SELL
                        sl = _current_price + _sl_dist
                        tp = _current_price - _tp_dist

                    logger.warning(
                        f"[ENTRY_REFRESH] {symbol} {action}: prix drifté de "
                        f"{_price_drift:.2f} pts ({_price_drift/_sl_dist*100:.0f}% du SL). "
                        f"Entry {_old_entry:.5f}→{entry:.5f} | "
                        f"SL {_old_sl:.5f}→{sl:.5f} | "
                        f"TP {_old_tp:.5f}→{tp:.5f} | "
                        f"R:R préservé {_tp_dist/_sl_dist:.2f}"
                    )
                elif _price_drift > 0:
                    logger.debug(
                        f"[ENTRY_REFRESH] {symbol}: drift {_price_drift:.2f} < seuil "
                        f"{_drift_threshold:.2f} — pas de recalcul"
                    )
        except Exception as _refresh_err:
            logger.warning(f"[ENTRY_REFRESH] {symbol}: Erreur — {_refresh_err}")

        # ═══════════════════════════════════════════════════════════════
        # FIX 2026-05-19 D13: SL_GUARD spread-aware (retcode 10016)
        # Élargit le SL pour qu'il "clear" le bid (LONG) ou l'ask (SHORT)
        # avec une marge min_dist = max(stops_level, spread) × 1.5.
        # Ne modifie PAS le TP — laisse le hard_filter min_rr rejeter si R:R
        # devient sub-unitaire après ajustement.
        # Fail-closed sur broker invalide (cancel trade, jamais d'estimation).
        # ═══════════════════════════════════════════════════════════════
        def _sl_guard_validate_broker(_sym: str):
            """Renvoie (symbol_info, tick, reason). reason='ok' ssi tout est exploitable."""
            if _mt5 is None:
                return None, None, "mt5_unavailable"
            _si = _mt5.symbol_info(_sym)
            if _si is None:
                return None, None, "symbol_info_unavailable"
            _tick = _mt5.symbol_info_tick(_sym)
            if _tick is None:
                return None, None, "tick_unavailable"
            _b = float(getattr(_tick, "bid", 0.0) or 0.0)
            _a = float(getattr(_tick, "ask", 0.0) or 0.0)
            if _b <= 0.0 or _a <= 0.0:
                return None, None, "bid_or_ask_invalid"
            if _a < _b:
                return None, None, "crossed_market"
            return _si, _tick, "ok"

        _si_g, _tick_g, _reason_g = _sl_guard_validate_broker(broker_symbol)
        if _reason_g != "ok":
            self._sl_guard_stats["broker_aborts"] += 1
            logger.error(
                f"[SL_GUARD][ABORT] {symbol} {action}: trade annulé — "
                f"reason={_reason_g} ts={datetime.now(timezone.utc).isoformat()}"
            )
            return None

        _spread_value = float(_tick_g.ask) - float(_tick_g.bid)
        # stops_level négatif théorique → ramené à 0 pour éviter min_dist négatif
        _stops_pts = int(getattr(_si_g, "trade_stops_level", 0) or 0)
        _point_val = float(getattr(_si_g, "point", 0.0) or 0.0)
        if _stops_pts < 0:
            logger.warning(
                "[SL_GUARD][BROKER_ANOMALY] %s trade_stops_level négatif (%d), normalisé à 0",
                symbol, _stops_pts,
            )
        _stops_level_value = max(0.0, _stops_pts * _point_val)
        _min_dist = max(_stops_level_value, _spread_value) * 1.5

        _sl_was_adjusted = False
        _old_sl = sl
        if _min_dist > 0.0 and sl is not None and entry is not None:
            if action == "BUY":
                _target_sl_max = float(_tick_g.bid) - _min_dist
                if sl > _target_sl_max:
                    sl = _target_sl_max
                    _sl_was_adjusted = True
                    self._sl_guard_stats["adjustments"] += 1
                    logger.info(
                        f"[SL_GUARD][ADJUST] {symbol} BUY: sl {_old_sl:.5f}→{sl:.5f} "
                        f"(bid={float(_tick_g.bid):.5f}, spread={_spread_value:.5f}, "
                        f"stops_lvl={_stops_level_value:.5f}, min_dist={_min_dist:.5f})"
                    )
            else:  # SELL / SHORT
                _target_sl_min = float(_tick_g.ask) + _min_dist
                if sl < _target_sl_min:
                    sl = _target_sl_min
                    _sl_was_adjusted = True
                    self._sl_guard_stats["adjustments"] += 1
                    logger.info(
                        f"[SL_GUARD][ADJUST] {symbol} SELL: sl {_old_sl:.5f}→{sl:.5f} "
                        f"(ask={float(_tick_g.ask):.5f}, spread={_spread_value:.5f}, "
                        f"stops_lvl={_stops_level_value:.5f}, min_dist={_min_dist:.5f})"
                    )

        # Hard filter min_rr post-guard — uniquement si SL effectivement ajusté
        if _sl_was_adjusted and entry and tp and sl is not None:
            _risk_new = abs(entry - sl)
            if _risk_new > 0:
                _rr_new = abs(tp - entry) / _risk_new
                _min_rr_eff = float(getattr(self, "_hf_min_rr", 1.0) or 1.0)
                if _rr_new < _min_rr_eff:
                    self._sl_guard_stats["rejections_post_guard"] += 1
                    logger.warning(
                        f"[HARD_FILTER][min_rr] {symbol} {action}: rejet après "
                        f"ajustement SL_GUARD — R:R={_rr_new:.3f} < "
                        f"min_rr={_min_rr_eff:.3f} (sl {_old_sl:.5f}→{sl:.5f}, "
                        f"tp inchangé={tp:.5f})"
                    )
                    return None

        # FIX R14: Vérification cohérence directionnelle post-refresh
        if entry and sl and tp:
            if action == "BUY" and (sl >= entry or tp <= entry):
                logger.error(
                    f"[DIR_CHECK] {symbol} BUY incohérent: "
                    f"sl={sl} >= entry={entry} ou tp={tp} <= entry={entry} — SKIP"
                )
                return None
            if action == "SELL" and (sl <= entry or tp >= entry):
                logger.error(
                    f"[DIR_CHECK] {symbol} SELL incohérent: "
                    f"sl={sl} <= entry={entry} ou tp={tp} >= entry={entry} — SKIP"
                )
                return None

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
            # FIX R16: Marquer le timestamp même en cas d'échec
            # pour empêcher le gate de re-tenter dans les 300s
            self._last_exec_ts = datetime.now(timezone.utc)
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

        # FIX 2026-03-09: Fallback 60→120 pour sémaphore MT5 (9 orchestrateurs sérialisés)
        interval_seconds = int(self.timeframes_cfg.get("orchestrator", 120))
        job_id = f"orch_{self.symbol}"

        # Nettoyage d’anciens jobs, si existent
        for jid in (job_id, f"report_{self.symbol}", f"autoopt_{self.symbol}", f"pm_{self.symbol}"):
            try:
                self.scheduler.remove_job(jid)
            except Exception:
                pass

        # FIX 2026-03-06: Décaler les symboles pour ne pas saturer MT5
        import hashlib
        _sym_hash = int(hashlib.md5(self.symbol.encode()).hexdigest()[:4], 16)
        _offset_secs = (_sym_hash % 9) * 7  # Décalage 0-56 secondes selon le symbole

        # Boucle principale de décision
        # Utiliser le wrapper synchrone qui exécute la coroutine async dans le bon event loop
        from datetime import timedelta as _td
        self.scheduler.add_job(
            self._run_agents_and_decide_sync,
            "interval",
            seconds=interval_seconds,
            id=job_id,
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + _td(seconds=_offset_secs),  # FIX 2026-03-06: décalage
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
                # FIX 2026-03-10: Wrapper le PM avec le lock hybride MT5
                # Le PM tourne dans un thread APScheduler et fait des appels MT5 COM
                # Sans le lock, il entre en conflit avec les coroutines asyncio → deadlock
                _pm_ref = self.pm

                def _pm_with_mt5_lock():
                    with _GLOBAL_MT5_SEMAPHORE:
                        _pm_ref.manage_open_positions()

                self.scheduler.add_job(
                    _pm_with_mt5_lock,
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
            # FIX 2026-03-10 R6: Appel MT5 sync → to_thread + lock (event loop non bloqué)
            async with _GLOBAL_MT5_SEMAPHORE:
                count, volume, net = await asyncio.to_thread(self._current_position_stats)
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

        # FIX 2026-03-10 R6: Appels MT5 sync → to_thread + lock (groupés pour minimiser les locks)
        async with _GLOBAL_MT5_SEMAPHORE:
            pnl_today_ccy = await asyncio.to_thread(self._today_pnl_currency)  # P/L réalisé (ce symbole)
            consec_losses = int(await asyncio.to_thread(self._current_losing_streak))  # série de pertes
        daily_loss_pct = pnl_today_ccy / max(equity_start, 1e-9)        # ex: -0.012 = -1.2% (pas d’appel MT5)

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

        # (audit fev2026) Floating P&L: vérifier réalisé + flottant
        # FIX 2026-02-24: utilisait 'mt5' non importé → remplacé par '_mt5' (Directive 11)
        if abs_limit > 0:
            try:
                floating_pnl = 0.0
                if _mt5 is not None:  # FIX 2026-02-24: était 'mt5' → '_mt5'
                    broker_sym = self.broker_symbol or self.symbol
                    # FIX 2026-03-10: Protéger l'accès COM avec le sémaphore global
                    async with _GLOBAL_MT5_SEMAPHORE:
                        open_positions = await asyncio.to_thread(_mt5.positions_get, symbol=broker_sym)
                    if open_positions:
                        floating_pnl = sum(float(getattr(p, "profit", 0.0) or 0.0) for p in open_positions)
                total_pnl = pnl_today_ccy + floating_pnl
                if total_pnl <= -abs(abs_limit):
                    logger.info("[RISK] %s daily loss (realized+floating) limit reached: realized=%.2f floating=%.2f total=%.2f <= -%.2f",
                                self.symbol, pnl_today_ccy, floating_pnl, total_pnl, abs_limit)
                    _record_guard_event(self.symbol, "daily-abs-floating-guard", f"Total {total_pnl:.2f} <= -{abs_limit:.2f}")
                    self._arm_cooldown(self._cooldown_after_loss_min, "daily-abs-floating-guard")
                    self._send_telegram(
                        f"[RISK] Limite journaliere (réalisé+flottant) atteinte ({self.symbol})\n"
                        f"Réalisé: {pnl_today_ccy:.2f} | Flottant: {floating_pnl:.2f} | Total: {total_pnl:.2f} <= -{abs_limit:.2f}\n"
                        f"Pause des entrées.",
                        kind="status", force=True,
                    )
                    return
            except Exception as e:
                # FIX 2026-02-24: En cas d'échec, bloquer par précaution (protéger le capital)
                logger.error(f"[RISK_CRITICAL] Floating P&L check failed: {e} — trades bloqués par précaution")
                self._send_telegram(
                    f"[FLOATING_PL_ERROR] {self.symbol}: Impossible de vérifier le P&L flottant ({e}). "
                    f"Nouveaux trades bloqués par précaution.",
                    kind="status", force=True,
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
            # FIX 2026-03-10 R6: _log_equity_snapshot fait account_info() → to_thread + lock
            async with _GLOBAL_MT5_SEMAPHORE:
                await asyncio.to_thread(self._log_equity_snapshot)

            symbol = self.symbol

            # 1) Planning profiles.yaml (on priorise le planning par symbole)
            if not self._is_symbol_profile_active_now():
                logger.info(f"[SCHEDULE] {symbol} désactivé selon profiles.schedule → pas d'action.")
                return

            # 2) Fenêtre orchestrator (optionnelle, fine-tuning intra-jour par profil)
            if not self._is_in_trading_window():
                logger.info(f"[WINDOW] {symbol} hors fenêtre orchestrator.trading_window → pas d'action.")
                return



            # ═══════════════════════════════════════════════════════════════
            # FIX 2026-02-20: Garde-fous AVANT calcul des signaux (étape 2.4)
            # Ordre: 1) Kill switch global, 2) Circuit-breaker symbole, 3) EOD
            # ═══════════════════════════════════════════════════════════════

            # (a) Kill Switch Global — vérifie perte journalière totale
            if get_global_kill_switch is not None:
                try:
                    _global_cfg = (self.overrides_all or {}).get("GLOBAL", {})
                    _ks_limit = float((_global_cfg.get("risk") or {}).get("global_daily_loss_limit", self._hf_kill_switch_usd))
                    _ks = get_global_kill_switch(_ks_limit)
                    _floating = 0.0
                    try:
                        _floating = float(self.risk.get_floating_pnl()) if hasattr(self.risk, "get_floating_pnl") else 0.0
                    except Exception:
                        _floating = 0.0
                    _ks_blocked, _ks_reason = _ks.check_kill_switch(_floating)
                    if _ks_blocked:
                        logger.warning(f"[KILL_SWITCH] {symbol} bloqué: {_ks_reason}")
                        self._send_telegram(
                            f"[KILL_SWITCH] Trading BLOQUE: {_ks_reason} "
                            f"(realized={_ks._state.get('realized_pnl', 0):.2f} + floating={_floating:.2f})",
                            kind="status", force=True
                        )
                        return
                except Exception as _ks_err:
                    logger.debug(f"[KILL_SWITCH] Erreur vérification: {_ks_err}")

            # (b) Circuit-Breaker par symbole — 3 pertes consécutives = 24h de pause
            if get_circuit_breaker is not None:
                try:
                    _cb = get_circuit_breaker()
                    _cb_blocked, _cb_reason = _cb.is_blocked(symbol)
                    if _cb_blocked:
                        logger.info(f"[CIRCUIT_BREAKER] {symbol} bloqué: {_cb_reason}")
                        return
                except Exception as _cb_err:
                    logger.debug(f"[CIRCUIT_BREAKER] Erreur vérification: {_cb_err}")

            # (c) Restriction EOD — pas de nouvelles positions non-crypto après 18:00 UTC
            if is_eod_restricted is not None:
                try:
                    _eod_cfg = (self.overrides_all or {}).get("GLOBAL", {})
                    _last_entry = str(_eod_cfg.get("last_entry_time_utc", "18:00"))
                    if is_eod_restricted(symbol, _last_entry):
                        logger.info(f"[EOD] {symbol} bloqué: après {_last_entry} UTC (non-crypto)")
                        return
                except Exception as _eod_err:
                    logger.debug(f"[EOD] Erreur vérification: {_eod_err}")

            # (d) Fermeture EOD — fermer positions non-crypto après 19:30 UTC
            if should_close_eod is not None:
                try:
                    _eod_close_cfg = (self.overrides_all or {}).get("GLOBAL", {})
                    _eod_close_time = str(_eod_close_cfg.get("eod_close_time_utc", "19:30"))
                    if should_close_eod(symbol, _eod_close_time):
                        logger.info(f"[EOD_CLOSE] {symbol}: fermeture EOD demandée ({_eod_close_time} UTC)")
                        # FIX 2026-02-20: Fermeture effective via MT5 (étape 2.3)
                        # FIX 2026-03-09: Toute la logique EOD dans asyncio.to_thread (appels MT5 synchrones)
                        try:
                            if _mt5 is not None:  # FIX 2026-02-24: était 'mt5' → '_mt5' (Directive 11)
                                _broker_sym = getattr(self, "broker_symbol", symbol)

                                def _eod_close_sync(_sym, _bsym, _close_time):
                                    """Bloc synchrone pour fermer les positions EOD via MT5 COM."""
                                    _closed = []
                                    _positions = _mt5.positions_get(symbol=_bsym) or []
                                    for _p in _positions:
                                        _ticket = int(getattr(_p, "ticket", 0) or 0)
                                        _vol = float(getattr(_p, "volume", 0) or 0)
                                        _type = int(getattr(_p, "type", 0))
                                        _profit = float(getattr(_p, "profit", 0) or 0)
                                        if _ticket <= 0 or _vol <= 0:
                                            continue
                                        _side = "BUY" if _type == 0 else "SELL"
                                        _order_type = _mt5.ORDER_TYPE_SELL if _side == "BUY" else _mt5.ORDER_TYPE_BUY
                                        _tick = _mt5.symbol_info_tick(_bsym)
                                        _price = (_tick.bid if _side == "BUY" else _tick.ask) if _tick else 0
                                        if _price <= 0:
                                            continue
                                        _req = {
                                            "action": _mt5.TRADE_ACTION_DEAL,
                                            "position": _ticket,
                                            "symbol": _bsym,
                                            "volume": _vol,
                                            "type": _order_type,
                                            "price": _price,
                                            "deviation": 30,
                                            "magic": 0,
                                            "comment": "eod_close",
                                            "type_filling": _mt5.ORDER_FILLING_IOC,
                                            "type_time": _mt5.ORDER_TIME_GTC,
                                        }
                                        _result = _mt5.order_send(_req)
                                        if _result and _result.retcode == _mt5.TRADE_RETCODE_DONE:
                                            _closed.append((_ticket, _profit, True, ""))
                                        else:
                                            _err = _result.comment if _result else "Unknown"
                                            _closed.append((_ticket, _profit, False, _err))
                                    return _closed

                                # FIX 2026-03-10: Protéger les appels COM EOD avec le sémaphore
                                async with _GLOBAL_MT5_SEMAPHORE:
                                    _eod_results = await asyncio.to_thread(_eod_close_sync, symbol, _broker_sym, _eod_close_time)
                                for _ticket, _profit, _ok, _err in _eod_results:
                                    if _ok:
                                        logger.info(f"[EOD_CLOSE] {symbol} ticket {_ticket} fermé (P&L: {_profit:+.2f})")
                                        self._send_telegram(
                                            f"[EOD_CLOSE] {symbol} #{_ticket} fermé à {_eod_close_time} UTC (P&L: {_profit:+.2f})",
                                            kind="trade_event", force=True
                                        )
                                    else:
                                        logger.warning(f"[EOD_CLOSE] Échec fermeture {symbol} #{_ticket}: {_err}")
                        except Exception as _eod_mt5_err:
                            logger.warning(f"[EOD_CLOSE] Erreur MT5: {_eod_mt5_err}")
                        return  # Pas de nouveau trade après EOD close
                except Exception as _eod_close_err:
                    logger.debug(f"[EOD_CLOSE] Erreur: {_eod_close_err}")

            # 1) Collecte des signaux agents + indicateurs (+ hints SL/TP/PRICE)
            per_tf_signals, global_signals, indicators, market = await self._gather_agent_signals(symbol)

            # Sauvegarde pour dashboard live
            self.save_signals_to_json(symbol, global_signals)

            # Prix courant & contexte
            price = market.get("price")

            # Fallback prix robuste
            # FIX 2026-03-09: Wrapper dans asyncio.to_thread pour ne pas bloquer le event loop
            if price is None:
                try:
                    # FIX 2026-03-10 R6: Protéger l'appel COM avec le lock
                    async with _GLOBAL_MT5_SEMAPHORE:
                        price = await asyncio.to_thread(self.mt5.get_last_price, symbol, "BUY")
                except Exception:
                    price = None

            if price is None:
                logger.info(f"[{symbol}] Pas de prix (tick & fallback indisponibles) → skip.")
                return

            # FIX 2026-02-20: Détection régime centralisée AVANT agrégation (étape 5.1)
            self._current_regime = ""
            try:
                if detect_market_regime is not None:
                    _regime_df = self._get_ohlcv_dataframe(symbol, "H1", 150) if hasattr(self, "_get_ohlcv_dataframe") else None
                    if _regime_df is not None and len(_regime_df) > 50:
                        _regime_res = detect_market_regime(symbol, _regime_df)
                        self._current_regime = str(_regime_res.get("regime_name", "")).lower()
            except Exception:
                pass

            # 2) Agrégation → direction/score/confluence
            direction, score_agr, confluence, _details = self._compute_aggregate_direction(
                per_tf_signals, global_signals, indicators
            )
            regime_label, tracker_input = self._build_tracker_signals(per_tf_signals, global_signals)

            # FIX 2026-03-23 R15: Log décision finale
            logger.info(
                f"[DECISION] {symbol}: {direction or 'NEUTRAL'} score={score_agr:.2f} "
                f"conf={confluence} regime={regime_label}"
            )
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

            # 3) Fast-tracks (audit fev2026: seuil 4→5 TF + confirmation structure/swing)
            tech_signals = per_tf_signals.get("technical", {})
            news_dir = _norm(global_signals.get("news") if global_signals else None)
            tech_majority_long = sum(1 for sig in tech_signals.values() if _norm(sig) == "LONG")
            tech_majority_short = sum(1 for sig in tech_signals.values() if _norm(sig) == "SHORT")

            # FIX 2026-02-20: Fast-track corrigé (étape 3.1)
            # - Structure ET swing requis (pas OR)
            # - Score individuel > 1.5 requis
            # - Bonus +0.5 au lieu de forcer 2.1
            structure_dir = _norm(global_signals.get("structure") if global_signals else None)
            swing_dir_ft = _norm(global_signals.get("swing") if global_signals else None)

            fast_track_validated = False
            if tech_majority_long >= 5 and news_dir == "LONG":
                if structure_dir == "LONG" and swing_dir_ft == "LONG" and score_agr > 1.5:
                    direction = "LONG"; score_agr += 0.5; confluence = max(confluence, 2)
                    fast_track_validated = True
            elif tech_majority_short >= 5 and news_dir == "SHORT":
                if structure_dir == "SHORT" and swing_dir_ft == "SHORT" and score_agr > 1.5:
                    direction = "SHORT"; score_agr += 0.5; confluence = max(confluence, 2)
                    fast_track_validated = True

            whale_dir = _norm(global_signals.get("whale") if global_signals else None)
            if whale_dir in ("LONG", "SHORT") and self.whale_agent:
                over_cfg = self.whale_override_cfg
                if bool(over_cfg.get("enable", False)):
                    trust_val = float(indicators.get("WHALE_TRUST_SCORE", 0.0))
                    signal_val = float(indicators.get("WHALE_SIGNAL_SCORE", 0.0))
                    min_trust = float(over_cfg.get("min_trust", self.whale_cfg.get("min_trust", self.min_trust)))
                    min_signal = float(over_cfg.get("min_signal", self.whale_cfg.get("min_signal", self.min_signal)))
                    allow_vol = bool(over_cfg.get("allow_in_vol_spike", self.whale_cfg.get("allow_in_vol_spike", self.whale_allow_in_vol_spike)))
                    vol_limit = float(over_cfg.get("volatility_z_th", self._hf_whale_max_vol_z))
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

            # FIX 2026-03-10 R6: weekend guard fait des appels MT5 (close_positions) → to_thread + lock
            async with _GLOBAL_MT5_SEMAPHORE:
                _wg_blocked = await asyncio.to_thread(self._weekend_guard_blocked)
            if _wg_blocked:
                reasons.append("forex_weekend_guard")
                decision_notes.append("forex_weekend_guard")

            if direction not in ("LONG", "SHORT"):
                reasons.append("direction_indeterminee")

            # FIX 2026-02-20: Session filter — ajuster min_score hors prime hours (étape 5.5)
            _eff_min_score = self.min_score_for_proposal
            if get_adjusted_min_score is not None:
                try:
                    _prime_cfg = ((self.overrides_all or {}).get(symbol, {}) or {}).get("prime_hours_utc")
                    _eff_min_score, _in_prime = get_adjusted_min_score(symbol, self.min_score_for_proposal, _prime_cfg)
                    if not _in_prime:
                        decision_notes.append(f"off_prime_hours(min_score={_eff_min_score:.2f})")
                except Exception:
                    pass

            if score_agr < _eff_min_score:
                reasons.append(f"score({score_agr:.2f})<min({_eff_min_score:.2f})")
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
                # FIX 2026-02-23: Recalculer si atr est None, 0 ou 0.0 (Directive 5)
                # FIX 2026-03-09: Wrapper dans asyncio.to_thread (appels MT5 synchrones)
                if not atr or atr <= 0:
                    # FIX 2026-03-10: Protéger les appels COM ATR avec le sémaphore
                    async with _GLOBAL_MT5_SEMAPHORE:
                        atr = await asyncio.to_thread(self._compute_atr, symbol, "H1") or await asyncio.to_thread(self._compute_atr, symbol, "M30")

                # Fallback ATR si manque SL/TP
                # FIX 2026-02-23: Test explicite atr > 0 (Directive 5)
                if atr and atr > 0:
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
                # FIX 2026-02-23: est_atr proportionnel au prix (Directive 6)
                # pt*200 donne 2$ pour BTCUSD — price*0.003 donne 204$ (bien plus réaliste)
                est_atr = float(atr) if (atr is not None and atr > 0) else max(pt * 200.0, (price or 0) * 0.003)
                broker_min = 0.0
                try:
                    if hasattr(self.mt5, "_min_stop_distance_points"):
                        # FIX 2026-03-10: Protéger l'accès COM avec le sémaphore
                        async with _GLOBAL_MT5_SEMAPHORE:
                            min_pts_candidate = float(await asyncio.to_thread(self.mt5._min_stop_distance_points, self.symbol))  # type: ignore[attr-defined]
                        broker_min = max(broker_min, min_pts_candidate * pt)
                except Exception:
                    broker_min = broker_min or 0.0
                # FIX 2026-02-23: Ajout price*0.0005 comme plancher (34$ pour BTCUSD) (Directive 6)
                _price_floor = (price * 0.0005) if price else 0.0
                min_pts = max(est_atr * 0.10, pt * 50.0, broker_min, _price_floor)

                def ensure_min_distance(p, s, t, side):
                    # FIX 2026-02-23: Utiliser est_atr au lieu de (atr or pt*200) (Directive 6)
                    _fb_atr = atr if (atr and atr > 0) else est_atr
                    if side == "LONG":
                        if s is None or s >= p - min_pts:
                            s = p - mul_sl * _fb_atr
                        if t is None or t <= p + min_pts:
                            t = p + mul_tp * _fb_atr
                    else:
                        if s is None or s <= p + min_pts:
                            s = p + mul_sl * _fb_atr
                        if t is None or t >= p - min_pts:
                            t = p - mul_tp * _fb_atr
                    # enforce distances mini finales
                    if abs(p - s) < min_pts:
                        s = p - min_pts if side == "LONG" else p + min_pts
                    if abs(t - p) < min_pts:
                        t = p + min_pts if side == "LONG" else p - min_pts
                    return s, t

                if direction in ("LONG", "SHORT") and price is not None:
                    sl, tp = ensure_min_distance(price, sl, tp, direction)

                    # FIX 2026-03-10: Si le R:R agent est trop bas, recalculer TP via ATR
                    # Les agents fournissent parfois des SL/TP trop conservateurs (R:R 0.40-0.70)
                    if sl is not None and tp is not None and price:
                        try:
                            _fb_atr = atr if (atr and atr > 0) else est_atr
                            if direction == "LONG":
                                _rr_check = (tp - price) / max(price - sl, 1e-9)
                            else:
                                _rr_check = (price - tp) / max(sl - price, 1e-9)
                            if _rr_check < self._hf_min_rr and _fb_atr > 0:
                                _desired_tp_dist = abs(price - sl) * self._hf_min_rr
                                _atr_tp_dist = mul_tp * _fb_atr
                                _new_tp_dist = max(_desired_tp_dist, _atr_tp_dist)
                                if direction == "LONG":
                                    tp = price + _new_tp_dist
                                else:
                                    tp = price - _new_tp_dist
                                _new_rr = _new_tp_dist / max(abs(price - sl), 1e-9)
                                logger.info(f"[RR_FIX] {symbol}: R:R {_rr_check:.2f} → {_new_rr:.2f} (TP recalculé via ATR)")
                        except Exception as _rr_e:
                            logger.debug(f"[RR_FIX] {symbol}: erreur recalcul: {_rr_e}")

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
                # Priorité: config orchestrator, sinon hard_filters.min_rr
                min_rr = float(self.ori_cfg.get("min_rr_required") or self.ori_cfg.get("min_rr") or self._hf_min_rr)
            except Exception:
                min_rr = self._hf_min_rr

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
                            elif regime_type == "volatile" and regime_confidence > self._hf_quiet_block_confidence:
                                decision_notes.append("volatile_market_caution")
                            # FIX 2026-02-20: Bloquer en régime QUIET (config: hard_filters.quiet_block_confidence)
                            elif regime_type == "quiet" and regime_confidence > self._hf_quiet_block_confidence:
                                reasons.append(f"regime_quiet(conf={regime_confidence:.2f})")
                                decision_notes.append("quiet_regime_blocked")
                                logger.info(f"[REGIME] {symbol} bloqué: régime QUIET (conf={regime_confidence:.2f})")
                            # R17: SHORT en régime non-trending_down = interdit sauf score élevé
                            elif direction == "SHORT" and regime_type not in ("trending_down",) and regime_confidence > 0.5:
                                _short_regime_min = self._hf_counter_trend_min_score
                                if score_agr < _short_regime_min:
                                    reasons.append(f"short_not_trending_down:{regime_type}")
                                    decision_notes.append(f"short_regime_blocked:{regime_type}")
                                    logger.info(
                                        f"[REGIME] {symbol} SHORT bloqué: régime={regime_type} "
                                        f"(pas trending_down), score={score_agr:.1f}<{_short_regime_min}"
                                    )

                        # ══════════════════════════════════════════════════════════════
                        # OPTIMISATION 2025-12-30: Renforcer filtre contre-tendance BUY
                        # Si tendance baissiere HTF (meme non stable), exiger score >= 10
                        # ══════════════════════════════════════════════════════════════
                        if regime_type == "trending_down" and direction == "LONG":
                            current_score = score_agr  # FIX 2026-02-24: était confidence (nombre confluences 2-5) au lieu du score réel
                            min_score_counter_trend = self._hf_counter_trend_min_score
                            if regime_confidence > 0.4 and current_score < min_score_counter_trend:
                                reasons.append(f"counter_trend_low_score:{current_score:.1f}<{min_score_counter_trend}")
                                decision_notes.append(f"buy_against_downtrend_blocked")
                                logger.info(f"[COUNTER_TREND] {symbol} BUY bloqué: score={current_score:.1f} < {min_score_counter_trend} en downtrend (conf={regime_confidence:.2f})")
                        elif regime_type == "trending_up" and direction == "SHORT":
                            current_score = score_agr  # FIX 2026-02-24: était confidence (nombre confluences 2-5) au lieu du score réel
                            min_score_counter_trend = self._hf_counter_trend_min_score
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
                # FIX 2026-03-10: Wrapper sync → to_thread + sémaphore
                async with _GLOBAL_MT5_SEMAPHORE:
                    open_crypto = await asyncio.to_thread(_count_open_crypto_positions)
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
                # FIX 2026-03-10: Wrapper sync → to_thread + sémaphore
                async with _GLOBAL_MT5_SEMAPHORE:
                    used = await asyncio.to_thread(_crypto_bucket_risk_used, get_symbol_profile)
                room = max(0.0, cap - used)

                # risque prévu pour le trade courant (approx comme dans _crypto_bucket_risk_used)
                inst = (self.profile.get("instrument") or {})
                point = float(inst.get("point") or 0.0)
                pip_value = float(inst.get("pip_value") or 0.0)
                # FIX 2026-03-10: Protéger l'accès COM avec le sémaphore
                async with _GLOBAL_MT5_SEMAPHORE:
                    ai = await asyncio.to_thread(_mt5.account_info)
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
                    # Snapshot "proposed" (même si auto)
                    try:
                        self._log_agents_snapshot_jsonl(
                            per_tf_signals, global_signals, indicators, market, context="proposed"
                        )
                    except Exception:
                        pass

                    # FIX 2026-03-10: execute_trade fait ~4 appels MT5 COM (account_info, positions_get,
                    # is_trade_blocked_by_inter_market, _count_open_crypto_positions)
                    # → sémaphore obligatoire pour éviter le deadlock COM inter-thread
                    async with _GLOBAL_MT5_SEMAPHORE:
                        trade_ok = await asyncio.to_thread(self.execute_trade, direction)
                    self._log_proposal_csv(direction, price, sl, tp, lots, score_agr, confluence, self.proposal_ttl_secs, expired=False, executed=bool(trade_ok))
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

    # ------------------------------------------------------------------ agent cache
    def _get_or_load_agent(self, module_name: str, class_name: str, *, symbol: Optional[str] = None):
        """Charge un agent depuis le cache ou l'instancie (Part A perf)."""
        key = f"{module_name}.{class_name}"

        # Skip si en cooldown erreur (réactivation auto après délai)
        if class_name in self._agent_disabled_until:
            if datetime.now(timezone.utc) > self._agent_disabled_until[class_name]:
                del self._agent_disabled_until[class_name]
                logger.info(f"[AGENT] {class_name} réactivé après cooldown")
                self._send_telegram(
                    f"🔄 [AGENT REACTIVATED] {class_name} réactivé après cooldown pour {self.symbol}",
                    kind="status", force=True
                )
            else:
                return None

        if key in self._agent_cache:
            return self._agent_cache[key]

        try:
            mod = importlib.import_module(f"agents.{module_name}")
            cls = getattr(mod, class_name, None)
            if cls is None:
                logger.warning(f"[AGENT] Classe introuvable: agents.{module_name}.{class_name}")
                return None

            init = getattr(cls, "__init__", None)
            if init is None:
                agent = cls()
                self._agent_cache[key] = agent
                return agent

            sig = inspect.signature(init)
            accepted = set(sig.parameters.keys())

            params: Dict[str, Any] = {}
            if "symbol" in accepted:
                params["symbol"] = symbol or self.symbol
            for k in ("mt5", "client", "mt5_client"):
                if k in accepted:
                    params[k] = self.mt5
                    break
            for k in ("profile", "cfg", "config", "conf"):
                if k in accepted:
                    params[k] = self.profile
                    break

            agent = cls(**params)
            self._agent_cache[key] = agent
            return agent
        except Exception as e:
            logger.warning(f"[AGENT] Chargement agents.{module_name}.{class_name} a échoué: {e}")
            return None

    def _invalidate_agent_cache(self, agent_class_name: Optional[str] = None) -> None:
        """Vide le cache d'agents. Si agent_class_name est fourni, ne retire que celui-là."""
        if agent_class_name is None:
            self._agent_cache.clear()
            logger.info("[AGENT] Cache agents vidé intégralement.")
        else:
            keys_to_remove = [k for k in self._agent_cache if k.endswith(f".{agent_class_name}")]
            for k in keys_to_remove:
                del self._agent_cache[k]
            if keys_to_remove:
                logger.info(f"[AGENT] Cache invalidé pour {agent_class_name}.")

    async def _gather_agent_signals(
        self, symbol: str
    ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str], Dict[str, float], Dict[str, Any]]:
        """
        Récupère les signaux par agent/TF + signaux globaux + indicateurs + contexte de marché.

        Les agents sont exécutés en parallèle via asyncio.gather + to_thread (Part B perf).
        """
        _AGENT_TIMEOUT = 45      # FIX 2026-03-06: augmenté 10→45s pour agents MT5
        _API_AGENT_TIMEOUT = 15  # FIX 2026-03-09: timeout réduit pour agents API (HTTP requests)

        # --- Contexte marché ---
        # FIX 2026-03-10 R6: _get_last_price fait ~8 appels MT5 → protéger avec le lock
        async with _GLOBAL_MT5_SEMAPHORE:
            price = await asyncio.to_thread(self._get_last_price, symbol)
        equity = None
        try:
            if hasattr(self.mt5, "get_account_info"):
                # FIX 2026-03-10 R6: Protéger l'appel COM avec le lock
                async with _GLOBAL_MT5_SEMAPHORE:
                    ai = await asyncio.to_thread(self.mt5.get_account_info)
                if ai and hasattr(ai, "equity"):
                    equity = float(ai.equity)
        except Exception:
            pass

        agents_cfg = (self.profile.get("agents") or {})

        # FIX 2026-03-10: fundamental/macro disabled par défaut si pas dans la config
        # Évite que les profils sans ces clés (SP500, NAS100...) les lancent
        _AGENTS_DEFAULT_DISABLED = {"fundamental", "macro"}

        def agent_enabled(name: str) -> bool:
            try:
                cfg = agents_cfg.get(name)
                if cfg is None:
                    return name not in _AGENTS_DEFAULT_DISABLED
                return bool(cfg.get("enabled", True))
            except Exception:
                return True

        per_tf_signals: Dict[str, Dict[str, str]] = {
            "technical": {},
            "scalping": {},
            "swing": {},
            "structure": {},
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

        # --- Loader dynamique (utilise cache self._agent_cache) ---
        def load_agent(module_name: str, class_name: str):
            return self._get_or_load_agent(module_name, class_name, symbol=symbol)

        # --- Runner générique ---
        def call_agent(agent, timeframe: Optional[str] = None) -> Optional[Dict[str, Any]]:
            if agent is None:
                return None

            agent_name = type(agent).__name__
            if agent_name in self._agent_disabled_until:
                if datetime.now(timezone.utc) > self._agent_disabled_until[agent_name]:
                    del self._agent_disabled_until[agent_name]
                    logger.info(f"[AGENT] {agent_name} réactivé après cooldown")
                    self._send_telegram(
                        f"🔄 [AGENT REACTIVATED] {agent_name} réactivé après cooldown pour {self.symbol}",
                        kind="status", force=True
                    )
                else:
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
                    logger.error(f"[AGENT] {agent_name} erreur sur méthode {name}: {e}", exc_info=True)
                    last_err = e
                    # Monitoring erreurs + cooldown progressif (2026-03-01)
                    self._agent_error_counts[agent_name] = self._agent_error_counts.get(agent_name, 0) + 1
                    if self._agent_error_counts[agent_name] >= 5:
                        prev_cd = self._agent_cooldown_hours.get(agent_name, 0.5)
                        cooldown_h = min(prev_cd * 2, 8.0)  # Double: 1h, 2h, 4h, 8h max
                        self._agent_cooldown_hours[agent_name] = cooldown_h
                        self._agent_disabled_until[agent_name] = datetime.now(timezone.utc) + timedelta(hours=cooldown_h)
                        self._agent_error_counts[agent_name] = 0
                        self._invalidate_agent_cache(agent_name)
                        logger.error(f"[AGENT] {agent_name} désactivé pour {cooldown_h:.0f}h après 5 erreurs")
                        self._send_telegram(
                            f"⚠️ [AGENT COOLDOWN] {agent_name} désactivé pour {cooldown_h:.0f}h ({self.symbol}) "
                            f"— réactivation auto à {self._agent_disabled_until[agent_name].strftime('%H:%M UTC')}",
                            kind="status", force=True
                        )
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

        # ================================================================
        # Blocs agents isolés (chacun retourne un dict partiel de résultats)
        # Exécutés en parallèle via asyncio.gather + to_thread
        # ================================================================

        def _run_technical() -> Dict[str, Any]:
            r: Dict[str, Any] = {"per_tf": {}, "indicators": {}, "details": {}}
            agent = load_agent("technical", "TechnicalAgent") if agent_enabled("technical") else None
            if not agent:
                return r
            for tf in self.tfs:
                out = call_agent(agent, timeframe=tf)
                if isinstance(out, dict):
                    r["per_tf"][tf] = _norm(out.get("signal"))
                    for k in ("ATR_H1", "ATR_M30", f"ATR_{tf}"):
                        if k in out and isinstance(out[k], (int, float)):
                            r["indicators"][k] = float(out[k])
                    sl = self._safe_float(out.get("sl"))
                    tp = self._safe_float(out.get("tp"))
                    pr = self._safe_float(out.get("price"))
                    if sl is not None or tp is not None or pr is not None:
                        d: Dict[str, float] = {}
                        if sl is not None: d["sl"] = sl
                        if tp is not None: d["tp"] = tp
                        if pr is not None: d["price"] = pr
                        r["details"][tf] = d
            return r

        def _run_scalping() -> Dict[str, Any]:
            r: Dict[str, Any] = {"per_tf": {}, "details": {}}
            agent = load_agent("scalping", "ScalpingAgent") if agent_enabled("scalping") else None
            if not agent:
                return r
            for tf in self.tfs:
                out = call_agent(agent, timeframe=tf)
                if isinstance(out, dict):
                    r["per_tf"][tf] = _norm(out.get("signal"))
                    sl = self._safe_float(out.get("sl"))
                    tp = self._safe_float(out.get("tp"))
                    pr = self._safe_float(out.get("price"))
                    if sl is not None or tp is not None or pr is not None:
                        d: Dict[str, float] = {}
                        if sl is not None: d["sl"] = sl
                        if tp is not None: d["tp"] = tp
                        if pr is not None: d["price"] = pr
                        r["details"][tf] = d
            return r

        def _run_swing() -> Dict[str, Any]:
            r: Dict[str, Any] = {"per_tf": {}, "global": {}, "details": {}}
            agent = load_agent("swing", "SwingAgent") if agent_enabled("swing") else None
            if not agent:
                return r
            votes = {"LONG": 0, "SHORT": 0}
            for tf in self.tfs:
                out = call_agent(agent, timeframe=tf)
                if isinstance(out, dict):
                    s = _norm(out.get("signal"))
                    if s:
                        r["per_tf"][tf] = s
                        votes[s] += 1
                    sl = self._safe_float(out.get("sl"))
                    tp = self._safe_float(out.get("tp"))
                    pr = self._safe_float(out.get("price"))
                    if sl is not None or tp is not None or pr is not None:
                        d: Dict[str, float] = {}
                        if sl is not None: d["sl"] = sl
                        if tp is not None: d["tp"] = tp
                        if pr is not None: d["price"] = pr
                        r["details"][tf] = d
            if votes["LONG"] > votes["SHORT"]:
                r["global"]["swing"] = "LONG"
            elif votes["SHORT"] > votes["LONG"]:
                r["global"]["swing"] = "SHORT"
            return r

        def _run_structure() -> Dict[str, Any]:
            r: Dict[str, Any] = {"per_tf": {}, "smc_tf": {}, "global": {}, "details": {}, "market": {}}
            agent = load_agent("structure", "StructureAgent") if agent_enabled("structure") else None
            if not agent:
                return r
            structure_v = {"LONG": 0, "SHORT": 0}
            smc_v = {"LONG": 0, "SHORT": 0}
            for tf in self.tfs:
                out = call_agent(agent, timeframe=tf)
                if isinstance(out, dict):
                    s = _norm(out.get("signal"))
                    if s:
                        r["per_tf"][tf] = s
                        structure_v[s] += 1
                    sl = self._safe_float(out.get("sl"))
                    tp = self._safe_float(out.get("tp"))
                    pr = self._safe_float(out.get("price"))
                    if sl is not None or tp is not None or pr is not None:
                        d: Dict[str, float] = {}
                        if sl is not None: d["sl"] = sl
                        if tp is not None: d["tp"] = tp
                        if pr is not None: d["price"] = pr
                        r["details"][tf] = d
                    smc = _norm(out.get("smc_signal"))
                    if smc:
                        r["smc_tf"][tf] = smc
                        smc_v[smc] += 1
                    if out.get("smc_events"):
                        r["market"].setdefault("smc_events", {})[tf] = out["smc_events"]
                    if out.get("smc_meta"):
                        r["market"].setdefault("smc_meta", {})[tf] = out["smc_meta"]
            if structure_v["LONG"] > structure_v["SHORT"]:
                r["global"]["structure"] = "LONG"
            elif structure_v["SHORT"] > structure_v["LONG"]:
                r["global"]["structure"] = "SHORT"
            if smc_v["LONG"] > smc_v["SHORT"]:
                r["global"]["smc"] = "LONG"
            elif smc_v["SHORT"] > smc_v["LONG"]:
                r["global"]["smc"] = "SHORT"
            return r

        def _run_whale() -> Dict[str, Any]:
            r: Dict[str, Any] = {"per_tf": {}, "global": {}, "indicators": {}, "details": {}, "market": {}}
            whale = getattr(self, "whale_agent", None)
            if not whale:
                return r
            out = whale.generate_signal()
            if isinstance(out, dict):
                s = _norm(out.get("signal"))
                if s and s != "WAIT":
                    r["per_tf"]["GLOBAL"] = s
                    r["global"]["whale"] = s
                    r["indicators"]["WHALE_TRUST_SCORE"] = float(out.get("trust_score", 0.0))
                    r["indicators"]["WHALE_SIGNAL_SCORE"] = float(out.get("signal_score", 0.0))
                    r["indicators"]["WHALE_LATENCY_MS"] = float(out.get("latency_ms", 0.0))
                    r["details"]["GLOBAL"] = {
                        "lots": float(out.get("lots", 0.0) or 0.0),
                        "sl": float(out.get("sl", 0.0) or 0.0),
                        "tp": float(out.get("tp", 0.0) or 0.0),
                    }
                    r["market"]["whale"] = {
                        "wallet": out.get("wallet"),
                        "source": out.get("source"),
                        "latency_ms": out.get("latency_ms"),
                    }
                    alpha = float(self.whale_cfg.get("ewma_alpha", 0.2))
                    self._whale_trust_ewma = ewma(self._whale_trust_ewma, float(out.get("trust_score", 0.0)), alpha=alpha)
                    if self._whale_trust_ewma is not None:
                        record_whale_trust_ewma(self.symbol, float(self._whale_trust_ewma))
                    r["indicators"]["WHALE_TRUST_EWMA"] = float(self._whale_trust_ewma or 0.0)
            return r

        def _run_news() -> Dict[str, Any]:
            r: Dict[str, Any] = {"global": {}}
            agent = load_agent("news", "NewsAgent") if agent_enabled("news") else None
            if not agent:
                return r
            s = ""
            out_g = call_agent(agent, timeframe=None)
            if isinstance(out_g, dict):
                s = _norm(out_g.get("signal"))
            if s:
                r["global"]["news"] = s
            if "news" not in r["global"]:
                votes = {"LONG": 0, "SHORT": 0}
                for tf in self.tfs:
                    out = call_agent(agent, timeframe=tf)
                    if isinstance(out, dict):
                        s = _norm(out.get("signal"))
                        if s:
                            votes[s] += 1
                if votes["LONG"] > votes["SHORT"]:
                    r["global"]["news"] = "LONG"
                elif votes["SHORT"] > votes["LONG"]:
                    r["global"]["news"] = "SHORT"
            return r

        def _run_sentiment() -> Dict[str, Any]:
            r: Dict[str, Any] = {"global": {}}
            agent = load_agent("sentiment", "SentimentAgent") if agent_enabled("sentiment") else None
            if not agent:
                return r
            out_g = call_agent(agent, timeframe=None)
            if isinstance(out_g, dict):
                s = _norm(out_g.get("signal"))
                if s:
                    r["global"]["sentiment"] = s
            if "sentiment" not in r["global"]:
                votes = {"LONG": 0, "SHORT": 0}
                for tf in self.tfs:
                    out = call_agent(agent, timeframe=tf)
                    if isinstance(out, dict):
                        s = _norm(out.get("signal"))
                        if s:
                            votes[s] += 1
                if votes["LONG"] > votes["SHORT"]:
                    r["global"]["sentiment"] = "LONG"
                elif votes["SHORT"] > votes["LONG"]:
                    r["global"]["sentiment"] = "SHORT"
            return r

        def _run_fundamental() -> Dict[str, Any]:
            r: Dict[str, Any] = {"per_tf": {}, "global": {}}
            agent = load_agent("fundamental", "FundamentalAgent") if agent_enabled("fundamental") else None
            if not agent:
                return r
            votes = {"LONG": 0, "SHORT": 0}
            for tf in self.tfs:
                out = call_agent(agent, timeframe=tf)
                if isinstance(out, dict):
                    s = _norm(out.get("signal"))
                    if s:
                        r["per_tf"][tf] = s
                        votes[s] += 1
            if votes["LONG"] == 0 and votes["SHORT"] == 0:
                out_g = call_agent(agent, timeframe=None)
                if isinstance(out_g, dict):
                    s = _norm(out_g.get("signal"))
                    if s:
                        r["global"]["fundamental"] = s
            return r

        def _run_macro() -> Dict[str, Any]:
            r: Dict[str, Any] = {"global": {}, "indicators": {}}
            agent = load_agent("macro", "MacroAgent") if agent_enabled("macro") else None
            if not agent:
                return r
            out_g = call_agent(agent, timeframe=None)
            if isinstance(out_g, dict):
                if bool(out_g.get("block")):
                    r["indicators"]["MACRO_BLOCK"] = 1.0
                s = _norm(out_g.get("signal"))
                if s:
                    r["global"]["fundamental"] = s
            return r

        # ================================================================
        # FIX 2026-03-06: Exécution séquentielle des agents MT5 + parallèle API
        # L'API MT5 COM est mono-thread → paralléliser cause des embouteillages
        # ================================================================

        # FIX 2026-03-09: Filtrer les agents désactivés AVANT de les lancer
        # Évite de gaspiller 45s de timeout par agent désactivé
        # Agents qui utilisent MT5 (copy_rates) — doivent tourner séquentiellement
        mt5_agents = [
            (n, fn) for n, fn in [
                ("technical", _run_technical),
                ("scalping", _run_scalping),
                ("swing", _run_swing),
                ("structure", _run_structure),
            ] if agent_enabled(n)
        ]

        # Agents qui utilisent des API externes (HTTP) — peuvent tourner en parallèle
        api_agents = [
            (n, fn) for n, fn in [
                ("whale", _run_whale),
                ("news", _run_news),
                ("sentiment", _run_sentiment),
                ("fundamental", _run_fundamental),
                ("macro", _run_macro),
            ] if agent_enabled(n)
        ]
        logger.debug(f"[AGENTS] {symbol}: MT5={[n for n,_ in mt5_agents]} API={[n for n,_ in api_agents]}")

        async def _run_with_timeout(name: str, fn):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(fn),
                    timeout=_AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(f"[AGENT] {name} timeout ({_AGENT_TIMEOUT}s) pour {self.symbol}")
                return None
            except Exception as e:
                logger.warning(f"[AGENT] {name} erreur pour {self.symbol}: {e}")
                return None

        # ================================================================
        # FIX 2026-03-09: Skip agents MT5 si le marché est fermé
        # Évite de monopoliser le sémaphore pendant 180s (4×45s timeout)
        # Les cryptos tradent 24/7, les forex/indices seulement en semaine
        # ================================================================
        _skip_mt5 = False
        if mt5_agents:
            try:
                _is_crypto = self.symbol.upper() in self._hf_crypto_symbols
                if not _is_crypto:
                    # FIX 2026-03-10 R6: Protéger l'appel COM avec le lock
                    async with _GLOBAL_MT5_SEMAPHORE:
                        _test_tick = await asyncio.to_thread(
                            self.mt5.get_tick, self.broker_symbol or self.symbol
                        )
                    if _test_tick is None:
                        _skip_mt5 = True
                        logger.info(f"[MARKET_CHECK] {symbol}: pas de tick MT5 (marché fermé?) → skip agents MT5")
            except Exception as _mc_err:
                logger.debug(f"[MARKET_CHECK] {symbol}: erreur vérification: {_mc_err}")

        if _skip_mt5:
            mt5_results = [None] * len(mt5_agents)
        else:
            # ================================================================
            # FIX 2026-03-08: Verrou global — un seul orchestrateur accède au COM à la fois
            # ================================================================
            async with _GLOBAL_MT5_SEMAPHORE:
                # 1) Agents MT5 séquentiellement (évite saturation COM)
                mt5_results = []
                for name, fn in mt5_agents:
                    result = await _run_with_timeout(name, fn)
                    mt5_results.append(result)

                # FIX 2026-03-10: Détection freeze MT5 — vérifier les VRAIS résultats
                # Les agents retournent {"per_tf": {...}, "global": {...}, ...} — PAS de clé "score"
                # Un agent qui a échoué retourne soit None, soit un dict avec per_tf/global vides
                def _agent_result_empty(r) -> bool:
                    if r is None:
                        return True
                    if not isinstance(r, dict):
                        return True
                    ptf = r.get("per_tf") or {}
                    gs = r.get("global") or {}
                    smc = r.get("smc_tf") or {}
                    return not ptf and not gs and not smc

                _mt5_all_failed = all(
                    _agent_result_empty(r) for r in mt5_results
                )
                if _mt5_all_failed and len(mt5_results) >= 2:
                    logger.warning(f"[MT5_HEALTH] {self.symbol} — Tous les agents MT5 ont retourné des résultats vides, tentative reconnexion COM")
                    try:
                        from utils.mt5_client import MT5Client as _MC
                        _MC.shutdown_if_needed()
                        await asyncio.sleep(3)
                        _MC.initialize_if_needed(force=True)
                        logger.info(f"[MT5_HEALTH] {self.symbol} — Reconnexion MT5 réussie")
                    except Exception as _re:
                        logger.error(f"[MT5_HEALTH] {self.symbol} — Reconnexion échouée: {_re}")

        # 2) Agents API en parallèle HORS du sémaphore (pas de contrainte mono-thread)
        async def _run_api_with_timeout(name: str, fn):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(fn),
                    timeout=_API_AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(f"[AGENT] {name} API timeout ({_API_AGENT_TIMEOUT}s) pour {self.symbol}")
                return None
            except Exception as e:
                logger.warning(f"[AGENT] {name} API erreur pour {self.symbol}: {e}")
                return None

        api_results = await asyncio.gather(
            *[_run_api_with_timeout(name, fn) for name, fn in api_agents],
            return_exceptions=True,
        )

        # Fusionner les résultats dans l'ordre original
        agent_tasks = mt5_agents + api_agents
        results = mt5_results + list(api_results)

        # ================================================================
        # Fusion des résultats dans les structures existantes
        # ================================================================
        agent_names = [name for name, _ in agent_tasks]
        for i, name in enumerate(agent_names):
            res = results[i]
            if isinstance(res, BaseException):
                logger.warning(f"[AGENT] {name} exception gather pour {self.symbol}: {res}")
                continue
            if res is None:
                continue

            # per_tf signals
            ptf = res.get("per_tf") or {}
            if ptf:
                if name == "whale":
                    per_tf_signals.setdefault("whale", {}).update(ptf)
                elif name in per_tf_signals:
                    per_tf_signals[name].update(ptf)

            # smc per_tf (structure only)
            smc_tf = res.get("smc_tf") or {}
            if smc_tf:
                per_tf_signals.setdefault("smc", {}).update(smc_tf)

            # global signals
            gs = res.get("global") or {}
            global_signals.update(gs)

            # indicators
            ind = res.get("indicators") or {}
            indicators.update(ind)

            # details → typed buckets
            details = res.get("details") or {}
            if name == "technical":
                tech_details.update(details)
            elif name == "scalping":
                scalp_details.update(details)
            elif name == "swing":
                swing_details.update(details)
            elif name == "structure":
                structure_details.update(details)
            elif name == "whale":
                whale_details.update(details)

            # market context
            mkt = res.get("market") or {}
            for mk, mv in mkt.items():
                if isinstance(mv, dict):
                    market.setdefault(mk, {}).update(mv)
                else:
                    market[mk] = mv

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

        # FIX 2026-02-20: agent_weights appliqués dans per_tf (étape 3.2)
        _agent_w = dict(getattr(self, "agent_weights", {}) or {})

        # FIX 2026-02-20: Poids dynamiques par régime (étape 5.2)
        # TRENDING: swing*1.3, scalping*0.7
        # RANGING: structure*1.3, swing*0.7
        # VOLATILE: scalping*0.5, structure*1.2
        _regime_label = str(getattr(self, "_current_regime", "") or "").lower()
        _regime_mults: Dict[str, Dict[str, float]] = {
            "trending_up":   {"swing": 1.3, "scalping": 0.7, "structure": 1.0, "news": 0.8},
            "trending_down": {"swing": 1.3, "scalping": 0.7, "structure": 1.0, "news": 0.8},
            "ranging":       {"swing": 0.7, "scalping": 1.0, "structure": 1.3, "news": 0.8},
            "volatile":      {"swing": 0.9, "scalping": 0.5, "structure": 1.2, "news": 0.6},
            "quiet":         {"swing": 0.5, "scalping": 0.3, "structure": 0.5, "news": 0.3},
        }
        if _regime_label in _regime_mults:
            _rm = _regime_mults[_regime_label]
            for _rk, _rv in _rm.items():
                if _rk in _agent_w:
                    _agent_w[_rk] = float(_agent_w[_rk]) * _rv

        # FIX 2026-02-20: tracking direction par agent pour pénalité dispersion (étape 3.3)
        _agent_dirs: list = []  # list of ("LONG"|"SHORT"|"NEUTRAL")

        for agent_name, tf_map in per_tf_signals.items():
            agent_weight = float(_agent_w.get(agent_name, 1.0))
            longs = sum(w(tf) for tf, sig in tf_map.items() if _norm(sig) == "LONG")
            shorts = sum(w(tf) for tf, sig in tf_map.items() if _norm(sig) == "SHORT")
            total_weight = longs + shorts
            if longs > shorts:
                score_long += (longs - shorts) * agent_weight
                dispersion = (longs - shorts) / max(total_weight, 1e-6)
                if dispersion >= self.min_confluence_dispersion:
                    confluence += float(self.confluence_weights.get(agent_name, 1.0))
                _agent_dirs.append("LONG")
            elif shorts > longs:
                score_short += (shorts - longs) * agent_weight
                dispersion = (shorts - longs) / max(total_weight, 1e-6)
                if dispersion >= self.min_confluence_dispersion:
                    confluence += float(self.confluence_weights.get(agent_name, 1.0))
                _agent_dirs.append("SHORT")
            else:
                _agent_dirs.append("NEUTRAL")

        # FIX 2026-02-20: Poids dynamiques appliqués aux global signals (étape 5.2)
        _eff_w_news = self.w_news * _regime_mults.get(_regime_label, {}).get("news", 1.0)
        _eff_w_swing = self.w_swing * _regime_mults.get(_regime_label, {}).get("swing", 1.0)
        _eff_w_scalp = self.w_scalp * _regime_mults.get(_regime_label, {}).get("scalping", 1.0)
        _eff_w_structure = self.w_structure * _regime_mults.get(_regime_label, {}).get("structure", 1.0)

        news_dir = _norm(global_signals.get("news") if global_signals else None)
        if news_dir == "LONG":
            score_long += _eff_w_news; confluence += 1
            _agent_dirs.append("LONG")
        elif news_dir == "SHORT":
            score_short += _eff_w_news; confluence += 1
            _agent_dirs.append("SHORT")

        swing_dir = _norm(global_signals.get("swing") if global_signals else None)
        if swing_dir == "LONG":
            score_long += _eff_w_swing
            _agent_dirs.append("LONG")
        elif swing_dir == "SHORT":
            score_short += _eff_w_swing
            _agent_dirs.append("SHORT")

        scalping_dir = _norm(global_signals.get("scalping") if global_signals else None)
        if scalping_dir == "LONG":
            score_long += _eff_w_scalp
            _agent_dirs.append("LONG")
        elif scalping_dir == "SHORT":
            score_short += _eff_w_scalp
            _agent_dirs.append("SHORT")

        structure_dir = _norm(global_signals.get("structure") if global_signals else None)
        if structure_dir == "LONG":
            score_long += _eff_w_structure
            _agent_dirs.append("LONG")
        elif structure_dir == "SHORT":
            score_short += _eff_w_structure
            _agent_dirs.append("SHORT")

        direction = "LONG" if score_long > score_short else ("SHORT" if score_short > score_long else "")
        score_agr = max(score_long, score_short)

        # FIX 2026-03-08: Diagnostic logging — scores individuels par agent
        _per_agent_detail = []
        for _aname, _atf_map in per_tf_signals.items():
            _al = sum(w(tf) for tf, sig in _atf_map.items() if _norm(sig) == "LONG")
            _as = sum(w(tf) for tf, sig in _atf_map.items() if _norm(sig) == "SHORT")
            _aw = float(_agent_w.get(_aname, 1.0))
            _net = round((_al - _as) * _aw, 2)
            _per_agent_detail.append(f"{_aname}={_net:+.2f}")
        _globals_detail = []
        for _gk, _gv in (global_signals or {}).items():
            _gn = _norm(_gv)
            if _gn in ("LONG", "SHORT"):
                _globals_detail.append(f"{_gk}={_gn}")
        logger.info(
            f"[SCORE_DIAG] {self.symbol}: dir={direction} score_L={score_long:.2f} score_S={score_short:.2f} "
            f"conf={confluence:.1f} regime={_regime_label} "
            f"agents=[{', '.join(_per_agent_detail)}] "
            f"globals=[{', '.join(_globals_detail)}]"
        )

        # FIX 2026-02-20: Pénalité de dispersion (config: orchestrator.hard_filters.disagree_*)
        details: Dict[str, Any] = {}
        if _agent_dirs and direction in ("LONG", "SHORT"):
            _total_agents = len(_agent_dirs)
            _disagree = sum(1 for d in _agent_dirs if d not in (direction, "NEUTRAL"))
            _disagree_pct = _disagree / _total_agents if _total_agents > 0 else 0.0
            if _disagree_pct > self._hf_disagree_block_pct:
                score_agr -= 1.0
                details["dispersion_penalty"] = -1.0
                details["disagree_pct"] = round(_disagree_pct, 2)
            elif _disagree_pct > self._hf_disagree_penalty_pct:
                score_agr -= 0.5
                details["dispersion_penalty"] = -0.5
                details["disagree_pct"] = round(_disagree_pct, 2)

        # FIX 2026-02-24: Cap confluence relevé 5.0→8.0 (le HARD_MIN est à 5, cap=5 rendait le filtre binaire)
        confluence = min(confluence, 8.0)

        return direction, float(score_agr), float(confluence), details
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
    def _nightly_backtest_and_optimize(self):
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
            self._invalidate_agent_cache()
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

            # FIX 2026-03-10: Acquérir le lock MT5 pour éviter le deadlock COM
            # _sync_history_job tourne dans un thread APScheduler, pas dans l'event loop
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=1)  # Dernier jour seulement pour les syncs fréquentes
            with _GLOBAL_MT5_SEMAPHORE:
                deals = _mt5.history_deals_get(start, end) or []

            if not deals:
                return

            os.makedirs("data", exist_ok=True)
            # FIX 2026-07-30 (P5): historique des deals cloisonne par compte.
            from utils.account_scope import chemin_donnees as _chemin_donnees
            path = str(_chemin_donnees("deals_history.csv"))

            # FIX 2026-02-23: Déclaration fields avant lecture (Directive 2)
            fields = ["time", "symbol", "type", "entry", "volume", "price", "profit",
                      "commission", "swap", "magic", "comment", "position_id", "order"]

            # FIX 2026-02-23: Raw parsing au lieu de DictReader (le fichier peut ne pas avoir de header)
            existing_ids = set()
            has_header = False
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for raw_line in f:
                            line = raw_line.strip()
                            if not line:
                                continue
                            if line.startswith("time,"):
                                has_header = True
                                continue
                            parts = line.split(",")
                            if len(parts) >= 13:
                                key = f"{parts[0]}_{parts[11]}_{parts[12]}"
                                existing_ids.add(key)
                except Exception:
                    pass

            # FIX 2026-02-23: Injecter header si fichier existant sans header
            if os.path.exists(path) and os.path.getsize(path) > 0 and not has_header:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(",".join(fields) + "\n")
                        f.write(content)
                    logger.info("[SYNC] Header CSV injecté dans deals_history.csv")
                except Exception as _hdr_err:
                    logger.debug(f"[SYNC] Erreur injection header: {_hdr_err}")

            # FIX 2026-02-23: write_header si fichier inexistant OU vide
            write_header = not os.path.exists(path) or os.path.getsize(path) == 0

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
    def _auto_optimize_job(self):
        """
        1) sync MT5 deals -> data/deals_history.csv
        2) run tuner -> proposals/profiles_patch.yaml
        3) si patch pour ce symbole: clamp + write to config/overrides.yaml + reload
        + sécurité : ne rien faire s'il y a des positions ouvertes sur ce symbole
        """
        try:
            # sécurité: ne pas modifier si position ouverte sur ce symbole
            try:
                # FIX 2026-03-10 R6: Protéger l'appel MT5 avec le lock hybride
                with _GLOBAL_MT5_SEMAPHORE:
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
        # FIX 2026-07-29 (P5): la condition exigeait aussi auto_execute=False, alors que
        # des boutons sont envoyés dès que telegram_validation=True, quel que soit
        # auto_execute. L'écouteur ne démarrait donc pas dans une configuration où des
        # boutons partaient quand même. Condition alignée sur celle d'envoi.
        needs_cb = any(getattr(o, "use_telegram_validation", False) for o in orchs)
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
        # 1) Charger .env à la racine (sans écraser les env existants)
        load_dotenv_env(path=".env", extra_paths=(), overwrite=False)
        # 2) Valider la présence des secrets essentiels (on tolère l'absence en mode dry)
        try:
            get_required("MT5_ACCOUNT","MT5_PASSWORD","MT5_SERVER","TELEGRAM_BOT_TOKEN","TELEGRAM_CHAT_ID")
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
