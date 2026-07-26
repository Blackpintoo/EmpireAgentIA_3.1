# PROMPT CLAUDE CODE — Fix Opérationnel (Round 13)

## Contexte

Le tracker fonctionne parfaitement (21 clôtures en 48h, R12 résolu). Le problème #1 est maintenant les **TP aberrants** qui détruisent le P&L.

Diagnostic du 17 mars :
- ❌ TP à 0.5-1 point de l'entry malgré le RR_FIX et RR_SAFETY
- Exemples : SP500 BUY 6751.86 → TP 6752.86 (1 pt) avec SL à 92 pts → RR=0.01
- Impact : 5 TP gagnants = +$51 total vs 2 SL perdants = -$757. P&L jour = -$428
- RR_FIX corrige 699 fois via ATR mais le TP final à MT5 est quand même aberrant
- ❌ RISK_CAP bypass : LTCUSD à $1,360 de risque (5.0 lots) malgré le cap de $300

**2 problèmes critiques + 1 ajustement :**

---

## INVESTIGATION 1 — Tracer le TP de bout en bout ⭐⭐ CRITIQUE

### Ce qu'on sait

Le flow du TP est :
1. **`_run_agents_and_decide`** : les agents calculent un TP → `RR_FIX` (ligne ~3572-3592) corrige via ATR si R:R trop bas → TP stocké dans le proposal dict
2. **`execute_trade`** : lit `tp = float(p["tp"])` (ligne ~2065) → Composite optimization PEUT modifier tp (lignes ~2333-2350) → `RR_SAFETY` (lignes ~2579-2631) corrige si R:R < 0.80 → `RISK_CAP` → appel `place_order`
3. **`place_order`** dans `mt5_client.py` : appelle `_respect_min_stops()` (lignes ~828-861) qui PEUT écraser le TP → construit la requête MT5 → `order_send()`

**Le problème** : le TP corrigé par RR_SAFETY ne semble pas arriver à MT5. Hypothèses :
- **H1** : L'appel `place_order()` utilise `p["tp"]` (proposal original) au lieu de `tp` (variable locale corrigée)
- **H2** : Le Composite Score Optimization (lignes ~2333-2350) écrase le TP avec une valeur aberrante APRÈS le RR_FIX mais AVANT le RR_SAFETY, et le RR_SAFETY rate la correction à cause d'une exception silencieuse
- **H3** : `_respect_min_stops()` dans `place_order` écrase le TP corrigé

### Action requise (INVESTIGATION)

**ÉTAPE 1** : Trouver l'appel exact à `place_order()` dans `execute_trade` (vers la ligne ~2667 ou après le bloc RISK_CAP). Examiner les paramètres passés.

Vérifier si le TP passé est :
- `tp` (variable locale → correct, inclut les corrections RR_SAFETY)
- `float(p["tp"])` ou `p.get("tp")` (proposal → INCORRECT, ignore les corrections)
- Ou autre

**Si le TP passé est `p["tp"]`** (hypothèse H1 confirmée), c'est la cause racine.

**ÉTAPE 2** : Examiner `_respect_min_stops()` dans `utils/mt5_client.py` (lignes ~828-861). Vérifier si cette méthode peut écraser un TP valide (éloigné de l'entry).

**ÉTAPE 3** : Examiner les lignes entre le RR_SAFETY (fin ligne ~2631) et l'appel `place_order`. Y a-t-il UNE SEULE assignation `tp = ...` qui écraserait la correction ?

---

## FIX 1 — S'assurer que le TP corrigé arrive à `place_order` ⭐⭐ CRITIQUE

### Correction dépend de l'investigation ci-dessus

**Si H1 confirmée** (place_order utilise `p["tp"]` au lieu de `tp`) :

Modifier l'appel `place_order()` pour utiliser la variable locale `tp` (et `sl`, `lots`) qui contiennent les valeurs corrigées par RR_SAFETY et RISK_CAP :

```python
# AVANT (buggy):
result = self.mt5_client.place_order(
    ...
    sl=float(p["sl"]),   # proposal original
    tp=float(p["tp"]),   # proposal original → ABERRANT
    ...
)

# APRÈS (corrigé):
result = self.mt5_client.place_order(
    ...
    sl=sl,    # variable locale corrigée par RR_SAFETY
    tp=tp,    # variable locale corrigée par RR_SAFETY + RISK_CAP
    ...
)
```

**Si H2 confirmée** (Composite optimization écrase le TP) :

Déplacer le bloc Composite optimization AVANT le RR_SAFETY, ou ajouter un check RR après le Composite. Le RR_SAFETY doit être le DERNIER à toucher au TP.

**Si H3 confirmée** (`_respect_min_stops` écrase le TP) :

Modifier `_respect_min_stops` pour ne PAS toucher au TP quand il est correctement éloigné de l'entry. Le TP ne doit être ajusté que s'il viole le minimum broker (ce qui ne devrait pas arriver avec un TP valide).

### Ajout de logging diagnostique (DANS TOUS LES CAS)

Ajouter un log WARNING juste AVANT l'appel `place_order` dans `execute_trade` :

```python
# FIX 2026-03-17 R13: Diagnostic TP avant order_send
logger.warning(
    f"[TP_TRACE] {symbol} {action}: entry={entry}, sl={sl}, tp={tp}, lots={lots}, "
    f"proposal_tp={float(p.get('tp', 0))}, "
    f"rr_final={abs(tp - entry) / max(abs(entry - sl), 1e-9):.3f}"
)
```

Et dans `place_order` de `mt5_client.py`, APRÈS `_respect_min_stops` :

```python
# FIX R13: Diagnostic _respect_min_stops
if adj_tp != tp:
    logger.warning(
        f"[MIN_STOPS] {symbol}: TP modifié par _respect_min_stops: "
        f"{tp} → {adj_tp} (base_price={base_price}, min_dist={min_dist})"
    )
```

**Résultat** : On saura exactement OÙ le TP est écrasé et on pourra corriger définitivement.

---

## FIX 2 — RISK_CAP : corriger le calcul du point_value ⭐ IMPORTANT

### Cause racine

Le RISK_CAP (R9) calcule le risque en USD avec `_point_val`. Si `mt5.symbol_info()` échoue (exception silencieuse), `_point_val` reste à **1.0** (défaut). Pour les cryptos comme LTCUSD, la vraie valeur est beaucoup plus élevée. Résultat : le risque calculé est ~100x plus petit que le risque réel, et le cap n'est jamais atteint.

Le `except Exception: pass` à la ligne ~2648 avale silencieusement l'erreur.

### Solution

**Fichier** : `orchestrator/orchestrator.py`

Chercher dans le bloc RISK_CAP (vers la ligne ~2638-2649), le bloc try/except qui récupère le symbol_info :

```python
                    _point_val = 1.0
                    try:
                        if _mt5:
                            _sym_info = _mt5.symbol_info(broker_symbol)
                            if _sym_info:
                                _ts = getattr(_sym_info, "trade_tick_size", 0)
                                _tv = getattr(_sym_info, "trade_tick_value", 0)
                                if _ts > 0 and _tv > 0:
                                    _point_val = _tv / _ts
                    except Exception:
                        pass
```

Remplacer par :
```python
                    _point_val = 1.0
                    _sym_info = None
                    try:
                        if _mt5:
                            _sym_info = _mt5.symbol_info(broker_symbol)
                            if _sym_info:
                                _ts = getattr(_sym_info, "trade_tick_size", 0)
                                _tv = getattr(_sym_info, "trade_tick_value", 0)
                                if _ts > 0 and _tv > 0:
                                    _point_val = _tv / _ts
                    except Exception as _pv_err:
                        logger.warning(f"[RISK_CAP] symbol_info({broker_symbol}) échoué: {_pv_err}")

                    # FIX 2026-03-17 R13: Alerte si point_value reste au défaut
                    if _point_val == 1.0:
                        logger.warning(
                            f"[RISK_CAP] {symbol}: _point_val=1.0 (défaut) — "
                            f"risque possiblement sous-estimé. "
                            f"sym_info={'OK' if _sym_info else 'None'}"
                        )
                        # Fallback conservateur pour les cryptos : bloquer si lots > 1.0
                        if symbol.endswith("USD") and lots > 1.0:
                            _risk_usd = _max_risk_usd + 1  # Forcer le cap
                            logger.warning(
                                f"[RISK_CAP] {symbol}: point_val inconnu + {lots:.2f} lots "
                                f"→ forçage cap à {_max_risk_usd}$"
                            )
```

**Résultat** :
- Les erreurs de symbol_info sont maintenant loggées (plus de silence)
- Si `_point_val` reste à 1.0, un warning apparaît
- Pour les cryptos (symbole finissant par "USD") avec > 1.0 lot et point_value inconnu, le cap est forcé par précaution

---

## FIX 3 — HARD_FILTER : remonter min_score de 3.5 à 3.8

### Problème

Taux de rejet de 35% (251 REJECT / 460 PASS) — en-dessous de la cible 40-70%. Trop de signaux faibles passent.

### Solution

**Fichier** : `config/config.yaml`

Chercher :
```yaml
    min_score: 3.5                     # FIX 2026-03-15 R12: 4.0→3.5 (77% rejet, cible 40-70%)
```

Remplacer par :
```yaml
    min_score: 3.8                     # FIX 2026-03-17 R13: 3.5→3.8 (35% rejet, cible 40-70%)
```

---

## Résumé des 3 fixes

| Fix | Fichier(s) | Criticité | Impact |
|-----|-----------|-----------|--------|
| 1 | `orchestrator/orchestrator.py` + `utils/mt5_client.py` | ⭐⭐ CRITIQUE | TP corrigé arrive à MT5 → P&L transformé |
| 2 | `orchestrator/orchestrator.py` | ⭐ IMPORTANT | RISK_CAP fonctionne pour crypto → plus de $1,360 |
| 3 | `config/config.yaml` | AJUSTEMENT | 35% → ~50% rejet |

## Vérification

```bash
python -m py_compile orchestrator/orchestrator.py
python -m py_compile utils/mt5_client.py
```

## Vérification en production

### Test critique (après 1-2 trades) :

1. **[TP_TRACE]** dans les logs : vérifier que `tp` (variable locale) ≠ `proposal_tp` quand le RR_SAFETY corrige. Et que `rr_final` > 0.80.

2. **[MIN_STOPS]** dans les logs : vérifier si `_respect_min_stops` modifie le TP. Si oui, noter de combien.

3. **Sur le premier trade** : vérifier dans MT5 que le TP est éloigné de l'entry (>= SL distance × min_rr). Si le TP est encore à 0.5-1 point : le problème est AVANT le [TP_TRACE] et les logs aideront à identifier la cause exacte.

4. **[RISK_CAP]** : chercher `point_val=1.0 (défaut)` ou `forçage cap`. Si présent → le fallback fonctionne.

## RÈGLES

1. **L'INVESTIGATION (FIX 1) est prioritaire.** Commence par tracer le TP dans le code. Identifie laquelle des 3 hypothèses (H1, H2, H3) est la bonne, puis corrige.
2. **Ajoute les logs diagnostiques** MÊME SI tu trouves et corriges la cause — on pourra vérifier en production.
3. **Compile chaque fichier.**
4. **Si la cause est dans `place_order`** (`_respect_min_stops`), fais attention à ne pas casser le mécanisme de protection broker — il doit continuer à empêcher les SL/TP en-dessous du minimum broker.
