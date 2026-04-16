# PROMPT CLAUDE CODE — Diagnostic 3 jours post-Round 16 (25-27 mars 2026)

## Contexte

Le bot tourne sans interruption depuis 3 jours avec tous les fixes R12-R16 actifs. L'objectif est d'évaluer la **tendance sur 3 jours** pour décider si des ajustements config sont nécessaires.

**Stack de fixes actifs :**
- R16 : Anti-Spam ORDER_SEND, Momentum Anti-Streak, RISK_CAP log cleanup
- R15 : MOMENTUM_CHECK, RISK_CAP indices override, Anti-QUICK_REVERSAL cooldown, HARD_FILTER .4f, [DECISION] log
- R14 : ENTRY_REFRESH (R:R préservé), DIR_CHECK
- R13 : HARD_FILTER 3.8
- R12 : Outcome tracker
- Fix : `_regime_label`, `counter_trend_min_score` = 6.0

**Données de référence :**

| Jour | Trades | Avg $/win | P&L net | Hit rate | QR losses | ORDER spam |
|------|--------|-----------|---------|----------|-----------|------------|
| 23 mars R14 | 9 | $124 | -$668 | 22% | -$627 | ? |
| 24 mars R15 | 15 | $53 | -$445 | 33% | -$344 | 67 |
| 25 mars R16 | 13 | $59 | -$835 | 15% | -$175 | 18 |
| 26 mars | ? | ? | ? | ? | ? | ? |
| 27 mars | ? | ? | ? | ? | ? | ? |

**Question clé** : Le hit rate de 15% du 25 mars était-il un outlier ou une tendance ? Si le hit rate moyen sur 3 jours est < 25%, il faudra ajuster les seuils config.

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 5000 lignes du log (3 jours)
tail -n 5000 logs/empire_agent.log

# 1b. trade_outcomes.csv COMPLET — source principale d'analyse
type data\trade_outcomes.csv

# 1c. MOMENTUM_CHECK
grep -i "MOMENTUM_CHECK" logs/empire_agent.log

# 1d. ANTI_SPAM
grep -i "ANTI_SPAM" logs/empire_agent.log

# 1e. COOLDOWN + QUICK_REVERSAL
grep -i "COOLDOWN\|QUICK_REVERSAL" logs/empire_agent.log

# 1f. streak
grep -i "streak" logs/empire_agent.log

# 1g. RISK_CAP
grep -i "RISK_CAP" logs/empire_agent.log | tail -20

# 1h. ENTRY_REFRESH
grep -i "ENTRY_REFRESH" logs/empire_agent.log | tail -20

# 1i. HARD_FILTER
grep -i "HARD_FILTER" logs/empire_agent.log | tail -30

# 1j. DECISION log
grep -i "\[DECISION\]" logs/empire_agent.log | tail -30

# 1k. SCORE_DIAG
grep -i "SCORE_DIAG" logs/empire_agent.log | tail -30

# 1l. ORDER_SEND — comptage total
grep -c "ORDER_SEND" logs/empire_agent.log

# 1m. ORDER_SEND par symbole
grep "ORDER_SEND" logs/empire_agent.log | grep -oP "\w+USD|SP500|NAS100" | sort | uniq -c | sort -rn

# 1n. Outcome tracker
grep -i "\[OUTCOME\]" logs/empire_agent.log | tail -40

# 1o. Kill switch
type data\daily_loss_state.json

# 1p. tracked_positions.json
type data\tracked_positions.json

# 1q. Erreurs
grep -i "Traceback\|Error\|Exception" logs/empire_agent.log | tail -30

# 1r. Restarts du bot (pour vérifier uptime 3 jours)
grep -i "Starting\|Initialisation\|Run polling" logs/empire_agent.log
```

---

## PHASE 2 — ANALYSE P&L SUR 3 JOURS ⭐⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Décomposer trade_outcomes.csv par jour

À partir de `trade_outcomes.csv`, calculer pour CHAQUE jour (25, 26, 27 mars) :

```
┌──────────────┬────────┬────────┬──────────┬───────────┬────────────┬───────────┬────────────┐
│ Jour         │ Trades │ TP win │ Trailing │ SL loss   │ BE         │ P&L net   │ Hit rate   │
├──────────────┼────────┼────────┼──────────┼───────────┼────────────┼───────────┼────────────┤
│ 25 mars      │        │        │          │           │            │           │            │
│ 26 mars      │        │        │          │           │            │           │            │
│ 27 mars      │        │        │          │           │            │           │            │
│ TOTAL 3j     │        │        │          │           │            │           │            │
└──────────────┴────────┴────────┴──────────┴───────────┴────────────┴───────────┴────────────┘
```

### 2.2 — Métriques clés sur 3 jours

Calculer :
- **Hit rate moyen** : (total wins) / (total trades)
- **Avg $/win** : total gains / nb wins
- **Avg $/loss** : total pertes / nb losses
- **Profit factor** : total gains / |total pertes|
- **R-mult moyen** : moyenne des R-mult de tous les trades
- **Expectancy par trade** : P&L net / total trades
- **Pire drawdown journalier** : la plus grosse perte sur un seul jour
- **QR losses total** : somme des trades SL en < 10 min

### 2.3 — Analyse par symbole sur 3 jours

```
┌─────────┬────────┬────────┬───────────┬───────────┬────────────┬───────────────────────┐
│ Symbole │ Trades │ Wins   │ P&L net   │ Hit rate  │ Avg $/win  │ Observation           │
├─────────┼────────┼────────┼───────────┼───────────┼────────────┼───────────────────────┤
│ XAUUSD  │        │        │           │           │            │                       │
│ SP500   │        │        │           │           │            │                       │
│ NAS100  │        │        │           │           │            │                       │
│ BTCUSD  │        │        │           │           │            │                       │
│ USDJPY  │        │        │           │           │            │                       │
│ SOLUSD  │        │        │           │           │            │                       │
│ LTCUSD  │        │        │           │           │            │                       │
│ AUDUSD  │        │        │           │           │            │                       │
│ BNBUSD  │        │        │           │           │            │                       │
└─────────┴────────┴────────┴───────────┴───────────┴────────────┴───────────────────────┘
```

**Identifier les symboles toxiques** : quels symboles ont un hit rate < 20% ou un P&L net très négatif sur 3 jours ? Ceux-ci sont candidats à être désactivés ou à avoir des filtres renforcés.

### 2.4 — Analyse par direction (LONG vs SHORT)

```
┌───────────┬────────┬────────┬───────────┬───────────┐
│ Direction │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────┼────────┼────────┼───────────┼───────────┤
│ LONG      │        │        │           │           │
│ SHORT     │        │        │           │           │
└───────────┴────────┴────────┴───────────┴───────────┘
```

Y a-t-il un biais directionnel ? (ex: les SHORT gagnent et les LONG perdent)

### 2.5 — Analyse par heure UTC

```
┌──────────┬────────┬────────┬───────────┬───────────┐
│ Heure    │ Trades │ Wins   │ P&L net   │ Hit rate  │
├──────────┼────────┼────────┼───────────┼───────────┤
│ 06-08    │        │        │           │           │
│ 08-10    │        │        │           │           │
│ 10-12    │        │        │           │           │
│ 12-14    │        │        │           │           │
│ 14-16    │        │        │           │           │
│ 16-18    │        │        │           │           │
└──────────┴────────┴────────┴───────────┴───────────┘
```

Y a-t-il des heures toxiques systématiquement perdantes ?

---

## PHASE 3 — FILTRES R15-R16 (contrôle)

### 3.1 — Momentum check sur 3 jours

- Total INVERSE bloqués : [N]
- Total "net neutre → PASS" : [N] → résultat (combien SL vs TP)
- Total "BLOQUÉ car streak ≥ 3" : [N]
- Max streak observé : [N]
- Le filtre momentum est-il trop agressif ? (bloque-t-il > 50% ?)

### 3.2 — Anti-Spam ORDER_SEND

- Total ORDER_SEND sur 3 jours : [N]
- Moyenne par jour : [N]
- Max par symbole/jour : [N]
- Positions doublons : [N] (doit être 0)

### 3.3 — Anti-QUICK_REVERSAL

- QR détectés sur 3 jours : [N]
- Cooldowns activés : [N]
- Trades bloqués par cooldown : [N]
- Total QR losses : $[X]

### 3.4 — HARD_FILTER

- Taux de rejet moyen sur 3 jours : [N]%
- Scores borderline observés (3.7x-3.8x) : [N]

### 3.5 — ENTRY_REFRESH

- Total refreshs sur 3 jours : [N]
- R:R préservé : 100% ? Si non, quels cas ?

---

## PHASE 4 — QUALITÉ DES AGENTS (diagnostic approfondi)

### 4.1 — Tracker vote distribution

À partir des logs [DECISION] et [HARD_FILTER], extraire les tracker_vote :
- Moyenne tracker_vote sur 3 jours : [X]
- % de trades avec tracker_vote < 0 : [N]%
- % de trades avec tracker_vote < -0.5 : [N]%

Si > 30% des trades ont un tracker_vote < -0.5, les agents sont systématiquement mauvais et le seuil tracker_contradiction devrait être baissé.

### 4.2 — Régimes de marché

À partir des logs [DECISION] et [SCORE_DIAG], analyser :
- Quels régimes sont les plus fréquents ? (trending_up, trending_down, volatile, quiet)
- Hit rate par régime ?
- Y a-t-il un régime où le bot est systématiquement perdant ?

### 4.3 — Confluence vs résultat

- Hit rate des trades avec confluence ≥ 4 vs confluence < 4 ?
- Hit rate des trades avec score ≥ 4.5 vs score < 4.5 ?

---

## PHASE 5 — INFRASTRUCTURE

- Uptime : 3 jours continus ? (vérifier les restarts)
- Event loop : 9/9 symboles stable ?
- Lock COM : 0 erreurs sur 3 jours ?
- Kill switch : déclenché à un moment ? Si oui, quand et combien de temps ?
- Tracebacks : 0 sur 3 jours ?
- retcode 10016 : combien au total ?
- Finnhub 403 : toujours présent ?

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT 3 JOURS POST-R16 — 25-27 mars 2026
═══════════════════════════════════════════════════════════════════

━━━ A. P&L SUR 3 JOURS ⭐⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Par jour :
┌──────────────┬────────┬────────┬──────────┬───────────┬────────────┬───────────┐
│ Jour         │ Trades │ Wins   │ Avg $/win│ P&L net   │ Hit rate   │ QR losses │
├──────────────┼────────┼────────┼──────────┼───────────┼────────────┼───────────┤
│ 25 mars      │ 13     │ 2      │ $59      │ -$835     │ 15%        │ -$175     │
│ 26 mars      │        │        │          │           │            │           │
│ 27 mars      │        │        │          │           │            │           │
│ TOTAL 3j     │        │        │          │           │            │           │
└──────────────┴────────┴────────┴──────────┴───────────┴────────────┴───────────┘

Métriques 3 jours :
- Hit rate moyen      : [X]%
- Avg $/win           : $[X]
- Avg $/loss          : -$[X]
- Profit factor       : [X]
- Expectancy/trade    : $[X]
- Pire drawdown jour  : -$[X] ([date])
- QR losses total     : -$[X]

VERDICT HIT RATE :
- ✅ > 30% moyen → hit rate OK, le 25 mars était un outlier
- ⚠️ 25-30% → limite, ajustement config recommandé
- ❌ < 25% → tendance confirmée, ajustements config NÉCESSAIRES

━━━ B. ANALYSE PAR SYMBOLE ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────┬────────┬────────┬───────────┬───────────┬─────────────────────┐
│ Symbole │ Trades │ Wins   │ P&L net   │ Hit rate  │ Recommandation      │
├─────────┼────────┼────────┼───────────┼───────────┼─────────────────────┤
│         │        │        │           │           │                     │
└─────────┴────────┴────────┴───────────┴───────────┴─────────────────────┘

Symboles toxiques (hit rate < 20% OU P&L < -$200 sur 3j) :
1. ...

━━━ C. ANALYSE PAR DIRECTION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌───────────┬────────┬────────┬───────────┬───────────┐
│ Direction │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────┼────────┼────────┼───────────┼───────────┤
│ LONG      │        │        │           │           │
│ SHORT     │        │        │           │           │
└───────────┴────────┴────────┴───────────┴───────────┘

━━━ D. ANALYSE PAR HEURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌──────────┬────────┬────────┬───────────┬───────────┐
│ Heure    │ Trades │ Wins   │ P&L net   │ Hit rate  │
├──────────┼────────┼────────┼───────────┼───────────┤
│          │        │        │           │           │
└──────────┴────────┴────────┴───────────┴───────────┘

Heures toxiques (hit rate < 15%) :
1. ...

━━━ E. FILTRES R15-R16 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Momentum INVERSE bloqués     : [N] / 3 jours
Momentum streak max          : [N]
"Net neutre" BLOQUÉ par streak: [N]
ORDER_SEND total             : [N] (avg [N]/jour)
Anti-QR cooldowns            : [N]
ENTRY_REFRESH                : [N], R:R préservé 100%
HARD_FILTER taux rejet       : [N]%

━━━ F. QUALITÉ AGENTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tracker vote moyen            : [X]
% trades avec tracker < -0.5  : [N]%
Régime dominant               : [X]
Hit rate par régime            : trending_up=[X]%, trending_down=[X]%, volatile=[X]%, quiet=[X]%
Hit rate confluence ≥ 4        : [X]%
Hit rate confluence < 4        : [X]%

━━━ G. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Uptime            : [3 jours continus / interruptions]
Event loop        : [OK/KO]
Lock COM          : [OK/KO]
Kill switch       : [déclenché ? quand ?]
Tracebacks        : [N]
retcode 10016     : [N]

━━━ H. RECOMMANDATIONS CONFIG ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Basé sur les données 3 jours, recommandations d'ajustement
dans config/config.yaml et config/overrides.yaml :

1. tracker_contradiction_threshold : [actuel] → [recommandé] ?
   Justification : [X]% des trades ont tracker < -0.5
2. min_score : [actuel 3.8] → [recommandé] ?
   Justification : hit rate des trades score < [X] est [Y]%
3. Symboles à désactiver/restreindre :
   [liste avec justification chiffrée]
4. Heures à bloquer :
   [liste avec justification chiffrée]
5. Direction restrictions par symbole :
   [liste si biais directionnel identifié]

CHAQUE recommandation doit être chiffrée avec les données des 3 jours.
Pas de recommandation sans preuve statistique.
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **L'analyse P&L sur 3 jours est la PRIORITÉ ABSOLUE.** C'est ce qui détermine si des ajustements sont nécessaires.
3. **Décomposer par jour, par symbole, par direction, par heure.** Les moyennes masquent les problèmes.
4. **Cite les chiffres exacts de trade_outcomes.csv.**
5. **Les recommandations config doivent être CHIFFRÉES** : "baisser X à Y car Z% des trades avec X > Y perdent".
6. **Ne recommande PAS de nouveau code** — le stack R12-R16 est complet. Seuls des ajustements config sont envisagés.
7. **Si le hit rate moyen 3 jours > 30%**, le 25 mars était un outlier → pas de changement urgent.
8. **Si le hit rate moyen 3 jours < 25%**, recommander des ajustements config précis.
