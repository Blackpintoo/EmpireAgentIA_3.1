import datetime as dt
from typing import List, Optional, Dict, Any

from utils.logger import logger
from utils.data_sources import fetch_fxstreet_calendar
from agents.utils import merge_agent_params
from utils.telegram_client import send_telegram_message  # sync, optionnel


class FundamentalAgent:
    """
    Agent Fondamental — analyse un calendrier économique pour produire :
      - un signal (LONG/SHORT/WAIT) autour d'événements macro
      - un biais directionnel léger via bias()
      - une fenêtre de blackout de trading via trading_blackout()

    Intégration :
      - Orchestrateur appelle trading_blackout(datetime.utcnow()) pour couper les propositions si news "high impact" proche.
      - Orchestrateur peut aussi consulter bias(symbol, now) pour pondérer légèrement.
    """

    def __init__(self, symbol: str = "BTCUSD", asset_currency: str = "USD", cfg: Optional[dict] = None, params: Optional[dict] = None, api_client=None):
        self.symbol = symbol
        self.asset_currency = asset_currency
        self.cfg = cfg or {}
        self.api = api_client  # ex: utils.econ_api.EconCalendarClient(), sinon None -> fallback HTTP / simulation

        defaults = {
            # Source calendrier (fallback HTTP si api_client=None)
            "calendar_api_url": "https://calendar-api.fxstreet.com/events",
            "calendar_cache_ttl": 300,

            # Événements d'intérêt (par devise)
            "major_events": [
                "FOMC", "CPI", "NFP", "ECB", "employment", "inflation",
                "interest rate", "GDP", "PMI", "retail sales", "unemployment", "trade balance"
            ],
            "asset_event_map": {
                "USD": ["FOMC", "CPI", "NFP", "employment", "inflation", "interest rate", "GDP", "PMI", "retail sales"],
                "EUR": ["ECB", "inflation", "unemployment", "GDP", "PMI", "trade balance"],
                "GBP": ["BOE", "GDP", "CPI", "PMI", "employment"],
                "JPY": ["BOJ", "GDP", "CPI", "PMI"],
                "CHF": ["SNB", "GDP", "CPI"],
                # Vous pouvez étendre ici selon votre portefeuille
            },

            # Mappage "mieux/pire que prévu" -> biais
            "sens_map": {"better": "bullish", "worse": "bearish"},

            # Fenêtres & seuils
            "lookback_minutes": 180,     # ne garde que les événements dans cette fenêtre autour de now (avant/après)
            "wait_minutes": 30,          # si l'événement est dans les X prochaines minutes -> WAIT (pas de trade)
            "blackout_minutes": 30,      # trading_blackout autour des news high impact
            "only_high_impact": True,    # ne traite que 'high' (ou désactiver pour medium/low)
            "use_forecast_diff_pct": True,
            "diff_pct_threshold": 0.3,   # % |actual-forecast| / |forecast| * 100

            # Règles spécifiques
            "reverse_on_negative": True, # ex: CPI > prévu => bearish (risque resserrement)
            "notify_telegram": True,     # message récapitulatif (sync, non bloquant pour l’orchestrateur)
        }
        merged = merge_agent_params(self.symbol, "fundamental", defaults)
        if params:
            merged.update(params)
        self.params = merged
        logger.debug(f"[INIT] {self.__class__.__name__} params: {self.params}")

    # --------------------- Fetch calendrier ---------------------
    def _fetch_via_api_client(self, start: dt.datetime, end: dt.datetime) -> List[Dict[str, Any]]:
        """
        Si un client externe est fourni (utils.econ_api.EconCalendarClient), on l'utilise.
        Le client doit exposer events_between(start, end) -> List[Event-like dict]
        Chaque event doit fournir au minimum: event, impact, currency, time (iso), actual?, forecast?
        """
        if not self.api:
            return []
        try:
            events = self.api.events_between(start, end) or []
            # Normalisation minimale vers un dict compatible
            norm = []
            for ev in events:
                norm.append({
                    "event": ev.get("event") or ev.get("title") or "",
                    "impact": ev.get("impact", "").lower(),
                    "actual": ev.get("actual"),
                    "forecast": ev.get("forecast"),
                    "currency": ev.get("currency") or self.asset_currency,
                    "time": ev.get("time") or ev.get("datetime")  # ISO8601 attendu
                })
            return norm
        except Exception as e:
            logger.error(f"[FUNDAMENTAL] api_client events_between failed: {e}")
            return []

    def _fetch_via_http(self, start: dt.datetime, end: dt.datetime) -> List[Dict[str, Any]]:
        """
        Fallback HTTP via helper utilitaire (FXStreet JSON public).
        """
        url = self.params.get("calendar_api_url") or "https://calendar-api.fxstreet.com/events"
        importance = None
        if self.params.get("only_high_impact", True):
            importance = ["high"]
        ttl = float(self.params.get("calendar_cache_ttl", 300.0))
        try:
            events = fetch_fxstreet_calendar(
                start=start,
                end=end,
                importance=importance,
                base_url=url,
                ttl=ttl,
            )
        except Exception as e:
            logger.error(f"[FUNDAMENTAL] FXStreet helper failed: {e}")
            return []

        if not events:
            return []
        if not isinstance(events, list):
            logger.debug("[FUNDAMENTAL] FXStreet payload inattendu (ignore)")
            return []
        return events


    def fetch_calendar(self, horizon_minutes: int = 180) -> List[Dict[str, Any]]:
        """
        Récupère les événements économiques dans [now - horizon ; now + horizon].
        """
        now = dt.datetime.now(dt.timezone.utc)
        start = now - dt.timedelta(minutes=horizon_minutes)
        end = now + dt.timedelta(minutes=horizon_minutes)

        events = []
        # 1) Client externe si fourni
        events = self._fetch_via_api_client(start, end)
        # 2) Fallback HTTP
        if not events:
            events = self._fetch_via_http(start, end)

        logger.debug(f"[{self.__class__.__name__}] {len(events)} événement(s) récupéré(s)")
        return events or []

    # --------------------- Analyse ---------------------
    @staticmethod
    def _parse_iso_utc(s: str) -> Optional[dt.datetime]:
        if not s:
            return None
        try:
            s = s.replace("Z", "+00:00")
            return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc).replace(tzinfo=None)
        except Exception:
            try:
                return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=None)
            except Exception:
                return None

    def _event_relevant_for_currency(self, ev: Dict[str, Any]) -> bool:
        amap = self.params.get("asset_event_map", {}) or {}
        ccy = (ev.get("currency") or self.asset_currency)
        if ccy not in amap:
            return False
        if self.params.get("only_high_impact", True) and (ev.get("impact","").lower() != "high"):
            return False
        name = (ev.get("event") or "").upper()
        return name in set(amap.get(ccy, []))

    def _diff_pass_threshold(self, actual: Optional[float], forecast: Optional[float]) -> bool:
        if actual is None or forecast is None:
            return True  # si pas de forecast/actual, on laisse passer
        try:
            if not self.params.get("use_forecast_diff_pct", True):
                return True
            if forecast == 0:
                return True
            diff_pct = abs(float(actual) - float(forecast)) / abs(float(forecast)) * 100.0
            return diff_pct >= float(self.params.get("diff_pct_threshold", 0.3))
        except Exception:
            return True

    def analyze_event(self, ev: Dict[str, Any]) -> Optional[str]:
        """
        Retourne 'bullish' | 'bearish' ou None si non pertinent.
        Règles spécifiques (CPI, NFP, etc.) si reverse_on_negative=True.
        """
        if not self._event_relevant_for_currency(ev):
            return None

        actual = ev.get("actual")
        forecast = ev.get("forecast")
        if not self._diff_pass_threshold(actual, forecast):
            logger.debug("[FUND] Ignoré (diff en % < seuil).")
            return None

        try:
            # Décision "better/worse"
            if (actual is None) or (forecast is None):
                better = None
            else:
                diff = float(actual) - float(forecast)
                better = (diff > 0)

            sens_map = self.params.get("sens_map", {"better": "bullish", "worse": "bearish"})
            event_name = (ev.get("event") or "").lower()
            reverse = self.params.get("reverse_on_negative", True)

            if reverse:
                # Ex.: CPI plus élevé que prévu = inflation plus forte => bearish
                if event_name in ["cpi", "inflation"]:
                    return "bearish" if better else "bullish"
                # Ex.: emploi/NFP mieux que prévu => économie plus forte => bullish (USD)
                if event_name in ["nfp", "employment", "unemployment"]:
                    return "bullish" if better else "bearish"

            # Par défaut
            if better is None:
                return None
            return sens_map["better" if better else "worse"]
        except Exception as e:
            logger.error(f"[FUND] Erreur analyse événement: {e}")
            return None

    # --------------------- Biais & Blackout ---------------------
    def upcoming(self, now: Optional[dt.datetime] = None, horizon_min: int = 90) -> List[Dict[str, Any]]:
        now = now or dt.datetime.now(dt.timezone.utc)
        events = self.fetch_calendar(horizon_minutes=horizon_min)
        out = []
        for ev in events:
            t = self._parse_iso_utc(ev.get("time"))
            if not t:
                continue
            dt_min = (t - now).total_seconds() / 60.0
            if abs(dt_min) <= horizon_min:
                out.append({**ev, "_minutes_to": dt_min})
        return out

    def trading_blackout(self, now: Optional[dt.datetime] = None) -> bool:
        """
        True si un événement HIGH impact pertinent est dans la fenêtre ±blackout_minutes.
        Utilisé par l’orchestrateur pour bloquer la proposition de trade.
        """
        now = now or dt.datetime.now(dt.timezone.utc)
        blk = int(self.params.get("blackout_minutes", 30))
        for ev in self.upcoming(now, horizon_min=max(blk, int(self.params.get("lookback_minutes", 180)))):
            if not self._event_relevant_for_currency(ev):
                continue
            t = self._parse_iso_utc(ev.get("time"))
            if not t:
                continue
            if abs((t - now).total_seconds()) <= blk * 60:
                return True
        return False

    def bias(self, symbol: Optional[str] = None, now: Optional[dt.datetime] = None) -> float:
        """
        Biais directionnel léger [-1..+1] : -0.2 si news HIGH proche, sinon 0.
        (Vous pouvez raffiner en pondérant selon le type d'événement.)
        """
        try:
            return -0.2 if self.trading_blackout(now) else 0.0
        except Exception:
            return 0.0

    # --------------------- Signal ---------------------
    def generate_signal(self, bar: Optional[dict] = None) -> Optional[Dict[str, Any]]:
        """
        Retourne un dict de type :
          {"signal": "WAIT"|"LONG"|"SHORT", "event": {...}, "confidence": 0.6, "timeframe": "H1"}
        - WAIT si un événement pertinent arrive dans wait_minutes
        - LONG/SHORT sinon, en fonction du biais (bullish/bearish)
        - None si rien de pertinent
        """
        logger.debug(f"[DEBUG] generate_signal appelé dans {self.__class__.__name__}")
        now = dt.datetime.now(dt.timezone.utc)
        lookback = int(self.params.get("lookback_minutes", 180))
        wait_min = int(self.params.get("wait_minutes", 30))

        events = self.fetch_calendar(horizon_minutes=lookback)
        signals = []

        for ev in events:
            if not self._event_relevant_for_currency(ev):
                continue

            t = self._parse_iso_utc(ev.get("time"))
            if not t:
                logger.debug(f"[FUND] Date non parseable pour {ev}")
                continue

            minutes_to = (t - now).total_seconds() / 60.0
            if abs(minutes_to) > lookback:
                continue

            # Event imminent -> WAIT
            if 0 <= minutes_to <= wait_min:
                signals.append({"signal": "WAIT", "event": ev, "confidence": 0.7, "timeframe": "H1"})
                continue

            # Sinon : direction
            impact_dir = self.analyze_event(ev)
            if not impact_dir:
                continue
            signal = "LONG" if impact_dir == "bullish" else "SHORT"
            conf = 0.55 if impact_dir == "bullish" else 0.55  # neutre ; ajustez si besoin par type d'event
            signals.append({"signal": signal, "event": ev, "confidence": conf, "timeframe": "H1"})

        final = signals[-1] if signals else None
        logger.debug(f"[FUND] Signal final: {final}")

        # Notification Telegram (optionnelle, non bloquante côté Orchestrateur sync)
        if final and self.params.get("notify_telegram", True):
            try:
                ev = final["event"]
                msg = (
                    f"[FUND] {final['signal']} sur {self.symbol} — "
                    f"{ev.get('event','?')} ({ev.get('currency', self.asset_currency)}) "
                    f"Actuel: {ev.get('actual', '?')} / Prévu: {ev.get('forecast', '?')}"
                )
                send_telegram_message(msg)
            except Exception as e:
                logger.warning(f"[FUND] Telegram notify failed: {e}")

        return final

    def execute(self, *args, **kwargs):
        logger.debug(f"[DEBUG] execute appelé dans {self.__class__.__name__}")
        return self.generate_signal(*args, **kwargs)
