# RAPPORT HEBDOMADAIRE - EmpireAgentIA_3

**Periode:** 2025-12-23 au 2025-12-30
**Genere le:** 2025-12-30 18:49:10

---
## 1. RESUME EXECUTIF

- **Trades:** 62 (32W / 30L)
- **Win Rate:** 51.6%
- **Profit Factor:** 1.00
- **P&L Total:** $-931.00
- **Drawdown Max:** $11,249.50

**Verdict:** Semaine **DEFICITAIRE**
**Score de sante du bot:** 3.0/10

---
## 2. STATISTIQUES DETAILLEES

### Performance globale

| Metrique | Valeur |
|----------|--------|
| Trades totaux | 62 |
| Gagnants | 32 |
| Perdants | 30 |
| Win Rate | 51.6% |
| Profit Factor | 1.00 |
| Gain brut | $16,583.99 |
| Perte brute | -$16,611.85 |
| P&L Net | $-931.00 |
| Gain moyen | $518.25 |
| Perte moyenne | -$553.73 |
| Meilleur trade | $1,701.27 |
| Pire trade | $-1,344.32 |
| R-Multiple moyen | 0.94 |
| Esperance | $-0.45 |
| Drawdown max | $11,249.50 |

### Performance par symbole

| Symbole | Trades | Win% | PF | P&L |
|---------|--------|------|-----|-----|
| SP500 | 20 | 90.0% | 9.46 | $7,307.29 |
| NAS100 | 10 | 30.0% | 7.18 | $3,718.04 |
| XAUUSD | 4 | 75.0% | 1.47 | $560.84 |
| EURUSD | 1 | 0.0% | 0.00 | $-115.08 |
| AUDUSD | 10 | 60.0% | 0.42 | $-436.25 |
| BTCUSD | 1 | 0.0% | 0.00 | $-542.35 |
| GBPUSD | 3 | 0.0% | 0.00 | $-2,695.39 |
| SOLUSD | 13 | 15.4% | 0.10 | $-8,728.10 |

### Performance par jour

| Jour | Trades | Win% | P&L |
|------|--------|------|-----|
| Lundi | 16 | 75.0% | $9,606.90 |
| Jeudi | 3 | 0.0% | $-2,664.69 |
| Vendredi | 36 | 50.0% | $-5,056.64 |
| Dimanche | 7 | 28.6% | $-2,816.57 |

### Performance par heure (Top 5)

| Heure | Trades | Win% | P&L |
|-------|--------|------|-----|
| 16:00 | 9 | 77.8% | $7,834.66 |
| 17:00 | 4 | 100.0% | $3,392.99 |
| 00:00 | 2 | 100.0% | $1,009.76 |
| 15:00 | 1 | 100.0% | $335.96 |
| 03:00 | 1 | 100.0% | $-406.89 |

### Performance par direction

| Direction | Trades | Win% | P&L |
|-----------|--------|------|-----|
| BUY | 45 | 48.9% | $-9,477.06 |
| SELL | 17 | 58.8% | $8,546.06 |

### Qualite des signaux

- **Signaux emis:** 94
- **Score moyen:** 10.0
- **Confluence moyenne:** 5.1
- **Score min/max:** 5.1 / 20.7

---
## 3. TOP TRADES

### Top 5 meilleurs trades

| # | Symbole | Type | Volume | Profit | Date |
|---|---------|------|--------|--------|------|
| 1 | XAUUSD | sell | 0.27 | $1,701.27 | 2025-12-29 17:06 |
| 2 | NAS100 | sell | 16.40 | $1,442.54 | 2025-12-29 16:50 |
| 3 | NAS100 | sell | 16.40 | $1,438.44 | 2025-12-29 16:50 |
| 4 | NAS100 | sell | 16.30 | $1,438.31 | 2025-12-29 16:50 |
| 5 | SP500 | sell | 89.30 | $1,434.16 | 2025-12-29 16:49 |

### Top 5 pires trades

| # | Symbole | Type | Volume | Perte | Date |
|---|---------|------|--------|-------|------|
| 1 | SOLUSD | buy | 45.57 | $-1,344.32 | 2025-12-26 18:01 |
| 2 | XAUUSD | buy | 0.52 | $-1,201.72 | 2025-12-26 20:20 |
| 3 | SOLUSD | sell | 86.98 | $-1,165.54 | 2025-12-25 16:43 |
| 4 | SOLUSD | buy | 73.10 | $-1,089.19 | 2025-12-28 22:05 |
| 5 | SOLUSD | buy | 40.26 | $-970.27 | 2025-12-29 12:42 |

---
## 4. POINTS FORTS

- Win rate superieur a 50% (51.6%)
- Symboles performants: SP500, XAUUSD, AUDUSD
- Direction SELL performante (58.8% win rate)

---
## 5. POINTS FAIBLES

- Profit Factor faible (1.00 < 1.3)
- Esperance negative ($-0.45)
- Symboles deficitaires: SOLUSD, GBPUSD, AUDUSD

---
## 6. RECOMMANDATIONS

### Recommandation 1

**PROBLEME:** Profit Factor faible (1.00)
**CAUSE PROBABLE:** Ratio risque/reward insuffisant ou gains coupes trop tot
**ACTIONS:**
- Augmenter le target R/R de 1.5 a 2.0
- Implementer un trailing stop plus agressif
- Reduire le stop loss pour un meilleur R/R
**FICHIER:** `config/config.yaml`

### Recommandation 2

**PROBLEME:** SOLUSD: Win rate critique (15.4%)
**CAUSE PROBABLE:** Ce symbole ne correspond pas aux strategies actuelles
**ACTIONS:**
- Desactiver temporairement SOLUSD
- Analyser les conditions de marche specifiques
- Revoir les parametres specifiques au symbole
**FICHIER:** `config/symbols.yaml`

### Recommandation 3

**PROBLEME:** NAS100: Win rate critique (30.0%)
**CAUSE PROBABLE:** Ce symbole ne correspond pas aux strategies actuelles
**ACTIONS:**
- Desactiver temporairement NAS100
- Analyser les conditions de marche specifiques
- Revoir les parametres specifiques au symbole
**FICHIER:** `config/symbols.yaml`

### Recommandation 4

**PROBLEME:** Heures deficitaires: 18:00, 19:00, 12:00
**CAUSE PROBABLE:** Sessions de trading non optimales
**ACTIONS:**
- Revoir les heures de trading autorisees
- Reduire l'exposition pendant ces heures
- Ajouter des filtres de session
**FICHIER:** `config/config.yaml`

---
## 7. PARAMETRES A AJUSTER

| Parametre | Actuel | Recommande | Raison |
|-----------|--------|------------|--------|
| min_score | 5.0 | 5.0 | OK |
| min_confluence | 3 | 3 | OK |
| symbols_to_disable | - | SOLUSD, NAS100 | Performance critique |

---
## 8. PLAN D'ACTION PRIORITAIRE

2. **CRITIQUE:** Revoir la strategie de sortie (R/R target, trailing stop)
3. **IMPORTANT:** Desactiver temporairement les symboles deficitaires: SOLUSD, GBPUSD
