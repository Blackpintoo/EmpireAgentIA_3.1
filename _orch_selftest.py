import asyncio
from orchestrator.orchestrator import Orchestrator
from utils.mt5_client import MT5Client

class TestOrch(Orchestrator):
    async def _send_validation_proposal(self, msg, direction, price, sl, tp, lots):
        # bypass Telegram: on exécute tout de suite
        self._last_proposal = {
            "symbol": self.symbol,
            "side": direction,
            "entry": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "lots": float(lots),
        }
        print("→ Proposition forcée:", msg.replace("\\n"," | "))
        ok = await self.execute_trade(direction)
        print("→ Exécution:", ok)

    def _gather_agent_signals(self, symbol):
        # Fabrication d'un contexte "bullish" pour déclencher
        price = self.mt5.get_last_price(symbol, side="BUY") or 0.0
        atr   = self._compute_atr(symbol, "H1") or (abs(price) * 0.002)  # fallback 0.2%
        per_tf = {
            "technical": {"M15":"LONG","M5":"LONG","M1":"LONG"}
        }
        global_sig = {"news":"LONG","swing":"LONG","scalping":"LONG"}
        indicators = {"ATR_H1": atr}
        acc = self.mt5.get_account_info()
        equity = float(getattr(acc, "equity", 0.0)) if acc else None
        market = {"price": price, "equity": equity}
        return per_tf, global_sig, indicators, market

async def main():
    o = TestOrch("BTCUSD")   # tu peux mettre "LINKUSD"
    await o._run_agents_and_decide()

asyncio.run(main())
