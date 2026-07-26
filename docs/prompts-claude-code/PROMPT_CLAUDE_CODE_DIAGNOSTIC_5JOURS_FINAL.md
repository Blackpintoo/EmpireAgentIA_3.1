# PROMPT CLAUDE CODE — Diagnostic 5 jours (28 mars - 2 avril 2026)

## Contexte

Le bot tourne avec le stack complet R12-R16 + ajustements config du 28 mars :
- **Config 28 mars** : `min_score_for_proposal` monté à 5.0 pour NAS100 et BNBUSD (symboles toxiques identifiés)
- R16 : Anti-Spam ORDER_SEND, Momentum Anti-Streak, RISK_CAP log cleanup
- R15 : MOMENTUM_CHECK, RISK_CAP indices override (1.0), Anti-QUICK_REVERSAL cooldown, HARD_FILTER .4f, [DECISION] log
- R14 : ENTRY_REFRESH (R:R préservé), DIR_CHECK
- R13 : HARD_FILTER 3.8
- R12 : Outcome tracker
- Fix : `_regime_label`, `counter_trend_min_score` = 6.0

**Objectif** : Évaluer sur 5 jours si l'ensemble des modifications (code R12-R16 + config) fonctionne correctement. Produire un bilan complet avec tendance et stabilité.

**Données de référence historique :**

| Jour | Trades | Avg $/win | P&L net | Hit rate | QR losses | ORDER spam |
|------|--------|-----------|---------|----------|-----------|------------|
| 23 mars R14 | 9 | $124 | -$668 | 22% | -$627 | ? |
| 24 mars R15 | 15 | $53 | -$445 | 33% | -$344 | 67 |
| 25 mars R16 | 14 | $109 | -$626 | 21% | -$175 | 18 |
| 26 mars | 16 | $161 | +$1,336 | 63% | -$103 | ~18 |
| 27 mars | 13 | $85 | +$14 | 62% | -$208 | ~16 |
| 28 mars → 2 avril | ? | ? | ? | ? | ? | ? |

**Questions clés :**
1. Le hit rate se stabilise-t-il > 40% ?
2. Le P&L net est-il positif sur 5 jours ?
3. Les ajustements config NAS100/BNBUSD ont-ils réduit les pertes ?
4. Tous les fixes R12-R16 sont-ils toujours stables ?
5. Y a-t-il de nouveaux bugs ou comportements inattendus ?

---

## PHASE 1 — Collecte des données

```bash
# 1a. Dernières 10000 lignes du log (5 jours)
tail -n 10000 logs/empire_agent.log

# 1b. trade_outcomes.csv COMPLET — source principale
type data\trade_outcomes.csv

# 1c. MOMENTUM_CHECK complet
grep -i "MOMENTUM_CHECK" logs/empire_agent.log

# 1d. ANTI_SPAM
grep -i "ANTI_SPAM" logs/empire_agent.log

# 1e. COOLDOWN + QUICK_REVERSAL
grep -i "COOLDOWN\|QUICK_REVERSAL" logs/empire_agent.log

# 1f. streak momentum
grep -i "streak" logs/empire_agent.log

# 1g. RISK_CAP
grep -i "RISK_CAP" logs/empire_agent.log | tail -30

# 1h. ENTRY_REFRESH
grep -i "ENTRY_REFRESH" logs/empire_agent.log | tail -30

# 1i. HARD_FILTER
grep -i "HARD_FILTER" logs/empire_agent.log | tail -40

# 1j. DECISION log
grep -i "\[DECISION\]" logs/empire_agent.log | tail -40

# 1k. SCORE_DIAG
grep -i "SCORE_DIAG" logs/empire_agent.log | tail -40

# 1l. ORDER_SEND — comptage total
grep -c "ORDER_SEND" logs/empire_agent.log

# 1m. ORDER_SEND par symbole
grep "ORDER_SEND" logs/empire_agent.log | grep -oP "\w+USD|SP500|NAS100|BNBUSD" | sort | uniq -c | sort -rn

# 1n. Outcome tracker
grep -i "\[OUTCOME\]" logs/empire_agent.log | tail -50

# 1o. Kill switch
type data\daily_loss_state.json

# 1p. tracked_positions.json
type data\tracked_positions.json

# 1q. Erreurs / Tracebacks
grep -i "Traceback\|Error\|Exception" logs/empire_agent.log | tail -40

# 1r. Restarts du bot (uptime)
grep -i "Starting\|Initialisation\|Run polling" logs/empire_agent.log

# 1s. NAS100 et BNBUSD spécifiquement (impact config)
grep -i "NAS100\|BNBUSD" logs/empire_agent.log | grep -i "HARD_FILTER\|ORDER_SEND\|DECISION\|REJET\|score" | tail -30

# 1t. Config vérification (min_score_for_proposal NAS100/BNBUSD)
python -c "import yaml; o=yaml.safe_load(open('config/overrides.yaml')); print('NAS100 min_score:', o.get('NAS100',{}).get('orchestrator',{}).get('min_score_for_proposal','NON DÉFINI')); print('BNBUSD min_score:', o.get('BNBUSD',{}).get('orchestrator',{}).get('min_score_for_proposal','NON DÉFINI'))"
```

---

## PHASE 2 — P&L SUR 5 JOURS ⭐⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Décomposer trade_outcomes.csv par jour

À partir de `trade_outcomes.csv`, calculer pour CHAQUE jour des 5 derniers jours :

```
┌──────────────┬────────┬────────┬──────────┬──────────┬───────────┬────────────┬───────────┐
│ Jour         │ Trades │ TP win │ Trailing │ SL loss  │ BE        │ P&L net    │ Hit rate  │
├──────────────┼────────┼────────┼──────────┼──────────┼───────────┼────────────┼───────────┤
│              │        │        │          │          │           │            │           │
│              │        │        │          │          │           │            │           │
│              │        │        │          │          │           │            │           │
│              │        │        │          │          │           │            │           │
│              │        │        │          │          │           │            │           │
│ TOTAL 5j     │        │        │          │          │           │            │           │
└──────────────┴────────┴────────┴──────────┴──────────┴───────────┴────────────┴───────────┘
```

### 2.2 — Métriques clés 5 jours

Calculer :
- **Hit rate moyen** : (total wins) / (total trades)
- **Avg $/win** : total gains / nb wins
- **Avg $/loss** : total pertes / nb losses
- **Profit factor** : total gains / |total pertes|
- **Expectancy par trade** : P&L net / total trades
- **Pire drawdown journalier** : la plus grosse perte sur un seul jour
- **Meilleur jour** : plus gros gain
- **QR losses total** : somme des trades SL en < 10 min
- **Jours positifs vs négatifs** : combien de jours rentables ?
- **Tendance** : le P&L s'améliore-t-il jour après jour ?

### 2.3 — Comparaison avec la période pré-config (25-27 mars)

```
┌──────────────────┬────────┬───────────┬────────────┬───────────┬────────────┐
│ Période          │ Trades │ Avg $/win │ P&L net    │ Hit rate  │ Profit fac │
├──────────────────┼────────┼───────────┼────────────┼───────────┼────────────┤
│ 25-27 mars       │ 43     │ $125      │ +$724      │ 49%       │ 1.38       │
│ 5 derniers jours │        │           │            │           │            │
└──────────────────┴────────┴───────────┴────────────┴───────────┴────────────┘
```

---

## PHASE 3 — IMPACT CONFIG NAS100/BNBUSD ⭐⭐ PRIORITÉ #2

### 3.1 — NAS100 avant/après config

```
┌───────────────────┬────────┬────────┬───────────┬───────────┐
│ Période           │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────────────┼────────┼────────┼───────────┼───────────┤
│ 25-27 mars (avant)│ 6      │ 1      │ -$107     │ 17%       │
│ 28 mars→2 avr     │        │        │           │           │
│ (après config 5.0)│        │        │           │           │
└───────────────────┴────────┴────────┴───────────┴───────────┘
```

Combien de trades NAS100 ont été BLOQUÉS par le nouveau seuil 5.0 ?
(Chercher les rejets NAS100 dans les logs avec score < 5.0)

### 3.2 — BNBUSD avant/après config

```
┌───────────────────┬────────┬────────┬───────────┬───────────┐
│ Période           │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────────────┼────────┼────────┼───────────┼───────────┤
│ 25-27 mars (avant)│ 5      │ 1      │ -$131     │ 20%       │
│ 28 mars→2 avr     │        │        │           │           │
│ (après config 5.0)│        │        │           │           │
└───────────────────┴────────┴────────┴───────────┴───────────┘
```

### 3.3 — Le seuil 5.0 est-il trop restrictif ?

- Si NAS100/BNBUSD ont 0 trades sur 5 jours → le seuil est peut-être trop haut
- Si quelques trades passent avec un bon hit rate → le seuil est bien calibré
- Combien de propositions ont été rejetées car score < 5.0 pour ces symboles ?

---

## PHASE 4 — ANALYSE PAR SYMBOLE

```
┌─────────┬────────┬────────┬───────────┬───────────┬────────────┬─────────────────────┐
│ Symbole │ Trades │ Wins   │ P&L net   │ Hit rate  │ Avg $/win  │ Tendance 5j         │
├─────────┼────────┼────────┼───────────┼───────────┼────────────┼─────────────────────┤
│ AUDUSD  │        │        │           │           │            │                     │
│ BTCUSD  │        │        │           │           │            │                     │
│ SP500   │        │        │           │           │            │                     │
│ SOLUSD  │        │        │           │           │            │                     │
│ USDJPY  │        │        │           │           │            │                     │
│ XAUUSD  │        │        │           │           │            │                     │
│ NAS100  │        │        │           │           │            │                     │
│ BNBUSD  │        │        │           │           │            │                     │
│ LTCUSD  │        │        │           │           │            │                     │
└─────────┴────────┴────────┴───────────┴───────────┴────────────┴─────────────────────┘
```

Identifier :
- **Stars** : hit rate > 50% ET P&L positif
- **Corrects** : hit rate 35-50%
- **Toxiques** : hit rate < 25% OU P&L très négatif

---

## PHASE 5 — ANALYSE PAR DIRECTION ET PAR HEURE

### 5.1 — Direction LONG vs SHORT

```
┌───────────┬────────┬────────┬───────────┬───────────┐
│ Direction │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────┼────────┼────────┼───────────┼───────────┤
│ LONG      │        │        │           │           │
│ SHORT     │        │        │           │           │
└───────────┴────────┴────────┴───────────┴───────────┘
```

Le biais SHORT massif du 25-27 mars (+$1,073 vs -$349 LONG) persiste-t-il ?

### 5.2 — Par session horaire

```
┌──────────────────┬────────┬────────┬───────────┬───────────┐
│ Session          │ Trades │ Wins   │ P&L net   │ Hit rate  │
├──────────────────┼────────┼────────┼───────────┼───────────┤
│ Asie (00-08)     │        │        │           │           │
│ Londres (08-13)  │        │        │           │           │
│ NY (13-18)       │        │        │           │           │
│ Soirée (18-23)   │        │        │           │           │
└──────────────────┴────────┴────────┴───────────┴───────────┘
```

---

## PHASE 6 — FILTRES R12-R16 (stabilité 5 jours)

Pour chaque jour, remplir :

```
                            │ Jour 1 │ Jour 2 │ Jour 3 │ Jour 4 │ Jour 5 │ TOTAL
Momentum INVERSE bloqués    │        │        │        │        │        │
Momentum streak-block       │        │        │        │        │        │
ORDER_SEND total            │        │        │        │        │        │
Anti-QR cooldowns           │        │        │        │        │        │
ENTRY_REFRESH               │        │        │        │        │        │
HARD_FILTER taux rejet      │        │        │        │        │        │
Tracebacks                  │        │        │        │        │        │
```

Vérifier la **stabilité** : les métriques sont-elles constantes jour après jour, ou y a-t-il des dérives ?

- ENTRY_REFRESH : R:R préservé 100% sur 5 jours ?
- ORDER_SEND : reste ≤ 20/jour (pas de régression spam) ?
- Tracebacks : 0 sur 5 jours ?
- Kill switch : déclenché à un moment ?

---

## PHASE 7 — INFRASTRUCTURE ET UPTIME

- Uptime : combien de jours continus ? Interruptions ?
- Event loop : 9/9 symboles stable sur 5 jours ?
- Lock COM : 0 erreurs ?
- Kill switch : déclenché ? Si oui, combien de fois et impact ?
- Tracebacks : 0 ?
- retcode 10016 : tendance (augmente/stable/diminue) ?
- Finnhub 403 : toujours présent ?
- Mémoire/CPU : signes de fuite mémoire ou ralentissement ?

---

## FORMAT DU RAPPORT

```
═══════════════════════════════════════════════════════════════════
RAPPORT 5 JOURS — [dates] — BILAN COMPLET R12-R16 + CONFIG
═══════════════════════════════════════════════════════════════════

━━━ A. P&L SUR 5 JOURS ⭐⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Par jour :
┌──────────────┬────────┬────────┬──────────┬───────────┬────────────┬───────────┐
│ Jour         │ Trades │ Wins   │ Avg $/win│ P&L net   │ Hit rate   │ QR losses │
├──────────────┼────────┼────────┼──────────┼───────────┼────────────┼───────────┤
│              │        │        │          │           │            │           │
│ TOTAL 5j     │        │        │          │           │            │           │
└──────────────┴────────┴────────┴──────────┴───────────┴────────────┴───────────┘

Métriques 5 jours :
- Hit rate moyen      : [X]%
- Avg $/win           : $[X]
- Avg $/loss          : -$[X]
- Profit factor       : [X]
- Expectancy/trade    : $[X]
- Jours positifs      : [N]/5
- Pire drawdown jour  : -$[X] ([date])
- Meilleur jour       : +$[X] ([date])
- QR losses total     : -$[X]

Tendance P&L (par jour, chronologique) :
[Décrire si le P&L s'améliore, se dégrade, ou oscille]

VERDICT :
- ✅ Profit factor > 1.0 ET jours positifs ≥ 3/5 → BOT RENTABLE
- ⚠️ Profit factor 0.8-1.0 → À L'ÉQUILIBRE, ajustements nécessaires
- ❌ Profit factor < 0.8 → PERDANT, revue profonde nécessaire

━━━ B. IMPACT CONFIG NAS100/BNBUSD ⭐⭐ ━━━━━━━━━━━━━━━━━━━━━━━━

NAS100 :
┌───────────────────┬────────┬────────┬───────────┬───────────┐
│ Période           │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────────────┼────────┼────────┼───────────┼───────────┤
│ 25-27 mars (avant)│ 6      │ 1      │ -$107     │ 17%       │
│ Après config 5.0  │        │        │           │           │
└───────────────────┴────────┴────────┴───────────┴───────────┘
Propositions rejetées (score < 5.0) : [N]
Trades exécutés (score ≥ 5.0)       : [N]

BNBUSD :
┌───────────────────┬────────┬────────┬───────────┬───────────┐
│ Période           │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────────────┼────────┼────────┼───────────┼───────────┤
│ 25-27 mars (avant)│ 5      │ 1      │ -$131     │ 20%       │
│ Après config 5.0  │        │        │           │           │
└───────────────────┴────────┴────────┴───────────┴───────────┘
Propositions rejetées (score < 5.0) : [N]
Trades exécutés (score ≥ 5.0)       : [N]

VERDICT CONFIG :
- ✅ Pertes réduites ET trades de qualité maintenus → seuil bien calibré
- ⚠️ 0 trades → seuil trop restrictif, baisser à 4.5
- ❌ Toujours perdant malgré le seuil → désactiver le symbole

━━━ C. ANALYSE PAR SYMBOLE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────┬────────┬────────┬───────────┬───────────┬─────────────────────┐
│ Symbole │ Trades │ Wins   │ P&L net   │ Hit rate  │ Verdict             │
├─────────┼────────┼────────┼───────────┼───────────┼─────────────────────┤
│         │        │        │           │           │                     │
└─────────┴────────┴────────┴───────────┴───────────┴─────────────────────┘

━━━ D. ANALYSE DIRECTION + HEURES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Direction :
┌───────────┬────────┬────────┬───────────┬───────────┐
│           │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────┼────────┼────────┼───────────┼───────────┤
│ LONG      │        │        │           │           │
│ SHORT     │        │        │           │           │
└───────────┴────────┴────────┴───────────┴───────────┘

Sessions :
┌──────────────────┬────────┬────────┬───────────┬───────────┐
│ Session          │ Trades │ Wins   │ P&L net   │ Hit rate  │
├──────────────────┼────────┼────────┼───────────┼───────────┤
│ Asie (00-08)     │        │        │           │           │
│ Londres (08-13)  │        │        │           │           │
│ NY (13-18)       │        │        │           │           │
│ Soirée (18-23)   │        │        │           │           │
└──────────────────┴────────┴────────┴───────────┴───────────┘

━━━ E. STABILITÉ FILTRES R12-R16 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Par jour :
                            │ J1   │ J2   │ J3   │ J4   │ J5   │ TOTAL │ Stable?
Momentum INVERSE bloqués    │      │      │      │      │      │       │ [oui/non]
Momentum streak-block       │      │      │      │      │      │       │
ORDER_SEND total            │      │      │      │      │      │       │ [≤20/j?]
Anti-QR cooldowns           │      │      │      │      │      │       │
ENTRY_REFRESH               │      │      │      │      │      │       │ [R:R 100%?]
HARD_FILTER taux rejet      │      │      │      │      │      │       │ [40-70%?]
Tracebacks                  │      │      │      │      │      │       │ [0?]

━━━ F. INFRASTRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Uptime            : [jours continus / interruptions]
Event loop        : [9/9 stable ?]
Lock COM          : [0 erreurs ?]
Kill switch       : [déclenché ? combien de fois ?]
Tracebacks        : [0 sur 5j ?]
retcode 10016     : [N total, tendance]

━━━ G. BILAN COMPLET R12-R16 + CONFIG ⭐⭐⭐ ━━━━━━━━━━━━━━━━━━━

┌──────────────────────────────┬───────────┬──────────────────────────────┐
│ Composant                    │ Statut    │ Impact mesuré 5j             │
├──────────────────────────────┼───────────┼──────────────────────────────┤
│ R12 Outcome tracker          │ ✅/❌/⚠️  │                              │
│ R13 HARD_FILTER 3.8          │ ✅/❌/⚠️  │                              │
│ R14 ENTRY_REFRESH            │ ✅/❌/⚠️  │                              │
│ R14 DIR_CHECK                │ ✅/❌/⚠️  │                              │
│ R15 MOMENTUM_CHECK           │ ✅/❌/⚠️  │                              │
│ R15 RISK_CAP indices         │ ✅/❌/⚠️  │                              │
│ R15 Anti-QR cooldown         │ ✅/❌/⚠️  │                              │
│ R16 Anti-Spam                │ ✅/❌/⚠️  │                              │
│ R16 Momentum Streak          │ ✅/❌/⚠️  │                              │
│ R16 RISK_CAP cleanup         │ ✅/❌/⚠️  │                              │
│ Config NAS100 5.0            │ ✅/❌/⚠️  │                              │
│ Config BNBUSD 5.0            │ ✅/❌/⚠️  │                              │
│ regime_label fix             │ ✅/❌/⚠️  │                              │
└──────────────────────────────┴───────────┴──────────────────────────────┘

SYNTHÈSE FINANCIÈRE 5 JOURS :
- P&L net total    : $[X]
- Profit factor    : [X]
- Hit rate moyen   : [X]%
- Expectancy/trade : $[X]
- Jours positifs   : [N]/5

ÉVOLUTION DEPUIS LE DÉBUT DES FIXES :
┌──────────────────┬───────────┬────────────┬───────────┬────────────┐
│ Période          │ Hit rate  │ Avg $/win  │ P&L/jour  │ Profit fac │
├──────────────────┼───────────┼────────────┼───────────┼────────────┤
│ Pré-R14 (16-17)  │ 62-67%   │ $49-51     │ -$334     │ < 0.5      │
│ R14 (23 mars)    │ 22%      │ $124       │ -$668     │ < 0.5      │
│ R15 (24 mars)    │ 33%      │ $53        │ -$445     │ < 0.7      │
│ R16 (25-27 mars) │ 49%      │ $125       │ +$241     │ 1.38       │
│ +Config (5 jours)│          │            │           │            │
└──────────────────┴───────────┴────────────┴───────────┴────────────┘

PROBLÈMES RESTANTS :
1. ...

RECOMMANDATIONS FINALES :
1. ...

VERDICT GLOBAL :
[Le bot est-il opérationnel et rentable ? Réponse claire et argumentée
basée sur les 5 jours de données.]
```

## RÈGLES

1. **Ne modifie AUCUN fichier.** Lecture seule.
2. **L'analyse P&L sur 5 jours est la PRIORITÉ ABSOLUE.** Décomposer par jour obligatoire.
3. **L'impact config NAS100/BNBUSD est la PRIORITÉ #2.** Comparer avant/après.
4. **Cite les chiffres exacts de trade_outcomes.csv.**
5. **Évaluer la TENDANCE** : le P&L s'améliore-t-il jour après jour ?
6. **Évaluer la STABILITÉ** : les filtres fonctionnent-ils de manière constante ?
7. **Ne recommande PAS de nouveau code** sauf bug critique.
8. **Les recommandations config doivent être CHIFFRÉES** avec données 5 jours.
9. **Le verdict global doit être CLAIR** : rentable / à l'équilibre / perdant.
10. **Comparer avec la période 25-27 mars** (P&L +$724, hit rate 49%, PF 1.38) pour mesurer la progression.
