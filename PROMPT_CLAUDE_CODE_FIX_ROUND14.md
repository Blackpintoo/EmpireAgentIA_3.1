# PROMPT CLAUDE CODE — Fix Opérationnel (Round 14)

## Contexte

Le diagnostic R13 a identifié la **CAUSE RACINE** des TP aberrants grâce aux logs `[TP_TRACE]` :

### Le problème : ENTRY STALE

Les agents calculent SL/TP comme des **prix absolus** basés sur le prix au moment de l'analyse. Mais entre l'analyse et l'exécution de l'ordre, le marché bouge (10-50 points selon le symbole). L'ordre market fill au prix ACTUEL, mais SL/TP restent fixés sur l'ANCIEN prix.

**Exemple concret (XAUUSD)** :
1. Analyse : entry=4988.85, TP=4944.71, SL=5022.73 → RR=1.39 ✅
2. Marché descend à 4950.22 (favorable pour le SELL)
3. Fill au prix 4950.22 → TP=4944.71 = seulement 5.51 pts du fill
4. RR réel = 5.51 / 72.51 = **0.076** ❌ (au lieu de 1.39)
5. Trade gagne +$49 au lieu de ~$560

**Cas catastrophique (SP500)** :
1. Proposal SELL: entry=6699.92, SL=6708.38
2. Marché monte à 6742.73 (+43 pts !)
3. SL est maintenant EN-DESSOUS du fill → _respect_min_stops le colle au prix
4. Stop-out instantané → -$1.25

**Impact mesuré** : manque à gagner de **~$600/jour**. 8 TP wins = +$391 (avg $49/win). Avec RR correct, attendu +$1,000/jour (avg $125/win).

---

## FIX 1 — Recalculer SL/TP sur le prix actuel avant place_order ⭐⭐⭐ CRITIQUE

### Principe

Juste AVANT l'appel `place_order`, on :
1. Récupère le prix ACTUEL du marché (ask pour BUY, bid pour SELL)
2. Calcule les DISTANCES SL et TP (depuis l'entry du proposal)
3. Recalcule SL et TP en appliquant ces distances au prix actuel
4. Met à jour entry avec le prix actuel

Cela préserve le R:R calculé par les agents, quel que soit le drift de prix.

### Fichier : `orchestrator/orchestrator.py`

### Emplacement

Trouver l'appel `place_order` dans `execute_trade` (vers la ligne ~2667). JUSTE AVANT cet appel (après le bloc RISK_CAP et le log `[TP_TRACE]`), ajouter le bloc de recalcul.

### Code à insérer

Chercher le log `[TP_TRACE]` (ajouté en R13) — il est juste avant `place_order`. APRÈS le `[TP_TRACE]` et AVANT l'appel `place_order`, insérer :

```python
                # ═══════════════════════════════════════════════════════════════
                # FIX 2026-03-18 R14: Recalcul SL/TP sur prix actuel
                # Les agents calculent SL/TP sur le prix au moment de l'analyse.
                # Entre l'analyse et l'exécution, le marché bouge.
                # On préserve les DISTANCES (risk/reward) mais on les applique
                # au prix ACTUEL pour maintenir le R:R correct.
                # ═══════════════════════════════════════════════════════════════
                try:
                    _current_price = None
                    try:
                        _tick = self._mt5_call("symbol_info_tick", broker_symbol)
                        if _tick:
                            _current_price = float(_tick.ask if action == "BUY" else _tick.bid)
                    except Exception:
                        pass

                    if _current_price is None:
                        try:
                            _current_price = float(self._mt5_call("get_last_price", broker_symbol))
                        except Exception:
                            pass

                    if _current_price and _current_price > 0 and entry and entry > 0:
                        _sl_dist = abs(entry - sl) if sl else 0
                        _tp_dist = abs(tp - entry) if tp else 0
                        _price_drift = abs(_current_price - entry)

                        # Seuil : ne recalculer que si le drift est significatif
                        # (> 10% de la distance SL, sinon pas la peine)
                        _drift_threshold = _sl_dist * 0.10 if _sl_dist > 0 else 0

                        if _price_drift > _drift_threshold and _sl_dist > 0 and _tp_dist > 0:
                            _old_entry = entry
                            _old_sl = sl
                            _old_tp = tp

                            entry = _current_price
                            if action == "BUY":
                                sl = _current_price - _sl_dist
                                tp = _current_price + _tp_dist
                            else:  # SELL
                                sl = _current_price + _sl_dist
                                tp = _current_price - _tp_dist

                            logger.warning(
                                f"[ENTRY_REFRESH] {symbol} {action}: prix drifté de "
                                f"{_price_drift:.2f} pts ({_price_drift/_sl_dist*100:.0f}% du SL). "
                                f"Entry {_old_entry:.5f}→{entry:.5f} | "
                                f"SL {_old_sl:.5f}→{sl:.5f} | "
                                f"TP {_old_tp:.5f}→{tp:.5f} | "
                                f"R:R préservé {_tp_dist/_sl_dist:.2f}"
                            )
                        elif _price_drift > 0:
                            logger.debug(
                                f"[ENTRY_REFRESH] {symbol}: drift {_price_drift:.2f} < seuil "
                                f"{_drift_threshold:.2f} — pas de recalcul"
                            )
                except Exception as _refresh_err:
                    logger.warning(f"[ENTRY_REFRESH] {symbol}: Erreur — {_refresh_err}")
```

### Points clés du fix :

1. **Préserve les distances** : `_sl_dist` et `_tp_dist` sont calculées depuis l'entry original, puis réappliquées au prix actuel
2. **Seuil de 10%** : ne recalcule que si le drift > 10% de la distance SL. Pour un SL de 90 pts, seuil = 9 pts. Évite de modifier inutilement pour de petits mouvements
3. **Log `[ENTRY_REFRESH]`** : trace chaque recalcul avec les valeurs avant/après et le R:R préservé
4. **Failsafe** : si le prix actuel ne peut pas être récupéré, l'ordre est envoyé avec les valeurs originales (pas de blocage)
5. **Direction-aware** : BUY → SL en-dessous, TP au-dessus. SELL → SL au-dessus, TP en-dessous.

### Vérification de cohérence directionnelle

Ajouter APRÈS le bloc ENTRY_REFRESH, une vérification finale :

```python
                # FIX R14: Vérification cohérence directionnelle post-refresh
                if entry and sl and tp:
                    if action == "BUY" and (sl >= entry or tp <= entry):
                        logger.error(
                            f"[DIR_CHECK] {symbol} BUY incohérent: "
                            f"sl={sl} >= entry={entry} ou tp={tp} <= entry={entry} — SKIP"
                        )
                        return None
                    if action == "SELL" and (sl <= entry or tp >= entry):
                        logger.error(
                            f"[DIR_CHECK] {symbol} SELL incohérent: "
                            f"sl={sl} <= entry={entry} ou tp={tp} >= entry={entry} — SKIP"
                        )
                        return None
```

Cela empêche les cas catastrophiques comme SP500#1 où le SL se retrouve du mauvais côté.

---

## FIX 2 — RISK_CAP : corriger point_val pour indices

### Problème

Le diagnostic montre `point_val=1.0 (défaut)` 5 fois pour SP500 et NAS100, malgré `sym_info=OK`. Le `trade_tick_size` ou `trade_tick_value` est 0 pour ces symboles chez ce broker.

### Solution

Ajouter un fallback qui utilise `trade_contract_size` et `profit_calc_mode` quand tick_size/tick_value sont à 0.

**Fichier** : `orchestrator/orchestrator.py`

Dans le bloc RISK_CAP, après le calcul de `_point_val` via tick_size/tick_value, ajouter un fallback :

Chercher (dans le bloc RISK_CAP, vers la ligne ~2638-2649) :

```python
                                if _ts > 0 and _tv > 0:
                                    _point_val = _tv / _ts
```

Ajouter APRÈS ce bloc `if _ts > 0 and _tv > 0:` (mais DANS le `if _sym_info:`) :

```python
                            # FIX R14: Fallback si tick_size/tick_value sont 0
                            if _point_val == 1.0 and _sym_info:
                                _cs = getattr(_sym_info, "trade_contract_size", 0)
                                _pt = getattr(_sym_info, "point", 0)
                                if _cs > 0 and _pt > 0:
                                    # Pour indices : 1 point de prix = contract_size * point
                                    _point_val = _cs * _pt
                                    logger.info(
                                        f"[RISK_CAP] {symbol}: point_val fallback via "
                                        f"contract_size={_cs} × point={_pt} = {_point_val}"
                                    )
```

---

## Résumé des 2 fixes

| Fix | Fichier | Criticité | Impact |
|-----|---------|-----------|--------|
| 1 | `orchestrator/orchestrator.py` | ⭐⭐⭐ CRITIQUE | SL/TP recalculés sur prix actuel → R:R préservé → +$600/jour estimé |
| 2 | `orchestrator/orchestrator.py` | IMPORTANT | RISK_CAP correct pour indices (SP500, NAS100) |

## Vérification

```bash
python -m py_compile orchestrator/orchestrator.py
```

## Vérification en production

### Test immédiat (premier trade) :

1. **[ENTRY_REFRESH]** dans les logs :
   - `prix drifté de X pts (Y% du SL). Entry A→B | SL C→D | TP E→F | R:R préservé Z`
   - Le R:R préservé doit être identique au R:R original (calculé par les agents)
   - Le drift en % du SL indique la magnitude du problème

2. **[DIR_CHECK]** : si présent → une incohérence directionnelle a été bloquée (cas SP500#1)

3. **[RISK_CAP] point_val fallback** : si présent pour SP500/NAS100 → le fallback contract_size fonctionne

### Test après 4-8h de trading :

4. **Comparer les TP** : les TP devraient maintenant être éloignés du fill (R:R réel > 1.0)

5. **P&L** : les TP wins devraient rapporter ~$125 en moyenne (au lieu de ~$49)
   - Si P&L jour > +$200 avec un hit rate similaire → fix confirmé
   - Si les TP sont encore proches du fill → vérifier que `[ENTRY_REFRESH]` se déclenche

6. **SP500/NAS100** : vérifier que `point_val` n'est plus 1.0 (chercher `[RISK_CAP]` fallback)

## RÈGLES

1. **Le FIX 1 est la priorité absolue.** C'est LE fix qui transforme le P&L.
2. **Place le code ENTRY_REFRESH entre le log [TP_TRACE] et l'appel place_order.** L'ordre est important : TP_TRACE logge les valeurs AVANT recalcul, ENTRY_REFRESH recalcule, puis place_order envoie les valeurs corrigées.
3. **Place la vérification DIR_CHECK après ENTRY_REFRESH et avant place_order.**
4. **Compile le fichier.**
5. **Ne touche PAS à `_respect_min_stops`** — il fonctionne correctement.
