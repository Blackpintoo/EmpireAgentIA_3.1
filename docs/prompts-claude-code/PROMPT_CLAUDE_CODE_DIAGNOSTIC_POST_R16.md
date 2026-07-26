# PROMPT CLAUDE CODE — Diagnostic post-Round 16

## Contexte

Round 16 a ajouté 3 fixes ciblant le spam d'ordres et le durcissement momentum :
- R16 FIX 1 : **Anti-Spam ORDER_SEND** — triple protection :
  - 1a : `_last_proposal = None` après consommation (proposal one-shot)
  - 1b : Guard `[ANTI_SPAM]` si position déjà ouverte sur le même symbole
  - 1c : `_last_exec_ts` mis à jour même en cas d'échec ORDER_SEND
- R16 FIX 2 : **Momentum Anti-Streak** — dict `_MOMENTUM_STREAK`, bloque "net neutre" après 3+ INVERSE consécutifs
- R16 FIX 3 : **RISK_CAP log cleanup** — alerte `_point_val=1.0 (défaut)` exclut les indices avec override

**Fixes précédents toujours actifs :**
- R15 : MOMENTUM_CHECK, RISK_CAP indices override, Anti-QUICK_REVERSAL cooldown, HARD_FILTER .4f, [DECISION] log
- R14 : ENTRY_REFRESH (R:R préservé 100%), DIR_CHECK
- R13 : HARD_FILTER 3.8 (40-70% rejet)
- R12 : Outcome tracker
- Fix : `regime_label` → `_regime_label`, `counter_trend_min_score` = 6.0

**Objectif** : Vérifier que le spam ORDER_SEND est éliminé, que le momentum anti-streak bloque les faux PASS, et mesurer l'impact sur le P&L. Aucun fichier ne doit être modifié.

**Référence P&L pré-R16 (24 mars) :**
- 15 trades, 5 wins (4 TP + 1 trailing), 9 SL, 1 BE
- Hit rate : 33%
- Avg $/win : $53
- P&L net : -$445
- 3 QUICK_REVERSALS : -$344
- 67 ORDER_SEND spam SP500 en 3h
- 1 faux PASS momentum XAUUSD → -$297.50

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 3000 lignes du log
tail -n 3000 logs/empire_agent.log

# 1b. ANTI_SPAM — LE FIX CLÉ R16
grep -i "ANTI_SPAM" logs/empire_agent.log

# 1c. ORDER_SEND — compter les occurrences par symbole
grep -i "ORDER_SEND\|order_send" logs/empire_agent.log | tail -30

# 1d. Comptage ORDER_SEND par symbole (vérif anti-spam)
grep -c "ORDER_SEND" logs/empire_agent.log

# 1e. MOMENTUM_CHECK avec streak
grep -i "MOMENTUM_CHECK" logs/empire_agent.log | tail -30

# 1f. streak dans les logs momentum
grep -i "streak" logs/empire_agent.log

# 1g. COOLDOWN + QUICK_REVERSAL
grep -i "COOLDOWN\|QUICK_REVERSAL" logs/empire_agent.log

# 1h. RISK_CAP — vérif cleanup faux-positif
grep -i "RISK_CAP" logs/empire_agent.log | tail -20

# 1i. ENTRY_REFRESH (contrôle R14)
grep -i "ENTRY_REFRESH" logs/empire_agent.log | tail -20

# 1j. DECISION log
grep -i "\[DECISION\]" logs/empire_agent.log | tail -20

# 1k. HARD_FILTER
grep -i "HARD_FILTER" logs/empire_agent.log | tail -20

# 1l. Outcome tracker
grep -i "\[OUTCOME\]" logs/empire_agent.log | tail -30

# 1m. Trades exécutés
grep -i "order_send\|retcode\|ticket=" logs/empire_agent.log | tail -20

# 1n. trade_outcomes.csv
type data\trade_outcomes.csv

# 1o. tracked_positions.json
type data\tracked_positions.json

# 1p. Kill switch
type data\daily_loss_state.json

# 1q. Erreurs / Tracebacks
grep -i "Traceback\|Error\|Exception" logs/empire_agent.log | tail -20

# 1r. _last_proposal = None (vérif consommation)
grep -i "Aucun payload compatible" logs/empire_agent.log | tail -20
```

---

## PHASE 2 — ANTI-SPAM ORDER_SEND ⭐⭐⭐ PRIORITÉ #1

### 2.1 — Spam éliminé ?

Compter les ORDER_SEND par symbole sur la journée :
```
┌─────────┬───────────────────┬──────────────────────┐
│ Symbole │ ORDER_SEND count  │ Attendu (normal)     │
├─────────┼───────────────────┼──────────────────────┤
│ SP500   │                   │ ≤ 5 (était 67 le 24) │
│ NAS100  │                   │ ≤ 5                  │
│ BTCUSD  │                   │ ≤ 5                  │
│ ...     │                   │                      │
│ TOTAL   │                   │ ≤ 30 (était 67+)     │
└─────────┴───────────────────┴──────────────────────┘
```

### 2.2 — Les 3 gardes fonctionnent-ils ?

**Guard 1a — Proposal consommée :**
- Chercher `Aucun payload compatible en mémoire` → signifie que `_last_proposal` était `None` quand un 2e cycle a tenté d'exécuter
- Combien d'occurrences ? Si > 0, le fix fonctionne

**Guard 1b — Position déjà ouverte :**
- Chercher `[ANTI_SPAM]` :
  - `position(s) déjà ouverte(s) → pas de nouvel ordre` → guard actif
  - Combien d'occurrences ?

**Guard 1c — _last_exec_ts en cas d'échec :**
- Vérifier si des retcodes d'échec (10016, etc.) sont suivis d'un silence de 300s (pas de re-tentative immédiate)

### 2.3 — Fills multiples ?

Vérifier qu'il n'y a PAS de positions doublons (2 positions ouvertes simultanément sur le même symbole dans la même direction) :
- `tracked_positions.json` : chaque symbole apparaît au max 1 fois ?
- `positions_get` dans les logs : pas de doublon ?

---

## PHASE 3 — MOMENTUM ANTI-STREAK ⭐⭐ PRIORITÉ #2

### 3.1 — Streak actif ?

Chercher `streak=` dans les logs momentum :
- `streak=1`, `streak=2`, ... → compteur incrémenté
- `BLOQUÉ car streak=N INVERSE consécutifs` → net neutre bloqué après streak ≥ 3

### 3.2 — Tableau des streaks

```
┌─────────┬──────────────┬───────────┬──────────────────────────────────┐
│ Symbole │ Direction    │ Max streak│ Action prise                      │
├─────────┼──────────────┼───────────┼──────────────────────────────────┤
│         │              │           │                                  │
└─────────┴──────────────┴───────────┴──────────────────────────────────┘
```

### 3.3 — Faux PASS éliminés ?

Le 24 mars, XAUUSD BUY avait 14 INVERSE puis 1 "net neutre → PASS" → SL.
Aujourd'hui, vérifier si des situations similaires (streak ≥ 3 + net neutre) sont correctement bloquées.

Compter :
- Trades "net neutre → PASS" autorisés (streak < 3) : combien ?
- Trades "net neutre → BLOQUÉ" (streak ≥ 3) : combien ?

---

## PHASE 4 — RISK_CAP LOG CLEANUP ⭐

### 4.1 — Faux-positif éliminé ?

Chercher `_point_val=1.0 (défaut)` dans les logs :
- Si SP500/NAS100 N'apparaissent PAS → fix OK
- Si SP500/NAS100 apparaissent encore → fix pas actif

Chercher `point_val override indices` :
- Toujours présent pour SP500/NAS100 → override actif

---

## PHASE 5 — P&L — LE TEST DÉCISIF

### 5.1 — Résultats des trades via trade_outcomes.csv

Pour chaque trade clos aujourd'hui :
```
┌────────────┬─────────┬──────────┬──────────┬──────────┬───────────┬─────────┬──────────────────┐
│ Ticket     │ Symbole │ Exit     │ P&L      │ R-mult   │ Durée min │ RR fill │ Note             │
├────────────┼─────────┼──────────┼──────────┼──────────┼───────────┼─────────┼──────────────────┤
│            │         │          │          │          │           │         │                  │
└────────────┴─────────┴──────────┴──────────┴──────────┴───────────┴─────────┴──────────────────┘
```

### 5.2 — Métriques de comparaison

```
┌──────────────┬────────┬───────────┬────────────┬───────────┬────────────┬─────────────┐
│ Jour         │ Trades │ Avg $/win │ P&L net    │ Hit rate  │ QR losses  │ ORDER spam  │
├──────────────┼────────┼───────────┼────────────┼───────────┼────────────┼─────────────┤
│ 16 mars      │ 12     │ $51/win   │ -$428      │ 67%       │ ?          │ ?           │
│ 17 mars      │ 13     │ $49/win   │ -$240      │ 62%       │ ?          │ ?           │
│ 23 mars R14  │ 9      │ $124/win  │ -$668      │ 22%       │ -$627      │ ?           │
│ 24 mars R15  │ 15     │ $53/win   │ -$445      │ 33%       │ -$344      │ 67          │
│ Auj. R16     │        │           │            │           │            │             │
└──────────────┴────────┴───────────┴────────────┴───────────┴────────────┴─────────────┘
```

**Cibles R16 :**
- Hit rate > 35%
- 0 QUICK_REVERSAL dû à un faux PASS momentum
- ORDER_SEND total ≤ 30 (vs 67+)
- P&L net meilleur que -$445
- 0 position doublon

---

## PHASE 6 — CONTRÔLES R14-R15 (toujours actifs)

### 6.1 — ENTRY_REFRESH
- Nombre de [ENTRY_REFRESH] : [N]
- R:R préservé : [oui/non]

### 6.2 — HARD_FILTER
- PASS : [N] | REJECT : [N] | Taux : [N]% (cible 40-70%)

### 6.3 — Anti-QUICK_REVERSAL
- QR détectés : [N]
- Cooldowns activés : [N]
- Trades bloqués par cooldown : [N]

### 6.4 — Outcome Tracker
- Clôtures aujourd'hui : [N]
- trade_outcomes.csv total : [N] entrées

---

## PHASE 7 — INFRASTRUCTURE

- Event loop : 9/9 symboles ?
- Lock COM : 0 erreurs ?
- Kill switch : déclenché ?
- regime_label : 0 erreurs ?
- Tracebacks : 0 ?
- retcode 10016 : combien ?
- Finnhub 403 : toujours présent ?

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT POST-ROUND 16 — [date/heure UTC]
═══════════════════════════════════════════════════════════════════

━━━ A. ANTI-SPAM ORDER_SEND ⭐⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ORDER_SEND total aujourd'hui : [N] (était 67+ le 24 mars)

Par symbole :
┌─────────┬───────────────────┐
│ Symbole │ ORDER_SEND count  │
├─────────┼───────────────────┤
│         │                   │
└─────────┴───────────────────┘

Gardes R16 :
- Proposal consommée (None)     : [N] rejets "Aucun payload"
- [ANTI_SPAM] position ouverte  : [N] blocages
- _last_exec_ts échec           : [N] (vérifié par absence de spam 300s)

Positions doublons : [0 attendu]

VERDICT ANTI-SPAM :
- ✅ Spam éliminé / ⚠️ Réduit / ❌ Toujours présent

━━━ B. MOMENTUM ANTI-STREAK ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Streaks max observés :
┌─────────┬──────────────┬───────────┐
│ Symbole │ Direction    │ Max streak│
├─────────┼──────────────┼───────────┤
│         │              │           │
└─────────┴──────────────┴───────────┘

"Net neutre" bloqués par streak ≥ 3 : [N]
"Net neutre" passés (streak < 3)     : [N]
Résultat des "net neutre" passés     : [TP/SL/en cours]

VERDICT MOMENTUM STREAK :
- ✅ Streak actif, faux PASS éliminés / ⚠️ Partiel / ❌ Inactif

━━━ C. RISK_CAP LOG CLEANUP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Faux-positif "point_val=1.0 (défaut)" pour indices : [oui/non]
Override actif pour SP500/NAS100 : [oui/non]

VERDICT : ✅ Nettoyé / ❌ Toujours présent

━━━ D. P&L — TEST DÉCISIF ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Trades clos aujourd'hui : [N]
TP wins   : [N] → +$[total] (avg $[X]/win)
Trailing  : [N] → +$[total]
SL losses : [N] → -$[total]
BE        : [N] → -$[total]
P&L net   : $[total]

Comparaison :
┌──────────────┬────────┬───────────┬────────────┬───────────┬────────────┬─────────────┐
│ Jour         │ Trades │ Avg $/win │ P&L net    │ Hit rate  │ QR losses  │ ORDER spam  │
├──────────────┼────────┼───────────┼────────────┼───────────┼────────────┼─────────────┤
│ 23 mars R14  │ 9      │ $124      │ -$668      │ 22%       │ -$627      │ ?           │
│ 24 mars R15  │ 15     │ $53       │ -$445      │ 33%       │ -$344      │ 67          │
│ Auj. R16     │        │           │            │           │            │             │
└──────────────┴────────┴───────────┴────────────┴───────────┴────────────┴─────────────┘

VERDICT P&L :
- ✅ Hit rate > 35% ET spam éliminé → R16 fonctionne
- ⚠️ Hit rate stable mais spam réduit → progrès partiel
- ❌ Spam toujours présent → investiguer

━━━ E. CONTRÔLES R14-R15 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ENTRY_REFRESH    : [N] refreshs, R:R préservé [oui/non]
HARD_FILTER      : PASS [N] / REJECT [N] / Taux [N]%
Anti-QR          : [N] QR détectés, [N] cooldowns, [N] bloqués
Outcome tracker  : [N] clôtures ([N] total csv)

━━━ F. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Event loop    : [OK/KO]
Lock COM      : [OK/KO]
Kill switch   : [oui/non]
regime_label  : [0 erreurs]
Tracebacks    : [N]
retcode 10016 : [N]

━━━ G. BILAN ROUND 16 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────────────────────────┬───────────┬──────────────────────────────────────────┐
│ Fix                          │ Statut    │ Preuve                                   │
├──────────────────────────────┼───────────┼──────────────────────────────────────────┤
│ R16 Anti-Spam ORDER_SEND     │ ✅/❌/⚠️  │                                          │
│ R16 Momentum Anti-Streak     │ ✅/❌/⚠️  │                                          │
│ R16 RISK_CAP log cleanup     │ ✅/❌/⚠️  │                                          │
│ R15 MOMENTUM_CHECK           │ ✅/❌/⚠️  │                                          │
│ R15 RISK_CAP indices         │ ✅/❌/⚠️  │                                          │
│ R15 Anti-QUICK_REVERSAL      │ ✅/❌/⚠️  │                                          │
│ R14 ENTRY_REFRESH            │ ✅/❌/⚠️  │                                          │
│ R13 HARD_FILTER 3.8          │ ✅/❌/⚠️  │                                          │
│ R12 Outcome tracker          │ ✅/❌/⚠️  │                                          │
│ regime_label fix             │ ✅/❌/⚠️  │                                          │
└──────────────────────────────┴───────────┴──────────────────────────────────────────┘

IMPACT R16 vs 24 mars :
- ORDER_SEND spam : [N] (vs 67)
- Faux PASS momentum : [N] (vs 1 → -$297)
- Hit rate : [X]% (vs 33%)
- P&L net : $[X] (vs -$445)

PROBLÈMES RESTANTS :
1. ...

RECOMMANDATIONS :
1. ...
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **ANTI-SPAM et MOMENTUM STREAK sont les 2 priorités** — c'est ce qui prouve le R16.
3. **Cite les lignes de log exactes.**
4. **Si aucun [ANTI_SPAM]** dans les logs → le bot n'a pas été redémarré avec R16. Signale-le.
5. **Si ORDER_SEND > 30 total** → le spam n'est pas éliminé. Investiguer pourquoi.
6. **Comparer IMPÉRATIVEMENT** avec le 24 mars : 67 spam, 33% hit rate, -$445 P&L.
7. **Vérifier 0 position doublon** (même symbole, même direction, 2 tickets).
