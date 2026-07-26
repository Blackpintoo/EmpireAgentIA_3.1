# PROMPT CLAUDE CODE — ROUND 17 : OPTIMISATION AVANCÉE (7 améliorations)

## CONTEXTE
Le bot est fonctionnel et à l'équilibre (PF 1.02, +$52 sur 5 jours). Les 3 meilleurs symboles
(XAUUSD +$1338, NAS100 +$435, SP500 +$149) rapportent +$1922, mais 5 symboles perdants
annulent les gains. **Au lieu de désactiver les perdants, on va les rendre plus intelligents.**

**Problème structurel majeur** : SHORT = 20.7% hit rate vs LONG = 58.3% HR.

---

## AMÉLIORATION 1 : SHORT PENALTY — Pénalité directionnelle asymétrique
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : Le SHORT a 20.7% HR vs 58.3% LONG. C'est LE problème #1.

### Instructions :
1. Dans `config/config.yaml`, ajouter sous `orchestrator.hard_filters:` :
```yaml
    # R17: Pénalité SHORT — les SHORT requièrent un score plus élevé
    short_score_penalty: 1.5          # Score additionnel requis pour SHORT vs LONG
    short_momentum_bars: 5            # Bougies M5 requises pour SHORT (vs 3 pour LONG)
    short_momentum_threshold: 0.7     # Confirmation plus stricte pour SHORT (vs 0.6)
```

2. Dans `orchestrator.py`, dans la méthode `execute_trade()`, **APRÈS le bloc HARD_FILTER score** (après la ligne `logger.info(f"[HARD_FILTER] {symbol}: PASS score=..."`), ajouter :
```python
        # ══════════════════════════════════════════════════════════════════════
        # FIX 2026-04-03 R17: SHORT PENALTY — Score plus élevé requis pour SHORT
        # Données: SHORT 20.7% HR vs LONG 58.3% HR → asymétrie structurelle
        # ══════════════════════════════════════════════════════════════════════
        _short_penalty = float(
            (self.cfg.get("orchestrator", {}).get("hard_filters", {})
             .get("short_score_penalty", 1.5))
        )
        if sig == "SHORT" and _short_penalty > 0:
            _short_min = HARD_MIN_SCORE + _short_penalty
            if score_agr < _short_min:
                logger.warning(
                    f"[SHORT_PENALTY] {symbol}: score {score_agr:.4f} < "
                    f"{_short_min:.1f} (base {HARD_MIN_SCORE} + penalty {_short_penalty}) → REJET SHORT"
                )
                self._send_telegram(
                    f"⬇️ [SHORT_PENALTY] {symbol}: score {score_agr:.1f} trop faible pour SHORT "
                    f"(min={_short_min:.1f}) → rejet",
                    kind="status", force=True
                )
                return False
            logger.info(f"[SHORT_PENALTY] {symbol}: score {score_agr:.1f} >= {_short_min:.1f} → SHORT autorisé")
        # ══════════════════════════════════════════════════════════════════════
```

3. Dans le bloc MOMENTUM_CHECK (vers ligne 2755), rendre les paramètres asymétriques :
   - Chercher `_momentum_bars = 3` et `_momentum_threshold = 0.6`
   - Remplacer par :
```python
            # R17: Paramètres momentum asymétriques (SHORT plus strict)
            _hf_cfg = self.cfg.get("orchestrator", {}).get("hard_filters", {})
            if action == "SELL":
                _momentum_bars = int(_hf_cfg.get("short_momentum_bars", 5))
                _momentum_threshold = float(_hf_cfg.get("short_momentum_threshold", 0.7))
            else:
                _momentum_bars = 3
                _momentum_threshold = 0.6
```

---

## AMÉLIORATION 2 : ADAPTIVE MIN_SCORE — Seuil dynamique par symbole
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : Au lieu d'un seuil fixe, le score minimum s'ajuste automatiquement selon la performance récente du symbole. Un symbole perdant voit son seuil monter.

### Instructions :
1. Dans `config/config.yaml`, ajouter sous `orchestrator.hard_filters:` :
```yaml
    # R17: Adaptive min_score — ajustement dynamique par win rate
    adaptive_score:
      enabled: true
      lookback_trades: 15             # Nombre de trades récents à analyser
      hr_threshold_boost_medium: 0.30 # Si HR < 30% → boost moyen
      hr_threshold_boost_hard: 0.15   # Si HR < 15% → boost fort
      score_boost_medium: 1.5         # Ajout au min_score si HR < 30%
      score_boost_hard: 3.0           # Ajout au min_score si HR < 15%
```

2. Ajouter une méthode dans la classe `SymbolOrchestrator` (avant `execute_trade`) :
```python
    def _get_adaptive_score_boost(self) -> float:
        """R17: Calcule un boost de min_score basé sur le win rate récent du symbole."""
        try:
            adaptive_cfg = (self.cfg.get("orchestrator", {})
                           .get("hard_filters", {})
                           .get("adaptive_score", {}))
            if not adaptive_cfg.get("enabled", False):
                return 0.0

            # Lire les outcomes récents depuis trade_outcomes.csv
            outcomes_path = pathlib.Path("data/trade_outcomes.csv")
            if not outcomes_path.exists():
                return 0.0

            lookback = int(adaptive_cfg.get("lookback_trades", 15))
            symbol_trades = []
            with open(outcomes_path, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("symbol", "").upper() == self.symbol.upper():
                        symbol_trades.append(row)

            # Garder les N derniers
            recent = symbol_trades[-lookback:] if len(symbol_trades) >= 5 else []
            if len(recent) < 5:
                return 0.0  # Pas assez de données

            wins = sum(1 for t in recent if float(t.get("pnl", 0)) > 0)
            hr = wins / len(recent)

            hr_hard = float(adaptive_cfg.get("hr_threshold_boost_hard", 0.15))
            hr_medium = float(adaptive_cfg.get("hr_threshold_boost_medium", 0.30))
            boost_hard = float(adaptive_cfg.get("score_boost_hard", 3.0))
            boost_medium = float(adaptive_cfg.get("score_boost_medium", 1.5))

            if hr < hr_hard:
                logger.info(
                    f"[ADAPTIVE_SCORE] {self.symbol}: HR={hr:.0%} ({wins}/{len(recent)}) "
                    f"< {hr_hard:.0%} → boost +{boost_hard}"
                )
                return boost_hard
            elif hr < hr_medium:
                logger.info(
                    f"[ADAPTIVE_SCORE] {self.symbol}: HR={hr:.0%} ({wins}/{len(recent)}) "
                    f"< {hr_medium:.0%} → boost +{boost_medium}"
                )
                return boost_medium
            else:
                logger.debug(
                    f"[ADAPTIVE_SCORE] {self.symbol}: HR={hr:.0%} ({wins}/{len(recent)}) → pas de boost"
                )
                return 0.0
        except Exception as e:
            logger.debug(f"[ADAPTIVE_SCORE] {self.symbol}: erreur — {e}")
            return 0.0
```

3. Dans `execute_trade()`, **JUSTE AVANT** le bloc HARD_FILTER score (avant `HARD_MIN_SCORE = self._hf_min_score`), ajouter :
```python
        # R17: Adaptive score boost
        _adaptive_boost = self._get_adaptive_score_boost()
```

4. Modifier la ligne `HARD_MIN_SCORE = self._hf_min_score` en :
```python
        HARD_MIN_SCORE = self._hf_min_score + _adaptive_boost
        if _adaptive_boost > 0:
            logger.info(f"[ADAPTIVE_SCORE] {symbol}: min_score ajusté {self._hf_min_score} + {_adaptive_boost} = {HARD_MIN_SCORE}")
```

---

## AMÉLIORATION 3 : LONG ONLY pour cryptos perdantes + AUDUSD/USDJPY restrictions
**Fichier** : `config/overrides.yaml`
**Pourquoi** : BTCUSD et SOLUSD ont un SHORT catastrophique. AUDUSD et USDJPY perdent sur tous les fronts mais on leur donne une dernière chance avec des restrictions sévères.

### Instructions dans `overrides.yaml` :

1. **BTCUSD** — ajouter après `telegram_validation: false` :
```yaml
    # R17: LONG only — SHORT catastrophique sur 5 jours
    allowed_directions: ["LONG"]
```

2. **SOLUSD** — ajouter dans le bloc `orchestrator:` :
```yaml
    # R17: LONG only — SHORT catastrophique sur 5 jours
    allowed_directions: ["LONG"]
    min_score_for_proposal: 4.0       # R17: Seuil relevé (était default 2.5)
```

3. **AUDUSD** — modifier le bloc existant :
```yaml
    # R17: Dernière chance — restrictions sévères
    allowed_directions: ["LONG"]      # R17: LONG only (SHORT = 0% HR)
    min_score_for_proposal: 5.0       # R17: seuil très élevé
    max_trades_per_day: 2             # déjà en place
    # R17: Changer les prime_hours — session Asie perd de l'argent
    prime_hours_utc:
      - {start: 7, end: 17}          # R17: London+NY au lieu de Asie
```

4. **USDJPY** — modifier le bloc existant :
```yaml
    # R17: Dernière chance — restrictions sévères
    allowed_directions: ["LONG"]      # R17: LONG only
    min_score_for_proposal: 5.0       # R17: seuil très élevé
    # R17: Restreindre aux heures Tokyo+London uniquement
    allowed_hours_utc: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
```

5. **BNBUSD** — laisser tel quel (déjà SHORT only avec min_score 5.0). Le système ADAPTIVE_SCORE va automatiquement durcir le seuil vu son 9% HR.

---

## AMÉLIORATION 4 : DIRECTION REVERSAL COOLDOWN — Anti-whipsaw
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : Après un SL en LONG, prendre immédiatement un SHORT (ou vice versa) = whipsaw. On ajoute un cooldown spécifique quand le signal inverse après une perte.

### Instructions :
1. Dans `config/config.yaml`, ajouter sous `orchestrator.cooldown:` :
```yaml
    # R17: Cooldown direction reversal — anti-whipsaw
    reversal_cooldown_min: 60         # 1h de cooldown si signal inverse après perte
```

2. Dans `orchestrator.py`, dans `execute_trade()`, **APRÈS le bloc anti-QUICK_REVERSAL** (après `return False` du QR cooldown), ajouter :
```python
        # ══════════════════════════════════════════════════════════════════════
        # FIX 2026-04-03 R17: REVERSAL COOLDOWN — Anti-whipsaw
        # Bloque si le dernier trade était une perte ET la direction actuelle est inversée
        # ══════════════════════════════════════════════════════════════════════
        try:
            _rev_cooldown_min = int(
                (self.cfg.get("orchestrator", {}).get("cooldown", {})
                 .get("reversal_cooldown_min", 60))
            )
            if _rev_cooldown_min > 0 and hasattr(self, "_last_trade_result"):
                _ltr = self._last_trade_result or {}
                _last_dir = _ltr.get("direction", "")
                _last_pnl = float(_ltr.get("pnl", 0))
                _last_ts = float(_ltr.get("close_ts", 0))

                if (_last_pnl < 0 and _last_dir and _last_dir != sig
                        and _last_ts > 0):
                    import time as _time_rev
                    _elapsed_min = (_time_rev.time() - _last_ts) / 60
                    if _elapsed_min < _rev_cooldown_min:
                        _remaining = int(_rev_cooldown_min - _elapsed_min)
                        logger.warning(
                            f"[REVERSAL_COOLDOWN] {symbol}: {sig} bloqué — dernier trade "
                            f"était {_last_dir} (perte ${abs(_last_pnl):.0f}), "
                            f"cooldown encore {_remaining} min"
                        )
                        self._send_telegram(
                            f"🔄 [ANTI-WHIPSAW] {symbol}: {sig} bloqué\n"
                            f"Dernier trade: {_last_dir} (perte)\n"
                            f"Cooldown inversé: encore {_remaining} min",
                            kind="status", force=True
                        )
                        return False
        except Exception as _rev_err:
            logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: erreur — {_rev_err}")
        # ══════════════════════════════════════════════════════════════════════
```

3. Il faut aussi stocker le résultat du dernier trade. Chercher l'endroit où le trade outcome est enregistré (probablement dans `_on_position_closed` ou similaire). Ajouter :
```python
        self._last_trade_result = {
            "direction": direction,  # "LONG" ou "SHORT"
            "pnl": pnl,
            "close_ts": time.time(),
        }
```
   Si `_last_trade_result` n'est pas initialisé dans `__init__`, l'ajouter : `self._last_trade_result = None`

---

## AMÉLIORATION 5 : RISK REDUCTION DYNAMIQUE pour symboles en perte
**Fichier** : `config/overrides.yaml`
**Pourquoi** : Même si un symbole perd, on peut minimiser l'impact en réduisant le risque par trade.

### Instructions dans `overrides.yaml` :

1. **BNBUSD** — modifier `risk:` :
```yaml
  risk:
    risk_per_trade: 0.002             # R17: Réduit de 0.004→0.002 (risque minimal)
    daily_loss_abs: 60                # R17: Réduit de 120→60 (kill switch plus serré)
```

2. **AUDUSD** — ajouter/modifier sous le bloc AUDUSD :
```yaml
  risk:
    risk_per_trade: 0.002             # R17: risque minimal
    daily_loss_abs: 60                # R17: kill switch serré
    max_consec_losses: 2              # R17: pause après 2 pertes (pas 3)
```

3. **USDJPY** — modifier `risk:` :
```yaml
  risk:
    risk_per_trade: 0.002             # R17: risque minimal
    daily_loss_abs: 60                # R17: kill switch serré (était 150)
    max_consec_losses: 2              # R17: pause après 2 pertes
```

4. **SOLUSD** — modifier `risk:` :
```yaml
  risk:
    risk_per_trade: 0.004             # R17: réduit (prudence)
    daily_loss_abs: 150               # R17: réduit de 300→150
```

---

## AMÉLIORATION 6 : ENHANCED REGIME FILTER pour SHORT
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : Le regime detector existe mais ne différencie pas LONG/SHORT dans sa sévérité. On le rend asymétrique.

### Instructions :
Dans la méthode `_run_agents_and_decide()`, dans le bloc REGIME (vers ligne 3897), modifier le filtre :

Chercher :
```python
                        if regime_type == "trending_down" and direction == "LONG" and regime_confidence > 0.6:
```

**APRÈS ce bloc if/elif** (après le elif pour trending_up/SHORT), ajouter un nouveau filtre :
```python
                            # R17: SHORT en régime non-trending_down = interdit sauf score élevé
                            elif direction == "SHORT" and regime_type not in ("trending_down",) and regime_confidence > 0.5:
                                _short_regime_min = self._hf_counter_trend_min_score
                                if score_agr < _short_regime_min:
                                    reasons.append(f"short_not_trending_down:{regime_type}")
                                    decision_notes.append(f"short_regime_blocked:{regime_type}")
                                    logger.info(
                                        f"[REGIME] {symbol} SHORT bloqué: régime={regime_type} "
                                        f"(pas trending_down), score={score_agr:.1f}<{_short_regime_min}"
                                    )
```

---

## AMÉLIORATION 7 : SESSION ASIE PENALTY — Pénalité heures peu liquides
**Fichier** : `orchestrator/orchestrator.py` et `config/config.yaml`
**Pourquoi** : La session Asie (00-08 UTC) = -$489 sur 5 jours pour les non-crypto. Au lieu de bloquer complètement, on applique une pénalité de score.

### Instructions :
1. Dans `config/config.yaml`, ajouter sous `orchestrator.hard_filters:` :
```yaml
    # R17: Pénalité session basse liquidité
    low_liquidity_score_penalty: 2.0  # Score additionnel requis pendant heures creuses
    low_liquidity_hours_utc: [0, 1, 2, 3, 4, 5, 22, 23]  # Heures concernées
```

2. Dans `execute_trade()`, **JUSTE AVANT** le bloc HARD_FILTER score, après le calcul du `_adaptive_boost`, ajouter :
```python
        # R17: Pénalité session basse liquidité
        _liq_penalty = 0.0
        _hf_cfg_r17 = self.cfg.get("orchestrator", {}).get("hard_filters", {})
        _liq_hours = _hf_cfg_r17.get("low_liquidity_hours_utc", [0, 1, 2, 3, 4, 5, 22, 23])
        _is_crypto_r17 = symbol.upper() in self._hf_crypto_symbols
        if not _is_crypto_r17 and current_hour_utc in _liq_hours:
            _liq_penalty = float(_hf_cfg_r17.get("low_liquidity_score_penalty", 2.0))
            logger.info(
                f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
                f"penalty +{_liq_penalty} sur min_score"
            )
```

3. Modifier la ligne du HARD_MIN_SCORE pour inclure cette pénalité :
```python
        HARD_MIN_SCORE = self._hf_min_score + _adaptive_boost + _liq_penalty
```

---

## RÉSUMÉ DES MODIFICATIONS

| # | Amélioration | Fichier(s) | Impact attendu |
|---|---|---|---|
| 1 | SHORT PENALTY | orchestrator.py + config.yaml | Élimine ~70% des SHORT perdants |
| 2 | ADAPTIVE MIN_SCORE | orchestrator.py + config.yaml | Auto-durcit les symboles en perte |
| 3 | LONG ONLY + restrictions | overrides.yaml | BTCUSD/SOLUSD/AUDUSD/USDJPY en LONG only |
| 4 | REVERSAL COOLDOWN | orchestrator.py + config.yaml | Élimine les whipsaws après perte |
| 5 | RISK REDUCTION | overrides.yaml | Réduit l'impact $ des symboles perdants |
| 6 | REGIME FILTER SHORT | orchestrator.py | Bloque SHORT hors tendance baissière |
| 7 | SESSION PENALTY | orchestrator.py + config.yaml | Réduit les pertes en session Asie |

## VÉRIFICATION APRÈS MODIFICATION
Après avoir appliqué les 7 améliorations, vérifier :
1. Le fichier `orchestrator.py` n'a pas d'erreur de syntaxe (`python -c "import py_compile; py_compile.compile('orchestrator/orchestrator.py', doraise=True)"`)
2. Le fichier `config/config.yaml` est valide (`python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"`)
3. Le fichier `config/overrides.yaml` est valide (`python -c "import yaml; yaml.safe_load(open('config/overrides.yaml'))"`)
4. Vérifier que `_last_trade_result` est bien initialisé dans `__init__` de `SymbolOrchestrator`
5. Lister un résumé de tous les changements effectués

## IMPORTANT
- Ne PAS désactiver de symbole. L'objectif est de les rendre plus intelligents.
- Chaque amélioration doit avoir des logs clairs avec un tag unique (ex: `[SHORT_PENALTY]`, `[ADAPTIVE_SCORE]`)
- Les nouvelles valeurs de config doivent toutes être dans config.yaml/overrides.yaml (pas hardcodées)
- Préserver TOUTE la logique existante — on AJOUTE, on ne remplace pas
