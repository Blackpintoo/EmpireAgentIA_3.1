# D13 — Diagnostic retcode 10016 et fix proposé

**Date** : 2026-05-19
**Périmètre** : LTCUSD, SOLUSD, BNBUSD
**Tag de sauvegarde** : `pre-phase3-2026-05-19` sur commit `46fda18` (HEAD courant)
**État** : aucune modification appliquée — proposition pour relecture humaine

---

## D13.1 — Diagnostic exact

### Données broker (`mt5.symbol_info`) au 2026-05-19

| Symbole | point  | digits | trade_stops_level | trade_freeze_level | spread (pts) | spread (USD) |
|---------|--------|--------|-------------------|---------------------|--------------|--------------|
| LTCUSD  | 0.01   | 2      | **0**             | 0                   | **103**      | **1.03**     |
| SOLUSD  | 0.01   | 2      | **0**             | 0                   | 54           | 0.54         |
| BNBUSD  | 0.01   | 2      | **0**             | 0                   | 273          | 2.73         |
| BTCUSD (réf.) | 0.01 | 2  | 0                 | 0                   | 1 706        | 17.06        |

**Observation critique** : `trade_stops_level = 0` sur les 3 cryptos. Le filtre
"distance broker minimum × point" tel que formulé dans le brief produit donc
`0 × point = 0` — il n'apporte aucune contrainte. **La cause réelle du retcode
10016 n'est pas `trade_stops_level`**, mais le **spread bid-ask**.

### Distance SL proposée (proposals_log, fenêtre 2026-05-01 → 2026-05-19)

| Symbole | n props | min    | p25    | médiane | p75    | max     | moyenne |
|---------|---------|--------|--------|---------|--------|---------|---------|
| LTCUSD  | 1 307   | 0.500  | 0.500  | **0.559** | 0.631 | 1.127   | 0.586   |
| SOLUSD  | 1 812   | 0.500  | 0.856  | **1.008** | 1.188 | 2.794   | 1.017   |
| BNBUSD  | 1 201   | 0.518  | 3.089  | **4.689** | 5.979 | 14.824  | 4.437   |

Comparaison médiane proposée vs spread broker :

| Symbole | Médiane SL_dist | Spread broker | Marge        | Risque retcode 10016 |
|---------|-----------------|---------------|--------------|----------------------|
| LTCUSD  | 0.56 USD        | **1.03 USD**  | **−0.47**    | **CRITIQUE** (SL < spread) |
| SOLUSD  | 1.01 USD        | 0.54 USD      | +0.47        | OK                   |
| BNBUSD  | 4.69 USD        | 2.73 USD      | +1.96        | OK                   |

### Forensic des 20 échecs retcode 10016 LTCUSD (fenêtre observation)

Cross-référence trade attempt vs barre M1 du marché à l'instant de l'envoi :

| Date / heure        | side | sent_sl   | M1 close  | (sent_sl − close)  | Verdict        |
|---------------------|------|-----------|-----------|--------------------|----------------|
| 2026-05-01 15:14    | LONG | 55.700    | 54.71     | **+0.99**          | SL au-dessus du marché |
| 2026-05-01 16:00    | LONG | 55.710    | 54.80     | +0.91              | idem           |
| 2026-05-01 16:40    | LONG | 55.640    | 54.85     | +0.79              | idem           |
| 2026-05-04 08:11    | LONG | 55.848    | 55.64     | +0.21              | idem           |
| 2026-05-08 15:35    | LONG | 57.150    | 56.21     | +0.94              | idem           |
| 2026-05-11 16:41    | LONG | 58.949    | 57.92     | +1.03              | idem           |
| 2026-05-14 15:59    | LONG | 58.012    | 56.78     | +1.23              | idem           |
| *(13 autres similaires)* | LONG | …    | …         | +0.21 à +1.36      | idem           |
| **2026-05-06 16:11** | LONG | 57.031   | 57.12     | **−0.089**         | SL juste sous close, mais à l'intérieur du spread |

**Conclusion** : sur 20 / 20 échecs, le SL envoyé est soit **au-dessus** du prix
de marché courant, soit **moins de 9 cents en dessous** (donc à l'intérieur
du spread `1.03 USD`). Pour un ordre LONG, MT5 exige `SL < BID − stops_level`
(et utilise le spread comme buffer minimum implicite). Le retcode 10016 est
donc déclenché par **un SL placé dans la zone bid-ask**, pas par un
`trade_stops_level` insuffisant.

### Origine du SL invalide

Le code d'`execute_trade` (orchestrator.py:3120-3170) applique `ENTRY_REFRESH`
qui recompose `new_sl = new_entry − sl_dist` à partir du `tick.ask` courant
(pour BUY). Si la proposition avait `sl_dist = 0.5 USD` et que `tick.ask = 56.20`,
le nouveau `sl = 55.70`. Mais `tick.bid = ask − spread = 56.20 − 1.03 = 55.17`.

Résultat : `sl = 55.70` se retrouve **entre BID (55.17) et ASK (56.20)**.
Pour MT5 qui valide les stops contre le BID en BUY, c'est un SL au-dessus du
prix de référence → **retcode 10016**.

La cause racine : **l'orchestrator calcule le SL relativement au ASK mais MT5
le valide contre le BID, sans tenir compte du spread du symbole**. La garde
`DIR_CHECK` (orchestrator.py:3175-3187) ne détecte pas le problème parce qu'elle
compare `sl` au `entry` interne (≈ ask), pas au BID réel.

---

## D13.2 — Correction proposée

### Choix 1 — Garde explicite dans le code (recommandé)

**Emplacement** : `orchestrator/orchestrator.py` immédiatement **après** le
bloc `ENTRY_REFRESH` (ligne 3171) et **avant** le bloc `DIR_CHECK` (ligne 3175).

**Patch proposé** (à appliquer dans une nouvelle modification, **pas committé
encore**) :

```python
# ═══════════════════════════════════════════════════════════════
# FIX 2026-05-19 D13: Garde SL — distance min = max(stops_level, spread) × safety
# Protège contre retcode 10016 quand le SL proposé tombe dans la zone bid-ask
# (cas observé sur LTCUSD : spread 103 pts = $1.03, SL_dist 50 pts = $0.50)
# ═══════════════════════════════════════════════════════════════
try:
    if _mt5 and entry and sl and tp:
        _si = _mt5.symbol_info(broker_symbol)
        _tick = _mt5.symbol_info_tick(broker_symbol)
        if _si and _tick:
            _stops_pts = int(getattr(_si, "trade_stops_level", 0) or 0)
            _spread_pts = int(getattr(_si, "spread", 0) or 0)
            _point = float(getattr(_si, "point", 0.0) or 0.0)
            # Marge minimum = max(stops_level, spread) × safety_factor
            _safety_factor = 1.5
            _min_dist = max(_stops_pts, _spread_pts) * _safety_factor * _point

            if _min_dist > 0:
                if action == "BUY":
                    _ref = float(_tick.bid)            # SL doit clear le BID
                    _sl_floor = _ref - _min_dist       # SL maximum admissible
                    if sl > _sl_floor:
                        _old_sl, _old_tp = sl, tp
                        _sl_dist_old = abs(entry - sl) if sl else _min_dist
                        _tp_dist_old = abs(tp - entry) if tp else _min_dist
                        sl = _sl_floor
                        # Préserve le R:R en élargissant TP proportionnellement
                        _new_sl_dist = abs(entry - sl)
                        if _sl_dist_old > 0:
                            _scale = _new_sl_dist / _sl_dist_old
                            tp = entry + _tp_dist_old * _scale
                        logger.warning(
                            f"[SL_GUARD] {symbol} BUY: SL trop serré "
                            f"(spread {_spread_pts}pts, stops {_stops_pts}pts). "
                            f"SL {_old_sl:.{int(_si.digits)}f}->{sl:.{int(_si.digits)}f} ; "
                            f"TP {_old_tp:.{int(_si.digits)}f}->{tp:.{int(_si.digits)}f}"
                        )
                else:  # SELL
                    _ref = float(_tick.ask)            # SL doit clear le ASK
                    _sl_floor = _ref + _min_dist
                    if sl < _sl_floor:
                        _old_sl, _old_tp = sl, tp
                        _sl_dist_old = abs(entry - sl) if sl else _min_dist
                        _tp_dist_old = abs(tp - entry) if tp else _min_dist
                        sl = _sl_floor
                        _new_sl_dist = abs(entry - sl)
                        if _sl_dist_old > 0:
                            _scale = _new_sl_dist / _sl_dist_old
                            tp = entry - _tp_dist_old * _scale
                        logger.warning(
                            f"[SL_GUARD] {symbol} SELL: SL trop serré "
                            f"(spread {_spread_pts}pts, stops {_stops_pts}pts). "
                            f"SL {_old_sl:.{int(_si.digits)}f}->{sl:.{int(_si.digits)}f} ; "
                            f"TP {_old_tp:.{int(_si.digits)}f}->{tp:.{int(_si.digits)}f}"
                        )
except Exception as _sl_guard_err:
    logger.debug(f"[SL_GUARD] erreur: {_sl_guard_err}")
```

**Effet attendu** :
- LTCUSD : SL élargi à `bid − 1.5 × 1.03 ≈ bid − 1.55 USD`. Pour `bid = 54.7`
  cela donne `sl = 53.15`. Le SL_dist passe de 0.5 USD à ~1.55 USD (+3x).
  Le R:R est préservé (TP élargi proportionnellement).
- SOLUSD / BNBUSD : aucun changement car `SL_dist > spread × 1.5` déjà.
- Effet de bord : le sizing risk-based produira automatiquement un lot
  plus petit pour LTCUSD (1.55 USD risque vs 0.5 USD avant) → réduction
  du risque absolu pour ce symbole, ce qui est cohérent avec sa probation.

### Choix 2 — Ajustement statique de `atr_sl_mult` dans `overrides.yaml`

**Modification proposée** (sans commit) :

```yaml
LTCUSD:
  orchestrator:
    atr_sl_mult: 4.0    # 2026-02-20: 2.5→1.5 (insuffisant) → D13 2026-05-19: 1.5→4.0
                        # Distance min calibrée pour clear spread $1.03 avec safety 1.5x

SOLUSD:
  orchestrator:
    atr_sl_mult: 2.25   # SHADOW: 1.5→2.25 (cohérent avec D15)

BNBUSD:
  orchestrator:
    atr_sl_mult: 2.25   # SHADOW: 1.5→2.25 (cohérent avec D15)
```

**Limites de cette approche seule** :
- Ne protège pas contre une augmentation future du spread broker (volatilité).
- Modifie le profil de risque sans diagnostic (mauvais design).
- Casse l'idée de "distance SL = f(ATR)" en la remplaçant par "distance SL =
  constante calibrée broker-spécifique".

### Recommandation D13

**Choix 1 + Choix 2** en combinaison :
1. Appliquer le patch `[SL_GUARD]` dans `orchestrator.py` → fix structurel,
   adaptatif au broker, protection contre régressions spread.
2. Relever `atr_sl_mult` LTCUSD à `3.0` (au lieu de `4.0` proposé en Choix 2) →
   défense en profondeur, réduit la fréquence d'activation du `SL_GUARD` et
   maintient une cohérence ATR-basée pour le sizing.
3. Pour BNBUSD/SOLUSD : pas de modification de `atr_sl_mult` à ce stade
   (le sujet est traité distinctement en D15 selon les conclusions Phase 3).

**Justification du choix `atr_sl_mult: 3.0` pour LTCUSD** : médiane actuelle
SL_dist = 0.56 USD avec `atr_sl_mult: 1.5`. Multiplier par 2 (à `3.0`) donne
une médiane ~1.12 USD, soit légèrement supérieure au spread broker `1.03 USD`.
Le `SL_GUARD` reste actif pour les cas où la médiane ne suffit pas (volatilité
réduite, propositions très serrées), mais déclenche moins souvent.

---

## Points de validation humaine requis

Avant tout `git add` :

1. **Approbation du patch `[SL_GUARD]`** dans `orchestrator/orchestrator.py`
   (~50 lignes ajoutées entre lignes 3171 et 3175). Aucune autre modification
   n'est nécessaire dans ce fichier.
2. **Approbation du changement `atr_sl_mult: 1.5 → 3.0` pour LTCUSD** dans
   `config/overrides.yaml` ligne 242. Aucun autre symbole modifié.
3. **Validation que SOLUSD/BNBUSD restent intouchés en D13** (à reprendre en D15
   selon le verdict du rapport d'audit).
4. **Pas de modification de `config/profiles.yaml`** (les commentaires de
   profil ne reflètent pas `atr_sl_mult` qui vit dans overrides).

## Note importante : LTCUSD reste en `enabled: true` mais `probation: true`

Le sujet D13 corrige uniquement le bug de SL invalide. Il ne traite pas
la performance fondamentale du symbole (probation R18, 0 % HR sur les
14 jours pré-fenêtre). À la sortie du patch, si LTCUSD continue à perdre
même avec SL valides, sa désactivation pourrait devenir une option à
considérer (sujet à porter dans le plan Phase 3 si pertinent).

---

**Fin du diagnostic D13. Aucune action git effectuée. Prêt pour relecture.**
