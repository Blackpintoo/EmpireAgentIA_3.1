# PROMPT CLAUDE CODE — Fix Cryptos Bloquées + Agents Fantômes + Event Loop Starvation

## Contexte

Après les fixes du 09/03 (asyncio.to_thread), le event loop ne gèle plus de façon silencieuse.
Cependant, un nouveau problème est apparu dimanche soir : **seul AUDUSD lance des cycles d'agents** (avec 100% de timeouts car marché fermé), les 4 cryptos (BTCUSD, LTCUSD, BNBUSD, SOLUSD) **ne lancent aucun cycle** alors qu'elles devraient trader 24/7.

### Causes racines identifiées (3 problèmes interdépendants)

#### Problème 1 — Agents fantômes : fundamental/macro toujours enabled dans profiles.yaml

Les agents `fundamental` et `macro` ont été retirés de la liste `agents:` dans `config.yaml` (FIX 09/03), mais cela ne suffit PAS. Le code de `_gather_agent_signals()` utilise une liste **hardcodée** de `api_agents` (lignes 4390-4396) et vérifie `agent_enabled()` qui lit `profile.agents.<name>.enabled` dans **profiles.yaml** — pas la liste de config.yaml. Comme `profiles.yaml` a `fundamental: {enabled: true}` et `macro: {enabled: true}` pour **tous les symboles** (lignes 105-106, 152-153, 199-200, 251-252, 297-298, 344-345, 711-712), ces agents s'exécutent toujours et timoutent à 45s chacun.

#### Problème 2 — Sémaphore monopolisé par AUDUSD (starvation des cryptos)

AUDUSD (marché forex fermé le dimanche) acquiert le sémaphore `_GLOBAL_MT5_SEMAPHORE` et lance ses 4 agents MT5 séquentiellement. Chacun timeout à 45s car MT5 ne fournit pas de données (marché fermé). Total sous le sémaphore : **4 × 45s = 180s**. Ensuite l'auto-reconnect ajoute ~3s.

Avec un cycle de 120s, AUDUSD redémarre un cycle **avant même d'avoir terminé le précédent**. Les cryptos sont en file d'attente mais n'obtiennent jamais le sémaphore. Résultat : 100% de starvation.

#### Problème 3 — Appels MT5 synchrones dans _gather_agent_signals AVANT le sémaphore

Lignes 3981 et 3984-3987 de `_gather_agent_signals()` font des appels MT5 synchrones (`self._get_last_price()` et `self.mt5.get_account_info()`) **avant** le bloc `async with _GLOBAL_MT5_SEMAPHORE`. Ces appels bloquent le event loop pour chaque orchestrateur, même ceux qui ne devraient pas toucher MT5.

---

## Corrections à appliquer (5 fixes)

### FIX 1 — Désactiver fundamental et macro dans profiles.yaml

**Fichier** : `config/profiles.yaml`

**Action** : Remplacer TOUTES les occurrences de :
```yaml
fundamental: {enabled: true}
macro: {enabled: true}
```
par :
```yaml
fundamental: {enabled: false}   # FIX 2026-03-09: Finnhub 403 — timeout systématique
macro: {enabled: false}         # FIX 2026-03-09: Finnhub 403 — timeout systématique
```

Il y a **7 paires** à modifier (aux lignes ~105-106, ~152-153, ~199-200, ~251-252, ~297-298, ~344-345, ~711-712).

**Vérification** : `grep -n "fundamental.*enabled.*true\|macro.*enabled.*true" config/profiles.yaml` ne doit plus rien retourner.

---

### FIX 2 — Filtrer les api_agents hardcodés par agent_enabled()

**Fichier** : `orchestrator/orchestrator.py`

**Action** : Vers la ligne ~4390, modifier la construction de `api_agents` pour filtrer les agents désactivés. AUSSI filtrer `mt5_agents` par cohérence :

Chercher :
```python
        # Agents qui utilisent MT5 (copy_rates) — doivent tourner séquentiellement
        mt5_agents = [
            ("technical", _run_technical),
            ("scalping", _run_scalping),
            ("swing", _run_swing),
            ("structure", _run_structure),
        ]

        # Agents qui utilisent des API externes (HTTP) — peuvent tourner en parallèle
        api_agents = [
            ("whale", _run_whale),
            ("news", _run_news),
            ("sentiment", _run_sentiment),
            ("fundamental", _run_fundamental),
            ("macro", _run_macro),
        ]
```

Remplacer par :
```python
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
```

**Impact** : Les agents `fundamental` et `macro` ne seront plus lancés (car disabled dans profiles.yaml). Économie : 45s de timeout × 2 agents = 90s par cycle.

---

### FIX 3 — Wrapper les appels MT5 pré-sémaphore dans _gather_agent_signals

**Fichier** : `orchestrator/orchestrator.py`

**Action** : Dans `_gather_agent_signals()` (vers ligne ~3981), les appels à `self._get_last_price(symbol)` et `self.mt5.get_account_info()` sont synchrones et bloquent le event loop AVANT le sémaphore.

Chercher (vers ligne ~3981) :
```python
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
```

Remplacer par :
```python
        # --- Contexte marché ---
        # FIX 2026-03-09: Wrapper dans asyncio.to_thread pour ne pas bloquer le event loop
        price = await asyncio.to_thread(self._get_last_price, symbol)
        equity = None
        try:
            if hasattr(self.mt5, "get_account_info"):
                ai = await asyncio.to_thread(self.mt5.get_account_info)
                if ai and hasattr(ai, "equity"):
                    equity = float(ai.equity)
        except Exception:
            pass
```

**Important** : Vérifier que `_gather_agent_signals` est bien une méthode `async` (elle l'est — ligne ~3970 : `async def _gather_agent_signals`).

---

### FIX 4 — Skip des agents MT5 pour les marchés fermés (anti-starvation)

**Fichier** : `orchestrator/orchestrator.py`

**Principe** : Quand un marché forex/indices est fermé (dimanche), il est inutile d'acquérir le sémaphore et de lancer 4 agents MT5 qui vont tous timeout à 45s. Il faut **skip les agents MT5** si le marché est fermé, ce qui libère le sémaphore pour les cryptos qui tradent 24/7.

**Action** : Juste AVANT le bloc `async with _GLOBAL_MT5_SEMAPHORE:` (vers ligne ~4414), ajouter une vérification :

```python
        # ================================================================
        # FIX 2026-03-09: Skip agents MT5 si le marché est fermé
        # Évite de monopoliser le sémaphore pendant 180s (4×45s timeout)
        # Les cryptos tradent 24/7, les forex/indices seulement en semaine
        # ================================================================
        _skip_mt5 = False
        if mt5_agents:  # ne vérifier que s'il y a des agents MT5 à lancer
            try:
                _is_crypto = self.symbol.upper() in self._hf_crypto_symbols
                if not _is_crypto:
                    # Forex/indices: vérifier si le marché est ouvert via un tick rapide
                    _test_tick = await asyncio.to_thread(
                        lambda: self.mt5.get_tick(self.broker_symbol) if hasattr(self.mt5, "get_tick") else None
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

                # FIX 2026-03-08: Détection freeze MT5 + auto-reconnect
                _mt5_all_failed = all(
                    r is None or (isinstance(r, dict) and r.get("score") in (None, 0, 0.0))
                    for r in mt5_results
                )
                if _mt5_all_failed and len(mt5_results) >= 2:
                    logger.warning(f"[MT5_HEALTH] {self.symbol} — Tous les agents MT5 ont échoué, tentative reconnexion COM")
                    try:
                        from utils.mt5_client import MT5Client as _MC
                        _MC.shutdown_if_needed()
                        await asyncio.sleep(3)
                        _MC.initialize_if_needed(force=True)
                        logger.info(f"[MT5_HEALTH] {self.symbol} — Reconnexion MT5 réussie")
                    except Exception as _re:
                        logger.error(f"[MT5_HEALTH] {self.symbol} — Reconnexion échouée: {_re}")
```

**Ce qui change** : On remplace le bloc `async with _GLOBAL_MT5_SEMAPHORE: ...` existant (lignes ~4414-4435) par le nouveau bloc ci-dessus qui inclut le test de marché. L'ancien code du sémaphore est conservé dans la branche `else`.

---

### FIX 5 — Réduire le timeout des agents API à 15 secondes

**Fichier** : `orchestrator/orchestrator.py`

**Raison** : Les agents API (news, sentiment) n'ont pas besoin de 45s — c'est un timeout prévu pour les agents MT5 qui font du calcul lourd. Les agents API font des requêtes HTTP qui devraient répondre en 5-10s. Réduire à 15s économise du temps quand un agent API est lent.

**Action** : Dans `_gather_agent_signals()`, après la définition de `_AGENT_TIMEOUT = 45` (ligne ~3978), ajouter un timeout séparé pour les agents API :

Chercher :
```python
        _AGENT_TIMEOUT = 45  # FIX 2026-03-06: augmenté 10→45s pour éviter timeouts agents
```

Remplacer par :
```python
        _AGENT_TIMEOUT = 45      # FIX 2026-03-06: augmenté 10→45s pour agents MT5
        _API_AGENT_TIMEOUT = 15  # FIX 2026-03-09: timeout réduit pour agents API (HTTP requests)
```

Puis modifier le bloc des agents API (vers ligne ~4437-4441) pour utiliser `_API_AGENT_TIMEOUT` :

Chercher :
```python
        # 2) Agents API en parallèle HORS du sémaphore (pas de contrainte mono-thread)
        api_results = await asyncio.gather(
            *[_run_with_timeout(name, fn) for name, fn in api_agents],
            return_exceptions=True,
        )
```

Remplacer par :
```python
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
```

---

## Résumé des modifications

| # | Fichier | Modification | Impact |
|---|---------|-------------|--------|
| 1 | profiles.yaml | `fundamental/macro: enabled: false` (7 paires) | Plus de timeout Finnhub 403 |
| 2 | orchestrator.py ~4382-4396 | Filtrer mt5_agents et api_agents par `agent_enabled()` | Agents désactivés ne se lancent plus |
| 3 | orchestrator.py ~3981-3989 | `_get_last_price` et `get_account_info` → `await asyncio.to_thread(...)` | Event loop non bloqué pré-sémaphore |
| 4 | orchestrator.py ~4414 | Skip sémaphore+agents MT5 si marché fermé (tick test) | AUDUSD ne monopolise plus le sémaphore le dimanche |
| 5 | orchestrator.py ~3978,4437 | Timeout API agents 45s→15s | Cycles plus rapides |

## Impact attendu

- **Les cryptos pourront enfin trader le dimanche** : le sémaphore n'est plus monopolisé par AUDUSD
- **Cycles 2× plus rapides** : suppression de fundamental/macro (90s de timeout en moins), timeout API réduit
- **Event loop toujours réactif** : plus d'appels MT5 synchrones hors thread

## Vérification après modification

1. `python -m py_compile orchestrator/orchestrator.py` → doit passer
2. `grep -n "fundamental.*enabled.*true\|macro.*enabled.*true" config/profiles.yaml` → doit être vide
3. Redémarrer le bot via `START_EMPIRE.bat`
4. Attendre **5 minutes** et vérifier dans les logs :
   - BTCUSD, LTCUSD, BNBUSD, SOLUSD lancent des cycles toutes les ~120s
   - `[MARKET_CHECK] AUDUSD: pas de tick` (le dimanche)
   - `[AGENTS] BTCUSD: MT5=[technical, scalping, swing, structure] API=[news, sentiment]` (pas fundamental/macro)
   - Les agents des cryptos retournent des scores > 0
   - Si un HARD_FILTER PASS se produit, un trade s'exécute (ou rejet avec message)
