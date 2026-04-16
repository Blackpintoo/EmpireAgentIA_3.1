# PROMPT CLAUDE CODE — Fix Opérationnel (Round 8)

## Contexte

Après 2 jours de trading réel (11-12 mars 2026), l'infrastructure est stable (0 freeze, 0 traceback), mais 3 problèmes opérationnels empêchent le bot d'être rentable :

1. **Kill switch trop sensible** — se déclenche sur le floating PnL en <1h, bloquant tout pour le reste de la journée
2. **SP500 TP absurde** — TP à 1 point de l'entrée avec SL à 102 points (R:R = 0.01)
3. **Trade outcomes non enregistrés** — `trade_outcomes.csv` vide malgré 10 trades en 2 jours

---

## FIX 1 — Kill Switch : séparer floating et realized

### Problème
Le kill switch à la ligne ~3076 additionne realized + floating : `total_pnl = realized + floating_pnl`. Avec 3-5 positions SHORT simultanées dans un marché haussier, le floating dépasse -$400 en minutes. Le bot ne trade qu'1 heure par jour.

### Solution
Appliquer des seuils séparés : -$400 pour le realized (pertes confirmées), -$800 pour le floating (laisser les positions respirer).

**Fichier** : `utils/risk_manager.py`

**Étape 1a** — Modifier le constructeur `GlobalKillSwitch.__init__` (ligne ~94) :

Chercher :
```python
    def __init__(self, limit_usd: float = 400.0):
        self.limit_usd = abs(limit_usd) if limit_usd else 400.0
```

Remplacer par :
```python
    def __init__(self, limit_usd: float = 400.0, floating_limit_usd: float = 0.0):
        self.limit_usd = abs(limit_usd) if limit_usd else 400.0
        # FIX 2026-03-12 R8: Seuil séparé pour le floating (0 = désactivé, utilise 2x realized)
        self.floating_limit_usd = abs(floating_limit_usd) if floating_limit_usd else (self.limit_usd * 2.0)
```

**Étape 1b** — Modifier `check_kill_switch` (ligne ~141) :

Chercher :
```python
    def check_kill_switch(self, floating_pnl: float = 0.0) -> Tuple[bool, str]:
        """
        Vérifie si le kill switch doit être activé.

        Args:
            floating_pnl: P&L flottant actuel (positions ouvertes)

        Returns:
            Tuple[blocked, reason]
        """
        self._check_day_reset()

        # Si déjà déclenché aujourd'hui
        if self._state.get("kill_switch_triggered", False):
            return True, "GLOBAL_DAILY_LOSS_LIMIT (already triggered)"

        realized = float(self._state.get("realized_pnl", 0.0))
        total_pnl = realized + float(floating_pnl)

        if total_pnl <= -self.limit_usd:
            self._state["kill_switch_triggered"] = True
            self._state["trigger_time"] = datetime.now(timezone.utc).isoformat()
            self._save_state()

            msg = (f"GLOBAL_DAILY_LOSS_LIMIT: total_pnl={total_pnl:.2f} "
                   f"(realized={realized:.2f} + floating={floating_pnl:.2f}) "
                   f"<= -${self.limit_usd:.0f}")
            logger.warning(f"[KILL_SWITCH] {msg}")
            _log_guard(f"KILL_SWITCH_TRIGGERED: {msg}")
            return True, "GLOBAL_DAILY_LOSS_LIMIT"

        return False, ""
```

Remplacer par :
```python
    def check_kill_switch(self, floating_pnl: float = 0.0) -> Tuple[bool, str]:
        """
        Vérifie si le kill switch doit être activé.
        FIX 2026-03-12 R8: Seuils séparés realized vs floating.

        Args:
            floating_pnl: P&L flottant actuel (positions ouvertes)

        Returns:
            Tuple[blocked, reason]
        """
        self._check_day_reset()

        # Si déjà déclenché aujourd'hui
        if self._state.get("kill_switch_triggered", False):
            return True, "GLOBAL_DAILY_LOSS_LIMIT (already triggered)"

        realized = float(self._state.get("realized_pnl", 0.0))
        floating = float(floating_pnl)
        total_pnl = realized + floating

        # FIX 2026-03-12 R8: Seuil 1 — realized seul (pertes confirmées)
        if realized <= -self.limit_usd:
            self._state["kill_switch_triggered"] = True
            self._state["trigger_time"] = datetime.now(timezone.utc).isoformat()
            self._state["trigger_type"] = "realized"
            self._save_state()
            msg = (f"DAILY_REALIZED_LIMIT: realized={realized:.2f} <= -${self.limit_usd:.0f}")
            logger.warning(f"[KILL_SWITCH] {msg}")
            _log_guard(f"KILL_SWITCH_TRIGGERED: {msg}")
            return True, "DAILY_REALIZED_LIMIT"

        # FIX 2026-03-12 R8: Seuil 2 — floating (laisser respirer les positions)
        if total_pnl <= -self.floating_limit_usd:
            self._state["kill_switch_triggered"] = True
            self._state["trigger_time"] = datetime.now(timezone.utc).isoformat()
            self._state["trigger_type"] = "floating"
            self._save_state()
            msg = (f"DAILY_FLOATING_LIMIT: total={total_pnl:.2f} "
                   f"(realized={realized:.2f} + floating={floating:.2f}) "
                   f"<= -${self.floating_limit_usd:.0f}")
            logger.warning(f"[KILL_SWITCH] {msg}")
            _log_guard(f"KILL_SWITCH_TRIGGERED: {msg}")
            return True, "DAILY_FLOATING_LIMIT"

        return False, ""
```

**Étape 1c** — Modifier `get_global_kill_switch` (ligne ~189) pour accepter le floating_limit :

Chercher :
```python
def get_global_kill_switch(limit_usd: float = 400.0) -> GlobalKillSwitch:
    """Récupère ou crée l'instance globale du kill switch."""
    global _global_kill_switch
    if _global_kill_switch is None:
        _global_kill_switch = GlobalKillSwitch(limit_usd)
    return _global_kill_switch
```

Remplacer par :
```python
def get_global_kill_switch(limit_usd: float = 400.0, floating_limit_usd: float = 0.0) -> GlobalKillSwitch:
    """Récupère ou crée l'instance globale du kill switch."""
    global _global_kill_switch
    if _global_kill_switch is None:
        _global_kill_switch = GlobalKillSwitch(limit_usd, floating_limit_usd)
    return _global_kill_switch
```

**Résultat** : Le kill switch ne se déclenche plus sur -$400 de floating. Il faut -$400 de realized OU -$800 de total (realized + floating). Les positions ont le temps de respirer.

---

## FIX 2 — Garde-fou R:R dans execute_trade (filet de sécurité)

### Problème
Le SP500 a été exécuté avec TP = 6717.52 (1 point de l'entrée) et SL = 6820.77 (102 points). Le R:R fix dans `_run_agents_and_decide` (ligne ~3485) DEVRAIT corriger ça, mais le trade est passé avec un R:R de 0.01. Le fix a probablement échoué silencieusement (exception catchée dans le try/except) ou les valeurs de la proposition ont été recalculées après le fix.

### Solution
Ajouter un **dernier filet de sécurité** directement dans `execute_trade`, JUSTE AVANT l'appel `place_order`. Si le R:R est < min_rr, recalculer le TP ou rejeter le trade.

**Fichier** : `orchestrator/orchestrator.py`

Chercher dans `execute_trade`, juste avant l'appel `self.mt5.place_order` (typiquement ligne ~2540-2545). Il y a probablement un bloc qui prépare le dict `order_params` ou appelle directement `place_order`. Chercher :

```python
        # --- Envoi ordre ---
```

ou chercher la ligne contenant `place_order` dans `execute_trade` :

```python
                result = self.mt5.place_order(
```

Insérer **AVANT** cet appel (au même niveau d'indentation) :

```python
                # FIX 2026-03-12 R8: Dernier garde-fou R:R avant order_send
                # Empêche les trades avec un R:R absurde (<0.50) qui passent à travers les filtres
                try:
                    _final_rr_min = max(0.50, float(getattr(self, '_hf_min_rr', 0.80)))
                    if action == "BUY":
                        _f_risk = abs(entry - sl) if entry > sl else abs(sl - entry)
                        _f_reward = abs(tp - entry) if tp > entry else abs(entry - tp)
                    else:
                        _f_risk = abs(sl - entry) if sl > entry else abs(entry - sl)
                        _f_reward = abs(entry - tp) if entry > tp else abs(tp - entry)
                    _f_rr = _f_reward / max(_f_risk, 1e-9)
                    if _f_rr < _final_rr_min:
                        # Recalculer TP basé sur le SL et le min_rr
                        _f_new_tp_dist = _f_risk * self._hf_min_rr
                        if action == "BUY":
                            tp = entry + _f_new_tp_dist
                        else:
                            tp = entry - _f_new_tp_dist
                        _f_new_rr = _f_new_tp_dist / max(_f_risk, 1e-9)
                        logger.warning(
                            f"[RR_SAFETY] {symbol}: R:R final {_f_rr:.3f} < {_final_rr_min} → "
                            f"TP recalculé {tp:.5f} (R:R={_f_new_rr:.2f})"
                        )
                except Exception as _rr_safety_err:
                    logger.debug(f"[RR_SAFETY] Erreur: {_rr_safety_err}")
```

**Aussi** mettre à jour le payload/proposal qui est envoyé à `place_order` pour utiliser le TP corrigé. Le TP est lu depuis la variable `tp` locale à `execute_trade` — vérifier qu'il est bien passé à `place_order`.

---

## FIX 3 — Trade Outcome Tracker : accès MT5 COM non protégé

### Problème
Le `TradeOutcomeTracker` tourne dans un thread daemon séparé (`trade-outcome-tracker`). Il appelle `mt5.positions_get()` et `mt5.history_deals_get()` directement, **sans le lock hybride `_GLOBAL_MT5_SEMAPHORE`**. Résultat :
- Deadlock COM silencieux avec les threads de l'orchestrateur
- Le thread se bloque, `trade_outcomes.csv` reste vide

### Solution
Importer le lock hybride et protéger les appels MT5 dans le tracker.

**Fichier** : `utils/trade_outcome_tracker.py`

**Étape 3a** — Ajouter l'import du lock (après les imports existants, vers la ligne ~35) :

Ajouter après le bloc d'imports :
```python
# FIX 2026-03-12 R8: Import du lock hybride MT5 pour éviter les deadlocks COM
try:
    from orchestrator.orchestrator import _GLOBAL_MT5_SEMAPHORE
    _HAS_MT5_LOCK = True
except ImportError:
    _GLOBAL_MT5_SEMAPHORE = None
    _HAS_MT5_LOCK = False
```

**Étape 3b** — Créer un helper pour les appels MT5 protégés. Ajouter après la fonction `_get_point_value` (vers la ligne ~180) :

```python
def _mt5_call_safe(func, *args, **kwargs):
    """Appelle une fonction MT5 en acquérant le lock hybride si disponible."""
    if _HAS_MT5_LOCK and _GLOBAL_MT5_SEMAPHORE is not None:
        with _GLOBAL_MT5_SEMAPHORE:
            return func(*args, **kwargs)
    return func(*args, **kwargs)
```

**Étape 3c** — Protéger `_get_open_positions`. Chercher dans la classe `TradeOutcomeTracker` la méthode `_get_open_positions`. Elle contient probablement :

```python
        positions = mt5.positions_get()
```

Remplacer par :
```python
        # FIX 2026-03-12 R8: Protéger l'appel MT5 avec le lock hybride
        positions = _mt5_call_safe(mt5.positions_get)
```

**Étape 3d** — Protéger `_get_recent_deals`. Chercher `mt5.history_deals_get` dans cette même classe :

```python
            deals = mt5.history_deals_get(start, end)
```

Remplacer par :
```python
            # FIX 2026-03-12 R8: Protéger l'appel MT5 avec le lock hybride
            deals = _mt5_call_safe(mt5.history_deals_get, start, end)
```

**Étape 3e** — Protéger tout autre appel `mt5.` dans le fichier. Faire un grep sur `mt5.` dans `trade_outcome_tracker.py` et remplacer chaque appel direct par `_mt5_call_safe(mt5.xxx, args)`. Les appels typiques à protéger :
- `mt5.positions_get()`
- `mt5.history_deals_get(start, end)`
- `mt5.symbol_info(symbol)` (dans `_get_point_value`)

**NOTE IMPORTANTE** : S'il y a un risque d'import circulaire (orchestrator importe trade_outcome_tracker ET trade_outcome_tracker importe orchestrator), utiliser un import lazy à l'intérieur de `_mt5_call_safe` :

```python
def _mt5_call_safe(func, *args, **kwargs):
    """Appelle une fonction MT5 en acquérant le lock hybride si disponible."""
    try:
        from orchestrator.orchestrator import _GLOBAL_MT5_SEMAPHORE
        with _GLOBAL_MT5_SEMAPHORE:
            return func(*args, **kwargs)
    except ImportError:
        return func(*args, **kwargs)
```

---

## Résumé des 3 fixes

| Fix | Fichier | Impact |
|-----|---------|--------|
| 1 | `utils/risk_manager.py` | Kill switch: realized -$400, floating -$800 (2x) |
| 2 | `orchestrator/orchestrator.py` | Garde-fou R:R dans execute_trade avant order_send |
| 3 | `utils/trade_outcome_tracker.py` | Lock MT5 COM → trade_outcomes.csv se remplit enfin |

## Vérification après modification

```bash
python -m py_compile utils/risk_manager.py
python -m py_compile orchestrator/orchestrator.py
python -m py_compile utils/trade_outcome_tracker.py
```

## Vérification en production (après 1h de trading)

1. **Kill switch** : le bot ne s'arrête plus après 1h. Chercher `[KILL_SWITCH]` dans les logs — il ne devrait se déclencher que si le realized atteint -$400 ou le total -$800.
2. **R:R** : chercher `[RR_SAFETY]` dans les logs. Si ce message apparaît, c'est que le filet de sécurité a recalculé un TP. Vérifier que le TP dans les trades est raisonnable (pas à 1 point de l'entrée).
3. **Outcome tracker** : chercher `[OUTCOME]` dans les logs. Vérifier que `data/trade_outcomes.csv` contient des entrées.
