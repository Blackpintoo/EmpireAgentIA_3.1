# PROMPT CLAUDE CODE — ROUND 19 : XAUUSD PROBATION + NAS100 BOOST + CORRECTIFS DÉPLOIEMENT (5 améliorations)

## CONTEXTE

Diagnostic POST-R18 (6 jours) : PF 0.56, P&L = perte. Améliorations R18 partiellement efficaces.
- **ASIA BLOCK** : ✅ Fonctionne parfaitement (0 entry non-crypto 00-07 UTC)
- **PROBATION** : ✅ Fonctionne (SOLUSD/BNBUSD/LTCUSD = 0 trades en 6 jours, pertes stoppées)
- **Hit rate global** : ✅ Amélioré (34.9% → 43.9%)
- **Cause #1** : XAUUSD effondrement brutal — 6 trades, 0 wins, -$1,276 (0% HR). Était la star (+$1,556, 71.4% HR avant R18). Probablement contexte macro (volatilité tarifs). Risk 0.012 trop élevé sans garde-fous.
- **Cause #2** : USDJPY toujours en échec — 3 trades, 0 wins, -$241 (0% HR). Malgré min_score 6.0 et LONG only.
- **Cause #3** : `[LIQ_PENALTY]` et `[REVERSAL_COOLDOWN]` = 0 occurrences dans 5.3M lignes de logs. Le code R18 n'est PAS exécuté en production → problème de déploiement suspecté. Le code ADAPTIVE_SCORE (même zone) fonctionne (14,326 occurrences).
- **Cause #4** : Finnhub 403 persiste — `config.yaml` a `enabled: false` mais `utils/econ_api.py` appelle Finnhub directement via `_fetch_finnhub()` sans vérifier le flag `enabled`.
- **Positif** : NAS100 = +$714, 73.3% HR, PF 6.0 (15 trades, 11 wins). Mérite une allocation risk augmentée.
- **Positif** : SP500 = +$245, 72.7% HR, PF 3.3. Solide.
- **Positif** : Avg $/win a baissé ($111 → $53) mais avg $/loss aussi ($130 → $68)

**Philosophie** : On ne désactive AUCUN symbole. XAUUSD et USDJPY passent en **mode probation temporaire** avec garde-fous extrêmes.

---

## FIX 1 : XAUUSD EN MODE PROBATION TEMPORAIRE (P1 — impact estimé +$1,200/6j)
**Fichier** : `config/overrides.yaml`
**Pourquoi** : XAUUSD a perdu $1,276 en 6 jours (0% HR, 6 SL consécutifs). Le risk 0.012 sans probation = hémorragie. En période de forte volatilité macro (tarifs), l'or est erratique. On le bride temporairement comme SOLUSD/BNBUSD/LTCUSD, mais en mode probation ADAPTÉ à XAUUSD (risk plus élevé que crypto car c'est historiquement notre meilleur actif).

### Remplacer TOUT le bloc XAUUSD dans `overrides.yaml` par :
```yaml
# ══════════════════════════════════════════════════════════════════════════════
# XAUUSD — Or — MODE PROBATION TEMPORAIRE R19
# POST-R18: 6 trades, 0 wins, -$1,276 (0% HR). Était +$1,556 (71.4%) avant.
# Contexte macro: volatilité tarifs → or erratique.
# ══════════════════════════════════════════════════════════════════════════════
XAUUSD:
  orchestrator:
    # R19: MODE PROBATION TEMPORAIRE — 0% HR, -$1,276 sur 6 jours
    probation: true
    allowed_directions: ["LONG"]          # R19: LONG only — les SHORTs en volatilité macro = suicide
    min_score_for_proposal: 6.5           # R19: relevé (était implicite ~2.5 via global). Score élevé requis.
    votes_required: 3                     # R19: 3 agents d'accord (moins strict que crypto car historiquement bon)
    max_trades_per_day: 2                 # R19: 2 trades/jour max (était 4)
    # FIX 2026-02-20: whale_override désactivé pour non-crypto (étape 4.8)
    whale_override:
      enable: false
    position_manager:
      enabled: true
      max_duration_minutes: 360           # FIX 2026-02-24: timeout 6h (Directive 4)
      break_even:
        rr: 1.0                           # R19: BE plus agressif 1.2→1.0 (protéger capital plus tôt)
        offset_points: 0.0
      partials:
        - rr: 1.5
          close_frac: 0.3
        - rr: 2.5
          close_frac: 0.3
      trailing:
        enabled: true
        start_rr: 1.4
        atr_timeframe: M15
        atr_period: 21
        atr_mult: 1.4
        lock_rr: 0.3
    cooldown:
      enabled: true
      min_secs_between_trades: 900        # R19: 15 min entre trades (était 600)
      max_trades_per_day: 2               # R19: réduit de 4→2
      after_trade_min: 5
      after_loss_min: 120                 # R19: 2h après perte (était 60)
      after_win_min: 4
      after_streak_n: 2                   # R19: pause après 2 pertes (était 3)
      after_streak_min: 1440              # R19: 24h de pause (1440 min) — moins que crypto (48h) car actif historiquement bon
    news_filter:
      enabled: true
      csv_path: data/news_calendar.csv
      impacts: ["High", "Medium"]
      window_before_min: 45               # R19: élargi 30→45 min (événements macro = danger pour or)
      window_after_min: 45                # R19: élargi 30→45 min
    position_limits:
      max_positions: 3                    # R19: réduit de 6→3
      max_volume: 0.10                    # R19: réduit de 0.15→0.10
      max_net_volume: 0.05
    live_guard:
      enabled: true
      pf_min_live: 1.10
      hit_min_live: 0.40
      min_trades_live: 15
      lookback_days: 7
    # FIX 2026-02-20: ATR SL resserré (étape 1.3)
    atr_sl_mult: 1.6                      # R19: resserré 1.8→1.6 (SL plus tight)
    atr_tp_mult: 2.5
    # FIX 2026-02-24: heures toxiques
    blocked_hours_utc: [14, 18]
    # R19: restreindre aux heures London (meilleure liquidité or)
    prime_hours_utc:
      - {start: 7, end: 17}              # Session London
    allowed_hours_utc: [7, 8, 9, 10, 11, 12, 13, 15, 16, 17]  # R19: London seulement, excluant 14h et 18h (bloquées)
  risk:
    risk_per_trade: 0.005                 # R19: réduit 0.012→0.005 (divisé par 2.4). Reste > crypto probation (0.001)
    daily_loss_abs: 100                   # R19: kill switch réduit 220→$100/jour
    max_consec_losses: 2                  # R19: pause après 2 pertes
```

**Logique** : XAUUSD est en probation MODÉRÉE (pas extrême comme les crypto). Risk divisé par 2.4, max 2 trades/jour, LONG only, score 6.5+, 3 votes. Si le marché se calme, on pourra augmenter progressivement.

---

## FIX 2 : BOOSTER NAS100 (P1 — impact estimé +$300-500/6j)
**Fichier** : `config/overrides.yaml`
**Pourquoi** : NAS100 = PF 6.0, 73.3% HR, +$714 en 6 jours. C'est de loin notre meilleur actif. Le risk actuel est implicite (hérité du global). On l'augmente pour capitaliser sur la performance.

### Modifier le bloc NAS100 dans `overrides.yaml` :
```yaml
# ══════════════════════════════════════════════════════════════════════════════
# NAS100 — Nasdaq — MOTEUR PRINCIPAL R19
# POST-R18: 15 trades, 11 wins, +$714, 73.3% HR, PF 6.0
# ══════════════════════════════════════════════════════════════════════════════
NAS100:
  orchestrator:
    min_score_for_proposal: 4.5           # R19: baissé de 5.0→4.5 (HR 73.3% justifie plus de trades)
    # FIX 2026-02-20: whale_override désactivé pour non-crypto (étape 4.8)
    whale_override:
      enable: false
    position_limits:
      max_volume: 2.0                     # R19: augmenté 1.0→2.0 (plus de marge)
    cooldown:
      enabled: true
      min_secs_between_trades: 600
      max_trades_per_day: 6               # R19: augmenté 4→6 (capitaliser sur le momentum)
      after_loss_min: 45                  # R19: réduit 60→45 (actif fiable, reprendre plus vite)
      after_streak_n: 3
      after_streak_min: 30
    # FIX 2026-02-20: ATR SL resserré (étape 1.3)
    atr_sl_mult: 1.6                      # Inchangé
    atr_tp_mult: 2.8                      # R19: augmenté 2.5→2.8 (laisser courir les winners)
    # FIX 2026-02-20: prime_hours (étape 5.5)
    prime_hours_utc:
      - {start: 13, end: 20}             # Session NY cash
    position_manager:
      max_duration_minutes: 300           # R19: augmenté 240→300 min (5h, laisser respirer)
  risk:
    risk_per_trade: 0.010                 # R19: AUGMENTÉ → 1.0% risk par trade (était implicite ~0.003)
    daily_loss_abs: 300                   # R19: kill switch augmenté 2000→300 (raisonnable pour le risk)
    max_consec_losses: 3                  # R19: pause après 3 pertes
```

**Logique** : On augmente le risk de ~0.3% (implicite global) à 1.0% pour NAS100. Avec un PF de 6.0 et 73.3% HR, chaque trade doit rapporter plus. On élargit aussi le TP (2.5→2.8) et on permet 6 trades/jour au lieu de 4.

---

## FIX 3 : VÉRIFIER/CORRIGER LE DÉPLOIEMENT LIQ_PENALTY + REVERSAL_COOLDOWN (P1 — correctif critique)
**Fichier** : `orchestrator/orchestrator.py`
**Pourquoi** : Malgré les corrections R18, `[LIQ_PENALTY]` et `[REVERSAL_COOLDOWN]` ont toujours 0 occurrences dans les logs (5.3M lignes). Le code `[ADAPTIVE_SCORE]` dans la même zone fonctionne (14,326 occ.). Cela suggère fortement que le code déployé en production ne correspond PAS au fichier local.

### 3a. TAG DE VERSION AU DÉMARRAGE — Dans la méthode `__init__()` de la classe orchestrator (ou dans le `start()`/`run()` initial), ajouter TOUT EN HAUT :
```python
        # ══════════════════════════════════════════════════════════════════════
        # R19: TAG DE VERSION — Permet de vérifier que le code déployé est le bon
        # ══════════════════════════════════════════════════════════════════════
        logger.warning(
            "═══════════════════════════════════════════════════════════════\n"
            "  ORCHESTRATOR VERSION: R19 — 2026-04-16\n"
            "  Features: ASIA_BLOCK, PROBATION, LIQ_PENALTY, REVERSAL_COOLDOWN,\n"
            "            ADAPTIVE_SCORE, SHORT_PENALTY, XAUUSD_PROBATION, NAS100_BOOST\n"
            "═══════════════════════════════════════════════════════════════"
        )
```

### 3b. LOG SYSTÉMATIQUE DANS execute_trade() — En TOUT DÉBUT de la méthode `execute_trade()`, avant toute logique, ajouter :
```python
        # ══════════════════════════════════════════════════════════════════════
        # R19: CHECKPOINT — Confirmer que le code R19 est bien celui qui s'exécute
        # ══════════════════════════════════════════════════════════════════════
        logger.debug(
            f"[R19_CHECKPOINT] {symbol}: execute_trade() appelé — "
            f"code version R19 (2026-04-16)"
        )
```

### 3c. VÉRIFICATION DU BLOC LIQ_PENALTY — Chercher le bloc `[LIQ_PENALTY]` existant (R18). S'il n'est PAS présent dans le fichier, c'est la preuve que le code déployé est ancien. Dans ce cas, AJOUTER le bloc complet (voir R18 FIX 3). S'il EST présent, ajouter un log `logger.warning` supplémentaire AVANT le if pour confirmer qu'on entre dans la zone :
```python
        # R19: Confirmation passage dans la zone LIQ_PENALTY
        logger.info(
            f"[LIQ_PENALTY_ZONE] {symbol}: entrée dans la zone LIQ_PENALTY — "
            f"hour={current_hour_utc}, crypto={symbol.upper() in self._hf_crypto_symbols}"
        )
```
→ Ce log doit apparaître AVANT le `if not _is_crypto_r17 and current_hour_utc in _liq_hours:` pour confirmer que le code est atteint.

### 3d. VÉRIFICATION DU BLOC REVERSAL_COOLDOWN — Même logique : chercher le bloc `[REVERSAL_COOLDOWN]` existant (R18). S'il est absent, AJOUTER le bloc complet (voir R18 FIX 4). S'il est présent, ajouter un log AVANT :
```python
        # R19: Confirmation passage dans la zone REVERSAL_COOLDOWN
        logger.info(
            f"[REV_COOLDOWN_ZONE] {symbol}: entrée dans la zone REVERSAL_COOLDOWN — "
            f"last_trade_result={'SET' if self._last_trade_result is not None else 'None'}"
        )
```

### 3e. COMMANDE DE VÉRIFICATION À EXÉCUTER APRÈS REDÉMARRAGE :
```bash
# Vérifier que le tag de version apparaît dans les logs au démarrage
timeout 120 tail -f orchestrator.log 2>/dev/null | grep -m 1 "ORCHESTRATOR VERSION: R19"

# Après quelques cycles (~5-10 min), vérifier les checkpoints
grep -c "R19_CHECKPOINT" orchestrator.log
grep -c "LIQ_PENALTY_ZONE" orchestrator.log
grep -c "REV_COOLDOWN_ZONE" orchestrator.log

# Si R19_CHECKPOINT = 0, le fichier déployé n'est PAS le bon.
# Dans ce cas, vérifier quel fichier Python est réellement importé :
python -c "import orchestrator.orchestrator; print(orchestrator.orchestrator.__file__)"
```

---

## FIX 4 : USDJPY EN MODE PROBATION (P2 — impact estimé +$200/6j)
**Fichier** : `config/overrides.yaml`
**Pourquoi** : USDJPY = 3 trades, 0 wins, -$241 (0% HR) en 6 jours POST-R18. Malgré LONG only et min_score 6.0. Il faut le passer en probation complète comme les crypto.

### Remplacer TOUT le bloc USDJPY dans `overrides.yaml` par :
```yaml
# ══════════════════════════════════════════════════════════════════════════════
# USDJPY — Forex — MODE PROBATION R19
# POST-R18: 3 trades, 0 wins, -$241 (0% HR). Malgré LONG only + min_score 6.0.
# ══════════════════════════════════════════════════════════════════════════════
USDJPY:
  orchestrator:
    # R19: MODE PROBATION — 0% HR, -$241 sur 6 jours
    probation: true
    allowed_directions: ["LONG"]          # R17: maintenu LONG only
    min_score_for_proposal: 7.0           # R19: monté 6.0→7.0 (probation)
    votes_required: 4                     # R19: 4 agents d'accord
    max_trades_per_day: 1                 # R19: 1 seul trade/jour
    # FIX 2026-02-20: whale_override désactivé pour non-crypto (étape 4.8)
    whale_override:
      enable: false
    position_limits:
      max_volume: 1.0
    allowed_hours_utc: [8, 9, 10, 11, 12, 13, 14, 15]  # Maintenu London+NY
    cooldown:
      enabled: true
      min_secs_between_trades: 600
      max_trades_per_day: 1               # R19: réduit à 1
      after_loss_min: 120                 # R19: 2h après perte (était 60)
      after_streak_n: 2                   # R19: pause après 2 pertes (était 3)
      after_streak_min: 2880              # R19: 48h de pause
    # FIX 2026-02-20: ATR SL resserré (étape 1.3)
    atr_sl_mult: 1.4
    atr_tp_mult: 2.5
    # FIX 2026-02-20: prime_hours (étape 5.5)
    prime_hours_utc:
      - {start: 7, end: 17}              # London + NY overlap
    position_manager:
      max_duration_minutes: 360
  risk:
    risk_per_trade: 0.001                 # R19: risque minimal absolu (0.1%)
    daily_loss_abs: 30                    # R19: kill switch $30/jour
    max_consec_losses: 2                  # R19: pause après 2 pertes
```

---

## FIX 5 : COUPER LE CHEMIN FINNHUB DANS econ_api.py (P2 — stop les 403)
**Fichier** : `utils/econ_api.py`
**Pourquoi** : `config.yaml` a `finnhub.enabled: false` mais `utils/econ_api.py` → `events_between()` → `_fetch_finnhub()` est appelé directement sans vérifier le flag `enabled`. Résultat : les appels Finnhub continuent et génèrent des 403 Forbidden.

### 5a. Modifier la méthode `events_between()` dans `utils/econ_api.py` (vers ligne 287-321) :

Chercher ce bloc :
```python
        # 2) Finnhub (source principale)
        events = _fetch_finnhub(start, end)
```

Et le remplacer par :
```python
        # 2) Finnhub (source principale) — R19: vérifier si activé dans config
        events = []
        _finnhub_enabled = True  # défaut: activé si pas de config
        try:
            import yaml
            with open("config/config.yaml", "r") as _cfg_f:
                _cfg_data = yaml.safe_load(_cfg_f)
            _finnhub_enabled = (
                _cfg_data.get("external_apis", {})
                .get("finnhub", {})
                .get("enabled", True)
            )
        except Exception:
            pass  # Si on ne peut pas lire la config, on laisse activé par défaut

        if _finnhub_enabled:
            events = _fetch_finnhub(start, end)
        else:
            logger.info(
                "[ECON_API] Finnhub désactivé dans config.yaml — skip _fetch_finnhub()"
            )
```

### 5b. ALTERNATIVE PLUS PROPRE — Si la classe `EconApi` reçoit déjà la config en paramètre ou a accès à `self.cfg`, utiliser directement :

Chercher la classe `EconApi` et sa méthode `__init__` (vers ligne 284). Modifier pour accepter la config :
```python
    def __init__(self, cfg: dict = None, **kwargs):
        self._cfg = cfg or {}
        self._finnhub_enabled = (
            self._cfg.get("external_apis", {})
            .get("finnhub", {})
            .get("enabled", True)
        )
```

Puis dans `events_between()`, remplacer l'appel direct :
```python
        # 2) Finnhub (source principale)
        if self._finnhub_enabled:
            events = _fetch_finnhub(start, end)
        else:
            logger.info("[ECON_API] Finnhub désactivé — skip")
            events = []
```

**NOTE** : Choisir l'approche 5a OU 5b selon comment `EconApi` est instancié dans le code. Si l'orchestrator passe déjà `cfg` → utiliser 5b. Sinon → utiliser 5a.

---

## RÉSUMÉ DES MODIFICATIONS

| # | Fix | Fichier(s) | Impact attendu |
|---|-----|-----------|----------------|
| 1 | XAUUSD PROBATION | overrides.yaml | +$1,200/6j (stop hémorragie, risk /2.4, LONG only) |
| 2 | NAS100 BOOST | overrides.yaml | +$300-500/6j (risk 1%, 6 trades/jour, TP élargi) |
| 3 | VÉRIF DÉPLOIEMENT | orchestrator.py | LIQ_PENALTY + REVERSAL_COOLDOWN enfin vérifiables |
| 4 | USDJPY PROBATION | overrides.yaml | +$200/6j (probation complète, risk 0.1%) |
| 5 | COUPER FINNHUB econ_api | utils/econ_api.py | Stop 403 spam, logs propres |

## VÉRIFICATION APRÈS MODIFICATION

```bash
# 1. Syntaxe Python — orchestrator
python -c "import py_compile; py_compile.compile('orchestrator/orchestrator.py', doraise=True)"

# 2. Syntaxe Python — econ_api
python -c "import py_compile; py_compile.compile('utils/econ_api.py', doraise=True)"

# 3. Syntaxe YAML config
python -c "import yaml; yaml.safe_load(open('config/config.yaml')); print('config.yaml OK')"

# 4. Syntaxe YAML overrides
python -c "import yaml; yaml.safe_load(open('config/overrides.yaml')); print('overrides.yaml OK')"

# 5. Vérifier les nouveaux paramètres
python -c "
import yaml

o = yaml.safe_load(open('config/overrides.yaml'))

print('=== R19 VÉRIFICATION ===')

# XAUUSD probation
xau = o.get('XAUUSD', {}).get('orchestrator', {})
print(f'XAUUSD: probation={xau.get(\"probation\", False)}, '
      f'min_score={xau.get(\"min_score_for_proposal\", \"DEFAULT\")}, '
      f'dirs={xau.get(\"allowed_directions\", \"ALL\")}, '
      f'max_trades={xau.get(\"max_trades_per_day\", \"DEFAULT\")}')
xau_risk = o.get('XAUUSD', {}).get('risk', {})
print(f'  risk={xau_risk.get(\"risk_per_trade\", \"DEFAULT\")}, '
      f'daily_loss={xau_risk.get(\"daily_loss_abs\", \"DEFAULT\")}')

# NAS100 boost
nas = o.get('NAS100', {}).get('orchestrator', {})
nas_risk = o.get('NAS100', {}).get('risk', {})
print(f'NAS100: min_score={nas.get(\"min_score_for_proposal\", \"DEFAULT\")}, '
      f'risk={nas_risk.get(\"risk_per_trade\", \"DEFAULT\")}, '
      f'max_trades={nas.get(\"cooldown\", {}).get(\"max_trades_per_day\", \"DEFAULT\")}')

# USDJPY probation
usd = o.get('USDJPY', {}).get('orchestrator', {})
usd_risk = o.get('USDJPY', {}).get('risk', {})
print(f'USDJPY: probation={usd.get(\"probation\", False)}, '
      f'min_score={usd.get(\"min_score_for_proposal\", \"DEFAULT\")}, '
      f'risk={usd_risk.get(\"risk_per_trade\", \"DEFAULT\")}')

# Résumé probation
for sym in ['SOLUSD', 'BNBUSD', 'LTCUSD', 'XAUUSD', 'USDJPY']:
    oc = o.get(sym, {}).get('orchestrator', {})
    rk = o.get(sym, {}).get('risk', {})
    print(f'  {sym}: probation={oc.get(\"probation\", False)}, '
          f'risk={rk.get(\"risk_per_trade\", \"?\")}')
"

# 6. Après redémarrage — vérifier le tag R19
# timeout 120 tail -f orchestrator.log 2>/dev/null | grep -m 1 "ORCHESTRATOR VERSION: R19"

echo "=== R19 APPLIQUÉ ==="
```

## IMPORTANT
- Ne PAS désactiver de symbole (`enabled: false`). On utilise le MODE PROBATION.
- XAUUSD est en probation **modérée** (risk 0.5%, 2 trades/jour, 3 votes) car c'est historiquement notre meilleur actif. Il reviendra quand la volatilité macro se calme.
- USDJPY est en probation **complète** (risk 0.1%, 1 trade/jour, 4 votes, kill $30).
- NAS100 est le **moteur principal** : risk augmenté à 1.0%, 6 trades/jour, TP élargi.
- Le FIX 3 (déploiement) est CRITIQUE : si le tag `R19` n'apparaît pas dans les logs, le fichier déployé n'est pas le bon → vérifier le chemin d'import Python.
- Le FIX 5 (Finnhub econ_api) résout le contournement du `enabled: false` dans config.yaml.
- Les logs doivent avoir des tags clairs : `[R19_CHECKPOINT]`, `[LIQ_PENALTY_ZONE]`, `[REV_COOLDOWN_ZONE]`, `[ECON_API]`
- Préserver TOUTE la logique existante — on MODIFIE les overrides et on AJOUTE des logs/guards, on ne supprime rien.

## CRITÈRES DE SORTIE DE PROBATION (pour prochain diagnostic)
| Symbole | Condition de sortie | Retour à |
|---------|-------------------|----------|
| XAUUSD | 5 wins consécutifs OU HR>60% sur 10+ trades | risk 0.008, 3 trades/jour |
| USDJPY | 5 wins consécutifs OU HR>50% sur 8+ trades | risk 0.002, 2 trades/jour |
| SOLUSD | 5 wins consécutifs | risk 0.003, 3 trades/jour |
| BNBUSD | 5 wins consécutifs | risk 0.003, 3 trades/jour |
| LTCUSD | 5 wins consécutifs | risk 0.002, 2 trades/jour |
