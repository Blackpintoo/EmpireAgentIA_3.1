# PROMPT CLAUDE CODE — Fix Final : TOUS les appels MT5 non protégés (Round 6)

## Contexte

**Prérequis** : Le Round 5 (PROMPT_CLAUDE_CODE_FIX_HYBRID_LOCK.md) DOIT être appliqué AVANT celui-ci. Il installe le lock hybride `_MT5Lock` et protège le PM + sync_history.

Après audit COMPLET de `orchestrator.py` (5349 lignes), **11 appels MT5 supplémentaires** ont été identifiés sans aucune protection par le lock. Ce Round 6 les corrige TOUS.

---

## Catégorie A — Appels sync DIRECTEMENT dans l'event loop (CRITIQUES)

Ces appels bloquent l'event loop ET peuvent provoquer un deadlock COM.

### FIX 1 — `_current_position_stats` (ligne ~2884)

**Fichier** : `orchestrator/orchestrator.py`

Chercher dans `_run_agents_and_decide` :
```python
            count, volume, net = self._current_position_stats()
```

Remplacer par :
```python
            # FIX 2026-03-10 R6: Appel MT5 sync → to_thread + lock (event loop non bloqué)
            async with _GLOBAL_MT5_SEMAPHORE:
                count, volume, net = await asyncio.to_thread(self._current_position_stats)
```

### FIX 2+3 — `_today_pnl_currency` + `_current_losing_streak` (lignes ~2908-2910)

Chercher le bloc :
```python
        pnl_today_ccy = self._today_pnl_currency()                      # P/L réalisé aujourd'hui (ce symbole)
        daily_loss_pct = pnl_today_ccy / max(equity_start, 1e-9)        # ex: -0.012 = -1.2%
        consec_losses = int(self._current_losing_streak())              # série de pertes consécutives
```

Remplacer par :
```python
        # FIX 2026-03-10 R6: Appels MT5 sync → to_thread + lock (groupés pour minimiser les locks)
        async with _GLOBAL_MT5_SEMAPHORE:
            pnl_today_ccy = await asyncio.to_thread(self._today_pnl_currency)  # P/L réalisé (ce symbole)
            consec_losses = int(await asyncio.to_thread(self._current_losing_streak))  # série de pertes
        daily_loss_pct = pnl_today_ccy / max(equity_start, 1e-9)        # ex: -0.012 = -1.2% (pas d'appel MT5)
```

### FIX 4 — `_weekend_guard_blocked` → `close_positions` (ligne ~3302)

`_weekend_guard_blocked()` est sync et peut appeler `self.mt5.close_positions()` (via `_flatten_positions_for_weekend`). Appelé directement dans l'event loop.

Chercher :
```python
            if self._weekend_guard_blocked():
                reasons.append("forex_weekend_guard")
                decision_notes.append("forex_weekend_guard")
```

Remplacer par :
```python
            # FIX 2026-03-10 R6: weekend guard fait des appels MT5 (close_positions) → to_thread + lock
            async with _GLOBAL_MT5_SEMAPHORE:
                _wg_blocked = await asyncio.to_thread(self._weekend_guard_blocked)
            if _wg_blocked:
                reasons.append("forex_weekend_guard")
                decision_notes.append("forex_weekend_guard")
```

---

## Catégorie B — Appels `asyncio.to_thread` SANS le lock (deadlock COM possible)

Ces appels utilisent bien `asyncio.to_thread` (ne bloquent pas l'event loop) mais ne prennent PAS le lock → conflit COM possible avec d'autres threads.

### FIX 5 — `_get_last_price` dans `_gather_agent_signals` (ligne ~4017)

`_get_last_price()` fait jusqu'à 8 appels MT5 internes (ensure_symbol, get_tick ×3, get_rates ×5).

Chercher :
```python
        # FIX 2026-03-09: Wrapper dans asyncio.to_thread pour ne pas bloquer le event loop
        price = await asyncio.to_thread(self._get_last_price, symbol)
```

Remplacer par :
```python
        # FIX 2026-03-10 R6: _get_last_price fait ~8 appels MT5 → protéger avec le lock
        async with _GLOBAL_MT5_SEMAPHORE:
            price = await asyncio.to_thread(self._get_last_price, symbol)
```

### FIX 6 — `get_account_info` dans `_gather_agent_signals` (ligne ~4021)

Chercher :
```python
            if hasattr(self.mt5, "get_account_info"):
                ai = await asyncio.to_thread(self.mt5.get_account_info)
```

Remplacer par :
```python
            if hasattr(self.mt5, "get_account_info"):
                # FIX 2026-03-10 R6: Protéger l'appel COM avec le lock
                async with _GLOBAL_MT5_SEMAPHORE:
                    ai = await asyncio.to_thread(self.mt5.get_account_info)
```

### FIX 7 — `get_tick` market check dans `_gather_agent_signals` (ligne ~4470)

Chercher :
```python
                    _test_tick = await asyncio.to_thread(
                        self.mt5.get_tick, self.broker_symbol or self.symbol
                    )
```

Remplacer par :
```python
                    # FIX 2026-03-10 R6: Protéger l'appel COM avec le lock
                    async with _GLOBAL_MT5_SEMAPHORE:
                        _test_tick = await asyncio.to_thread(
                            self.mt5.get_tick, self.broker_symbol or self.symbol
                        )
```

### FIX 8 — `get_last_price` fallback dans `_run_agents_and_decide` (ligne ~3142)

Chercher :
```python
            if price is None:
                try:
                    price = await asyncio.to_thread(self.mt5.get_last_price, symbol, "BUY")
```

Remplacer par :
```python
            if price is None:
                try:
                    # FIX 2026-03-10 R6: Protéger l'appel COM avec le lock
                    async with _GLOBAL_MT5_SEMAPHORE:
                        price = await asyncio.to_thread(self.mt5.get_last_price, symbol, "BUY")
```

---

## Catégorie C — Jobs `async def` dans BackgroundScheduler (ne s'exécutent JAMAIS)

`BackgroundScheduler` exécute ses jobs dans des threads normaux. Quand il appelle une `async def`, il obtient un objet coroutine jamais awaité → le job ne s'exécute **jamais** silencieusement.

### FIX 9 — `_send_status_report` : `async def` → `def` + lock MT5

**Fichier** : `orchestrator/orchestrator.py`

**Étape 9a** — Chercher (ligne ~1386) :
```python
    async def _send_status_report(self):
```

Remplacer par :
```python
    def _send_status_report(self):
```

**Étape 9b** — Protéger `account_info` dans cette méthode. Chercher (ligne ~1393) :
```python
            ai = getattr(self.mt5, "get_account_info", lambda: None)()
```

Remplacer par :
```python
            # FIX 2026-03-10 R6: Protéger l'appel MT5 avec le lock hybride (thread scheduler)
            with _GLOBAL_MT5_SEMAPHORE:
                ai = getattr(self.mt5, "get_account_info", lambda: None)()
```

**Étape 9c** — Protéger `positions_get` dans cette méthode. Chercher (ligne ~1400) :
```python
            try:
                poss_raw = _mt5.positions_get(symbol=self.broker_symbol) or []
```

Remplacer par :
```python
            try:
                # FIX 2026-03-10 R6: Protéger l'appel MT5 avec le lock hybride
                with _GLOBAL_MT5_SEMAPHORE:
                    poss_raw = _mt5.positions_get(symbol=self.broker_symbol) or []
```

### FIX 10 — `_auto_optimize_job` : `async def` → `def` + lock MT5

**Étape 10a** — Chercher (ligne ~5191) :
```python
    async def _auto_optimize_job(self):
```

Remplacer par :
```python
    def _auto_optimize_job(self):
```

**Étape 10b** — Protéger `positions_get` dans cette méthode. Chercher (ligne ~5201) :
```python
                poss = _mt5.positions_get(symbol=self.broker_symbol) or []
```

Remplacer par :
```python
                # FIX 2026-03-10 R6: Protéger l'appel MT5 avec le lock hybride
                with _GLOBAL_MT5_SEMAPHORE:
                    poss = _mt5.positions_get(symbol=self.broker_symbol) or []
```

### FIX 11 — `_nightly_backtest_and_optimize` : `async def` → `def`

Chercher (ligne ~5062) :
```python
    async def _nightly_backtest_and_optimize(self):
```

Remplacer par :
```python
    def _nightly_backtest_and_optimize(self):
```

**C'est tout.** Pas d'appel `_mt5` direct, pas de `await` interne.

---

## Résumé des 11 modifications

| Fix | Lignes | Catégorie | Modification |
|-----|--------|-----------|-------------|
| 1 | ~2884 | A - CRITIQUE | `_current_position_stats()` → `to_thread` + lock |
| 2+3 | ~2908-2910 | A - CRITIQUE | `_today_pnl_currency()` + `_current_losing_streak()` → `to_thread` + lock (groupés) |
| 4 | ~3302 | A - CRITIQUE | `_weekend_guard_blocked()` → `to_thread` + lock |
| 5 | ~4017 | B - deadlock | `_get_last_price` + lock |
| 6 | ~4021 | B - deadlock | `get_account_info` + lock |
| 7 | ~4470 | B - deadlock | `get_tick` market check + lock |
| 8 | ~3142 | B - deadlock | `get_last_price` fallback + lock |
| 9 | ~1386 | C - fantôme | `_send_status_report` : `async def` → `def` + 2 locks MT5 |
| 10 | ~5191 | C - fantôme | `_auto_optimize_job` : `async def` → `def` + lock MT5 |
| 11 | ~5062 | C - fantôme | `_nightly_backtest_and_optimize` : `async def` → `def` |

---

## Inventaire COMPLET de TOUS les accès MT5 après Round 4 + Round 5 + Round 6

### Mode `async with _GLOBAL_MT5_SEMAPHORE:` (coroutines dans event loop)

| # | Ligne | Appel | Round |
|---|-------|-------|-------|
| 1 | ~2884 | `_current_position_stats` → `positions_get` | **R6 FIX 1** |
| 2 | ~2908 | `_today_pnl_currency` → `history_deals_get` | **R6 FIX 2** |
| 3 | ~2910 | `_current_losing_streak` → `history_deals_get` | **R6 FIX 3** |
| 4 | ~2937 | `positions_get` (daily loss floating) | R4 FIX 1 |
| 5 | ~3112 | `_eod_close_sync` (positions_get + order_send) | R4 FIX 2 |
| 6 | ~3142 | `get_last_price` fallback | **R6 FIX 8** |
| 7 | ~3302 | `_weekend_guard_blocked` → `close_positions` | **R6 FIX 4** |
| 8 | ~3374 | `_compute_atr` (copy_rates) | R4 FIX 3 |
| 9 | ~3403 | `_min_stop_distance_points` | R4 FIX 4 |
| 10 | ~3581 | `_count_open_crypto_positions` | R4 FIX 5 |
| 11 | ~3598 | `_crypto_bucket_risk_used` | R4 FIX 5 |
| 12 | ~3608 | `account_info` (crypto equity) | R4 FIX 6 |
| 13 | ~3711 | `execute_trade` (4+ appels MT5 internes) | R4 FIX 7 |
| 14 | ~4017 | `_get_last_price` (~8 appels MT5) | **R6 FIX 5** |
| 15 | ~4021 | `get_account_info` | **R6 FIX 6** |
| 16 | ~4470 | `get_tick` (market check) | **R6 FIX 7** |
| 17 | ~4485 | Agents MT5 (technical, scalping, swing, structure) | Existant |

### Mode `with _GLOBAL_MT5_SEMAPHORE:` (threads BackgroundScheduler)

| # | Job | Appels MT5 | Round |
|---|-----|-----------|-------|
| 18 | PM `manage_open_positions` | positions_get, order_send, history_deals_get, copy_rates, symbol_info_tick | R5 FIX 2 |
| 19 | `_sync_history_job` | `history_deals_get` | R5 FIX 3 |
| 20 | `_send_status_report` | `get_account_info`, `positions_get` | **R6 FIX 9** |
| 21 | `_auto_optimize_job` | `positions_get` | **R6 FIX 10** |

### Appels MT5 dans `__init__` (séquentiels, pas de concurrence)

| # | Ligne | Appel | Protégé ? |
|---|-------|-------|-----------|
| 22 | ~714 | `resolve_symbol_name` | N/A (init séquentiel) |
| 23 | ~715 | `ensure_symbol` | N/A (init séquentiel) |

**Total : 23 points d'accès MT5. TOUS protégés sauf les 2 d'initialisation (qui sont séquentiels par design).**

---

## Ce qui ne change PAS

- Les 9 `async with _GLOBAL_MT5_SEMAPHORE:` du Round 4 → inchangés
- Le lock hybride `_MT5Lock` du Round 5 → inchangé
- Le PM et `_sync_history_job` protégés par le Round 5 → inchangés
- `_run_agents_and_decide_sync` → inchangé
- Les méthodes sync (`_today_pnl_currency`, etc.) → inchangées en interne, seulement leurs appels dans l'event loop sont wrappés

## Impact attendu

### Catégorie A (FIX 1-4) :
- **Plus de blocage event loop** : les appels MT5 synchrones déplacés dans des threads
- **Plus de conflit COM** : tous les threads acquièrent le lock avant d'accéder à MT5

### Catégorie B (FIX 5-8) :
- **Plus de deadlock COM** entre `_gather_agent_signals` et les agents d'un autre orchestrateur
- **Plus de deadlock COM** entre le fallback prix et le PM

### Catégorie C (FIX 9-11) :
- **Rapports Telegram fonctionnent** : `_send_status_report` toutes les 2h
- **Auto-optimisation fonctionne** : `_auto_optimize_job` à 21:05
- **Optimisation Optuna fonctionne** : `_nightly_backtest_and_optimize`

### Performance :
- Latence légèrement accrue (~1-5s) quand un orchestrateur attend le lock pendant qu'un autre utilise MT5
- **Acceptable** vs les deadlocks actuels qui paralysent TOUT pendant des heures

## Ordre d'application

1. **D'ABORD** appliquer le Round 5 (`PROMPT_CLAUDE_CODE_FIX_HYBRID_LOCK.md`) — installe le lock hybride `_MT5Lock`
2. **ENSUITE** appliquer ce Round 6 — utilise le lock hybride pour protéger les 11 appels restants

## Vérification après modification

1. `python -m py_compile orchestrator/orchestrator.py` → doit passer
2. Redémarrer via `START_EMPIRE.bat`
3. Vérifier dans les logs après **30 minutes** :
   - PM_DIAG tourne toutes les 20s (cycles réguliers, pas de freeze)
   - Les cycles d'analyse tournent toutes les ~120s SANS interruption
   - `[REPORT]` apparaît (preuve que `_send_status_report` fonctionne enfin)
   - HARD_FILTER PASS suivi de `[TRADE]` ou `[EXECUTE]` → **trade exécuté !**
   - Pas de freeze silencieux (tous les types de logs coexistent)
   - Aucun deadlock COM (l'event loop ne gèle plus)
