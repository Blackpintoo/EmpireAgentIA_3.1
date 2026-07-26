# PROMPT CLAUDE CODE — Diagnostic EXHAUSTIF post-Rounds 3-6

## Contexte

Le bot de trading EmpireAgentIA_3 gère 9 symboles via MetaTrader 5 (COM). Après 1 semaine sans aucun trade, 4 rounds de corrections ont été appliqués (Rounds 3 à 6) pour éliminer les deadlocks COM et les blocages de l'event loop. Le bot vient d'être redémarré.

**Objectif** : Diagnostiquer TOUT ce qui pourrait encore empêcher l'exécution de trades. Aucun fichier ne doit être modifié. Lecture seule.

---

## PHASE 1 — Collecte des données

Exécute TOUTES les commandes suivantes et conserve les résultats :

```bash
# 1a. Dernières 1000 lignes du log principal
tail -n 1000 logs/empire_agent.log

# 1b. Si le fichier n'existe pas, chercher les logs
dir /s /b logs\*.log 2>nul
dir /s /b *.log 2>nul

# 1c. Fichier de config principal
type config\config.yaml

# 1d. Overrides par symbole
type config\overrides.yaml

# 1e. Profils par symbole
type config\profiles.yaml

# 1f. Guards actifs (fichiers flag)
dir /b data\guards\*.flag 2>nul
type data\guards\stop_all.flag 2>nul
type data\guards\target_met.flag 2>nul

# 1g. Derniers signaux générés
type data\latest_signals.json 2>nul

# 1h. Journal des trades
type data\trades_log.csv 2>nul

# 1i. Deals history
tail -n 50 data\deals_history.csv 2>nul

# 1j. Vérifier que py_compile passe
python -m py_compile orchestrator/orchestrator.py
```

---

## PHASE 2 — Analyse de l'event loop (7 vérifications)

### 2.1 — L'event loop tourne-t-il ?
Dans les logs, chercher les timestamps des cycles d'analyse (lignes contenant `_run_agents_and_decide` ou `[CYCLE]` ou `[ORCH]` ou `score=`).
- Calculer l'écart entre les 10 derniers cycles pour chaque symbole.
- **OK** : écarts de 60-180s réguliers
- **KO** : trou >5 min ou aucun cycle récent

### 2.2 — Y a-t-il eu un freeze ?
Chercher tout trou de >5 minutes entre deux lignes de log consécutives (toutes lignes confondues, pas seulement les cycles).
- **OK** : pas de trou >5 min
- **KO** : lister chaque trou avec timestamps début/fin

### 2.3 — Erreurs de lock ou COM ?
Chercher : `_MT5Lock`, `_GLOBAL_MT5_SEMAPHORE`, `threading.Lock`, `acquire`, `deadlock`, `COM error`, `RPC_E_WRONG_THREAD`, `RuntimeError`, `mt5.initialize`, `MT5 not initialized`
- **OK** : aucune occurrence
- **KO** : lister chaque erreur

### 2.4 — Erreurs Python non catchées ?
Chercher : `Traceback`, `Exception`, `Error`, `CRITICAL`, `FATAL`
- Lister les erreurs uniques (pas les duplicats)
- Classifier : bloquante (empêche le trading) vs non-bloquante

### 2.5 — Le scheduler APScheduler tourne-t-il ?
Chercher : `SchedulerAlreadyRunningError`, `scheduler`, `add_job`, `Missed job`
- **OK** : pas d'erreur scheduler
- **KO** : erreurs listées

### 2.6 — Combien de symboles sont actifs ?
Compter le nombre de symboles distincts qui apparaissent dans les 200 dernières lignes de log.
- **Attendu** : 9 symboles (BTCUSD, ETHUSD, SOLUSD, BNBUSD, XAUUSD, EURUSD, USDJPY, SP500, NAS100)
- **KO** : certains symboles absents → lesquels ?

### 2.7 — Cooldowns actifs ?
Chercher : `[COOLDOWN]`, `_arm_cooldown`, `cooldown actif`
- Lister les symboles en cooldown et la durée restante

---

## PHASE 3 — Analyse du Position Manager (3 vérifications)

### 3.1 — Le PM tourne-t-il ?
Chercher `[PM` ou `PM_DIAG` ou `manage_open_positions` dans les logs.
- **OK** : apparaît régulièrement (toutes les ~20s)
- **KO** : absent ou erreurs

### 3.2 — Positions ouvertes actuelles ?
Chercher les logs mentionnant des positions ouvertes, ou lire `data/latest_signals.json`.

### 3.3 — Erreurs PM ?
Chercher toute erreur associée au PM (trailing stop, BE, partials).

---

## PHASE 4 — Analyse de la chaîne de décision (12 vérifications)

C'est la partie LA PLUS IMPORTANTE. Pour chaque symbole, tracer le chemin complet de la dernière décision.

### 4.1 — Score des agents
Chercher les lignes contenant `score=` ou `agent_scores` ou `composite_score` pour chaque symbole.
- Quel est le score obtenu ?
- Quel est le `min_score_for_proposal` configuré ? (lire dans overrides.yaml et profiles.yaml)
- Le score dépasse-t-il le seuil ?

### 4.2 — Confluence
Chercher `confluence=` ou `min_confluence` pour chaque symbole.
- Quelle confluence obtenue ?
- Quel seuil configuré ?
- La confluence dépasse-t-elle le seuil ?

### 4.3 — Direction
Chercher `direction=` ou `LONG` ou `SHORT` pour chaque symbole.
- Une direction est-elle déterminée ou `direction_indeterminee` ?

### 4.4 — R:R (Risk/Reward)
Chercher `rr=` ou `R:R` ou `_estimate_rr` ou `min_rr` pour chaque symbole.
- Quel R:R calculé ?
- Quel seuil `min_rr` ? (devrait être 0.80)
- Le R:R dépasse-t-il le seuil ?

### 4.5 — Session filter
Chercher `session_filter` ou `blocked_hours` ou `prime_hours` ou `hors_session`.
- Y a-t-il un symbole bloqué par le filtre de session ?
- Quelles sont les heures bloquées configurées ? (lire dans config.yaml et overrides.yaml)
- L'heure actuelle est-elle dans une plage bloquée ?

### 4.6 — Daily loss limit
Chercher `DAILY_LOSS` ou `daily_loss_limit` ou `daily_loss_abs` ou `daily-abs-guard`.
- Un symbole est-il bloqué par la limite de perte journalière ?
- Quel est le PnL actuel vs la limite ?

### 4.7 — Guards actifs
Chercher `[GUARD]` ou `stop_all.flag` ou `target_met.flag`.
- Un guard global est-il actif ? Lire les fichiers dans `data/guards/`.

### 4.8 — Trade gate (anti-spam)
Chercher `_trade_gate_ok` ou `délai min` ou `max_trades_per_day` ou `max_trades_per_hour` ou `once_per_candle`.
- Un symbole est-il bloqué par l'anti-spam ?

### 4.9 — News freeze
Chercher `news_freeze` ou `is_frozen_now` ou `NEWS_GUARD` ou `econ_calendar`.
- Le trading est-il gelé à cause d'un événement économique ?

### 4.10 — Weekend guard
Chercher `weekend_guard` ou `WeekendGuard` ou `forex_weekend_guard`.
- Le weekend guard bloque-t-il le trading ? (ne devrait pas en semaine)

### 4.11 — Crypto bucket / correlation
Chercher `crypto_bucket` ou `correlation_conflict` ou `LIMIT` ou `position-limit`.
- Un plafond de position/volume/net est-il atteint ?

### 4.12 — HARD_FILTER résumé
Chercher `HARD_FILTER` ou `PASS` ou `REJECT`.
- Pour chaque symbole : PASS ou REJECT + raison exacte
- Compter le total de PASS vs REJECT sur les derniers cycles

---

## PHASE 5 — Analyse de l'exécution des trades (5 vérifications)

### 5.1 — Tentatives d'exécution
Chercher `execute_trade` ou `[EXEC]` ou `[TRADE]` ou `order_send` ou `place_order`.
- Combien de tentatives dans les logs ?

### 5.2 — Résultats d'exécution
Chercher `retcode` ou `ticket=` ou `TRADE_RETCODE`.
- Combien réussis (retcode=10009) vs échoués ?
- Quels retcodes d'erreur ?

### 5.3 — dry_run actif ?
Chercher `dry_run` ou `DRY_RUN` dans les logs ET dans les configs.
- Dans `config.yaml` : y a-t-il `dry_run: true` ?
- Dans les logs : y a-t-il `[DRY_RUN]` ou `mode: dry` ?

### 5.4 — Live guard (should_allow_live)
Chercher `should_allow_live` ou `live_guard` ou `insufficient_sample`.
- Le live guard bloque-t-il ? (devrait retourner True si <10 trades historiques)

### 5.5 — Circuit breaker (mt5_client)
Chercher `circuit_breaker` ou `CIRCUIT` ou `market_closed` ou `market not open`.
- Le circuit breaker du client MT5 est-il ouvert ?

---

## PHASE 6 — Analyse de la configuration (8 vérifications)

### 6.1 — min_score_for_proposal
Lire la valeur pour chaque symbole dans `overrides.yaml` (section `orchestrator.min_score_for_proposal`) et `profiles.yaml`.
- Valeurs typiques : 1.8 à 2.2
- **PROBLÈME** si > 2.5 (trop restrictif, aucun signal ne passe)

### 6.2 — min_confluence
Lire la valeur pour chaque symbole.
- Valeur typique : 2 à 3
- **PROBLÈME** si > 4 (trop restrictif)

### 6.3 — min_rr
Lire la valeur pour chaque symbole.
- Devrait être 0.80 (fixé en Round 3)
- **PROBLÈME** si > 1.5

### 6.4 — ATR multipliers (atr_sl_mult, atr_tp_mult)
Lire dans `overrides.yaml` pour chaque symbole.
- Calculer le R:R théorique = atr_tp_mult / atr_sl_mult
- **PROBLÈME** si R:R théorique < min_rr

### 6.5 — blocked_hours / prime_hours
Lire `blocked_hours_extended` dans `config.yaml` et `prime_hours_utc` / `blocked_hours_utc` dans `overrides.yaml`.
- L'heure actuelle (UTC) tombe-t-elle dans une plage bloquée ?

### 6.6 — Agents activés/désactivés
Lire `profiles.yaml` pour chaque symbole :
- Quels agents sont `enabled: true` vs `enabled: false` ?
- `fundamental` et `macro` devraient être `enabled: false` partout (Round 3)

### 6.7 — max_trades_per_day / max_trades_per_hour
Lire les limites configurées.
- Combien de trades aujourd'hui vs la limite ?

### 6.8 — Interval d'analyse (interval_secs)
Quel est l'intervalle entre cycles d'analyse ? (typique : 120s)
- **PROBLÈME** si > 600s (trop lent pour saisir les opportunités)

---

## PHASE 7 — Vérification des jobs schedulés (3 vérifications)

### 7.1 — _sync_history_job
Chercher `[SYNC]` dans les logs.
- **OK** : apparaît toutes les ~5 min
- **KO** : absent

### 7.2 — _send_status_report
Chercher `[REPORT]` dans les logs.
- **OK** : apparaît (premier rapport après 1-2h)
- **KO** : absent (mais normal si bot démarré depuis <2h)

### 7.3 — _auto_optimize_job / _nightly_backtest_and_optimize
Chercher `[AUTO-OPT]` ou `[NightlyOpt]` dans les logs.
- **OK** : apparaît à 21:05 UTC
- **KO** : absent (mais normal si pas encore 21:05)

---

## FORMAT DU RAPPORT

Produis le rapport EXACTEMENT dans ce format :

```
═══════════════════════════════════════════════════════════════════
RAPPORT DE SANTÉ EXHAUSTIF — [date/heure UTC]
Uptime depuis redémarrage : [durée]
═══════════════════════════════════════════════════════════════════

Statut global : 🟢 OPÉRATIONNEL / 🟡 DÉGRADÉ / 🔴 BLOQUÉ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. INFRASTRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. EVENT LOOP
   État : OK / KO
   Dernier cycle : [timestamp]
   Écart moyen entre cycles : [N]s
   Freeze détecté : oui/non (si oui : [timestamps])
   Symboles actifs : [N]/9 — [liste]

2. LOCK HYBRIDE MT5
   État : OK / KO
   Erreurs COM : [nombre]
   Détail : [commentaire]

3. POSITION MANAGER
   État : OK / KO
   Fréquence : toutes les [N]s
   Positions ouvertes : [nombre] ([détails])
   Erreurs : [nombre]

4. SCHEDULER APScheduler
   État : OK / KO
   Jobs actifs : [liste]
   Erreurs : [nombre]

5. ERREURS PYTHON
   Erreurs bloquantes : [nombre] — [liste]
   Erreurs non-bloquantes : [nombre] — [liste]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
B. CHAÎNE DE DÉCISION (par symbole)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────┬───────┬──────┬──────┬─────┬───────────┬──────────────────────────────┐
│ Symbole  │ Score │ Min  │ Conf │ R:R │ Résultat  │ Raison rejet (si REJECT)     │
├──────────┼───────┼──────┼──────┼─────┼───────────┼──────────────────────────────┤
│ BTCUSD   │ X.XX  │ X.XX │ X/X  │X.XX │ PASS/REJ  │                              │
│ ETHUSD   │       │      │      │     │           │                              │
│ SOLUSD   │       │      │      │     │           │                              │
│ BNBUSD   │       │      │      │     │           │                              │
│ XAUUSD   │       │      │      │     │           │                              │
│ EURUSD   │       │      │      │     │           │                              │
│ USDJPY   │       │      │      │     │           │                              │
│ SP500    │       │      │      │     │           │                              │
│ NAS100   │       │      │      │     │           │                              │
└──────────┴───────┴──────┴──────┴─────┴───────────┴──────────────────────────────┘

Total PASS : [N] / Total REJECT : [N]

Blocages détectés :
- Session filter : [symboles bloqués ou "aucun"]
- Daily loss : [symboles bloqués ou "aucun"]
- Guards : [flags actifs ou "aucun"]
- Trade gate : [symboles bloqués ou "aucun"]
- News freeze : [actif/inactif]
- Weekend guard : [actif/inactif]
- Crypto bucket : [symboles bloqués ou "aucun"]
- Cooldown : [symboles en cooldown ou "aucun"]
- Correlation : [conflits ou "aucun"]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
C. EXÉCUTION DES TRADES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tentatives : [N]
Réussis : [N] (retcode 10009)
Échoués : [N] — [retcodes + raisons]
dry_run : [actif/inactif]
Live guard : [état]
Circuit breaker : [état]

Si 0 trade exécuté, IDENTIFIER la cause racine :
→ [explication précise de pourquoi aucun trade ne passe, en traçant
   la chaîne complète : agents → score → HARD_FILTER → execute_trade]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
D. CONFIGURATION (anomalies détectées)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────┬────────────┬────────────┬─────────┬─────────┬─────────┬─────────────┐
│ Symbole  │ min_score  │ min_conflu │ min_rr  │ tp_mult │ sl_mult │ R:R théo    │
├──────────┼────────────┼────────────┼─────────┼─────────┼─────────┼─────────────┤
│ BTCUSD   │            │            │         │         │         │             │
│ ...      │            │            │         │         │         │             │
└──────────┴────────────┴────────────┴─────────┴─────────┴─────────┴─────────────┘

Anomalies :
- [liste de toute config suspecte : seuils trop hauts, heures bloquées
  couvrant les heures de trading, agents désactivés qui ne devraient pas
  l'être, etc.]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E. JOBS SCHEDULÉS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_sync_history_job    : OK / KO — dernier run [timestamp]
_send_status_report  : OK / KO / N/A (si <2h uptime)
_auto_optimize_job   : OK / KO / N/A (si pas encore 21:05)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
F. DIAGNOSTIC FINAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROBLÈMES IDENTIFIÉS (par ordre de criticité) :
1. [CRITIQUE] ...
2. [MAJEUR] ...
3. [MINEUR] ...

CAUSE RACINE DU 0 TRADE (si applicable) :
→ [explication en 1-3 phrases de la raison principale pour laquelle
   aucun trade ne s'exécute, avec les valeurs exactes observées]

RECOMMANDATIONS :
1. ...
2. ...
3. ...

═══════════════════════════════════════════════════════════════════
```

## RÈGLES STRICTES

1. **Ne modifie AUCUN fichier.** Ce prompt est 100% lecture seule.
2. **Ne fais AUCUNE hypothèse.** Chaque affirmation doit être étayée par une ligne de log ou une valeur de config que tu as lue.
3. **Si les logs sont insuffisants** (<5 min de données), indique-le clairement et donne les résultats partiels.
4. **Si un fichier n'existe pas**, note-le et passe au suivant.
5. **Cite les lignes de log exactes** pour chaque problème identifié (avec timestamp).
6. **Le diagnostic final doit être actionnable** : pour chaque problème, indiquer précisément quoi corriger.
