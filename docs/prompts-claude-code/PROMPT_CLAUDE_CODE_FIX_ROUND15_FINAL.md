# PROMPT CLAUDE CODE — Fix Round 15 (Qualité Signal + RISK_CAP + HARD_FILTER)

## Contexte

Après 14 rounds de corrections (R3-R14), le bot est techniquement stable :
- ✅ ENTRY_REFRESH R14 : R:R préservé 100%, avg $/win = $124 (+153% vs $49 pré-R14)
- ✅ Outcome tracker R12 : 56 clôtures enregistrées
- ✅ HARD_FILTER R13 : 40.8% de rejet (dans la cible 40-70%)
- ✅ Kill switch, COM locks, DIR_CHECK — tout fonctionne
- ✅ Bug `regime_label` → `_regime_label` (ligne 5080) déjà corrigé

**Diagnostic du 23 mars 2026 — Problèmes identifiés :**

1. **Hit rate catastrophique : 22%** (2 wins / 9 trades) — le bot se trompe de direction
2. **3 QUICK_REVERSALS** : trades SL en < 7 min = -$627 (68% des pertes du jour)
   - AUDUSD BUY : SL en 7 min → -$297.60
   - SP500 BUY : SL en 5 min → -$30.41
   - LTCUSD SELL : SL en 3 min → -$298.68
3. **RISK_CAP indices cassé** : `point_val = contract_size × point = 1.0 × 0.01 = 0.01` pour SP500/NAS100 → sous-estime le risque réel d'un facteur ~100×. Aucun cap de risque sur les indices.
4. **HARD_FILTER opérateur `<` strict** : les scores pile à 3.8 sont rejetés (devrait être `<=` pour accepter)
5. **Finnhub API 403** : clé API expirée, calendrier économique inactif (non bloquant, info seulement)

**5 fixes à appliquer, par ordre de priorité :**

---

## FIX 1 — Filtre Momentum Pré-Exécution ⭐⭐⭐ CRITIQUE

### Principe

Avant d'exécuter un trade, vérifier que le prix se déplace dans la même direction que le signal dans les **dernières 5-15 minutes** (3 bougies M5). Si le prix va clairement dans la direction OPPOSÉE, skip le trade.

Ce filtre aurait bloqué les 3 QUICK_REVERSALS du 23 mars (-$627 économisés) et 3 des 5 SL du 20 mars.

### Emplacement

**Fichier** : `orchestrator/orchestrator.py`

Dans `execute_trade`, AVANT le bloc ENTRY_REFRESH (R14) et APRÈS le log [TP_TRACE]. L'ordre final sera :
1. [TP_TRACE] — log les valeurs
2. **[MOMENTUM_CHECK]** — vérifie le momentum (NOUVEAU R15)
3. [ENTRY_REFRESH] — recalcule SL/TP
4. [DIR_CHECK] — vérifie la cohérence
5. place_order — envoie l'ordre

### Code à insérer

Chercher le log `[TP_TRACE]` (R13, vers la ligne ~2691). APRÈS le [TP_TRACE] et AVANT le bloc ENTRY_REFRESH (R14), insérer :

```python
                # ═══════════════════════════════════════════════════════════════
                # FIX 2026-03-23 R15: Filtre Momentum Pré-Exécution
                # Vérifie que le prix se déplace dans la direction du signal
                # sur les dernières 3 bougies M5. Bloque si momentum inverse.
                # ═══════════════════════════════════════════════════════════════
                try:
                    _momentum_ok = True
                    _momentum_bars = 3  # 3 bougies M5 = 15 minutes
                    _momentum_threshold = 0.6  # 60% des bougies doivent confirmer

                    _m5_rates = self._mt5_call("copy_rates_from_pos", broker_symbol, 5, 0, _momentum_bars + 1)
                    # Timeframe 5 = M5 dans l'enum MT5

                    if _m5_rates is not None and len(_m5_rates) >= _momentum_bars + 1:
                        _closes = [float(r[4]) for r in _m5_rates]  # index 4 = close
                        _confirms = 0

                        for i in range(1, len(_closes)):
                            if action == "BUY" and _closes[i] > _closes[i - 1]:
                                _confirms += 1
                            elif action == "SELL" and _closes[i] < _closes[i - 1]:
                                _confirms += 1

                        _confirm_ratio = _confirms / _momentum_bars if _momentum_bars > 0 else 0

                        if _confirm_ratio < _momentum_threshold:
                            # Vérifier aussi la direction globale (close[-1] vs close[0])
                            _net_move = _closes[-1] - _closes[0]
                            _against = (action == "BUY" and _net_move < 0) or \
                                       (action == "SELL" and _net_move > 0)

                            if _against:
                                logger.warning(
                                    f"[MOMENTUM_CHECK] {symbol} {action}: momentum INVERSE "
                                    f"({_confirm_ratio*100:.0f}% confirm, net={_net_move:.5f}). "
                                    f"Trade BLOQUÉ — prix va dans la mauvaise direction."
                                )
                                _momentum_ok = False
                            else:
                                logger.info(
                                    f"[MOMENTUM_CHECK] {symbol} {action}: momentum faible "
                                    f"({_confirm_ratio*100:.0f}% confirm) mais net neutre — PASS"
                                )
                        else:
                            logger.debug(
                                f"[MOMENTUM_CHECK] {symbol} {action}: momentum OK "
                                f"({_confirm_ratio*100:.0f}% confirm)"
                            )
                    else:
                        logger.debug(f"[MOMENTUM_CHECK] {symbol}: données M5 indisponibles — PASS")

                    if not _momentum_ok:
                        return None

                except Exception as _mom_err:
                    logger.debug(f"[MOMENTUM_CHECK] {symbol}: Erreur — {_mom_err}")
                    # En cas d'erreur, laisser passer (fail-open)
```

### Note sur `copy_rates_from_pos`

L'appel `self._mt5_call("copy_rates_from_pos", broker_symbol, 5, 0, 4)` récupère les 4 dernières bougies M5. Le timeframe `5` correspond à `mt5.TIMEFRAME_M5`. Si cette méthode n'existe pas dans la couche d'abstraction MT5 du bot, utiliser l'équivalent disponible (chercher `copy_rates`, `get_rates`, `_get_candles` dans le code).

**Alternative si `copy_rates_from_pos` n'est pas exposé** : utiliser la méthode qui récupère les bougies pour les agents. Chercher comment les agents obtiennent leurs données M5 (probablement via `_get_rates` ou `_fetch_candles` dans l'orchestrateur ou un helper).

**Si aucune méthode n'est disponible**, utiliser directement MT5 avec le lock :
```python
import MetaTrader5 as mt5
_m5_rates = mt5.copy_rates_from_pos(broker_symbol, mt5.TIMEFRAME_M5, 0, 4)
```
(avec le lock MT5 approprié via `_mt5_call_safe` ou `async with _GLOBAL_MT5_SEMAPHORE`)

---

## FIX 2 — RISK_CAP indices : point_val hardcodé ⭐⭐ IMPORTANT

### Problème

Pour SP500 et NAS100, `trade_tick_size` et `trade_tick_value` retournent 0 dans MT5, donc le code utilise le fallback `contract_size × point`. Mais :
- SP500 : `contract_size=1.0 × point=0.01 = 0.01` → **100× trop bas**
- NAS100 : idem

Le résultat : le RISK_CAP ne se déclenche JAMAIS pour les indices car le risque calculé est ~$0.46 au lieu de ~$46 pour 1 lot.

### Solution

**Fichier** : `orchestrator/orchestrator.py`, dans le bloc RISK_CAP (vers ligne ~2638-2684).

APRÈS le fallback `contract_size × point` (ligne ~2653) et AVANT le test `if _point_val == 1.0` (ligne ~2662), ajouter un **override hardcodé** pour les indices connus :

```python
                            # FIX 2026-03-23 R15: Override point_val pour indices CFD
                            # contract_size × point donne 0.01 pour SP500/NAS100
                            # mais le risque réel est ~$1/pt/lot (vérifié empiriquement :
                            # SP500 SL -$45.85 pour ~46 pts, 1 lot → $1/pt)
                            _indices_point_val = {
                                "SP500": 1.0,
                                "SP500#1": 1.0,
                                "NAS100": 1.0,
                                "NAS100#1": 1.0,
                            }
                            _sym_upper = symbol.upper().replace("#", "#")
                            if _sym_upper in _indices_point_val:
                                _point_val = _indices_point_val[_sym_upper]
                                logger.info(
                                    f"[RISK_CAP] {symbol}: point_val override indices = {_point_val} "
                                    f"(fallback contract_size×point était {_cs * _pt})"
                                )
```

Le code final dans le bloc RISK_CAP doit être (ordre) :
1. Essayer `trade_tick_value / trade_tick_size`
2. Si `_point_val == 1.0` → fallback `contract_size × point`
3. **NOUVEAU** : Si le symbole est un indice connu → override hardcodé
4. Si `_point_val == 1.0` → alerte + forçage cap

### Alternative plus propre

Si tu préfères, ajouter la config dans `config/config.yaml` sous `risk:` :
```yaml
risk:
  point_val_overrides:
    SP500: 1.0
    NAS100: 1.0
```
Et lire cette config dans le bloc RISK_CAP. Mais le hardcodé est plus simple et immédiat.

---

## FIX 3 — Anti-QUICK_REVERSAL (cooldown symbole) ⭐ IMPORTANT

### Problème

3 trades ont touché le SL en moins de 7 minutes le 23 mars, coûtant $627 (68% des pertes). Quand un trade se fait stopper très vite, c'est souvent un signe que le momentum local est contre nous. Réenvoyer un trade sur le même symbole immédiatement est suicidaire.

### Solution

Après chaque SL détecté en < 10 minutes, appliquer un cooldown de 30 minutes sur ce symbole.

**Fichier** : `orchestrator/orchestrator.py`

### 3a — Stocker le cooldown

Au début de `__init__` (ou près des autres dictionnaires de tracking), ajouter :
```python
        self._symbol_cooldown: Dict[str, float] = {}  # {symbol: timestamp_fin_cooldown}
```

### 3b — Déclencher le cooldown dans l'outcome tracker

Chercher le bloc `[OUTCOME] Trade cloture` (R12). Quand un trade est détecté comme SL avec une durée < 10 minutes, ajouter :

```python
                    # FIX 2026-03-23 R15: Cooldown anti-QUICK_REVERSAL
                    if exit_type == "SL" and duration_min < 10:
                        import time as _time_mod
                        _cooldown_minutes = 30
                        self._symbol_cooldown[symbol] = _time_mod.time() + (_cooldown_minutes * 60)
                        logger.warning(
                            f"[QUICK_REVERSAL] {symbol}: SL en {duration_min:.0f} min → "
                            f"cooldown {_cooldown_minutes} min activé"
                        )
```

### 3c — Vérifier le cooldown avant d'exécuter

Dans `execute_trade`, AVANT le [TP_TRACE] (donc tout au début de la logique d'exécution), ajouter :

```python
                # FIX 2026-03-23 R15: Vérification cooldown anti-QUICK_REVERSAL
                import time as _time_mod
                _cooldown_until = self._symbol_cooldown.get(symbol, 0)
                if _time_mod.time() < _cooldown_until:
                    _remaining = int((_cooldown_until - _time_mod.time()) / 60)
                    logger.warning(
                        f"[COOLDOWN] {symbol}: trade bloqué — cooldown QUICK_REVERSAL "
                        f"encore {_remaining} min"
                    )
                    return None
```

**Adapter les variables** : `exit_type`, `duration_min`, et `symbol` selon les noms réels dans le code de l'outcome tracker. Chercher le bloc existant `[OUTCOME]` pour voir comment ces valeurs sont calculées.

---

## FIX 4 — HARD_FILTER : opérateur `<` → `<=` (mineur)

### Problème

Ligne ~2129 de `orchestrator.py` :
```python
if score_agr < HARD_MIN_SCORE:
```
Un score de exactement 3.8 est rejeté car `3.8 < 3.8` est False... MAIS dans le diagnostic on a vu `score 3.8 < 3.8 → REJET`, ce qui signifie qu'il y a probablement un arrondi float.

### Solution

Pas de changement de l'opérateur (< est correct pour rejeter tout ce qui est EN DESSOUS du seuil). Le problème est probablement un arrondi float (3.7999... affiché comme 3.8).

**Action** : améliorer le log pour afficher plus de décimales et confirmer :
```python
        logger.warning(f"[HARD_FILTER] {symbol}: score {score_agr:.4f} < {HARD_MIN_SCORE} → REJET")
```
Changer `.1f` en `.4f` dans le log HARD_FILTER (ligne ~2130) pour voir les décimales réelles.

---

## FIX 5 — Diagnostic signal enrichi [SIGNAL_DIAG] (logging)

### Principe

Le [SCORE_DIAG] existant (ligne ~5078-5083, méthode `_compute_aggregate_direction`) fonctionne déjà. **Note : le bug `regime_label` → `_regime_label` à la ligne 5080 a déjà été corrigé.**

Compléter le log existant pour inclure les signaux par agent individuellement. Le log actuel affiche déjà `agents=[...]` et `globals=[...]`, ce qui est suffisant. Pas de modification nécessaire sauf si le format est insuffisant.

**Action optionnelle** : ajouter un log dans `_run_agents_and_decide` APRÈS l'appel à `_compute_aggregate_direction` (vers la ligne ~3463) pour loguer le résultat final de la décision avec le régime :

```python
        # FIX 2026-03-23 R15: Log décision finale
        logger.info(
            f"[DECISION] {symbol}: {direction or 'NEUTRAL'} score={score_agr:.2f} "
            f"conf={confluence} regime={regime_label}"
        )
```

---

## Résumé des 5 fixes

| # | Fix | Fichier(s) | Criticité | Impact estimé |
|---|-----|-----------|-----------|---------------|
| 1 | Filtre Momentum Pré-Exécution | `orchestrator/orchestrator.py` | ⭐⭐⭐ CRITIQUE | Bloque trades contre le flux → -$627 économisés le 23 mars |
| 2 | RISK_CAP indices point_val | `orchestrator/orchestrator.py` | ⭐⭐ IMPORTANT | Cap risque effectif sur SP500/NAS100 (actuellement 0) |
| 3 | Anti-QUICK_REVERSAL cooldown | `orchestrator/orchestrator.py` | ⭐⭐ IMPORTANT | Cooldown 30 min après SL < 10 min |
| 4 | HARD_FILTER log décimales | `orchestrator/orchestrator.py` | MINEUR | Diagnostic arrondi float |
| 5 | SIGNAL_DIAG logging | `orchestrator/orchestrator.py` | DIAGNOSTIC | Tracer les décisions pour analyse future |

## Vérification

```bash
python -m py_compile orchestrator/orchestrator.py
```

## Vérification en production

### Test immédiat (premiers trades) :

1. **[MOMENTUM_CHECK]** dans les logs :
   - `momentum OK (X% confirm)` → trade autorisé
   - `momentum INVERSE ... Trade BLOQUÉ` → trade filtré
   - Compter : combien bloqués vs autorisés ?

2. **[RISK_CAP]** pour SP500/NAS100 :
   - `point_val override indices = 1.0` → fix actif
   - `risque $X > max $300 → lots réduits` → cap effectif

3. **[COOLDOWN]** après un SL rapide :
   - `trade bloqué — cooldown QUICK_REVERSAL encore X min` → protection active

### Test après une journée :

4. **Hit rate** : comparer avec le 23 mars (22%)
   - Cible R15 : > 35% (éliminer les QUICK_REVERSALS)

5. **Trades bloqués par momentum** : si > 50% des trades sont bloqués, baisser `_momentum_threshold` de 0.6 à 0.4

6. **RISK_CAP indices** : vérifier que SP500/NAS100 sont maintenant capés à $300 max

## RÈGLES

1. **Le FIX 1 (momentum) est la PRIORITÉ ABSOLUE.** C'est le seul qui bloque activement les mauvais trades.
2. **Le FIX 2 (RISK_CAP indices) est le second.** C'est un risque latent qui pourrait causer une grosse perte.
3. **Adapter les appels MT5** pour récupérer les bougies M5. Chercher comment les agents récupèrent leurs données et utiliser la même méthode.
4. **Ne casse pas les méthodes existantes.** Chaque fix doit être un ajout, pas une modification du pipeline existant.
5. **Compile le fichier** après tous les changements.
6. **Le bug `regime_label` ligne 5080 est DÉJÀ corrigé** (remplacé par `_regime_label`). Ne pas le re-modifier.
7. **Le `counter_trend_min_score` est déjà à 6.0 dans config.yaml** (ligne 308). Pas de changement nécessaire.
