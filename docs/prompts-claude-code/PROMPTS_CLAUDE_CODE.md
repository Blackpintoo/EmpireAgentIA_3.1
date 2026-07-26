# Prompts Claude Code — EmpireAgentIA_3
## Mis à jour le 2 mars 2026
### (Basé sur l'analyse complète + corrections déjà implémentées)

---

## PHASE 1 — Restructuration du portefeuille de paires (Priorité maximale)

### PROMPT 1 : Retirer les paires structurellement perdantes

```
Dans le fichier config/profiles.yaml du projet EmpireAgentIA_3,
effectue les modifications suivantes sur le portefeuille de symboles :

RETIRER complètement (supprimer de la liste des symboles, même disabled) :
- LTCUSD : PF 0.28, WR 29% sur 266 trades, perte -30 895$. Échec structurel.
- SOLUSD : PF 0.13, WR 29% sur 122 trades, perte -12 686$. Même réactivé le 11/02, reste non rentable.
- ADAUSD : déjà disabled, 72% counter-trend, perte -138 956$. Irrécupérable.
- XAGUSD : déjà disabled, WR 0%, perte -11 006$.
- UK100 : déjà disabled, WR 0%, perte -23 124$.
- USOUSD : déjà paused, insufficient data et CL-OIL historiquement WR 8%.
- GBPUSD : déjà disabled, WR 0%, perte -2 695$.

GARDER DISABLED (à réévaluer après Optuna) :
- EURUSD : WR 21%, -143 891$. Garder disabled mais ne pas supprimer car paire majeure — réévaluation après optimisation Optuna complète.

Ne touche PAS aux paires actives (NAS100, SP500, AUDUSD, USDJPY, XAUUSD, BNBUSD, BTCUSD).

Assure-toi que max_symbols_parallel reste cohérent avec le nombre de paires restantes.
```

### PROMPT 2 : Ajouter les nouvelles paires recommandées

```
Dans le fichier config/profiles.yaml du projet EmpireAgentIA_3,
ajoute les paires suivantes en tant que NOUVELLES paires actives (enabled: true) :

1. GBPJPY :
   - Forte volatilité intraday, idéal pour les agents scalping/momentum
   - session_filter: london + new_york (heures UTC 7-16)
   - lot_size: commencer conservateur à 0.5
   - Pas de blacklist hours nécessaire

2. USDCHF :
   - Corrélation inverse EURUSD, bon pour diversification
   - session_filter: london + new_york (heures UTC 7-16)
   - lot_size: 0.5
   - Paire stable, adapté aux agents swing et technical

3. AUDJPY :
   - Carry trade classique, bon signal momentum
   - session_filter: tokyo + london (heures UTC 0-8, 7-16)
   - lot_size: 0.5
   - Adapté aux agents swing et price_action

4. ETHUSD :
   - RÉACTIVER (changer enabled: false → enabled: true)
   - PF historique de 3.24, WR 57% — c'est la meilleure paire crypto après BTCUSD
   - Reprendre la config crypto standard : exempt de session_filter
   - lot_size: 0.5, max_lot: 1.0

Pour chaque nouvelle paire, copie la structure de configuration d'une paire
existante similaire (forex pour GBPJPY/USDCHF/AUDJPY, crypto pour ETHUSD)
et adapte les paramètres ci-dessus.

Vérifie que ces symboles existent bien chez le broker Vantage International
en regardant les noms dans le fichier config.yaml section mt5.
```

### PROMPT 3 : Optimiser les paires sous-performantes conservées

```
Dans config/profiles.yaml du projet EmpireAgentIA_3, optimise les paramètres
des paires suivantes qui sont rentables mais sous-optimales :

1. BNBUSD (actuellement actif) :
   - Problème identifié : position sizing trop agressif causant des pertes disproportionnées
   - Réduire max_lot de sa valeur actuelle à 0.3
   - Ajouter un cooldown_minutes: 30 entre les trades
   - Restreindre les whitelist hours aux heures de volume crypto : [8,9,10,11,12,13,14,15,16,17,18,19,20,21,22] UTC

2. SP500 (actuellement actif) :
   - Problème identifié : ratio risque/récompense (RR) trop bas
   - Dans la section agent overrides ou dans le profil du symbole,
     forcer min_rr: 2.0 (au lieu du 1.5 global) spécifiquement pour SP500
   - Cela filtrera les trades à faible potentiel sur cet indice

3. XAUUSD (actuellement actif, déjà rentable +1 962$) :
   - Potentiel d'amélioration : élargir les heures de trading
   - S'assurer que la session_filter couvre bien london + new_york complet (7h-21h UTC)
   - L'or performe surtout pendant le chevauchement London-NY (13h-16h UTC)
```

---

## PHASE 2 — Recalibration Optuna avec données réelles

### PROMPT 4 : Lancer un cycle Optuna complet post-corrections

```
Dans le projet EmpireAgentIA_3, lance un cycle d'optimisation Optuna complet.

CONTEXTE : Les modules econ_api.py et advanced_sentiment.py ont été refactorisés
le 1er mars 2026 pour utiliser des données réelles (Finnhub, CFTC, Binance)
au lieu de données simulées. Les anciens paramètres optimisés sur du bruit
sont donc obsolètes et doivent être recalibrés.

ÉTAPES :
1. Dans config/config.yaml, augmenter temporairement :
   - optuna.n_trials: 100 (au lieu de 50)
   - optuna.timeout: 900 (au lieu de 600)

2. Exécuter l'optimisation pour CHAQUE agent, dans cet ordre :
   - python -m optimization.optuna_agent --agent technical --trials 100 --start 2025-06-01 --end 2026-02-28
   - python -m optimization.optuna_agent --agent scalping --trials 100 --start 2025-06-01 --end 2026-02-28
   - python -m optimization.optuna_agent --agent swing --trials 100 --start 2025-06-01 --end 2026-02-28

3. Après chaque run, sauvegarder les meilleurs paramètres trouvés
   dans config/profiles.yaml sous la section de chaque agent.

4. Remettre optuna.n_trials: 50 et timeout: 600 après la calibration.

5. Afficher un résumé des paramètres avant/après pour chaque agent.

NOTE : La période de backtest commence en juin 2025 pour inclure des données
récentes où les marchés ont évolué (post-COVID recovery, taux élevés).
```

---

## PHASE 3 — Optimisations de performance

### PROMPT 5 : TTL Cache pour les appels MT5 redondants

```
Dans le fichier orchestrator/orchestrator.py du projet EmpireAgentIA_3,
implémente un cache TTL pour les appels MT5 répétitifs.

PROBLÈME : Chaque cycle de 60 secondes appelle MT5 pour récupérer les mêmes
données (positions ouvertes, account info, symbol info) pour chaque symbole.
Avec 12+ symboles actifs, cela génère des dizaines d'appels redondants par cycle.

SOLUTION :
1. Créer un décorateur ou une classe utilitaire TTLCache dans utils/cache.py :
   ```python
   import time
   import threading

   class TTLCache:
       def __init__(self, ttl_seconds=10):
           self._cache = {}
           self._lock = threading.Lock()
           self._ttl = ttl_seconds

       def get(self, key):
           with self._lock:
               if key in self._cache:
                   value, timestamp = self._cache[key]
                   if time.time() - timestamp < self._ttl:
                       return value
                   del self._cache[key]
           return None

       def set(self, key, value):
           with self._lock:
               self._cache[key] = (value, time.time())

       def clear(self):
           with self._lock:
               self._cache.clear()
   ```

2. Dans l'orchestrateur, wrapper les appels suivants avec ce cache (TTL = 10s) :
   - mt5.account_info()
   - mt5.positions_get()
   - mt5.symbol_info(symbol)
   - mt5.symbol_info_tick(symbol)

3. Le cache doit être thread-safe (threading.Lock) car plusieurs orchestrateurs
   tournent en parallèle.

4. Ajouter une méthode clear_cache() appelée au début de chaque cycle
   _run_agents_and_decide() pour garantir des données fraîches par cycle.

5. Logger le hit ratio du cache toutes les 100 requêtes pour monitoring.
```

### PROMPT 6 : Paralléliser l'exécution des agents avec asyncio.gather

```
Dans orchestrator/orchestrator.py du projet EmpireAgentIA_3,
optimise la méthode _gather_agent_signals() (ou équivalent) pour
paralléliser l'exécution des agents.

ÉTAT ACTUEL : asyncio est déjà importé et AsyncIOScheduler est utilisé.
Les agents sont déjà cachés via self._agent_cache. Mais les agents
semblent être exécutés séquentiellement dans la boucle de collecte de signaux.

MODIFICATION :
1. Identifier la boucle qui itère sur les agents pour collecter les signaux
   (chercher _gather_agent_signals, _run_agents_and_decide, ou la section
   qui appelle agent.analyze() pour chaque agent activé).

2. Wrapper chaque appel agent dans asyncio.to_thread() pour exécution parallèle :
   ```python
   async def _gather_agent_signals(self, symbol):
       tasks = []
       for agent_name, agent in self._active_agents.items():
           tasks.append(asyncio.to_thread(agent.analyze, symbol, timeframe))
       results = await asyncio.gather(*tasks, return_exceptions=True)
       # Traiter les résultats, ignorer les exceptions
   ```

3. Ajouter un timeout de 30 secondes par agent pour éviter qu'un agent bloqué
   ne retarde tout le cycle :
   ```python
   results = await asyncio.wait_for(
       asyncio.gather(*tasks, return_exceptions=True),
       timeout=30
   )
   ```

4. Logger le temps d'exécution avant/après pour mesurer le gain.

ATTENTION :
- MT5 n'est PAS thread-safe. Les appels MT5 dans les agents doivent
  passer par un Lock global ou un executor dédié.
- Ne pas paralléliser les agents qui partagent des ressources fichier
  sans protection (vérifier les locks existants).
```

---

## PHASE 4 — Corrections résiduelles

### PROMPT 7 : Fix dry-run mode (BUG-01)

```
Dans orchestrator/orchestrator.py du projet EmpireAgentIA_3,
corrige le mode dry-run.

BUG : Quand DRY_RUN=True dans la config, le code fait référence à des
variables non définies dans le bloc de simulation (variables qui n'existent
que dans le bloc d'exécution réelle MT5).

CORRECTION :
1. Chercher toutes les occurrences de "dry_run" ou "DRY_RUN" dans le fichier.
2. Pour chaque bloc if dry_run / if not dry_run, vérifier que toutes les
   variables utilisées dans le bloc dry_run sont bien définies DANS ce bloc
   (et non héritées du bloc else qui ne s'exécute pas).
3. Le bloc dry_run doit simuler :
   - Un order_result fictif avec ticket, price, volume
   - Un retcode de succès (10009)
   - Logger "[DRY-RUN] Simulated order: ..." au lieu d'exécuter MT5
4. Tester en lançant brièvement avec DRY_RUN=True pour confirmer
   qu'il n'y a plus de NameError ou UnboundLocalError.
```

### PROMPT 8 : Fix floating P&L false positive (BUG-04)

```
Dans orchestrator/orchestrator.py du projet EmpireAgentIA_3,
corrige le calcul du P&L flottant qui peut déclencher le kill switch
sur un faux positif.

BUG : Le calcul du floating P&L additionne les profits/pertes non réalisés
de toutes les positions ouvertes. Mais si MT5 retourne des positions avec
un profit temporairement négatif (spread élargi, slippage à l'ouverture),
le daily_loss_usd peut être franchi et déclencher le GlobalKillSwitch
alors que les positions sont encore viables.

CORRECTION :
1. Chercher le calcul de floating_pnl ou unrealized_pnl dans l'orchestrateur.
2. Ajouter un buffer de grâce : ne déclencher le kill switch que si
   floating_pnl < -(daily_loss_usd * 1.1) pendant 2 vérifications consécutives
   (pas sur une seule lecture).
3. Implémenter un compteur de confirmations :
   ```python
   if floating_pnl < -self.daily_loss_limit:
       self._kill_switch_confirmations += 1
       if self._kill_switch_confirmations >= 2:
           self._trigger_kill_switch(reason="Confirmed daily loss exceeded")
   else:
       self._kill_switch_confirmations = 0
   ```
4. Logger un WARNING au premier dépassement et un CRITICAL au second.
```

### PROMPT 9 : Empêcher la désactivation permanente d'agents (BUG-06)

```
Dans orchestrator/orchestrator.py du projet EmpireAgentIA_3,
corrige le mécanisme de désactivation des agents sous-performants.

BUG : Quand un agent a un score bas pendant plusieurs cycles consécutifs,
il peut être désactivé (enabled: false) de manière permanente sans
mécanisme de réactivation automatique. Après quelques semaines,
plusieurs agents utiles peuvent être désactivés à tort (marché temporairement
défavorable à leur stratégie).

CORRECTION :
1. Chercher le code qui désactive un agent (chercher "disable", "enabled = False",
   "deactivate" dans le contexte des agents).
2. Ajouter un mécanisme de cooldown au lieu d'une désactivation permanente :
   ```python
   # Au lieu de : agent.enabled = False
   # Faire :
   agent.cooldown_until = datetime.now() + timedelta(hours=24)
   agent.enabled = False
   logger.warning(f"Agent {agent.name} en cooldown 24h (score moyen trop bas)")
   ```
3. Au début de chaque cycle, vérifier si le cooldown est expiré :
   ```python
   if not agent.enabled and hasattr(agent, 'cooldown_until'):
       if datetime.now() >= agent.cooldown_until:
           agent.enabled = True
           logger.info(f"Agent {agent.name} réactivé après cooldown")
   ```
4. Limiter à 3 désactivations max avant de passer en cooldown long (72h)
   pour éviter les boucles on/off.
```

---

## PHASE 5 — Monitoring et validation

### PROMPT 10 : Script de monitoring des performances post-corrections

```
Crée un script scripts/monitor_performance.py dans le projet EmpireAgentIA_3
qui analyse les performances depuis les corrections du 1er mars 2026.

Le script doit :
1. Lire data/deals_history.csv
2. Filtrer uniquement les trades à partir du 2026-03-01
3. Calculer pour chaque symbole :
   - Nombre de trades
   - Win Rate (%)
   - Profit Factor
   - P&L net ($)
   - Drawdown max
   - R-multiple moyen
4. Calculer les métriques globales :
   - P&L total depuis le 1er mars
   - Projection mensuelle basée sur les données disponibles
   - Comparaison avec l'objectif de 5 000$/mois
5. Identifier les paires qui sous-performent encore malgré les corrections
6. Afficher le résultat dans un tableau formaté en console
7. Sauvegarder le rapport en CSV dans data/performance_report_post_fix.csv

LIBRAIRIES : pandas, tabulate (installer si nécessaire)
FORMAT DE SORTIE : tableau ASCII clair avec couleurs (vert = rentable, rouge = perte)
```

---

## Résumé de l'ordre d'exécution

| Ordre | Prompt | Impact | Effort |
|-------|--------|--------|--------|
| 1 | Prompt 1 — Retirer paires perdantes | Élevé | Faible |
| 2 | Prompt 2 — Ajouter nouvelles paires | Élevé | Moyen |
| 3 | Prompt 3 — Optimiser paires conservées | Moyen | Faible |
| 4 | Prompt 7 — Fix dry-run | Moyen | Faible |
| 5 | Prompt 8 — Fix floating P&L | Élevé | Moyen |
| 6 | Prompt 9 — Fix désactivation agents | Moyen | Moyen |
| 7 | Prompt 4 — Optuna recalibration | Élevé | Élevé |
| 8 | Prompt 5 — TTL Cache MT5 | Moyen | Moyen |
| 9 | Prompt 6 — Paralléliser agents | Moyen | Élevé |
| 10 | Prompt 10 — Script monitoring | Faible | Faible |
