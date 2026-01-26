import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from utils.config import get_symbol_profile, get_enabled_symbols
from utils.logger import logger
from utils.mt5_client import MT5Client
from utils.performance_tracker import PerformancePoint, default_tracker
from utils.risk_manager import RiskManager

class Orchestrator:
    def __init__(self, symbol: str, telegram_client=None):
        self.symbol = symbol
        self.telegram_client = telegram_client  # optional Telegram client
        self.profile: Dict[str, Any] = get_symbol_profile(symbol)
        self.ori_cfg: Dict[str, Any] = self.profile.get("orchestrator", {})
        self.votes_required: int = int(self.ori_cfg.get("votes_required", 2))

        mtf = self.ori_cfg.get("multi_timeframes", {}) or {}
        self.mtf_enabled: bool = bool(mtf.get("enabled", True))
        self.tfs: List[str] = list(mtf.get("tfs", ["H1", "M15", "M5", "M1"]))
        self.tf_weights: Dict[str, float] = dict(mtf.get("tf_weights", {}))

        self.timeframes_cfg: Dict[str, Any] = self.ori_cfg.get("timeframes", {})
        self.scheduler = AsyncIOScheduler()
        self.risk = RiskManager(symbol)
        self.tracker = default_tracker()
        self._last_proposal: Optional[Dict[str, Any]] = None
        MT5Client.initialize_if_needed()
        self.mt5 = MT5Client()
        self.mt5.ensure_symbol(self.symbol)

        logger.info(f"[ORCH] {self.symbol} votes_required={self.votes_required} "
                    f"tfs={self.tfs} weights={self.tf_weights}")

    async def start(self):
        interval_seconds = int(self.timeframes_cfg.get("orchestrator", 60))
        job_id = f"orch_{self.symbol}"
        # Avoid duplicate jobs on hot reload
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass
        self.scheduler.add_job(self._orchestrate_once, "interval", seconds=interval_seconds, id=job_id)
        self.scheduler.start()
        logger.info(f"[ORCH] {self.symbol} scheduler démarré ({interval_seconds}s).")
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            self.scheduler.shutdown(wait=False)

    async def _orchestrate_once(self):
        try:
            proposal = self._build_proposal()
            if not proposal:
                logger.info("[ORCH] %s: aucun signal exploitable.", self.symbol)
                return
            logger.info(
                "[ORCH] %s vote=%s (signals=%s)",
                self.symbol,
                f"{float(proposal.get('weighted_vote', 0.0)):.3f}",
                str(len(proposal.get('signals') or [])),
            )
            self._last_proposal = proposal
            threshold = float(self.ori_cfg.get("auto_execute_threshold", 1.5))
            executed = proposal["weighted_vote"] >= threshold
            outcome = proposal["weighted_vote"] if executed else None
            self._record_performance_stats(
                proposal,
                executed=executed,
                outcome=outcome,
                retcode=0 if executed else None,
            )
        except Exception as e:
            logger.exception(f"[ORCH] Erreur {self.symbol}: {e}")

    def _collect_signals(self) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []
        base_score = float(self.ori_cfg.get("base_score", 0.5))
        regime = str(self.ori_cfg.get("regime", "default"))
        for tf in self.tfs:
            weight = float(self.tf_weights.get(tf, 1.0))
            score = base_score + 0.1 * weight
            signals.append(
                {
                    "agent": f"synthetic_{tf.lower()}",
                    "timeframe": tf,
                    "score": score,
                    "regime": regime,
                }
            )
        return signals

    def _build_proposal(self) -> Optional[Dict[str, Any]]:
        signals = self._collect_signals()
        if not signals:
            return None
        regime = str(self.ori_cfg.get("regime", "default"))
        weighted_vote, enriched = self.tracker.compute_weighted_vote(
            self.symbol,
            signals,
            regime=regime,
        )
        return {
            "symbol": self.symbol,
            "regime": regime,
            "weighted_vote": float(weighted_vote),
            "signals": enriched,
            "rr": float(weighted_vote),
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        }

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
        regime = proposal.get("regime") or "default"
        metadata = {
            "weighted_vote": proposal.get("weighted_vote"),
            "retcode": retcode,
            "executed": executed,
        }
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
        snapshot = self.tracker.snapshot(top_n=1)
        if snapshot:
            top = snapshot[0]
            logger.info("[TRACKER] top %s/%s bucket=%s weight=%s count=%s",
                        top['symbol'], top['agent'], top['bucket'], f"{float(top.get('weight', 0.0)):.2f}", str(int(top.get('count', 0))))

async def run_for_symbols(symbols: List[str]):
    tasks = [Orchestrator(sym).start() for sym in symbols]
    await asyncio.gather(*tasks)
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", help="Liste des symboles à lancer")
    args = parser.parse_args()

    syms = args.symbols if args.symbols else get_enabled_symbols()
    if not syms:
        raise SystemExit("Aucun symbole à lancer. Renseignez enabled_symbols dans profiles.yaml ou utilisez --symbols.")
    logger.info(f"Lancement Orchestrator en parallèle pour: {syms}")
    asyncio.run(run_for_symbols(syms))




