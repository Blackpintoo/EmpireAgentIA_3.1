# PROMPT CLAUDE CODE — Diagnostic post-Round 6

## Contexte

Le bot de trading EmpireAgentIA_3 vient de recevoir les corrections Rounds 3 à 6 :
- Round 3 : fix `_mt5_all_failed` faux positif, fundamental/macro désactivés, R:R recalculé
- Round 4 : 8 appels `asyncio.to_thread` MT5 protégés par le sémaphore
- Round 5 : lock hybride `_MT5Lock` (threading.Lock sous-jacent), PM et sync_history protégés
- Round 6 : 11 derniers appels MT5 protégés (22 points de lock au total)

Le bot vient d'être redémarré via `START_EMPIRE.bat`.

## Mission

Tu dois **lire les logs en temps réel** et produire un **rapport de santé complet** couvrant les 7 axes ci-dessous.

## Étapes

### 1. Lire les logs récents

```bash
# Dernières 500 lignes du log principal
tail -n 500 logs/empire_agent.log
```

Si le fichier est vide ou n'existe pas, chercher d'autres logs :
```bash
dir /s /b logs\*.log
dir /s /b *.log
```

### 2. Vérifier que l'event loop ne gèle PAS

Chercher dans les logs les timestamps des cycles d'analyse. Calculer l'écart entre cycles successifs.

**OK** : cycles espacés de 60-180s de façon régulière
**KO** : un trou de >5 minutes entre deux cycles, ou aucun cycle récent

### 3. Vérifier que le lock hybride `_MT5Lock` fonctionne

Chercher toute erreur liée à :
- `_GLOBAL_MT5_SEMAPHORE`
- `_MT5Lock`
- `threading.Lock`
- `acquire`
- `RuntimeError`
- `deadlock`
- `COM error`
- `RPC_E_WRONG_THREAD`

**OK** : aucune erreur de ce type
**KO** : erreurs de lock ou COM

### 4. Vérifier que le Position Manager tourne

Chercher `[PM` ou `PM_DIAG` ou `manage_open_positions` dans les logs.

**OK** : apparaît régulièrement (toutes les ~20s)
**KO** : absent ou erreurs

### 5. Vérifier les décisions de trading (HARD_FILTER)

Chercher les lignes contenant `HARD_FILTER` ou `PASS` ou `REJECT` ou `score=` ou `confluence=`.

Pour chaque symbole, noter :
- Score obtenu vs min_score requis
- Confluence obtenue vs min_confluence requis
- Raison du rejet si REJECT

**Résumer** : combien de PASS vs REJECT sur les derniers cycles, et pour quels symboles.

### 6. Vérifier si un trade a été exécuté

Chercher `[TRADE]`, `[EXECUTE]`, `order_send`, `retcode`, `ticket=`.

**OK** : au moins un trade exécuté ou une tentative d'exécution
**KO** : 0 tentative

Si 0 trade, chercher la raison dans la chaîne de décision :
- Le score est-il suffisant ? (>= min_score, typiquement 1.8-2.2)
- La confluence est-elle suffisante ? (>= min_confluence, typiquement 2-3)
- Le R:R est-il suffisant ? (>= 0.80)
- Y a-t-il un blocage de session ? (`session_filter`, `blocked_hours`, `prime_hours`)
- Y a-t-il un guard actif ? (`GUARD`, `COOLDOWN`, `DAILY_LOSS`, `stop_all.flag`)
- Y a-t-il un gate actif ? (`_trade_gate_ok`, `max_trades_per_day`)

### 7. Vérifier les jobs schedulés (Round 6 fix)

Chercher `[REPORT]`, `[AUTO-OPT]`, `[NightlyOpt]`, `[SYNC]` dans les logs.

**OK** : `[SYNC]` apparaît toutes les 5 min (sync_history fonctionne)
**KO** : absent

## Format du rapport

Produire le rapport EXACTEMENT dans ce format :

```
═══════════════════════════════════════════════════════════
RAPPORT DE SANTÉ — [date/heure UTC]
═══════════════════════════════════════════════════════════

Statut global : 🟢 OPÉRATIONNEL / 🟡 DÉGRADÉ / 🔴 BLOQUÉ

1. EVENT LOOP
   État : OK / KO
   Dernier cycle : [timestamp]
   Écart moyen entre cycles : [N]s
   Détail : [commentaire]

2. LOCK HYBRIDE MT5
   État : OK / KO
   Erreurs COM : [nombre]
   Détail : [commentaire]

3. POSITION MANAGER
   État : OK / KO
   Fréquence : toutes les [N]s
   Détail : [commentaire]

4. DÉCISIONS DE TRADING (derniers cycles)
   ┌──────────┬───────┬────────────┬────────┬─────────────────────┐
   │ Symbole  │ Score │ Confluence │ R:R    │ Résultat            │
   ├──────────┼───────┼────────────┼────────┼─────────────────────┤
   │ BTCUSD   │ X.XX  │ X          │ X.XX   │ PASS / REJECT (why) │
   │ ...      │       │            │        │                     │
   └──────────┴───────┴────────────┴────────┴─────────────────────┘
   Total PASS : [N] / Total REJECT : [N]

5. TRADES EXÉCUTÉS
   État : [N] trades tentés / [N] réussis
   Détail : [tickets, symboles, retcodes]
   Si 0 trade : [raison identifiée dans la chaîne de décision]

6. JOBS SCHEDULÉS
   _send_status_report : OK / KO
   _sync_history_job   : OK / KO
   _auto_optimize_job  : OK / KO (prévu à 21:05)

7. PROBLÈMES IDENTIFIÉS
   [Liste numérotée des problèmes trouvés, par ordre de criticité]
   Si aucun : "Aucun problème identifié."

═══════════════════════════════════════════════════════════
```

## IMPORTANT

- Ne modifie AUCUN fichier. Ce prompt est en **lecture seule**.
- Si les logs sont insuffisants (bot démarré il y a <5 min), indique-le et donne les résultats partiels disponibles.
- Si le fichier de log n'existe pas, cherche dans `data/`, `output/`, ou à la racine du projet.
