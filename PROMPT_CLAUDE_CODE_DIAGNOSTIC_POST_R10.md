# PROMPT CLAUDE CODE — Diagnostic post-Round 10

## Contexte

Round 10 a ajouté 3 corrections :
- R10 FIX 1 : Outcome tracker persistance + réconciliation au démarrage
- R10 FIX 2 : HARD_FILTER min_score 5.0 → 4.0
- R10 FIX 3 : Finnhub fallback dans connectors/finnhub_calendar.py

**Objectif** : Vérifier les 3 fixes. Aucun fichier ne doit être modifié.

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 2000 lignes du log principal
tail -n 2000 logs/empire_agent.log

# 1b. Fichier de persistance du tracker (NOUVEAU R10)
type data\tracked_positions.json

# 1c. Trades outcomes (LE TEST CLÉ)
type data\trade_outcomes.csv

# 1d. Kill switch
type data\daily_loss_state.json

# 1e. Config HARD_FILTER actuelle
python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); print('hard_filters:', c.get('orchestrator',{}).get('hard_filters',{}))"

# 1f. Compilation
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile connectors/finnhub_calendar.py
```

---

## PHASE 2 — Outcome Tracker R10 ⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Fichier de persistance
Lire `data/tracked_positions.json` :
- **OK** : contient des positions avec ticket, symbol, sl, tp, etc.
- **KO** : absent, vide ou malformé

### 2.2 — Réconciliation au démarrage
Chercher `[OUTCOME] Réconciliation` dans les logs :
- `Chargé N positions trackées depuis le disque` → persistance chargée
- `N positions fermées pendant l'arrêt du bot` → closures détectées
- `#{ticket} ... P&L=... (fermé pendant l'arrêt du bot)` → clôture récupérée
- `Pas de positions sauvegardées — skip réconciliation` → premier run OK, normal
- `N clôtures récupérées, N positions restaurées` → réconciliation terminée

### 2.3 — Clôtures dans trade_outcomes.csv
Lire `data/trade_outcomes.csv` :
- **OK** : nouvelles entrées datées après le 14 mars
- **KO** : toujours les 3 entrées du 1er mars

### 2.4 — Retry R9 + Réconciliation R10
Chercher `[OUTCOME] Trade cloture` et `[OUTCOME] Deal non trouvé ... retry` :
- Combien de clôtures enregistrées en session ?
- Combien de retries nécessaires ?

### 2.5 — Résumé tracker
Compter :
- Positions trackées depuis le démarrage
- Clôtures via réconciliation (fermées pendant l'arrêt)
- Clôtures via poll normal (fermées en session)
- Clôtures via retry R9 (timing)

---

## PHASE 3 — HARD_FILTER R10

### 3.1 — Taux de rejet
Compter HARD_FILTER PASS vs REJECT.
- Taux attendu : 40-70%
- Si >80% : recommander de baisser à 3.5
- Si <20% : recommander de monter à 4.5

### 3.2 — Scores des PASS et REJECT
Pour les 5 derniers PASS et 5 derniers REJECT, noter le score et le symbole.

### 3.3 — Nombre de trades
Combien de trades exécutés vs les jours précédents :
- 13 mars : 14 trades (min_score 2.5)
- 14 mars (R9) : 2 trades (min_score 5.0)
- Aujourd'hui : ? trades (min_score 4.0)

---

## PHASE 4 — Finnhub R10

### 4.1 — Erreurs Finnhub
Chercher `[FINNHUB]` et `finnhub` dans les logs.
- `[FINNHUB] Désactivé après N erreurs` → fallback activé
- Combien d'erreurs 403 aujourd'hui ?

---

## PHASE 5 — Infrastructure rapide

### 5.1 — Event loop stable ? 9/9 symboles actifs ?
### 5.2 — Erreurs COM/Lock ? 0 attendu.
### 5.3 — Kill switch déclenché ?
### 5.4 — Erreurs Python bloquantes ?

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT POST-ROUND 10 — [date/heure UTC]
═══════════════════════════════════════════════════════════════════

━━━ A. OUTCOME TRACKER R10 ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Persistance (tracked_positions.json) : OK/KO — [N] positions
Réconciliation au démarrage          : [N] clôtures récupérées
Clôtures en session                  : [N]
trade_outcomes.csv                   : [N] entrées (total)
  Nouvelles depuis R10               : [N]

VERDICT : ✅ Tracker enfin complet / ⚠️ Partiel / ❌ Toujours cassé

━━━ B. HARD_FILTER R10 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PASS : [N] | REJECT : [N] | Taux rejet : [N]%
Trades exécutés : [N]

VERDICT : ✅ Équilibré / ⚠️ Ajuster / ❌ Toujours trop strict/permissif

━━━ C. FINNHUB R10 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Erreurs 403 : [N] (vs 3 R9 / 16 avant)
Fallback activé : oui/non

━━━ D. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Event loop : OK/KO | Lock COM : OK/KO | Kill switch : activé/non

━━━ E. BILAN ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────────────┬───────────┬────────────────────────┐
│ Fix                      │ Statut    │ Preuve                 │
├──────────────────────────┼───────────┼────────────────────────┤
│ Outcome tracker persist. │ ✅/❌/⚠️  │                        │
│ Outcome tracker reconc.  │ ✅/❌/⚠️  │                        │
│ HARD_FILTER 4.0          │ ✅/❌/⚠️  │                        │
│ Finnhub fallback         │ ✅/❌/⚠️  │                        │
└──────────────────────────┴───────────┴────────────────────────┘

PROBLÈMES RESTANTS :
1. ...

RECOMMANDATIONS :
1. ...
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **Cite les lignes de log exactes.**
3. **Focus sur le outcome tracker** — c'est LE test décisif du R10.
4. **Si le bot n'a pas encore été redémarré depuis R10**, signale-le : la réconciliation ne peut être testée qu'après un redémarrage.
