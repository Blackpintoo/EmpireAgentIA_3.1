# PROMPT CLAUDE CODE — Diagnostic EXHAUSTIF post-Round 9

## Contexte

EmpireAgentIA_3 a reçu 9 rounds de corrections (Rounds 3-9). Le bot gère 9 symboles via MetaTrader 5 COM. Les corrections Round 9 incluent :
- R9 FIX 1 : Outcome tracker retry (pending closures, 10 tentatives × 30s)
- R9 FIX 2 : HARD_FILTER seuils remontés (score 5.0, confluence 2.5, R:R 1.0)
- R9 FIX 3 : Plafond risque absolu $300/trade
- R9 FIX 4 : Log diagnostique LONG/SHORT scores
- R9 FIX 5 : Finnhub 403 fallback gracieux

**Objectif** : Vérifier que TOUT fonctionne après Round 9. Aucun fichier ne doit être modifié.

---

## PHASE 1 — Collecte des données

Exécute TOUTES ces commandes et conserve les résultats :

```bash
# 1a. Dernières 2000 lignes du log principal
tail -n 2000 logs/empire_agent.log

# 1b. Fichier d'état du kill switch
type data\daily_loss_state.json

# 1c. Trades outcomes (Round 9 FIX 1 — LE TEST CLÉ)
type data\trade_outcomes.csv

# 1d. Trades log
type data\trades_log.csv

# 1e. Guards actifs
dir /b data\guards\*.flag 2>nul
type data\guards\stop_all.flag 2>nul

# 1f. Derniers signaux
type data\latest_signals.json

# 1g. Config kill switch et risk
python -c "import yaml; c=yaml.safe_load(open('config/overrides.yaml')); print('GLOBAL risk:', c.get('GLOBAL',{}).get('risk',{})); print('kill_switch:', c.get('GLOBAL',{}).get('risk',{}).get('kill_switch',{}))"

# 1h. Config HARD_FILTER
python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); print('hard_filters:', c.get('orchestrator',{}).get('hard_filters',{}))"

# 1i. Compilation OK
python -m py_compile orchestrator/orchestrator.py
python -m py_compile utils/risk_manager.py
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile utils/event_guard.py

# 1j. Positions ouvertes
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

## PHASE 3 — Kill Switch (2 checks)

### 3.1 — État actuel du kill switch
Lire `data/daily_loss_state.json` :
- `kill_switch_triggered` : true/false ?
- `trigger_type` : "realized" ou "floating" ?
- Durée de trading avant déclenchement ?

### 3.2 — P&L du jour
Chercher `realized_pnl`, `floating_pnl`, `total_pnl` dans les logs.

---

## PHASE 4 — Outcome Tracker Round 9 (4 checks) ⭐ PRIORITAIRE

### 4.1 — Tracker actif ?
Chercher `[OUTCOME]` dans les logs.
- `[OUTCOME] Démarrage de la boucle de surveillance` → tracker démarré
- `[OUTCOME] Nouvelle position trackée` → positions détectées

### 4.2 — Retry mécanisme fonctionne ?
Chercher `retry` dans les logs `[OUTCOME]` :
- `[OUTCOME] Deal non trouvé ... retry 1/10` → le retry est actif
- `[OUTCOME] Deal toujours non trouvé ... retry N/10` → retry en cours
- `[OUTCOME] Abandon` → retries épuisés (deal vraiment introuvable)

### 4.3 — Clôtures enregistrées ?
Chercher `[OUTCOME] Trade cloture` dans les logs.
- **OK** : au moins 1 clôture enregistrée → le fix fonctionne !
- **KO** : 0 clôture malgré des positions fermées → problème plus profond

### 4.4 — trade_outcomes.csv rempli ?
Lire `data/trade_outcomes.csv` :
- **OK** : contient des entrées pour aujourd'hui (tickets, P&L, R-multiple)
- **KO** : vide ou absent

---

## PHASE 5 — HARD_FILTER Round 9 (3 checks) ⭐ PRIORITAIRE

### 5.1 — Taux de rejet
Compter `HARD_FILTER` PASS vs REJECT dans les logs.
- Taux de rejet attendu : 30-60%
- **OK** : >15% de rejet → le filtre fonctionne
- **KO si trop strict** : >80% de rejet → `min_score` trop haut
- **KO si trop permissif** : <10% de rejet → `min_score` encore trop bas

### 5.2 — Scores des signaux rejetés
Pour les signaux REJECT, noter le score et la raison :
- Rejet par `min_score` → les scores sont <5.0
- Rejet par `min_confluence` → confluence <2.5
- Rejet par `min_rr` → R:R <1.0

### 5.3 — Impact sur le nombre de trades
Compter le nombre total de trades exécutés vs le 13 mars (14 trades).
- Si 5-10 trades : bon équilibre
- Si 0-2 trades : trop strict
- Si >12 trades : encore trop permissif

---

## PHASE 6 — Risk Cap Round 9 (2 checks) ⭐ PRIORITAIRE

### 6.1 — Plafond activé ?
Chercher `[RISK_CAP]` dans les logs.
- Si présent : le plafond a empêché un trade surdimensionné → noter les détails
- Si absent : tous les trades étaient <$300 de risque → OK

### 6.2 — Risque des trades exécutés
Pour chaque trade exécuté, calculer le risque en USD :
- Risque = |entry - SL| × lots × point_value
- **OK** : tous les risques ≤ $300
- **KO** : un risque > $300 → le plafond n'a pas fonctionné

---

## PHASE 7 — Diagnostic Directionnel Round 9 (2 checks)

### 7.1 — SCORE_DIAG présent ?
Chercher `[SCORE_DIAG]` dans les logs.
- Si présent : noter pour chaque symbole le ratio LONG/SHORT

### 7.2 — Biais directionnel
Analyser les `[SCORE_DIAG]` :
- Pour chaque symbole : `avg(score_long)` vs `avg(score_short)`
- **Biais agents** : LONG >> SHORT systématiquement pour tous les symboles
- **Biais marché** : LONG >> SHORT seulement pour les indices (trending up)
- **Équilibré** : LONG ≈ SHORT → pas de biais

---

## PHASE 8 — Trading (6 checks)

### 8.1 — Trades exécutés
Chercher `[TRADE]`, `[EXEC]`, `order_send`, `retcode`, `ticket=`.
- Combien de tentatives ? Combien de succès (retcode 10009) ?

### 8.2 — R:R des trades
Pour chaque trade, calculer R:R = |TP - entry| / |SL - entry|
- **OK** : tous R:R >= 1.0 (nouveau seuil)

### 8.3 — Direction des trades
Compter LONG vs SHORT.
- Taux LONG attendu : 40-70% (vs 93% avant)
- Si toujours >85% LONG : le biais n'est pas dans le HARD_FILTER

### 8.4 — Finnhub 403
Chercher `[EVENT_GUARD] Finnhub désactivé` dans les logs.
- Si présent : Finnhub ne pollue plus → OK

### 8.5 — EventGuard
Chercher `[EVENT_GUARD]` dans les logs.
- Le RLock fonctionne-t-il ?
- Des événements HIGH bloquent-ils le trading ?

### 8.6 — Position Manager
Chercher `PM_DIAG`.

---

## PHASE 9 — Jobs schedulés (3 checks)

### 9.1 — _sync_history_job → chercher `[SYNC]`
### 9.2 — _send_status_report → chercher `[REPORT]`
### 9.3 — _auto_optimize_job → chercher `[AUTO-OPT]`

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT DE SANTÉ POST-ROUND 9 — [date/heure UTC]
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
B. ROUND 9 — OUTCOME TRACKER ⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tracker démarré       : oui/non
Positions trackées    : [N]
Retry activé          : oui/non — [N] retries vus
Clôtures enregistrées : [N] (vs 0 avant R9)
trade_outcomes.csv    : [N] lignes
Deadlock/timing       : résolu/persiste

VERDICT : ✅ Tracker complet / ⚠️ Retry actif mais pas de clôtures / ❌ Broken

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
C. ROUND 9 — HARD_FILTER ⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASS    : [N]
REJECT  : [N]
Taux rejet : [N]% (attendu: 30-60%)
Trades exécutés : [N] (vs 14 avant R9)

VERDICT : ✅ Filtre efficace / ⚠️ Trop strict / ⚠️ Encore trop permissif / ❌ Pas appliqué

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
D. ROUND 9 — RISK CAP ⭐
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[RISK_CAP] activé  : [N] fois
Max risque observé : $[N] (plafond: $300)

VERDICT : ✅ Risque contrôlé / ❌ Trade surdimensionné passé

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E. ROUND 9 — DIAGNOSTIC DIRECTIONNEL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[SCORE_DIAG] présent : oui/non
Ratio LONG/SHORT par symbole :
┌──────────┬──────────┬───────────┬───────────┬───────────────┐
│ Symbole  │ Avg LONG │ Avg SHORT │ Direction │ Biais ?       │
├──────────┼──────────┼───────────┼───────────┼───────────────┤
│          │          │           │           │               │
└──────────┴──────────┴───────────┴───────────┴───────────────┘

Taux LONG global : [N]% (vs 93% avant R9)

VERDICT : ✅ Équilibré / ⚠️ Biais modéré / ❌ Toujours >85% LONG

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
F. TRADING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades tentés   : [N]
Trades réussis  : [N] (retcode 10009)
Trades échoués  : [N] — [retcodes + symboles]
HARD_FILTER     : [N] PASS / [N] REJECT (taux [N]%)

Trades détaillés :
┌───────┬─────────┬──────┬─────────┬─────────┬─────────┬──────┬────────┬────────────┐
│ Heure │ Symbole │ Dir  │ Entry   │ SL      │ TP      │ R:R  │ Risk$  │ Résultat   │
├───────┼─────────┼──────┼─────────┼─────────┼─────────┼──────┼────────┼────────────┤
│       │         │      │         │         │         │      │        │            │
└───────┴─────────┴──────┴─────────┴─────────┴─────────┴──────┴────────┴────────────┘

Digest P&L : $[N] | [N] trades | hit-rate [N]%

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
G. DIAGNOSTIC FINAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BILAN ROUND 9 :
┌──────────────────────────────┬───────────┬─────────────────────────┐
│ Fix                          │ Statut    │ Preuve                  │
├──────────────────────────────┼───────────┼─────────────────────────┤
│ Outcome tracker retry        │ ✅/❌/⚠️  │ [preuve dans les logs]  │
│ HARD_FILTER seuils           │ ✅/❌/⚠️  │ [preuve dans les logs]  │
│ Risk cap $300                │ ✅/❌/⚠️  │ [preuve dans les logs]  │
│ Score LONG/SHORT diagnostic  │ ✅/❌/⚠️  │ [preuve dans les logs]  │
│ Finnhub fallback             │ ✅/❌/⚠️  │ [preuve dans les logs]  │
└──────────────────────────────┴───────────┴─────────────────────────┘

PROBLÈMES RESTANTS (par criticité) :
1. [CRITIQUE] ...
2. [MAJEUR] ...
3. [MINEUR] ...

Si 0 trade : CAUSE RACINE identifiée →
Si trades mais pertes : ANALYSE des patterns →
Si trop de rejets : AJUSTEMENT des seuils →

RECOMMANDATIONS :
1. ...
2. ...
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **Cite les lignes de log exactes** pour chaque affirmation.
3. **Focus sur les 5 fixes Round 9** — chaque fix doit avoir un VERDICT clair (✅/❌/⚠️) avec preuve.
4. **Si les logs sont insuffisants** (<30 min de données), indique-le.
5. **Attention au HARD_FILTER** : si le taux de rejet est >80%, recommande de baisser `min_score` à 4.0. Si <10%, recommande de monter à 6.0.
