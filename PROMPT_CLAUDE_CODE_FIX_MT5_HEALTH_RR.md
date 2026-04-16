# PROMPT CLAUDE CODE — Fix MT5_HEALTH False Positive + R:R Trop Bas + fundamental/macro Fantômes

## Contexte

Après les fixes du 09/03 (cryptos bloquées, sémaphore, agents fantômes), le bot est 🟢 OPÉRATIONNEL mais 3 problèmes majeurs empêchent toute exécution de trade :

### Rapport du lundi 09/03/2026 (après restart 20:55 UTC)

**Symboles fonctionnels (score > 0)** : SOLUSD (10.10), SP500 (8.1), NAS100 (7.1), LTCUSD (6-7), AUDUSD (5.1)
**Symboles bloqués (score = 0)** : BTCUSD, BNBUSD, XAUUSD, USDJPY — agents=[] sur chaque cycle
**Trades exécutés** : 0 sur 6 HARD_FILTER PASS — tous rejetés par R:R < 0.80

---

## Causes racines identifiées (3 problèmes)

### Problème 1 — CRITIQUE : `_mt5_all_failed` est TOUJOURS True (faux positif)

**Fichier** : `orchestrator/orchestrator.py`, lignes ~4453-4456

Le check de santé MT5 à la ligne 4453 est :
```python
_mt5_all_failed = all(
    r is None or (isinstance(r, dict) and r.get("score") in (None, 0, 0.0))
    for r in mt5_results
)
```

**Le bug** : Les fonctions `_run_technical()`, `_run_scalping()`, `_run_swing()`, `_run_structure()` retournent des dicts avec les clés `per_tf`, `global`, `details`, `indicators`, `smc_tf`, `market` — **JAMAIS** une clé `"score"`. Donc :
- `r.get("score")` retourne **toujours** `None`
- `None in (None, 0, 0.0)` est **toujours** `True`
- `_mt5_all_failed` est **TOUJOURS** `True`, même quand les agents ont parfaitement fonctionné

**Impact catastrophique** :
- **315 reconnexions COM inutiles** le 9 mars (chaque cycle × chaque symbole)
- Chaque reconnexion fait `MC.shutdown_if_needed()` + `MC.initialize_if_needed(force=True)` DANS le sémaphore
- Le COM est constamment tué et relancé → instabilité aléatoire
- Les orchestrateurs qui passent juste après un shutdown voient leurs agents MT5 échouer → score=0
- C'est la **cause racine** du score=0 pour BTCUSD, BNBUSD, XAUUSD, USDJPY

**Preuve dans les logs** :
```
20:56:40 | [MT5_HEALTH] BTCUSD — Tous les agents MT5 ont échoué, tentative reconnexion COM
20:56:43 | [MT5_HEALTH] BTCUSD — Reconnexion MT5 réussie
20:56:54 | [SCORE_DIAG] BTCUSD: dir= score_L=0.00 score_S=0.00 conf=0.0 agents=[] globals=[]
```
Mais au MÊME moment, SOLUSD a des agents qui fonctionnent :
```
20:56:44 | [MT5_HEALTH] SOLUSD — Tous les agents MT5 ont échoué, tentative reconnexion COM  ← FAUX POSITIF !
20:57:02 | [SCORE_DIAG] SOLUSD: dir=LONG score_L=10.10 conf=4.0 agents=[technical=+2.00, swing=+3.00, structure=+1.00, smc=+3.00]
```
SOLUSD a un score de 10.10 mais le health check dit quand même "tous les agents ont échoué" !

---

### Problème 2 — fundamental/macro toujours actifs pour SP500, NAS100, et profils incomplets

**Fichier** : `config/profiles.yaml`

Le FIX du 09/03 a ajouté `fundamental: {enabled: false}` et `macro: {enabled: false}` dans **7 paires** (lignes ~105, ~152, ~199, ~251, ~297, ~344, ~711). Mais la section `agents:` du profil **SP500** (ligne 569-574) n'a PAS de clé `fundamental` ni `macro` :

```yaml
  SP500:
    agents:
      technical: {enabled: true}
      scalping: {enabled: true}
      swing: {enabled: true}
      structure: {enabled: true}
      smart_money: {enabled: true}
      # ← PAS de fundamental ni macro !
```

La fonction `agent_enabled()` (ligne 3995-4000) fait :
```python
def agent_enabled(name: str) -> bool:
    cfg = agents_cfg.get(name) or {}
    return bool(cfg.get("enabled", True))  # DEFAULT = True !
```

Quand la clé n'existe pas : `agents_cfg.get("fundamental")` → `None` → `cfg = {} ` → `cfg.get("enabled", True)` → **True**.

**Résultat** : fundamental et macro sont toujours lancés pour SP500, NAS100, et tout profil qui ne les liste pas explicitement. Preuve dans les logs :
```
20:56:01 | [AGENT] macro API timeout (15s) pour SP500
20:56:01 | [AGENT] fundamental API timeout (15s) pour SP500
20:56:26 | [AGENT] fundamental API timeout (15s) pour NAS100
20:56:26 | [AGENT] macro API timeout (15s) pour NAS100
```

22 timeouts fundamental/macro le 9 mars après le restart (soit 15s × 22 = 330s de gaspillage).

---

### Problème 3 — R:R systématiquement < 0.80 (tous les trades bloqués)

Les 6 HARD_FILTER PASS du 9 mars ont TOUS été rejetés :
```
SP500: rr(0.49)<min_rr(0.80)
NAS100: rr(0.48)<min_rr(0.80)
AUDUSD: rr(0.70)<min_rr(0.80)
USDJPY: rr(0.71)<min_rr(0.80)
SOLUSD: rr(0.40)<min_rr(0.80)
```

**Cause** : La fonction `pick_candidate()` (ligne ~4126) prend les SL/TP de l'agent prioritaire (scalping > structure > technical > swing). Quand un agent fournit SL et TP, le fallback ATR (ligne 3371 : `if sl is None or tp is None`) est IGNORÉ.

Les multiplicateurs ATR dans `overrides.yaml` donnent tous R:R > 1.0 :
- SOLUSD: tp=2.5/sl=1.5 → R:R = 1.67
- SP500: tp=2.5/sl=1.6 → R:R = 1.56
- AUDUSD: tp=2.5/sl=1.4 → R:R = 1.79

Mais ces multiplicateurs ne sont jamais utilisés car les agents fournissent leurs propres SL/TP (trop conservateurs).

---

## Corrections à appliquer (4 fixes)

### FIX 1 — CRITIQUE : Corriger le check `_mt5_all_failed`

**Fichier** : `orchestrator/orchestrator.py`

**Action** : Remplacer le check de santé MT5 (lignes ~4452-4466) par un check qui vérifie les VRAIS résultats des agents :

Chercher :
```python
                # FIX 2026-03-08: Détection freeze MT5 + auto-reconnect
                _mt5_all_failed = all(
                    r is None or (isinstance(r, dict) and r.get("score") in (None, 0, 0.0))
                    for r in mt5_results
                )
                if _mt5_all_failed and len(mt5_results) >= 2:
                    logger.warning(f"[MT5_HEALTH] {self.symbol} — Tous les agents MT5 ont échoué, tentative reconnexion COM")
                    try:
                        from utils.mt5_client import MT5Client as _MC
                        _MC.shutdown_if_needed()
                        await asyncio.sleep(3)
                        _MC.initialize_if_needed(force=True)
                        logger.info(f"[MT5_HEALTH] {self.symbol} — Reconnexion MT5 réussie")
                    except Exception as _re:
                        logger.error(f"[MT5_HEALTH] {self.symbol} — Reconnexion échouée: {_re}")
```

Remplacer par :
```python
                # FIX 2026-03-10: Détection freeze MT5 — vérifier les VRAIS résultats
                # Les agents retournent {"per_tf": {...}, "global": {...}, ...} — PAS de clé "score"
                # Un agent qui a échoué retourne soit None, soit un dict avec per_tf vide
                def _agent_result_empty(r) -> bool:
                    if r is None:
                        return True
                    if not isinstance(r, dict):
                        return True
                    # Vérifier si l'agent a produit des signaux per_tf
                    ptf = r.get("per_tf") or {}
                    gs = r.get("global") or {}
                    smc = r.get("smc_tf") or {}
                    return not ptf and not gs and not smc

                _mt5_all_failed = all(
                    _agent_result_empty(r) for r in mt5_results
                )
                if _mt5_all_failed and len(mt5_results) >= 2:
                    logger.warning(f"[MT5_HEALTH] {self.symbol} — Tous les agents MT5 ont retourné des résultats vides, tentative reconnexion COM")
                    try:
                        from utils.mt5_client import MT5Client as _MC
                        _MC.shutdown_if_needed()
                        await asyncio.sleep(3)
                        _MC.initialize_if_needed(force=True)
                        logger.info(f"[MT5_HEALTH] {self.symbol} — Reconnexion MT5 réussie")
                    except Exception as _re:
                        logger.error(f"[MT5_HEALTH] {self.symbol} — Reconnexion échouée: {_re}")
```

**Impact** : Plus de faux positifs → plus de reconnexions COM inutiles → COM stable → BTCUSD, BNBUSD, XAUUSD, USDJPY retrouvent leurs scores.

---

### FIX 2 — Changer le default de `agent_enabled()` à False pour fundamental/macro

**Fichier** : `orchestrator/orchestrator.py`

**Action** : Modifier `agent_enabled()` (lignes ~3995-4000) pour que les agents fundamental et macro soient disabled par défaut si pas dans la config du profil :

Chercher :
```python
        def agent_enabled(name: str) -> bool:
            try:
                cfg = agents_cfg.get(name) or {}
                return bool(cfg.get("enabled", True))
            except Exception:
                return True
```

Remplacer par :
```python
        # FIX 2026-03-10: fundamental/macro disabled par défaut si pas dans la config
        # Évite que les profils sans ces clés (SP500, NAS100...) les lancent
        _AGENTS_DEFAULT_DISABLED = {"fundamental", "macro"}

        def agent_enabled(name: str) -> bool:
            try:
                cfg = agents_cfg.get(name)
                if cfg is None:
                    # Agent non listé dans le profil → disabled si dans la blacklist
                    return name not in _AGENTS_DEFAULT_DISABLED
                return bool(cfg.get("enabled", True))
            except Exception:
                return True
```

**Impact** : fundamental et macro ne seront plus lancés pour SP500, NAS100, ou tout profil qui ne les liste pas explicitement. Économie : 15s × 2 agents × ~N cycles.

---

### FIX 3 — Forcer le R:R minimum via ATR quand l'agent fournit un SL/TP insuffisant

**Fichier** : `orchestrator/orchestrator.py`

**Action** : À la ligne ~3422, JUSTE APRÈS l'appel `ensure_min_distance` et AVANT le calcul des lots (ligne 3425), insérer un recalcul du TP via ATR si le R:R est insuffisant.

Chercher (ligne ~3422) :
```python
                if direction in ("LONG", "SHORT") and price is not None:
                    sl, tp = ensure_min_distance(price, sl, tp, direction)

                # Calcul lots si possible
```

Remplacer par :
```python
                if direction in ("LONG", "SHORT") and price is not None:
                    sl, tp = ensure_min_distance(price, sl, tp, direction)

                    # FIX 2026-03-10: Si le R:R agent est trop bas, recalculer TP via ATR
```

Puis ajouter ENTRE la ligne `ensure_min_distance` et `# Calcul lots si possible` :
```python
                    # FIX 2026-03-10: Si le R:R agent est trop bas, recalculer TP via ATR
                    # Les agents fournissent parfois des SL/TP trop conservateurs (R:R 0.40-0.70)
                    # Fallback: utiliser atr_tp_mult × ATR pour le TP si R:R < min_rr
                    if sl is not None and tp is not None and price and direction in ("LONG", "SHORT"):
                        try:
                            _fb_atr = atr if (atr and atr > 0) else est_atr
                            if direction == "LONG":
                                _rr_check = (tp - price) / max(price - sl, 1e-9)
                            else:
                                _rr_check = (price - tp) / max(sl - price, 1e-9)
                            if _rr_check < self._hf_min_rr and _fb_atr > 0:
                                # Recalculer SEULEMENT le TP pour atteindre min_rr
                                _desired_tp_dist = abs(price - sl) * self._hf_min_rr
                                _atr_tp_dist = mul_tp * _fb_atr
                                _new_tp_dist = max(_desired_tp_dist, _atr_tp_dist)
                                if direction == "LONG":
                                    tp = price + _new_tp_dist
                                else:
                                    tp = price - _new_tp_dist
                                _new_rr = _new_tp_dist / max(abs(price - sl), 1e-9)
                                logger.info(f"[RR_FIX] {symbol}: R:R {_rr_check:.2f} → {_new_rr:.2f} (TP recalculé via ATR)")
                        except Exception as _rr_e:
                            logger.debug(f"[RR_FIX] {symbol}: erreur recalcul: {_rr_e}")
```

**Important** : Ce code doit être APRÈS `ensure_min_distance` mais AVANT que `sl` et `tp` soient utilisés pour construire la proposal/le trade. Il ne modifie que le TP, pas le SL (pour préserver la gestion du risque).

**Impact** : Les trades avec R:R > 0.80 (grâce au TP ATR) seront exécutés au lieu d'être systématiquement rejetés.

---

### FIX 4 — Ajouter fundamental/macro disabled dans TOUS les profils manquants de profiles.yaml

**Fichier** : `config/profiles.yaml`

**Action** : Chercher TOUS les blocs `agents:` qui n'ont PAS `fundamental: {enabled: false}` et `macro: {enabled: false}`, et les ajouter.

Les profils déjà fixés (7 paires) sont aux lignes ~105, ~152, ~199, ~251, ~297, ~344, ~711. Mais les profils suivants manquent probablement ces entrées :

- **SP500** (ligne ~569-574)
- **NAS100** (chercher sa section agents)
- **UK100** (même si disabled, par sécurité)
- Tout autre profil qui a une section `agents:` sans fundamental/macro

Pour chacun, ajouter sous la section `agents:` :
```yaml
      fundamental: {enabled: false}  # FIX 2026-03-10: Finnhub 403
      macro: {enabled: false}         # FIX 2026-03-10: Finnhub 403
```

**Vérification** : Après modification, lancer :
```bash
python -c "
import yaml
with open('config/profiles.yaml') as f:
    data = yaml.safe_load(f)
for sym, cfg in data.get('profiles', {}).items():
    agents = (cfg.get('agents') or {})
    f_en = agents.get('fundamental', {}).get('enabled', 'NOT_SET')
    m_en = agents.get('macro', {}).get('enabled', 'NOT_SET')
    if f_en != False or m_en != False:
        print(f'WARN: {sym} fundamental={f_en} macro={m_en}')
"
```
Ne doit rien afficher (tous les profils doivent avoir `False`).

---

## Résumé des modifications

| # | Fichier | Modification | Impact |
|---|---------|-------------|--------|
| 1 | orchestrator.py ~4452-4466 | Fix `_mt5_all_failed` : vérifier `per_tf`/`global`/`smc_tf` vides au lieu de `r.get("score")` | Plus de faux positifs → COM stable → BTCUSD/BNBUSD/XAUUSD/USDJPY retrouvent leurs scores |
| 2 | orchestrator.py ~3995-4000 | `agent_enabled()` : default disabled pour fundamental/macro | Plus de timeouts pour SP500/NAS100 |
| 3 | orchestrator.py ~3425 | Recalcul TP via ATR si R:R < min_rr | Trades exécutés au lieu d'être tous rejetés |
| 4 | profiles.yaml | Ajouter fundamental/macro disabled dans tous les profils manquants | Ceinture+bretelles avec FIX 2 |

## Impact attendu

- **BTCUSD, BNBUSD, XAUUSD, USDJPY retrouvent des scores > 0** : le COM n'est plus constamment redémarré
- **0 reconnexion COM inutile** au lieu de 315/jour : stabilité MT5 maximale
- **Les trades passent enfin** : le TP est recalculé via ATR quand l'agent fournit un R:R insuffisant
- **fundamental/macro ne se lancent plus pour aucun symbole** : 0 timeout Finnhub

## Vérification après modification

1. `python -m py_compile orchestrator/orchestrator.py` → doit passer
2. Redémarrer le bot via `START_EMPIRE.bat`
3. Attendre **5 minutes** et vérifier dans les logs :
   - `[MT5_HEALTH]` n'apparaît **PAS** (ou très rarement, seulement en cas de vrai freeze)
   - BTCUSD, BNBUSD, XAUUSD, USDJPY montrent des `agents=[technical, swing, structure, smc]` dans SCORE_DIAG
   - Plus AUCUN `[AGENT] fundamental API timeout` ou `macro API timeout`
   - Des `[RR_FIX]` apparaissent quand le TP est recalculé
   - Des `[HARD_FILTER] PASS` suivis d'exécution de trade (pas de rejet R:R)
