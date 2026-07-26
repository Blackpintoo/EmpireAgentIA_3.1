# PROMPT CLAUDE CODE — Fix COM Deadlock Inter-Thread (Round 4)

## Contexte

Après les fixes du Round 3 (MT5_HEALTH, fundamental/macro, R:R), le bot produit des scores corrects et ~30 HARD_FILTER PASS en 1h. Mais l'event loop gèle silencieusement dès qu'un trade tente de s'exécuter.

**Symptôme** : Event loop gelé depuis 07:18 UTC le 10/03/2026 (10h+ sans cycle). Le PM_DIAG continue car il tourne dans le BackgroundScheduler (thread séparé).

## Cause racine : Deadlock COM MT5 inter-thread

### Le problème

La librairie Python MetaTrader5 utilise une interface COM **mono-thread** (STA — Single-Threaded Apartment). Toute tentative d'accès concurrent depuis deux threads différents provoque un **deadlock** de la DLL MT5.

Le `_GLOBAL_MT5_SEMAPHORE` (asyncio.Semaphore(1)) ne protège que l'exécution des agents MT5 (lignes ~4445-4466). Mais **6 autres appels MT5** via `asyncio.to_thread()` s'exécutent **HORS du sémaphore** dans la méthode async `_run_agents_and_decide` :

| Ligne | Appel | Contexte | Protégé ? |
|-------|-------|----------|-----------|
| ~4445-4466 | Agents MT5 (technical, scalping, swing, structure) | `_run_with_timeout` → `to_thread` | ✅ Sémaphore |
| **~2936** | `_mt5.positions_get(symbol=broker_sym)` | Daily loss floating check | ❌ **NON** |
| **~3110** | `_eod_close_sync(...)` | Fermeture EOD positions | ❌ **NON** |
| **~3364** | `self._compute_atr(symbol, "H1"/"M30")` | Fallback ATR si manquant | ❌ **NON** |
| **~3393** | `self.mt5._min_stop_distance_points(self.symbol)` | Broker min stop distance | ❌ **NON** |
| **~3597** | `_mt5.account_info()` | Crypto bucket equity | ❌ **NON** |
| **~3700** | `self.execute_trade(direction)` | Exécution du trade (contient 4+ appels MT5) | ❌ **NON** |

De plus, deux appels synchrones directs (NON wrappés dans `asyncio.to_thread`) pour les cryptos :

| Ligne | Appel | Contexte |
|-------|-------|----------|
| **~3574** | `_count_open_crypto_positions()` → `_mt5.positions_get()` | Crypto bucket max_open check |
| **~3589** | `_crypto_bucket_risk_used(get_symbol_profile)` → `_mt5.positions_get()` + `_mt5.account_info()` | Crypto bucket cap check |

### Le scénario de deadlock (SP500 le 10/03 à 07:18)

1. Orchestrateur SP500 finit ses agents → sémaphore libéré → atteint `execute_trade` (ligne 3700) → thread A appelle `_mt5.account_info()` via COM
2. Orchestrateur NAS100 acquiert le sémaphore → ses agents lancés dans thread B → appelle `_mt5.copy_rates()` via COM
3. **Deux threads accèdent au COM MT5 simultanément → DLL deadlock**
4. Thread A est bloqué ∞ → `await asyncio.to_thread(execute_trade)` ne retourne jamais → coroutine SP500 suspendue
5. Thread B est bloqué ∞ → agents NAS100 ne finissent jamais → sémaphore jamais libéré
6. Tous les autres orchestrateurs attendent le sémaphore → **tout l'event loop est paralysé**

---

## Correction : Protéger TOUS les appels MT5 avec le sémaphore

### Approche

Tous les appels `asyncio.to_thread()` qui touchent MT5 doivent acquérir `_GLOBAL_MT5_SEMAPHORE` AVANT d'exécuter l'appel dans le thread. Les appels synchrones directs doivent être wrappés dans `asyncio.to_thread()` + sémaphore.

### FIX 1 — Ligne ~2936 : `positions_get` daily loss floating

Chercher :
```python
                    # FIX 2026-03-09: Wrapper dans asyncio.to_thread pour ne pas bloquer le event loop
                    open_positions = await asyncio.to_thread(_mt5.positions_get, symbol=broker_sym)  # FIX 2026-02-24
```

Remplacer par :
```python
                    # FIX 2026-03-10: Protéger l'accès COM avec le sémaphore global
                    async with _GLOBAL_MT5_SEMAPHORE:
                        open_positions = await asyncio.to_thread(_mt5.positions_get, symbol=broker_sym)
```

### FIX 2 — Ligne ~3110 : `_eod_close_sync`

Chercher :
```python
                                _eod_results = await asyncio.to_thread(_eod_close_sync, symbol, _broker_sym, _eod_close_time)
```

Remplacer par :
```python
                                # FIX 2026-03-10: Protéger les appels COM EOD avec le sémaphore
                                async with _GLOBAL_MT5_SEMAPHORE:
                                    _eod_results = await asyncio.to_thread(_eod_close_sync, symbol, _broker_sym, _eod_close_time)
```

### FIX 3 — Ligne ~3364 : `_compute_atr` fallback

Chercher :
```python
                    atr = await asyncio.to_thread(self._compute_atr, symbol, "H1") or await asyncio.to_thread(self._compute_atr, symbol, "M30")
```

Remplacer par :
```python
                    # FIX 2026-03-10: Protéger les appels COM ATR avec le sémaphore
                    async with _GLOBAL_MT5_SEMAPHORE:
                        atr = await asyncio.to_thread(self._compute_atr, symbol, "H1") or await asyncio.to_thread(self._compute_atr, symbol, "M30")
```

### FIX 4 — Ligne ~3393 : `_min_stop_distance_points`

Chercher :
```python
                        min_pts_candidate = float(await asyncio.to_thread(self.mt5._min_stop_distance_points, self.symbol))  # type: ignore[attr-defined]
```

Remplacer par :
```python
                        # FIX 2026-03-10: Protéger l'accès COM avec le sémaphore
                        async with _GLOBAL_MT5_SEMAPHORE:
                            min_pts_candidate = float(await asyncio.to_thread(self.mt5._min_stop_distance_points, self.symbol))  # type: ignore[attr-defined]
```

### FIX 5 — Lignes ~3574 et ~3589 : Appels crypto bucket synchrones

**Ligne ~3574** — Chercher :
```python
                open_crypto = _count_open_crypto_positions()  # type: ignore
```

Remplacer par :
```python
                # FIX 2026-03-10: Wrapper sync → to_thread + sémaphore
                async with _GLOBAL_MT5_SEMAPHORE:
                    open_crypto = await asyncio.to_thread(_count_open_crypto_positions)
```

**Ligne ~3589** — Chercher :
```python
                used = _crypto_bucket_risk_used(get_symbol_profile)
```

Remplacer par :
```python
                # FIX 2026-03-10: Wrapper sync → to_thread + sémaphore
                async with _GLOBAL_MT5_SEMAPHORE:
                    used = await asyncio.to_thread(_crypto_bucket_risk_used, get_symbol_profile)
```

### FIX 6 — Ligne ~3597 : `account_info` crypto bucket

Chercher :
```python
                # FIX 2026-03-09: Wrapper dans asyncio.to_thread (appel MT5 synchrone)
                ai = await asyncio.to_thread(_mt5.account_info)
```

Remplacer par :
```python
                # FIX 2026-03-10: Protéger l'accès COM avec le sémaphore
                async with _GLOBAL_MT5_SEMAPHORE:
                    ai = await asyncio.to_thread(_mt5.account_info)
```

### FIX 7 — Ligne ~3700 : `execute_trade` (le plus critique)

Chercher :
```python
                    # FIX 2026-02-24: logger executed APRÈS execute_trade pour refléter le vrai statut
                    # FIX 2026-03-09: execute_trade contient des appels MT5 synchrones (account_info, positions_get)
                    # → on le lance dans un thread pour ne pas bloquer le event loop asyncio
                    trade_ok = await asyncio.to_thread(self.execute_trade, direction)
```

Remplacer par :
```python
                    # FIX 2026-03-10: execute_trade fait ~4 appels MT5 COM (account_info, positions_get,
                    # is_trade_blocked_by_inter_market, _count_open_crypto_positions)
                    # → sémaphore obligatoire pour éviter le deadlock COM inter-thread
                    async with _GLOBAL_MT5_SEMAPHORE:
                        trade_ok = await asyncio.to_thread(self.execute_trade, direction)
```

---

## Résumé des 7 modifications

| Fix | Ligne | Modification | Appel MT5 protégé |
|-----|-------|-------------|-------------------|
| 1 | ~2936 | + `async with _GLOBAL_MT5_SEMAPHORE:` | `positions_get` |
| 2 | ~3110 | + `async with _GLOBAL_MT5_SEMAPHORE:` | `_eod_close_sync` (positions_get + order_send) |
| 3 | ~3364 | + `async with _GLOBAL_MT5_SEMAPHORE:` | `_compute_atr` (copy_rates) |
| 4 | ~3393 | + `async with _GLOBAL_MT5_SEMAPHORE:` | `_min_stop_distance_points` |
| 5 | ~3574 + ~3589 | sync → `asyncio.to_thread` + sémaphore | `_count_open_crypto_positions` + `_crypto_bucket_risk_used` |
| 6 | ~3597 | + `async with _GLOBAL_MT5_SEMAPHORE:` | `account_info` |
| 7 | ~3700 | + `async with _GLOBAL_MT5_SEMAPHORE:` | `execute_trade` (4+ appels MT5 internes) |

**Toutes les modifications sont identiques** : ajouter `async with _GLOBAL_MT5_SEMAPHORE:` autour de l'appel `asyncio.to_thread()` existant. Pour les 2 appels sync crypto (FIX 5), ajouter aussi le wrap `asyncio.to_thread`.

## Impact attendu

- **0 deadlock COM** : tous les accès MT5 sont sérialisés par le sémaphore
- **Event loop ne gèle plus** : les `await` sur le sémaphore suspendent la coroutine proprement
- **Légère augmentation de la latence** : un orchestrateur attend le sémaphore pendant que `execute_trade` d'un autre tourne (~1-3s). Acceptable vs le deadlock actuel.

## Vérification après modification

1. `python -m py_compile orchestrator/orchestrator.py` → doit passer
2. Redémarrer via `START_EMPIRE.bat`
3. Vérifier dans les logs après **10 minutes** :
   - L'event loop ne gèle PAS (cycles d'analyse continuent toutes les ~120s)
   - Des HARD_FILTER PASS sont suivis d'exécution effective (`[TRADE]` ou `[EXECUTE]` dans les logs)
   - Pas de `[MT5_HEALTH]` généralisé (le fix Round 3 devrait avoir réduit à ~0)
   - Le PM_DIAG ET les cycles d'analyse tournent en parallèle sans interruption
