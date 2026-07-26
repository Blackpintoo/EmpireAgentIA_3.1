# PROMPT CLAUDE CODE — Fix Opérationnel (Round 9)

## Contexte

Après Round 8, l'infrastructure est stable et le bot a tradé 8h27 le 13 mars (vs <1h avant R8). Résultats du diagnostic du 13 mars :
- ✅ Kill switch R8 : fonctionne (realized -$400 / floating -$800)
- ✅ R:R guard R8 : en place (0 activation nécessaire)
- ⚠️ Outcome tracker R8 : deadlock COM corrigé, mais 14 positions trackées / 0 clôtures enregistrées
- ❌ HARD_FILTER : 407 PASS / 0 REJECT (0% de rejet — filtre inutile)
- ❌ LTCUSD a ouvert avec $1,235 de risque (6x la moyenne) 30s avant le kill switch

**5 problèmes à corriger, par ordre de criticité :**

---

## FIX 1 — Outcome Tracker : mécanisme de retry pour les clôtures ⭐ CRITIQUE

### Cause racine

Dans `_poll_and_update()` (ligne ~848-870), quand une position disparaît de `positions_get()` :
1. Le tracker appelle `_get_recent_deals(since_days=2)` puis `_get_closing_deals_for_ticket(ticket, deals)`
2. Si `closing_deals` est **vide** (deal pas encore dans l'historique MT5), le ticket est **supprimé définitivement** du tracking (ligne 869) :
   ```python
   if not closing_deals:
       logger.debug(f"[OUTCOME] Deal non trouvé pour #{ticket}")
       del self._tracked_positions[ticket]
       continue
   ```
3. Le deal apparaît dans `history_deals_get()` quelques secondes plus tard, mais le ticket n'est plus tracké → **la clôture n'est jamais enregistrée**

C'est un **problème de timing** : MT5 a un délai entre la disparition d'une position de `positions_get()` et l'apparition du deal dans `history_deals_get()`. Avec le code actuel, la première tentative échoue et le ticket est abandonné.

Le `logger.debug` à la ligne 868 est invisible dans les logs (niveau INFO), donc le problème est silencieux.

### Solution

Ajouter un mécanisme de "pending closure" avec retry.

**Fichier** : `utils/trade_outcome_tracker.py`

**Étape 1a** — Ajouter un attribut de retry dans `__init__` (après `self._partial_aggregation`, vers la ligne ~243) :

Chercher :
```python
        # Agrégation des fermetures partielles par ticket
        # {ticket: {"deals": [...], "total_profit": float, "total_commission": float, ...}}
        self._partial_aggregation: Dict[int, Dict[str, Any]] = {}
```

Ajouter APRÈS :
```python
        # FIX 2026-03-13 R9: Pending closure avec retry
        # {ticket: {"attempts": int, "first_seen": datetime}}
        self._pending_closures: Dict[int, Dict[str, Any]] = {}
        self._max_closure_retries: int = 10   # 10 tentatives × 30s = 5 min max
```

**Étape 1b** — Remplacer la logique de détection de clôture dans `_poll_and_update`. Chercher le bloc (lignes ~848-924) :

```python
                    # 4. Détecter les positions fermées
                    tracked_tickets = set(self._tracked_positions.keys())
                    current_tickets = set(current_positions.keys())
                    closed_tickets = tracked_tickets - current_tickets

                    for ticket in closed_tickets:
                        if ticket in self._closed_tickets:
                            if ticket in self._tracked_positions:
                                del self._tracked_positions[ticket]
                            continue

                        original = self._tracked_positions.get(ticket)
                        if not original:
                            continue

                        # Chercher TOUS les deals de clôture pour ce ticket
                        deals = self._get_recent_deals(since_days=2)
                        closing_deals = self._get_closing_deals_for_ticket(ticket, deals)

                        if not closing_deals:
                            logger.debug(f"[OUTCOME] Deal non trouvé pour #{ticket}")
                            del self._tracked_positions[ticket]
                            continue
```

Remplacer par :
```python
                    # 4. Détecter les positions fermées
                    tracked_tickets = set(self._tracked_positions.keys())
                    current_tickets = set(current_positions.keys())
                    closed_tickets = tracked_tickets - current_tickets

                    # FIX 2026-03-13 R9: Ajouter aussi les pending closures au check
                    for pending_ticket in list(self._pending_closures.keys()):
                        if pending_ticket not in closed_tickets:
                            closed_tickets.add(pending_ticket)

                    for ticket in closed_tickets:
                        if ticket in self._closed_tickets:
                            if ticket in self._tracked_positions:
                                del self._tracked_positions[ticket]
                            self._pending_closures.pop(ticket, None)
                            continue

                        original = self._tracked_positions.get(ticket)
                        if not original:
                            self._pending_closures.pop(ticket, None)
                            continue

                        # Chercher TOUS les deals de clôture pour ce ticket
                        deals = self._get_recent_deals(since_days=2)
                        closing_deals = self._get_closing_deals_for_ticket(ticket, deals)

                        if not closing_deals:
                            # FIX 2026-03-13 R9: Ne pas supprimer immédiatement — retry
                            if ticket not in self._pending_closures:
                                self._pending_closures[ticket] = {
                                    "attempts": 1,
                                    "first_seen": datetime.now(timezone.utc),
                                }
                                logger.info(
                                    f"[OUTCOME] Deal non trouvé pour #{ticket} {original.symbol} "
                                    f"— retry 1/{self._max_closure_retries}"
                                )
                            else:
                                self._pending_closures[ticket]["attempts"] += 1
                                attempts = self._pending_closures[ticket]["attempts"]
                                logger.info(
                                    f"[OUTCOME] Deal toujours non trouvé pour #{ticket} {original.symbol} "
                                    f"— retry {attempts}/{self._max_closure_retries}"
                                )
                                if attempts >= self._max_closure_retries:
                                    logger.warning(
                                        f"[OUTCOME] Abandon #{ticket} {original.symbol} après "
                                        f"{attempts} tentatives — deal introuvable dans l'historique MT5"
                                    )
                                    del self._tracked_positions[ticket]
                                    del self._pending_closures[ticket]
                            continue
```

**Étape 1c** — Après le bloc `if outcome:` qui enregistre la clôture (lignes ~881-924), il y a `del self._tracked_positions[ticket]`. Ajouter le nettoyage du pending :

Chercher :
```python
                        # Nettoyer
                        del self._tracked_positions[ticket]
```

Remplacer par :
```python
                        # Nettoyer
                        del self._tracked_positions[ticket]
                        self._pending_closures.pop(ticket, None)  # FIX R9: cleanup pending
```

**Résultat** : Les positions fermées sont réessayées pendant 5 min max (10 × 30s). Le deal a le temps d'apparaître dans l'historique MT5. Les logs sont au niveau INFO (visibles).

---

## FIX 2 — HARD_FILTER : remonter les seuils ⭐ IMPORTANT

### Problème

Le HARD_FILTER a 0% de rejet (407 PASS, 0 REJECT le 13 mars). Les seuils ont été progressivement abaissés pour "débloquer le trading" :
- `min_score` : 8.0 → 2.5 (fix du 6 mars)
- `min_confluence` : 3.0 → 2.0 (fix du 8 mars)
- `min_rr` : 1.2 → 0.8 (fix du 8 mars)

À 2.5 de score minimum, **tout passe**. Le filtre ne filtre rien. Le bot prend 14 trades en une journée dont la plupart sont perdants.

### Solution

Remonter les seuils à un niveau intermédiaire qui filtre les signaux faibles sans tout bloquer.

**Fichier** : `config/config.yaml`

Chercher dans la section `hard_filters:` (vers la ligne ~301) :
```yaml
  hard_filters:
    min_score: 2.5                     # FIX 2026-03-06: aligné avec fallback Python
    min_confluence: 2.0                # FIX 2026-03-08: 3→2.0 pour débloquer trading
    tracker_contradiction: 0.25
    disagree_block_pct: 0.45
    disagree_penalty_pct: 0.35
    min_rr: 0.8                        # FIX 2026-03-08: 1.2→0.8 pour débloquer trading
    counter_trend_min_score: 6.0
```

Remplacer par :
```yaml
  hard_filters:
    min_score: 5.0                     # FIX 2026-03-13 R9: 2.5→5.0 (trop permissif, 0% rejet)
    min_confluence: 2.5                # FIX 2026-03-13 R9: 2.0→2.5 (filtrer les signaux faibles)
    tracker_contradiction: 0.25
    disagree_block_pct: 0.45
    disagree_penalty_pct: 0.35
    min_rr: 1.0                        # FIX 2026-03-13 R9: 0.8→1.0 (R:R minimum raisonnable)
    counter_trend_min_score: 6.0
```

**Logique des nouveaux seuils :**
- `min_score: 5.0` — les scores vont de 0 à ~12. Un score de 5.0 signifie que la majorité des agents sont alignés. Rejette les signaux faibles (<5.0) mais passe les signaux avec bonne confluence.
- `min_confluence: 2.5` — exige au moins 2-3 sources de confluence (timeframes ou agents alignés).
- `min_rr: 1.0` — exige un ratio risque/récompense d'au moins 1:1. Un trade avec R:R < 1.0 n'a pas d'edge statistique.

**Résultat attendu** : Le HARD_FILTER devrait rejeter ~30-60% des signaux, gardant les meilleurs.

---

## FIX 3 — Garde-fou risque absolu par trade ⭐ IMPORTANT

### Problème

LTCUSD a ouvert avec $1,235 de risque (6x la moyenne de ~$200), 30 secondes avant le kill switch floating. Le `risk_per_trade` est configuré à 0.002 (0.2%) mais le calcul de lots produit un risque disproportionné à cause de la valeur du point pour certains symboles crypto.

Le `max_volume` (5.0 lots pour LTCUSD) est vérifié dans `RiskManager.compute_position_size()`, mais le risque en dollars n'est pas plafonné directement.

### Solution

Ajouter un **plafond absolu de risque en USD** dans `execute_trade`, JUSTE AVANT l'appel `place_order`. Si le risque calculé dépasse le plafond, réduire le lot proportionnellement.

**Fichier** : `orchestrator/orchestrator.py`

Chercher le bloc `[RR_SAFETY]` dans `execute_trade` (ajouté en Round 8, vers la ligne ~2579). **APRÈS** le bloc try/except du `[RR_SAFETY]`, et **AVANT** l'appel `place_order`, ajouter :

```python
                # FIX 2026-03-13 R9: Garde-fou risque absolu par trade
                # Empêche les positions avec un risque en USD disproportionné
                try:
                    _max_risk_usd = float(self.risk.config.get("max_risk_per_trade_usd", 300.0))
                    if sl and entry and lots:
                        _sl_dist = abs(entry - sl)
                        _point_val = 1.0
                        try:
                            _sym_info = self._mt5_call("symbol_info", symbol)
                            if _sym_info:
                                _ts = getattr(_sym_info, "trade_tick_size", 0)
                                _tv = getattr(_sym_info, "trade_tick_value", 0)
                                if _ts > 0 and _tv > 0:
                                    _point_val = _tv / _ts
                        except Exception:
                            pass
                        _risk_usd = _sl_dist * lots * _point_val
                        if _risk_usd > _max_risk_usd:
                            _old_lots = lots
                            lots = (_max_risk_usd / (_sl_dist * _point_val))
                            # Arrondir aux step du symbole
                            try:
                                _vol_step = getattr(_sym_info, "volume_step", 0.01) if _sym_info else 0.01
                                lots = max(_vol_step, round(lots / _vol_step) * _vol_step)
                            except Exception:
                                lots = round(lots, 2)
                            logger.warning(
                                f"[RISK_CAP] {symbol}: risque ${_risk_usd:.0f} > max ${_max_risk_usd:.0f} "
                                f"→ lots réduits {_old_lots:.4f} → {lots:.4f}"
                            )
                except Exception as _risk_cap_err:
                    logger.debug(f"[RISK_CAP] Erreur: {_risk_cap_err}")
```

**Aussi**, ajouter le paramètre dans la config. Dans `config/config.yaml`, dans la section `risk:` (vers la ligne ~340), ajouter :

Chercher :
```yaml
    daily_loss_limit_pct: 0.02
```

Ajouter APRÈS :
```yaml
    max_risk_per_trade_usd: 300       # FIX R9: plafond absolu risque par trade ($)
```

**Note** : Le plafond de $300 est 1.5x la moyenne de risque (~$200). Il évite les dérapages comme les $1,235 de LTCUSD tout en laissant une marge raisonnable.

**Résultat** : Aucun trade ne peut risquer plus de $300 USD, quel que soit le calcul de lots.

---

## FIX 4 — Logging directionnel pour diagnostiquer le biais LONG

### Problème

93% des trades du 13 mars étaient LONG, malgré des signaux SHORT forts (SP500: 10.10, NAS100: 10.10). Le code de scoring dans `_run_agents_and_decide` est mathématiquement symétrique, mais quelque chose dans les agents ou les signaux produit un biais LONG systématique. On a besoin de données pour comprendre.

### Solution

Ajouter un log qui affiche les scores LONG et SHORT pour chaque décision, permettant de diagnostiquer la source du biais.

**Fichier** : `orchestrator/orchestrator.py`

Chercher dans `_run_agents_and_decide`, la ligne qui détermine la direction (vers la ligne ~4837) :

```python
        direction = "LONG" if score_long > score_short else ("SHORT" if score_short > score_long else "")
```

Ajouter **APRÈS** cette ligne :
```python
        # FIX 2026-03-13 R9: Log diagnostic pour biais directionnel
        logger.info(
            f"[SCORE_DIAG] {symbol}: LONG={score_long:.2f} SHORT={score_short:.2f} "
            f"→ {direction or 'NEUTRAL'} (delta={abs(score_long - score_short):.2f}, "
            f"confluence={confluence})"
        )
```

**Résultat** : Chaque cycle d'analyse logge les scores LONG et SHORT. Après une journée de trading, on pourra identifier si le biais vient des agents techniques, du régime de marché, ou des signaux globaux.

---

## FIX 5 — Finnhub API 403 : fallback gracieux

### Problème

L'API Finnhub renvoie 403 depuis 3+ jours (clé expirée ou quota dépassé). Cela génère des erreurs dans les logs et pourrait affecter la qualité des signaux si les données de calendrier économique sont manquantes.

### Solution

Ajouter un fallback qui désactive silencieusement Finnhub après 3 erreurs consécutives au lieu de retenter à chaque cycle.

**Fichier** : `utils/event_guard.py`

Chercher la méthode qui appelle l'API Finnhub (probablement dans `_fetch_finnhub` ou `_refresh_from_finnhub`). Identifier le bloc qui fait la requête HTTP.

**Ajouter un compteur d'erreurs** en haut de la classe `EventGuard.__init__` :

```python
        self._finnhub_consecutive_errors: int = 0
        self._finnhub_max_errors: int = 3
        self._finnhub_disabled: bool = False
```

**Dans la méthode de fetch Finnhub**, ajouter en début de méthode :

```python
        # FIX 2026-03-13 R9: Skip Finnhub si désactivé après trop d'erreurs
        if self._finnhub_disabled:
            return []  # ou {} selon le type de retour
```

Et dans le bloc `except` qui catch les erreurs 403 :

```python
        except Exception as e:
            self._finnhub_consecutive_errors += 1
            if self._finnhub_consecutive_errors >= self._finnhub_max_errors:
                self._finnhub_disabled = True
                logger.warning(
                    f"[EVENT_GUARD] Finnhub désactivé après {self._finnhub_consecutive_errors} "
                    f"erreurs consécutives: {e}"
                )
            else:
                logger.debug(f"[EVENT_GUARD] Finnhub erreur {self._finnhub_consecutive_errors}: {e}")
```

**Note** : Ce fix est moins critique que les 4 précédents. Si le temps manque, il peut être reporté au Round 10. L'impact est principalement du nettoyage de logs.

---

## Résumé des 5 fixes

| Fix | Fichier | Criticité | Impact |
|-----|---------|-----------|--------|
| 1 | `utils/trade_outcome_tracker.py` | ⭐ CRITIQUE | Retry 5 min pour les clôtures → CSV enfin rempli |
| 2 | `config/config.yaml` | ⭐ IMPORTANT | HARD_FILTER score 5.0 / confluence 2.5 / R:R 1.0 → ~40% rejet |
| 3 | `orchestrator/orchestrator.py` + `config/config.yaml` | ⭐ IMPORTANT | Max $300/trade → plus de positions à $1,235 |
| 4 | `orchestrator/orchestrator.py` | DIAGNOSTIC | Log LONG/SHORT scores → comprendre le biais 93% LONG |
| 5 | `utils/event_guard.py` | MINEUR | Finnhub 403 → désactivation gracieuse après 3 erreurs |

## Vérification après modification

```bash
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile orchestrator/orchestrator.py
python -m py_compile utils/event_guard.py
```

## Vérification en production (après 2-4h de trading)

1. **Outcome tracker** : chercher `[OUTCOME]` dans les logs.
   - `[OUTCOME] Deal non trouvé ... retry N/10` → le retry fonctionne
   - `[OUTCOME] Trade cloture` → les clôtures sont enregistrées !
   - Vérifier que `data/trade_outcomes.csv` contient des entrées.

2. **HARD_FILTER** : chercher `HARD_FILTER` dans les logs.
   - Compter PASS vs REJECT. Taux de rejet attendu : 30-60%.
   - Si >80% de rejet : `min_score` trop haut → baisser à 4.0.
   - Si <10% de rejet : `min_score` trop bas → monter à 6.0.

3. **Risk cap** : chercher `[RISK_CAP]` dans les logs.
   - Si présent : le plafond a empêché un trade surdimensionné.
   - Vérifier les lots et le risque des trades dans `trades_log.csv`.

4. **Score diagnostic** : chercher `[SCORE_DIAG]` dans les logs.
   - Pour chaque symbole, noter le ratio LONG/SHORT.
   - Si LONG >> SHORT systématiquement : le biais vient des agents.
   - Si variable : le biais vient du marché (trending up).

5. **Finnhub** : chercher `[EVENT_GUARD] Finnhub désactivé` dans les logs.
   - Si présent : Finnhub ne pollue plus les logs.
   - Penser à renouveler la clé API quand possible.

## RÈGLES

1. **Applique les fixes dans l'ordre 1 → 5.**
2. **Ne change rien d'autre.**
3. **Compile chaque fichier après modification.**
4. **Si un fix ne peut pas être appliqué** (code différent de ce qui est décrit), signale-le et passe au suivant.
