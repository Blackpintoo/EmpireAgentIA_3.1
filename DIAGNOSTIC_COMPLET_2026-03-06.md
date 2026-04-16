# Diagnostic Complet — EmpireAgentIA v3

**Date** : 6 mars 2026
**Analyste** : Claude
**Périmètre** : Analyse intégrale du code source (~170 fichiers Python)

---

## Résumé Exécutif

Le bot de trading ne prend **aucun trade** car il est bloqué par une combinaison de **3 problèmes majeurs** qui se renforcent mutuellement :

1. **Tous les agents timeout à 10 secondes** → score = 0, confluence = 0
2. **Hard filters impossibles à atteindre** → min_score = 8.0 et min_confluence = 5 agents
3. **Telegram en boucle d'erreur** → 474+ retries, notifications bloquées

Même si un seul de ces problèmes était résolu, les deux autres suffiraient à empêcher tout trade.

---

## Architecture du Système

```
main.py
  └─ Orchestrator (1 par symbole × 9 symboles = 9 instances)
       ├─ APScheduler : _run_agents_and_decide() toutes les 60s
       ├─ 9 agents en parallèle (asyncio.gather + to_thread)
       │    ├─ TechnicalAgent   → boucle sur 6 TFs (D1,H4,H1,M30,M5,M1)
       │    ├─ ScalpingAgent    → boucle sur 6 TFs
       │    ├─ SwingAgent       → boucle sur 6 TFs
       │    ├─ StructureAgent   → boucle sur 6 TFs
       │    ├─ WhaleAgent       → 1 appel global
       │    ├─ NewsAgent        → appels HTTP RSS externes
       │    ├─ SentimentAgent   → API Fear&Greed + Twitter + Google Trends
       │    ├─ FundamentalAgent → boucle sur 6 TFs
       │    └─ MacroAgent       → 1 appel global
       ├─ Agrégation des scores + votes
       ├─ Chaîne de filtres (15+ filtres successifs)
       ├─ RiskManager (sizing, daily limits, kill switch)
       └─ PositionManager (BE, partials, trailing) toutes les 20s
```

**9 symboles actifs** : NAS100, SP500, AUDUSD, USDJPY, XAUUSD, BNBUSD, LTCUSD, BTCUSD, SOLUSD

---

## Problème #1 : Timeouts Systématiques des Agents (CRITIQUE)

### Constat

Fichier : `orchestrator/orchestrator.py`, ligne 3938

```python
_AGENT_TIMEOUT = 10  # secondes
```

Chaque agent est exécuté via `asyncio.wait_for(asyncio.to_thread(fn), timeout=10)`. Quand un agent timeout, il retourne `None` → aucun signal → score 0.

### Cause Racine

Les agents techniques (technical, scalping, swing, structure) bouclent sur **6 timeframes** (D1, H4, H1, M30, M5, M1). Pour chaque timeframe, ils appellent `mt5.copy_rates_from_pos()` avec **300 barres**.

Calcul : 4 agents × 6 TFs × 300 barres × appel MT5 = **~72 requêtes MT5** en parallèle sur 9 symboles (648 requêtes au total par cycle). Avec un terminal MT5 unique, ces requêtes sont sérialisées et dépassent facilement les 10 secondes.

En plus, les agents news/sentiment/fundamental font des **appels HTTP externes** (RSS feeds, Fear&Greed API, Twitter, Google Trends, Alpha Vantage, Finnhub) — chacun avec ses propres latences réseau.

### Impact

- 100% des agents timeout sur 100% des symboles
- Score agrégé = 0.00 systématiquement
- Confluence = 0 (aucun agent ne vote)
- Le système boucle à vide toutes les 60 secondes sans jamais trader

### Solution Recommandée

```python
# 1. Augmenter le timeout à 30-60 secondes
_AGENT_TIMEOUT = 45  # secondes

# 2. Réduire les timeframes analysés (garder 3-4 max)
tfs: ["H4", "H1", "M15", "M5"]  # au lieu de 6 TFs

# 3. Réduire le nombre de barres
count = 150  # au lieu de 300

# 4. Ajouter un cache MT5 par symbole/TF (TTL 30-60s)
# Le MT5Client a déjà une classe TTLCache — l'activer dans les agents
```

---

## Problème #2 : Hard Filters Impossibles à Atteindre (CRITIQUE)

### Constat

Fichier : `orchestrator/orchestrator.py`, lignes 754-755

```python
self._hf_min_score: float = float(_hf.get("min_score", 8.0))
self._hf_min_confluence: int = int(_hf.get("min_confluence", 5))
```

Ces **hard filters** sont des seuils absolus qui ne peuvent pas être contournés (lignes 2080-2098). Ils sont **distincts** des seuils configurables `min_score_for_proposal` (2.5) et `min_confluence` (3) du config.yaml.

### Le Paradoxe de la Double Barrière

La chaîne de décision a **deux niveaux de filtrage** :

| Filtre | Seuil Score | Seuil Confluence | Source |
|--------|------------|-----------------|--------|
| Hard Filter (bloquant) | **8.0** | **5 agents** | Code par défaut |
| Soft Filter (config.yaml) | 2.5 | 3 | `config.yaml` ligne 194-195 |
| USDJPY spécifique | 8.0 | 5 | `profiles.yaml` ligne 417-418 |

Le FIX du 2026-03-05 a abaissé les seuils *soft* à 2.5/3, mais les **hard filters restent à 8.0/5** et bloquent en amont.

### Pourquoi c'est Impossible

Pour atteindre un score de 8.0, il faudrait que pratiquement **tous les agents** sur **tous les timeframes** donnent un signal unanime avec une forte conviction. Même dans des conditions parfaites, c'est quasiment inatteignable. Avec 9 agents dont plusieurs timeout systématiquement, c'est strictement impossible.

### Solution Recommandée

Dans `config.yaml`, ajouter une section `hard_filters` :

```yaml
orchestrator:
  hard_filters:
    min_score: 2.5        # Aligner avec min_score_for_proposal
    min_confluence: 3     # Aligner avec min_confluence
    min_rr: 1.2           # Ratio risque/récompense minimum
    tracker_contradiction: 0.25
```

---

## Problème #3 : Telegram en Boucle d'Erreur (MODÉRÉ)

### Constat

Les logs montrent 474+ retries consécutifs avec `TelegramNetworkError`. Le client async (`telegram_client_async.py`) tente de se reconnecter en boucle sans backoff suffisant.

### Impact

- Consomme des ressources CPU/réseau inutilement
- Aucune notification envoyée (startup, digest, trades, erreurs)
- Pas de blocage direct sur le trading, mais perte de monitoring

### Solution

- Vérifier le token Telegram et la connectivité réseau
- Ajouter un circuit-breaker : après 10 échecs → pause 5 minutes
- Le bot Telegram ne devrait pas bloquer les autres opérations

---

## Problème #4 : Session Hours Très Restrictives (MODÉRÉ)

### Constat

Fichier : `orchestrator/orchestrator.py`, ligne 764

```python
self._hf_blocked_hours: list = [0,1,2,3,4,5,18,19,20,21,22,23]  # UTC
```

Cela bloque **12 heures sur 24** (minuit-5h et 18h-23h UTC). Seules les heures **6h-17h UTC** sont ouvertes pour le trading.

### Impact

- Les cryptos (24/7) sont bloquées la moitié du temps
- Les sessions asiatique (0-5h UTC) et américaine après-midi (18h+ UTC) sont perdues
- Les symboles avec whitelist horaire (SOLUSD heures [13,23], LTCUSD heures [8,18,22]) sont doublement restreints

### Solution

Différencier les heures bloquées par type d'actif :

```yaml
orchestrator:
  session:
    blocked_hours_utc_forex: [0,1,2,3,4,5,22,23]
    blocked_hours_utc_crypto: []  # Cryptos 24/7
    blocked_hours_utc_indices: [0,1,2,3,4,5,21,22,23]
```

---

## Problème #5 : Chaîne de Filtres Trop Longue (MODÉRÉ)

### Constat

La méthode `_run_agents_and_decide()` (lignes 2818-3500+) applique **15+ filtres successifs** avant d'autoriser un trade :

1. Cooldown guard
2. Guard files (stop_all.flag, target_met.flag)
3. Position limits
4. Daily loss limit (absolute)
5. Daily loss + floating P&L
6. RiskManager daily limit
7. Consecutive losses cooldown
8. Kill switch global ($400/jour)
9. Circuit breaker (3 pertes = 24h pause)
10. EOD restriction (18h UTC)
11. Schedule profiles.yaml
12. Trading window
13. Agents signal gathering
14. Hard filters (score 8.0, confluence 5)
15. Soft filters (score 2.5, confluence 3)
16. Economic calendar
17. Volatility filter
18. Swing/scalping confirmation
19. Weekend guard
20. R:R ratio minimum
21. Gating backtest check

Chaque filtre est un point d'arrêt potentiel. En pratique, le signal n'arrive jamais au-delà du filtre #13 (agents timeout) et #14 (hard filters).

---

## Problème #6 : Configuration USDJPY Incohérente (MINEUR)

`profiles.yaml` ligne 417-418 :

```yaml
min_score_for_proposal: 8.0
min_confluence: 5
```

Ces seuils **par symbole** overrident les seuils globaux (2.5/3). USDJPY ne pourra donc jamais trader même si les problèmes globaux sont résolus.

---

## Tableau Récapitulatif des Corrections

| Priorité | Fichier | Correction | Impact |
|----------|---------|-----------|--------|
| **P0** | `orchestrator.py` L3938 | `_AGENT_TIMEOUT = 45` | Agents ne timeout plus |
| **P0** | `config.yaml` | Ajouter `hard_filters.min_score: 2.5` | Hard filters atteignables |
| **P0** | `config.yaml` | Ajouter `hard_filters.min_confluence: 3` | Hard filters atteignables |
| **P1** | `profiles.yaml` USDJPY | `min_score_for_proposal: 2.5` | USDJPY peut trader |
| **P1** | `config.yaml` | `tfs: [H4, H1, M15, M5]` | Moins de requêtes MT5 |
| **P1** | `orchestrator.py` L764 | Différencier heures crypto/forex | Plus de créneaux crypto |
| **P2** | `telegram_client_async.py` | Circuit-breaker après 10 échecs | Stop boucle d'erreur |
| **P2** | Agents `_get_rates()` | `count=150` au lieu de 300 | Requêtes MT5 plus rapides |
| **P3** | `orchestrator.py` | Réduire la chaîne de filtres | Simplifier la logique |

---

## Conclusion

Le système est actuellement dans un état de **blocage total** dû à trois problèmes interconnectés : les agents ne peuvent pas répondre dans le temps imparti (10s), et même s'ils le pouvaient, les hard filters (score 8.0, confluence 5) bloqueraient tout signal. Les corrections P0 (timeout + hard filters) doivent être appliquées **simultanément** pour que le système puisse recommencer à trader.

Le code est bien structuré et l'architecture multi-agents est solide. Le problème principal est un excès de couches de protection ajoutées successivement (chaque patch renforce les filtres) qui ont fini par rendre le système inopérant.
