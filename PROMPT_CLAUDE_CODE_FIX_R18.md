# PROMPT CLAUDE CODE — ROUND 18 : CORRECTIONS + MODE PROBATION (6 améliorations)

## CONTEXTE

Diagnostic 14 jours : PF 0.80, P&L -$1,192. Le bot perd de l'argent.
- **Cause #1** : Session Asie (00-07 UTC) = -$1,113, soit 93% des pertes → 13.3% HR
- **Cause #2** : SOLUSD (-$906, 18.5% HR), BNBUSD (-$489, 7.1% HR), LTCUSD (-$299, 0% HR)
- **Cause #3** : Filtres R17 `[LIQ_PENALTY]` et `[REVERSAL_COOLDOWN]` = 0 occurrences dans les logs → bugs à corriger
- **Positif** : XAUUSD +$1,556 (71.4% HR), NAS100 +$535 (56.3% HR), SP500 +$58 (42.1% HR)
- **Positif** : R17 fonctionne partiellement (ADAPTIVE_SCORE 9528 blocages, SHORT_PENALTY 272 blocages)

**Philosophie** : On ne désactive AUCUN symbole. On les met en **mode probation** avec des garde-fous extrêmes.

---

## FIX 1 : BLOQUER LES ENTRIES SESSION ASIE (P1 — impact estimé +$1,000/14j)
**Fichiers** : `config/config.yaml` + `orchestrator/orchestrator.py`
**Pourquoi** : 15 trades en Asie (00-07 UTC), 13.3% HR, -$1,113. C'est LE problème #1.

### 1a. Config — ajouter dans `config.yaml` sous `orchestrator.hard_filters:` :
```yaml
    # R18: Blocage complet des entries session Asie pour non-crypto
    asia_block:
      enabled: true
      hours_utc: [0, 1, 2, 3, 4, 5, 6, 7]     # 00h-07h UTC bloqué
      exempt_crypto: true                         # Crypto exemptée (24/7)
```

### 1b. Code — dans `execute_trade()`, JUSTE APRÈS le bloc HOUR_FILTER (après la ligne `# Log si le filtre est passé`), AVANT le bloc HARD FILTERS, ajouter :

```python
        # ══════════════════════════════════════════════════════════════════════
        # FIX 2026-04-10 R18: ASIA BLOCK — Bloquer entries 00-07 UTC non-crypto
        # Diagnostic 14j: session Asie = -$1,113 (93% des pertes), 13.3% HR
        # ══════════════════════════════════════════════════════════════════════
        try:
            _asia_cfg = (self.cfg.get("orchestrator", {})
                        .get("hard_filters", {})
                        .get("asia_block", {}))
            if _asia_cfg.get("enabled", False):
                _asia_hours = _asia_cfg.get("hours_utc", [0, 1, 2, 3, 4, 5, 6, 7])
                _asia_exempt = _asia_cfg.get("exempt_crypto", True)
                _is_crypto_asia = symbol.upper() in self._hf_crypto_symbols

                if current_hour_utc in _asia_hours and not (_asia_exempt and _is_crypto_asia):
                    logger.warning(
                        f"[ASIA_BLOCK] {symbol}: entry bloquée — heure {current_hour_utc}h UTC "
                        f"en session Asie (00-07 UTC). Non-crypto interdit."
                    )
                    self._send_telegram(
                        f"🌙 [ASIA_BLOCK] {symbol}: entry bloquée\n"
                        f"Heure: {current_hour_utc}h UTC (session Asie)\n"
                        f"→ Seules les cryptos sont autorisées 00-07 UTC",
                        kind="status", force=True
                    )
                    return False
                elif current_hour_utc in _asia_hours and _asia_exempt and _is_crypto_asia:
                    logger.debug(
                        f"[ASIA_BLOCK] {symbol}: crypto exemptée — heure {current_hour_utc}h UTC PASS"
                    )
        except Exception as _asia_err:
            logger.debug(f"[ASIA_BLOCK] {symbol}: erreur — {_asia_err}")
        # ══════════════════════════════════════════════════════════════════════
```

---

## FIX 2 : MODE PROBATION pour symboles en difficulté (P1 — impact estimé +$1,200/14j)
**Fichiers** : `config/overrides.yaml` + `config/config.yaml` + `orchestrator/orchestrator.py`
**Pourquoi** : Au lieu de désactiver SOLUSD/BNBUSD/LTCUSD, on les met en probation avec des restrictions extrêmes mais intelligentes.

### 2a. Config — ajouter dans `config.yaml` sous `orchestrator:` :
```yaml
  # R18: Mode probation — restrictions extrêmes pour symboles en difficulté
  probation:
    enabled: true
    max_trades_per_day: 1                # 1 seul trade par jour max
    daily_loss_abs: 30                   # Kill switch à $30/jour (1 perte = stop)
    risk_per_trade_override: 0.001       # 0.1% risque par trade (minimum absolu)
    votes_required_override: 4           # 4 agents doivent être d'accord (sur 5+)
    min_score_override: 7.0              # Score très élevé requis
    consecutive_loss_pause_hours: 48     # Après 2 pertes consécutives → pause 48h
    consecutive_loss_threshold: 2        # Nombre de pertes consécutives avant pause
    promotion_consecutive_wins: 5        # 5 wins consécutifs → sort de probation
    # Heures autorisées (seulement les meilleures sessions)
    allowed_hours_utc: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]  # London+NY uniquement
```

### 2b. Overrides — mettre les 3 symboles en probation dans `overrides.yaml` :

Pour **SOLUSD**, modifier le bloc existant :
```yaml
SOLUSD:
  orchestrator:
    # R18: MODE PROBATION — 27 trades, 18.5% HR, -$906 sur 14j
    probation: true
    allowed_directions: ["LONG"]          # R17: maintenu LONG only
    min_score_for_proposal: 7.0           # R18: relevé de 4.0→7.0
    max_trades_per_day: 1                 # R18: 1 seul trade/jour
    votes_required: 4                     # R18: 4 agents d'accord
    allowed_hours_utc: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]  # R18: London+NY only
    position_limits:
      max_volume: 5.0
    cooldown:
      enabled: true
      min_secs_between_trades: 600
      max_trades_per_day: 1               # R18: réduit à 1
      after_loss_min: 120                 # R18: 2h après perte (était 60)
      after_streak_n: 2                   # R18: pause après 2 pertes (était 3)
      after_streak_min: 2880              # R18: 48h de pause (2880 min)
    atr_sl_mult: 1.5
    atr_tp_mult: 2.5
    position_manager:
      max_duration_minutes: 360
  risk:
    risk_per_trade: 0.001                 # R18: risque minimal absolu (0.1%)
    daily_loss_abs: 30                    # R18: kill switch $30/jour
    max_consec_losses: 2                  # R18: 2 pertes = pause
```

Pour **BNBUSD**, modifier le bloc existant :
```yaml
BNBUSD:
  orchestrator:
    auto_execute: true
    telegram_validation: false
    # R18: MODE PROBATION — 14 trades, 7.1% HR, -$489 sur 14j
    # R18: Changement SHORT only → LONG only (les SHORTs = 7.1% HR, catastrophique)
    probation: true
    allowed_directions: ["LONG"]          # R18: INVERSE de R17 — essayer LONG au lieu de SHORT
    min_score_for_proposal: 7.0           # R18: relevé de 5.0→7.0
    min_rr: 0.8
    votes_required: 4                     # R18: 4 agents d'accord
    max_trades_per_day: 1                 # R18: 1 seul trade/jour
    min_confluence: 1.2
    require_scalping_entry: false
    require_swing_confirm: false
    agent_weights:
      swing: 0.6
      structure: 0.7
      scalping: 0.6
      smart_money: 0.6
      news: 0.4
    once_per_candle_tf: "M30"
    allowed_hours_utc: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]  # R18: London+NY
    cooldown:
      enabled: true
      min_secs_between_trades: 600
      max_trades_per_day: 1               # R18: réduit à 1
      after_trade_min: 4
      after_loss_min: 120                 # R18: 2h après perte
      after_win_min: 6
      after_streak_n: 2                   # R18: pause après 2 pertes
      after_streak_min: 2880              # R18: 48h de pause
    news_filter:
      enabled: true
      csv_path: data/news_calendar.csv
      impacts: ["High", "Medium"]
      window_before_min: 45
      window_after_min: 45
    position_limits:
      max_positions: 2
      max_volume: 1.0
      max_net_volume: 0.01
    blocked_hours_utc: [0, 1, 2, 3, 4, 5, 6, 7]  # R18: nuit bloquée
    live_guard:
      enabled: true
      pf_min_live: 1.20
      hit_min_live: 0.40
      min_trades_live: 15
      lookback_days: 7
    trading_window:
      enabled: false
    multi_timeframes:
      enabled: true
      tfs: ["H1", "M15", "M5"]
      tf_weights:
        H1: 1.2
        M15: 1.0
        M5: 0.9
    atr_sl_mult: 1.5
    atr_tp_mult: 2.5
  risk:
    risk_per_trade: 0.001                 # R18: risque minimal absolu
    daily_loss_abs: 30                    # R18: kill switch $30/jour
    max_consec_losses: 2                  # R18: 2 pertes = pause
    daily_loss_limit_pct: 0.025
    dynamic_risk: true
  position_manager:
    enabled: true
    max_duration_minutes: 360
    break_even:
      rr: 1.2
      offset_points: 0.0
    partials:
      - rr: 1.5
        close_frac: 0.3
      - rr: 2.5
        close_frac: 0.3
    trailing:
      enabled: true
      start_rr: 1.7
      atr_timeframe: M15
      atr_period: 21
      atr_mult: 1.8
      lock_rr: 0.3
```

Pour **LTCUSD**, modifier le bloc existant :
```yaml
LTCUSD:
  orchestrator:
    enabled: true
    # R18: MODE PROBATION — 1 trade, 0% HR, -$299 sur 14j
    probation: true
    allowed_directions: ["LONG"]          # R18: LONG only
    min_score_for_proposal: 7.0           # R18: relevé de 2.5→7.0
    max_trades_per_day: 1                 # R18: 1 seul trade/jour
    auto_execute: true
    telegram_validation: false
    status_report_hours: 2
    min_rr: 0.8
    votes_required: 4                     # R18: 4 agents d'accord
    min_confluence: 2.0
    min_confluence_dispersion: 0.15
    require_scalping_entry: false
    require_swing_confirm: true
    allowed_hours_utc: [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]  # R18: London+NY
    agent_weights:
      swing: 0.8
      structure: 0.9
      scalping: 0.4
      smart_money: 0.7
      news: 0.3
    tracker_confluence_weight: 0.70
    tracker_vote_threshold: 0.80
    market_confluence_weight: 0.75
    tf_weight_dynamic_scale: 0.15
    multi_timeframes:
      enabled: true
      tfs: ["H1", "M15", "M5"]
      tf_weights:
        H1: 1.2
        M15: 1.0
        M5: 0.9
    once_per_candle_tf: "H1"
    cooldown:
      enabled: true
      min_secs_between_trades: 1800
      max_trades_per_day: 1               # R18: réduit à 1
      after_trade_min: 15
      after_win_min: 20
      after_loss_min: 120                 # R18: 2h après perte
      after_reject_min: 10
      after_streak_n: 2                   # R18: pause après 2 pertes
      after_streak_min: 2880              # R18: 48h de pause
    news_filter:
      enabled: true
      csv_path: data/news_calendar.csv
      impacts: ["High"]
      window_before_min: 60
      window_after_min: 60
    position_limits:
      max_positions: 1
      max_volume: 5.0
      max_net_volume: 1.0
    live_guard:
      enabled: true
      pf_min_live: 1.50
      hit_min_live: 0.55
      min_trades_live: 10
      lookback_days: 5
    trading_window:
      enabled: false
    atr_sl_mult: 1.5
    atr_tp_mult: 3.5
  risk:
    risk_per_trade: 0.001                 # R18: risque minimal absolu
    daily_loss_abs: 30                    # R18: kill switch $30/jour
    max_consec_losses: 2                  # R18: 2 pertes = pause
    daily_loss_limit_pct: 0.01
    dynamic_risk: true
  position_manager:
    enabled: true
    break_even:
      rr: 1.2
      offset_points: 2.0
    partials:
      - rr: 1.5
        close_frac: 0.3
      - rr: 2.5
        close_frac: 0.3
    trailing:
      enabled: true
      start_rr: 1.0
      atr_timeframe: M15
      atr_period: 21
      atr_mult: 1.5
      lock_rr: 0.5
```

### 2c. Code — dans `execute_trade()`, ajouter un log de probation. APRÈS le bloc ASIA_BLOCK, AVANT le HARD FILTER :
```python
        # ══════════════════════════════════════════════════════════════════════
        # FIX 2026-04-10 R18: LOG PROBATION — Identifier les symboles en probation
        # ══════════════════════════════════════════════════════════════════════
        _is_probation = bool(self.ori_cfg.get("probation", False))
        if _is_probation:
            logger.info(
                f"[PROBATION] {symbol}: symbole en MODE PROBATION — "
                f"restrictions max (1 trade/jour, risk 0.1%, score 7.0+, 4 votes)"
            )
        # ══════════════════════════════════════════════════════════════════════
```

---

## FIX 3 : CORRIGER LIQ_PENALTY (P2 — le tag ne s'affiche jamais)
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : 0 occurrences de `[LIQ_PENALTY]` dans les logs. Le problème est que les non-crypto en heures 00-05 UTC sont déjà bloquées par `blocked_hours_utc` ou `prime_hours_utc` AVANT d'atteindre le code LIQ_PENALTY. Seules les heures 22-23 UTC pourraient déclencher le filtre, mais beaucoup de symboles ont des `prime_hours` qui excluent ces heures.

### Solution : Élargir la plage LIQ_PENALTY et ajouter un log de passage même quand non déclenché.

Chercher le bloc LIQ_PENALTY (vers ligne 2267) et remplacer par :
```python
        # R18: Pénalité session basse liquidité (corrigé — R17 ne se déclenchait jamais)
        _liq_penalty = 0.0
        _hf_cfg_r17 = self.cfg.get("orchestrator", {}).get("hard_filters", {})
        _liq_hours = _hf_cfg_r17.get("low_liquidity_hours_utc", [0, 1, 2, 3, 4, 5, 6, 7, 22, 23])
        _is_crypto_r17 = symbol.upper() in self._hf_crypto_symbols
        if not _is_crypto_r17 and current_hour_utc in _liq_hours:
            _liq_penalty = float(_hf_cfg_r17.get("low_liquidity_score_penalty", 2.0))
            logger.info(
                f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
                f"penalty +{_liq_penalty} sur min_score"
            )
        else:
            logger.debug(
                f"[LIQ_PENALTY] {symbol}: heure {current_hour_utc}h UTC → "
                f"pas de penalty (crypto={_is_crypto_r17}, in_liq_hours={current_hour_utc in _liq_hours})"
            )
```

Et dans `config.yaml`, modifier la plage horaire pour inclure les heures pré-London :
```yaml
    low_liquidity_hours_utc: [0, 1, 2, 3, 4, 5, 6, 7, 22, 23]  # R18: étendu à 00-07h + 22-23h
```

---

## FIX 4 : CORRIGER REVERSAL_COOLDOWN (P2 — le tag ne s'affiche jamais)
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : 0 occurrences. Deux causes identifiées :
1. `_last_trade_result` est `None` après restart (pas persisté)
2. Les symboles LONG only (BTCUSD, SOLUSD, AUDUSD, USDJPY) ne peuvent pas avoir de reversal (toujours LONG)
3. Le code utilise `_time_rev.time()` qui retourne les secondes depuis minuit, pas un timestamp Unix

### Solution : Corriger le calcul de temps + ajouter un log de passage.

Chercher le bloc REVERSAL_COOLDOWN (vers ligne 2110) et remplacer TOUT le bloc par :
```python
        # ══════════════════════════════════════════════════════════════════════
        # FIX 2026-04-10 R18: REVERSAL COOLDOWN — Anti-whipsaw (corrigé)
        # R17 original ne se déclenchait jamais car time.time() ≠ timestamp Unix
        # ══════════════════════════════════════════════════════════════════════
        try:
            _rev_cooldown_min = int(
                (self.cfg.get("orchestrator", {}).get("cooldown", {})
                 .get("reversal_cooldown_min", 60))
            )
            if _rev_cooldown_min > 0 and self._last_trade_result is not None:
                _ltr = self._last_trade_result
                _last_dir = _ltr.get("direction", "")
                _last_pnl = float(_ltr.get("pnl", 0))
                _last_ts = float(_ltr.get("close_ts", 0))
                _now_ts = time.time()  # FIX R18: utiliser time.time() directement (Unix timestamp)

                if _last_pnl < 0 and _last_dir and _last_dir != sig and _last_ts > 0:
                    _elapsed_min = (_now_ts - _last_ts) / 60.0
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
                    else:
                        logger.debug(
                            f"[REVERSAL_COOLDOWN] {symbol}: reversal {_last_dir}→{sig} "
                            f"mais cooldown expiré ({_elapsed_min:.0f} min > {_rev_cooldown_min} min) → PASS"
                        )
                elif _last_dir == sig:
                    logger.debug(
                        f"[REVERSAL_COOLDOWN] {symbol}: même direction {sig} → pas de reversal → PASS"
                    )
                elif _last_pnl >= 0:
                    logger.debug(
                        f"[REVERSAL_COOLDOWN] {symbol}: dernier trade {_last_dir} était gagnant → PASS"
                    )
            elif self._last_trade_result is None:
                logger.debug(
                    f"[REVERSAL_COOLDOWN] {symbol}: aucun trade précédent enregistré → PASS"
                )
        except Exception as _rev_err:
            logger.debug(f"[REVERSAL_COOLDOWN] {symbol}: erreur — {_rev_err}")
        # ══════════════════════════════════════════════════════════════════════
```

Aussi, vérifier que dans le stockage du résultat (vers ligne 1162), le `close_ts` utilise bien `time.time()` et pas autre chose. Le code actuel est :
```python
                self._last_trade_result = {
                    "direction": _dir_close.upper() if _dir_close else "",
                    "pnl": _pnl_close,
                    "close_ts": time.time(),
                }
```
→ C'est correct. Le bug était dans la lecture (`_time_rev.time()` qui crée un alias inutile).

---

## FIX 5 : AJUSTER MIN_SCORE BTCUSD et USDJPY (P2)
**Fichier** : `config/overrides.yaml`

### 5a. BTCUSD — monter min_score de 1.2 à 3.0
Chercher `min_score_for_proposal: 1.2` dans le bloc BTCUSD et remplacer par :
```yaml
    min_score_for_proposal: 3.0             # R18: monté de 1.2→3.0 (28.6% HR trop bas)
```

### 5b. USDJPY — monter min_score de 5.0 à 6.0
Chercher `min_score_for_proposal: 5.0` dans le bloc USDJPY et remplacer par :
```yaml
    min_score_for_proposal: 6.0             # R18: monté de 5.0→6.0 (25% HR, LONGs à -$46)
```

---

## FIX 6 : DÉSACTIVER PROPREMENT FINNHUB (P2 — stop les 403 en boucle)
**Fichier** : `config/config.yaml`
**Pourquoi** : L'API Finnhub renvoie 403 Forbidden depuis le 7 avril. Le calendrier économique n'est plus alimenté. Les erreurs polluent les logs et gaspillent du temps dans le sémaphore MT5.

### Solution : Désactiver Finnhub dans config.yaml
Chercher le bloc `finnhub:` et modifier :
```yaml
  finnhub:
    enabled: false                        # R18: DÉSACTIVÉ — 403 Forbidden depuis le 7 avril
    # enabled: true                       # Réactiver quand la clé API sera renouvelée
    api_key: "${FINNHUB_API_KEY}"
    cache_ttl: 3600
    freeze_period_minutes: 15
    events_to_track:
      - FOMC
      - NFP
      - CPI
      - GDP
      - ECB
      - BOE
      - BOJ
```

---

## RÉSUMÉ DES MODIFICATIONS

| # | Fix | Fichier(s) | Impact attendu |
|---|-----|-----------|----------------|
| 1 | ASIA BLOCK | orchestrator.py + config.yaml | +$1,000/14j (élimine 93% des pertes) |
| 2 | MODE PROBATION | overrides.yaml + config.yaml + orchestrator.py | +$1,200/14j (SOLUSD/BNBUSD/LTCUSD bridés) |
| 3 | FIX LIQ_PENALTY | orchestrator.py + config.yaml | Filtre enfin actif + meilleur logging |
| 4 | FIX REVERSAL_COOLDOWN | orchestrator.py | Anti-whipsaw enfin fonctionnel |
| 5 | MIN_SCORE BTCUSD/USDJPY | overrides.yaml | Filtrage trades faibles |
| 6 | DISABLE FINNHUB | config.yaml | Stop 403 spam, logs propres |

## VÉRIFICATION APRÈS MODIFICATION

```bash
# 1. Syntaxe Python
python -c "import py_compile; py_compile.compile('orchestrator/orchestrator.py', doraise=True)"

# 2. Syntaxe YAML config
python -c "import yaml; yaml.safe_load(open('config/config.yaml')); print('config.yaml OK')"

# 3. Syntaxe YAML overrides
python -c "import yaml; yaml.safe_load(open('config/overrides.yaml')); print('overrides.yaml OK')"

# 4. Vérifier les nouveaux paramètres
python -c "
import yaml
c = yaml.safe_load(open('config/config.yaml'))
hf = c.get('orchestrator', {}).get('hard_filters', {})
ab = hf.get('asia_block', {})
print('asia_block.enabled:', ab.get('enabled', 'ABSENT'))
print('asia_block.hours:', ab.get('hours_utc', 'ABSENT'))
print('low_liq_hours:', hf.get('low_liquidity_hours_utc', 'ABSENT'))
print('finnhub.enabled:', c.get('external_apis', {}).get('finnhub', {}).get('enabled', 'ABSENT'))

prob = c.get('orchestrator', {}).get('probation', {})
print('probation.enabled:', prob.get('enabled', 'ABSENT'))
print('probation.max_trades:', prob.get('max_trades_per_day', 'ABSENT'))

o = yaml.safe_load(open('config/overrides.yaml'))
for sym in ['SOLUSD', 'BNBUSD', 'LTCUSD', 'BTCUSD', 'USDJPY']:
    oc = o.get(sym, {}).get('orchestrator', {})
    print(f'{sym}: probation={oc.get(\"probation\", False)}, min_score={oc.get(\"min_score_for_proposal\", \"DEFAULT\")}, dirs={oc.get(\"allowed_directions\", \"ALL\")}')
"

# 5. Résumé des changements
echo "=== R18 APPLIQUÉ ==="
```

## IMPORTANT
- Ne PAS désactiver de symbole (enabled: false). On utilise le MODE PROBATION.
- Le mode probation = 1 trade/jour, risk 0.1%, score 7.0+, 4 votes, kill switch $30, pause 48h après 2 pertes
- BNBUSD passe de SHORT only → LONG only (le SHORT était catastrophique à 7.1% HR)
- ASIA BLOCK s'applique aux non-crypto uniquement (crypto = 24/7)
- Les logs doivent avoir des tags clairs : `[ASIA_BLOCK]`, `[PROBATION]`, `[LIQ_PENALTY]`, `[REVERSAL_COOLDOWN]`
- Préserver TOUTE la logique existante — on AJOUTE, on ne remplace pas (sauf les 2 blocs corrigés)
