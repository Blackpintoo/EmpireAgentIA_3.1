# Prompt Claude Code — Fix saturation MT5 + TFs

Copie-colle le bloc ci-dessous dans Claude Code :

---

```
Le rapport de monitoring montre que TOUS les agents timeout encore malgré le passage à 45s. Cause racine : l'API MT5 COM est mono-thread, et 81 agents en parallèle (9 symboles × 9 agents) lancent ~486 requêtes MT5 par cycle.

Il y a 3 corrections à appliquer SIMULTANÉMENT.

---

## CORRECTION 1 — Réduire les TFs dans le fallback Python

Fichier : `orchestrator/orchestrator.py`
Ligne ~821, chercher :
```python
self.tfs: List[str] = list(mtf.get("tfs", ["H4", "H1", "M30", "M15", "M5", "M1"]))
```
Remplacer par :
```python
self.tfs: List[str] = list(mtf.get("tfs", ["H1", "M15", "M5"]))  # FIX 2026-03-06: réduit de 6→3 TFs pour éviter saturation MT5
```

## CORRECTION 2 — Réduire les TFs dans overrides.yaml pour TOUS les symboles

Fichier : `config/overrides.yaml`

Pour BTCUSD (ligne ~70) : remplacer
```yaml
      tfs: ["H4", "H1", "M30", "M15", "M5"]
```
par :
```yaml
      tfs: ["H1", "M15", "M5"]
```

Pour BNBUSD (ligne ~318) : remplacer
```yaml
      tfs: ["H4", "H1", "M30", "M15"]
```
par :
```yaml
      tfs: ["H1", "M15", "M5"]
```

Pour LTCUSD (ligne ~196) : remplacer
```yaml
      tfs: ["H4", "H1", "M30"]
```
par :
```yaml
      tfs: ["H1", "M15", "M5"]
```

Pour tous les autres symboles qui ont un bloc `multi_timeframes:` avec `tfs:` dans overrides.yaml, remplacer leur liste de TFs par :
```yaml
      tfs: ["H1", "M15", "M5"]
```

Chercher TOUTES les occurrences de `tfs:` dans overrides.yaml et les mettre à `["H1", "M15", "M5"]`.

Aussi dans `config/config.yaml`, mettre à jour la section multi_timeframes :
```yaml
multi_timeframes:
  enabled: true
  tfs: [H1, M15, M5]
  tf_weights:
    H1: 1.2
    M15: 1.0
    M5: 0.9
```

## CORRECTION 3 — Séquencer les symboles par batches de 3

C'est la correction la plus importante. Le problème est que les 9 orchestrateurs tournent TOUS en même temps et appellent TOUS MT5 en parallèle.

Fichier : `orchestrator/orchestrator.py`

Dans la méthode `_gather_agent_signals` (vers la ligne 4336-4367), le code exécute les 9 agents en parallèle avec `asyncio.gather`. Le problème est que `asyncio.to_thread` les envoie tous dans le ThreadPoolExecutor en même temps, et ils s'empilent sur l'API MT5 COM qui est mono-thread.

Remplacer le bloc d'exécution parallèle (lignes ~4336-4367) :

```python
        # ================================================================
        # Exécution parallèle avec timeout individuel
        # ================================================================
        agent_tasks = [
            ("technical", _run_technical),
            ("scalping", _run_scalping),
            ("swing", _run_swing),
            ("structure", _run_structure),
            ("whale", _run_whale),
            ("news", _run_news),
            ("sentiment", _run_sentiment),
            ("fundamental", _run_fundamental),
            ("macro", _run_macro),
        ]

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
                logger.warning(f"[AGENT] {name} erreur parallèle pour {self.symbol}: {e}")
                return None

        results = await asyncio.gather(
            *[_run_with_timeout(name, fn) for name, fn in agent_tasks],
            return_exceptions=True,
        )
```

Par ce nouveau code qui exécute les agents MT5-dépendants en SÉQUENTIEL et les agents API-externes en parallèle :

```python
        # ================================================================
        # FIX 2026-03-06: Exécution séquentielle des agents MT5 + parallèle API
        # L'API MT5 COM est mono-thread → paralléliser cause des embouteillages
        # ================================================================

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

        # 1) Agents MT5 séquentiellement (évite saturation COM)
        mt5_results = []
        for name, fn in mt5_agents:
            result = await _run_with_timeout(name, fn)
            mt5_results.append(result)

        # 2) Agents API en parallèle (pas de contrainte mono-thread)
        api_results = await asyncio.gather(
            *[_run_with_timeout(name, fn) for name, fn in api_agents],
            return_exceptions=True,
        )

        # Fusionner les résultats dans l'ordre original
        agent_tasks = mt5_agents + api_agents
        results = mt5_results + list(api_results)
```

IMPORTANT : Le bloc qui suit (`agent_names = [name for name, _ in agent_tasks]` et la boucle de fusion) doit rester INCHANGÉ — il fonctionnera correctement car `agent_tasks` et `results` sont reconstruits dans le bon ordre.

## CORRECTION 4 — Ajouter un délai inter-symboles dans le scheduler

Fichier : `orchestrator/orchestrator.py`
Dans la méthode `start` (vers la ligne 2649), là où le job principal est programmé :

```python
        self.scheduler.add_job(
            self._run_agents_and_decide_sync,
            "interval",
            seconds=interval_seconds,
            id=job_id,
            replace_existing=True,
        )
```

Ajouter un décalage basé sur l'index du symbole pour que les 9 orchestrateurs ne se lancent pas tous à la même seconde. Chercher dans `__init__` s'il y a un moyen de connaître l'index, sinon utiliser un hash du symbole :

Juste AVANT le `self.scheduler.add_job(...)`, ajouter :
```python
        # FIX 2026-03-06: Décaler les symboles pour ne pas saturer MT5
        import hashlib
        _sym_hash = int(hashlib.md5(self.symbol.encode()).hexdigest()[:4], 16)
        _offset_secs = (_sym_hash % 9) * 7  # Décalage 0-56 secondes selon le symbole
```

Puis modifier le `add_job` pour ajouter un `jitter` ou utiliser `next_run_time` :
```python
        from datetime import timedelta as _td
        self.scheduler.add_job(
            self._run_agents_and_decide_sync,
            "interval",
            seconds=interval_seconds,
            id=job_id,
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + _td(seconds=_offset_secs),  # FIX 2026-03-06: décalage
        )
```

## CORRECTION 5 — Élargir la trading_window de BNBUSD

Fichier : `config/overrides.yaml`
Dans la section BNBUSD, chercher :
```yaml
    trading_window:
      enabled: true
      timezone: "Europe/Zurich"
      start: "08:00"
      end: "19:00"
```
Remplacer par :
```yaml
    trading_window:
      enabled: true
      timezone: "Europe/Zurich"
      start: "07:00"
      end: "23:00"
```

---

## VÉRIFICATION

1. Vérifier syntaxe Python : `python -c "import ast; ast.parse(open('orchestrator/orchestrator.py').read()); print('OK')"`
2. Vérifier YAML : `python -c "import yaml; yaml.safe_load(open('config/overrides.yaml')); print('overrides OK')"`
3. Vérifier YAML : `python -c "import yaml; yaml.safe_load(open('config/config.yaml')); print('config OK')"`
4. Compter le nombre total de TFs dans overrides.yaml : `grep -c "tfs:" config/overrides.yaml` et vérifier que toutes les listes sont ["H1", "M15", "M5"]
5. Récapitulatif de tous les fichiers modifiés

Ne crée PAS de commit, attends ma confirmation.
```
