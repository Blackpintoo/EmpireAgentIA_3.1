# PROMPT CLAUDE CODE — Fix Round 16 (Spam Order + Momentum Streak + Cleanup)

## Contexte

Round 15 est un succès : hit rate 22% → 33%, P&L -$668 → -$445, 46 trades bloqués par momentum, 22 bloqués par cooldown QR. Tous les 5 fixes R15 sont actifs et fonctionnels.

**Diagnostic du 24 mars 2026 — 3 problèmes identifiés :**

1. **❌ BUG CRITIQUE — SP500 ORDER_SEND SPAM** : 67 ordres identiques `SP500 BUY vol=1.0 price=6604.98` envoyés entre 10:01 et 13:13 (toutes les 2 min pendant ~3 heures). Le même prix exact sans ENTRY_REFRESH → stale proposal. Le bot retente le même ordre à chaque cycle de `_run_agents_and_decide` (toutes les 2 min) sans vérifier que l'ordre précédent a déjà échoué ou que la position est déjà ouverte. **Risque : fills multiples si le broker accepte soudainement.**

2. **⚠️ Momentum "net neutre" trop permissif** : XAUUSD a eu 14 blocages INVERSE consécutifs, puis 1 pass "net neutre" → SL en 7 min (-$297.50). Quand un symbole a été bloqué N fois de suite par momentum, le critère "net neutre → PASS" est dangereux.

3. **⚠️ RISK_CAP alerte faux-positif** : le log `_point_val=1.0 (défaut) — risque possiblement sous-estimé` se déclenche APRÈS l'override indices car le test `if _point_val == 1.0` ne distingue pas "1.0 par défaut" de "1.0 override correct".

**3 fixes à appliquer :**

---

## FIX 1 — Anti-Spam ORDER_SEND ⭐⭐⭐ CRITIQUE

### Analyse du bug

Le cycle est :
1. `_run_agents_and_decide` s'exécute toutes les 2 minutes
2. Les agents calculent la même direction (ex: BUY SP500)
3. `_last_proposal` est écrasé avec un **nouveau `expires_at`** (TTL frais)
4. `execute_trade` est appelé
5. L'anti-spam `_trade_gate_ok` DEVRAIT bloquer (min 300s entre trades, max 5/heure)
6. **MAIS** soit le gate est contourné, soit l'ORDER_SEND échoue au broker (retcode != DONE) et `_last_exec_ts` n'est pas mis à jour → le gate ne voit pas de trade précédent

### Cause probable

Quand l'ORDER_SEND échoue (ex: `retcode=10016` marché fermé, ou prix trop éloigné), le code ne met pas à jour `_last_exec_ts` → le gate `_trade_gate_ok` autorise le prochain cycle → boucle infinie de tentatives.

**Il y a aussi un problème fondamental** : `_last_proposal` n'est JAMAIS remis à `None` après exécution. Si le même signal revient au cycle suivant, un nouveau `_last_proposal` avec TTL frais est créé, et `execute_trade` est re-appelé.

### Solution — 3 gardes complémentaires

**Fichier** : `orchestrator/orchestrator.py`

#### 1a — Effacer `_last_proposal` après consommation

Dans `execute_trade`, APRÈS la ligne qui lit le payload `p = self._last_proposal` (vers ligne ~2072), ajouter immédiatement :

```python
        p = self._last_proposal
        self._last_proposal = None  # FIX R16: Consommer la proposal (empêche re-exécution)
```

Cela garantit qu'une proposal ne peut être exécutée qu'UNE SEULE FOIS. Au prochain cycle, si `_last_proposal` est `None`, le check `if not self._last_proposal` (ligne ~2039) rejettera l'exécution.

**ATTENTION** : vérifier que `_last_proposal = None` est AUSSI mis dans les branches d'échec (return False après TTL expirée, etc.) — sinon le proposal reste en mémoire après un rejet. En fait, le plus simple est de mettre `self._last_proposal = None` JUSTE APRÈS `p = self._last_proposal`, avant tout check. Comme ça `p` contient les données, mais `_last_proposal` est vidé quoi qu'il arrive.

#### 1b — Guard : pas de doublon si position déjà ouverte sur le même symbole/même direction

Dans `execute_trade`, APRÈS le cooldown QR check (ligne ~2033) et AVANT la lecture de `_last_proposal` (ligne ~2039), ajouter :

```python
        # FIX 2026-03-24 R16: Anti-spam — pas de nouveau trade si position déjà ouverte même symbole
        try:
            if _mt5 is not None:
                _existing_pos = _mt5.positions_get(symbol=canon_to_broker(symbol) or self.broker_symbol)
                if _existing_pos and len(_existing_pos) > 0:
                    logger.info(
                        f"[ANTI_SPAM] {symbol}: {len(_existing_pos)} position(s) déjà ouverte(s) "
                        f"→ pas de nouvel ordre"
                    )
                    return False
        except Exception as _asp_err:
            logger.debug(f"[ANTI_SPAM] {symbol}: check échoué ({_asp_err}) — PASS")
```

**Note** : cela bloque un 2e trade sur le même symbole tant qu'une position est ouverte. Si le bot doit pouvoir ouvrir plusieurs positions par symbole (pyramiding), conditionner par la direction :
```python
                    # Vérifier si même direction
                    for _ep in _existing_pos:
                        _ep_type = int(getattr(_ep, "type", -1))
                        _ep_dir = "BUY" if _ep_type == 0 else "SELL"
                        if _ep_dir == action:
                            logger.info(f"[ANTI_SPAM] {symbol}: position {_ep_dir} déjà ouverte → skip")
                            return False
```

Choisir l'option la plus conservatrice (bloquer tout doublon) sauf si le bot est configuré pour pyramider.

#### 1c — Guard : `_last_exec_ts` mis à jour même en cas d'échec ORDER_SEND

Chercher l'endroit où `_last_exec_ts` est mis à jour (ligne ~2903). Vérifier qu'il est AUSSI mis à jour quand l'ORDER_SEND échoue (retcode != DONE). Si ce n'est pas le cas, ajouter la mise à jour dans la branche d'échec :

```python
            # FIX R16: Marquer le timestamp même en cas d'échec
            # pour empêcher le gate de re-tenter dans les 300s
            self._last_exec_ts = datetime.now(timezone.utc)
```

Chercher le bloc qui gère les retcodes d'échec (probablement vers les lignes ~2860-2880, après `order_send`). Ajouter le `_last_exec_ts` dans la branche `else` (échec).

---

## FIX 2 — Momentum Anti-Streak ⭐⭐ IMPORTANT

### Problème

Le filtre momentum a un mode "net neutre → PASS" qui laisse passer des trades quand le momentum est faible mais pas clairement inverse. Le problème : après 14 blocages INVERSE consécutifs sur XAUUSD BUY, le 15e pass a causé un SL en 7 min (-$297.50).

Quand un symbole/direction a été bloqué N fois de suite par le momentum, il faut durcir le critère.

### Solution

Ajouter un compteur de blocages consécutifs par symbole/direction. Si > 3 blocages INVERSE consécutifs, **bloquer aussi les "net neutre → PASS"** pendant 15 minutes.

**Fichier** : `orchestrator/orchestrator.py`

#### 2a — Compteur streak (niveau module ou dans __init__)

Ajouter un dict au niveau module (près des autres dicts globaux comme `_QR_COOLDOWNS`) :

```python
# FIX 2026-03-24 R16: Compteur streak momentum INVERSE par symbole+direction
_MOMENTUM_STREAK: Dict[str, int] = {}  # clé = "SYMBOL_ACTION", valeur = nb blocages consécutifs
_MOMENTUM_STREAK_THRESHOLD = 3  # Après 3 INVERSE consécutifs, bloquer aussi "net neutre"
```

#### 2b — Incrémenter/reset le streak dans le filtre momentum

Dans le filtre momentum (lignes ~2729-2787 dans `execute_trade`), modifier :

**Quand un trade est BLOQUÉ (momentum INVERSE)** — après `_momentum_ok = False` :
```python
                                _streak_key = f"{symbol}_{action}"
                                _MOMENTUM_STREAK[_streak_key] = _MOMENTUM_STREAK.get(_streak_key, 0) + 1
                                logger.warning(
                                    f"[MOMENTUM_CHECK] {symbol} {action}: momentum INVERSE "
                                    f"({_confirm_ratio*100:.0f}% confirm, net={_net_move:.5f}). "
                                    f"Trade BLOQUÉ — streak={_MOMENTUM_STREAK[_streak_key]}"
                                )
```

**Quand un trade est "net neutre → PASS"** — ajouter la vérification streak AVANT le PASS :
```python
                        else:
                            # FIX R16: Vérifier le streak avant de PASS
                            _streak_key = f"{symbol}_{action}"
                            _streak_count = _MOMENTUM_STREAK.get(_streak_key, 0)
                            if _streak_count >= _MOMENTUM_STREAK_THRESHOLD:
                                logger.warning(
                                    f"[MOMENTUM_CHECK] {symbol} {action}: momentum faible "
                                    f"({_confirm_ratio*100:.0f}% confirm) — BLOQUÉ car "
                                    f"streak={_streak_count} INVERSE consécutifs"
                                )
                                _momentum_ok = False
                            else:
                                logger.info(
                                    f"[MOMENTUM_CHECK] {symbol} {action}: momentum faible "
                                    f"({_confirm_ratio*100:.0f}% confirm) mais net neutre — PASS"
                                )
```

**Quand un trade PASSE (momentum OK)** — reset le streak :
```python
                    else:
                        _streak_key = f"{symbol}_{action}"
                        _MOMENTUM_STREAK[_streak_key] = 0  # Reset streak
                        logger.debug(
                            f"[MOMENTUM_CHECK] {symbol} {action}: momentum OK "
                            f"({_confirm_ratio*100:.0f}% confirm)"
                        )
```

### Impact attendu

Le cas XAUUSD du 24 mars : 14 INVERSE → streak=14 → le "net neutre" aurait été bloqué → -$297.50 économisés.

---

## FIX 3 — RISK_CAP alerte faux-positif (cleanup log)

### Problème

Le log d'alerte `_point_val=1.0 (défaut) — risque possiblement sous-estimé` (ligne ~2693) se déclenche pour SP500/NAS100 APRÈS l'override indices, car `_point_val == 1.0` est vrai pour l'override correct.

### Solution

**Fichier** : `orchestrator/orchestrator.py`

À la ligne ~2693, le test `if _point_val == 1.0:` doit exclure les symboles avec override :

Chercher le bloc (vers lignes ~2692-2700) :
```python
                if _point_val == 1.0:
                    logger.warning(
                        f"[RISK_CAP] {symbol}: _point_val=1.0 (défaut) — "
```

Remplacer par :
```python
                # FIX R16: Exclure les indices avec override (1.0 est correct pour eux)
                _indices_override_symbols = {"SP500", "SP500#1", "NAS100", "NAS100#1", "DJ30", "DJ30#1", "GER40", "GER40#1", "UK100", "UK100#1"}
                if _point_val == 1.0 and symbol.upper() not in _indices_override_symbols:
                    logger.warning(
                        f"[RISK_CAP] {symbol}: _point_val=1.0 (défaut) — "
```

**Alternative** : utiliser le même dict `_indices_point_val` qui est défini dans le bloc override (FIX R15). Si ce dict est accessible ici (même scope), utiliser :
```python
                if _point_val == 1.0 and symbol.upper() not in _indices_point_val:
```

---

## Résumé des 3 fixes

| # | Fix | Fichier(s) | Criticité | Impact estimé |
|---|-----|-----------|-----------|---------------|
| 1 | Anti-Spam ORDER_SEND | `orchestrator/orchestrator.py` | ⭐⭐⭐ CRITIQUE | Élimine 67 ordres spam/3h, empêche fills multiples |
| 2 | Momentum Anti-Streak | `orchestrator/orchestrator.py` | ⭐⭐ IMPORTANT | Bloque "net neutre" après N INVERSE → -$297 économisés |
| 3 | RISK_CAP log cleanup | `orchestrator/orchestrator.py` | MINEUR | Supprime faux-positif log SP500/NAS100 |

## Vérification

```bash
python -m py_compile orchestrator/orchestrator.py
```

## Vérification en production

### Test immédiat :

1. **[ANTI_SPAM]** dans les logs :
   - `position(s) déjà ouverte(s) → pas de nouvel ordre` → guard actif
   - Compter les occurrences. Si > 0, le fix fonctionne.

2. **ORDER_SEND SP500** :
   - Compter les ORDER_SEND pour SP500 sur 1 heure
   - Cible : ≤ 5 (max_trades_per_hour), pas 67

3. **[MOMENTUM_CHECK]** avec streak :
   - `streak=N INVERSE consécutifs` → compteur visible
   - `BLOQUÉ car streak=N` → net neutre bloqué après streak

### Test après une journée :

4. **Nombre total d'ORDER_SEND** : doit être < 30 (était 67+)
5. **Hit rate** : cible > 35% (les "faux PASS" momentum éliminés)
6. **Aucun fill multiple** : 0 positions doublons par symbole

## RÈGLES

1. **Le FIX 1 (anti-spam) est la PRIORITÉ ABSOLUE.** C'est un risque financier direct (fills multiples).
2. **Le fix le plus important du FIX 1 est le `self._last_proposal = None`** après consommation. C'est la racine du problème.
3. **Ne casse pas les méthodes existantes.** Chaque fix est un ajout.
4. **Compile le fichier.**
5. **Les fixes R15 sont DÉJÀ EN PLACE et FONCTIONNELS** — ne pas les modifier ou casser :
   - MOMENTUM_CHECK (lignes ~2729-2787)
   - RISK_CAP override indices (après ligne ~2690)
   - Anti-QUICK_REVERSAL cooldown (lignes ~2023-2033)
   - HARD_FILTER .4f (ligne ~2143)
   - [DECISION] log (après ligne ~3497)
   - `_regime_label` fix (ligne 5080)
6. **`_last_exec_ts` doit être mis à jour même quand ORDER_SEND échoue** pour que le gate anti-spam fonctionne.
7. **Le guard anti-spam (position déjà ouverte) utilise `_mt5.positions_get()`** qui nécessite le lock COM. Comme `execute_trade` est DÉJÀ appelé dans `async with _GLOBAL_MT5_SEMAPHORE` (ligne ~4052), le lock est déjà acquis. **NE PAS** ajouter un deuxième `async with _GLOBAL_MT5_SEMAPHORE` dans `execute_trade` car ça causerait un deadlock. L'appel `_mt5.positions_get()` dans `execute_trade` est safe car le sémaphore est déjà détenu par le thread appelant.
