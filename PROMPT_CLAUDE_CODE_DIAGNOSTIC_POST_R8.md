# PROMPT CLAUDE CODE — Diagnostic EXHAUSTIF post-Round 8

## Contexte

EmpireAgentIA_3 a reçu 8 rounds de corrections (Rounds 3-8). Le bot gère 9 symboles via MetaTrader 5 COM. Les corrections incluent :
- R3-R6 : Lock hybride MT5 (22 points de protection COM), fix agents, R:R recalculé
- R7 : EventGuard RLock (deadlock réentrant corrigé)
- R8 : Kill switch séparé (realized -$400, floating -$800), garde-fou R:R dans execute_trade, outcome tracker protégé par le lock MT5

**Objectif** : Vérifier que TOUT fonctionne après Round 8. Aucun fichier ne doit être modifié.

---

## PHASE 1 — Collecte des données

Exécute TOUTES ces commandes et conserve les résultats :

```bash
# 1a. Dernières 1500 lignes du log principal
tail -n 1500 logs/empire_agent.log

# 1b. Fichier d'état du kill switch
type data\daily_loss_state.json

# 1c. Trades outcomes (Round 8 FIX 3)
type data\trade_outcomes.csv

# 1d. Trades log
type data\trades_log.csv

# 1e. Guards actifs
dir /b data\guards\*.flag 2>nul
type data\guards\stop_all.flag 2>nul
type data\guards\target_met.flag 2>nul

# 1f. Derniers signaux
type data\latest_signals.json

# 1g. Config kill switch
python -c "import yaml; c=yaml.safe_load(open('config/overrides.yaml')); print('GLOBAL risk:', c.get('GLOBAL',{}).get('risk',{})); print('kill_switch:', c.get('GLOBAL',{}).get('risk',{}).get('kill_switch',{}))"

# 1h. Compilation OK
python -m py_compile orchestrator/orchestrator.py
python -m py_compile utils/risk_manager.py
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile utils/event_guard.py

# 1i. Positions ouvertes
type data\open_positions.json 2>nul
```

---

## PHASE 2 — Event loop & infrastructure (5 checks)

### 2.1 — Event loop stable ?
Chercher les timestamps des cycles d'analyse pour chaque symbole. Calculer l'écart entre les 10 derniers cycles.
- **OK** : écarts 60-180s réguliers, 9 symboles actifs
- **KO** : trou >5 min ou symboles manquants

### 2.2 — Freezes ?
Chercher tout trou >5 min entre deux lignes de log consécutives.
- Lister chaque trou avec timestamps si trouvé

### 2.3 — Erreurs COM / Lock ?
Chercher : `COM error`, `RPC_E_WRONG_THREAD`, `deadlock`, `_MT5Lock`, `RuntimeError`, `MT5 not initialized`
- **OK** : 0 occurrence

### 2.4 — Erreurs Python ?
Chercher : `Traceback`, `CRITICAL`, `FATAL`, `Exception` (hors debug)
- Classifier : bloquante vs non-bloquante

### 2.5 — Scheduler APScheduler ?
Chercher : `SchedulerAlreadyRunningError`, `Missed job`
- **OK** : pas d'erreur

---

## PHASE 3 — Kill Switch Round 8 (4 checks) ⭐ PRIORITAIRE

### 3.1 — État actuel du kill switch
Lire `data/daily_loss_state.json` :
- `kill_switch_triggered` : true/false ?
- `realized_pnl` : combien ?
- `trigger_type` : "realized" ou "floating" ?
- `date` : correspond à aujourd'hui ?

### 3.2 — Seuils appliqués
Chercher `[KILL_SWITCH]` dans les logs :
- Le seuil realized est-il bien -$400 ?
- Le seuil floating est-il bien -$800 ?
- S'est-il déclenché ? Si oui, sur quel seuil et à quelle heure ?

### 3.3 — Durée de trading effective
Calculer le temps entre le premier et le dernier cycle d'analyse de la journée.
- **OK** : >4h de trading actif (vs <1h les jours précédents)
- **KO** : <2h → le kill switch se déclenche encore trop tôt

### 3.4 — P&L du jour
Chercher `realized_pnl`, `floating_pnl`, `total_pnl` dans les logs.
- Quel est le P&L réalisé actuel ?
- Le kill switch a-t-il encore bloqué le trading trop tôt ?

---

## PHASE 4 — Garde-fou R:R Round 8 (3 checks) ⭐ PRIORITAIRE

### 4.1 — RR_SAFETY activé ?
Chercher `[RR_SAFETY]` dans les logs.
- Si présent : pour quel symbole ? Quel R:R original ? Quel TP recalculé ?
- Si absent : soit tous les R:R étaient OK, soit le garde-fou n'est pas atteint

### 4.2 — R:R des trades exécutés
Pour chaque trade exécuté, calculer le R:R réel :
- R:R = |TP - entry| / |SL - entry|
- **OK** : tous les R:R >= 0.50
- **KO** : un R:R < 0.50 → le garde-fou n'a pas fonctionné

### 4.3 — SP500 spécifiquement
Si SP500 a tradé, vérifier que le TP n'est plus à 1 point de l'entrée.
- Comparer avec le 12 mars : entry=6718.52, TP=6717.52 (R:R=0.01) → ce bug ne doit plus exister

---

## PHASE 5 — Trade Outcome Tracker Round 8 (3 checks) ⭐ PRIORITAIRE

### 5.1 — Tracker actif ?
Chercher `[OUTCOME]` dans les logs.
- `[OUTCOME] Démarrage de la boucle de surveillance` → tracker démarré
- `[OUTCOME] Nouvelle position trackée` → positions détectées
- `[OUTCOME] Trade cloture` → clôtures enregistrées

### 5.2 — trade_outcomes.csv rempli ?
Lire `data/trade_outcomes.csv` :
- **OK** : contient des entrées pour aujourd'hui (tickets, P&L, R-multiple)
- **KO** : vide ou absent → le tracker ne fonctionne toujours pas

### 5.3 — Deadlock du tracker ?
Si `[OUTCOME] Démarrage` est présent mais aucun `[OUTCOME] Nouvelle position` ni `[OUTCOME] Trade cloture` :
- Le tracker est probablement en deadlock sur un appel MT5
- Chercher si `_mt5_call_safe` est utilisé (Round 8 FIX 3)

---

## PHASE 6 — Chaîne de décision (9 checks)

### 6.1 — Scores des agents
Pour chaque symbole, noter le dernier score dans SCORE_DIAG.

### 6.2 — HARD_FILTER PASS vs REJECT
Compter le total de PASS vs REJECT depuis le dernier redémarrage.
- Taux de passage attendu : >50%

### 6.3 — Trades exécutés
Chercher `[TRADE]`, `[EXEC]`, `order_send`, `retcode`, `ticket=`.
- Combien de tentatives ? Combien de succès (retcode 10009) ?
- Quels symboles ? Quelles directions ?

### 6.4 — Erreur 10016 BNBUSD
Le 12 mars, BNBUSD avait 2 erreurs 10016 (stops invalides).
- Le problème persiste-t-il ?

### 6.5 — Blocages actifs
Lister pour chaque symbole s'il est bloqué par :
- Session filter / blocked_hours
- Daily loss / kill switch
- Cooldown
- News freeze / EventGuard
- Weekend guard
- Correlation / crypto bucket

### 6.6 — EventGuard (Round 7)
Chercher `[EVENT_GUARD]` dans les logs.
- Le RLock fonctionne-t-il ? (pas de freeze après HARD_FILTER PASS)
- Des événements HIGH bloquent-ils le trading ?

### 6.7 — Finnhub API
Chercher `Finnhub` et `403` dans les logs.
- L'erreur 403 persiste-t-elle ?

### 6.8 — Fear & Greed API
Chercher `Fear` et `SSL` dans les logs.
- Les erreurs SSL persistent-elles ?

### 6.9 — Position Manager
Chercher `PM_DIAG`.
- Fréquence : toutes les ~20s ?
- Erreurs PM ?

---

## PHASE 7 — Jobs schedulés (3 checks)

### 7.1 — _sync_history_job → chercher `[SYNC]`
### 7.2 — _send_status_report → chercher `[REPORT]`
### 7.3 — _auto_optimize_job → chercher `[AUTO-OPT]`

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT DE SANTÉ POST-ROUND 8 — [date/heure UTC]
Uptime : [durée depuis redémarrage]
═══════════════════════════════════════════════════════════════════

Statut global : 🟢 OPÉRATIONNEL / 🟡 DÉGRADÉ / 🔴 BLOQUÉ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A. INFRASTRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Event loop       : OK/KO — écart moyen [N]s — [N]/9 symboles actifs
Lock MT5 COM     : OK/KO — [N] erreurs
Position Manager : OK/KO — cycle [N]s
Scheduler        : OK/KO
Erreurs Python   : [N] bloquantes / [N] non-bloquantes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
B. ROUND 8 — KILL SWITCH ⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

État            : actif / non déclenché
Seuil realized  : -$[N] (attendu: -$400)
Seuil floating  : -$[N] (attendu: -$800)
P&L realized    : $[N]
P&L floating    : $[N]
Déclenché ?     : oui/non — si oui: [type] à [heure]
Durée trading   : [N]h [N]min (vs <1h avant R8)

VERDICT : ✅ Amélioration / ❌ Même problème / ⚠️ Partiel

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
C. ROUND 8 — GARDE-FOU R:R ⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[RR_SAFETY] activé  : [N] fois — symboles: [liste]
R:R des trades :
┌──────────┬───────┬─────────┬─────────┬─────────┬──────────────┐
│ Symbole  │ Dir   │ Entry   │ SL      │ TP      │ R:R calculé  │
├──────────┼───────┼─────────┼─────────┼─────────┼──────────────┤
│          │       │         │         │         │              │
└──────────┴───────┴─────────┴─────────┴─────────┴──────────────┘

VERDICT : ✅ Tous R:R >= 0.50 / ❌ R:R absurde détecté

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
D. ROUND 8 — OUTCOME TRACKER ⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tracker démarré       : oui/non
Positions trackées    : [N]
Clôtures enregistrées : [N]
trade_outcomes.csv    : [N] lignes (vs 0 avant R8)
Deadlock détecté      : oui/non

VERDICT : ✅ Tracker fonctionne / ❌ Toujours en deadlock

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E. TRADING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades tentés   : [N]
Trades réussis  : [N] (retcode 10009)
Trades échoués  : [N] — [retcodes + symboles]
HARD_FILTER     : [N] PASS / [N] REJECT (taux [N]%)
BNBUSD 10016    : résolu/persiste

Trades détaillés :
┌───────┬─────────┬──────┬─────────┬─────────┬─────────┬──────┬────────────┐
│ Heure │ Symbole │ Dir  │ Entry   │ SL      │ TP      │ R:R  │ Résultat   │
├───────┼─────────┼──────┼─────────┼─────────┼─────────┼──────┼────────────┤
│       │         │      │         │         │         │      │            │
└───────┴─────────┴──────┴─────────┴─────────┴─────────┴──────┴────────────┘

Digest P&L : $[N] | [N] trades | hit-rate [N]%

Blocages actifs :
- Kill switch    : [état]
- Cooldown       : [symboles]
- Session filter : [symboles]
- EventGuard     : [symboles]
- Autres         : [détails]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
F. JOBS SCHEDULÉS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_sync_history_job   : OK/KO — dernier run [timestamp]
_send_status_report : OK/KO/N/A
_auto_optimize_job  : OK/KO/N/A

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
G. DIAGNOSTIC FINAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BILAN ROUND 8 :
┌─────────────────────────┬───────────┬─────────────────────────┐
│ Fix                     │ Statut    │ Preuve                  │
├─────────────────────────┼───────────┼─────────────────────────┤
│ Kill switch séparé      │ ✅/❌/⚠️  │ [preuve dans les logs]  │
│ Garde-fou R:R           │ ✅/❌/⚠️  │ [preuve dans les logs]  │
│ Outcome tracker         │ ✅/❌/⚠️  │ [preuve dans les logs]  │
└─────────────────────────┴───────────┴─────────────────────────┘

PROBLÈMES RESTANTS (par criticité) :
1. [CRITIQUE] ...
2. [MAJEUR] ...
3. [MINEUR] ...

Si 0 trade : CAUSE RACINE identifiée →
Si trades mais pertes : ANALYSE des patterns →

RECOMMANDATIONS :
1. ...
2. ...
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **Cite les lignes de log exactes** pour chaque affirmation.
3. **Focus sur les 3 fixes Round 8** — chaque fix doit avoir un VERDICT clair (✅/❌/⚠️) avec preuve.
4. **Si les logs sont insuffisants** (<15 min de données), indique-le.
