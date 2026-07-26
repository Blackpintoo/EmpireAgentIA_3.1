# PROMPT CLAUDE CODE — Diagnostic 2 semaines (28 mars - 10 avril 2026)

## Contexte

Le bot tourne avec le stack complet R12-R17.
- **R17 (10 avril)** : SHORT Penalty (+1.5 score), Adaptive min_score, LONG only BTCUSD/SOLUSD/AUDUSD/USDJPY, Reversal Cooldown (anti-whipsaw 60min), Risk Reduction symboles perdants, Regime Filter SHORT renforcé, Session Asie Penalty (+2.0)
- **Config 28 mars** : `min_score_for_proposal` 5.0 pour NAS100 et BNBUSD
- R16 : Anti-Spam ORDER_SEND (triple protection), Momentum Anti-Streak, RISK_CAP log cleanup
- R15 : MOMENTUM_CHECK, RISK_CAP indices override, Anti-QUICK_REVERSAL cooldown, HARD_FILTER .4f
- R14 : ENTRY_REFRESH (R:R préservé), DIR_CHECK
- R13 : HARD_FILTER 3.8
- R12 : Outcome tracker

**Objectif** : Bilan complet sur 14 jours. Mesurer la progression, identifier les tendances, évaluer chaque filtre. Les améliorations R17 viennent d'être appliquées et ne couvrent que les dernières heures — le gros de l'analyse porte donc sur R12-R16 + config.

---

## PHASE 1 — Collecte des données

**IMPORTANT** : Exécuter toutes les commandes ci-dessous AVANT d'analyser. Ne pas sauter d'étape.

```bash
# 1a. INTÉGRALITÉ du fichier trade_outcomes.csv — SOURCE PRINCIPALE
type data\trade_outcomes.csv

# 1b. Dernières 25000 lignes du log (14 jours)
tail -n 25000 logs/empire_agent.log

# 1c. Tous les filtres R15-R17
findstr /I "MOMENTUM_CHECK" logs\empire_agent.log
findstr /I "ANTI_SPAM" logs\empire_agent.log
findstr /I "COOLDOWN QUICK_REVERSAL" logs\empire_agent.log
findstr /I "streak" logs\empire_agent.log
findstr /I "SHORT_PENALTY" logs\empire_agent.log
findstr /I "ADAPTIVE_SCORE" logs\empire_agent.log
findstr /I "REVERSAL_COOLDOWN" logs\empire_agent.log
findstr /I "LIQ_PENALTY" logs\empire_agent.log
findstr /I "DIRECTION_FILTER" logs\empire_agent.log

# 1d. HARD_FILTER + SCORE_DIAG + DECISION
findstr /I "HARD_FILTER" logs\empire_agent.log | tail -80
findstr /I "SCORE_DIAG" logs\empire_agent.log | tail -80
findstr /I "[DECISION]" logs\empire_agent.log | tail -80

# 1e. RISK_CAP + ENTRY_REFRESH
findstr /I "RISK_CAP" logs\empire_agent.log | tail -40
findstr /I "ENTRY_REFRESH" logs\empire_agent.log | tail -40

# 1f. ORDER_SEND comptage total + par symbole
findstr /c:"ORDER_SEND" logs\empire_agent.log | find /c /v ""
findstr "ORDER_SEND" logs\empire_agent.log | findstr /I "XAUUSD BTCUSD SP500 NAS100 BNBUSD AUDUSD USDJPY SOLUSD LTCUSD EURUSD GBPUSD"

# 1g. Outcome tracker
findstr /I "[OUTCOME]" logs\empire_agent.log | tail -80

# 1h. Kill switch + positions
type data\daily_loss_state.json
type data\tracked_positions.json

# 1i. Erreurs / Tracebacks
findstr /I "Traceback Error Exception" logs\empire_agent.log | tail -50

# 1j. Restarts du bot
findstr /I "Starting Initialisation" logs\empire_agent.log

# 1k. Config vérification
python -c "import yaml; o=yaml.safe_load(open('config/overrides.yaml')); [print(f'{s}: min_score={o.get(s,{}).get(\"orchestrator\",{}).get(\"min_score_for_proposal\",\"DEFAULT\")}, allowed_dirs={o.get(s,{}).get(\"orchestrator\",{}).get(\"allowed_directions\",\"ALL\")}') for s in ['NAS100','BNBUSD','BTCUSD','SOLUSD','AUDUSD','USDJPY']]"

# 1l. Vérifier que R17 est en place
python -c "import yaml; c=yaml.safe_load(open('config/config.yaml')); hf=c.get('orchestrator',{}).get('hard_filters',{}); print('short_score_penalty:', hf.get('short_score_penalty','ABSENT')); print('adaptive_score:', hf.get('adaptive_score',{}).get('enabled','ABSENT')); print('low_liq_penalty:', hf.get('low_liquidity_score_penalty','ABSENT')); cd=c.get('orchestrator',{}).get('cooldown',{}); print('reversal_cooldown:', cd.get('reversal_cooldown_min','ABSENT'))"
```

---

## PHASE 2 — P&L SUR 14 JOURS ⭐⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Décomposer trade_outcomes.csv par jour (14 jours)

À partir de `trade_outcomes.csv`, calculer pour CHAQUE jour :

```
┌──────────────┬────────┬────────┬──────────┬──────────┬───────────┬────────────┬───────────┐
│ Jour         │ Trades │ TP win │ Trailing │ SL loss  │ BE        │ P&L net    │ Hit rate  │
├──────────────┼────────┼────────┼──────────┼──────────┼───────────┼────────────┼───────────┤
│ 28 mars      │        │        │          │          │           │            │           │
│ 29 mars      │        │        │          │          │           │            │           │
│ 30 mars      │        │        │          │          │           │            │           │
│ 31 mars      │        │        │          │          │           │            │           │
│ 1 avril      │        │        │          │          │           │            │           │
│ 2 avril      │        │        │          │          │           │            │           │
│ 3 avril      │        │        │          │          │           │            │           │
│ 4 avril      │        │        │          │          │           │            │           │
│ 5 avril      │        │        │          │          │           │            │           │
│ 6 avril      │        │        │          │          │           │            │           │
│ 7 avril      │        │        │          │          │           │            │           │
│ 8 avril      │        │        │          │          │           │            │           │
│ 9 avril      │        │        │          │          │           │            │           │
│ 10 avril     │        │        │          │          │           │            │           │
│ TOTAL 14j    │        │        │          │          │           │            │           │
└──────────────┴────────┴────────┴──────────┴──────────┴───────────┴────────────┴───────────┘
```

### 2.2 — Métriques clés 14 jours

Calculer :
- **Hit rate global** : (total wins) / (total trades)
- **Avg $/win** : total gains / nb wins
- **Avg $/loss** : total pertes / nb losses
- **Profit factor** : total gains / |total pertes|
- **Expectancy par trade** : P&L net / total trades
- **Pire drawdown journalier** : la plus grosse perte sur un seul jour
- **Meilleur jour** : plus gros gain
- **QR losses total** : somme des trades SL en < 10 min (trades avec durée < 600s et pnl < 0)
- **Jours positifs vs négatifs** : combien de jours rentables sur 14 ?
- **Tendance** : le P&L s'améliore-t-il semaine 1 vs semaine 2 ?
- **Max drawdown cumulé** : plus grosse perte cumulée depuis un pic

### 2.3 — Comparaison semaine 1 vs semaine 2

```
┌──────────────────┬────────┬───────────┬────────────┬───────────┬────────────┐
│ Période          │ Trades │ Avg $/win │ P&L net    │ Hit rate  │ Profit fac │
├──────────────────┼────────┼───────────┼────────────┼───────────┼────────────┤
│ Semaine 1        │        │           │            │           │            │
│ (28 mars-3 avr)  │        │           │            │           │            │
│ Semaine 2        │        │           │            │           │            │
│ (4-10 avril)     │        │           │            │           │            │
│ TOTAL 14 jours   │        │           │            │           │            │
└──────────────────┴────────┴───────────┴────────────┴───────────┴────────────┘
```

### 2.4 — Courbe de P&L cumulé

Tracer la courbe de P&L cumulé jour par jour sur 14 jours :
```
P&L cumulé ($)
    ^
    |        ___
    |   ___/
    |  /
    | /
    |/
    +---+---+---+---+---+---+---+---+---+---+---+---+---+----> Jours
    28  29  30  31   1   2   3   4   5   6   7   8   9  10
```
(Utiliser les chiffres réels pour dessiner en ASCII)

---

## PHASE 3 — ANALYSE PAR SYMBOLE ⭐⭐ PRIORITÉ #2

### 3.1 — Performance globale par symbole

```
┌─────────┬────────┬────────┬───────────┬───────────┬────────────┬───────────┬─────────────┐
│ Symbole │ Trades │ Wins   │ P&L net   │ Hit rate  │ Avg $/win  │ Avg $/loss│ Classement  │
├─────────┼────────┼────────┼───────────┼───────────┼────────────┼───────────┼─────────────┤
│ XAUUSD  │        │        │           │           │            │           │             │
│ NAS100  │        │        │           │           │            │           │             │
│ SP500   │        │        │           │           │            │           │             │
│ BTCUSD  │        │        │           │           │            │           │             │
│ SOLUSD  │        │        │           │           │            │           │             │
│ BNBUSD  │        │        │           │           │            │           │             │
│ AUDUSD  │        │        │           │           │            │           │             │
│ USDJPY  │        │        │           │           │            │           │             │
│ LTCUSD  │        │        │           │           │            │           │             │
│ EURUSD  │        │        │           │           │            │           │             │
│ TOTAL   │        │        │           │           │            │           │             │
└─────────┴────────┴────────┴───────────┴───────────┴────────────┴───────────┴─────────────┘
```

Classement : ⭐ Star (HR>50% ET P&L>0) | ✅ Correct (HR 35-50%) | ⚠️ Fragile (HR 25-35%) | ❌ Toxique (HR<25% OU grosse perte)

### 3.2 — Évolution par symbole : semaine 1 vs semaine 2

Pour chaque symbole, comparer semaine 1 et semaine 2 :
```
┌─────────┬─────────────────────────┬─────────────────────────┬────────────────┐
│ Symbole │ Sem 1 (28mar-3avr)      │ Sem 2 (4-10avr)         │ Tendance       │
│         │ Trades│HR  │P&L         │ Trades│HR  │P&L         │                │
├─────────┼───────┼────┼────────────┼───────┼────┼────────────┼────────────────┤
│ XAUUSD  │       │    │            │       │    │            │ ↗️ ↘️ →       │
│ NAS100  │       │    │            │       │    │            │                │
│ SP500   │       │    │            │       │    │            │                │
│ etc.    │       │    │            │       │    │            │                │
└─────────┴───────┴────┴────────────┴───────┴────┴────────────┴────────────────┘
```

### 3.3 — Impact config NAS100/BNBUSD (min_score 5.0)

Comparer les 3 périodes pour NAS100 et BNBUSD :
```
┌───────────────────┬────────┬────────┬───────────┬───────────┐
│ Période           │ Trades │ Wins   │ P&L net   │ Hit rate  │
├───────────────────┼────────┼────────┼───────────┼───────────┤
│ Avant config      │        │        │           │           │
│ Après config (14j)│        │        │           │           │
└───────────────────┴────────┴────────┴───────────┴───────────┘
```

Combien de trades bloqués par le seuil 5.0 ? (chercher dans les logs HARD_FILTER REJET pour ces symboles)

---

## PHASE 4 — ANALYSE PAR DIRECTION ⭐⭐ PRIORITÉ #3

### 4.1 — LONG vs SHORT global

```
┌───────────┬────────┬────────┬───────────┬───────────┬────────────┐
│ Direction │ Trades │ Wins   │ P&L net   │ Hit rate  │ Profit fac │
├───────────┼────────┼────────┼───────────┼───────────┼────────────┤
│ LONG      │        │        │           │           │            │
│ SHORT     │        │        │           │           │            │
└───────────┴────────┴────────┴───────────┴───────────┴────────────┘
```

### 4.2 — LONG vs SHORT par symbole

```
┌─────────┬──────────────────────────┬──────────────────────────┐
│ Symbole │ LONG                     │ SHORT                    │
│         │ Trades│HR  │P&L          │ Trades│HR  │P&L          │
├─────────┼───────┼────┼─────────────┼───────┼────┼─────────────┤
│ XAUUSD  │       │    │             │       │    │             │
│ NAS100  │       │    │             │       │    │             │
│ SP500   │       │    │             │       │    │             │
│ BTCUSD  │       │    │             │       │    │             │
│ SOLUSD  │       │    │             │       │    │             │
│ BNBUSD  │       │    │             │       │    │             │
│ AUDUSD  │       │    │             │       │    │             │
│ USDJPY  │       │    │             │       │    │             │
│ LTCUSD  │       │    │             │       │    │             │
└─────────┴───────┴────┴─────────────┴───────┴────┴─────────────┘
```

Le biais SHORT (20.7% HR sur 5j) s'est-il amélioré ?

---

## PHASE 5 — ANALYSE PAR SESSION HORAIRE

### 5.1 — Par tranche horaire (UTC)

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

### 5.2 — Heatmap heure × symbole (top 5 symboles seulement)

```
         │ 00-04 │ 04-08 │ 08-12 │ 12-16 │ 16-20 │ 20-24 │
─────────┼───────┼───────┼───────┼───────┼───────┼───────┤
XAUUSD   │  P&L  │  P&L  │  P&L  │  P&L  │  P&L  │  P&L  │
NAS100   │       │       │       │       │       │       │
SP500    │       │       │       │       │       │       │
BTCUSD   │       │       │       │       │       │       │
SOLUSD   │       │       │       │       │       │       │
```

---

## PHASE 6 — FILTRES ET PROTECTIONS (stabilité 14 jours)

### 6.1 — Comptage des filtres par semaine

```
                              │ Sem 1  │ Sem 2  │ TOTAL  │ Tendance
──────────────────────────────┼────────┼────────┼────────┼──────────
Momentum INVERSE bloqués      │        │        │        │
Momentum streak-block         │        │        │        │
HARD_FILTER rejets            │        │        │        │
ORDER_SEND total              │        │        │        │
Anti-QR cooldowns             │        │        │        │
ANTI_SPAM bloqués             │        │        │        │
DIRECTION_FILTER bloqués      │        │        │        │
SHORT_PENALTY bloqués (R17)   │        │        │        │
ADAPTIVE_SCORE boosts (R17)   │        │        │        │
REVERSAL_COOLDOWN bloqués(R17)│        │        │        │
LIQ_PENALTY appliqués (R17)   │        │        │        │
REGIME SHORT bloqués          │        │        │        │
```

### 6.2 — Trades Quick Reversal (SL en < 10 min)

Lister tous les trades fermés en SL avec durée < 600 secondes :
```
┌──────────┬─────────┬───────┬──────────┬──────────┬──────────┐
│ Date     │ Symbole │ Dir   │ Durée(s) │ P&L      │ Cause    │
├──────────┼─────────┼───────┼──────────┼──────────┼──────────┤
│          │         │       │          │          │          │
└──────────┴─────────┴───────┴──────────┴──────────┴──────────┘
```

Total QR losses : _____ $
Part des QR dans total losses : _____ %

### 6.3 — Erreurs et crashes

- Nombre de restarts sur 14 jours ?
- Erreurs/Tracebacks répétitifs ?
- Le bot a-t-il été interrompu (kill switch, crash) ?

---

## PHASE 7 — DIAGNOSTIC R17 (dernières heures seulement)

Si le bot a eu le temps de tourner depuis l'application de R17 :
- Les tags `[SHORT_PENALTY]`, `[ADAPTIVE_SCORE]`, `[REVERSAL_COOLDOWN]`, `[LIQ_PENALTY]` apparaissent-ils dans les logs ?
- Des trades ont-ils été bloqués par ces nouveaux filtres ?
- Des erreurs liées au nouveau code R17 ?

Si R17 n'a pas encore eu le temps de tourner (< 1h), noter simplement "R17 trop récent pour évaluer".

---

## PHASE 8 — SYNTHÈSE ET RECOMMANDATIONS

### 8.1 — Score global du bot

```
┌──────────────────────┬─────────┬──────────┬──────────────────┐
│ Métrique             │ Valeur  │ Cible    │ Verdict          │
├──────────────────────┼─────────┼──────────┼──────────────────┤
│ P&L net 14j          │         │ > $0     │ ✅ / ❌          │
│ Hit rate global      │         │ > 40%    │                  │
│ Profit factor        │         │ > 1.3    │                  │
│ Expectancy/trade     │         │ > $5     │                  │
│ Jours positifs       │         │ > 8/14   │                  │
│ Max drawdown jour    │         │ < $400   │                  │
│ QR losses part       │         │ < 20%    │                  │
│ Biais SHORT HR       │         │ > 30%    │                  │
│ Crashes/restarts     │         │ < 3      │                  │
└──────────────────────┴─────────┴──────────┴──────────────────┘
```

### 8.2 — Top 3 problèmes restants

1. ...
2. ...
3. ...

### 8.3 — Top 3 points positifs

1. ...
2. ...
3. ...

### 8.4 — Recommandations concrètes

Pour chaque recommandation, indiquer :
- Ce qui doit changer (config ou code)
- L'impact attendu en $
- La priorité (P1/P2/P3)

### 8.5 — Symboles à surveiller / ajouter / retirer

Basé sur 14 jours de données :
- Quels symboles sont confirmés rentables ?
- Quels symboles sont irrécupérables malgré les protections ?
- Faut-il réactiver ETHUSD ou EURUSD ?
