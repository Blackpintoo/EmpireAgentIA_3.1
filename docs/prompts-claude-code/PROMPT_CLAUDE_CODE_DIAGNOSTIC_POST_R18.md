# PROMPT CLAUDE CODE — Diagnostic 6 jours POST-R18 (10-16 avril 2026)

## Contexte

Le bot tourne avec le stack complet R12-R18 depuis le 10 avril 2026.
- **R18 (10 avril)** : ASIA BLOCK (00-07 UTC non-crypto), MODE PROBATION (SOLUSD/BNBUSD/LTCUSD), FIX LIQ_PENALTY, FIX REVERSAL_COOLDOWN, BTCUSD min_score 3.0, USDJPY min_score 6.0, Finnhub désactivé
- **R17 (10 avril)** : SHORT Penalty (+1.5), Adaptive min_score, LONG only BTCUSD/SOLUSD/AUDUSD/USDJPY, Reversal Cooldown, Risk Reduction, Regime Filter SHORT, Session Penalty
- R16 : Anti-Spam ORDER_SEND, Momentum Anti-Streak
- R15 : MOMENTUM_CHECK, RISK_CAP indices, Anti-QR cooldown
- R14 : ENTRY_REFRESH, DIR_CHECK
- R13 : HARD_FILTER 3.8 | R12 : Outcome tracker

**Référence pré-R18 (14 jours)** : PF 0.80, P&L -$1,192, HR 34.9%, 126 trades
- Session Asie = -$1,113 (93% des pertes)
- SHORT = 23.1% HR, -$1,391
- SOLUSD -$906, BNBUSD -$489, LTCUSD -$299

**Objectif** : Mesurer l'impact de R18. Les 3 questions clés :
1. L'ASIA BLOCK a-t-il éliminé les pertes nocturnes ?
2. Le MODE PROBATION bride-t-il les symboles toxiques ?
3. LIQ_PENALTY et REVERSAL_COOLDOWN fonctionnent-ils enfin ?

---

## PHASE 1 — Collecte des données

**IMPORTANT** : Exécuter TOUTES les commandes avant d'analyser.

```bash
# 1a. INTÉGRALITÉ du fichier trade_outcomes.csv
type data\trade_outcomes.csv

# 1b. Dernières 15000 lignes du log (6 jours)
tail -n 15000 logs/empire_agent.log

# 1c. NOUVEAUX filtres R18
findstr /I "ASIA_BLOCK" logs\empire_agent.log
findstr /I "PROBATION" logs\empire_agent.log
findstr /I "LIQ_PENALTY" logs\empire_agent.log
findstr /I "REVERSAL_COOLDOWN" logs\empire_agent.log

# 1d. Filtres R17
findstr /I "SHORT_PENALTY" logs\empire_agent.log | find /c /v ""
findstr /I "ADAPTIVE_SCORE" logs\empire_agent.log | find /c /v ""
findstr /I "DIRECTION_FILTER" logs\empire_agent.log | find /c /v ""

# 1e. Filtres R15-R16
findstr /I "MOMENTUM_CHECK" logs\empire_agent.log | tail -30
findstr /I "ANTI_SPAM" logs\empire_agent.log | find /c /v ""
findstr /I "QUICK_REVERSAL" logs\empire_agent.log | tail -20
findstr /I "HARD_FILTER" logs\empire_agent.log | tail -50

# 1f. ORDER_SEND comptage
findstr /c:"ORDER_SEND" logs\empire_agent.log | find /c /v ""

# 1g. Erreurs
findstr /I "Traceback Error Exception" logs\empire_agent.log | tail -40

# 1h. Restarts
findstr /I "Starting Initialisation" logs\empire_agent.log

# 1i. Kill switch + positions
type data\daily_loss_state.json
type data\tracked_positions.json

# 1j. Config vérification R18
python -c "
import yaml
c = yaml.safe_load(open('config/config.yaml'))
hf = c.get('orchestrator', {}).get('hard_filters', {})
ab = hf.get('asia_block', {})
print('=== R18 CONFIG ===')
print('asia_block.enabled:', ab.get('enabled', 'ABSENT'))
print('asia_block.hours:', ab.get('hours_utc', 'ABSENT'))
print('low_liq_hours:', hf.get('low_liquidity_hours_utc', 'ABSENT'))
print('finnhub.enabled:', c.get('external_apis', {}).get('finnhub', {}).get('enabled', 'ABSENT'))
prob = c.get('orchestrator', {}).get('probation', {})
print('probation.enabled:', prob.get('enabled', 'ABSENT'))

o = yaml.safe_load(open('config/overrides.yaml'))
for sym in ['SOLUSD', 'BNBUSD', 'LTCUSD', 'BTCUSD', 'USDJPY', 'AUDUSD']:
    oc = o.get(sym, {}).get('orchestrator', {})
    r = o.get(sym, {}).get('risk', {})
    print(f'{sym}: probation={oc.get(\"probation\", False)}, min_score={oc.get(\"min_score_for_proposal\", \"DEF\")}, dirs={oc.get(\"allowed_directions\", \"ALL\")}, risk={r.get(\"risk_per_trade\", \"DEF\")}, daily_abs={r.get(\"daily_loss_abs\", \"DEF\")}')
"
```

---

## PHASE 2 — P&L POST-R18 (6 jours) ⭐⭐⭐ PRIORITÉ ABSOLUE

### 2.1 — Tableau jour par jour (uniquement les trades APRÈS le 10 avril)

Filtrer `trade_outcomes.csv` pour ne garder que les trades ouverts/fermés **à partir du 10 avril 2026** (date d'application R18).

```
┌──────────────┬────────┬────────┬──────────┬──────────┬───────────┬────────────┬───────────┐
│ Jour         │ Trades │ TP win │ Trailing │ SL loss  │ BE        │ P&L net    │ Hit rate  │
├──────────────┼────────┼────────┼──────────┼──────────┼───────────┼────────────┼───────────┤
│ 10 avril     │        │        │          │          │           │            │           │
│ 11 avril     │        │        │          │          │           │            │           │
│ 12 avril     │        │        │          │          │           │            │           │
│ 13 avril     │        │        │          │          │           │            │           │
│ 14 avril     │        │        │          │          │           │            │           │
│ 15 avril     │        │        │          │          │           │            │           │
│ 16 avril     │        │        │          │          │           │            │           │
│ TOTAL 6j     │        │        │          │          │           │            │           │
└──────────────┴────────┴────────┴──────────┴──────────┴───────────┴────────────┴───────────┘
```

### 2.2 — Métriques clés 6 jours POST-R18

Calculer :
- **Hit rate global**
- **Avg $/win** et **Avg $/loss**
- **Profit factor**
- **Expectancy par trade**
- **Pire drawdown journalier**
- **Meilleur jour**
- **QR losses** (trades SL en < 10 min, durée < 600s et pnl < 0)
- **Jours positifs vs négatifs**

### 2.3 — Comparaison AVANT vs APRÈS R18

```
┌──────────────────────┬────────┬───────────┬────────────┬───────────┬────────────┐
│ Période              │ Trades │ Avg $/win │ P&L net    │ Hit rate  │ Profit fac │
├──────────────────────┼────────┼───────────┼────────────┼───────────┼────────────┤
│ PRÉ-R18 (14j)       │  126   │  $111.15  │ -$1,192.38 │  34.9%    │    0.80    │
│ POST-R18 (6j)       │        │           │            │           │            │
│ Différence           │        │           │            │           │            │
└──────────────────────┴────────┴───────────┴────────────┴───────────┴────────────┘
```

### 2.4 — Courbe P&L cumulé POST-R18

Tracer en ASCII la courbe du P&L cumulé jour par jour depuis le 10 avril.

---

## PHASE 3 — IMPACT R18 : ASIA BLOCK ⭐⭐ PRIORITÉ #2

### 3.1 — Combien de trades bloqués par ASIA_BLOCK ?

Compter les occurrences de `[ASIA_BLOCK]` dans les logs. Lister les symboles et heures bloqués.

### 3.2 — Trades en session Asie POST-R18

```
┌──────────────────────┬────────┬────────┬───────────┬───────────┐
│ Période              │ Trades │ Wins   │ P&L       │ Hit rate  │
├──────────────────────┼────────┼────────┼───────────┼───────────┤
│ Asie PRÉ-R18 (14j)  │   15   │    2   │ -$1,113   │  13.3%    │
│ Asie POST-R18 (6j)  │        │        │           │           │
└──────────────────────┴────────┴────────┴───────────┴───────────┘
```

Y a-t-il encore des trades non-crypto entre 00-07 UTC ? Si oui, pourquoi ?

---

## PHASE 4 — IMPACT R18 : MODE PROBATION ⭐⭐ PRIORITÉ #3

### 4.1 — Symboles en probation : activité POST-R18

```
┌─────────┬────────┬────────┬───────────┬───────────┬──────────────────────────────────────┐
│ Symbole │ Trades │ Wins   │ P&L       │ Hit rate  │ Comparaison PRÉ-R18                  │
├─────────┼────────┼────────┼───────────┼───────────┼──────────────────────────────────────┤
│ SOLUSD  │        │        │           │           │ PRÉ: 27 trades, 18.5%, -$906         │
│ BNBUSD  │        │        │           │           │ PRÉ: 14 trades, 7.1%, -$489          │
│ LTCUSD  │        │        │           │           │ PRÉ: 1 trade, 0%, -$299              │
└─────────┴────────┴────────┴───────────┴───────────┴──────────────────────────────────────┘
```

- Combien de trades bloqués par le tag `[PROBATION]` ?
- Le min_score 7.0 + 4 votes laisse-t-il passer quelques trades de qualité ?
- BNBUSD en LONG only : y a-t-il eu des trades ? Résultat ?

### 4.2 — Symboles non-probation : performance POST-R18

```
┌─────────┬────────┬────────┬───────────┬───────────┬──────────────────────────────────────┐
│ Symbole │ Trades │ Wins   │ P&L       │ Hit rate  │ Comparaison PRÉ-R18                  │
├─────────┼────────┼────────┼───────────┼───────────┼──────────────────────────────────────┤
│ XAUUSD  │        │        │           │           │ PRÉ: 14 trades, 71.4%, +$1,556       │
│ NAS100  │        │        │           │           │ PRÉ: 16 trades, 56.3%, +$535         │
│ SP500   │        │        │           │           │ PRÉ: 19 trades, 42.1%, +$58          │
│ BTCUSD  │        │        │           │           │ PRÉ: 14 trades, 28.6%, -$197         │
│ AUDUSD  │        │        │           │           │ PRÉ: 13 trades, 38.5%, -$803         │
│ USDJPY  │        │        │           │           │ PRÉ: 8 trades, 25%, -$648            │
└─────────┴────────┴────────┴───────────┴───────────┴──────────────────────────────────────┘
```

---

## PHASE 5 — IMPACT R18 : DIRECTION LONG vs SHORT

### 5.1 — Biais directionnel POST-R18

```
┌───────────┬────────┬────────┬───────────┬───────────┬────────────┐
│ Direction │ Trades │ Wins   │ P&L net   │ Hit rate  │ Profit fac │
├───────────┼────────┼────────┼───────────┼───────────┼────────────┤
│ LONG      │        │        │           │           │            │
│ SHORT     │        │        │           │           │            │
├───────────┼────────┼────────┼───────────┼───────────┼────────────┤
│ PRÉ-R18   │        │        │           │           │            │
│ LONG      │   74   │   32   │  +$199    │  43.2%    │    1.06    │
│ SHORT     │   52   │   12   │ -$1,391   │  23.1%    │    0.48    │
└───────────┴────────┴────────┴───────────┴───────────┴────────────┘
```

Le SHORT_PENALTY + Regime Filter + LONG only ont-ils réduit le nombre de SHORT et amélioré le HR ?

### 5.2 — SHORT par symbole POST-R18

Lister tous les trades SHORT POST-R18 avec symbole, score, résultat. Le SHORT ne devrait rester que sur XAUUSD, NAS100, SP500 (les seuls symboles non restreints en direction).

---

## PHASE 6 — FILTRES R18 : FONCTIONNEMENT

### 6.1 — Comptage des tags R18 dans les logs

```
                              │ Occurrences │ Attendu      │ Verdict
──────────────────────────────┼─────────────┼──────────────┼──────────
[ASIA_BLOCK]                  │             │ > 50         │
[PROBATION]                   │             │ > 0          │
[LIQ_PENALTY] (déclenché)     │             │ > 0          │
[LIQ_PENALTY] (debug/PASS)    │             │ > 100        │
[REVERSAL_COOLDOWN] (bloqué)  │             │ > 0          │
[REVERSAL_COOLDOWN] (debug)   │             │ > 50         │
[SHORT_PENALTY]               │             │ > 100        │
[ADAPTIVE_SCORE]              │             │ > 1000       │
[DIRECTION_FILTER]            │             │ > 200        │
[HARD_FILTER] rejets          │             │ > 5000       │
ANTI_SPAM                     │             │ > 100        │
ORDER_SEND total              │             │ < 100        │
```

### 6.2 — Sessions horaires POST-R18

```
┌──────────────────┬────────┬────────┬───────────┬───────────┐
│ Session          │ Trades │ Wins   │ P&L net   │ Hit rate  │
├──────────────────┼────────┼────────┼───────────┼───────────┤
│ Asie (00-08)     │        │        │           │           │
│ Londres (08-13)  │        │        │           │           │
│ NY (13-18)       │        │        │           │           │
│ Soirée (18-23)   │        │        │           │           │
├──────────────────┼────────┼────────┼───────────┼───────────┤
│ PRÉ-R18          │        │        │           │           │
│ Asie (00-08)     │   15   │    2   │ -$1,113   │  13.3%    │
│ Londres (08-13)  │   22   │    6   │  -$386    │  27.3%    │
│ NY (13-18)       │   42   │   14   │  +$311    │  33.3%    │
│ Soirée (18-23)   │   47   │   22   │    -$4    │  46.8%    │
└──────────────────┴────────┴────────┴───────────┴───────────┘
```

### 6.3 — Erreurs et stabilité

- Restarts depuis le 10 avril ?
- Erreurs/Tracebacks liés au code R17/R18 ?
- Kill switch déclenché ?
- Finnhub : les 403 ont-ils cessé ?

---

## PHASE 7 — SYNTHÈSE

### 7.1 — Score global POST-R18

```
┌──────────────────────┬──────────┬──────────┬──────────┬──────────────────┐
│ Métrique             │ PRÉ-R18  │ POST-R18 │ Cible    │ Verdict          │
├──────────────────────┼──────────┼──────────┼──────────┼──────────────────┤
│ P&L net              │ -$1,192  │          │ > $0     │                  │
│ Hit rate global      │  34.9%   │          │ > 40%    │                  │
│ Profit factor        │  0.80    │          │ > 1.3    │                  │
│ Expectancy/trade     │  -$9.46  │          │ > $5     │                  │
│ Jours positifs       │  5/14    │          │ > 4/6    │                  │
│ Max drawdown jour    │  -$852   │          │ < $400   │                  │
│ SHORT HR             │  23.1%   │          │ > 35%    │                  │
│ Asie P&L             │ -$1,113  │          │ > -$50   │                  │
│ Probation P&L        │ -$1,694  │          │ > -$100  │                  │
│ Crashes              │    0     │          │ < 2      │                  │
└──────────────────────┴──────────┴──────────┴──────────┴──────────────────┘
```

### 7.2 — Verdict R18

Répondre clairement :
1. **ASIA BLOCK fonctionne ?** (les pertes Asie ont-elles disparu ?)
2. **PROBATION fonctionne ?** (SOLUSD/BNBUSD/LTCUSD bridés ?)
3. **LIQ_PENALTY fonctionne ?** (tags dans les logs ?)
4. **REVERSAL_COOLDOWN fonctionne ?** (tags dans les logs ?)
5. **Le bot est-il rentable ?** (P&L > 0 ?)
6. **La tendance s'améliore-t-elle ?** (PF en hausse ?)

### 7.3 — Top 3 problèmes restants + recommandations

Pour chaque problème, indiquer :
- Ce qui ne va pas (données)
- Ce qu'il faut changer (config ou code)
- Priorité (P1/P2/P3)

### 7.4 — Symboles : bilan

```
⭐ Stars confirmées    :
✅ Corrects            :
⚠️ En probation        :
❌ À considérer retirer :
🆕 À considérer ajouter :
```
