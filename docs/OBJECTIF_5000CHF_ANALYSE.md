# ANALYSE DE FAISABILITE - OBJECTIF 5'000 CHF/MOIS

## Periode d'analyse: 13-24 Decembre 2025

---

## 1. METRIQUES ACTUELLES

### Volume de trading
- **Total propositions**: 183 trades sur 12 jours
- **Moyenne quotidienne**: ~15 propositions/jour
- **Trades haute qualite (score >= 8)**: 102 (55.7%)
- **Trades bonne confluence (>= 5)**: 98 (53.6%)

### Problemes identifies
| Probleme | Pourcentage | Impact |
|----------|-------------|--------|
| Score < 7.0 | 34% | CRITIQUE |
| Confluence < 5 | 46% | CRITIQUE |
| Heures toxiques | 21% | ELEVE |
| Contre-trend | 32% | ELEVE |
| ADAUSD contre-trend | 72% | CRITIQUE |
| USDJPY contre-trend | 42% | ELEVE |

### Symboles les plus actifs
1. SP500: 31 trades (score moyen 11.56)
2. XAGUSD: 31 trades (score moyen 6.40) - A SURVEILLER
3. UK100: 26 trades (score moyen 10.51)
4. ADAUSD: 25 trades (score moyen 8.62) - PROBLEMATIQUE
5. SOLUSD: 23 trades (score moyen 8.82)

---

## 2. CALCUL DE FAISABILITE

### Capital disponible
- **Capital demo actuel**: 100'000 USD
- **Taux CHF/USD approximatif**: 0.90

### Objectif mensuel
- **Objectif**: 5'000 CHF/mois = ~5'555 USD/mois
- **Rendement requis**: 5.55% par mois

### Scenarios de trading

#### Scenario A: Conservative (Win Rate 45%, RR 1:1.5)
```
Expectancy = (0.45 × 1.5) - (0.55 × 1.0) = 0.675 - 0.55 = 0.125
Profit par trade = 0.125 × Risk
```
- Risk par trade: 1% = 1'000 USD
- Profit moyen par trade: 125 USD
- Trades necessaires: 5'555 / 125 = **45 trades/mois**
- Trades par jour: 2-3 trades

#### Scenario B: Moderate (Win Rate 50%, RR 1:1.5)
```
Expectancy = (0.50 × 1.5) - (0.50 × 1.0) = 0.75 - 0.50 = 0.25
```
- Risk par trade: 1% = 1'000 USD
- Profit moyen par trade: 250 USD
- Trades necessaires: 5'555 / 250 = **22 trades/mois**
- Trades par jour: 1 trade

#### Scenario C: Aggressive (Win Rate 55%, RR 1:2.0)
```
Expectancy = (0.55 × 2.0) - (0.45 × 1.0) = 1.10 - 0.45 = 0.65
```
- Risk par trade: 1% = 1'000 USD
- Profit moyen par trade: 650 USD
- Trades necessaires: 5'555 / 650 = **9 trades/mois**
- Trades par jour: 0.5 trade (tous les 2 jours)

---

## 3. RECOMMANDATIONS POUR ATTEINDRE L'OBJECTIF

### A. Filtrage strict des trades

```yaml
# config/config.yaml - Parametres optimises
orchestrator:
  min_score_for_proposal: 8.0     # Etait 7.0
  min_confluence: 5               # Etait 4
  hard_min_score: 7.5             # Nouveau seuil dur

volatility_filter:
  low_liquidity_hours_utc: [0,1,2,3,4,5,18,19,20,21,22,23]
```

### B. Symboles a privilegier
| Symbole | Action | Raison |
|---------|--------|--------|
| SP500 | GARDER | Score eleve, bonne confluence |
| UK100 | GARDER | Score eleve, faible contre-trend |
| BTCUSD | GARDER | Bonne performance |
| SOLUSD | SURVEILLER | Score correct mais volatil |
| XAUUSD | GARDER | Bonne confluence |
| ADAUSD | DESACTIVER | 72% contre-trend |
| USDJPY | DESACTIVER | 42% contre-trend |
| XAGUSD | REDUIRE | Score faible |

### C. Sessions optimales
| Session | Trades | Score Moy | Recommandation |
|---------|--------|-----------|----------------|
| London Close (15-17) | 64 | 9.1 | PRIORITAIRE |
| Off-hours | 82 | 9.3 | SELECTIF |
| NY (12-15) | 28 | 7.8 | ACTIF |
| London (07-10) | 9 | 6.8 | PRUDENT |

### D. Money Management SMC

```python
# Nouveau calcul SL base sur invalidation de structure
from utils.smc_patterns import compute_invalidation_sl

sl_info = compute_invalidation_sl(df, direction)
sl_price = sl_info['sl_price']
sl_distance = sl_info['distance_pct']

# Ajuster la taille de position
max_risk_pct = 1.0  # 1% du capital
position_size = (capital * max_risk_pct / 100) / sl_distance
```

---

## 4. PROJECTION REALISTE

### Hypotheses
- Capital: 100'000 USD
- Risk par trade: 1% (1'000 USD)
- Win rate cible: 48% (apres corrections)
- RR moyen: 1:1.6
- Trades qualifies par jour: 2

### Calcul mensuel
```
Expectancy = (0.48 × 1.6) - (0.52 × 1.0) = 0.768 - 0.52 = 0.248
Profit par trade = 0.248 × 1'000 = 248 USD
Trades par mois = 2 × 22 = 44 trades
Profit mensuel = 44 × 248 = 10'912 USD = ~9'820 CHF
```

### Avec corrections appliquees
Si on applique tous les filtres:
- Reduction des trades contre-trend de 32% a 15%
- Elimination des heures toxiques
- Desactivation ADAUSD/USDJPY

**Nouveau Win Rate estime: 52%**
```
Expectancy = (0.52 × 1.6) - (0.48 × 1.0) = 0.832 - 0.48 = 0.352
Profit par trade = 352 USD
Profit mensuel = 44 × 352 = 15'488 USD = ~13'939 CHF
```

---

## 5. TIMELINE VERS L'OBJECTIF

### Semaine 1-2: Stabilisation
- [ ] Appliquer tous les filtres stricts
- [ ] Desactiver ADAUSD et USDJPY
- [ ] Monitorer les metriques quotidiennes
- [ ] Objectif: Win Rate > 45%

### Semaine 3-4: Optimisation
- [ ] Ajuster les poids des agents selon performance
- [ ] Affiner les heures de trading
- [ ] Implementer le calendrier economique
- [ ] Objectif: Expectancy positive stable

### Mois 2: Scaling
- [ ] Augmenter graduellement le risk par trade (si metriques OK)
- [ ] Ajouter des symboles performants
- [ ] Objectif: 5'000 CHF/mois

### Mois 3+: Maintenance
- [ ] Audit hebdomadaire des performances
- [ ] Ajustements saisonniers
- [ ] Objectif: Maintenir 5'000+ CHF/mois

---

## 6. KPIs A SUIVRE QUOTIDIENNEMENT

| Metrique | Seuil Minimum | Cible | Action si <Min |
|----------|---------------|-------|----------------|
| Win Rate | 42% | 50%+ | Reduire trades |
| Profit Factor | 1.2 | 1.5+ | Verifier filtres |
| Score moyen | 7.5 | 9.0+ | Augmenter seuil |
| Confluence moyenne | 4.5 | 5.5+ | Verifier agents |
| Trades contre-trend | <20% | <10% | Verifier MTF |
| Drawdown journalier | <3% | <2% | Arreter trading |

---

## CONCLUSION

L'objectif de 5'000 CHF/mois est **REALISABLE** avec les conditions suivantes:

1. **Capital minimum**: 100'000 USD (deja disponible)
2. **Win rate minimum**: 45% avec RR 1:1.5
3. **Nombre de trades**: 2-3 par jour (haute qualite uniquement)
4. **Corrections critiques**: Toutes appliquees
5. **Discipline**: Suivre strictement les filtres

Le systeme actuel, avec les corrections appliquees, peut theoriquement generer
**10'000-15'000 CHF/mois** si les conditions sont respectees.

---

*Document genere le 2025-12-25*
*EmpireAgentIA_3 - Analyse de faisabilite*
