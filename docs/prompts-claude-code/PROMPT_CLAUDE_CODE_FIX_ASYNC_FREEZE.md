# PROMPT CLAUDE CODE — Fix Event Loop Freeze Post-HARD_FILTER + Intervals + Agents Finnhub

## Contexte

Après les fixes du 08/03 (sémaphore MT5, auto-reconnect, trading windows crypto), le bot démarre correctement et le sémaphore fonctionne. Cependant, **après ~2 minutes le event loop asyncio gèle complètement et silencieusement**. Le Position Manager (BackgroundScheduler) continue mais tous les orchestrateurs sont bloqués.

### Cause racine identifiée

Après le `[HARD_FILTER] PASS`, la coroutine entre dans le code de décision qui contient **des appels MT5 synchrones directs** (pas wrappés dans `asyncio.to_thread()`). Si le COM MT5 est lent ou gelé, ces appels bloquent tout le event loop asyncio et **aucune autre coroutine ne peut s'exécuter**. Aucune erreur n'est loggée car le code est simplement bloqué, pas en erreur.

### Appels bloquants identifiés (dans `_run_agents_and_decide`, qui est `async`)

1. **Ligne ~3123** : `self.mt5.get_last_price(symbol, side="BUY")` — fallback prix
2. **Ligne ~3347** : `self._compute_atr(symbol, timeframe="H1")` — appelle `self.mt5.get_rates()` en interne
3. **Ligne ~3377** : `self.mt5._min_stop_distance_points(self.symbol)` — distance minimum broker
4. **Ligne ~3558** : `_mt5.account_info()` — crypto bucket risk check
5. **Ligne ~2934** : `_mt5.positions_get(symbol=broker_sym)` — daily abs floating guard
6. **Lignes ~3068-3095** : bloc entier EOD close — `positions_get`, `symbol_info_tick`, `order_send`
7. **Ligne ~3659** : `self.execute_trade(direction)` — méthode synchrone qui contient `_mt5.account_info()` (ligne ~2151) et `_mt5.positions_get()` (ligne ~1967)

### Problèmes secondaires

- **Interval 60s** : La plupart des symboles utilisent encore 60s au lieu de 120s. Le champ `interval_secs` ajouté le 08/03 à LTCUSD et BNBUSD est au **mauvais niveau YAML** (racine du symbole) alors que le code lit `self.ori_cfg.get("timeframes", {}).get("orchestrator", 60)` (sous `orchestrator.timeframes`). De plus, le fallback dans le code est `60`, pas `120`.
- **Finnhub 403** : Les agents `fundamental` et `macro` timeout systématiquement car l'API Finnhub retourne 403 Forbidden. Ils gaspillent du temps dans chaque cycle.

---

## Corrections à appliquer (3 blocs)

### BLOC 1 — CRITIQUE : Wrapper les appels MT5 synchrones dans asyncio.to_thread()

**Fichier** : `orchestrator/orchestrator.py`

**Principe** : Tout appel MT5 synchrone (COM) dans une méthode `async` doit être wrappé dans `await asyncio.to_thread(...)` pour ne pas bloquer le event loop. Les appels dans des méthodes synchrones (comme `execute_trade`) doivent être lancés eux-mêmes via `await asyncio.to_thread(self.execute_trade, ...)`.

---

#### FIX 1a — Fallback prix (ligne ~3123 dans `_run_agents_and_decide`)

Chercher le bloc :
```python
# Fallback prix robuste
if price is None:
    try:
        price = self.mt5.get_last_price(symbol, side="BUY")
    except Exception:
        price = None
```

Remplacer par :
```python
# Fallback prix robuste
# FIX 2026-03-09: Wrapper dans asyncio.to_thread pour ne pas bloquer le event loop
if price is None:
    try:
        price = await asyncio.to_thread(self.mt5.get_last_price, symbol, "BUY")
    except Exception:
        price = None
```

---

#### FIX 1b — _compute_atr (ligne ~3347 dans `_run_agents_and_decide`)

Chercher le bloc :
```python
# FIX 2026-02-23: Recalculer si atr est None, 0 ou 0.0 (Directive 5)
if not atr or atr <= 0:
    atr = self._compute_atr(symbol, timeframe="H1") or self._compute_atr(symbol, timeframe="M30")
```

Remplacer par :
```python
# FIX 2026-02-23: Recalculer si atr est None, 0 ou 0.0 (Directive 5)
# FIX 2026-03-09: Wrapper dans asyncio.to_thread (appels MT5 synchrones)
if not atr or atr <= 0:
    atr = await asyncio.to_thread(self._compute_atr, symbol, "H1") or await asyncio.to_thread(self._compute_atr, symbol, "M30")
```

---

#### FIX 1c — _min_stop_distance_points (ligne ~3377 dans `_run_agents_and_decide`)

Chercher le bloc :
```python
try:
    if hasattr(self.mt5, "_min_stop_distance_points"):
        min_pts_candidate = float(self.mt5._min_stop_distance_points(self.symbol))  # type: ignore[attr-defined]
        broker_min = max(broker_min, min_pts_candidate * pt)
except Exception:
    broker_min = broker_min or 0.0
```

Remplacer par :
```python
try:
    if hasattr(self.mt5, "_min_stop_distance_points"):
        # FIX 2026-03-09: Wrapper dans asyncio.to_thread (appel MT5 synchrone)
        min_pts_candidate = float(await asyncio.to_thread(self.mt5._min_stop_distance_points, self.symbol))  # type: ignore[attr-defined]
        broker_min = max(broker_min, min_pts_candidate * pt)
except Exception:
    broker_min = broker_min or 0.0
```

---

#### FIX 1d — account_info crypto bucket (ligne ~3558 dans `_run_agents_and_decide`)

Chercher :
```python
pip_value = float(inst.get("pip_value") or 0.0)
ai = _mt5.account_info()
equity = float(getattr(ai, "equity", 0.0) or 0.0)
```

Remplacer par :
```python
pip_value = float(inst.get("pip_value") or 0.0)
# FIX 2026-03-09: Wrapper dans asyncio.to_thread (appel MT5 synchrone)
ai = await asyncio.to_thread(_mt5.account_info)
equity = float(getattr(ai, "equity", 0.0) or 0.0)
```

---

#### FIX 1e — positions_get daily abs floating guard (ligne ~2934 dans `_run_agents_and_decide`)

Chercher :
```python
if _mt5 is not None:  # FIX 2026-02-24: était 'mt5' → '_mt5'
    broker_sym = self.broker_symbol or self.symbol
    open_positions = _mt5.positions_get(symbol=broker_sym)  # FIX 2026-02-24
```

Remplacer par :
```python
if _mt5 is not None:  # FIX 2026-02-24: était 'mt5' → '_mt5'
    broker_sym = self.broker_symbol or self.symbol
    # FIX 2026-03-09: Wrapper dans asyncio.to_thread pour ne pas bloquer le event loop
    open_positions = await asyncio.to_thread(_mt5.positions_get, symbol=broker_sym)  # FIX 2026-02-24
```

---

#### FIX 1f — Bloc EOD close (lignes ~3066-3095 dans `_run_agents_and_decide`)

Ce bloc contient de nombreux appels MT5 (`positions_get`, `symbol_info_tick`, `order_send`). La meilleure approche est d'extraire toute la logique dans une **fonction synchrone locale** et la lancer via `asyncio.to_thread`.

Chercher le bloc complet qui commence par :
```python
# FIX 2026-02-20: Fermeture effective via MT5 (étape 2.3)
try:
    if _mt5 is not None:  # FIX 2026-02-24
        _broker_sym = getattr(self, "broker_symbol", symbol)
        _eod_positions = _mt5.positions_get(symbol=_broker_sym) or []  # FIX 2026-02-24
        for _eod_p in _eod_positions:
            ... (tout le bloc for avec order_send etc.)
except Exception as _eod_mt5_err:
    logger.warning(f"[EOD_CLOSE] Erreur MT5: {_eod_mt5_err}")
```

Remplacer par :
```python
# FIX 2026-02-20: Fermeture effective via MT5 (étape 2.3)
# FIX 2026-03-09: Toute la logique EOD dans asyncio.to_thread (appels MT5 synchrones)
try:
    if _mt5 is not None:  # FIX 2026-02-24
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
```

---

#### FIX 1g — execute_trade wrappé dans asyncio.to_thread (ligne ~3659)

`execute_trade()` est une méthode **synchrone** qui contient `_mt5.account_info()` (ligne ~2151) et `_mt5.positions_get()` (ligne ~1967). On NE PEUT PAS mettre `await` à l'intérieur de `execute_trade` car ce n'est pas async. La solution : wrapper l'appel entier dans `asyncio.to_thread` depuis `_run_agents_and_decide`.

Chercher :
```python
# FIX 2026-02-24: logger executed APRÈS execute_trade pour refléter le vrai statut
trade_ok = self.execute_trade(direction)
```

Remplacer par :
```python
# FIX 2026-02-24: logger executed APRÈS execute_trade pour refléter le vrai statut
# FIX 2026-03-09: execute_trade contient des appels MT5 synchrones (account_info, positions_get)
# → on le lance dans un thread pour ne pas bloquer le event loop asyncio
trade_ok = await asyncio.to_thread(self.execute_trade, direction)
```

---

### BLOC 2 — Corriger l'interval de cycle pour tous les symboles

#### FIX 2a — Fallback dans le code Python

**Fichier** : `orchestrator/orchestrator.py`

Chercher (vers ligne ~2649) :
```python
interval_seconds = int(self.timeframes_cfg.get("orchestrator", 60))
```

Remplacer par :
```python
# FIX 2026-03-09: Fallback 60→120 pour sémaphore MT5 (9 orchestrateurs sérialisés)
interval_seconds = int(self.timeframes_cfg.get("orchestrator", 120))
```

#### FIX 2b — Ajouter timeframes dans GLOBAL des overrides

**Fichier** : `config/overrides.yaml`

Dans la section `GLOBAL.orchestrator`, ajouter `timeframes.orchestrator: 120` :
```yaml
GLOBAL:
  orchestrator:
    # FIX 2026-03-09: Interval global 120s pour tous les symboles (sémaphore MT5)
    timeframes:
      orchestrator: 120

    weekend_guard:
      enabled: true
      ... (le reste ne change pas)
```

#### FIX 2c — Supprimer les `interval_secs` mal placés

**Fichier** : `config/overrides.yaml`

Le champ `interval_secs` ajouté le 08/03 au niveau racine de BTCUSD (~ligne 159) et LTCUSD (~ligne 252) n'est **jamais lu** par le code (le code lit `orchestrator.timeframes.orchestrator`, pas `interval_secs`). Supprimer ou commenter ces lignes :

- Chercher `interval_secs: 120` sous la section BTCUSD et le supprimer/commenter
- Chercher `interval_secs: 120` sous la section LTCUSD et le supprimer/commenter

---

### BLOC 3 — Désactiver les agents Finnhub (fundamental + macro)

**Fichier** : `config/config.yaml`

Dans la liste `agents:` (vers ligne ~560), commenter `fundamental` et `macro` :

Chercher :
```yaml
  - fundamental    # ✅ RÉACTIVÉ - Finnhub Economic Calendar (utilisé via macro)
  - macro          # ✅ ACTIF - Gating macro + Finnhub Calendar
```

Remplacer par :
```yaml
  # FIX 2026-03-09: Désactivés — Finnhub API renvoie 403 Forbidden (clé invalide/expirée)
  # → timeout systématique à chaque cycle, gaspille du temps dans le sémaphore
  # Réactiver quand la clé Finnhub sera remplacée/renouvelée
  # - fundamental    # DÉSACTIVÉ - Finnhub 403
  # - macro          # DÉSACTIVÉ - Finnhub 403
```

---

## Résumé des modifications

| # | Fichier | Modification | Impact |
|---|---------|-------------|--------|
| 1a | orchestrator.py ~3123 | `get_last_price` → `await asyncio.to_thread(...)` | Fallback prix ne bloque plus le event loop |
| 1b | orchestrator.py ~3347 | `_compute_atr` → `await asyncio.to_thread(...)` | Calcul ATR ne bloque plus |
| 1c | orchestrator.py ~3377 | `_min_stop_distance_points` → `await asyncio.to_thread(...)` | Distance broker ne bloque plus |
| 1d | orchestrator.py ~3558 | `account_info` → `await asyncio.to_thread(...)` | Crypto bucket check ne bloque plus |
| 1e | orchestrator.py ~2934 | `positions_get` → `await asyncio.to_thread(...)` | Daily loss guard ne bloque plus |
| 1f | orchestrator.py ~3068-3095 | Bloc EOD → fonction sync dans `asyncio.to_thread(...)` | EOD close ne bloque plus |
| 1g | orchestrator.py ~3659 | `execute_trade()` → `await asyncio.to_thread(...)` | Exécution MT5 ne bloque plus |
| 2a | orchestrator.py ~2649 | Fallback `60` → `120` | Tous les symboles à 120s minimum |
| 2b | overrides.yaml GLOBAL | Ajout `orchestrator.timeframes.orchestrator: 120` | Interval propagé à tous les symboles |
| 2c | overrides.yaml | Suppression `interval_secs` mal placés | Nettoyage config inutile |
| 3 | config.yaml | Comment `fundamental` et `macro` | Plus de timeouts Finnhub 403 |

## Impact attendu

- **Le event loop ne gèlera plus** : tous les appels MT5 synchrones dans le code async sont maintenant dans des threads séparés
- **Tous les symboles tournent à 120s** : le fallback est corrigé et GLOBAL propage le bon champ
- **Cycles plus rapides** : suppression de 2 agents qui timoutaient systématiquement (fundamental, macro)
- **Le bot pourra enfin exécuter des trades** : la chaîne HARD_FILTER PASS → execute_trade ne bloquera plus

## Vérification après modification

1. `python -m py_compile orchestrator/orchestrator.py` → doit passer sans erreur
2. Redémarrer le bot via `START_EMPIRE.bat`
3. Attendre **5 minutes** et vérifier dans les logs :
   - Aucun gel silencieux (les cycles de tous les symboles continuent toutes les ~120s)
   - Des `[HARD_FILTER] PASS` suivis de véritables tentatives d'exécution de trades
   - Aucun timeout `fundamental` ou `macro`
   - Les agents MT5 (scalping, swing, technical, structure, smart_money) répondent cycle après cycle
4. Si LTCUSD ou SOLUSD obtiennent un HARD_FILTER PASS, un trade devrait s'exécuter (ou être rejeté avec un message clair, pas un gel)
