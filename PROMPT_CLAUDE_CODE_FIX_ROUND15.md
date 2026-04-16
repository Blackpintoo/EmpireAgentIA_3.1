# PROMPT CLAUDE CODE — Fix Qualité de Signal (Round 15)

## Contexte

Après 12 rounds de corrections d'infrastructure (R3-R14), le bot est techniquement stable :
- ✅ ENTRY_REFRESH R14 : R:R préservé, avg $/win doublé ($49→$96)
- ✅ Outcome tracker R12 : 45 clôtures enregistrées
- ✅ HARD_FILTER R13 : 58.6% de rejet (dans la cible)
- ✅ Kill switch, COM locks, PM — tout fonctionne

Le **nouveau problème #1** est la qualité des signaux : 0% hit rate le 20 mars (5 SL + 1 BE, tous dans la mauvaise direction). Le bot a un edge technique (R:R préservé) mais pas d'edge directionnel (les agents se trompent trop souvent).

### Analyse des 45 trades (trade_outcomes.csv, 15-20 mars) :

- **TP wins** : 19 (hit rate ~42%)
- **SL loss** : 14
- **BE** : 9
- **Trailing** : 1
- P&L moyen par TP win (pré-R14) : ~$49
- P&L moyen par TP win (post-R14) : ~$96

Le hit rate de 42% avec un R:R de 1.67 est théoriquement profitable (seuil de rentabilité = 37%). Mais les jours de 0% hit rate (20 mars : 5 SL en 2h) causent des pertes concentrées qui déclenchent le kill switch avant que les bonnes journées ne compensent.

### Causes racines identifiées :

1. **Aucun filtre momentum pré-exécution** — Le bot exécute des signaux même quand le prix se déplace CONTRE la direction du signal dans les minutes précédant l'ordre
2. **Counter-trend threshold irréaliste** — Score >= 10.0 requis pour trader contre le régime, mais le score max atteignable est ~5-6. Résultat : 0% de trades counter-trend → quand le trend reverse, le bot est coincé
3. **Regime lag** — Détection sur H1 (150 bars) = 150h de lookback. Sur les cryptos et indices rapides, le régime change bien plus vite

**3 fixes conservateurs, testables :**

---

## FIX 1 — Filtre Momentum Pré-Exécution ⭐⭐ CRITIQUE

### Principe

Avant d'exécuter un trade, vérifier que le prix se déplace dans la même direction que le signal dans les **dernières 5-15 minutes** (3 bougies M5). Si le prix va clairement dans la direction OPPOSÉE, skip le trade.

Ce filtre aurait bloqué au moins 3 des 5 SL du 20 mars :
- BTCUSD SHORT alors que BTC montait de 3641 pts
- XAUUSD LONG alors que XAUUSD descendait (retournement baissier)
- SOLUSD LONG alors que SOLUSD descendait (retournement)

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
                # FIX 2026-03-20 R15: Filtre Momentum Pré-Exécution
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

### Points clés

1. **3 bougies M5** = 15 minutes de momentum. Suffisant pour détecter un retournement immédiat
2. **Seuil 60%** = 2 bougies sur 3 doivent confirmer. Si le prix zigzague (1/3 confirm), on vérifie le net move
3. **Double vérification** : ratio de bougies + direction nette. Les deux doivent être CONTRE pour bloquer
4. **Fail-open** : en cas d'erreur de données, le trade passe (pas de blocage par défaut)
5. **Log [MOMENTUM_CHECK]** pour tracer chaque décision

### Note sur `copy_rates_from_pos`

L'appel `self._mt5_call("copy_rates_from_pos", broker_symbol, 5, 0, 4)` récupère les 4 dernières bougies M5. Le timeframe `5` correspond à `mt5.TIMEFRAME_M5`. Si cette méthode n'existe pas dans la couche d'abstraction MT5 du bot, utiliser l'équivalent disponible (chercher `copy_rates`, `get_rates`, `_get_candles` dans le code).

**Alternative si `copy_rates_from_pos` n'est pas exposé** : utiliser la méthode qui récupère les bougies pour les agents. Chercher comment les agents obtiennent leurs données M5 (probablement via `_get_rates` ou `_fetch_candles` dans l'orchestrateur ou un helper).

---

## FIX 2 — Assouplir le seuil counter-trend ⭐ IMPORTANT

### Problème

La condition counter-trend dans `_run_agents_and_decide` (vers les lignes ~3783-3796) exige un score >= 10.0 pour trader contre le régime. Mais le score maximum atteignable est ~5-6 (5 agents × poids). Résultat : **aucun trade counter-trend n'est jamais autorisé**. Quand le trend reverse, le bot continue à trader dans l'ancienne direction.

### Solution

Baisser le seuil de 10.0 à **6.0** (atteignable avec forte confluence).

**Fichier** : `orchestrator/orchestrator.py`

Chercher dans `_run_agents_and_decide`, le bloc qui vérifie le counter-trend (vers la ligne ~3783-3796). Il devrait ressembler à :

```python
if regime_confidence > 0.4:
    if (regime_type == "trending_down" and direction == "LONG") or \
       (regime_type == "trending_up" and direction == "SHORT"):
        if score_agr < 10.0:
```

Remplacer `10.0` par `6.0` :

```python
        if score_agr < 6.0:  # FIX R15: 10.0→6.0 (10.0 inatteignable, bloquait 100% counter-trend)
```

**Aussi**, chercher `counter_trend_min_score` dans `config/config.yaml` (section `hard_filters`, vers la ligne ~309) :

```yaml
    counter_trend_min_score: 6.0
```

Remplacer par `6.0` s'il est encore à une autre valeur.

**Note** : ce seuil signifie qu'un trade counter-trend doit avoir une très forte confluence (4+ agents alignés). C'est encore conservateur, mais au moins c'est atteignable.

---

## FIX 3 — Diagnostic qualité de signal (logging enrichi)

### Principe

Ajouter un log à chaque décision d'agent pour comprendre POURQUOI les signaux sont mauvais.

### Fichier : `orchestrator/orchestrator.py`

Dans `_run_agents_and_decide`, après le calcul du direction final et du score (vers la ligne ~4837-4840, après `direction = "LONG" if score_long > score_short else ...`), ajouter ou compléter le log [SCORE_DIAG] existant :

Chercher le `[SCORE_DIAG]` existant (ajouté en R9). Le remplacer ou compléter par :

```python
        # FIX 2026-03-20 R15: Diagnostic signal enrichi
        logger.info(
            f"[SIGNAL_DIAG] {symbol} tf={timeframe}: "
            f"LONG={score_long:.2f} SHORT={score_short:.2f} → {direction or 'NEUTRAL'} "
            f"score={score_agr:.2f} conf={confluence} "
            f"regime={getattr(self, '_last_regime_type', 'unknown')} "
            f"agents=[{', '.join(f'{k}:{v}' for k, v in per_tf_signals.get(timeframe, {}).items() if v)}]"
        )
```

**Note** : adapter le code selon les variables accessibles. L'objectif est de logger :
- Les scores LONG/SHORT
- Le régime détecté
- Les signaux individuels de chaque agent
- La confluence

Cela permettra d'analyser après quelques jours QUELS agents se trompent et dans quelles conditions.

---

## Résumé des 3 fixes

| Fix | Fichier(s) | Criticité | Impact |
|-----|-----------|-----------|--------|
| 1 | `orchestrator/orchestrator.py` | ⭐⭐ CRITIQUE | Filtre momentum → bloque trades contre le flux immédiat |
| 2 | `orchestrator/orchestrator.py` + `config/config.yaml` | ⭐ IMPORTANT | Counter-trend 10→6 → permet les reversals |
| 3 | `orchestrator/orchestrator.py` | DIAGNOSTIC | Logging agent-level pour analyse future |

## Vérification

```bash
python -m py_compile orchestrator/orchestrator.py
```

## Vérification en production

### Test immédiat (premiers trades) :

1. **[MOMENTUM_CHECK]** dans les logs :
   - `momentum OK (X% confirm)` → trade autorisé
   - `momentum INVERSE ... Trade BLOQUÉ` → trade filtré par momentum
   - Compter : combien de trades bloqués vs autorisés ?

2. **[SIGNAL_DIAG]** dans les logs :
   - Quels agents signalent LONG vs SHORT ?
   - Le régime correspond-il à la réalité du marché ?

### Test après une journée :

3. **Hit rate** : comparer avec les jours précédents
   - 16 mars : 50% | 17 mars : 55% | 18 mars : 62% | 19 mars : 50% | 20 mars : 0%
   - Cible R15 : > 40% constant (éliminer les jours à 0%)

4. **Trades bloqués par momentum** : si > 50% des trades sont bloqués, baisser le seuil de confirmation de 60% à 40%.

5. **Counter-trend trades** : chercher des trades où la direction est CONTRE le régime. Est-ce que le seuil 6.0 laisse passer certains ?

## RÈGLES

1. **Le FIX 1 (momentum) est la priorité.** C'est le seul qui bloque activement les mauvais trades.
2. **Adapter l'appel MT5 pour récupérer les bougies M5.** Chercher comment les agents récupèrent leurs données et utiliser la même méthode.
3. **Ne casse pas les méthodes existantes.** Le filtre momentum doit être un ajout, pas une modification du pipeline existant.
4. **Compile le fichier.**
5. **Si `copy_rates_from_pos` n'est pas exposé**, utiliser cette alternative dans _mt5_call :
   ```python
   import MetaTrader5 as mt5
   _m5_rates = mt5.copy_rates_from_pos(broker_symbol, mt5.TIMEFRAME_M5, 0, 4)
   ```
   (avec le lock MT5 approprié via `_mt5_call_safe` ou `async with _GLOBAL_MT5_SEMAPHORE`)
