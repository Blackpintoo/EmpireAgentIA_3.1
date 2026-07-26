# PROMPT CLAUDE CODE — Fix Opérationnel (Round 12)

## Contexte

Le diagnostic du 15 mars révèle **deux problèmes critiques** :

### Problème #1 — `history_deals_get()` ne trouve AUCUN deal (7/7 abandons)

Le outcome tracker détecte les positions qui disparaissent de MT5, mais quand il cherche les deals de clôture dans `history_deals_get()`, il ne trouve **jamais rien**. 100% des positions sont abandonnées après 10 retries (5 min). Le `trade_outcomes.csv` est resté à 3 entrées depuis le 1er mars.

**Causes racines identifiées :**

1. **Dates timezone-aware** : Le code utilise `datetime.now(timezone.utc)` qui produit des `datetime` avec `tzinfo=UTC`. L'API Python MT5 attend des **datetime naïfs** (sans tzinfo). Avec des dates timezone-aware, `history_deals_get()` peut retourner `None` ou une tuple vide silencieusement.

2. **Recherche inefficace** : Le code récupère TOUS les deals récents avec `history_deals_get(start, end)` puis filtre manuellement par `position_id`. L'API MT5 supporte directement `history_deals_get(position=ticket_id)` qui est beaucoup plus fiable et ciblé.

### Problème #2 — RR_SAFETY guard n'a pas bloqué BTCUSD #981546157 (RR=0.03)

BTCUSD ouvert avec TP=+37 pts / SL=-1232 pts = RR 0.03. Le guard R8 n'a pas bloqué.

**Causes identifiées :**

1. Le guard ajuste le TP mais **ne rejette jamais le trade**. Même avec un RR aberrant, le trade passe.
2. Le bloc `except Exception: logger.debug(...)` avale silencieusement toute erreur. Si une exception a lieu dans le calcul, le guard est complètement bypassed sans aucune trace visible dans les logs.
3. Si `sl` ou `tp` ou `entry` est 0, les conditions `if entry and sl` sont `False` et le guard est skippé.

---

## FIX 1 — Outcome Tracker : corriger `history_deals_get()` ⭐⭐ CRITIQUE

### Fichier : `utils/trade_outcome_tracker.py`

### Étape 1a — Réécrire `_get_recent_deals` avec datetime naïfs + recherche par position

Chercher la méthode `_get_recent_deals` (vers la ligne ~507) :

```python
    def _get_recent_deals(self, since_days: int = 1) -> List[Any]:
        """Récupère les deals récents depuis MT5."""
        if not MT5_AVAILABLE or not mt5:
            return []

        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=since_days)

            deals = _mt5_call_safe(mt5.history_deals_get, start, now)
            return list(deals) if deals else []

        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur récupération deals: {e}")
            return []
```

Remplacer par :
```python
    def _get_recent_deals(self, since_days: int = 1) -> List[Any]:
        """Récupère les deals récents depuis MT5.
        FIX 2026-03-15 R12: Utilise des datetime naïfs (requis par l'API MT5 Python)."""
        if not MT5_AVAILABLE or not mt5:
            return []

        try:
            # FIX R12: MT5 Python API requiert des datetime NAÏFS (sans tzinfo)
            from datetime import datetime as _dt
            now = _dt.utcnow()
            start = now - timedelta(days=since_days)

            deals = _mt5_call_safe(mt5.history_deals_get, start, now)
            if deals is None or len(deals) == 0:
                logger.debug(f"[OUTCOME] history_deals_get({since_days}j): 0 deals")
                return []
            result = list(deals)
            logger.debug(f"[OUTCOME] history_deals_get({since_days}j): {len(result)} deals")
            return result

        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur récupération deals: {e}")
            return []
```

### Étape 1b — Ajouter une méthode de recherche ciblée par position_id

Après `_get_recent_deals`, ajouter cette nouvelle méthode :

```python
    def _get_deals_for_position(self, ticket: int) -> List[Any]:
        """Récupère les deals d'une position spécifique via l'API MT5.
        FIX 2026-03-15 R12: Utilise history_deals_get(position=ticket) — plus fiable."""
        if not MT5_AVAILABLE or not mt5:
            return []

        try:
            # Méthode 1: Recherche directe par position_id (la plus fiable)
            deals = _mt5_call_safe(mt5.history_deals_get, position=ticket)
            if deals is not None and len(deals) > 0:
                result = list(deals)
                logger.info(
                    f"[OUTCOME] Deals pour position #{ticket}: {len(result)} trouvés "
                    f"(méthode position=)"
                )
                return result

            # Méthode 2: Fallback par date (7 jours, datetime naïfs)
            from datetime import datetime as _dt
            now = _dt.utcnow()
            start = now - timedelta(days=7)
            all_deals = _mt5_call_safe(mt5.history_deals_get, start, now)
            if all_deals is not None and len(all_deals) > 0:
                matching = [
                    d for d in all_deals
                    if getattr(d, "position_id", 0) == ticket
                ]
                if matching:
                    logger.info(
                        f"[OUTCOME] Deals pour position #{ticket}: {len(matching)} trouvés "
                        f"(méthode date fallback sur {len(all_deals)} deals totaux)"
                    )
                    return matching
                else:
                    logger.warning(
                        f"[OUTCOME] Position #{ticket}: 0 deals matching sur "
                        f"{len(all_deals)} deals totaux (7j). position_id non trouvé."
                    )
            else:
                logger.warning(
                    f"[OUTCOME] Position #{ticket}: history_deals_get retourne "
                    f"{'None' if all_deals is None else '0 deals'} (7j)"
                )

            return []

        except Exception as e:
            logger.warning(f"[OUTCOME] Erreur _get_deals_for_position(#{ticket}): {e}")
            return []
```

### Étape 1c — Modifier `_poll_and_update` pour utiliser la nouvelle méthode

Dans `_poll_and_update`, chercher le bloc qui cherche les deals de clôture (vers la ligne ~872) :

```python
                        # Chercher TOUS les deals de clôture pour ce ticket
                        deals = self._get_recent_deals(since_days=2)
                        closing_deals = self._get_closing_deals_for_ticket(ticket, deals)
```

Remplacer par :
```python
                        # FIX 2026-03-15 R12: Recherche ciblée par position + fallback
                        all_position_deals = self._get_deals_for_position(ticket)
                        closing_deals = self._get_closing_deals_for_ticket(ticket, all_position_deals)
```

### Étape 1d — Modifier `_reconcile_at_startup` de la même façon

Dans `_reconcile_at_startup`, chercher (vers la ligne ~371-372) :

```python
        # Récupérer les deals récents (7 jours pour couvrir les weekends)
        deals = self._get_recent_deals(since_days=7)
```

ET plus bas (vers la ligne ~380) :

```python
            closing_deals = self._get_closing_deals_for_ticket(ticket, deals)
```

Remplacer le premier par :
```python
        # FIX R12: On utilise _get_deals_for_position par ticket (plus fiable)
        # La variable deals n'est plus utilisée globalement
```

Et le second par :
```python
            # FIX R12: Recherche ciblée par position
            all_position_deals = self._get_deals_for_position(ticket)
            closing_deals = self._get_closing_deals_for_ticket(ticket, all_position_deals)
```

### Étape 1e — Ajouter une méthode de diagnostic (appelable manuellement)

À la fin de la classe `TradeOutcomeTracker` (avant les fonctions utilitaires globales), ajouter :

```python
    def diagnostic_check_deals(self) -> Dict[str, Any]:
        """Diagnostic: vérifie si history_deals_get fonctionne correctement.
        FIX R12: Permet de tester l'API MT5 sans attendre une clôture."""
        result = {
            "mt5_available": MT5_AVAILABLE,
            "tracked_positions": len(self._tracked_positions),
            "closed_tickets": len(self._closed_tickets),
        }

        if not MT5_AVAILABLE or not mt5:
            result["error"] = "MT5 non disponible"
            return result

        # Test 1: history_deals_get avec dates naïves (7 jours)
        try:
            from datetime import datetime as _dt
            now = _dt.utcnow()
            start = now - timedelta(days=7)
            deals = _mt5_call_safe(mt5.history_deals_get, start, now)
            result["deals_7d_naive"] = len(deals) if deals else 0
            result["deals_7d_type"] = type(deals).__name__ if deals is not None else "None"
        except Exception as e:
            result["deals_7d_error"] = str(e)

        # Test 2: history_deals_get avec dates timezone-aware (pour comparaison)
        try:
            now_utc = datetime.now(timezone.utc)
            start_utc = now_utc - timedelta(days=7)
            deals_utc = _mt5_call_safe(mt5.history_deals_get, start_utc, now_utc)
            result["deals_7d_utc"] = len(deals_utc) if deals_utc else 0
            result["deals_7d_utc_type"] = type(deals_utc).__name__ if deals_utc is not None else "None"
        except Exception as e:
            result["deals_7d_utc_error"] = str(e)

        # Test 3: Pour chaque position trackée, chercher les deals
        for ticket, pos in list(self._tracked_positions.items())[:3]:
            try:
                pos_deals = _mt5_call_safe(mt5.history_deals_get, position=ticket)
                result[f"position_{ticket}"] = len(pos_deals) if pos_deals else 0
            except Exception as e:
                result[f"position_{ticket}_error"] = str(e)

        logger.info(f"[OUTCOME] DIAGNOSTIC: {json.dumps(result, default=str)}")
        return result
```

**Résultat attendu** :
- `history_deals_get(position=ticket)` est la méthode la plus fiable pour trouver les deals d'une position
- Les datetime naïfs (`utcnow()` sans tzinfo) résolvent le problème potentiel d'API MT5
- Le diagnostic permet de vérifier exactement ce que l'API retourne

---

## FIX 2 — RR_SAFETY : rejeter le trade si RR aberrant ⭐ IMPORTANT

### Problème

Le guard actuel (R8) ajuste le TP mais ne bloque jamais le trade. Le `except Exception: pass` (avec `logger.debug`) avale silencieusement toute erreur. BTCUSD a passé avec un RR de 0.03.

### Solution

Transformer le guard en vrai bloqueur : si le RR est < min_rr ET que la correction TP échoue, **bloquer le trade**.

### Fichier : `orchestrator/orchestrator.py`

Chercher le bloc RR_SAFETY (vers la ligne ~2579-2601) :

```python
                # FIX 2026-03-12 R8: Dernier garde-fou R:R avant order_send
                try:
                    _final_rr_min = max(0.50, float(getattr(self, '_hf_min_rr', 0.80)))
                    if action == "BUY":
                        _f_risk = abs(entry - sl) if entry and sl else 0
                        _f_reward = abs(tp - entry) if entry and tp else 0
                    else:
                        _f_risk = abs(sl - entry) if entry and sl else 0
                        _f_reward = abs(entry - tp) if entry and tp else 0
                    _f_rr = _f_reward / max(_f_risk, 1e-9) if _f_risk > 0 else 0
                    if _f_risk > 0 and _f_rr < _final_rr_min:
                        _f_new_tp_dist = _f_risk * self._hf_min_rr
                        if action == "BUY":
                            tp = entry + _f_new_tp_dist
                        else:
                            tp = entry - _f_new_tp_dist
                        _f_new_rr = _f_new_tp_dist / max(_f_risk, 1e-9)
                        logger.warning(
                            f"[RR_SAFETY] {symbol}: R:R final {_f_rr:.3f} < {_final_rr_min} → "
                            f"TP recalculé {tp:.5f} (R:R={_f_new_rr:.2f})"
                        )
                except Exception as _rr_safety_err:
                    logger.debug(f"[RR_SAFETY] Erreur: {_rr_safety_err}")
```

Remplacer par :
```python
                # FIX 2026-03-15 R12: Garde-fou R:R — BLOQUE le trade si RR aberrant
                _rr_trade_blocked = False
                try:
                    _final_rr_min = max(0.50, float(getattr(self, '_hf_min_rr', 0.80)))
                    if action == "BUY":
                        _f_risk = abs(entry - sl) if (entry and sl and entry > sl) else 0
                        _f_reward = abs(tp - entry) if (entry and tp and tp > entry) else 0
                    else:
                        _f_risk = abs(sl - entry) if (entry and sl and sl > entry) else 0
                        _f_reward = abs(entry - tp) if (entry and tp and entry > tp) else 0

                    _f_rr = _f_reward / max(_f_risk, 1e-9) if _f_risk > 0 else 0

                    if _f_risk > 0 and _f_rr < _final_rr_min:
                        # Tenter de corriger le TP
                        _f_new_tp_dist = _f_risk * self._hf_min_rr
                        if action == "BUY":
                            tp = entry + _f_new_tp_dist
                        else:
                            tp = entry - _f_new_tp_dist
                        _f_new_rr = _f_new_tp_dist / max(_f_risk, 1e-9)
                        logger.warning(
                            f"[RR_SAFETY] {symbol}: R:R {_f_rr:.3f} < {_final_rr_min} → "
                            f"TP corrigé {tp:.5f} (R:R={_f_new_rr:.2f})"
                        )

                    # Vérifier que le RR est maintenant acceptable
                    if _f_risk > 0:
                        if action == "BUY":
                            _f_reward_final = abs(tp - entry) if tp > entry else 0
                        else:
                            _f_reward_final = abs(entry - tp) if entry > tp else 0
                        _f_rr_final = _f_reward_final / max(_f_risk, 1e-9)
                        if _f_rr_final < 0.30:
                            # RR toujours aberrant après correction → BLOQUER
                            _rr_trade_blocked = True
                            logger.error(
                                f"[RR_SAFETY] {symbol}: R:R TOUJOURS ABERRANT {_f_rr_final:.3f} "
                                f"après correction — TRADE BLOQUÉ "
                                f"(entry={entry}, sl={sl}, tp={tp})"
                            )
                    elif entry and sl:
                        # Risk = 0 signifie SL = entry → trade sans risque ou bug
                        logger.warning(
                            f"[RR_SAFETY] {symbol}: risk=0 (entry={entry}, sl={sl}) — suspect"
                        )

                except Exception as _rr_safety_err:
                    logger.warning(f"[RR_SAFETY] {symbol}: Erreur guard — {_rr_safety_err}")

                if _rr_trade_blocked:
                    logger.error(f"[RR_SAFETY] {symbol}: Trade REJETÉ (RR aberrant)")
                    return None
```

**Points clés du fix :**
1. Ajout de vérifications directionnelles : `entry > sl` pour BUY, `sl > entry` pour SELL — empêche les calculs inversés
2. Double vérification : après la correction du TP, revérifier le RR. Si toujours < 0.30, **bloquer le trade**
3. `logger.debug` → `logger.warning` pour les exceptions (visibles dans les logs)
4. `_rr_trade_blocked = True` + `return None` après le bloc try/except → le trade est bloqué proprement

**Note** : le seuil de blocage est 0.30 (pas 0.80). C'est un filet de sécurité pour les RR aberrants (0.03, 0.05), pas un filtre de qualité (c'est le rôle du HARD_FILTER).

---

## FIX 3 — HARD_FILTER : baisser min_score de 4.0 à 3.5

### Problème

Le taux de rejet est de 77% (106 REJECT / 31 PASS). Encore au-dessus de la cible 40-70%. BTCUSD est souvent rejeté à 3.8-4.2. Le weekend biaise les résultats (moins de symboles actifs), mais un ajustement léger est justifié.

### Solution

**Fichier** : `config/config.yaml`

Chercher :
```yaml
    min_score: 4.0                     # FIX 2026-03-14 R10: 5.0→4.0 (97% rejet trop strict)
```

Remplacer par :
```yaml
    min_score: 3.5                     # FIX 2026-03-15 R12: 4.0→3.5 (77% rejet, cible 40-70%)
```

**Note** : On valide ce seuil sur une journée de semaine complète (lundi-vendredi). Si le taux de rejet est <30% en semaine, remonter à 4.0.

---

## Résumé des 3 fixes

| Fix | Fichier(s) | Criticité | Impact |
|-----|-----------|-----------|--------|
| 1 | `utils/trade_outcome_tracker.py` | ⭐⭐ CRITIQUE | Datetime naïfs + recherche par position → deals enfin trouvés |
| 2 | `orchestrator/orchestrator.py` | ⭐ IMPORTANT | RR_SAFETY bloque les trades avec RR < 0.30, plus de silencing |
| 3 | `config/config.yaml` | AJUSTEMENT | min_score 4.0→3.5, taux rejet attendu ~50% |

## Vérification après modification

```bash
python -m py_compile utils/trade_outcome_tracker.py
python -m py_compile orchestrator/orchestrator.py
```

## Vérification en production — TEST CRITIQUE POUR LE TRACKER

### Méthode 1 : Diagnostic automatique (immédiat)

Après démarrage du bot, exécuter ce script Python dans le même environnement :

```python
import sys, os
sys.path.insert(0, os.getcwd())
from utils.trade_outcome_tracker import get_outcome_tracker
tracker = get_outcome_tracker()
result = tracker.diagnostic_check_deals()
print(result)
```

Vérifier dans le résultat :
- `deals_7d_naive > 0` → l'API MT5 retourne des deals avec des dates naïves
- `deals_7d_utc == 0` → confirmation que les dates UTC causaient le problème
- `position_XXXXX > 0` → la recherche par position fonctionne

### Méthode 2 : Attendre une clôture (2-4h)

1. Chercher `[OUTCOME] Deals pour position #` dans les logs.
   - `N trouvés (méthode position=)` → la recherche ciblée fonctionne !
   - `N trouvés (méthode date fallback)` → la méthode position= n'a pas marché, mais le fallback oui
   - Ni l'un ni l'autre → problème plus profond (vérifier le diagnostic)

2. Chercher `[OUTCOME] Trade cloture:` dans les logs.
   - Si présent → **VICTOIRE** ! Le tracker enregistre enfin les clôtures.

3. Vérifier `data/trade_outcomes.csv` :
   ```bash
   type data\trade_outcomes.csv
   ```
   - Nouvelles entrées post-15 mars → tracker complet

### Méthode 3 : RR_SAFETY

Chercher `[RR_SAFETY]` dans les logs :
- `R:R ... < ... → TP corrigé` → le guard ajuste les TP aberrants
- `R:R TOUJOURS ABERRANT ... TRADE BLOQUÉ` → le guard a bloqué un trade dangereux
- `Erreur guard` → le guard a une exception (visible maintenant avec logger.warning)

## RÈGLES

1. **Applique les fixes dans l'ordre 1 → 3.**
2. **Ne change rien d'autre.**
3. **Le FIX 1 est le plus important.** C'est le fix qui résout le problème #1 depuis Round 8.
4. **Compile chaque fichier après modification.**
5. **Après le redémarrage, le diagnostic immédiat (Méthode 1) est crucial** pour confirmer que l'API MT5 répond correctement.
