# PROMPT CLAUDE CODE — Fix Deadlock COM : Lock Hybride async+thread (Round 5)

## Contexte

Les 8 protections sémaphore du Round 4 sérialisent correctement les appels MT5 entre coroutines asyncio. Mais le **Position Manager** et le **sync_history_job** tournent dans des threads APScheduler (BackgroundScheduler) et font des appels MT5 COM **sans aucune protection** car `asyncio.Semaphore` est invisible pour les threads normaux.

**Résultat** : Deadlock COM à 18:02:48 le 10/03/2026 — le PM (thread scheduler) appelle `_mt5.positions_get()` pendant que `execute_trade` (thread asyncio.to_thread, protégé par le sémaphore) appelle `_mt5.account_info()`.

## Solution : Lock hybride `_MT5Lock`

Remplacer `asyncio.Semaphore(1)` par un objet qui supporte **les deux modes** :
- `async with _GLOBAL_MT5_SEMAPHORE:` → coroutines (event loop non bloqué)
- `with _GLOBAL_MT5_SEMAPHORE:` → threads scheduler (blocking classique)

Les deux modes partagent le **même `threading.Lock()`** sous-jacent → exclusion mutuelle totale.

---

## Modifications à appliquer (3 fixes)

### FIX 1 — Remplacer la déclaration du sémaphore par le lock hybride

**Fichier** : `orchestrator/orchestrator.py`

Chercher (lignes ~610-617) :
```python
# ================================================================
# FIX 2026-03-08: Verrou GLOBAL inter-orchestrateurs pour MT5 COM
# Le COM MT5 est mono-thread : un seul orchestrateur peut l'utiliser à la fois
# asyncio.Semaphore(1) = un seul coroutine à la fois, les autres await sans bloquer
# Doit être au niveau MODULE (pas classe) pour être accessible dans les méthodes
# ================================================================
import asyncio as _aio_mod
_GLOBAL_MT5_SEMAPHORE = _aio_mod.Semaphore(1)
```

Remplacer par :
```python
# ================================================================
# FIX 2026-03-10: Lock HYBRIDE inter-orchestrateurs + Position Manager pour MT5 COM
# Le COM MT5 est mono-thread : un seul thread peut l'utiliser à la fois
# _MT5Lock supporte:
#   - async with (coroutines asyncio) → attend sans bloquer l'event loop
#   - with (threads BackgroundScheduler) → blocking classique
# Les deux partagent le même threading.Lock() → exclusion mutuelle totale
# Doit être au niveau MODULE (pas classe) pour être accessible partout
# ================================================================
import asyncio as _aio_mod
import threading as _threading_mod


class _MT5Lock:
    """Lock hybride pour MT5 COM — fonctionne en async (coroutines) et sync (threads)."""

    def __init__(self):
        self._lock = _threading_mod.Lock()

    # --- Mode sync (BackgroundScheduler threads: PM, sync_history) ---
    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *args):
        self._lock.release()

    # --- Mode async (coroutines asyncio: _run_agents_and_decide, execute_trade) ---
    async def __aenter__(self):
        loop = _aio_mod.get_event_loop()
        # Attendre le lock dans un thread executor → ne bloque PAS l'event loop
        await loop.run_in_executor(None, self._lock.acquire)
        return self

    async def __aexit__(self, *args):
        self._lock.release()


_GLOBAL_MT5_SEMAPHORE = _MT5Lock()
```

**Note importante** : Le nom `_GLOBAL_MT5_SEMAPHORE` est conservé volontairement pour ne PAS avoir à modifier les 9 points d'acquisition `async with _GLOBAL_MT5_SEMAPHORE:` dans le code. Ils continuent à fonctionner car `_MT5Lock` supporte `async with`.

### FIX 2 — Protéger le Position Manager avec le lock

**Fichier** : `orchestrator/orchestrator.py`

Chercher (lignes ~2718-2728) :
```python
        # Gestion des positions ouvertes (BE/partials/trailing)
        pm_secs = int((self.profile.get("position_manager") or {}).get("interval_secs", 20))
        try:
            if self.pm and hasattr(self.pm, "manage_open_positions"):
                self.scheduler.add_job(
                    self.pm.manage_open_positions,
                    "interval",
                    seconds=pm_secs,
                    id=f"pm_{self.symbol}",
                    replace_existing=True,
                )
        except Exception as e:
            logger.warning(f"[PM] schedule fail: {e}")
```

Remplacer par :
```python
        # Gestion des positions ouvertes (BE/partials/trailing)
        pm_secs = int((self.profile.get("position_manager") or {}).get("interval_secs", 20))
        try:
            if self.pm and hasattr(self.pm, "manage_open_positions"):
                # FIX 2026-03-10: Wrapper le PM avec le lock hybride MT5
                # Le PM tourne dans un thread APScheduler et fait des appels MT5 COM
                # Sans le lock, il entre en conflit avec les coroutines asyncio → deadlock
                _pm_ref = self.pm

                def _pm_with_mt5_lock():
                    with _GLOBAL_MT5_SEMAPHORE:
                        _pm_ref.manage_open_positions()

                self.scheduler.add_job(
                    _pm_with_mt5_lock,
                    "interval",
                    seconds=pm_secs,
                    id=f"pm_{self.symbol}",
                    replace_existing=True,
                )
        except Exception as e:
            logger.warning(f"[PM] schedule fail: {e}")
```

### FIX 3 — Protéger `_sync_history_job` avec le lock

**Fichier** : `orchestrator/orchestrator.py`

Chercher la méthode `_sync_history_job` (ligne ~5097) :
```python
    def _sync_history_job(self):
        """
        Synchronise l'historique des deals MT5 vers data/deals_history.csv
        Appelé automatiquement toutes les 5 minutes.
        """
        try:
            import csv
            from datetime import timedelta

            if _mt5 is None:
                return
```

Remplacer par :
```python
    def _sync_history_job(self):
        """
        Synchronise l'historique des deals MT5 vers data/deals_history.csv
        Appelé automatiquement toutes les 5 minutes.
        """
        try:
            import csv
            from datetime import timedelta

            if _mt5 is None:
                return

            # FIX 2026-03-10: Acquérir le lock MT5 pour éviter le deadlock COM
            # _sync_history_job tourne dans un thread APScheduler, pas dans l'event loop
```

Et envelopper TOUT le reste du corps de la méthode (de `end = datetime.now(...)` jusqu'à la fin du `try`) dans `with _GLOBAL_MT5_SEMAPHORE:`.

La méthode complète doit ressembler à :
```python
    def _sync_history_job(self):
        """
        Synchronise l'historique des deals MT5 vers data/deals_history.csv
        Appelé automatiquement toutes les 5 minutes.
        """
        try:
            import csv
            from datetime import timedelta

            if _mt5 is None:
                return

            # FIX 2026-03-10: Acquérir le lock MT5 pour éviter le deadlock COM
            with _GLOBAL_MT5_SEMAPHORE:
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=1)
                deals = _mt5.history_deals_get(start, end) or []

                if not deals:
                    return

                # ... (tout le reste du code existant, indenté d'un niveau supplémentaire)
```

**ATTENTION** : Tout le code après `if _mt5 is None: return` et avant le `except` final doit être indenté d'un niveau supplémentaire (4 espaces de plus) pour être dans le bloc `with _GLOBAL_MT5_SEMAPHORE:`.

---

## Résumé des 3 modifications

| Fix | Lignes | Modification |
|-----|--------|-------------|
| 1 | ~610-617 | `asyncio.Semaphore(1)` → classe `_MT5Lock` (async+sync hybride) |
| 2 | ~2718-2728 | PM wrappé dans `with _GLOBAL_MT5_SEMAPHORE:` via closure |
| 3 | ~5097+ | `_sync_history_job` wrappé dans `with _GLOBAL_MT5_SEMAPHORE:` |

## Ce qui ne change PAS

- Les 9 `async with _GLOBAL_MT5_SEMAPHORE:` existants (Round 4) → fonctionnent inchangés car `_MT5Lock` supporte `async with`
- L'API du sémaphore est identique → 0 risque de régression
- Le BackgroundScheduler continue à lancer PM et sync_history dans ses threads → mais maintenant ils respectent le lock

## Impact attendu

- **0 deadlock COM** : TOUS les accès MT5 (coroutines + threads scheduler) sont sérialisés par le même `threading.Lock()`
- **Event loop ne gèle plus** : les coroutines `await` le lock via `run_in_executor` (non-bloquant)
- **PM continue toutes les 20s** : il attend juste le lock si un agent MT5 tourne (~2-5s max)
- **Les trades s'exécutent enfin** : `execute_trade` n'entre plus en conflit avec le PM

## Vérification après modification

1. `python -m py_compile orchestrator/orchestrator.py` → doit passer
2. Redémarrer via `START_EMPIRE.bat`
3. Vérifier dans les logs après **30 minutes** :
   - PM_DIAG tourne toutes les 20s (cycles réguliers, pas de freeze)
   - Les cycles d'analyse tournent toutes les ~120s SANS interruption
   - HARD_FILTER PASS suivi de `[TRADE]` ou `[EXECUTE]` (trade exécuté !)
   - Pas de freeze silencieux (les deux types de logs coexistent)
